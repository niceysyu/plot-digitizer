#!/usr/bin/env bash
# Plot Digitizer - macOS / Linux local build (Python 3.8+ with tkinter)
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
if [[ "$(uname)" == "Darwin" ]]; then
  pyinstaller --noconfirm --windowed --name PlotDigitizer plot_digitizer.py
  echo "Done: dist/PlotDigitizer.app"
else
  pyinstaller --noconfirm --onefile --name PlotDigitizer plot_digitizer.py
  echo "Done: dist/PlotDigitizer"
fi
