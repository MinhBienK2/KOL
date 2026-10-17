#!/usr/bin/env python3
"""Convenience CLI wrapper for Chief AI Commercial Director."""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.director import main

if __name__ == "__main__":
    main()
