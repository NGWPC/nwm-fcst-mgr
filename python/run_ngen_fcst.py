# python program to run ngen for realtime forecasting given the forcing data in .nc and 
# validation configuration file in .yaml 

from pathlib import Path
import sys
import pandas as pd
import geopandas as gpd
import os
import json
import yaml
import shutil
import glob
from datetime import datetime, timedelta
import subprocess
import netCDF4
import matplotlib.pyplot as plt
import logging
from datetime import datetime, timezone
import os
import time

logger = logging.getLogger(__name__)
#logging.basicConfig(level=logging.INFO)

#LOG = logging.getLogger(__name__)

def create_timestamp() -> str: 
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")
    

def log_level_set():
    '''
    Set logging level and specify logger configuration.
    
    Arguments
    ---------
    input_parameters (dict): User input logging parameters
    
    Returns
    -------
    None
    
    Notes
    -----
    In the absense of user-specified logging level, level defaults to DEBUG
    See also https://docs.python.org/3/library/logging.html
    
    '''

    log_level = 'INFO'
    if True:
        BASE_DIR = Path(__file__).resolve().parent.parent

        if Path("/ngencerf/data").exists() :
            log_file_dir = Path(f'/ngencerf/data/run-logs/ngen_fcst_{create_timestamp()}/')
        else :
            log_file_dir = Path(BASE_DIR) / f'run-logs/ngen_fcst_{create_timestamp()}/'

        log_file_name = "ngen_fcst.log"
        os.makedirs(log_file_dir, exist_ok=True)
        logFilePath = os.path.join(log_file_dir, log_file_name)
        try:
            logFile = open(logFilePath, "a")
            print(f"Logging into: {logFilePath}")
        except IOError:
            print(f"Can't Open local directory Log File: {logFilePath}", file=sys.stderr)
        
        logging.Formatter.converter = time.gmtime
        logging.basicConfig(
            force=True,
            level=log_level,
            format='%(asctime)s.%(msecs)03d NGEN_FCST %(levelname)s    %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S',
            handlers=[
            logging.FileHandler(logFilePath, mode='a'),  # Log to a file
            #logging.StreamHandler(sys.stdout)  
        ])
    else:       
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)s - %(funcName)s]: %(message)s',
            stream=sys.stderr,
        )  

import argparse

# setup the logger
log_level_set()
   
# set environment variable for ngencerf backend - @TODO
#os.environ['NGEN_RESULTS_DIR'] = str(Path(agent.workdir).parent.parent)
#logging.info(f'Set environment variable NGEN_RESULTS_DIR to: {os.environ["NGEN_RESULTS_DIR"]}')

# Create the parser
parser = argparse.ArgumentParser()

# Add arguments
parser.add_argument('forcing_file', type=str, help='Path to the NetCDF forcing file')
parser.add_argument('config_file', type=str, help='Path to the config yaml file for a validation run (e.g., 01123000_config_valid_best.yaml from ngen-cal)')
parser.add_argument('output_folder', type=str, help='Path to the folder to be created for storing inputs/outputs from running ngen')

# Parse the arguments
args = parser.parse_args()
logger.info(f"Forcing file to use: {args.forcing_file}")
logger.info(f"Validation config file to use: {args.config_file}")
logger.info(f"Relative folder path to outputs: {args.output_folder}")

# define forcing file and valid_best config file
forcing_file = Path(args.forcing_file).resolve(strict=True)
config_file = Path(args.config_file).resolve(strict=True)

# make sure forcing file exists as netcdf
if os.path.splitext(forcing_file)[1] != '.nc':
    logger.warning(f'{forcing_file} does not have .nc extension. Assuming it is a netcdf file')

# read forcing to get start and end times
ncvar = netCDF4.Dataset(forcing_file, "r")

t0 = pd.to_datetime(ncvar.model_initialization_time,format="%Y-%m-%d_%H:%M:%S")
times = [t1 for t1 in ncvar['Time']]
start_time = t0 + pd.Timedelta(seconds=3600)
end_time = t0 + pd.Timedelta(seconds=(times[-1]-times[0]+60)*60)
logger.info(f'Start time: {start_time}')
logger.info(f'End time: {end_time}')

# read yaml configuration file for best validation
with open(config_file) as file:
    conf = yaml.safe_load(file)

# read the realization file
real_file = Path(conf['model']['realization'])
real_file.resolve(strict=True)
with open(real_file) as fp:
    real_config = json.load(fp)

# update forcing in realization file
real_config['global']['forcing'] = dict([('path',str(forcing_file)),('provider','NetCDF')])

# update time period in realization file
real_config['time']['start_time'] = str(start_time)
real_config['time']['end_time'] = str(end_time)

# create output directory in Calibration Output directory
out_dir0 = Path(conf['general']['yaml_file']).parent.parent.resolve(strict=True)
out_dir = Path(out_dir0, 'Forecast_Run', args.output_folder)
out_dir.mkdir(parents=True, exist_ok=True)
out_dir = out_dir.resolve()
logger.info(f'New run directory created at: {out_dir}')

# for noah-owp-modular & UEB, update path to BMI config files in realization file
# as well as start/end times in BMI config files 
modules = real_config['global']['formulations'][0]['params']['modules']
mod_dict = {'NoahOWP': 'noah-owp-modular', 'UEB': 'ueb'}

startdate = start_time.strftime("%Y%m%d%H%M")
enddate = end_time.strftime("%Y%m%d%H%M")

for i1,m1 in enumerate(modules):
    if m1['params']['model_type_name'] in ['NoahOWP','UEB']:

        # read the BMI config files from the source directory in the realization file
        src0 = real_config['global']['formulations'][0]['params']['modules'][i1]['params']['init_config']
        src = Path(src0.replace('{{id}}','*'))
        dst = Path(out_dir, mod_dict[m1['params']['model_type_name']] + '_input')
        dst.mkdir(parents=True, exist_ok=True)
        for f1 in glob.glob(f'{src}'):
            with open(f1) as f:
                lines = f.readlines()

            # update start/end times
            for i2,l1 in enumerate(lines):
                if m1['params']['model_type_name'] == 'NoahOWP':
                    if 'startdate' in l1:
                        lines[i2] = "  " + "startdate".ljust(19) + "= " + "'" + startdate + "'" + "               ! UTC time start of simulation (YYYYMMDDhhmm)\n"
                    elif 'enddate' in l1:
                        lines[i2] = "  " + "enddate".ljust(19) + "= " + "'" + enddate + "'" + "               ! UTC time end of simulation (YYYYMMDDhhmm)\n"
                elif m1['params']['model_type_name'] == 'UEB':
                    lines[8] = f'{startdate[:4]} {startdate[4:6]} {startdate[6:8]} {startdate[8:10]}.0\n'
                    lines[9] = f'{enddate[:4]} {enddate[4:6]} {enddate[6:8]} {enddate[8:10]}.0\n'  
            
            # write to new BMI config files
            with open(Path(dst, os.path.basename(f1)), 'w') as outfile:
                outfile.writelines(lines)

        # replace path to BMI config file in realization file
        real_config['global']['formulations'][0]['params']['modules'][i1]['params']['init_config'] = str(Path(dst, os.path.basename(src0)))

# For t-route, update path to config file as well as time-related info in the config file
src = Path(real_config['routing']['t_route_config_file_with_path'])
src.resolve(strict=True)
with open(src) as fp1:
    rt_config = yaml.safe_load(fp1)

# compute number of time steps and max_loop_size
nts = len(pd.date_range(start=start_time, end=end_time, freq='5min'))-1
max_loop_size = divmod(nts*300, 3600)[0]+1
stream_output_time = divmod(nts*300, 3600)[0]+1

# update t-route config
rt_config['compute_parameters']['restart_parameters']['start_datetime'] = str(start_time)
rt_config['compute_parameters']['forcing_parameters']['nts'] = nts
rt_config['compute_parameters']['forcing_parameters']['max_loop_size'] = max_loop_size
rt_config['output_parameters']['stream_output']['stream_output_time'] = stream_output_time

# write to new t-route config file
new_file = Path(out_dir, os.path.basename(src))
with open(new_file, 'w') as file:
    yaml.dump(rt_config, file, sort_keys=False, default_flow_style=False, indent=4)

# update path to new t-route config in realization
real_config['routing']['t_route_config_file_with_path'] = str(new_file)

# save the new realization file
new_real_file = Path(out_dir, os.path.basename(real_file))
with open(new_real_file, 'w') as outfile:
    json.dump(real_config, outfile, indent=4, separators=(", ", ": "), sort_keys=False)

# hydrofabric gpkg
gpkg_cats = conf['model']['catchments']
gpkg_nexus = conf['model']['nexus']

# ngen executable
ngen_exe = conf['model']['binary']

# run command
cmd = f'{ngen_exe} {gpkg_cats} "all" {gpkg_nexus} "all" {new_real_file}'

# kick off ngen run and save stdout & stderr to ngen_stdout_stderr.log
log_file = Path(out_dir, 'ngen_stdout_stderr.log')
with open(log_file, 'a+') as log:
    subprocess.check_call(cmd, stdout=log, stderr=log, shell=True, cwd=str(out_dir))

# move output files to output directory
output_dir = Path(out_dir, "output/")
output_dir.mkdir(parents=True, exist_ok=True)
for pat1 in ['cat*.csv','nex*.csv','troute*.nc']:
    for f1 in glob.glob(f'{out_dir}/{pat1}'):
        shutil.move(f1,Path(output_dir,os.path.basename(f1)))
logger.info(f'Outputs are saved at: {output_dir}')

# get gage ID and make sure it is not empty
try:
    gage0 = conf['model']['eval_params']['basinID']
except:
    raise ValueError(f'Key model/eval_params/basinID not found in {config_file}')
if gage0=="":
    raise ValueError(f'basinID in {config_file} cannot be empty')

# Handle crosswalk file (in order to get the correct feature_id when reading t-route data)
x_walk = pd.Series(dtype=object)
cwt_file = conf['model']['crosswalk']
try:
    with open(cwt_file) as fp:
        data = json.load(fp)
        for id, values in data.items():
            gage = values.get('Gage_no')
            if gage:
                if not isinstance(gage, str):
                    gage = gage[0]
                if gage==gage0:
                    x_walk[id] = gage
                    break
except FileNotFoundError:
    raise FileNotFoundError(f"Crosswalk file '{cwt_file}' not found.")
except json.JSONDecodeError:
    raise ValueError(f"Failed to parse JSON from crosswalk file '{cwt_file}'.")

if x_walk.empty:
    raise Exception(f'{gage0} is not found in crosswalk file {cwt_file}')

# get catchment at basin outlet for reading from t-route output
catchment_hydro_fabric = gpd.read_file(gpkg_cats, layer='divides')
catchment_hydro_fabric.set_index('id', inplace=True)
nexus_id = catchment_hydro_fabric.loc[x_walk.index[0].replace('cat','wb')]['toid']
wb_lst = [x.split('-')[1] for x in list(catchment_hydro_fabric.query('toid==@nexus_id').index)]

# read troute output
file1 = glob.glob(f'{output_dir}/troute*.nc')[0]
ncvar = netCDF4.Dataset(file1, "r")
fid_index = [list(ncvar['feature_id'][0:]).index(int(fid)) for fid in wb_lst]
output = pd.DataFrame(data={'sim_flow': pd.DataFrame(ncvar['flow'][fid_index], index=fid_index).T.sum(axis=1)})
t0 = pd.to_datetime(ncvar.file_reference_time,format="%Y-%m-%d_%H:%M:%S")
output.index = [t0+pd.Timedelta(seconds=int(t1)) for t1 in ncvar['time']]
output.index.name = 'Time'

# plot the hydrograph
output.plot(y='sim_flow',kind='line')
plt.xlabel('Time')
plt.ylabel('Streamflow (m^3/s)')
plt.savefig(Path(output_dir, gage0 + '_hydrograph.png'), bbox_inches ="tight")

# save streamflow simulation to csv
output.to_csv(Path(output_dir, gage0 + '_output.csv'))
logger.info('Run completed!')