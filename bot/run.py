"""Entry point for the SMM Telegram bot."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "smm_bot"))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "smm_bot"))

import asyncio
from main import main

if __name__ == "__main__":
    asyncio.run(main())

# build: 2026-05-07
