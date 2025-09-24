import glob
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
import geopandas as gpd
import pandas as pd
import netCDF4

import matplotlib.pyplot as plt
import yaml
import argparse

# from git_util import print_git_info_all
from nwm_fcst_mgr.log_level import log_level_set

# setup the logger
log_level_set()
logger = logging.getLogger(__name__)


def run_fcst(valid_yaml: str, real_path: str):
    """
    Execute ngen run for forecast period and cold start period (if provided)
    
    valid_yaml: path to validation yaml file from past calibration run
    real_path: path to realizattion file for a cold start or forecast period
    """

    # Read validation yaml file
    valid_config = load_yaml(valid_yaml)

    logger.info(f'Validation file loaded from: {valid_yaml}')

    # Retrieve output_dir
    real_file = Path(real_path)
    out_dir = real_file.parent

    # Retrieve hydrofabric gpkg
    gpkg_cats = valid_config['model']['catchments']
    gpkg_nexus = valid_config['model']['nexus']

    # Retrieve ngen executable
    ngen_exe = valid_config['model']['binary']

    # get gage ID and make sure it is not empty
    try:
        gage0 = valid_config['model']['eval_params']['basinID']
    except ValueError as e:
        logger.critical(f'Key model/eval_params/basinID not found in {valid_yaml}\n{e}')
        raise
    if gage0 == "":
        try:
            raise ValueError(f'basinID in {valid_yaml} cannot be empty')
        except ValueError as e:
            logger.critical(e)
            raise

    # Execute ngen run for either cold-start or forecast period
    cmd = f'{ngen_exe} {gpkg_cats} "all" {gpkg_nexus} "all" {real_path}'

    # kick off ngen run and save stdout & stderr to ngen_stdout_stderr.log
    log_file = out_dir / "ngen_stdout_stderr.log"
    with open(log_file, 'a+') as log:
        subprocess.check_call(cmd, stdout=log, stderr=log, shell=True, cwd=str(out_dir))

    # move output files to output directory
    run_output_dir = out_dir / "output/"
    run_output_dir.mkdir(parents=True, exist_ok=True)
    for pat1 in ['cat*.csv', 'nex*.csv', 'troute*.nc']:
        for f1 in glob.glob(f'{out_dir}/{pat1}'):
            shutil.move(f1, Path(run_output_dir, os.path.basename(f1)))

    # read troute output file
    outfile = glob.glob(f'{run_output_dir}/troute*.nc')[0]
    output = read_troute_output(gage0, valid_config['model']['crosswalk'], gpkg_cats, outfile)

    # plot the hydrograph
    output.plot(y='sim_flow', kind='line')
    plt.xlabel('Time')
    plt.ylabel('Streamflow (m^3/s)')
    plt.savefig(Path(run_output_dir, gage0 + '_hydrograph.png'), bbox_inches="tight")

    # save streamflow simulation to csv
    output.to_csv(Path(run_output_dir, gage0 + '_output.csv'))

    logger.info(f'Fcst-mgr NGEN run outputs are saved at: {run_output_dir}')


def load_yaml(file_path: str) -> dict:
    """
    Read yaml-based configuration file from previous ngen calibration run
    """
    # Confirm input file exists
    file_path = Path(file_path).absolute()
    if not file_path.exists():
        try:
            raise FileNotFoundError(f'Input file not found: {file_path}')
        except FileNotFoundError as e:
            logger.critical(e)
            raise

    # Read the yaml-based configuration file
    try:
        with open(file_path) as file:
            yaml_dict = yaml.safe_load(file)
    except FileNotFoundError as e:
        logger.critical(f'Config valid yaml file does not exist: {file_path}\n{e}')
        raise
    except yaml.YAMLError as e:
        logger.critical(f"YAML parsing error in valid config yaml file: {file_path}\n{e}")
        raise
    except Exception as e:
        logger.critical(f"Unexpected error loading valid config yaml file at: {file_path}\n{e}")
        raise

    return yaml_dict


def read_troute_output(
        gage0: str,
        cwt_file: Path,
        gpkg_file: Path,
        out_file: Path,
) -> pd.DataFrame:

    """
    Arguments:
    ---------
    gage0: gage ID to retrieve streamflow simulations
    cwt_file: path to crosswalk file mapping gage to catchments
    gpkg_file: path to geopackage file
    out_file: path to t-route output file (in NetCDF format)

    Returns:
    ---------
    dataframe containing time and streamflow simulations

    """
    # Handle crosswalk file (in order to get the correct feature_id when reading t-route data)
    x_walk = pd.Series(dtype=object)
    try:
        with open(cwt_file) as fp:
            data = json.load(fp)
            for id, values in data.items():
                gage = values.get('Gage_no')
                if gage:
                    if not isinstance(gage, str):
                        gage = gage[0]
                    if gage == gage0:
                        x_walk[id] = gage
                        break
    except FileNotFoundError:
        raise FileNotFoundError(f"Crosswalk file '{cwt_file}' not found.")
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse JSON from crosswalk file '{cwt_file}'.")

    if x_walk.empty:
        raise Exception(f'{gage0} is not found in crosswalk file {cwt_file}')

    # get catchment at basin outlet for reading from t-route output
    catchment_hydro_fabric = gpd.read_file(gpkg_file, layer='divides')
    catchment_hydro_fabric.set_index('id', inplace=True)
    nexus_id = catchment_hydro_fabric.loc[x_walk.index[0].replace('cat', 'wb')]['toid']
    wb_lst = [x.split('-')[1] for x in catchment_hydro_fabric.index[catchment_hydro_fabric['toid'] == nexus_id]]

    # read troute output
    ncvar = netCDF4.Dataset(out_file, "r")
    fid_index = [list(ncvar['feature_id'][0:]).index(int(fid)) for fid in wb_lst]
    output = pd.DataFrame(data={'sim_flow': pd.DataFrame(ncvar['flow'][fid_index], index=fid_index).T.sum(axis=1)})
    t0 = pd.to_datetime(ncvar.file_reference_time, format="%Y-%m-%d_%H:%M:%S")
    output.index = [t0 + pd.Timedelta(seconds=int(t1)) for t1 in ncvar['time']]
    output.index.name = 'Time'

    return output


def parse_args():
    # Create command line parser
    parser = argparse.ArgumentParser()

    # Add arguments
    parser.add_argument('valid_yaml', type=str, help=('Path to validation yaml file from previous run of nwm-cal-mgr'))
    parser.add_argument('real_path', type=str, help=('Path to cold start or forecast period realization file'))

    return parser.parse_args()


def main():
    args = parse_args()
    run_fcst(args.valid_yaml, args.real_path)


if __name__ == "__main__":
    main()
