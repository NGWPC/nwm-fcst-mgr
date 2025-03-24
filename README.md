# ngen-fcst



## Name
ngen Forecast

## Description
A program to run ngen given the forecast forcing provided via a .nc file and a configuration file from validation with ngen-cal

## Installation

### Clone ngen-fcst

git clone -b development --recurse-submodules https://gitlab.sh.nextgenwaterprediction.com/NGWPC/nwm-ngen/ngen-fcst.git

### Build the environment

To run the program, one would need an environment for successfully running ngen and its modules (including t-route).

If you already have an environment for running ngen, you can use the same venv and pip install matplotlib if it is not already installed.

Otherwise, follow the following steps to build a new environment (in AWS Ubuntu 22.04 LTS Workspace):

1) cd [VENV_ROOT]
2) /usr/bin/python3.11 -m venv venv.ngen
3) source venv.ngen/bin/activate
4) pip install --upgrade pip
5) pip3 install numpy==1.26.4 pandas bmipy netcdf4==1.6.3 joblib toolz Cython geopandas pyarrow matplotlib deprecated 
6) cd [NGEN_ROOT]/ngen/extern/t-route/
7) pip install -r requirements.txt
8) ./compiler.sh 

where [VENV_ROOT] and [NGEN_ROOT] refer to the directory to install the python virtual environment and the root directory where ngen is installed, respectively.

## Usage

Follow the following steps to test the program:

1. source [VENV_ROOT]/env.ngen/bin/activate
2. cd [NGEN-FCST_ROOT]/ngen-fcst
3. python python/run_ngen_fcst.py test_data/forcing.nc test_data/valid_config.yaml fcst_run1

where [NGEN-FCST_ROOT] is where ngen-fcst is installed

The program takes three command line arguments:
1) Path to the NetCDF forcing file or folder containing csv forcing files for all catchments in the basin
2) Path to the config yaml file for a validation run (from ngen-cal)
3) Path to the folder to be created for storing inputs/outputs from running ngen, relative to the Output directory of the calibration run as indicated in the config yaml file. For example, if "fcst_run1" is the 3rd argument, and "yaml_file" in the "general" section of the config file is '/home/yuqiong.liu/work/Gitlab/run/kge_DDS/noah_cfes/01123000/Output/Validation_Run/01123000_config_valid_best.yaml', then the new output directory to be created for the ngen-fcst run would be:

/home/yuqiong.liu/work/Gitlab/run/kge_DDS/noah_cfes/01123000/Output/Forecast_Run/fcst_run1

## Docker container

### Requirements

To build and run ngen-fcst, you will need the following software installed and running on your system:
- Docker Engine

You will also need the following data:
- a forcing file in NetCDF format
- a YAML-formatted configuration file

### Build

To build the ngen-fcst container, execute the following command:
```
docker build --tag=ngen-fcst .
```

### Running

To run the ngen-fcst applicaton, execute the following command:
```
docker run ngen-fcst
```

This will print a usage statement for the container:
```
Usage: run-ngen-fcst.sh <forcing_file> <config_file> <output_path> [log_file] [venv_path]

FORCING_FILE: Path to the NetCDF forcing file or a folder containing csv forcing files for all catchments in the basin.
CONFIG_FILE: Path to the config yaml file for a validation run (from ngen-cal).
OUTPUT_PATH: Path to the folder to be created for storing inputs/outputs from running ngen.
LOG_FILE (optional): Path to the output file where the script's output will be saved.  Used when running in LOCAL or DOCKER environment
VENV_PATH (optional): Path to the Python virtual environment.  Used when running in the LOCAL environment.

Examples:
  run-ngen-fcst.sh test_data/forcing.nc test_data/valid_config.yaml fcst_run1
  run-ngen-fcst.sh test_data/forcing.nc test_data/valid_config.yaml fcst_run1 /path/to/output /path/to/venv
```

The path provided for any files should match the path within the container, as well as the paths insider your configuration file. So if `forcing.nc` is located at `~/ngencerf/data/ngen-cal-data/forcing/forcing.nc` and `valid_config.yaml` is located at `~/ngencerf/data/ngen-cal-data/configs/valid_config.yaml`, you should run the command:
```
docker run -v ~/ngencerf/data/ngen-cal-data/forcing/:/ngencerf/data/forcing/ -v  ~/ngencerf/data/ngen-cal-data/configs/:/ngencerf/data/configs/ ngen-fcst /ngencerf/data/forcing/forcing.nc /ngencerf/data/configs/valid_config.yaml fcst_run1
```

## Contributing
State if you are open to contributions and what your requirements are for accepting them.

For people who want to make changes to your project, it's helpful to have some documentation on how to get started. Perhaps there is a script that they should run or some environment variables that they need to set. Make these steps explicit. These instructions could also be useful to your future self.

You can also document commands to lint the code or run tests. These steps help to ensure high code quality and reduce the likelihood that the changes inadvertently break something. Having instructions for running tests is especially helpful if it requires external setup, such as starting a Selenium server for testing in a browser.

## Authors and acknowledgment
Show your appreciation to those who have contributed to the project.

## License
For open source projects, say how it is licensed.

## Project status
If you have run out of energy or time for your project, put a note at the top of the README saying that development has slowed down or stopped completely. Someone may choose to fork your project or volunteer to step in as a maintainer or owner, allowing your project to keep going. You can also make an explicit request for maintainers.
