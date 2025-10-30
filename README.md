# nwm-fcst-mgr

## Description
A program to execute forecast and hindcast runs runs provided a configuration file from a past calibration run by the nwm-cal-mgr.

## Installation

### Clone nwm-fcst-mgr

git clone -b development --recurse-submodules https://github.com/NGWPC/nwm-fcst-mgr.git

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
2. cd [NWM-FCST-MGR_ROOT]/nwm-fcst-mgr
3. pip install .

where [NWM-FCST-MGR_ROOT] is where nwm-fcst-mgr is installed.

#### Forecast Run

The program takes four arguments for a forecast run:
1) input_path: Path to input.config file for forecast
2) valid_yaml: Path to the config yaml file for a validation run (from nwm-cal-mgr)
3) fcst_run_name: Name of the folder to be created for storing inputs/outputs from running ngen
4) --use_cold_start: Optional boolean flag to enable a cold start run

Nwm-fcst-mgr in forecast mode can be run from the CLI or from Python code directly. The forecast manager will automatically handle calls to the Model Setup Workflow Manager to setup cold start and forecast runs and execute those runs through calls to Ngen.

### Python
1. from nwm_fcst_mgr.forecast import fcst_workflow
2. input_path = '/home/jeff.wade/ngwpc/run_ngen/cold_start_workflow/input_forecast.config'
3. valid_yaml = '/home/jeff.wade/ngwpc/run_ngen/kge_dds/noah_cfes/01123000/Output/Validation_Run/01123000_config_valid_best.yaml'
4. fcst_run_name = 'fcst_run1'
5. use_cold_start = True
6. fcst_workflow(input_path=input_path, valid_yaml=valid_yaml, fcst_run_name=fcst_run_name, use_cold_start=True)


### CLI
python -m nwm_fcst_mgr.forecast fcst_workflow input_path valid_yaml fcst_run_name --use_cold_start

where the arguments are replaced by the paths above.

#### Hindcast Run

The program takes six arguments for a hindcast run:
1) input_path: Path to input.config file for forecast
2) valid_yaml: Path to the config yaml file for a validation run (from nwm-cal-mgr)
3) fcst_run_name: Name of the folder to be created for storing inputs/outputs from running ngen
4) cycle_interval: Cycle interval (in hours) between consecutive hindcast runs
5) num_intervals: Number of hindcast intervals to run
6) --use_cold_start: Optional boolean flag to enable a cold start run
7) --use_int_ana: Optional boolean flag to enable an intermediate ana run

Nwm-fcst-mgr in hindcast mode can be run from the CLI or from Python code directly. The hindcast manager will automatically handle calls to the Model Setup Workflow Manager to setup cold start, intermediate AnA, and hindcast runs and execute those runs through calls to Ngen.

### Python
1. from nwm_fcst_mgr.forecast import hindcast_workflow
2. input_path = '/home/jeff.wade/ngwpc/run_ngen/cold_start_workflow/input_forecast.config'
3. valid_yaml = '/home/jeff.wade/ngwpc/run_ngen/kge_dds/noah_cfes/01123000/Output/Validation_Run/01123000_config_valid_best.yaml'
4. fcst_run_name = 'hindcast_run1'
5. cycle_interval = 3
6. num_intervals = 6
7. use_cold_start = True
8. use_int_ana = True

8. hindcast_workflow(input_path=input_path, valid_yaml=valid_yaml, fcst_run_name=fcst_run_name, cycle_interval=cycle_interval, num_intervals=num_intervals, use_cold_start=True, use_int_ana=True)


### CLI
python -m nwm_fcst_mgr.forecast hindcast_workflow input_path valid_yaml fcst_run_name cycle_interval num_intervals --use_cold_start

where the arguments are replaced by the paths above.


## Docker container

### Requirements

To build and run nwm-fcst-mgr, you will need the following software installed and running on your system:
- Docker Engine

### Build

To build the nwm-fcst-mgr container, execute the following command:
```
docker build --tag=nwm-fcst-mgr .
```

### Running


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
