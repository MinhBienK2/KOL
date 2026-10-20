#!/usr/bin/env python3
"""Deterministic helper: audit run_result.json and render_report.json for recommended recovery."""
import json
import sys
from pathlib import Path


def audit_run(ws_root: Path) -> int:
    result_path = ws_root / "run_result.json"
    report_path = ws_root / "artifacts" / "render_report.json"
    if not result_path.exists():
        print("NO_RESULT: run_result.json not found")
        return 1
    with open(result_path, "r", encoding="utf-8") as f:
        res = json.load(f)
    print(f"STATUS: {res.get('status')} | EXIT: {res.get('exit_code')}")
    if res.get("exit_code") == 0:
        print("SUCCESS: Pipeline completed with all gates passed.")
        return 0
    if res.get("failed_stage"):
        print(f"FAILED_STAGE: {res.get('failed_stage')} -> recommend: --from-stage {res.get('failed_stage')}")
    for gate in res.get("failed_gates", []):
        print(f"FAILED_GATE: {gate.get('gate')} -> error: {gate.get('error')}")
    return int(res.get("exit_code", 1))


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    sys.exit(audit_run(path))
