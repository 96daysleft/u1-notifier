#!/usr/bin/env python3
"""
U1 Alert Notifier - Main Entry Point

A Python-based service that connects to a Snapmaker U1's Moonraker WebSocket
and sends real-time alert notifications to Discord via webhooks.
"""

import asyncio
import sys
from pathlib import Path

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.service import main

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Service interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to start service: {e}")
        sys.exit(1)
