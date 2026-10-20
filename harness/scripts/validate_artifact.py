#!/usr/bin/env python3
"""Deterministic helper: validate artifact JSON file syntax and basic structure."""
import json
import sys
from pathlib import Path


def validate(path: Path) -> int:
    if not path.is_file():
        print(f"ERROR: {path} is not a file")
        return 1
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print("ERROR: artifact must be a JSON object")
            return 1
        print(f"VALID: {path.name} parsed successfully ({len(data)} root keys)")
        return 0
    except Exception as exc:
        print(f"INVALID: {path.name} failed parsing: {exc}")
        return 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 validate_artifact.py <path_to_json>")
        sys.exit(1)
    sys.exit(validate(Path(sys.argv[1])))
