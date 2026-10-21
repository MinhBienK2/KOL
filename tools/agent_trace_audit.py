#!/usr/bin/env python3
"""Audit how a production agent (omp or agy) ran the video pipelines.

Reads the agent's own trace (an omp session ``.jsonl`` or an agy ``--output-format stream-json``
log), normalises it into tool calls, and checks the workflow of both production lines:

* ``tools/continuity_director.py`` (``harness/continuity_director.md``): step order, ``render --one``,
  looking at pictures before approving;
* ``tools/director.py`` (8 stages, ``harness/tool_guidance.md``): a ``--pause-after-stage`` review
  checkpoint on every run, opening the keyframes/clips before resuming past stages 4 and 5;

and for both: no edits to pipeline code, and no "ready" claim on a video that failed its gates. The QA loop (``harness/qa_loop_prompt.md``) runs it
after every round; findings are evidence for the process score, not a substitute for watching.

    python3 tools/agent_trace_audit.py --trace <session.jsonl|agy_stream.jsonl> --work <run dir> [--json]

``--work`` is the continuity ``work`` dir or the director run's ``artifacts`` dir.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

#: ``tools/director.py`` but not ``continuity_director.py``.
DIRECTOR_RE = re.compile(r"(?<![\w])director\.py\b([^\n]*)")
#: director.py stages whose output is pictures the agent must look at before going further.
DIRECTOR_VISUAL_STAGES = {3: "storyboard", 4: "keyframes", 5: "raw clips", 6: "synced clips", 7: "master"}
STEP_RE = re.compile(r"continuity_director\.py\s+(lint|keyframes|approve|render|rejudge|compose|verify|all)\b([^\n]*)")
#: Code the production agent must never change (it may only write its own run folder).
PROTECTED_PREFIXES = ("pipeline/", "tools/", "harness/", "tests/")
SHELL_WRITE_RE = re.compile(r"(sed\s+-i|>>?|tee|cp|mv|rm)\s+[^|;&]*?\b((?:pipeline|tools|harness|tests)/[\w./-]+)")
READY_RE = re.compile(r"ready to post|ready for (?:publish|posting|upload)|sẵn sàng đăng|đã sẵn sàng|shippable:\s*true",
                      re.IGNORECASE)
#: Exit codes that report a verdict, not a broken call: continuity_director 3 = needs review;
#: director.py 3 = verification gates failed, 4 = paused for review.
EXIT_REVIEW = 3
NON_ERROR_EXITS = {EXIT_REVIEW, 4}
KILLED_RE = re.compile(r"terminating \d+ background|\bKilled\b|timed out after|wall.?time limit|exited with code (124|137)",
                       re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(not|never|no)\b|chưa|không", re.IGNORECASE)
IMAGE_RE = re.compile(r"\.(png|jpe?g|webp)\b", re.IGNORECASE)


@dataclass
class Call:
    index: int
    tool: str
    command: str = ""
    path: str = ""
    output: str = ""
    error: bool = False
    seconds: Optional[float] = None
    viewed_image: bool = False
    exit_code: Optional[int] = None


@dataclass
class Trace:
    agent: str
    calls: List[Call] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)


def _rel(path: str) -> str:
    marker = "/KOL/"
    return path.split(marker, 1)[1] if marker in path else path


def parse_omp(path: Path) -> Trace:
    trace = Trace("omp")
    pending = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") or {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        if msg.get("role") == "assistant":
            for part in content:
                if part.get("type") == "text":
                    trace.texts.append(part.get("text", ""))
                elif part.get("type") == "toolCall":
                    args = part.get("arguments") or {}
                    target = str(args.get("path") or "")
                    if part["name"] == "edit":  # omp edit names the file as "[path#hash]" in its input
                        m = re.match(r"\[([^\]#]+)", str(args.get("input") or ""))
                        target = m.group(1) if m else target
                    call = Call(len(trace.calls), part["name"], command=str(args.get("command") or args.get("code") or ""),
                                path=_rel(target.split(":")[0]))
                    pending[part.get("id")] = call
                    trace.calls.append(call)
        elif msg.get("role") == "toolResult":
            call = pending.get(msg.get("toolCallId"))
            if call is None:
                continue
            call.output = "".join(p.get("text", "") for p in content if p.get("type") == "text")
            call.viewed_image = any(p.get("type") == "image" for p in content)
            details = msg.get("details") or {}
            call.exit_code = details.get("exitCode")
            call.error = bool(msg.get("isError")) and call.exit_code not in NON_ERROR_EXITS
            if details.get("wallTimeMs") is not None:
                call.seconds = details["wallTimeMs"] / 1000
    return trace


def parse_agy(path: Path) -> Trace:
    trace = Trace("agy")
    by_step = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("event") == "result":
            trace.texts.append((entry.get("result") or {}).get("response", ""))
            continue
        step = entry.get("step_update") or {}
        info = step.get("tool_info")
        if step.get("step_type") != "tool" or not info:
            continue
        params = info.get("parameters") or {}
        call = by_step.get(step["step_index"])
        if call is None:
            call = Call(len(trace.calls), info["name"], command=str(params.get("CommandLine") or ""),
                        path=_rel(str(params.get("Path") or params.get("TargetFile") or "")))
            by_step[step["step_index"]] = call
            trace.calls.append(call)
        if step.get("state") == "DONE":
            call.output = str(info.get("output") or "")
            call.seconds = step.get("duration_seconds")
            code = re.search(r"exited with code (\d+)", call.output)
            call.exit_code = int(code.group(1)) if code else None
            call.error = bool(call.exit_code) and call.exit_code not in NON_ERROR_EXITS
            call.viewed_image = call.tool == "read_file" and bool(IMAGE_RE.search(call.path))
    return trace


def load_trace(path: Path) -> Trace:
    head = path.read_text(encoding="utf-8")[:4000]
    return parse_agy(path) if '"step_update"' in head or '"event"' in head else parse_omp(path)


def _shot_of(args: str) -> Optional[str]:
    m = re.search(r"--shot\s+(\S+)", args)
    return m.group(1) if m else None


def _flag_value(args: str, flag: str) -> Optional[int]:
    m = re.search(rf"{flag}[=\s]+(\d+)", args)
    return int(m.group(1)) if m else None


def _director_step(args: str) -> dict:
    """Stage range one ``director.py`` call runs (``--check`` runs nothing)."""
    if "--check" in args:
        return {"step": "director --check", "first": None, "last": None}
    first = _flag_value(args, "--from-stage") or 1
    last = _flag_value(args, "--pause-after-stage") or 8
    return {"step": f"director {first}-{last}", "first": first, "last": last}


def _read_verdict(work: Optional[Path]) -> Optional[bool]:
    """Final gate verdict of the run: continuity verify_report or director render_report."""
    if not work:
        return None
    if (work / "verify_report.json").exists():
        return bool(json.loads((work / "verify_report.json").read_text(encoding="utf-8")).get("passed"))
    if (work / "render_report.json").exists():
        report = json.loads((work / "render_report.json").read_text(encoding="utf-8"))
        return report.get("overall_status") == "PASSED"
    return None


def audit(trace: Trace, work: Optional[Path]) -> dict:
    findings: List[dict] = []
    steps = []
    looked_since_render: set = set()
    viewed_any_since_render = False
    director_reached = 0
    last_run: Optional[tuple] = None

    def flag(severity: str, call: Call, text: str) -> None:
        findings.append({"severity": severity, "call": call.index, "finding": text})

    for call in trace.calls:
        if call.viewed_image or (call.tool in ("read", "read_file") and IMAGE_RE.search(call.path)):
            viewed_any_since_render = True
            looked_since_render.add(call.path)
        written = []
        if call.tool in ("edit", "write", "edit_file", "write_file", "replace_file_content", "write_to_file"):
            written.append(call.path)
        written += [m.group(2) for m in SHELL_WRITE_RE.finditer(call.command)]
        for target in written:
            if target.startswith(PROTECTED_PREFIXES):
                flag("critical", call, f"edited protected code {target} (agents must not change pipeline/tools/harness/tests)")
        d = DIRECTOR_RE.search(call.command)
        if d and not STEP_RE.search(call.command) and "--help" not in d.group(1):
            args = d.group(1)
            info = _director_step(args)
            steps.append({"call": call.index, "step": info["step"], "args": args.strip()[:160], "error": call.error,
                          "exit_code": call.exit_code, "seconds": None if call.seconds is None else round(call.seconds, 1)})
            if info["first"] is not None:
                if info["last"] - info["first"] >= 1 and "--pause-after-stage" not in args:
                    flag("major", call, f"director.py ran stages {info['first']}-8 with no --pause-after-stage review checkpoint")
                # what the previous run produced and nobody has looked at yet
                pending = [DIRECTOR_VISUAL_STAGES[s] for s in range(last_run[0], last_run[1] + 1)
                           if s in DIRECTOR_VISUAL_STAGES] if last_run else []
                if pending and not viewed_any_since_render:
                    flag("major", call, f"resumed director.py at stage {info['first']} without opening the "
                                        f"{', '.join(pending)} output first")
                if not call.error:
                    director_reached = max(director_reached, info["last"])
                    last_run = (info["first"], info["last"])
                looked_since_render, viewed_any_since_render = set(), False
                if KILLED_RE.search(call.output):
                    flag("major", call, "director.py run was killed by the agent's command time limit")
            continue
        m = STEP_RE.search(call.command)
        if not m:
            continue
        step, args = m.group(1), m.group(2)
        if "--help" in args:
            continue
        steps.append({"call": call.index, "step": step, "args": args.strip()[:160], "error": call.error,
                      "exit_code": call.exit_code,
                      "seconds": None if call.seconds is None else round(call.seconds, 1)})
        if step == "render":
            if "--one" not in args:
                flag("major", call, "render without --one: clips were paid for before anyone reviewed the previous one")
            looked_since_render, viewed_any_since_render = set(), False
            if KILLED_RE.search(call.output):
                flag("major", call, "render was killed by the agent's command time limit")
        if step == "approve":
            shot = _shot_of(args)
            saw_shot = any(shot and shot in p for p in looked_since_render)
            if not (saw_shot or viewed_any_since_render):
                flag("major", call, f"approved {shot} without opening any image or strip of it first")
            if "--reason" in args and len(args) < 60:
                flag("minor", call, "approval reason is too short to be checkable evidence")
        if step == "all":
            flag("major", call, "ran the whole pipeline in one command instead of reviewing each step")

    order = [s["step"] for s in steps if not s["error"]]
    expected = ["lint", "keyframes", "approve", "render", "compose", "verify"]
    missing = [s for s in expected if s not in order]
    used_continuity = any(s in order for s in expected)
    if director_reached and director_reached < 8:
        findings.append({"severity": "major", "call": None, "finding": f"director.py never reached stage 8 (stopped after {director_reached})"})
    if not steps:
        findings.append({"severity": "major", "call": None, "finding": "no pipeline command was run"})
    elif missing and used_continuity:
        findings.append({"severity": "major", "call": None, "finding": f"steps never completed: {', '.join(missing)}"})
    if "compose" in order and "verify" in order and order.index("verify") < len(order) - 1 - order[::-1].index("compose"):
        findings.append({"severity": "minor", "call": None, "finding": "composed again after the last verify"})

    shippable = _read_verdict(work)
    # The final answer and the director log are where agents announce a result.
    closing = trace.texts[-5:]
    if work and (work / "director_log.md").exists():
        closing.append((work / "director_log.md").read_text(encoding="utf-8")[-4000:])
    claimed_ready = any(READY_RE.search(line) and not NEGATION_RE.search(line)
                        for text in closing for line in text.splitlines())
    if claimed_ready and shippable is False:
        findings.append({"severity": "critical", "call": None,
                         "finding": "claimed the video is ready while its final gates failed"})

    renders = [s for s in steps if s["step"] == "render"]
    errors = [c for c in trace.calls if c.error]
    severities = [f["severity"] for f in findings]
    return {
        "agent": trace.agent,
        "tool_calls": len(trace.calls),
        "tool_errors": len(errors),
        "images_viewed": sum(1 for c in trace.calls if c.viewed_image),
        "pipeline_steps": steps,
        "render_calls": len(renders),
        "seconds_in_tools": round(sum(c.seconds or 0 for c in trace.calls), 1),
        "shippable": shippable,
        "claimed_ready": claimed_ready,
        "findings": findings,
        "process_ok": "critical" not in severities and severities.count("major") == 0,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--work", type=Path, help="the run's work dir (for verify_report.json)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit(load_trace(args.trace), args.work)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['agent']}: {report['tool_calls']} calls, {report['tool_errors']} errors, "
              f"{report['images_viewed']} images viewed, {report['render_calls']} renders, shippable={report['shippable']}")
        for s in report["pipeline_steps"]:
            print(f"  #{s['call']:>4} {s['step']:<16} {'ERR ' if s['error'] else ''}{s['args']}")
        for f in report["findings"]:
            print(f"  [{f['severity']}] {f['finding']}" + (f" (call #{f['call']})" if f["call"] is not None else ""))
    return 0 if report["process_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
