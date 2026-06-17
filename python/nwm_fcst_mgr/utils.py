"""Utilities"""

import ewts
from datetime import datetime, timezone
from os import environ
from pathlib import Path

OS_ENV_KEY_RESULTS_DIR = "NGEN_RESULTS_DIR"
OS_ENV_KEY_NGEN_LOG_FILE_PREFIX = "NGEN_LOG_FILE_PREFIX"

def set_os_env_key(key: str, val: str, override: bool = True) -> None:
    """Set the value of the OS environment key.
    Optionally, keep the existing value for that key without overriding, if it already exists.

    Parameters:
        key : str
            OS environment key whose value will be modified.
        val : str
            New value to set to.
        override : bool (default True)
            If True, then do replace the existing value of that key if it already exists.
            If False, then do not replace the value.
    """
    LOG = ewts.get_logger(ewts.FCST_MGR_ID).get_bound_logger()

    errors: list[Exception] = []
    if not isinstance(key, str):
        errors.append(TypeError(f"For key {key}, expected type {str}, got {type(key)}"))
    if not isinstance(val, str):
        errors.append(
            TypeError(f"For value {val}, expected type {str}, got {type(val)}")
        )
    if errors:
        raise RuntimeError(errors)

    if key in environ:
        msg_suffix = f"OS env key {repr(key)} already exists with value {repr(environ[key])}, override={override}"
        if not override:
            LOG.info("Will not override: " + msg_suffix)
            return
        LOG.info("Will override: " + msg_suffix)

    LOG.info(f"Setting OS env key {repr(key)} to value {repr(val)}.")
    environ[key] = val

def create_timestamp(date_only: bool = False, iso: bool = False, append_ms: bool = False) -> str:
    now = datetime.now(timezone.utc)

    if date_only:
        ts_base = now.strftime("%Y%m%d")
    elif iso:
        ts_base = now.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        ts_base = now.strftime("%Y%m%dT%H%M%S")

    if append_ms:
        ms_str = f".{now.microsecond // 1000:03d}"
        return ts_base + ms_str
    else:
        return ts_base

def initialize_logger(log_path: str | None = None, log_id: str | None = None) -> tuple[ewts.EwtsLogger, Path]:
    '''
    Set up logger.

    Arguments
    ---------
    log_path: optional log directory path
    log_id: optional identifier appended to the log filename

    Returns
    -------
    ewts.EwtsLogger
        Instance of the EWTS logger.
    Path
        The resolved log *file* path (not log *dir*)
    '''

    if log_path is not None:
        log_file_dir = Path(log_path)
        log_file_name = f"fcst_mgr_{log_id}.log" if log_id else "fcst_mgr.log"
    else:
        base_dir = Path(__file__).resolve().parent.parent

        if Path("/ngencerf/data").exists():
            log_file_dir = Path("/ngencerf/data/run-logs/fcst-mgr")
        else:
            log_file_dir = base_dir / "run-logs/fcst-mgr"

        log_file_name = f"fcst_mgr_{create_timestamp()}.log"
    
    

    # In case the logger was previously setup for bootstrapping
    ewts.logger.reset_logger(ewts.FCST_MGR_ID)

    return ewts.logger.setup_logger(
        ewts.FCST_MGR_ID,
        level="INFO",
        log_dir=log_file_dir,
        log_file_name=log_file_name,
        running_in_ngen=False,
        enabled=True,
    ), (log_file_dir / log_file_name)


