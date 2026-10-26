#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .devcontainer/environment.sh
if [[ ! -x .venv/bin/python ]]; then python -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py compile_translations
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py check
.venv/bin/python manage.py test --noinput
