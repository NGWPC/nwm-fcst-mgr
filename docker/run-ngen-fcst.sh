#!/bin/bash

# Define valid commands
VALID_COMMANDS=("cold_start" "forecast")

# This shell script lives in the nwm-fcst-mgr repo.  It is used by CerfServer when calling nwm-fcst-mgr
#
# It is used by CerfServer directly when running in LOCAL mode.
# It is used by the nwm-fcst-mgr docker container when the server is running in DOCKER or PARALLEL_WORKS mode

FORECAST_SCRIPT=nwm_fcst_mgr.forecast
COLD_START_SCRIPT=nwm_fcst_mgr.forecast

# Set the umask so files and directories are created with 777 permissions
umask 000

# Function to display help message
show_help() {
  echo "Usage: $(basename "$0") <command> <validation_yaml> <realization_file> [stdout_file] [venv_path]"
  echo ""
  echo "COMMAND:"
  echo "  forecast    Run forecast script (requires validation_yaml + forecast_realization)."
  echo "  cold_start  Run cold start script (requires validation_yaml + cold_start_realization)."
  echo ""
  echo "VALIDATION_YAML: Path to the config yaml file for a validation run (from MSWM)."
  echo "FORECAST_REALIZATION: (Required for forecast) Path to the forecast realization file."
  echo "COLD_START_REALIZATION: (Required for cold_start) Path to the cold start realization file."
  echo "STDOUT_FILE (optional): Path to the stdout file where the script's console output will be saved.  Used when running in LOCAL or DOCKER environment"
  echo "VENV_PATH (optional): Path to the Python virtual environment.  Used when running in the LOCAL environment."
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") forecast validation.yaml realization.yaml"
  echo "  $(basename "$0") cold_start validation.yaml cold_start_realization.yaml"
  echo "  $(basename "$0") forecast validation.yaml realization.yaml cold_start_realization.yaml"
  echo ""
  exit 1
}

# Show help if the user requests it with --help or -h
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  show_help
fi

# Check if the command for the script is provided as the first argument
if [ -z "$1" ]; then
  echo "[run-ngen-fcst.sh] Error: No script command provided. Allowable commands are: ${VALID_COMMANDS[*]}."
  show_help
fi

# Get the script command and select the corresponding script path
SCRIPT_COMMAND=$1
shift 1

case "$SCRIPT_COMMAND" in
  "forecast")
    SCRIPT_PATH=$FORECAST_SCRIPT
    REQUIRED_ARGS=2
    ;;
  "cold_start")
    SCRIPT_PATH=$COLD_START_SCRIPT
    REQUIRED_ARGS=2
    ;;
  *)
    echo "[run-ngen-fcst.sh] Error: Invalid script command: '$SCRIPT_COMMAND'. Allowable commands are: ${VALID_COMMANDS[*]}."
    show_help
    ;;
esac

# Check if the correct number of arguments are provided for the selected command
if [ $# -lt $REQUIRED_ARGS ]; then
  echo "[run-ngen-fcst.sh] Error: Insufficient arguments. $SCRIPT_COMMAND requires $REQUIRED_ARGS arguments."
  show_help
fi

VALIDATION_YAML=$1
REALIZATION_FILE=$2
shift 2

echo "[run-ngen-fcst.sh]  VALIDATION_YAML: ${VALIDATION_YAML}"
echo "[run-ngen-fcst.sh] REALIZATION_FILE: ${REALIZATION_FILE}"

# File existence checks (fatal if missing)
if [[ ! -f "${VALIDATION_YAML}" && ! -d "${VALIDATION_YAML}" ]]; then
  echo "[run-ngen-fcst.sh] Fatal: Config file not found at ${VALIDATION_YAML}"
  exit 1
fi

if [ ! -f "${REALIZATION_FILE}" ]; then
  if [ "$SCRIPT_COMMAND" == "forecast" ]; then
    echo "[run-ngen-fcst.sh] Fatal: Forecast realization file not found at ${REALIZATION_FILE}"
  else
    echo "[run-ngen-fcst.sh] Fatal: Cold start realization file not found at ${REALIZATION_FILE}"
  fi
  exit 1
fi

# Handle optional stdout file
STDOUT_FILE=""
if [ $# -ge 1 ]; then
  STDOUT_FILE=$1
  echo "[run-ngen-fcst.sh] Output file: $STDOUT_FILE"

  # Create output directory if it doesn't exist
  STDOUT_DIR=$(dirname "$STDOUT_FILE")
  if [ ! -d "$STDOUT_DIR" ]; then
    mkdir --parents "$STDOUT_DIR"
  fi

  shift 1
fi

# Handle optional virtual environment
VENV_PATH=""
if [ $# -ge 1 ]; then
  VENV_PATH=$1
  echo "[run-ngen-fcst.sh] Virtual environment: $VENV_PATH"
  shift 1
fi

# Activate the virtual environment if provided
if [ -n "$VENV_PATH" ]; then
  if [ -d "$VENV_PATH/bin" ]; then
    source "$VENV_PATH/bin/activate"
  else
    echo "[run-ngen-fcst.sh] Fatal: Virtual environment path '$VENV_PATH' is invalid."
    exit 1
  fi
else
  echo "[run-ngen-fcst.sh] No virtual environment provided, running with default Python environment."
fi

# Run the Python script, redirecting its output if an output file is provided
echo "[run-ngen-fcst.sh] Running $SCRIPT_PATH ($SCRIPT_COMMAND) with inputs: ${VALIDATION_YAML} ${REALIZATION_FILE}"

if [ -z "$STDOUT_FILE" ]; then
  python -m $SCRIPT_PATH "$VALIDATION_YAML" "$REALIZATION_FILE"
else
  python -m $SCRIPT_PATH "$VALIDATION_YAML" "$REALIZATION_FILE" &> "$STDOUT_FILE" 2>&1
fi

python_exit_code=$?
if [ $python_exit_code -ne 0 ]; then
  echo "[run-ngen-fcst.sh] $SCRIPT_PATH exited with code $python_exit_code"
fi

# Display output if redirected to a file
if [ -n "$STDOUT_FILE" ]; then
  echo "Output from running $SCRIPT_PATH"
  echo "-------------- start of $STDOUT_FILE -----------------------------"
  cat "$STDOUT_FILE"
  echo "---------------- end of $STDOUT_FILE -----------------------------"
fi

echo "[run-ngen-fcst.sh] Done running $SCRIPT_PATH"

exit $python_exit_code
