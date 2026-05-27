#!/bin/bash

# Initialize database if it doesn't exist
if [ ! -f "sinta_tracker.db" ]; then
    echo "Database not found. Seeding database from config..."
    python sinta_tracker.py --seed-from-config
fi

# Start the background scraping loop daemon
echo "Starting SINTA tracker daemon in the background..."
python sinta_tracker.py --loop &

# Start the Flask dashboard
echo "Starting Flask web dashboard..."
python dashboard.py
