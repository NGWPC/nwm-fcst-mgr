"""Utilities"""

import ewts
from os import environ

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
