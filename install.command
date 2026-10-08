#!/bin/bash
# Double-clickable installer for Mocha Flame Export.
cd "$(dirname "$0")"
python3 install.py
echo "Press Return to close."
read _
