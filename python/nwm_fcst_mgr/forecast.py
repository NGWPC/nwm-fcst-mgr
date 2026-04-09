from enum import Enum, auto
import glob
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
import geopandas as gpd
import pandas as pd
import netCDF4
import configparser
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import yaml
import argparse

from nwm_fcst_mgr.consts import PARTITION_CONFIG_FILE_NAME_SUFFIX
from nwm_fcst_mgr.exceptions import NgenCalledProcessError, NgenIntentionallyStoppedError
from nwm_fcst_mgr.ngen_cli import NgenCLI
from nwm_fcst_mgr.utils import initialize_logger, set_os_env_key, OS_ENV_KEY_RESULTS_DIR, OS_ENV_KEY_NGEN_LOG_FILE_PREFIX
from mswm.manager import build_fcst, build_region, build_default, update_fcst_run

# Set valid cycle hours for each forecast configuration
VALID_CYCLE_HOURS = {
    "medium_range_blend": [0, 6, 12, 18],
    "medium_range_blend_alaska": [0, 6, 12, 18],
    "long_range_mem1": [0, 6, 12, 18],
    "long_range_mem2": [0, 6, 12, 18],
    "long_range_mem3": [0, 6, 12, 18],
    "long_range_mem4": [0, 6, 12, 18],
}

# setup the logger
logger = initialize_logger()


class ConfigCache:
    """
    Cache for validation config and extracted values that are shared across multiple forecast runs
    Supports two modes:
        from_valid=True: loads config from a valid_yaml file (validation-based workflow)
        from_valid=False: loads gpkg and ngen_exe paths directly from run_dir (default/regionalization)
    """
    def __init__(self, valid_yaml: str = None, run_dir: str = None, from_valid: bool = True):
        self.from_valid = from_valid

        if from_valid:
            if valid_yaml is None:
                msg = "valid_yaml must be provided when from_valid=True"
                logger.critical(msg)
                raise ValueError(msg)
            self.valid_yaml = valid_yaml
            self.valid_config = load_yaml(valid_yaml)
            logger.info(f"Validation file loaded from: {valid_yaml}")
            self.gpkg_cats, self.gpkg_nexus, self.ngen_exe, self.gage0 = extract_config(
                self.valid_config, self.valid_yaml
            )
        else:
            if run_dir is None:
                msg = "valid_yaml must be provided when from_valid=True"
                logger.critical(msg)
                raise ValueError(msg)
            self.valid_yaml = None
            self.valid_config = None
            self.gage0 = None
            self.gpkg_cats, self.gpkg_nexus, self.ngen_exe, self.gage0 = extract_config_from_run_dir(run_dir)


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

    partition_file: (optional) path to partition configuration file.
        If provided, the work will be divided among n processors where n in the number of partitions in this file.
    """

    def __init__(
        self,
        real_path: str,
        config_cache: ConfigCache = None,
        partition_file: str | None = None,
    ):
        self._status = RunStatus.NOSTATUS

        self.real_path = real_path
        self.config_cache = config_cache
        self.partition_file = partition_file

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

        if self._status in (RunStatus.NOSTATUS, RunStatus.PREPROCESSED):
            if self.proc is not None:
                raise RuntimeError(f"Status is {self._status}, but self.proc is not None")
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

        # Retrieve output_dir
        real_file = Path(self.real_path)
        self.out_dir = real_file.parent

        global logger
        logger = initialize_logger(str(self.out_dir), self.out_dir.name)

        # set environment variable for ngencerf backend
        set_os_env_key(
            OS_ENV_KEY_RESULTS_DIR, str(self.out_dir), override=False
        )
        set_os_env_key(
            OS_ENV_KEY_NGEN_LOG_FILE_PREFIX, self.out_dir.name, override=False
        )

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
        log_file = self.out_dir / f"{self.out_dir.name}_ngen_stdout_stderr.log"

        logger.info(f"Opening log file using mode {repr(log_file_open_mode)}: {log_file}")
        self.log_handle = open(log_file, log_file_open_mode)

        ngen_cli = NgenCLI(
            ngen_path=self.ngen_exe,
            cats_path=self.gpkg_cats,
            cats_subset_ids=None,
            nexus_path=self.gpkg_nexus,
            nexus_subset_ids=None,
            realization_config_path=self.real_path,
            partition_config_path=self.partition_file,
        )
        self.cmd = ngen_cli.ngen_cmd(as_string=True)

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

    def postprocess(self, suppress_output: bool = False) -> None:
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

        if not suppress_output:

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


def search_for_partition_config(realization_file: str) -> str:
    """Search the realization folder for a partition configuration file.
    If 0 are found, return None
    If 1 is found, return its path.
    If 2+ are found, raise an error."""
    candidates: list[str] = []

    realization_directory = os.path.dirname(os.path.realpath(realization_file))
    for item in os.listdir(realization_directory):
        if item.endswith(f"{PARTITION_CONFIG_FILE_NAME_SUFFIX}.json"):
            candidates.append(os.path.join(realization_directory, item))
    if len(candidates) == 0:
        return None
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        f"Found {len(candidates)} candidates for partition config files (expected 0 or 1): {candidates}"
    )


def run_workflow(
    real_path: str,
    config_cache: ConfigCache,
    suppress_output: bool = False,
    partition_file: str | None = None,
):
    """
    Execute ngen run workflow for forecast period and cold start period (if provided)
    real_path: path to realization file for a cold start or forecast period
    config_cache: ConfigCache containing pre-loaded config and extracted values
    suppress_output: suppress postprocess output of plot and csv of streamflow
    partition_file: (optional) path to partition configuration file.
        If provided, the work will be divided among n processors where n in the number of partitions in this file.
    """
    with ForecastExecutionManager(
        real_path,
        config_cache,
        partition_file,
    ) as fem:
        fem.preprocess()
        fem.execute(wait=True)
        fem.postprocess(suppress_output)


def load_config(file_path: str) -> configparser.ConfigParser:
    """
    Read msw-mgr input.config file and return ConfigParser object
    """
    # Confirm input file exists
    file_path = Path(file_path).absolute()
    if not file_path.exists():
        try:
            raise FileNotFoundError(f'Input file not found: {file_path}')
        except FileNotFoundError as e:
            logger.critical(e)
            raise

    # Read the configuration file
    try:
        config = configparser.ConfigParser()
        config.read(file_path)
    except FileNotFoundError as e:
        logger.critical(f"Input file not found: {file_path}\n{e}")
        raise
    except configparser.Error as e:
        logger.critical(f"ConfigParser error reading config file: {file_path}\n{e}")
        raise
    except Exception as e:
        logger.critical(f"Unexpected error loading config: {file_path}\n{e}")
        raise

    return config


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
    """
    Extract and validate static config values from loaded config file
    """
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


def extract_config_from_run_dir(run_dir: str) -> tuple:
    """
    Extract gpkg and ngen executable paths from an existing default or regionalization run directory

    Parameters
    ----------
    run_dir: str
        Path to the existing run directory

    Returns
    ---------
    gpkg_cats, gpkg_nexus, ngen_exe
    """
    input_dir = Path(run_dir) / "Input"

    # Find gpkg file
    gpkg_files = list(input_dir.glob("*.gpkg"))
    if not gpkg_files:
        msg = f"Geopackage file not found in run directory: {input_dir}"
        logger.critical(msg)
        raise FileNotFoundError(msg)
    gpkg = str(gpkg_files[0])

    # Find ngen executable
    ngen_exe = str(input_dir / "ngen")
    if not Path(ngen_exe).exists():
        msg = f"ngen executable not found in run directory: {input_dir}"
        logger.critical(msg)
        raise FileNotFoundError(msg)

    return gpkg, gpkg, ngen_exe


def _get_run_type_from_config(input_path: str) -> str:
    """
    Read run_type from the [General] section of an input.config file

    Parameters
    ----------
    input_path: str
        Path to input.config file

    Returns
    ---------
    run_type string
    """
    config = load_config(input_path)
    try:
        run_type = config["General"]["run_type"]
    except KeyError as e:
        msg = f"run_type not found in [General] section of input.config: {e}"
        logger.critical(msg)
        raise KeyError(msg)
    return run_type


def _build_realization(input_path: str, run_type: str, **kwargs) -> str:
    """
    Call build_region or build_default based on run type

    Parameters
    ----------
    input_path: str
        Path to input.config file
    run_type: str
        Run type from input.config ('regionalization' or 'default')
    **kwargs
        Additional arguments passed to build_region or build_default

    Returns
    ---------
    run_type string
    """
    if run_type == 'regionalization':
        return build_region(input_path, **kwargs)
    elif run_type == 'default':
        return build_default(input_path, **kwargs)
    else:
        msg = f"Unupported run_type for from_valid=False workflow: {run_type}. Must be 'regionalization' or 'default'."
        logger.critical(msg)
        raise ValueError(msg)


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

    # Get outlet div_id from crosswalk
    outlet_div_id = int(x_walk.index[0])

    # Read flowpaths layer to find downstream nexus for outlet catchment
    flowpaths = gpd.read_file(gpkg_file, layer='flowpaths')
    outlet_fp = flowpaths[flowpaths['div_id'] == outlet_div_id]
    if outlet_fp.empty:
        msg = f"div_id {outlet_div_id} not found in flowpaths layer"
        logger.critical(msg)
        raise ValueError(msg)
    dn_nex_id = outlet_fp['dn_nex_id'].iloc[0]
    wb_lst = flowpaths[flowpaths['dn_nex_id'] == dn_nex_id]['div_id'].astype(int).tolist()

    # read troute output
    ncvar = netCDF4.Dataset(out_file, "r")
    fid_index = [list(ncvar['feature_id'][0:]).index(int(fid)) for fid in wb_lst]
    output = pd.DataFrame(data={'sim_flow': pd.DataFrame(ncvar['flow'][fid_index], index=fid_index).T.sum(axis=1)})
    t0 = pd.to_datetime(ncvar.file_reference_time, format="%Y-%m-%d_%H:%M:%S")
    output.index = [t0 + pd.Timedelta(seconds=int(t1)) for t1 in ncvar['time']]
    output.index.name = 'Time'

    return output


def check_hind_intervals(input_path: str, hind_interval: list) -> None:
    """
    Check that all hindcast intervals fall on valid cycle hours for a given forcing configuration

    Parameters
    ----------
    input_path: str
        Path to input.config file
    hind_interval: list
        List of hindcast intervals in hours
    """
    # Load config file
    config = load_config(input_path)

    # Read values from config file
    try:
        cycle_datetime = config['Forcing']['cycle_datetime']
        forcing_configuration = config['Forcing']['forcing_configuration']
    except KeyError as e:
        logger.critical(f"Error reading values from [Forcing] section of input.config: {e}")
        raise

    # Check if configuration has valid cycle hours restrictions
    config_key = next((k for k in VALID_CYCLE_HOURS if k in forcing_configuration), None)
    if config_key is None:
        return  # No restriction for given configuration

    # Check that hindcast interval falls on valid cycle time
    valid_hours = VALID_CYCLE_HOURS[config_key]
    cycle_dt = datetime.strptime(cycle_datetime, "%Y-%m-%d %H:%M:%S")

    for interval in hind_interval:
        interval_dt = cycle_dt + timedelta(hours=interval)
        if interval_dt.hour not in valid_hours:
            msg = (
                f"Hindcast iteration at {interval} hours falls on hour {interval_dt.hour}, which is not a valid cycle hour for {forcing_configuration}. "
                f"Valid hours: {valid_hours}"
            )
            logger.critical(msg)
            raise ValueError(msg)


def run_forecast(
    real_path: str,
    valid_yaml: str = None,
    from_valid: bool = True,
    partition_file: str | None = None
):
    """
    Run forecast workflow with optional cold start run

    Parameters
    ---------
    real_path : str
        Path to realization file for forecast
    valid_yaml : str
        Path to validation yaml file from previous run of nwm-cal-mgr
    from_valid : bool
        Boolean flag to create forecast from validation run
    partition_file : str | None (optional) path to partition configuration file.
        If provided, the work will be divided among n processors where n in the number of partitions in this file.
        TODO add multiprocessing support to run_hindcast and run_lagged_ensemble.
    """
    logger.info(f'Initializing forecast run (from_valid={from_valid})')

    if from_valid:
        if valid_yaml is None:
            msg = "valid_yaml must be provided when from_valid=True"
            logger.critical(msg)
            raise ValueError(msg)
        config_cache = ConfigCache(valid_yaml=valid_yaml, from_valid=True)
    else:
        run_dir = str(Path(real_path).parent)
        config_cache = ConfigCache(run_dir=run_dir, from_valid=False)

    # Run forecast or cold start, depending on provided realization path
    run_workflow(real_path, config_cache, supress_output=not from_valid, partition_file=partition_file)
    logger.info("Ngen run completed")


def run_hindcast(input_path, valid_yaml, fcst_run_name, cycle_interval, num_iterations, cold_start_state=None):
    """
    Run hindcast workflow with warm start runs, initial cold start should be run separately
    Accepts cycle interval and number of intervals for repeated hindcasts

    Parameters
    ---------
    input_path : str
        Path to input.config file for hindcast
    valid_yaml : str
        Path to validation yaml file from previous run of nwm-cal-mgr
    fcst_run_name : str
        Name of the folder to be created for storing inputs/outputs for hindcast
    cycle_interval : int
        Cycle interval (in hours) between hindcast runs
    num_iterations : int
        Number of hindcast cycles to perform
    cold_start_state : str, optional
        Path to directory containing state files to load at start of first hindcast
        If provided, will be used for first hindcast cycle (hind_cycle=0)
        Subsequent cycles will use warm start states
    """
    logger.info(f'Initializing hindcast runs from: {valid_yaml}')

    # Load config and extract once per workflow
    config_cache = ConfigCache(valid_yaml, from_valid=True)

    # Generate hindcast interval times in hours
    hind_interval = list(range(0, num_iterations * cycle_interval, cycle_interval))

    # Validate that all hindcast intervals fall on valid cycle hours for this configuration
    check_hind_intervals(input_path, hind_interval)

    logger.info(f"Initializing hindcast runs at intervals: {hind_interval}")

    # Initialize previous hindcast cycle for coordinating warm starts
    prev_hind_cycle = 0

    # Initialize previous state to be loaded for warm start
    prev_warm_start_state = cold_start_state

    # Loop through hindcast intervals
    for hind_cycle in hind_interval:

        # Skip warm start for first hindcast, which will use the cold start state
        if hind_cycle != 0:

            logger.info(f"Initializing warm start AnA run for hindcast iteration at {hind_cycle} hours")

            # Generate msw-mgr inputs for warm start run for hindcast iteration
            warm_start_real_path, warm_start_state = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                                                fcst_run_name=fcst_run_name, use_warm_start=True,
                                                                hind_cycle=hind_cycle, prev_hind_cycle=prev_hind_cycle,
                                                                save_state=True, load_state_from=prev_warm_start_state)
            logger.info(f"Warm start realization file for hindcast iteration at {hind_cycle} hours written to: {warm_start_real_path}")

            # Execute warm start ngen run to generate hindcasting model states
            run_workflow(valid_yaml, warm_start_real_path, config_cache, suppress_output=True)
            logger.info(f"Warm start run for hindcast iteration at {hind_cycle} hours completed")
            logger.info(f"Warm start state saved to {warm_start_state}")

            # Update state to be used by warm start in next iteration
            prev_warm_start_state = warm_start_state

        # Create hindcast input files
        hind_kwargs = {
            'input_path': input_path,
            'valid_yaml': valid_yaml,
            'fcst_run_name': fcst_run_name,
            'use_hindcast': True,
            'hind_cycle': hind_cycle
        }

        logger.info(f"Initializing hindcast run for iteration at {hind_cycle} hours")

        # Load from cold start state for first cycle if it's provided
        if hind_cycle == 0:
            if cold_start_state is not None:
                hind_kwargs['load_state_from'] = cold_start_state
                logger.info(f"Hindcast iteration at {hind_cycle} hours loading state from: {cold_start_state}")
        # Otherwise, load from warm start state
        else:
            hind_kwargs['load_state_from'] = warm_start_state
            logger.info(f"Hindcast iteration at {hind_cycle} hours loading state from: {warm_start_state}")

        hind_real_path = build_fcst(**hind_kwargs)
        logger.info(f"Hindcast realization file for iteration at {hind_cycle} hours written to: {hind_real_path}")

        # Run hindcasting period
        run_workflow(valid_yaml, hind_real_path, config_cache)
        logger.info(f"Hindcast run for iteration at {hind_cycle} hours completed")

        # Store previous hindcast cycle value to set next warm start duration
        prev_hind_cycle = hind_cycle


def run_lagged_ensemble(
        input_path,
        valid_yaml: str = None,
        fcst_run_name: str = None,
        from_valid: bool = True,
        open_loop_state=None,
        closed_loop_state=None
):
    """
    Run lagged ensemble workflow, loading from open and closed loop AnA states

    Parameters
    ---------
    input_path : str
        Path to input.config file for hindcast
    valid_yaml : str
        Path to validation yaml file from previous run of nwm-cal-mgr
    fcst_run_name : str
        Name of the folder to be created for storing inputs/outputs for hindcast
    from_valid : bool
        If True, use validation-based workflow. If False, use default/regionalization workflow.
    open_loop_state : str, optional
        Path to directory containing open loop AnA state files to initialize no DA member
    closed_loop_state : str, optional
        Path to directory containing closed loop AnA state files to initialize all other members
    """
    logger.info(f'Initializing lagged ensemble runs from_valid={from_valid}')

    if from_valid:
        if valid_yaml is None or fcst_run_name is None:
            msg = "valid_yaml and fcst_run_name must be provided when from_valid=True"
            logger.critical(msg)
            raise ValueError(msg)
    else:
        run_type = _get_run_type_from_config(input_path)

    # Set list of medium range lagged ensemble runs and hours of forcing lag
    ens_members = {
        'no_da': 0,
        'mem1': 0,
        'mem2': 6,
        'mem3': 12,
        'mem4': 18,
        'mem5': 24,
        'mem6': 30
    }

    # For from_valid=True, config_cache is the same for all members
    if from_valid:
        config_cache = ConfigCache(valid_yaml=valid_yaml, from_valid=True)

    # Loop through lagged ensemble members
    for member, lag in ens_members.items():

        logger.info(f"Setting up lagged ensemble run for medium range {member}")

        # Build realization via msw-mgr
        if from_valid:
            lag_ens_kwargs = {
                'input_path': input_path,
                'valid_yaml': valid_yaml,
                'fcst_run_name': fcst_run_name,
                'use_lagged_ens': True,
                'lagged_ens_mem': member,
                'forcing_lag': lag
            }

            # Load open loop AnA run state for no_da member, load closed loop AnA run state for all other members
            if member == "no_da":
                if open_loop_state is not None:
                    lag_ens_kwargs['load_state_from'] = open_loop_state
                    logger.info(f"Lagged ensember {member} member initialized with open loop state: {open_loop_state}")
            else:
                if closed_loop_state is not None:
                    lag_ens_kwargs['load_state_from'] = closed_loop_state
                    logger.info(f"Lagged ensember {member} member initialized with closed loop state: {closed_loop_state}")

            # Create lagged ensemble member input files
            member_real_path = build_fcst(**lag_ens_kwargs)

        else:
            lag_ens_kwargs = {
                'use_lagged_ens': True,
                'lagged_ens_mem': member,
                'forcing_lag': lag
            }

            # Load open loop AnA run state for no_da member, load closed loop AnA run state for all other members
            if member == "no_da":
                # Build no_da member realization from scratch
                if open_loop_state is not None:
                    lag_ens_kwargs['load_state_from'] = open_loop_state
                    logger.info(f"Lagged ensember {member} member initialized with open loop state: {open_loop_state}")

                member_real_path = _build_realization(
                    input_path=input_path,
                    run_type=run_type,
                    **lag_ens_kwargs
                )
                no_da_real_path = member_real_path
            else:
                # Copy no_da run folder and update forcing for each subsequent member
                src_run_path = str(Path(no_da_real_path).parent)
                dst_run_path = str(Path(no_da_real_path).parent.parent) / f"lagged_ens_{member}"

                if closed_loop_state is not None:
                    lag_ens_kwargs['load_state_from'] = closed_loop_state
                    logger.info(f"Lagged ensember {member} member initialized with closed loop state: {closed_loop_state}")

                member_real_path = update_fcst_run(
                    input_path=input_path,
                    src_run_path=src_run_path,
                    dst_run_path=dst_run_path,
                    **lag_ens_kwargs
                )

        logger.info(f"Lagged ensemble {member} member realization file written to: {member_real_path}")

        # For from_valid=False, derive run_dir from each member's realization path
        if not from_valid:
            config_cache = ConfigCache(
                run_dir=str(Path(member_real_path).parent),
                from_valid=False
            )

        # Run lagged ensemble period
        run_workflow(member_real_path, config_cache, supress_output=not from_valid)
        logger.info(f"Lagged ensemble {member} member run completed")


def parse_args():
    # Create command line parser
    parser = argparse.ArgumentParser(prog="nwm-fcst-mgr",
                                     description="Forecast Manager command-line")
    subparser = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # Define parent parser for shared arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument('real_path', type=str, help='Path to cold start or forecast period realization file')
    parent_parser.add_argument('--from_valid', action='store_true', default=True, help='use validation-based workflow (default=True)')

    # Subcommand: forecast_workflow
    forecast_workflow_sub = subparser.add_parser("run_forecast", parents=[parent_parser], help="Run forecast workflow")
    forecast_workflow_sub.add_argument('--valid_yaml', type=str, default=None, help='Path to validation yaml file from previous run of nwm-cal-mgr')

    # Subcommand: hindcast_workflow
    hindcast_workflow_sub = subparser.add_parser("run_hindcast", parents=[parent_parser], help="Run hindcast workflow")
    hindcast_workflow_sub.add_argument('input_path', type=str, help='Path to input.config file for forecast')
    hindcast_workflow_sub.add_argument("fcst_run_name", help="Name of the folder to be created for storing inputs/outputs from running ngen")
    hindcast_workflow_sub.add_argument("cycle_interval", type=int, help="Cycle interval (in hours) between hindcast runs")
    hindcast_workflow_sub.add_argument("num_iterations", type=int, help="Number of hindcast cycles to perform")
    hindcast_workflow_sub.add_argument("--cold_start_state", type=str, default=None, help="Path to directory containing cold start state files")

    # Subcommand: lagged_ensembles_workflow
    lagged_ens_workflow_sub = subparser.add_parser("run_lagged_ensemble", parents=[parent_parser], help="Run lagged ensembles workflow")
    lagged_ens_workflow_sub.add_argument('input_path', type=str, help='Path to input.config file for forecast')
    lagged_ens_workflow_sub.add_argument('--valid_yaml', type=str, default=None, help='Path to validation yaml file from previous run of nwm-cal-mgr')
    lagged_ens_workflow_sub.add_argument("--fcst_run_name", help="Name of the folder to be created for storing inputs/outputs from running ngen")
    lagged_ens_workflow_sub.add_argument("--open_loop_state", type=str, default=None, help="Path to directory containing open loop ana state files")
    lagged_ens_workflow_sub.add_argument("--closed_loop_state", type=str, default=None, help="Path to directory containing closed loop ana state files")

    return parser.parse_args()


def main():

    # Retrieve CLI args
    args = parse_args()

    # Run fcst/hindcast workflows
    if args.command == "run_forecast":
        run_forecast(real_path=args.real_path, valid_yaml=args.valid_yaml, from_valid=args.from_valid)
    elif args.command == "run_hindcast":
        run_hindcast(valid_yaml=args.valid_yaml, input_path=args.input_path,
                     fcst_run_name=args.fcst_run_name, cycle_interval=args.cycle_interval,
                     num_iterations=args.num_iterations, cold_start_state=args.cold_start_state)
    elif args.command == "run_lagged_ensemble":
        run_lagged_ensemble(valid_yaml=args.valid_yaml, input_path=args.input_path,
                            fcst_run_name=args.fcst_run_name, from_valid=args.from_valid,
                            open_loop_state=args.open_loop_state, closed_loop_state=args.closed_loop_state)
    else:
        raise ValueError(f"Unexpected command: {args.command}. Use either 'run_forecast', 'run_hindcast', or 'run_lagged_ensemble'.")


if __name__ == "__main__":
    # print_git_info_all()
    main()
