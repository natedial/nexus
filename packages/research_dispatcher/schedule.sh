#!/bin/bash

# Research Dispatch - Scheduler Script
# This script activates the virtual environment and runs the main script
# Use this with cron or other scheduling systems

# Change to script directory
cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Run the main script
python src/main.py

# Optional: Log output with timestamp
# python src/main.py >> logs/research_dispatch_$(date +\%Y\%m\%d).log 2>&1
