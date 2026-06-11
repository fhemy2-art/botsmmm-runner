"""
SMM Bot — Entry point.
This file redirects to the modular version in smm_bot/ directory.
"""
import sys
import os
import asyncio

# Add the smm_bot package directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "smm_bot"))

from main import main

if __name__ == "__main__":
    asyncio.run(main())
