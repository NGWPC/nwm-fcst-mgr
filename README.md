# ngen-fcst



## Name
NGEN-FCST

## Description
A program to run ngen given the forecast forcing provided via a .nc file and a configuration file from validation with ngen-cal

## Installation
To run the program, one would need an environment for successfulyl running ngen and its modules (including t-route). Follow the following steps to build the environment (in AWS Ubuntu 22.04 LTS Workspace):

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

source [VENV_ROOT]/env.ngen/bin/activate
cd [NGEN-FCST_ROOT]/ngen-fcst
python python/run_ngen_fcst.py test_data/forcing.nc test_data/valid_config.yaml fcst_run1

where [NGEN-FCST_ROOT] is where ngen-fcst is installed

The program takes three command line arguments:
1) Path to the NetCDF forcing file
2) Path to the config yaml file for a validation run (from ngen-cal)
3) Path to the folder to be created for storing inputs/outputs from running ngen

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
