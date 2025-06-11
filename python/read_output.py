import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import netCDF4

def read_troute_output(
        gage0: str,
        cwt_file:Path,
        gpkg_file: Path,
        out_file:Path,
) -> pd.DataFrame:

    """
    Arguments:
    ---------
    gage0: gage ID to retrieve streamflow simulations for
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
    catchment_hydro_fabric = gpd.read_file(gpkg_file, layer='divides')
    catchment_hydro_fabric.set_index('id', inplace=True)
    nexus_id = catchment_hydro_fabric.loc[x_walk.index[0].replace('cat', 'wb')]['toid']
    wb_lst = [x.split('-')[1] for x in list(catchment_hydro_fabric.query('toid==@nexus_id').index)]

    # read troute output
    ncvar = netCDF4.Dataset(out_file, "r")
    fid_index = [list(ncvar['feature_id'][0:]).index(int(fid)) for fid in wb_lst]
    output = pd.DataFrame(data={'sim_flow': pd.DataFrame(ncvar['flow'][fid_index], index=fid_index).T.sum(axis=1)})
    t0 = pd.to_datetime(ncvar.file_reference_time, format="%Y-%m-%d_%H:%M:%S")
    output.index = [t0 + pd.Timedelta(seconds=int(t1)) for t1 in ncvar['time']]
    output.index.name = 'Time'

    return output