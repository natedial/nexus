#!/bin/bash

# Research Dispatch - Scheduler Script
# This script activates the virtual environment and runs the main script
# Use this with cron or other scheduling systems

# Change to script directory
cd "$(dirname "$0")"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
  . .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  . venv/bin/activate
else
  echo "No virtualenv found at .venv/bin/activate or venv/bin/activate" >&2
  exit 1
fi

# Run the main script
python src/main.py

# Optional: Log output with timestamp
# python src/main.py >> logs/research_dispatch_$(date +\%Y\%m\%d).log 2>&1
