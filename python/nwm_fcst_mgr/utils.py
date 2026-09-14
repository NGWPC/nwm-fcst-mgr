"""Utilities"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from os import environ
from pathlib import Path
import logging
import sys


OS_ENV_KEY_RESULTS_DIR = "NGEN_RESULTS_DIR"
OS_ENV_KEY_NGEN_LOG_FILE_PREFIX = "NGEN_LOG_FILE_PREFIX"
HINDCAST_LOGGER_ID = "HINDCAST"

# Matches the "STATUS" custom level EWTS registers via logging.addLevelName(60, "STATUS")
# in ewts/logger.py. Defined here (not just conditionally, when EWTS is unavailable) so
# StdoutStyleFormatter can treat STATUS records like INFO records regardless of whether
# EWTS itself already registered the level name.
STATUS_LEVEL = 60

try:
    import ewts
    from ewts.modules import FCST_MGR_ID
    EWTS_AVAILABLE = True
except ImportError:
    FCST_MGR_ID = "FCSTMGR"
    EWTS_AVAILABLE = False
    logging.addLevelName(STATUS_LEVEL, "STATUS")


class StdoutStyleFormatter(logging.Formatter):

    INFO_FORMAT = (
        "%(asctime)s %(name)-8s %(levelname)-7s %(message)s"
    )

    DETAILED_FORMAT = (
        "%(asctime)s %(name)-8s %(levelname)-7s "
        "%(message)s "
        "[%(filename)s.%(funcName)s(L%(lineno)s)]"
    )

    def format(self, record):
        if record.levelno in (logging.INFO, STATUS_LEVEL):
            self._style._fmt = self.INFO_FORMAT
        else:
            self._style._fmt = self.DETAILED_FORMAT

        return super().format(record)

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def configure_stdout_logging(logger: logging.Logger) -> None:
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(StdoutStyleFormatter())
        logger.addHandler(handler)

    logger.propagate = False


def _attach_file_handler(logger: logging.Logger, full_log_path: Path, log_level: str = "INFO") -> None:
    """Add/replace a FileHandler on an already-configured logger without touching
    its existing handlers (e.g. the stdout StreamHandler set up before this call)."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(full_log_path)
    file_handler.setLevel(log_level)
    for handler in logger.handlers:
        if handler.formatter is not None:
            file_handler.setFormatter(handler.formatter)
            break
    logger.addHandler(file_handler)


def _remove_console_handlers(logger: logging.Logger) -> None:
    """Remove handlers that write to a stream (e.g. stdout/stderr) but are not
    file handlers. FileHandler is itself a StreamHandler subclass, so this
    excludes FileHandler instances explicitly rather than relying on isinstance."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)


def get_fcst_mgr_logger() -> ewts.EwtsLogger | logging.Logger:
    if EWTS_AVAILABLE:
        return ewts.get_logger(FCST_MGR_ID)
    return logging.getLogger(FCST_MGR_ID)


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
    LOG = get_fcst_mgr_logger()

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


def initialize_logger(log_path: str | None = None, log_id: str | None = None) -> tuple[ewts.EwtsLogger | logging.Logger, Path | None]:
    '''
    Set up logger.

    Arguments
    ---------
    log_path: optional log directory path. If not provided, no default
        directory or filename is resolved -- logging goes to stdout only
        (or, if EWTS is available, whatever EWTS itself does for log_dir=None).
    log_id: optional identifier appended to the log filename; only used when
        log_path is provided.

    Returns
    -------
    ewts.EwtsLogger | logging.Logger
        Instance of the EWTS logger; or, if EWTS is unavailable, a plain Python
        logger writing to the given log_path if one was provided, or to stdout
        only if it was not.
    Path | None
        The resolved log *file* path (not log *dir*), or None if log_path was
        not provided.
    '''
    if log_path is None:
        log_file_dir = None
        log_file_name = None
        log_file_path = None
    else:
        log_file_dir = Path(log_path)
        log_file_name = f"fcst_mgr_{log_id}.log" if log_id else "fcst_mgr.log"
        log_file_path = log_file_dir / log_file_name

        # In certain conditions the log dir does not yet exist
        os.makedirs(log_file_dir, exist_ok=True)

    if EWTS_AVAILABLE:
        # In case the logger was previously setup for bootstrapping
        ewts.logger.reset_logger(FCST_MGR_ID)

        return ewts.logger.setup_logger(
            FCST_MGR_ID,
            level="INFO",
            log_dir=log_file_dir,
            log_file_name=log_file_name,
            running_in_ngen=False,
            enabled=True,
        ), log_file_path

    logger = logging.getLogger(FCST_MGR_ID)
    configure_stdout_logging(logger)
    if log_file_path is not None:
        _attach_file_handler(logger, log_file_path, "INFO")
        _remove_console_handlers(logger)
    return logger, log_file_path


def initialize_hindcast_logger(log_path: str) -> ewts.EwtsLogger | logging.Logger:
    '''
    Set up the dedicated hindcast logger, which persists for the duration of a run_hindcast() workflow

    Arguments
    ---------
    log_path: Directory to write hindcast log (hindcast run's root folder).

    Returns
    -------
    ewts.EwtsLogger | logging.Logger
        Instance of the EWTS logger, or a plain Python logger writing to a file
        under log_path if EWTS is unavailable.
    '''
    log_file_name = "fcst_mgr_hindcast.log"

    if EWTS_AVAILABLE:
        return ewts.logger.setup_logger(
            HINDCAST_LOGGER_ID,
            level="INFO",
            log_dir=Path(log_path),
            log_file_name=log_file_name,
            running_in_ngen=False,
            enabled=True,
        )

    log_file_dir = Path(log_path)
    log_file_path = log_file_dir / log_file_name
    os.makedirs(log_file_dir, exist_ok=True)

    logger = logging.getLogger(HINDCAST_LOGGER_ID)
    configure_stdout_logging(logger)
    _attach_file_handler(logger, log_file_path, "INFO")
    _remove_console_handlers(logger)
    return logger
