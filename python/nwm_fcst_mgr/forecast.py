from enum import Enum, auto
import glob
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
import geopandas as gpd
import pandas as pd
import netCDF4

import matplotlib.pyplot as plt
import yaml
import argparse

from nwm_fcst_mgr.log_level import log_level_set
from nwm_fcst_mgr.exceptions import NgenCalledProcessError, NgenIntentionallyStoppedError
from mswm.manager import build_fcst

# setup the logger
logger = logging.getLogger(__name__)
log_level_set()


class ConfigCache:
    """
    Cache for validation config and extracted values that are shared across multiple forecast runs
    """
    def __init__(self, valid_yaml: str):
        self.valid_yaml = valid_yaml
        self.valid_config = load_yaml(valid_yaml)
        logger.info(f"Validation file loaded from: {valid_yaml}")

        # Extract and validate config values once
        self.gpkg_cats, self.gpkg_nexus, self.ngen_exe, self.gage0 = extract_config(
            self.valid_config, self.valid_yaml
        )


class RunStatus(Enum):
    NOSTATUS = auto()
    PREPROCESSED = auto()  # Ready to run ngen
    EXECUTION_RUNNING = auto()
    EXECUTION_STOPPED = auto()
    EXECUTION_SUCCESS = auto()  # Finished running ngen
    EXECUTION_FAILED = auto()
    POSTPROCESSED = auto()


class ForecastExecutionManager:
    """
    Context manager for executing forecast via asynchronous ngen call.
    To run asynchronously, use wait=False during call to execute().
    To halt execution, either exit the context manager, or call schedule_ngen_stoppage().
    """

    def __init__(self, valid_yaml: str, real_path: str, config_cache: ConfigCache = None):
        self._status = RunStatus.NOSTATUS

        self.valid_yaml = valid_yaml
        self.real_path = real_path
        self.config_cache = config_cache

        # Set from config_cache or preprocess)
        self.valid_config = None
        self.out_dir = None
        self.gpkg_cats = None
        self.gpkg_nexus = None
        self.ngen_exe = None
        self.gage0 = None

        # Set during execute()
        self.cmd = None
        self.cwd = None
        self.proc = None
        self.log_handle = None

        # Set during postprocess()
        self.output_csv = None

        # If set to True, then the ngen proc will be sent a SIGTERM
        self._stop_ngen_flag = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Called when the context manager leaves its `with` block.

        KeyboardInterrupt is handled specially to avoid the situation of it being
        replaced by NgenIntentionallyStoppedError during the call to self._stop_ngen().
        This special handling causes the user to receive the original KeyboardInterrupt
        exception, which allows idiomatic interruption of the main thread in test cases
        that are designed to catch and ignore instances of NgenIntentionallyStoppedError.
        """
        try:
            self.close()
        except NgenIntentionallyStoppedError as e:
            if exc_type is KeyboardInterrupt:
                return False
            else:
                raise e

    def close(self):
        try:
            self._stop_ngen()
        finally:
            self._close_log()

    def _close_log(self):
        if self.log_handle is not None:
            if not self.log_handle.closed:
                logger.debug(f"Closing log: {self.log_handle.name}")
                self.log_handle.flush()
                os.fsync(self.log_handle.fileno())
                self.log_handle.close()

    def _stop_ngen(self) -> None:
        """
        If ngen is not running:
            return
        If ngen is running:
            Send a SIGTERM signal to the ngen process.
                If the process does not stop within a window of time, send a SIGKILL and raise a TimeoutError.
            Set self._status.
            Raise NgenIntentionallyStoppedError.
        """
        if self._status in (
            RunStatus.EXECUTION_STOPPED,
            RunStatus.EXECUTION_SUCCESS,
            RunStatus.EXECUTION_FAILED,
            RunStatus.POSTPROCESSED,
        ):
            self.proc.poll()
            if self.proc.returncode is None:
                raise RuntimeError(f"Expected process to have already stopped since status = {self._status}, but it has not")
            logger.debug("ngen has already stopped")
            return

        if self.proc is None:
            raise RuntimeError("self.proc not initialized")

        logger.info("Intentionally stopping ngen...")
        stop_timeout_sec = 5
        signal_to_send = signal.SIGTERM
        deadline = time.perf_counter() + stop_timeout_sec

        self.proc.send_signal(signal_to_send)
        while True:
            if time.perf_counter() > deadline:
                msg = f"Timed out waiting at least {stop_timeout_sec} seconds for ngen to stop after sending signal {signal_to_send}. Sending {signal.SIGKILL}"
                logger.error(msg)
                self.proc.send_signal(signal.SIGKILL)
                self.proc.wait()
                raise TimeoutError(msg)

            self.proc.poll()
            if self.proc.returncode is not None:  # Process has exited
                break
            time.sleep(0.5)

        self._status = RunStatus.EXECUTION_STOPPED
        raise NgenIntentionallyStoppedError(self.proc.returncode, self.cmd, self.cwd)

    def _check_process_returncode(self) -> None:
        """Poll the ngen process, set status if it has exited, and raise NgenCalledProcessError if it had a non-zero exit code."""
        if self._status != RunStatus.EXECUTION_RUNNING:
            raise RuntimeError(f"Expected self._status == {RunStatus.EXECUTION_RUNNING}, got {self._status}")
        self.proc.poll()
        match self.proc.returncode:
            case None:  # Still running
                pass
            case 0:
                self._status = RunStatus.EXECUTION_SUCCESS
                logger.info("NGEN run completed successfully")
            case _:
                self._status = RunStatus.EXECUTION_FAILED
                logger.critical(
                    f"Ngen run failed with return code {self.proc.returncode}. Command: {self.cmd}. Cwd: {self.cwd}"
                )
                raise NgenCalledProcessError(self.proc.returncode, self.cmd, self.cwd)

    def schedule_ngen_stoppage(self) -> None:
        """Set the ngen stop flag to True, causing it to be stopped during the next check on the process"""
        self._stop_ngen_flag = True

    def poll_ngen_flush_log(self) -> None:
        self.log_handle.flush()
        os.fsync(self.log_handle.fileno())
        if self._stop_ngen_flag:
            self._stop_ngen()
        self._check_process_returncode()

    def preprocess(self) -> None:
        """Preprocess an ngen run, validate some inputs, and set the execution status."""

        # Use cached config values
        self.valid_config = self.config_cache.valid_config
        self.gpkg_cats = self.config_cache.gpkg_cats
        self.gpkg_nexus = self.config_cache.gpkg_nexus
        self.ngen_exe = self.config_cache.ngen_exe
        self.gage0 = self.config_cache.gage0

        # set environment variable for ngencerf backend
        os.environ["NGEN_RESULTS_DIR"] = str(Path(self.real_path).parent)
        logging.info(f"Set environment variable NGEN_RESULTS_DIR to: {os.environ['NGEN_RESULTS_DIR']}")

        # Retrieve output_dir
        real_file = Path(self.real_path)
        self.out_dir = real_file.parent

        self._status = RunStatus.PREPROCESSED

    def execute(self, wait: bool = True, log_file_open_mode: str = "a+") -> None:
        """Execute ngen run for either cold-start or forecast period.
        To interrupt execution: call self.schedule_ngen_stoppage().
        To start a new output log file for the subprocess' stdout+stderr: use "w" instead of default "a+" for log_file_open_mode.
        """
        if self._status != RunStatus.PREPROCESSED:
            raise RuntimeError(f"Invalid self._status: {self._status} (expected {RunStatus.PREPROCESSED})")
        if log_file_open_mode not in ("a+", "w"):
            raise ValueError(f'Expected "a+" or "w" for log_file_open_mode, but got: {log_file_open_mode}')

        logger.info(f"Initializing NGEN run from:  {self.real_path}")

        # kick off ngen run and save stdout & stderr to ngen_stdout_stderr.log
        log_file = self.out_dir / "ngen_stdout_stderr.log"

        logger.info(f"Opening log file using mode {repr(log_file_open_mode)}: {log_file}")
        self.log_handle = open(log_file, log_file_open_mode)

        self.cmd = f'{self.ngen_exe} {self.gpkg_cats} "all" {self.gpkg_nexus} "all" {self.real_path}'
        self.cwd = str(self.out_dir)
        logger.info(f"Starting ngen via cmd: {self.cmd} from cwd: {self.cwd}")
        self.proc = subprocess.Popen(self.cmd, stdout=self.log_handle, stderr=self.log_handle, shell=True, cwd=self.cwd)
        self._status = RunStatus.EXECUTION_RUNNING

        if wait:
            poll_freq_seconds = 2
            logger.debug(f"Polling ngen process every {poll_freq_seconds} seconds...")
            start = time.perf_counter()
            while True:
                self.poll_ngen_flush_log()
                if self._status == RunStatus.EXECUTION_SUCCESS:
                    break
                logger.debug(f"ngen has been running for {(time.perf_counter() - start):.1f} seconds...")
                time.sleep(poll_freq_seconds)
            logger.info(f"ngen finished after {(time.perf_counter() - start):.1f} seconds")
            self._close_log()

        else:
            logger.info(f"Returning while ngen is running at: {self.proc}")

    def postprocess(self) -> None:
        """Postprocess results after ngen finishes running."""
        # TODO could assert that certain csv and nc files exist and are non-empty

        if self._status != RunStatus.EXECUTION_SUCCESS:
            raise RuntimeError(f"Invalid self._status: {self._status} (expected {RunStatus.EXECUTION_SUCCESS})")

        # move output files to output directory
        run_output_dir = self.out_dir / "Output/"
        run_output_dir.mkdir(parents=True, exist_ok=True)
        for pat1 in ["cat*.csv", "nex*.csv", "troute*.nc"]:
            for f1 in glob.glob(f"{self.out_dir}/{pat1}"):
                shutil.move(f1, Path(run_output_dir, os.path.basename(f1)))

        logger.info(f"NGEN outputs moved to: {run_output_dir}")

        # read troute output file
        outfile = glob.glob(f"{run_output_dir}/troute*.nc")[0]
        logger.info(f"Reading T-route output file: {outfile}")
        output = read_troute_output(self.gage0, self.valid_config["model"]["crosswalk"], self.gpkg_cats, outfile)

        # plot the hydrograph
        plot_path = Path(run_output_dir, self.gage0 + "_hydrograph.png")
        output.plot(y="sim_flow", kind="line")
        plt.xlabel("Time")
        plt.ylabel("Streamflow (m^3/s)")
        plt.savefig(plot_path, bbox_inches="tight")

        logger.info(f"Hydrograph plot saved to: {plot_path}")

        # save streamflow simulation to csv
        self.output_csv = Path(run_output_dir, self.gage0 + "_output.csv")
        output.to_csv(self.output_csv)

        logger.info(f"Fcst-mgr NGEN run outputs saved at: {run_output_dir}")

        self._status = RunStatus.POSTPROCESSED


def run_workflow(valid_yaml: str, real_path: str, config_cache: ConfigCache):
    """
    Execute ngen run workflow for forecast period and cold start period (if provided)
    valid_yaml: path to validation yaml file from past calibration run
    real_path: path to realization file for a cold start or forecast period
    config_cache: ConfigCache containing pre-loaded config and extracted values
    """
    with ForecastExecutionManager(valid_yaml, real_path, config_cache) as fem:
        fem.preprocess()
        fem.execute(wait=True)
        fem.postprocess()


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


def extract_config(valid_config: dict, valid_yaml: str) -> tuple:
    """ Extract and validate static config values from loaded config file"""
    # Retrieve hydrofabric gpkg
    gpkg_cats = valid_config["model"]["catchments"]
    gpkg_nexus = valid_config["model"]["nexus"]

    # Retrieve ngen executable
    ngen_exe = valid_config["model"]["binary"]

    # get gage ID and make sure it is not empty
    try:
        gage0 = valid_config["model"]["eval_params"]["basinID"]
    except ValueError as e:
        logger.critical(f"Key model/eval_params/basinID not found in {valid_yaml}\n{e}")
        raise
    if gage0 == "":
        try:
            raise ValueError(f"basinID in {valid_yaml} cannot be empty")
        except ValueError as e:
            logger.critical(e)
            raise

    return gpkg_cats, gpkg_nexus, ngen_exe, gage0


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
    except FileNotFoundError as e:
        logger.critical(f'Crosswalk file not found: {cwt_file}\n{e}')
        raise
    except json.JSONDecodeError as e:
        logger.critical(f'Failed to parse JSON from crosswalk file: {cwt_file}\n{e}')
        raise

    if x_walk.empty:
        try:
            raise Exception(f'{gage0} is not found in crosswalk file {cwt_file}')
        except Exception as e:
            logger.critical(e)
            raise

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


def run_forecast(valid_yaml, real_path):
    """
    Run forecast workflow with optional cold start run
    """
    logger.info(f'Initializing forecast run from: {valid_yaml}')

    # Load config and extract once per workflow
    config_cache = ConfigCache(valid_yaml)

    # Run forecast or cold start, depending on provided realization path
    run_workflow(valid_yaml, real_path, config_cache)
    logger.info("Ngen run completed")


def run_hindcast(input_path, valid_yaml, fcst_run_name, cycle_interval, num_iterations):
    """
    Run hindcast workflow with warm start runs, initial cold start should be run separately
    Accepts cycle interval and number of intervals for repeated hindcasts
    """
    logger.info(f'Initializing hindcast runs from: {valid_yaml}')

    # Load config and extract once per workflow
    config_cache = ConfigCache(valid_yaml)

    # Generate hindcast interval times in hours
    hind_interval = list(range(0, num_iterations * cycle_interval, cycle_interval))

    # Initialize previous hindcast cycle for coordinating warm starts
    prev_hind_cycle = 0

    # Loop through hindcast intervals
    for hind_cycle in hind_interval:

        logger.info(f"Initializing hindcast run at interval: + {hind_cycle} hours")

        # Format run name for hindcast cycle
        hind_run_name = fcst_run_name + '_' + str(hind_cycle)

        # Skip warm start for first hindcast, which will use the cold start state
        if hind_cycle != 0:

            # Generate msw-mgr inputs for warm start run for hindcast iteration
            warm_start_real_path = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                              fcst_run_name=hind_run_name, use_warm_start=True, hind_cycle=hind_cycle, prev_hind_cycle=prev_hind_cycle)
            logger.info(f"Warm start realization file for hindcast cycle {hind_cycle} written to: {warm_start_real_path}")

            # Run intermediate ana to generate hindcasting model states
            run_workflow(valid_yaml, warm_start_real_path, config_cache)
            logger.info(f"Warm start run for hindcast cycle {hind_cycle} completed")

        # Create hindcast input files
        hind_real_path = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                    fcst_run_name=hind_run_name, use_hindcast=True, hind_cycle=hind_cycle)
        logger.info(f"Hindcast run {hind_cycle} realization file written to: {hind_real_path}")

        # Run hindcasting period
        run_workflow(valid_yaml, hind_real_path, config_cache)
        logger.info(f"Hindcast run {hind_cycle} completed")

        # Store previous hindcast cycle value to set next warm start duration
        prev_hind_cycle = hind_cycle


def parse_args():
    # Create command line parser
    parser = argparse.ArgumentParser(prog="nwm-fcst-mgr",
                                     description="Forecast Manager command-line")
    subparser = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # Define parent parser for shared arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument('valid_yaml', type=str, help='Path to validation yaml file from previous run of nwm-cal-mgr')

    # Subcommand: forecast_workflow
    forecast_workflow_sub = subparser.add_parser("run_forecast", parents=[parent_parser], help="Run forecast workflow")
    forecast_workflow_sub.add_argument('real_path', type=str, help='Path to cold start or forecast period realization file')

    # Subcommand: hindcast_workflow
    hindcast_workflow_sub = subparser.add_parser("run_hindcast", parents=[parent_parser], help="Run hindcast workflow")
    hindcast_workflow_sub.add_argument('input_path', type=str, help='Path to input.config file for forecast')
    hindcast_workflow_sub.add_argument("fcst_run_name", help="Name of the folder to be created for storing inputs/outputs from running ngen")
    hindcast_workflow_sub.add_argument("cycle_interval", type=int, help="Cycle interval (in hours) between hindcast runs")
    hindcast_workflow_sub.add_argument("num_iterations", type=int, help="Number of hindcast cycles to perform")

    return parser.parse_args()


def main():

    # Retrieve CLI args
    args = parse_args()

    # Run fcst/hindcast workflows
    if args.command == "run_forecast":
        run_forecast(valid_yaml=args.valid_yaml, real_path=args.real_path)
    elif args.command == "run_hindcast":
        run_hindcast(valid_yaml=args.valid_yaml, input_path=args.input_path,
                     fcst_run_name=args.fcst_run_name, cycle_interval=args.cycle_interval,
                     num_iterations=args.num_iterations)
    else:
        raise ValueError(f"Unexpected command: {args.command}. Use either 'forecast_workflow' or 'hindcast_workflow'.")


if __name__ == "__main__":
    # print_git_info_all()
    main()
