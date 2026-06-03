#!/bin/bash

LOG_PREFIX="[run-ngen-fcst.sh]"

# This shell script lives in the nwm-fcst-mgr repo.
# It is used by CerfServer runtime containers to invoke nwm-fcst-mgr scripts.

VALID_COMMANDS=("cold_start" "forecast" "hindcast")

SCRIPT_MODULE=nwm_fcst_mgr.forecast
FORECAST_SUBCOMMAND=run_forecast
HINDCAST_SUBCOMMAND=run_hindcast
COLD_START_SUBCOMMAND=run_forecast

# Set the umask so files and directories are created with 777 permissions
umask 000

show_help() {
  echo "Usage: $(basename "$0") <command> <args...> [stdout_file]"
  echo ""
  echo "COMMAND:"
  echo "  forecast    Run forecast script."
  echo "  cold_start  Run cold start script."
  echo "  hindcast    Run hindcast script."
  echo ""
  echo "FORECAST:"
  echo "  $(basename "$0") forecast --valid_yaml <validation_yaml> <forecast_realization> [stdout_file]"
  echo ""
  echo "COLD_START:"
  echo "  $(basename "$0") cold_start --valid_yaml <validation_yaml> <cold_start_realization> [stdout_file]"
  echo ""
  echo "HINDCAST:"
  echo "  $(basename "$0") hindcast --valid_yaml <validation_yaml> <input_config> <my_hindcast_run> <interval_cycle> <num_iterations> [cold_start_state] [stdout_file]"
  echo ""
  echo "VALIDATION_YAML: Path to the config yaml file for a validation run."
  echo "FORECAST_REALIZATION: Required for forecast. Path to the forecast realization file."
  echo "COLD_START_REALIZATION: Required for cold_start. Path to the cold start realization file."
  echo "INPUT_CONFIG: Required for hindcast. Path to the hindcast input config file."
  echo "MY_HINDCAST_RUN: Required for hindcast. Path to the directory for this run."
  echo "INTERVAL_CYCLE: Required for hindcast. Cycle interval in hours, e.g., 3."
  echo "NUM_ITERATIONS: Required for hindcast. Iterations, e.g., 10."
  echo "COLD_START_STATE: Optional for hindcast. Path to the cold start state directory."
  echo "STDOUT_FILE: Optional path where script console output will be saved."
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") forecast --valid_yaml validation.yaml realization.yaml"
  echo "  $(basename "$0") cold_start --valid_yaml validation.yaml cold_start_realization.yaml"
  echo "  $(basename "$0") hindcast --valid_yaml validation.yaml input.config hindcast_5 3 10"
  echo "  $(basename "$0") hindcast --valid_yaml validation.yaml input.config hindcast_5 3 10 /path/to/cold_start_state"
  echo "  $(basename "$0") hindcast --valid_yaml validation.yaml input.config hindcast_5 3 10 /path/to/cold_start_state /path/to/output.log"
  echo ""
  exit 1
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  show_help
fi

if [ -z "$1" ]; then
  echo "$LOG_PREFIX Error: No script command provided. Allowable commands are: ${VALID_COMMANDS[*]}."
  show_help
fi

SCRIPT_COMMAND=$1
shift 1

case "$SCRIPT_COMMAND" in
  "forecast")
    SUBCOMMAND=$FORECAST_SUBCOMMAND
    REQUIRED_ARGS=2
    ;;
  "cold_start")
    SUBCOMMAND=$COLD_START_SUBCOMMAND
    REQUIRED_ARGS=2
    ;;
  "hindcast")
    SUBCOMMAND=$HINDCAST_SUBCOMMAND
    REQUIRED_ARGS=5
    ;;
  *)
    echo "$LOG_PREFIX Error: Invalid script command: '$SCRIPT_COMMAND'. Allowable commands are: ${VALID_COMMANDS[*]}."
    show_help
    ;;
esac

if [ $# -lt "$REQUIRED_ARGS" ]; then
  echo "$LOG_PREFIX Error: Insufficient arguments. $SCRIPT_COMMAND requires $REQUIRED_ARGS arguments."
  show_help
fi

COLD_START_STATE=""

if [ "$SCRIPT_COMMAND" == "hindcast" ]; then
  VALIDATION_YAML=$1
  INPUT_CONFIG=$2
  MY_HINDCAST_RUN=$3
  INTERVAL_CYCLE=$4
  NUM_ITERATIONS=$5
  shift 5

  if [ $# -ge 1 ]; then
    COLD_START_STATE=$1
    shift 1
  fi

  echo "$LOG_PREFIX VALIDATION_YAML: $VALIDATION_YAML"
  echo "$LOG_PREFIX INPUT_CONFIG: $INPUT_CONFIG"
  echo "$LOG_PREFIX MY_HINDCAST_RUN: $MY_HINDCAST_RUN"
  echo "$LOG_PREFIX INTERVAL_CYCLE: $INTERVAL_CYCLE"
  echo "$LOG_PREFIX NUM_ITERATIONS: $NUM_ITERATIONS"

  if [ -n "$COLD_START_STATE" ]; then
    echo "$LOG_PREFIX COLD_START_STATE: $COLD_START_STATE"
  fi
else
  VALIDATION_YAML=$1
  REALIZATION_FILE=$2
  shift 2

  echo "$LOG_PREFIX VALIDATION_YAML: $VALIDATION_YAML"
  echo "$LOG_PREFIX REALIZATION_FILE: $REALIZATION_FILE"
fi

if [[ ! -f "$VALIDATION_YAML" && ! -d "$VALIDATION_YAML" ]]; then
  echo "$LOG_PREFIX Fatal: Config file not found at $VALIDATION_YAML"
  exit 1
fi

if [ "$SCRIPT_COMMAND" == "hindcast" ]; then
  if [ ! -f "$INPUT_CONFIG" ]; then
    echo "$LOG_PREFIX Fatal: Hindcast input config file not found at $INPUT_CONFIG"
    exit 1
  fi

  if [ -n "$COLD_START_STATE" ] && [[ ! -f "$COLD_START_STATE" && ! -d "$COLD_START_STATE" ]]; then
    echo "$LOG_PREFIX Fatal: Cold start state path not found at $COLD_START_STATE"
    exit 1
  fi
else
  if [ ! -f "$REALIZATION_FILE" ]; then
    if [ "$SCRIPT_COMMAND" == "forecast" ]; then
      echo "$LOG_PREFIX Fatal: Forecast realization file not found at $REALIZATION_FILE"
    else
      echo "$LOG_PREFIX Fatal: Cold start realization file not found at $REALIZATION_FILE"
    fi
    exit 1
  fi
fi

STDOUT_FILE=""
if [ $# -ge 1 ]; then
  STDOUT_FILE=$1
  shift 1

  echo "$LOG_PREFIX Output file: $STDOUT_FILE"

  STDOUT_DIR=$(dirname "$STDOUT_FILE")
  mkdir --parents "$STDOUT_DIR"
fi

if [ $# -gt 0 ]; then
  echo "$LOG_PREFIX Error: Unexpected extra arguments: $*"
  show_help
fi

if [ "$SCRIPT_COMMAND" == "hindcast" ]; then
  echo "$LOG_PREFIX Running $SCRIPT_MODULE $SUBCOMMAND with inputs: $VALIDATION_YAML $INPUT_CONFIG $MY_HINDCAST_RUN $INTERVAL_CYCLE $NUM_ITERATIONS"

  HINDCAST_ARGS=(
    -m "$SCRIPT_MODULE" "$SUBCOMMAND"
    --valid_yaml "$VALIDATION_YAML"
    "$INPUT_CONFIG"
    "$MY_HINDCAST_RUN"
    "$INTERVAL_CYCLE"
    "$NUM_ITERATIONS"
  )

  if [ -n "$COLD_START_STATE" ]; then
    echo "$LOG_PREFIX Including cold start state: $COLD_START_STATE"
    HINDCAST_ARGS+=("--cold_start_state" "$COLD_START_STATE")
  fi

  if [ -z "$STDOUT_FILE" ]; then
    python "${HINDCAST_ARGS[@]}"
  else
    python "${HINDCAST_ARGS[@]}" > "$STDOUT_FILE" 2>&1
  fi
else
  echo "$LOG_PREFIX Running $SCRIPT_MODULE $SUBCOMMAND with inputs: $VALIDATION_YAML $REALIZATION_FILE"

  if [ -z "$STDOUT_FILE" ]; then
    python -m "$SCRIPT_MODULE" "$SUBCOMMAND" --valid_yaml "$VALIDATION_YAML" "$REALIZATION_FILE"
  else
    python -m "$SCRIPT_MODULE" "$SUBCOMMAND" --valid_yaml "$VALIDATION_YAML" "$REALIZATION_FILE" > "$STDOUT_FILE" 2>&1
  fi
fi

python_exit_code=$?

if [ $python_exit_code -ne 0 ]; then
  echo "$LOG_PREFIX $SCRIPT_MODULE $SUBCOMMAND exited with code $python_exit_code"
fi

if [ -n "$STDOUT_FILE" ]; then
  echo "$LOG_PREFIX Output from running $SCRIPT_MODULE $SUBCOMMAND"
  echo "-------------- start of $STDOUT_FILE -----------------------------"
  cat "$STDOUT_FILE"
  echo "---------------- end of $STDOUT_FILE -----------------------------"
fi

echo "$LOG_PREFIX Done running $SCRIPT_MODULE $SUBCOMMAND"

exit $python_exit_code
