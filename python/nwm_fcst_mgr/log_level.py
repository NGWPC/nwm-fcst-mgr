from datetime import datetime, timezone
from pathlib import Path

import ewts

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

def initialize_logger(log_path: str | None = None, log_id: str | None = None) -> ewts.EwtsLogger:
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
        bind_now=True,
    )

