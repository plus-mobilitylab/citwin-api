#!/bin/bash

# usage: start.sh [CONDA_ENV] [API_PORT] [API_ROOT_PATH]

CONDA_ENV="${1:-citwin-api}"
API_PORT="${2:-8000}"
API_ROOT_PATH="${3:-/}"

# activate conda environment
source /opt/miniconda3/bin/activate "$CONDA_ENV"

# change to app directory
cd "$(dirname "$0")" || exit

# start uvicorn server
python -m uvicorn api.api:app --host localhost --port "$API_PORT" --root-path "$API_ROOT_PATH" --workers 1
