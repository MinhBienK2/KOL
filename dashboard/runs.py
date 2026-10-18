"""Run discovery, stage derivation and view-model assembly for the supervisor dashboard.

Two on-disk layouts are supported (see ``docs/adr/0005-run-telemetry-and-supervisor-dashboard.md``):

* workspace -- ``{base_dir}/projects/{topic}/{project_id}/`` with ``run_id="{topic}/{project_id}"``
* legacy    -- ``{base_dir}/artifacts/{project_id}/`` with ``run_id="{project_id}"``

Live state comes from ``telemetry/state.json`` + ``telemetry/events.jsonl`` when a run was
instrumented; otherwise stage status is derived from the canonical pipeline artifacts, always
cross-checking that the media those artifacts reference still exists on disk.

Everything here is read-only and fail-safe: a missing or corrupt artifact never raises, it just
yields ``None`` (the dashboard reports a gap instead of a stack trace).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from pipeline import telemetry as telemetry_module
from pipeline.config import BASE_DIR, OUTPUT_DIR

SCHEMA_VERSION = 1

LAYOUT_WORKSPACE = "workspace"
LAYOUT_LEGACY = "legacy"

PROJECTS_DIRNAME = "projects"
ARTIFACTS_DIRNAME = "artifacts"
TELEMETRY_DIRNAME = telemetry_module.TELEMETRY_DIRNAME
STATE_FILENAME = telemetry_module.STATE_FILENAME
EVENTS_FILENAME = telemetry_module.EVENTS_FILENAME

TOTAL_STAGES = telemetry_module.TOTAL_STAGES

STATUS_COMPLETED = "completed"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"

#: Canonical artifacts: their presence is what makes a legacy directory a run at all.
CANONICAL_ARTIFACTS: Tuple[str, ...] = (
    "brief.json",
    "competitor_research.json",
    "creative_concept.json",
    "script.json",
    "scene_plan.json",
    "asset_manifest.json",
    "edit_decisions.json",
    "render_report.json",
    "publish_log.json",
    "storyboard_contact_sheet.jpg",
)

#: Which stage owns each canonical artifact (used for labelling scanned files).
ARTIFACT_STAGE: Dict[str, int] = {
    "brief.json": 1,
    "competitor_research.json": 1,
    "creative_concept.json": 1,
    "script.json": 2,
    "scene_plan.json": 3,
    "storyboard_contact_sheet.jpg": 3,
    "asset_manifest.json": 4,
    "edit_decisions.json": 7,
    "render_report.json": 8,
    "publish_log.json": 8,
}

#: Legacy runs keep their media in run-named sub-directories of the shared output tree.
SHARED_MEDIA_DIRNAME = {
    "keyframes": "keyframes",
    "raw_clips": "raw_clips",
    "synced_clips": "synced_clips",
    "audio": "audio",
}

#: Input trees that generated assets legitimately live in (identity anchors, wardrobe refs).
INPUT_DIRNAMES: Tuple[str, ...] = ("assets", "archive_raw")


class RunNotFound(LookupError):
    """Raised when a ``run_id`` does not resolve to a run on disk."""


class PathEscape(PermissionError):
    """Raised when a requested path resolves outside the run's own data roots."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _utc_iso(timestamp: Optional[float] = None, *, text: Optional[str] = None) -> Optional[str]:
    """ISO-8601 UTC timestamp in the repo convention (``...Z``)."""
    if text:
        return text
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(float(timestamp), timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _file_mtime_iso(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        if path.is_file():
            return _utc_iso(path.stat().st_mtime)
    except OSError:
        return None
    return None


def _parse_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _elapsed_seconds(started_at: Optional[str], finished_at: Optional[str]) -> Optional[float]:
    start, end = _parse_iso(started_at), _parse_iso(finished_at)
    if start is None or end is None:
        return None
    return round(max(0.0, end - start), 3)


def _load_json(path: Optional[Path]) -> Any:
    """Load JSON, returning ``None`` for missing or corrupt files (never raises)."""
    if path is None:
        return None
    try:
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _as_dict(value: Any) -> Optional[Dict[str, Any]]:
    return value if isinstance(value, dict) else None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_size(path: Optional[Path]) -> Optional[int]:
    if path is None:
        return None
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return None
    return None


def _kind_for(path: Optional[Path], fallback: Optional[str] = None) -> str:
    if fallback:
        return fallback
    if path is None:
        return "file"
    return telemetry_module.artifact_kind(path)


# ---------------------------------------------------------------------------
# Prompt segmentation
# ---------------------------------------------------------------------------

#: Directive labels used by the DramaClaw 6-part prompt builder and the legacy builders.
#: Segments are only produced for labels actually present in the prompt text.
_PATTERN_LABELS: Tuple[Tuple[str, str], ...] = (
    ("Generate a", r"Generate a \[[^\]]+\] aspect ratio"),
    ("Framing", r"Framing:"),
    (
        "Commercial",
        r"Commercial (?:fashion and lifestyle video featuring"
        r"|presenter video featuring"
        r"|macro product cinematography of)",
    ),
    ("Subject", r"Subject:"),
    ("Wardrobe and styling", r"Wardrobe and styling:"),
    ("Wardrobe", r"Wardrobe:"),
    ("Visual acting action", r"Visual acting action:"),
    ("Delivery action", r"Delivery action:"),
    ("Action and interaction", r"Action and interaction:"),
    ("Poise", r"Poise:"),
    ("Camera angle", r"Camera angle:"),
    ("Camera framing", r"Camera framing:"),
    ("Camera movement", r"Camera movement:"),
    ("Camera choreography", r"Camera choreography:"),
    ("Environment and staging", r"Environment and staging:"),
    ("Environment", r"Environment:"),
    ("Lighting key", r"Lighting key:"),
    ("Lighting", r"Lighting:"),
    ("SET", r"SET:"),
    ("WEAR", r"WEAR:"),
    ("Character", r"Character:"),
    ("Identity lock", r"Identity lock:"),
    ("Style", r"Style:"),
    ("Scene action", r"Scene action:"),
)

_SEGMENT_RE = re.compile(
    "|".join(f"(?<![A-Za-z0-9])(?:{pattern})" for _, pattern in _PATTERN_LABELS)
)


def _label_for(fragment: str) -> Optional[str]:
    for label, pattern in _PATTERN_LABELS:
        if re.fullmatch(pattern, fragment):
            return label
    return None


def split_prompt_segments(prompt: Optional[str]) -> List[Dict[str, str]]:
    """Split a generation prompt on the known directive labels.

    Returns ``[{"label", "text"}, ...]`` covering the whole prompt; fragments before the first
    label are labelled ``"prompt"``. When no label is present the prompt is returned as a single
    ``"prompt"`` segment. Text is never invented: every segment is a verbatim slice.
    """
    text = (prompt or "").strip()
    if not text:
        return []

    matches: List[Tuple[int, int, str]] = []
    for match in _SEGMENT_RE.finditer(text):
        label = _label_for(match.group(0))
        if label is None:
            continue
        matches.append((match.start(), match.end(), label))
    if not matches:
        return [{"label": "prompt", "text": text}]

    segments: List[Dict[str, str]] = []
    for index, (start, _end, label) in enumerate(matches):
        stop = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        chunk = text[start:stop].strip()
        if chunk:
            segments.append({"label": label, "text": chunk})
    if matches[0][0] > 0:
        leading = text[: matches[0][0]].strip()
        if leading:
            segments.insert(0, {"label": "prompt", "text": leading})
    return segments or [{"label": "prompt", "text": text}]


# ---------------------------------------------------------------------------
# RunRef
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunRef:
    """Everything the dashboard needs to read one run without touching the filesystem again."""

    run_id: str
    project_id: str
    topic: Optional[str]
    layout: str
    root: Path
    artifacts_dir: Path
    telemetry_dir: Path
    telemetry_dirs: Tuple[Path, ...]
    base_dir: Path
    repo_root: Path
    url_base: Path
    allowed_roots: Tuple[Path, ...]
    has_telemetry: bool
    allowed_files: FrozenSet[Path] = field(default_factory=frozenset)

    @property
    def is_workspace(self) -> bool:
        return self.layout == LAYOUT_WORKSPACE

    def state_path(self) -> Path:
        return self.telemetry_dir / STATE_FILENAME

    def events_path(self) -> Path:
        return self.telemetry_dir / EVENTS_FILENAME


def resolve_base_dir(base_dir: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the dashboard output root (``OUTPUT_DIR`` by default)."""
    if base_dir is None:
        return Path(OUTPUT_DIR).resolve()
    return Path(base_dir).resolve()


def _shared_media_roots(base: Path, project_id: str) -> Tuple[Path, ...]:
    return tuple((base / dirname / project_id).resolve() for dirname in SHARED_MEDIA_DIRNAME.values())


def _input_roots(repo_root: Path) -> Tuple[Path, ...]:
    return tuple((repo_root / name).resolve() for name in INPUT_DIRNAMES)


def _pick_telemetry(dirs: Sequence[Path], project_id: str) -> Tuple[Path, bool]:
    for candidate in dirs:
        state = _load_json(candidate / STATE_FILENAME)
        if isinstance(state, dict) and str(state.get("project_id") or "") == project_id:
            return candidate, True
    for candidate in dirs:
        if (candidate / STATE_FILENAME).exists():
            return candidate, True
    return dirs[0], False


def _workspace_ref(base: Path, topic: str, project_id: str) -> RunRef:
    root = (base / PROJECTS_DIRNAME / topic / project_id).resolve()
    artifacts_dir = root / ARTIFACTS_DIRNAME
    telemetry_dir, has_telemetry = _pick_telemetry((root / TELEMETRY_DIRNAME,), project_id)
    allowed_roots = (
        root,
        *_shared_media_roots(base, project_id),
        *_input_roots(BASE_DIR),
    )
    ref = RunRef(
        run_id=f"{topic}/{project_id}",
        project_id=project_id,
        topic=topic,
        layout=LAYOUT_WORKSPACE,
        root=root,
        artifacts_dir=artifacts_dir,
        telemetry_dir=telemetry_dir,
        telemetry_dirs=(telemetry_dir,),
        base_dir=base,
        repo_root=Path(BASE_DIR).resolve(),
        url_base=root,
        allowed_roots=allowed_roots,
        has_telemetry=has_telemetry,
    )
    return replace(ref, allowed_files=_collect_allowed_files(ref))


def _legacy_ref(base: Path, project_id: str) -> RunRef:
    root = (base / ARTIFACTS_DIRNAME / project_id).resolve()
    telemetry_dirs = ((root / TELEMETRY_DIRNAME).resolve(), (base / TELEMETRY_DIRNAME).resolve())
    telemetry_dir, has_telemetry = _pick_telemetry(telemetry_dirs, project_id)
    allowed_roots = (
        root,
        *_shared_media_roots(base, project_id),
        *_input_roots(BASE_DIR),
    )
    ref = RunRef(
        run_id=project_id,
        project_id=project_id,
        topic=None,
        layout=LAYOUT_LEGACY,
        root=root,
        artifacts_dir=root,
        telemetry_dir=telemetry_dir,
        telemetry_dirs=tuple(telemetry_dirs),
        base_dir=base,
        repo_root=Path(BASE_DIR).resolve(),
        url_base=base,
        allowed_roots=allowed_roots,
        has_telemetry=has_telemetry,
    )
    return replace(ref, allowed_files=_collect_allowed_files(ref))


def _collect_allowed_files(run_ref: RunRef) -> FrozenSet[Path]:
    """Files declared by the run's own artifacts that live outside its media roots."""
    allowed: set = set()
    for name in ("render_report.json", "edit_decisions.json", "publish_log.json"):
        data = _as_dict(_load_json(_artifact_path(run_ref, name)))
        if not data:
            continue
        for key in ("master_video_path", "output_master_path", "thumbnail_path"):
            resolved = resolve_reference(run_ref, data.get(key))
            if resolved is not None:
                allowed.add(resolved)
    state = load_state(run_ref)
    if state:
        for key in ("master_video_path", "thumbnail_path"):
            resolved = resolve_reference(run_ref, state.get(key))
            if resolved is not None:
                allowed.add(resolved)
    return frozenset(allowed)


# ---------------------------------------------------------------------------
# Discovery / resolution
# ---------------------------------------------------------------------------


def _has_canonical_artifact(directory: Path) -> bool:
    return any((directory / name).is_file() for name in CANONICAL_ARTIFACTS)


def _workspace_has_content(directory: Path) -> bool:
    if (directory / TELEMETRY_DIRNAME / STATE_FILENAME).exists():
        return True
    for sub in (ARTIFACTS_DIRNAME, "keyframes", "media"):
        child = directory / sub
        if child.is_dir() and any(child.iterdir()):
            return True
    return False


def _discover_workspace_refs(base: Path) -> List[RunRef]:
    projects_dir = base / PROJECTS_DIRNAME
    if not projects_dir.is_dir():
        return []
    refs: List[RunRef] = []
    try:
        topic_dirs = sorted(child for child in projects_dir.iterdir() if child.is_dir())
    except OSError:
        return []
    for topic_dir in topic_dirs:
        try:
            project_dirs = sorted(child for child in topic_dir.iterdir() if child.is_dir())
        except OSError:
            continue
        for project_dir in project_dirs:
            if _workspace_has_content(project_dir):
                refs.append(_workspace_ref(base, topic_dir.name, project_dir.name))
    return refs


def _discover_legacy_refs(base: Path) -> List[RunRef]:
    legacy_dir = base / ARTIFACTS_DIRNAME
    if not legacy_dir.is_dir():
        return []
    refs: List[RunRef] = []
    try:
        candidates = sorted(child for child in legacy_dir.iterdir() if child.is_dir())
    except OSError:
        return []
    for child in candidates:
        if _has_canonical_artifact(child) or (child / TELEMETRY_DIRNAME / STATE_FILENAME).exists():
            refs.append(_legacy_ref(base, child.name))
    return refs


def resolve_run(run_id: str, base_dir: Optional[Union[str, Path]] = None) -> RunRef:
    """Resolve ``run_id`` (``topic/project_id`` or bare legacy ``project_id``) to a :class:`RunRef`."""
    base = resolve_base_dir(base_dir)
    raw = str(run_id or "").strip().strip("/")
    if not raw:
        raise RunNotFound(run_id)
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise RunNotFound(run_id)

    if len(parts) == 2:
        topic, project_id = parts
        root = base / PROJECTS_DIRNAME / topic / project_id
        if not root.is_dir():
            raise RunNotFound(run_id)
        return _workspace_ref(base, topic, project_id)
    if len(parts) > 2:
        raise RunNotFound(run_id)

    project_id = parts[0]
    legacy_root = base / ARTIFACTS_DIRNAME / project_id
    if legacy_root.is_dir() and (_has_canonical_artifact(legacy_root) or (legacy_root / "artifacts").is_dir()):
        return _legacy_ref(base, project_id)

    projects_dir = base / PROJECTS_DIRNAME
    if projects_dir.is_dir():
        for topic_dir in sorted(child for child in projects_dir.iterdir() if child.is_dir()):
            if (topic_dir / project_id).is_dir():
                return _workspace_ref(base, topic_dir.name, project_id)

    if legacy_root.is_dir():
        return _legacy_ref(base, project_id)
    raise RunNotFound(run_id)


def discover_runs(base_dir: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """List every run under ``base_dir`` (newest first) in the ``GET /api/runs`` item shape."""
    base = resolve_base_dir(base_dir)
    refs = [*_discover_workspace_refs(base), *_discover_legacy_refs(base)]
    items = [summarize_run(ref) for ref in refs]
    items.sort(key=lambda item: (item.get("updated_at") or "", item["run_id"]), reverse=True)
    return items


# ---------------------------------------------------------------------------
# Path resolution / serving
# ---------------------------------------------------------------------------


def _search_roots(run_ref: RunRef) -> Tuple[Path, ...]:
    ordered = (run_ref.root, run_ref.url_base, run_ref.base_dir, run_ref.repo_root)
    unique: List[Path] = []
    for path in ordered:
        if path not in unique:
            unique.append(path)
    return tuple(unique)


def reference_candidates(run_ref: RunRef, reference: Any) -> List[Path]:
    """Candidate absolute paths for a manifest-declared reference (never raises)."""
    text = _as_str(reference)
    if not text:
        return []
    normalised = text.replace("\\", "/")
    raw = Path(normalised)
    if raw.is_absolute():
        return [raw]

    candidates: List[Path] = []
    parts = [part for part in raw.parts if part not in ("", ".")]
    stripped = Path(*parts[1:]) if parts and parts[0] == run_ref.base_dir.name and len(parts) > 1 else raw
    for base in _search_roots(run_ref):
        candidates.append(base / normalised)
        if str(stripped) != normalised:
            candidates.append(base / stripped)
    # Generated media mirrored into the workspace drops the campaign directory name, e.g.
    # ``output/keyframes/campaign_x/shot_01_clean.jpg`` -> ``{root}/keyframes/shot_01_clean.jpg``.
    if len(parts) >= 2:
        category, filename = parts[-2], parts[-1]
        for base in _search_roots(run_ref):
            candidates.append(base / category / filename)
    candidates.append(run_ref.root / raw.name)
    unique: List[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def is_allowed(run_ref: RunRef, path: Path) -> bool:
    """Whether ``path`` lives inside the run's own roots (or is a declared run file)."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    if resolved in run_ref.allowed_files:
        return True
    for root in run_ref.allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_reference(run_ref: RunRef, reference: Any) -> Optional[Path]:
    """Best-effort resolution of an artifact-declared path to an existing file."""
    for candidate in reference_candidates(run_ref, reference):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def safe_resolve(run_ref: RunRef, rel_path: Any) -> Path:
    """Resolve a served path, raising :class:`PathEscape` when it leaves the run's roots."""
    text = _as_str(rel_path)
    if not text:
        raise PathEscape("empty path")
    raw = Path(text.replace("\\", "/"))
    candidates = [raw] if raw.is_absolute() else [base / raw for base in _search_roots(run_ref)]
    fallback: Optional[Path] = None
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not is_allowed(run_ref, resolved):
            continue
        if resolved.is_file():
            return resolved
        if fallback is None:
            fallback = resolved
    if fallback is not None:
        return fallback
    raise PathEscape(rel_path)


def file_url(run_ref: RunRef, rel_path: Optional[str]) -> Optional[str]:
    if not rel_path:
        return None
    return f"/api/runs/{run_ref.run_id}/file?path={quote(rel_path, safe='/')}"


def relative_for_url(run_ref: RunRef, path: Path) -> Optional[str]:
    """Relative path for URLs, or ``None`` when the file is not servable for this run."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    if not resolved.is_file() or not is_allowed(run_ref, resolved):
        return None
    for base in (run_ref.url_base, run_ref.root, run_ref.repo_root):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return None


def make_file_ref(
    run_ref: RunRef,
    path: Optional[Path],
    *,
    label: Optional[str] = None,
    kind: Optional[str] = None,
    rel_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the frozen ``fileRef`` shape for a resolved (or missing) file."""
    resolved = path
    exists = bool(resolved is not None and resolved.is_file())
    if exists and rel_path is None:
        rel_path = relative_for_url(run_ref, resolved)  # type: ignore[arg-type]
    name_hint = resolved.name if resolved is not None else (rel_path or "")
    return {
        "name": Path(name_hint).name if name_hint else None,
        "label": label or name_hint or "file",
        "rel_path": rel_path if exists else None,
        "url": file_url(run_ref, rel_path) if exists else None,
        "kind": _kind_for(resolved, kind),
        "size_bytes": _safe_size(resolved) if exists else None,
        "exists": exists,
    }


def file_ref_for_reference(
    run_ref: RunRef,
    reference: Any,
    *,
    label: Optional[str] = None,
    kind: Optional[str] = None,
    allow_inputs: bool = False,
) -> Optional[Dict[str, Any]]:
    """``fileRef`` for an artifact-declared path; ``None`` when nothing is declared.

    With ``allow_inputs`` the file may come from the repository input trees (``assets/``,
    ``archive_raw/``); otherwise it is only exposed when it is servable for this run.
    """
    text = _as_str(reference)
    if not text:
        return None
    resolved = resolve_reference(run_ref, text)
    if resolved is None:
        return {
            "name": Path(text).name,
            "label": label or Path(text).name,
            "rel_path": None,
            "url": None,
            "kind": kind or telemetry_module.artifact_kind(text),
            "size_bytes": None,
            "exists": False,
        }
    ref = make_file_ref(run_ref, resolved, label=label, kind=kind)
    if ref["url"] is None and allow_inputs:
        for root in _input_roots(run_ref.repo_root):
            try:
                rel = str(resolved.relative_to(root.resolve()))
            except ValueError:
                continue
            ref["rel_path"] = str(Path(root.name) / rel)
            ref["url"] = file_url(run_ref, ref["rel_path"])
            break
    return ref


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_json(path: Optional[Path]) -> Any:
    """Public alias for the tolerant JSON loader (``None`` for missing/corrupt files)."""
    return _load_json(path)


def locate_artifact(run_ref: RunRef, name: str) -> Optional[Path]:
    """Locate a JSON artifact by file name inside the run (``None`` when not present)."""
    text = _as_str(name)
    if not text:
        return None
    normalised = text.replace("\\", "/")
    raw = Path(normalised)
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        return None
    candidates = (f"{ARTIFACTS_DIRNAME}/{normalised}", normalised)
    for relative in candidates:
        try:
            resolved = safe_resolve(run_ref, relative)
        except PathEscape:
            continue
        if resolved.is_file():
            return resolved
    return None


def load_state(run_ref: RunRef) -> Optional[Dict[str, Any]]:
    for directory in run_ref.telemetry_dirs:
        state = _as_dict(_load_json(directory / STATE_FILENAME))
        if state and str(state.get("project_id") or "") == run_ref.project_id:
            return state
    return None


def run_events_path(run_ref: RunRef) -> Optional[Path]:
    for directory in run_ref.telemetry_dirs:
        candidate = directory / EVENTS_FILENAME
        if candidate.is_file():
            return candidate
    return None


def read_run_events(run_ref: RunRef, since: int = 0, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = run_events_path(run_ref)
    if path is None:
        return []
    return telemetry_module.read_events(path, since=since, limit=limit)


def _artifact_path(run_ref: RunRef, name: str) -> Path:
    preferred = run_ref.artifacts_dir / name
    if preferred.is_file():
        return preferred
    alternate = run_ref.root / name
    if alternate.is_file():
        return alternate
    return preferred


@dataclass
class RunContext:
    """All parsed, read-only inputs for one run."""

    run_ref: RunRef
    state: Optional[Dict[str, Any]]
    events: List[Dict[str, Any]]
    artifact_paths: Dict[str, Path]
    brief: Optional[Dict[str, Any]]
    research: Optional[Dict[str, Any]]
    concept: Optional[Dict[str, Any]]
    script: Optional[Dict[str, Any]]
    scene_plan: Optional[Dict[str, Any]]
    manifest: Optional[Dict[str, Any]]
    edit_decisions: Optional[Dict[str, Any]]
    render_report: Optional[Dict[str, Any]]
    publish_log: Optional[Dict[str, Any]]
    shots: List[Dict[str, Any]]
    beats: List[Dict[str, Any]]
    master_video_path: Optional[Path]
    thumbnail_path: Optional[Path]


def _first_existing(base_dir: Path, names: Iterable[str]) -> Optional[Path]:
    for name in names:
        candidate = base_dir / name
        if candidate.is_file():
            return candidate
    return None


def _declared_master_path(run_ref: RunRef, ctx: Dict[str, Any]) -> Optional[Path]:
    for container, key in (
        (ctx.get("state"), "master_video_path"),
        (ctx.get("render_report"), "master_video_path"),
        (ctx.get("publish_log"), "master_video_path"),
        (ctx.get("edit_decisions"), "output_master_path"),
    ):
        data = _as_dict(container)
        if not data:
            continue
        resolved = resolve_reference(run_ref, data.get(key))
        if resolved is not None:
            return resolved
    candidate = run_ref.root / f"final_master_{run_ref.project_id}.mp4"
    return candidate if candidate.is_file() else None


def _declared_thumbnail_path(run_ref: RunRef, ctx: Dict[str, Any]) -> Optional[Path]:
    for container, key in (
        (ctx.get("state"), "thumbnail_path"),
        (ctx.get("publish_log"), "thumbnail_path"),
    ):
        data = _as_dict(container)
        if not data:
            continue
        resolved = resolve_reference(run_ref, data.get(key))
        if resolved is not None:
            return resolved
    candidate = run_ref.root / f"thumbnail_{run_ref.project_id}.jpg"
    if candidate.is_file():
        return candidate
    for name in (
        f"thumbnail_{run_ref.project_id}.jpg",
        f"thumbnail_{run_ref.project_id}.png",
        "thumbnail_master.jpg",
    ):
        found = _first_existing(run_ref.base_dir, (name,))
        if found is not None:
            return found
    return None


def load_run_context(run_ref: RunRef, *, include_events: bool = True) -> RunContext:
    """Parse every artifact of a run, tolerating missing or corrupt files."""
    state = load_state(run_ref)
    artifact_paths = {name: _artifact_path(run_ref, name) for name in CANONICAL_ARTIFACTS}
    parsed = {name: _load_json(path) for name, path in artifact_paths.items()}
    context_data: Dict[str, Any] = {
        "state": state,
        "brief": _as_dict(parsed.get("brief.json")),
        "research": _as_dict(parsed.get("competitor_research.json")),
        "concept": _as_dict(parsed.get("creative_concept.json")),
        "script": _as_dict(parsed.get("script.json")),
        "scene_plan": _as_dict(parsed.get("scene_plan.json")),
        "manifest": _as_dict(parsed.get("asset_manifest.json")),
        "edit_decisions": _as_dict(parsed.get("edit_decisions.json")),
        "render_report": _as_dict(parsed.get("render_report.json")),
        "publish_log": _as_dict(parsed.get("publish_log.json")),
    }
    scene_plan = context_data["scene_plan"] or {}
    script = context_data["script"] or {}
    shots = [shot for shot in scene_plan.get("shots") or [] if isinstance(shot, dict)]
    beats = [beat for beat in script.get("beats") or [] if isinstance(beat, dict)]
    events = read_run_events(run_ref) if include_events else []
    return RunContext(
        run_ref=run_ref,
        state=state,
        events=events,
        artifact_paths=artifact_paths,
        brief=context_data["brief"],
        research=context_data["research"],
        concept=context_data["concept"],
        script=context_data["script"],
        scene_plan=context_data["scene_plan"],
        manifest=context_data["manifest"],
        edit_decisions=context_data["edit_decisions"],
        render_report=context_data["render_report"],
        publish_log=context_data["publish_log"],
        shots=shots,
        beats=beats,
        master_video_path=_declared_master_path(run_ref, context_data),
        thumbnail_path=_declared_thumbnail_path(run_ref, context_data),
    )


# ---------------------------------------------------------------------------
# Media / manifest joins
# ---------------------------------------------------------------------------


def _manifest_list(ctx: RunContext, key: str) -> List[Any]:
    manifest = ctx.manifest or {}
    value = manifest.get(key)
    return list(value) if isinstance(value, list) else []


def _pick_by_shot(items: Sequence[Any], shot_id: str, index: int) -> Any:
    """Pick the manifest entry belonging to ``shot_id`` (by name, then by position)."""
    for item in items:
        reference = item.get("image_path") or item.get("cleaned_image_path") if isinstance(item, dict) else item
        name = Path(str(reference or "")).name
        if name and shot_id and name.startswith(shot_id):
            return item
    for item in items:
        if isinstance(item, dict) and str(item.get("shot_id") or "") == shot_id:
            return item
    if 0 <= index < len(items):
        return items[index]
    return None


def _keyframe_entry(ctx: RunContext, shot_id: str, index: int) -> Optional[Dict[str, Any]]:
    entries = [item for item in _manifest_list(ctx, "keyframes") if isinstance(item, dict)]
    for entry in entries:
        if str(entry.get("shot_id") or "") == shot_id:
            return entry
    if not entries:
        return None
    for entry in entries:
        if Path(str(entry.get("cleaned_image_path") or "")).name.startswith(shot_id):
            return entry
    if 0 <= index < len(entries):
        return entries[index]
    return None


# ---------------------------------------------------------------------------
# Stage derivation
# ---------------------------------------------------------------------------


def _existing_paths(run_ref: RunRef, references: Iterable[Any]) -> List[Path]:
    found: List[Path] = []
    for reference in references:
        resolved = resolve_reference(run_ref, reference)
        if resolved is not None and resolved not in found:
            found.append(resolved)
    return found


def _reference_values(ctx: RunContext, key: str) -> List[Any]:
    return [value for value in _manifest_list(ctx, key) if value not in (None, "")]


def _keyframe_references(ctx: RunContext) -> List[Any]:
    refs: List[Any] = []
    for entry in _manifest_list(ctx, "keyframes"):
        if isinstance(entry, dict):
            refs.append(entry.get("cleaned_image_path") or entry.get("image_path"))
        else:
            refs.append(entry)
    return refs


def derive_stage_evidence(ctx: RunContext) -> Dict[int, Dict[str, Any]]:
    """Derive per-stage status from canonical artifacts when no telemetry exists.

    Every media reference is cross-checked against the filesystem: a stage only counts as
    completed when the files it claims to have produced are actually there.
    """
    run_ref = ctx.run_ref
    raw_clips = _reference_values(ctx, "raw_video_clips")
    synced_clips = _reference_values(ctx, "synced_video_clips")
    audio_stems = _reference_values(ctx, "audio_stems")
    keyframes = _keyframe_references(ctx)

    evidence: Dict[int, Dict[str, Any]] = {}

    def record(stage: int, completed: bool, message: str, references: Sequence[Any]) -> None:
        evidence[stage] = {
            "status": STATUS_COMPLETED if completed else STATUS_PENDING,
            "message": message,
            "references": list(references),
        }

    brief_path = ctx.artifact_paths["brief.json"]
    record(1, brief_path.is_file(), "Derived from brief.json" if brief_path.is_file() else "brief.json missing", [brief_path])
    script_path = ctx.artifact_paths["script.json"]
    record(2, script_path.is_file(), "Derived from script.json" if script_path.is_file() else "script.json missing", [script_path])
    scene_path = ctx.artifact_paths["scene_plan.json"]
    record(3, scene_path.is_file(), "Derived from scene_plan.json" if scene_path.is_file() else "scene_plan.json missing", [scene_path])

    manifest_path = ctx.artifact_paths["asset_manifest.json"]
    found_keyframes = _existing_paths(run_ref, keyframes)
    stage4_ok = bool(found_keyframes)
    record(
        4,
        stage4_ok,
        (
            f"{len(found_keyframes)}/{len(keyframes)} keyframes present"
            if manifest_path.is_file()
            else "asset_manifest.json missing"
        ),
        [manifest_path, *keyframes],
    )

    found_raw = _existing_paths(run_ref, raw_clips)
    record(5, bool(found_raw), f"{len(found_raw)}/{len(raw_clips)} raw clips present", raw_clips)

    found_audio = _existing_paths(run_ref, audio_stems)
    found_synced = _existing_paths(run_ref, synced_clips)
    record(
        6,
        bool(found_audio) and bool(found_synced),
        f"{len(found_audio)}/{len(audio_stems)} voice stems, {len(found_synced)}/{len(synced_clips)} synced clips",
        [*audio_stems, *synced_clips],
    )

    edit_path = ctx.artifact_paths["edit_decisions.json"]
    master_ok = ctx.master_video_path is not None and ctx.master_video_path.is_file()
    record(
        7,
        edit_path.is_file() and master_ok,
        "Derived from edit_decisions.json + master video"
        if edit_path.is_file() and master_ok
        else ("master video missing" if edit_path.is_file() else "edit_decisions.json missing"),
        [edit_path, ctx.master_video_path],
    )

    report_path = ctx.artifact_paths["render_report.json"]
    record(
        8,
        report_path.is_file(),
        "Derived from render_report.json" if report_path.is_file() else "render_report.json missing",
        [report_path],
    )
    return evidence


def _stage_artifacts_from_evidence(run_ref: RunRef, references: Sequence[Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for reference in references:
        if reference is None:
            continue
        resolved = resolve_reference(run_ref, reference)
        if resolved is None:
            continue
        refs.append(make_file_ref(run_ref, resolved))
    return refs


def _derived_stage_entries(ctx: RunContext, evidence: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for spec in telemetry_module.STAGE_CATALOG:
        record = evidence.get(spec.stage, {})
        finished_at = None
        references = record.get("references") or []
        for reference in references:
            resolved = resolve_reference(ctx.run_ref, reference)
            stamp = _file_mtime_iso(resolved)
            if stamp and (finished_at is None or stamp > finished_at):
                finished_at = stamp
        entries.append(
            {
                "stage": spec.stage,
                "key": spec.key,
                "title": spec.title,
                "status": record.get("status", STATUS_PENDING),
                "started_at": None,
                "finished_at": finished_at,
                "duration_seconds": None,
                "progress": None,
                "message": record.get("message"),
                "error": None,
                "artifacts": _stage_artifacts_from_evidence(ctx.run_ref, references),
                "items": [],
            }
        )
    return entries


def _latest_mtime(run_ref: RunRef) -> Optional[float]:
    latest: Optional[float] = None
    candidates: List[Path] = []
    for directory in run_ref.telemetry_dirs:
        candidates.append(directory)
    candidates.extend([run_ref.artifacts_dir, run_ref.root])
    for directory in _shared_media_roots(run_ref.base_dir, run_ref.project_id):
        candidates.append(directory)
    for directory in candidates:
        try:
            if directory.is_file():
                stamps = [directory.stat().st_mtime]
            elif directory.is_dir():
                stamps = [child.stat().st_mtime for child in directory.iterdir()]
            else:
                continue
        except OSError:
            continue
        for stamp in stamps:
            if latest is None or stamp > latest:
                latest = stamp
    return latest


# ---------------------------------------------------------------------------
# View model
# ---------------------------------------------------------------------------


def _run_status(stages: Sequence[Dict[str, Any]]) -> str:
    statuses = [stage.get("status") for stage in stages]
    if STATUS_FAILED in statuses:
        return STATUS_FAILED
    if all(status in (STATUS_COMPLETED, STATUS_SKIPPED) for status in statuses):
        return STATUS_COMPLETED
    if any(status in (STATUS_COMPLETED, STATUS_SKIPPED, STATUS_RUNNING) for status in statuses):
        return STATUS_RUNNING
    return STATUS_UNKNOWN


def _count_completed(stages: Sequence[Dict[str, Any]]) -> int:
    return sum(1 for stage in stages if stage.get("status") in (STATUS_COMPLETED, STATUS_SKIPPED))


def _run_identity(ctx: RunContext) -> Dict[str, Any]:
    """Identity/meta fields shared by the list item and the view model."""
    run_ref = ctx.run_ref
    state = ctx.state or {}
    meta = _as_dict(state.get("run_meta")) or {}
    brief = ctx.brief or {}
    publish = ctx.publish_log or {}
    render = ctx.render_report or {}
    script = ctx.script or {}
    scene_plan = ctx.scene_plan or {}

    campaign_id = (
        _as_str(meta.get("campaign_id"))
        or _as_str(brief.get("campaign_id"))
        or _as_str(render.get("campaign_id"))
        or _as_str(publish.get("campaign_id"))
        or run_ref.project_id
    )
    research_intel = _as_dict((ctx.research or {}).get("product_intel")) or {}
    product_name = (
        _as_str(meta.get("product_name"))
        or _as_str(brief.get("product_name"))
        or _as_str(publish.get("product_name"))
        or _as_str(script.get("product_name"))
        or _as_str(research_intel.get("title"))
    )
    archetype = (
        _as_str(meta.get("archetype"))
        or _as_str(brief.get("archetype"))
        or _as_str(brief.get("category"))
        or _as_str(script.get("archetype"))
        or _as_str(scene_plan.get("archetype"))
        or run_ref.topic
    )
    return {
        "campaign_id": campaign_id,
        "product_name": product_name,
        "archetype": archetype,
        "video_mode": _as_str(meta.get("video_mode")),
        "resume_from_stage": meta.get("resume_from_stage"),
    }


def _run_timing(ctx: RunContext) -> Dict[str, Optional[str]]:
    state = ctx.state or {}
    meta = _as_dict(state.get("run_meta")) or {}
    if state:
        started_at = _as_str(state.get("last_started_at")) or _as_str(state.get("first_started_at"))
        finished_at = _as_str(state.get("finished_at"))
        elapsed = meta.get("elapsed_seconds")
        if elapsed is None:
            elapsed = state.get("elapsed_seconds")
        if elapsed is None:
            elapsed = _elapsed_seconds(started_at, finished_at)
        return {
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": round(float(elapsed), 3) if isinstance(elapsed, (int, float)) else None,
        }

    stamps: List[float] = []
    for path in ctx.artifact_paths.values():
        try:
            if path.is_file():
                stamps.append(path.stat().st_mtime)
        except OSError:
            continue
    if not stamps:
        return {"started_at": None, "finished_at": None, "elapsed_seconds": None}
    first, last = min(stamps), max(stamps)
    return {
        "started_at": _utc_iso(first),
        "finished_at": _utc_iso(last),
        "elapsed_seconds": round(max(0.0, last - first), 3),
    }


def _events_summary(ctx: RunContext) -> Dict[str, Any]:
    last_seq = 0
    for event in ctx.events:
        try:
            last_seq = max(last_seq, int(event.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return {"count": len(ctx.events), "last_seq": last_seq}


def _last_message(ctx: RunContext, stages: Sequence[Dict[str, Any]]) -> Optional[str]:
    state = ctx.state or {}
    last_event = _as_dict(state.get("last_event")) or {}
    text = _as_str(last_event.get("text"))
    if text:
        return text
    for stage in reversed(list(stages)):
        if stage.get("status") == STATUS_RUNNING and stage.get("message"):
            return _as_str(stage.get("message"))
    if ctx.events:
        text = _as_str(ctx.events[-1].get("text"))
        if text:
            return text
    for stage in reversed(list(stages)):
        message = _as_str(stage.get("message"))
        if message:
            return message
    return None


def _blank_view_stage(spec: "telemetry_module.StageSpec") -> Dict[str, Any]:
    return {
        "stage": spec.stage,
        "key": spec.key,
        "title": spec.title,
        "status": STATUS_PENDING,
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
        "progress": None,
        "message": None,
        "error": None,
        "artifacts": [],
        "items": [],
    }


def _view_stages(ctx: RunContext) -> List[Dict[str, Any]]:
    run_ref = ctx.run_ref
    state = ctx.state
    if state:
        artifact_index = _as_dict(state.get("artifact_index")) or {}
        entries: List[Dict[str, Any]] = []
        for raw_stage in state.get("stages") or []:
            if not isinstance(raw_stage, dict):
                continue
            stage_number = int(raw_stage.get("stage") or 0)
            spec = telemetry_module.stage_spec(stage_number)
            artifacts: List[Dict[str, Any]] = []
            for rel_path in raw_stage.get("artifacts") or []:
                record = _as_dict(artifact_index.get(str(rel_path))) or {}
                resolved = resolve_reference(run_ref, record.get("abs_path") or rel_path)
                if resolved is None and record.get("abs_path"):
                    resolved = resolve_reference(run_ref, record.get("abs_path"))
                ref = make_file_ref(
                    run_ref,
                    resolved,
                    label=_as_str(record.get("label")) or Path(str(rel_path)).name,
                    kind=_as_str(record.get("kind")),
                )
                if ref["exists"] is False and record.get("abs_path"):
                    ref["label"] = _as_str(record.get("label")) or Path(str(record.get("abs_path"))).name
                artifacts.append({**ref, "stage": stage_number, "written_at": record.get("written_at")})
            progress = _as_dict(raw_stage.get("progress"))
            entries.append(
                {
                    "stage": stage_number,
                    "key": _as_str(raw_stage.get("key")) or spec.key,
                    "title": _as_str(raw_stage.get("title")) or spec.title,
                    "status": _as_str(raw_stage.get("status")) or STATUS_PENDING,
                    "started_at": raw_stage.get("started_at"),
                    "finished_at": raw_stage.get("finished_at"),
                    "duration_seconds": raw_stage.get("duration_seconds"),
                    "progress": progress,
                    "message": raw_stage.get("message"),
                    "error": raw_stage.get("error"),
                    "artifacts": artifacts,
                    "items": raw_stage.get("items") or [],
                }
            )
        entries.sort(key=lambda entry: entry["stage"])
        known = {entry["stage"] for entry in entries}
        for spec in telemetry_module.STAGE_CATALOG:
            if spec.stage not in known:
                entries.append(_blank_view_stage(spec))
        entries.sort(key=lambda entry: entry["stage"])
        return entries[:TOTAL_STAGES]

    return _derived_stage_entries(ctx, derive_stage_evidence(ctx))


def _merge_by_shot(ctx: RunContext) -> List[Dict[str, Any]]:
    shots: List[Dict[str, Any]] = []
    for index, raw_shot in enumerate(ctx.shots):
        shot_id = _as_str(raw_shot.get("shot_id")) or f"shot_{index + 1:02d}"
        beat = None
        scene_id = _as_str(raw_shot.get("scene_id"))
        if scene_id:
            beat = next((b for b in ctx.beats if _as_str(b.get("scene_id")) == scene_id), None)
        if beat is None and 0 <= index < len(ctx.beats):
            beat = ctx.beats[index]
        beat = beat or {}

        scene_action = _as_str(raw_shot.get("scene_description")) or _as_str(beat.get("visual_cue"))
        raw = _as_str(raw_shot.get("scene_description"))
        prompt_text = _as_str(raw_shot.get("prompt_6part"))
        keyframe_entry = _keyframe_entry(ctx, shot_id, index) or {}
        cleaned = keyframe_entry.get("cleaned_image_path")
        source_image = keyframe_entry.get("image_path")
        keyframe_ref = file_ref_for_reference(ctx.run_ref, cleaned) or file_ref_for_reference(ctx.run_ref, source_image)
        keyframe_source_ref = file_ref_for_reference(
            ctx.run_ref, source_image, label=Path(str(source_image)).name if _as_str(source_image) else None, allow_inputs=True
        )
        clip_ref = file_ref_for_reference(ctx.run_ref, _pick_by_shot(_manifest_list(ctx, "raw_video_clips"), shot_id, index), label=f"Raw clip {shot_id}")
        synced_ref = file_ref_for_reference(ctx.run_ref, _pick_by_shot(_manifest_list(ctx, "synced_video_clips"), shot_id, index), label=f"Synced clip {shot_id}")
        voice_ref = file_ref_for_reference(ctx.run_ref, _pick_by_shot(_manifest_list(ctx, "audio_stems"), shot_id, index), label=f"Voice stem {shot_id}")

        shots.append(
            {
                "shot_id": shot_id,
                "scene_id": scene_id,
                "beat_type": _as_str(beat.get("beat_type")) or _as_str(raw_shot.get("beat_type")),
                "shot_type": _as_str(raw_shot.get("shot_type")),
                "angle": _as_str(raw_shot.get("angle")),
                "camera_motion": _as_str(raw_shot.get("camera_motion")),
                "camera_choreography": _as_str(raw_shot.get("camera_choreography")) or _as_str(beat.get("camera_choreography")),
                "lighting": _as_str(raw_shot.get("lighting")),
                "lighting_contract": _as_str(raw_shot.get("lighting_contract")) or _as_str(beat.get("lighting_contract")),
                "color_temp_kelvin": raw_shot.get("color_temp_kelvin"),
                "character_tag": _as_str(raw_shot.get("character_tag")),
                "character_role": _as_str(raw_shot.get("character_role")) or _as_str(beat.get("character_role")),
                "is_hero_moment": bool(raw_shot.get("is_hero_moment")),
                "scene_description": raw,
                "estimated_duration": raw_shot.get("estimated_duration"),
                "style_constraints": _as_str(raw_shot.get("style_constraints")),
                "identity_lock_directive": _as_str(raw_shot.get("identity_lock_directive")),
                "narrative_purpose": _as_str(raw_shot.get("narrative_purpose")) or _as_str(beat.get("narrative_purpose")),
                "prompt": prompt_text,
                "segments": split_prompt_segments(prompt_text),
                "spoken_text": _as_str(beat.get("spoken_text")),
                "on_screen_text": _as_str(beat.get("on_screen_text")),
                "visual_cue": scene_action,
                "audio_strategy": _as_str(beat.get("audio_strategy")),
                "keyframe": keyframe_ref,
                "keyframe_source": keyframe_source_ref,
                "clip": clip_ref,
                "synced": synced_ref,
                "voice": voice_ref,
                "render": None,
            }
        )
    return shots


def _api_calls_for_shot(ctx: RunContext, shot_id: str, task_id: Optional[str], stage: int) -> List[Dict[str, Any]]:
    state = ctx.state or {}
    calls = [call for call in state.get("api_calls") or [] if isinstance(call, dict)]
    matched: List[Dict[str, Any]] = []
    for call in calls:
        if _as_str(call.get("shot_id")) == shot_id:
            matched.append(call)
            continue
        if task_id and task_id in json.dumps(call, ensure_ascii=False, default=str):
            matched.append(call)
    return matched


def _prompt_record(
    ctx: RunContext,
    shot_id: str,
    *,
    stage: int,
    prompt: str,
    mode: Optional[str] = None,
    model: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    duration_requested: Any = None,
    first_frame: Any = None,
    task_id: Optional[str] = None,
    attempts: Any = None,
    output_rel_path: Optional[str] = None,
    output_path: Optional[Path] = None,
    size_bytes: Any = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    run_ref = ctx.run_ref
    first_frame_resolved = resolve_reference(run_ref, first_frame) if first_frame else None
    first_frame_rel = relative_for_url(run_ref, first_frame_resolved) if first_frame_resolved else None
    output_resolved = resolve_reference(run_ref, output_path or output_rel_path) if (output_path or output_rel_path) else None
    output_rel = relative_for_url(run_ref, output_resolved) if output_resolved else None
    if output_rel is None and output_rel_path:
        output_rel = _as_str(output_rel_path)
    return {
        "shot_id": shot_id,
        "stage": stage,
        "prompt": prompt,
        "segments": split_prompt_segments(prompt),
        "mode": mode,
        "model": model,
        "aspect_ratio": aspect_ratio,
        "duration_requested": duration_requested,
        "first_frame_rel": first_frame_rel,
        "first_frame_url": file_url(run_ref, first_frame_rel),
        "task_id": task_id,
        "attempts": attempts,
        "output_rel_path": output_rel,
        "output_url": file_url(run_ref, output_rel) if output_resolved else None,
        "size_bytes": size_bytes if size_bytes is not None else _safe_size(output_resolved),
        "updated_at": updated_at,
        "api_calls": _api_calls_for_shot(ctx, shot_id, task_id, stage),
    }


def _prompts(ctx: RunContext) -> List[Dict[str, Any]]:
    run_ref = ctx.run_ref
    state = ctx.state or {}
    state_prompts = _as_dict(state.get("prompts")) or {}

    records: Dict[str, Dict[str, Any]] = {}
    for shot_id, raw in state_prompts.items():
        data = _as_dict(raw)
        if not data:
            continue
        records[str(shot_id)] = _prompt_record(
            ctx,
            str(shot_id),
            stage=int(data.get("stage") or 5),
            prompt=_as_str(data.get("prompt")) or "",
            mode=_as_str(data.get("mode")),
            model=_as_str(data.get("model")),
            aspect_ratio=_as_str(data.get("aspect_ratio")),
            duration_requested=data.get("duration_requested"),
            first_frame=data.get("first_frame"),
            task_id=_as_str(data.get("task_id")),
            attempts=data.get("attempts"),
            output_rel_path=_as_str(data.get("output_rel_path")),
            size_bytes=data.get("size_bytes"),
            updated_at=_as_str(data.get("updated_at")),
        )

    for index, raw_shot in enumerate(ctx.shots):
        shot_id = _as_str(raw_shot.get("shot_id")) or f"shot_{index + 1:02d}"
        if shot_id in records:
            continue
        prompt_text = _as_str(raw_shot.get("prompt_6part"))
        if not prompt_text:
            continue
        keyframe_entry = _keyframe_entry(ctx, shot_id, index) or {}
        updated_at = _file_mtime_iso(ctx.artifact_paths.get("scene_plan.json"))
        aspect = _as_str(raw_shot.get("aspect_ratio"))
        if not aspect:
            match = re.search(r"\[([0-9]+:[0-9]+)\] aspect ratio", prompt_text)
            if match:
                aspect = match.group(1)
        records[shot_id] = _prompt_record(
            ctx,
            shot_id,
            stage=5,
            prompt=prompt_text,
            aspect_ratio=aspect,
            first_frame=keyframe_entry.get("cleaned_image_path") or keyframe_entry.get("image_path"),
            updated_at=updated_at,
        )

    ordered: List[Dict[str, Any]] = []
    seen: set = set()
    for index, raw_shot in enumerate(ctx.shots):
        shot_id = _as_str(raw_shot.get("shot_id")) or f"shot_{index + 1:02d}"
        if shot_id in records and shot_id not in seen:
            ordered.append(records[shot_id])
            seen.add(shot_id)
    for shot_id, record in records.items():
        if shot_id not in seen:
            ordered.append(record)
            seen.add(shot_id)
    return ordered


def _artifact_refs(ctx: RunContext) -> List[Dict[str, Any]]:
    run_ref = ctx.run_ref
    refs: Dict[str, Dict[str, Any]] = {}

    if run_ref.artifacts_dir.is_dir():
        for path in sorted(ctx.artifact_paths.values()):
            if not path.is_file():
                continue
            rel = relative_for_url(run_ref, path) or str(path)
            refs[rel] = {
                **make_file_ref(run_ref, path, label=path.name),
                "stage": ARTIFACT_STAGE.get(path.name),
                "label": path.name,
                "written_at": _file_mtime_iso(path),
            }

    state = ctx.state or {}
    for rel_path, raw in (_as_dict(state.get("artifact_index")) or {}).items():
        record = _as_dict(raw)
        if not record:
            continue
        resolved = resolve_reference(run_ref, record.get("abs_path") or rel_path)
        key = _as_str(record.get("rel_path")) or str(rel_path)
        refs[key] = {
            **make_file_ref(
                run_ref,
                resolved,
                label=_as_str(record.get("label")) or Path(str(rel_path)).name,
                kind=_as_str(record.get("kind")),
            ),
            "stage": record.get("stage"),
            "written_at": record.get("written_at"),
        }
    return list(refs.values())


def _media_inventory(ctx: RunContext, shots: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    run_ref = ctx.run_ref
    media: List[Dict[str, Any]] = []
    seen: set = set()

    def add(ref: Optional[Dict[str, Any]]) -> None:
        if not ref:
            return
        key = (ref.get("rel_path"), ref.get("label"))
        if key in seen:
            return
        seen.add(key)
        media.append(ref)

    for shot in shots:
        add(shot.get("keyframe"))
        add(shot.get("keyframe_source"))
        add(shot.get("clip"))
        add(shot.get("synced"))
        add(shot.get("voice"))

    contact_sheet = (ctx.scene_plan or {}).get("storyboard_contact_sheet")
    storyboard_path = run_ref.artifacts_dir / "storyboard_contact_sheet.jpg"
    if storyboard_path.is_file():
        add(make_file_ref(run_ref, storyboard_path, label="Storyboard contact sheet"))
    elif _as_str(contact_sheet):
        add(file_ref_for_reference(run_ref, contact_sheet, label="Storyboard contact sheet"))

    if ctx.master_video_path is not None:
        add(make_file_ref(run_ref, ctx.master_video_path, label="Master video"))
    if ctx.thumbnail_path is not None:
        add(make_file_ref(run_ref, ctx.thumbnail_path, label="Thumbnail"))

    for extra in _manifest_list(ctx, "keyframes"):
        if isinstance(extra, dict):
            add(file_ref_for_reference(run_ref, extra.get("cleaned_image_path"), label="Keyframe"))
    return media


def _scene_plan_summary(ctx: RunContext) -> Optional[Dict[str, Any]]:
    if not ctx.scene_plan:
        return None
    contact_sheet = None
    storyboard_path = ctx.run_ref.artifacts_dir / "storyboard_contact_sheet.jpg"
    if storyboard_path.is_file():
        contact_sheet = make_file_ref(ctx.run_ref, storyboard_path, label="Storyboard contact sheet")
    else:
        contact_sheet = file_ref_for_reference(ctx.run_ref, (ctx.scene_plan or {}).get("storyboard_contact_sheet"), label="Storyboard contact sheet")
    return {
        "shot_count": len(ctx.shots),
        "slideshow_risk": (ctx.scene_plan or {}).get("slideshow_risk"),
        "spatial_staging_contract": (ctx.scene_plan or {}).get("spatial_staging_contract"),
        "contact_sheet": contact_sheet,
    }


def summarize_run(run_ref: RunRef) -> Dict[str, Any]:
    """Build the ``GET /api/runs`` list item for one run."""
    ctx = load_run_context(run_ref)
    stages = _view_stages(ctx)
    identity = _run_identity(ctx)
    timing = _run_timing(ctx)
    completed = _count_completed(stages)
    mtime = _latest_mtime(run_ref)
    status = _as_str((ctx.state or {}).get("status")) or _run_status(stages)
    return {
        "run_id": run_ref.run_id,
        "project_id": run_ref.project_id,
        "topic": run_ref.topic,
        "layout": run_ref.layout,
        "status": status,
        "current_stage": (ctx.state or {}).get("current_stage"),
        "completed_stages": completed,
        "total_stages": TOTAL_STAGES,
        "progress_percent": round(100.0 * completed / TOTAL_STAGES, 2) if TOTAL_STAGES else 0.0,
        "product_name": identity["product_name"],
        "campaign_id": identity["campaign_id"],
        "started_at": timing["started_at"],
        "finished_at": timing["finished_at"],
        "elapsed_seconds": timing["elapsed_seconds"],
        "master_exists": bool(ctx.master_video_path is not None and ctx.master_video_path.is_file()),
        "has_telemetry": bool(ctx.state is not None),
        "message": _last_message(ctx, stages),
        "updated_at": _utc_iso(mtime),
    }


def build_view(run_ref: RunRef) -> Dict[str, Any]:
    """Assemble the frozen view model for one run."""
    ctx = load_run_context(run_ref)
    stages = _view_stages(ctx)
    identity = _run_identity(ctx)
    timing = _run_timing(ctx)
    completed = _count_completed(stages)
    prompts = _prompts(ctx)
    shots = _merge_by_shot(ctx)
    prompts_by_shot = {prompt["shot_id"]: prompt for prompt in prompts}
    for shot in shots:
        shot["render"] = prompts_by_shot.get(shot["shot_id"])

    state = ctx.state or {}
    status = _as_str(state.get("status")) or _run_status(stages)
    events_summary = _events_summary(ctx)
    render_report = ctx.render_report or {}
    gates = [gate for gate in (render_report.get("verification_gates") or []) if isinstance(gate, dict)]

    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": run_ref.run_id,
            "project_id": run_ref.project_id,
            "topic": run_ref.topic,
            "layout": run_ref.layout,
            "root": str(run_ref.root),
            "artifacts_dir": str(run_ref.artifacts_dir),
            "master_video_path": str(ctx.master_video_path) if ctx.master_video_path else None,
            "thumbnail_path": str(ctx.thumbnail_path) if ctx.thumbnail_path else None,
            "has_telemetry": bool(ctx.state is not None),
            "source": "telemetry" if ctx.state is not None else "artifacts",
            "campaign_id": identity["campaign_id"],
            "product_name": identity["product_name"],
            "archetype": identity["archetype"],
            "video_mode": identity["video_mode"],
            "resume_from_stage": identity["resume_from_stage"],
            "started_at": timing["started_at"],
            "finished_at": timing["finished_at"],
            "elapsed_seconds": timing["elapsed_seconds"],
            "status": status,
            "current_stage": state.get("current_stage"),
            "completed_stages": completed,
            "progress_percent": round(100.0 * completed / TOTAL_STAGES, 2) if TOTAL_STAGES else 0.0,
            "message": _last_message(ctx, stages),
        },
        "stages": stages,
        "artifacts": _artifact_refs(ctx),
        "prompts": prompts,
        "shots": shots,
        "gates": gates,
        "media": _media_inventory(ctx, shots),
        "brief": ctx.brief,
        "research": ctx.research,
        "concept": ctx.concept,
        "script": ctx.script,
        "scene_plan_summary": _scene_plan_summary(ctx),
        "edit_decisions": ctx.edit_decisions,
        "render_report": ctx.render_report,
        "publish_log": ctx.publish_log,
        "events": events_summary,
        "generated_at": telemetry_module.now_iso(),
    }
