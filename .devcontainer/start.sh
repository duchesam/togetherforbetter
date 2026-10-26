#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .devcontainer/environment.sh
.venv/bin/python .devcontainer/start.py
