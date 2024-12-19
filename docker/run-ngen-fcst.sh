#!/bin/bash

# Run script for run_ngen_fcst.py
#
# It is used by CerfServer directly when running in LOCAL mode.
# It is used by the ngen-fcst docker container when the server is running in DOCKER or PARALLEL_WORKS mode

FORECAST_SCRIPT=/ngen-app/ngen-fcst/python/run_ngen_fcst.py

# Set the umask so files and directories are created with 777 permissions
umask 000

# Function to display help message
show_help() {
  echo "Usage: $(basename "$0") \<command\> \<forcing_file\> \<config_file\> \<output_dir\> [stdout_file] [venv_path]"
  echo ""
  echo ""
  echo "COMMAND:"
  echo "  forecast          Run forecast script."
  echo ""
  echo "FORCING_FILE: Path to the NetCDF forcing file."
  echo "CONFIG_FILE: Path to the config yaml file for a validation run (from ngen-cal)."
  echo "OUTPUT_DIR: Path to the folder to be created for storing inputs/outputs from running ngen."
  echo "STDOUT_FILE (optional): Path to the stdout file where the script's console output will be saved.  Used when running in LOCAL or DOCKER environment"
  echo "VENV_PATH (optional): Path to the Python virtual environment.  Used when running in the LOCAL environment."
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") forecast test_data/forcing.nc test_data/valid_config.yaml fcst_run1"
  echo "  $(basename "$0") forecast test_data/forcing.nc test_data/valid_config.yaml fcst_run1 /path/to/output/ngen-fcst.log /path/to/venv"
  echo ""
  exit 1
}

# Show help if the user requests it with --help or -h
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  show_help
fi

# Check if the command for the script is provided as the first argument
if [ -z "$1" ]; then
  echo "Error: No script command provided. Allowable commands are: 'forecast'."
  show_help
fi

# Get the script command and select the corresponding script path
SCRIPT_COMMAND=$1
shift 1

case "$SCRIPT_COMMAND" in
  "forecast")
    SCRIPT_PATH=$FORECAST_SCRIPT
    REQUIRED_ARGS=3
    ;;
  *)
    echo "Error: Invalid script command: '$SCRIPT_COMMAND'.   Use 'calibration', 'validation', 'validation_iteration' or 'create_input'."
    show_help
    ;;
esac

# Check if the selected script exists
if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Error: Script not found at $SCRIPT_PATH"
  exit 1
fi

# Check if the correct number of arguments are provided for the selected command
if [ $# -lt $REQUIRED_ARGS ]; then
  echo "Error: Insufficient arguments. $SCRIPT_COMMAND requires $REQUIRED_ARGS arguments."
  show_help
fi

FORCING_FILE=$1
CONFIG_FILE=$2
OUTPUT_DIR=$3
shift $REQUIRED_ARGS

echo "FORCING_FILE: ${FORCING_FILE}"
echo "CONFIG_FILE: ${CONFIG_FILE}"
echo "OUTPUT_DIR: ${OUTPUT_DIR}"

# Check if the forcing data exists
if [ ! -f "${FORCING_FILE}" ]; then
  echo "Forcing data not found at ${FORCING_FILE}"
fi

# Check if the configuration file exists
if [ ! -f "${CONFIG_FILE}" ]; then
  echo "Configuration file not found at ${CONFIG_FILE}"
fi

if [ $# -ge 1 ]; then
  STDOUT_FILE=$1
  echo "Output file: $STDOUT_FILE"

  # Create output directory if it doesn't exist
  STDOUT_DIR=$(dirname "$STDOUT_FILE")
  if [ ! -d "$STDOUT_DIR" ]; then
    mkdir --parents "$STDOUT_DIR"
  fi

  shift 1
fi

if [ $# -ge 1 ]; then
  VENV_PATH=$1
  echo "Virtual environment: $VENV_PATH"
  shift 1
fi

# Activate the virtual environment if provided
if [ -n "$VENV_PATH" ]; then
  if [ -d "$VENV_PATH/bin" ]; then
    source "$VENV_PATH/bin/activate"
  else
    echo "Error: Virtual environment path '$VENV_PATH' is invalid."
    exit 1
  fi
else
  echo "No virtual environment provided, running with default Python environment."
fi

# Run the Python script, redirecting its output if an output file is provided
echo "   Running $(basename "$SCRIPT_PATH") with input file: $CONFIG_FILE"
if [ -z "$STDOUT_FILE" ]; then
  python "${SCRIPT_PATH}" "${FORCING_FILE}" "${CONFIG_FILE}" "${STDOUT_DIR}"
else
  python "${SCRIPT_PATH}" "${FORCING_FILE}" "${CONFIG_FILE}" "${STDOUT_DIR}" &> "${STDOUT_FILE}"
fi

python_exit_code=$?
if [ $python_exit_code -ne 0 ]; then
  echo "$(basename "$SCRIPT_PATH") exited with code $python_exit_code"
fi

# Display output if redirected to a file
if [ -n "$STDOUT_FILE" ]; then
  echo "Output from running $(basename "$SCRIPT_PATH")"
  echo "-------------- start of $STDOUT_FILE -----------------------------"
  cat "$STDOUT_FILE"
  echo "---------------- end of $STDOUT_FILE -----------------------------"
fi

echo "Done running $(basename "$SCRIPT_PATH")"

exit $python_exit_code
