#!/bin/zsh
set -e
cd "${0:A:h}"
export PYTHONPATH="$PWD/src"
exec .venv/bin/python scripts/configure_workbench.py
