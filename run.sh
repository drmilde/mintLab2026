#!/bin/sh
# Startet den Comic Maker mit dem Python-3.10-venv dieses Ordners.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python app.py
fi
exec python3.10 app.py
