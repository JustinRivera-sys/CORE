#!/bin/bash
# Abre el panel de control del proyecto (usa el entorno virtual del proyecto)
cd "$(dirname "$0")"
exec "$HOME/IA/venv/bin/python" panel_universidad.py
