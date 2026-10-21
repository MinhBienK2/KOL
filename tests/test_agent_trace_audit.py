import json

from tools import agent_trace_audit as audit_mod

DIRECTOR = "python3 tools/continuity_director.py"


def _omp_trace(tmp_path, calls):
    """calls: (tool, arguments, result_text, is_error, exit_code, has_image)."""
    lines = [{"type": "session", "cwd": "/x/KOL"}]
    for i, (tool, args, text, is_error, code, image) in enumerate(calls):
        lines.append({"type": "message", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "id": f"c{i}", "name": tool, "arguments": args}]}})
        content = [{"type": "text", "text": text}] + ([{"type": "image", "data": "blob:x"}] if image else [])
        lines.append({"type": "message", "message": {"role": "toolResult", "toolCallId": f"c{i}", "toolName": tool,
                                                     "content": content, "isError": is_error,
                                                     "details": {"exitCode": code, "wallTimeMs": 1000}}})
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return path


def _bash(cmd, code=0, text="ok"):
    return ("bash", {"command": cmd}, text, code not in (0, None), code, False)


def test_clean_run_passes(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "verify_report.json").write_text(json.dumps({"passed": True}))
    trace = _omp_trace(tmp_path, [
        _bash(f"{DIRECTOR} lint --bible b"),
        _bash(f"{DIRECTOR} keyframes --bible b", code=3),
        ("read", {"path": "/x/KOL/run/work/keyframes/shot_01_cand1.png"}, "", False, None, True),
        _bash(f"{DIRECTOR} approve --bible b --shot shot_01 --candidate shot_01_cand1.png --reason \"lettering THONGNHAT sharp, single speed, face frontal\""),
        _bash(f"{DIRECTOR} render --bible b --one", code=3),
        _bash(f"{DIRECTOR} compose --bible b"),
        _bash(f"{DIRECTOR} verify --bible b"),
    ])
    report = audit_mod.audit(audit_mod.load_trace(trace), work)
    assert report["findings"] == [] and report["process_ok"] is True
    assert report["tool_errors"] == 0  # exit 3 means "review", not a failed call


def test_flags_blind_approval_code_edits_and_false_ready(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "verify_report.json").write_text(json.dumps({"passed": False}))
    (work / "director_log.md").write_text("Never write ready to post after a failed verify.\nREADY TO POST.\n")
    trace = _omp_trace(tmp_path, [
        _bash(f"{DIRECTOR} render --bible b"),
        _bash(f"{DIRECTOR} approve --bible b --shot shot_02 --clip shot_02_a1.mp4 --reason ok"),
        ("edit", {"input": "[pipeline/continuity/verify.py#AB12]\nPUT >3:\n+X = 1"}, "ok", False, None, False),
        _bash("sed -i 's/0.45/0.2/' tools/continuity_director.py"),
    ])
    found = " | ".join(f["finding"] for f in audit_mod.audit(audit_mod.load_trace(trace), work)["findings"])
    assert "render without --one" in found
    assert "approved shot_02 without opening" in found
    assert "pipeline/continuity/verify.py" in found and "tools/continuity_director.py" in found
    assert "claimed the video is ready" in found


def test_parses_agy_stream(tmp_path):
    events = [
        {"event": "step_update", "step_update": {"step_index": 1, "state": "DONE", "step_type": "tool",
                                                 "tool_info": {"name": "run_command",
                                                               "parameters": {"CommandLine": f"{DIRECTOR} render --one"},
                                                               "output": "Command exited with code 3."}}},
        {"event": "step_update", "step_update": {"step_index": 2, "state": "DONE", "step_type": "tool",
                                                 "tool_info": {"name": "edit_file",
                                                               "parameters": {"Path": "/x/KOL/pipeline/continuity/chain.py"}}}},
        {"event": "result", "result": {"response": "done"}},
    ]
    path = tmp_path / "agy_stream.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    trace = audit_mod.load_trace(path)
    assert trace.agent == "agy" and trace.calls[0].exit_code == 3 and not trace.calls[0].error
    report = audit_mod.audit(trace, None)
    assert any("pipeline/continuity/chain.py" in f["finding"] for f in report["findings"])


def test_director_runs_need_checkpoints_and_a_look(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "render_report.json").write_text(json.dumps({"overall_status": "FAILED"}))
    blind = _omp_trace(tmp_path, [
        _bash("python3 tools/director.py --campaign c --json", code=3),
    ])
    found = " | ".join(f["finding"] for f in audit_mod.audit(audit_mod.load_trace(blind), artifacts)["findings"])
    assert "no --pause-after-stage" in found
    assert audit_mod.load_trace(blind).calls[0].error is False  # exit 3 = gates failed, the call worked

    resumed_blind = _omp_trace(tmp_path, [
        _bash("python3 tools/director.py --campaign c --pause-after-stage 4 --json", code=4),
        _bash("python3 tools/director.py --campaign c --from-stage 5 --pause-after-stage 5 --json", code=4),
    ])
    found = " | ".join(f["finding"] for f in audit_mod.audit(audit_mod.load_trace(resumed_blind), artifacts)["findings"])
    assert "without opening the storyboard, keyframes output" in found
    assert "never reached stage 8" in found


def test_director_reviewed_run_is_clean(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "render_report.json").write_text(json.dumps({"overall_status": "PASSED"}))
    look = ("read", {"path": "/x/KOL/projects/t/c/runs/v1/media/keyframes/shot_01.png"}, "", False, None, True)
    trace = _omp_trace(tmp_path, [
        _bash("python3 tools/director.py --campaign c --check --json"),
        _bash("python3 tools/director.py --campaign c --pause-after-stage 4 --json", code=4),
        look,
        _bash("python3 tools/director.py --campaign c --from-stage 5 --pause-after-stage 5 --json", code=4),
        look,
        _bash("python3 tools/director.py --campaign c --from-stage 6 --pause-after-stage 7 --json", code=4),
        look,
        _bash("python3 tools/director.py --campaign c --from-stage 8 --json"),
    ])
    report = audit_mod.audit(audit_mod.load_trace(trace), artifacts)
    assert report["findings"] == [] and report["shippable"] is True
