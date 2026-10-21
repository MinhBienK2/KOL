#!/usr/bin/env python3
"""Golden checks the QA loop runs after every change to the harness, tools or gates.

Each case is a real past run with a known verdict. A change that lets a known-bad run pass (or a
known-good run fail) is a regression: revert it or fix it before the next round. Add a case to
``tests/fixtures/continuity/qa_golden.json`` (traces and reports under ``golden/``) whenever a round teaches a new failure.

    python3 tools/qa_regression.py [--skip-tests]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.continuity.chain import identity_consistency  # noqa: E402
from tools.agent_trace_audit import audit, load_trace  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "continuity" / "qa_golden.json"


def check_case(case: dict) -> list[str]:
    """Return the expectations this case breaks (empty when it still behaves as recorded)."""
    broken = []
    work = ROOT / case["work"]
    if "trace" in case:
        report = audit(load_trace(ROOT / case["trace"]), work)
        if report["process_ok"] != case["expect_process_ok"]:
            broken.append(f"process_ok={report['process_ok']} (expected {case['expect_process_ok']})")
        found = " | ".join(f["finding"] for f in report["findings"])
        broken += [f"audit no longer finds: {needle}" for needle in case.get("expect_findings", []) if needle not in found]
    if "expect_identity_passed" in case:
        ident = identity_consistency(work / "keyframes" / "shot_01_keyframe.png", work / "master.mp4")
        if bool(ident.get("passed")) != case["expect_identity_passed"]:
            broken.append(f"master identity passed={ident.get('passed')} similarity={ident.get('similarity')} "
                          f"(expected passed={case['expect_identity_passed']})")
    return broken


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)
    failures = 0
    for case in json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]:
        broken = check_case(case)
        failures += bool(broken)
        print(f"{'FAIL' if broken else 'ok  '} {case['name']}: {case['why']}")
        for b in broken:
            print(f"     - {b}")
    if not args.skip_tests:
        tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/"], cwd=ROOT, capture_output=True, text=True)
        print(f"{'ok  ' if tests.returncode == 0 else 'FAIL'} pytest: {tests.stdout.strip().splitlines()[-1] if tests.stdout else tests.stderr[-300:]}")
        failures += tests.returncode != 0
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
