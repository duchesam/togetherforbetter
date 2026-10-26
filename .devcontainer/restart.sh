#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .devcontainer/environment.sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py compile_translations
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python .devcontainer/start.py --restart
