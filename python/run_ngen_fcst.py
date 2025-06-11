# python program to run ngen for realtime forecasting given the forcing data (in either NetCDF or CSV format )
# validation configuration file in .yaml 

import glob
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import yaml
import argparse

from git_util import print_git_info_all
from log_level import log_level_set
from process_forcing import update_forcing_in_realization
from update_bmi_config import update_noah_ueb, update_troute
from read_output import read_troute_output

# setup the logger
log_level_set()
logger = logging.getLogger(__name__)

# print git hash info
print_git_info_all()

# set environment variable for ngencerf backend - @TODO
#os.environ['NGEN_RESULTS_DIR'] = str(Path(agent.workdir).parent.parent)
#logging.info(f'Set environment variable NGEN_RESULTS_DIR to: {os.environ["NGEN_RESULTS_DIR"]}')

# Create the parser
parser = argparse.ArgumentParser()

# Add arguments
parser.add_argument('forcing_file', type=str, help=('Path to the NetCDF forcing file OR '
                      'a folder containing .csv forcing files for all catchments'))
parser.add_argument('config_file', type=str, help='Path to the config yaml file for a validation run (e.g., 01123000_config_valid_best.yaml from ngen-cal)')
parser.add_argument('output_folder', type=str, help='Path to the folder to be created for storing inputs/outputs from running ngen')

# Parse the arguments
args = parser.parse_args()
logger.info(f"Forcing file(s) to use: {args.forcing_file}")
logger.info(f"Validation config file to use: {args.config_file}")
logger.info(f"Relative folder path to outputs: {args.output_folder}")

# Read the yaml-based configuration file (from a previous ngen-cal validation run)
config_file = Path(args.config_file).absolute()
if not config_file.exists():
    raise FileNotFoundError(f'Config fiel {config_file} does not exist!')
with open(config_file) as file:
    conf = yaml.safe_load(file)

# create output directory 
out_dir0 = Path(conf['general']['yaml_file']).parent.parent.resolve(strict=True)
out_dir = Path(out_dir0, 'Forecast_Run', args.output_folder)
out_dir.mkdir(parents=True, exist_ok=True)
logger.info(f'New run directory created at: {out_dir}')

# read realization file
real_file = Path(conf['model']['realization'])
real_file.resolve(strict=True)
with open(real_file) as fp:
    real_config = json.load(fp)

# get hydrofabric gpkg
gpkg_cats = conf['model']['catchments']
gpkg_nexus = conf['model']['nexus']

# get ngen executable
ngen_exe = conf['model']['binary']

# Update forcing and time related info in realization file
real_config = update_forcing_in_realization(Path(args.forcing_file), real_config, gpkg_cats)

# For UEB and Noah-OWP-Modular, create new BMI config files with new time info, and
# update path to BMI configs in realization file accordingly 
real_config = update_noah_ueb(real_config, out_dir)

# Do the same for t-route
real_config = update_troute(real_config, out_dir)

# save the new realization file
new_real_file = Path(out_dir, os.path.basename(real_file))
with open(new_real_file, 'w') as outfile:
    json.dump(real_config, outfile, indent=4, separators=(", ", ": "), sort_keys=False)

# run command
cmd = f'{ngen_exe} {gpkg_cats} "all" {gpkg_nexus} "all" {new_real_file}'

# kick off ngen run and save stdout & stderr to ngen_stdout_stderr.log
log_file = Path(out_dir, 'ngen_stdout_stderr.log')
with open(log_file, 'a+') as log:
    subprocess.check_call(cmd, stdout=log, stderr=log, shell=True, cwd=str(out_dir))

# move output files to output directory
output_dir = Path(out_dir, "output/")
output_dir.mkdir(parents=True, exist_ok=True)
for pat1 in ['cat*.csv', 'nex*.csv', 'troute*.nc']:
    for f1 in glob.glob(f'{out_dir}/{pat1}'):
        shutil.move(f1, Path(output_dir, os.path.basename(f1)))
logger.info(f'Outputs are saved at: {output_dir}')

# get gage ID and make sure it is not empty
try:
    gage0 = conf['model']['eval_params']['basinID']
except:
    raise ValueError(f'Key model/eval_params/basinID not found in {config_file}')
if gage0=="":
    raise ValueError(f'basinID in {config_file} cannot be empty')

# read troute output file
outfile = glob.glob(f'{output_dir}/troute*.nc')[0]
output = read_troute_output(gage0, conf['model']['crosswalk'], gpkg_cats, outfile)

# plot the hydrograph
output.plot(y='sim_flow', kind='line')
plt.xlabel('Time')
plt.ylabel('Streamflow (m^3/s)')
plt.savefig(Path(output_dir, gage0 + '_hydrograph.png'), bbox_inches ="tight")

# save streamflow simulation to csv
output.to_csv(Path(output_dir, gage0 + '_output.csv'))
logger.info('Run completed!')