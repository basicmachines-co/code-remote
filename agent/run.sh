#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/.env"
source "$SCRIPT_DIR/.venv/bin/activate"
export RELAY_URL AUTH_TOKEN
python3 "$SCRIPT_DIR/agent.py"
