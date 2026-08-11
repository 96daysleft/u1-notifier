#!/bin/bash
# Development script for running the U1 Alert Notifier

echo "🚀 Starting U1 Alert Notifier (Python)"
echo "📦 Installing dependencies..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Install requirements
venv/bin/pip install -r requirements.txt

echo "▶️ Starting service..."
venv/bin/python main.py
