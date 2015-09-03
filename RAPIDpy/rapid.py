# -*- coding: utf-8 -*-
from csv import writer as csvwriter
import datetime
from dateutil.parser import parse
from dateutil.tz import tzoffset
from multiprocessing import cpu_count
from netCDF4 import Dataset
import numpy as np
import os
from pytz import utc
from requests import get
from subprocess import Popen, PIPE

#local
from helper_functions import csv_to_list
from make_CF_RAPID_output import ConvertRAPIDOutputToCF

#------------------------------------------------------------------------------
#Main Dataset Manager Class
#------------------------------------------------------------------------------
class RAPID(object):
    """
    This class is designed to prepare the rapid_namelist file and run 
    the RAPID program.
    """
    def __init__(self, rapid_executable_location, num_processors=1, 
                 use_all_processors=False, **kwargs):
        """
        Initialize the class with variables given by the user
        """
        self._rapid_executable_location = rapid_executable_location
        self._num_processors = num_processors
        #use all processors akes precedent over num_processors arg
        if use_all_processors == True:
            self._num_processors = cpu_count()
            
        #*******************************************************************************
        #Runtime options 
        #*******************************************************************************
        self.BS_opt_Qinit = False
        #!.false. --> no read initial flow    .true. --> read initial flow
        self.BS_opt_Qfinal = False
        #!.false. --> no write final flow     .true. --> write final flow 
        self.BS_opt_dam = False
        #!.false. --> no dam model used       .true. --> dam model used
        self.BS_opt_for = False
        #!.false. --> no forcing              .true. --> forcing
        self.BS_opt_influence = False
        #!.false. --> no output influence     .true. --> output influence
        self.IS_opt_routing = 1
        #!1       --> matrix-based Muskingum  2      --> traditional Muskingum
        #!3       --> Transbnd. matrix-based
        self.IS_opt_run = 1
        #!1       --> regular run             2      --> parameter optimization
        self.IS_opt_phi = 1
        #!1       --> phi1                    2      --> phi2
        
        #*******************************************************************************
        #Temporal information
        #*******************************************************************************
        #NOTE: ALL TIME IN SECONDS!
        #ALWAYS USED
        self.ZS_TauR = 0 #duration of routing procedure (time step of runoff data)
        self.ZS_dtR = 0 #internal routing time step
        #ONLY FOR REGULAR RUN
        self.ZS_TauM = 0 #total simulation time 
        self.ZS_dtM = 0 #input time step 
        #ONLY FOR OPTIMIZATION RUN
        self.ZS_TauO = 0 #total optimization time  
        self.ZS_dtO = 0 #observation time step
        #FORCING MODE (replace some values with observations) 
        self.ZS_dtF = 0 #time step of forcing data
        
        #*******************************************************************************
        #Domain in which input data is available
        #*******************************************************************************
        self.IS_riv_tot = 0 #number of river reaches in rapid connect file
        self.rapid_connect_file = '' #path to rapid_connect file
        self.IS_max_up = 2 #maximum number of ustream segments
        self.Vlat_file = '' #path to runoff file
        
        #*******************************************************************************
        #Domain in which model runs
        #*******************************************************************************
        self.IS_riv_bas = 0 #number of river reaches in subbasin
        self.riv_bas_id_file = '' #subbasin reach id file
        
        #*******************************************************************************
        #Initial instantaneous flow file
        #*******************************************************************************
        self.Qinit_file = '' #initial flow file (same order as rapid_connect)
        
        #*******************************************************************************
        #Final instantaneous flow file
        #*******************************************************************************
        self.Qfinal_file = '' #path to output final flow file
        
        #*******************************************************************************
        #Available dam data
        #*******************************************************************************
        self.IS_dam_tot = 0 #number of dams
        self.dam_tot_id_file = '' #ids of dam location
        
        #*******************************************************************************
        #Dam data used
        #*******************************************************************************
        self.IS_dam_use = 0 #number in subset of dam data to use
        self.dam_use_id_file = '' #ids of subset of dams
        
        #*******************************************************************************
        #Available forcing data
        #*******************************************************************************
        self.IS_for_tot = 0
        self.for_tot_id_file = ''
        self.Qfor_file = ''
        
        #*******************************************************************************
        #Forcing data used as model runs
        #*******************************************************************************
        self.IS_for_use = 0
        self.for_use_id_file = ''
        
        #*******************************************************************************
        #File where max (min) of absolute values of b (QoutR) are stored
        #*******************************************************************************
        self.babsmax_file = ''
        self.QoutRabsmin_file = ''
        self.QoutRabsmax_file = ''
        
        #*******************************************************************************
        #Regular model run
        #*******************************************************************************
        self.k_file = ''
        self.x_file = ''
        self.Qout_file = ''
        
        #*******************************************************************************
        #Optimization
        #*******************************************************************************
        self.ZS_phifac = 0
        #------------------------------------------------------------------------------
        #Routing parameters
        #------------------------------------------------------------------------------
        self.kfac_file = ''
        self.xfac_file = '' 
        self.ZS_knorm_init = 0
        self.ZS_xnorm_init = 0
        #------------------------------------------------------------------------------
        #Gage observations
        #------------------------------------------------------------------------------
        self.IS_obs_tot = 0
        self.obs_tot_id_file = ''
        self.Qobs_file = ''
        self.Qobsbarrec_file = ''
        self.IS_obs_use = 0
        self.obs_use_id_file = ''
        self.IS_strt_opt = 0
        
        
        
        self.update_parameters(**kwargs)
        

    def update_parameters(self, **kwargs):
        """
        Update AutoRoute parameters
        """
        #set arguments based off of user input
        for key, value in kwargs.iteritems():
            if key in dir(self) and not key.startswith('_'):
                setattr(self, key, value)
            else:
                raise Exception("Invalid RAPID parameter %s." % key)
    
    def update_reach_number_data(self):
        """
        Updates the reach number data based on input files
        """
        #get rapid connect info
        rapid_connect_table = csv_to_list(self.rapid_connect_file)
        self.IS_riv_tot = len(rapid_connect_table)
        self.IS_max_up = max([int(float(row[2])) for row in rapid_connect_table])
    
        #get riv_bas_id info
        riv_bas_id_table = csv_to_list(self.riv_bas_id_file)
        self.IS_riv_bas = len(riv_bas_id_table)


    def generate_namelist_file(self, file_path):
        """
        Generate rapid_namelist file
        """
        print "Generating RAPID namelist file ..."
        try:
            os.remove(file_path)
        except OSError:
            pass
        
        with open(file_path,'w') as new_file:
            new_file.write('&NL_namelist\n')
            for attr, value in self.__dict__.iteritems():
                if not attr.startswith('_'):
                    if attr.startswith('BS'):
                        new_file.write("%s = .%s.\n" % (attr, str(value).lower()))
                    elif isinstance(value, int):
                        new_file.write("%s = %s\n" % (attr, value))
                    else:
                        new_file.write("%s = \'%s\'\n" % (attr, value))
            new_file.write("/\n")
        
    def update_namelist_file(self, file_path):
        """
        Update existing namelist file with new parameters
        """
        if os.path.exists(file_path) and file_path:
            print "Adding missing inputs from RAPID input file ..."
            old_file = open(file_path, 'r')
            for line in old_file:
                line = line.strip()
                if not line[:1].isalpha() or not line:
                    continue
                line_split = line.split()
                attr = line_split[0]
                value = None
                if len(line_split)>1:
                    value = line_split[1]
                elif attr in self._no_value_attr_list:
                    value = True
                #add attribute if exists
                if attr in dir(self) \
                    and not attr.startswith('_'):
                    #set attribute if not set already
                    if not getattr(self, attr):
                        setattr(self, attr, value)
                else:
                    print "Invalid argument" , attr, ". Skipping ..."
            old_file.close()
            
            self.generate_input_file(file_path)
        else:
            raise Exception("RAPID namelist file to update not found.")
            
    def make_output_CF_compliant(self, 
                                 simulation_start_datetime,
                                 comid_lat_lon_z_file="",
                                 project_name="Normal RAPID project"):
        """
        Converts RAPID output to be CF compliant
        """
        cv = ConvertRAPIDOutputToCF(rapid_output_file=self.Qout_file, #location of timeseries output file
                                    start_datetime=simulation_start_datetime, #time of the start of the simulation time
                                    time_step=self.ZS_TauR, #time step of simulation in seconds
                                    qinit_file=self.Qinit_file, #RAPID qinit file
                                    comid_lat_lon_z_file=comid_lat_lon_z_file, #path to comid_lat_lon_z file
                                    rapid_connect_file=self.rapid_connect_file, #path to RAPID connect file
                                    project_name=project_name, #name of your project
                                    output_id_dim_name='COMID', #name of ID dimension in output file, typically COMID or FEATUREID
                                    output_flow_var_name='Qout', #name of streamflow variable in output file, typically Qout or m3_riv
                                    print_debug=False)
        cv.convert()
        
        
    def run(self, rapid_namelist_file=""):
        """
        Run RAPID program and generate file based on inputs
        """
    
        time_start = datetime.datetime.utcnow()
    
        if not rapid_namelist_file or not os.path.exists(rapid_namelist_file):
            #generate input file if it does not exist
            if not rapid_namelist_file:
                rapid_namelist_file = os.path.join(os.getcwd(), "rapid_namelist")
            self.generate_namelist_file(rapid_namelist_file)
        else:
            #update existing file
            self.update_namelist_file(rapid_namelist_file)

        local_rapid_executable_location = os.path.join(os.path.dirname(rapid_namelist_file), "rapid")

        #create link to RAPID if needed
        temp_link_to_rapid = ""
        if not os.path.exists(local_rapid_executable_location) \
            and not self._rapid_executable_location == local_rapid_executable_location:
            os.symlink(self._rapid_executable_location, local_rapid_executable_location)
            temp_link_to_rapid = local_rapid_executable_location

        def rapid_cleanup(local_rapid_executable, rapid_namelist_file):
            """
            Cleans up the rapid files generated by the process
            """
            #remove rapid link
            try:
                os.unlink(local_rapid_executable)
                os.remove(local_rapid_executable)
            except OSError:
                pass
    
            #remove namelist file
            try:
                os.remove(rapid_namelist_file)
            except OSError:
                pass
        
        #run RAPID
        print "Running RAPID ..."
        run_rapid_command = []
        if self._num_processors > 1:
            run_rapid_command = ["mpiexec", "-n", str(self._num_processors)]
        run_rapid_command.append(local_rapid_executable_location)
        run_rapid_command.append("-ksp_type")
        run_rapid_command.append("richardson")
        
        process = Popen(run_rapid_command, 
                        stdout=PIPE, stderr=PIPE, shell=False)
        out, err = process.communicate()
        if err:
            print err
            rapid_cleanup(temp_link_to_rapid, rapid_namelist_file)
            raise
        else:
            print 'RAPID output:'
            for line in out.split('\n'):
                print line

        rapid_cleanup(temp_link_to_rapid, rapid_namelist_file)
        print "Time to run RAPID: %s" % (datetime.datetime.utcnow()-time_start)

    def generate_qinit_from_past_qout(self, qinit_file):
        """
        Generate qinit from qout file
        """
        print "Generating qinit file from qout file ..."
        print "Extracting data ..."
        #get information from datasets
        data_nc = Dataset(self.Qout_file, mode="r")
        riv_bas_id_array = data_nc.variables['COMID'][:]
        qout_dimensions = data_nc.variables['Qout'].dimensions
        if qout_dimensions[0].lower() == 'time' and qout_dimensions[1].lower() == 'comid':
            #data is raw rapid output
            data_values = data_nc.variables['Qout'][-1,:]
        elif qout_dimensions[1].lower() == 'time' and qout_dimensions[0].lower() == 'comid':
            #the data is CF compliant and has time=0 added to output
            data_values = data_nc.variables['Qout'][:,-1]
        else:
            data_nc.close()
            raise Exception( "Invalid ECMWF forecast file %s" % self.Qout_file)
        data_nc.close()
    
        print "Reordering data..."
        rapid_connect_array = csv_to_list(self.rapid_connect_file)
        stream_id_array = np.array([int(float(row[0])) for row in rapid_connect_array])
        init_flows_array = np.zeros(len(rapid_connect_array))
        for riv_bas_index, riv_bas_id in enumerate(riv_bas_id_array):
            try:
                data_index = np.where(stream_id_array==riv_bas_id)[0][0]
                init_flows_array[data_index] = data_values[riv_bas_index]
            except Exception:
                raise Exception ('riv bas id %s not found in connectivity list.' % riv_bas_id)
        
        print "Writing to file ..."
        with open(qinit_file, 'wb') as qinit_out:
            for init_flow in init_flows_array:
                qinit_out.write('{}\n'.format(init_flow))

        self.Qinit_file = qinit_file
        self.BS_opt_Qinit = True
        print "Initialization Complete!"

    def generate_usgs_avg_daily_flows_opt(self, reach_id_gage_id_file,
                                          start_datetime, end_datetime,
                                          out_streamflow_file, out_stream_id_file):
        """
        Generate streamflow file and stream id file required for optimization 
        based on usgs gage ids associated with stream ids
        """
        print "Generating avg streamflow file and stream id file required for optimization ..."
        reach_id_gage_id_list = csv_to_list(reach_id_gage_id_file) 
        if start_datetime.tzinfo is None or start_datetime.tzinfo.utcoffset(start_datetime) is None:
            start_datetime.replace(tzinfo=utc)
        if end_datetime.tzinfo is None or end_datetime.tzinfo.utcoffset(end_datetime) is None:
            end_datetime.replace(tzinfo=utc)
            
        gage_data_matrix = []
        valid_comid_list = []
        num_days_needed = (end_datetime-start_datetime).days
    
        gage_id_list = []
        for row in reach_id_gage_id_list[1:]:
            station_id = row[1]
            if len(row[1]) == 7:
                station_id = '0' + row[1]
            gage_id_list.append(station_id)
        
        num_gage_id_list = np.array(gage_id_list, dtype=np.int32)
        print "Querying Server for Data ..."                            
    
        #print station_id
        query_params = {
                        'format': 'json',
                        'sites': ",".join(gage_id_list),
                        'startDT': start_datetime.astimezone(tzoffset(None, -18000)).strftime("%Y-%m-%d"),
                        'endDT': end_datetime.astimezone(tzoffset(None, -18000)).strftime("%Y-%m-%d"),
                        'parameterCd': '00060', #streamflow
                        'statCd': '00003' #average
                       }
        response = get("http://waterservices.usgs.gov/nwis/dv", params=query_params)
        if response.ok:
            data_valid = True
            try:
                requested_data = response.json()['value']['timeSeries']
            except IndexError:
                data_valid = False
                pass
            
            if data_valid:
                for time_series in enumerate(requested_data):
                    usgs_station_full_name = time_series[1]['name']
                    usgs_station_id = usgs_station_full_name.split(":")[1]
                    gage_data = []
                    for time_step in time_series[1]['values'][0]['value']:
                        local_datetime = parse(time_step['dateTime'])
                        if local_datetime > end_datetime:
                            break
                        
                        if local_datetime >= start_datetime:
                            if not time_step['value']:
                                print "MISSING DATA", station_id, local_datetime, time_step['value']
                            gage_data.append(float(time_step['value'])/35.3146667)
    
                    try:
                        #get where streamids assocated with USGS sation id is
                        streamid_index = np.where(num_gage_id_list==int(float(usgs_station_id)))[0][0]+1
                    except Exception:
                        print "USGS Station", usgs_station_id, "not found in list ..."
                        raise
                        
                    if len(gage_data) == num_days_needed:
                        gage_data_matrix.append(gage_data)
                        valid_comid_list.append(reach_id_gage_id_list[streamid_index][0])
                    else:
                        print "StreamID", reach_id_gage_id_list[streamid_index][0], "USGS Station", \
                              usgs_station_id, "MISSING", num_days_needed-len(gage_data), "DATA VALUES"
            if gage_data_matrix and valid_comid_list:
                print "Writing Output ..."                            
                np_array = np.array(gage_data_matrix).transpose()  
                with open(out_streamflow_file, 'wb') as gage_data:
                    wf = csvwriter(gage_data)
                    for row in np_array:
                        wf.writerow(row)
                        
                with open(out_stream_id_file, 'wb') as comid_data:
                    cf = csvwriter(comid_data)
                    for row in valid_comid_list:
                        cf.writerow([int(float(row))])
                        
                #set parameters for RAPID run
                self.IS_obs_tot = len(valid_comid_list)
                self.obs_tot_id_file = out_stream_id_file
                self.Qobs_file = out_streamflow_file
                self.IS_obs_use = len(valid_comid_list)
                self.obs_use_id_file = out_stream_id_file
            else:
                print "No valid data returned ..."
        else:
            print "USGS query error ..."


"""
if __name__ == "__main__":
    rapid_manager = RAPID(rapid_executable_location=rapid_executable_location,
                          use_all_processors=True,                          
                          ZS_TauR = 24*3600, #duration of routing procedure (time step of runoff data)
                          ZS_dtR = 15*60, #internal routing time step
                          ZS_TauM = len(era_interim_file_list)*24*3600, #total simulation time 
                          ZS_dtM = 24*3600 #input time step 
                         )
    era_rapid_output_file = os.path.join(master_watershed_output_directory,
                                                           'Qout_erai.nc')
    rapid_manager.update_parameters(rapid_connect_file=case_insensitive_file_search(master_watershed_input_directory,
                                                                                 r'rapid_connect\.csv'),
                                    Vlat_file=master_rapid_runoff_file,
                                    riv_bas_id_file=case_insensitive_file_search(master_watershed_input_directory,
                                                                                 r'riv_bas_id\.csv'),
                                    k_file=case_insensitive_file_search(master_watershed_input_directory,
                                                                        r'k\.csv'),
                                    x_file=case_insensitive_file_search(master_watershed_input_directory,
                                                                        r'x\.csv'),
                                    Qout_file=era_rapid_output_file
                                    )

    comid_lat_lon_z_file = case_insensitive_file_search(master_watershed_input_directory,
                                                        r'comid_lat_lon_z\.csv')

    rapid_manager.update_reach_number_data()
    rapid_manager.run()
    rapid_manager.make_output_CF_compliant(simulation_start_datetime=datetime.datetime(1980, 1, 1),
                                           comid_lat_lon_z_file=comid_lat_lon_z_file,
                                           project_name="ERA Interim Historical flows by US Army ERDC")     
"""
            
            