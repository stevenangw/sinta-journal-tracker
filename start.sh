#!/bin/bash

# Initialize database if it doesn't exist
if [ ! -f "sinta_tracker.db" ]; then
    echo "Database not found. Initializing database..."
    python sinta_tracker.py --init
fi

# Start the background scraping loop daemon
echo "Starting SINTA tracker daemon in the background..."
python sinta_tracker.py --loop &

# Start the Flask dashboard
echo "Starting Flask web dashboard..."
python dashboard.py
