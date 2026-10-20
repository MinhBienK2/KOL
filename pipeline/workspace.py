"""Project Workspace module for self-contained, topic-driven, versioned output management.

Layout (ADR 0007):
projects/{topic}/{project_id}/
├── project.json                       # Project metadata and version index
├── input/                             # Invariant user assets & reference documents
└── runs/
    ├── v1/
    │   ├── prompt_ledger.json         # Exact API generation parameters and model prompts
    │   ├── master.mp4 (or final_master_{project_id}.mp4)
    │   ├── thumbnail.jpg (or thumbnail_{project_id}.jpg)
    │   ├── artifacts/                 # 7 canonical JSON artifacts
    │   ├── keyframes/                 # Clean 9:16 keyframes with Telea inpainting
    │   ├── media/                     # raw_clips/, synced_clips/, audio/
    │   └── telemetry/                 # state.json and events.jsonl
    └── v2/                            # Incremental revision (hardlinked unchanged assets)
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

from pipeline.archetypes import ProductArchetype
from pipeline.config import BASE_DIR, OUTPUT_DIR, PROJECTS_DIR

T = TypeVar("T", bound=BaseModel)


def canonical_artifact_models() -> Dict[str, Type[BaseModel]]:
    """Canonical artifacts an agent may supply itself (`--inject NAME=PATH`) instead of letting a
    stage generate them (ADR 0001: stages advance only when prerequisite artifacts validate).

    Imported lazily: pipeline.schemas pulls in pipeline.researcher, which imports this module.
    """
    from pipeline.schemas import AssetManifestArtifact, BriefArtifact, ScenePlanArtifact, ScriptArtifact

    return {
        "brief": BriefArtifact,
        "script": ScriptArtifact,
        "scene_plan": ScenePlanArtifact,
        "asset_manifest": AssetManifestArtifact,
    }

# Stage that normally produces each injectable artifact.
ARTIFACT_PRODUCER_STAGE: Dict[str, int] = {"brief": 1, "script": 2, "scene_plan": 3, "asset_manifest": 4}

# Canonical artifacts that must exist and validate before a stage may start.
STAGE_PREREQUISITES: Dict[int, tuple] = {
    2: ("brief",),
    3: ("script",),
    4: ("script", "scene_plan"),
    5: ("scene_plan", "asset_manifest"),
    6: ("script", "asset_manifest"),
    7: ("script", "asset_manifest"),
    8: ("script", "scene_plan", "asset_manifest"),
}


def first_stage_after(artifact_names: List[str]) -> int:
    """First stage that still has to run once ``artifact_names`` were supplied by the caller."""
    return max((ARTIFACT_PRODUCER_STAGE[name] for name in artifact_names), default=0) + 1


def _first_error(exc: ValidationError) -> str:
    """One-line summary of the first pydantic validation error."""
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
    return f"{where}: {first.get('msg')}"


def _missing_media(field: str, paths: List[str]) -> List[str]:
    """Problems for an asset-manifest media list that is empty or names files that do not exist."""
    if not paths:
        return [f"asset_manifest.json lists no {field} (run the stage that produces them)"]
    return [f"asset_manifest.json {field} file is missing: {p}" for p in paths if not Path(p).is_file()]


def _safe_link_or_copy(src: Path, dst: Path) -> None:
    """Create a hardlink from src to dst; fall back to copy2 on cross-device link error."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


class ProjectWorkspace:
    """Manages the filesystem layout, paths, and versioned execution runs for a commercial project."""

    topic: str
    project_id: str
    version: str
    projects_root: Path
    project_root: Path
    runs_dir: Path
    root: Path  # Points to the active run directory (runs/{version}) for backward compatibility
    input_dir: Path
    project_json_path: Path
    prompt_ledger_path: Path
    artifacts_dir: Path
    keyframes_dir: Path
    media_dir: Path
    raw_clips_dir: Path
    synced_clips_dir: Path
    audio_dir: Path
    telemetry_dir: Path
    master_video_path: Path
    master_video_short_path: Path
    thumbnail_path: Path
    thumbnail_short_path: Path

    def __init__(
        self,
        topic: Union[str, ProductArchetype],
        project_id: str,
        version: str = "v1",
        base_dir: Optional[Union[Path, str]] = None,
    ) -> None:
        self.topic = topic.value if isinstance(topic, ProductArchetype) else str(topic).strip()
        if not self.topic:
            self.topic = ProductArchetype.GENERAL_COMMERCIAL.value

        self.project_id = str(project_id).strip()
        if not self.project_id:
            raise ValueError("project_id cannot be empty")

        self.version = str(version).strip() or "v1"

        # Resolve projects root directory
        if base_dir is not None:
            raw_base = Path(base_dir).resolve()
            if raw_base.name == "projects":
                self.projects_root = raw_base
            elif (raw_base / "projects").is_dir():
                self.projects_root = raw_base / "projects"
            else:
                self.projects_root = raw_base / "projects"
        else:
            self.projects_root = PROJECTS_DIR.resolve()

        # Project level paths
        self.project_root = self.projects_root / self.topic / self.project_id
        self.input_dir = self.project_root / "input"
        self.runs_dir = self.project_root / "runs"
        self.project_json_path = self.project_root / "project.json"

        # Run level paths (root points to runs/{version} for full drop-in compatibility)
        self.root = self.runs_dir / self.version
        self.artifacts_dir = self.root / "artifacts"
        self.keyframes_dir = self.root / "keyframes"
        self.media_dir = self.root / "media"
        self.raw_clips_dir = self.media_dir / "raw_clips"
        self.synced_clips_dir = self.media_dir / "synced_clips"
        self.audio_dir = self.media_dir / "audio"
        self.telemetry_dir = self.root / "telemetry"
        self.prompt_ledger_path = self.root / "prompt_ledger.json"

        # Masters and thumbnails (both canonical project_id name and short alias)
        self.master_video_path = self.root / f"final_master_{self.project_id}.mp4"
        self.master_video_short_path = self.root / "master.mp4"
        self.thumbnail_path = self.root / f"thumbnail_{self.project_id}.jpg"
        self.thumbnail_short_path = self.root / "thumbnail.jpg"

    def ensure_dirs(self) -> None:
        """Create all subdirectories for this project workspace and initialize project.json."""
        for path in (
            self.project_root,
            self.input_dir,
            self.runs_dir,
            self.root,
            self.artifacts_dir,
            self.keyframes_dir,
            self.media_dir,
            self.raw_clips_dir,
            self.synced_clips_dir,
            self.audio_dir,
            self.telemetry_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self._ensure_project_json()

    def _ensure_project_json(self) -> None:
        """Ensure project.json exists and tracks current version."""
        now = datetime.now(timezone.utc).isoformat()
        if self.project_json_path.exists():
            try:
                with open(self.project_json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            versions = meta.get("versions") or []
            if self.version not in versions:
                versions.append(self.version)
            meta.update(
                {
                    "project_id": self.project_id,
                    "topic": self.topic,
                    "active_version": self.version,
                    "versions": versions,
                    "updated_at": now,
                }
            )
        else:
            meta = {
                "project_id": self.project_id,
                "topic": self.topic,
                "active_version": self.version,
                "versions": [self.version],
                "created_at": now,
                "updated_at": now,
            }

        with open(self.project_json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def update_project_meta(self, **kwargs: Any) -> Dict[str, Any]:
        """Update arbitrary metadata fields in project.json."""
        self.ensure_dirs()
        meta: Dict[str, Any] = {}
        if self.project_json_path.exists():
            try:
                with open(self.project_json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}

        meta.update(kwargs)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(self.project_json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    def get_project_meta(self) -> Dict[str, Any]:
        """Read metadata from project.json."""
        if not self.project_json_path.exists():
            return {
                "project_id": self.project_id,
                "topic": self.topic,
                "active_version": self.version,
                "versions": [self.version],
            }
        try:
            with open(self.project_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "project_id": self.project_id,
                "topic": self.topic,
                "active_version": self.version,
                "versions": [self.version],
            }

    def list_versions(self) -> List[str]:
        """List all discrete run versions under runs/ sorted."""
        if not self.runs_dir.exists():
            return [self.version]
        found: List[str] = []
        for child in sorted(self.runs_dir.iterdir()):
            if child.is_dir() and re.match(r"^v\d+$", child.name):
                found.append(child.name)
        return found or [self.version]

    def create_next_version(self, inherit_from: Optional[str] = None) -> "ProjectWorkspace":
        """Branch to a new version (e.g. v2), inheriting unmodified assets via hardlinks."""
        existing = self.list_versions()
        numbers = []
        for ver in existing:
            m = re.match(r"^v(\d+)$", ver)
            if m:
                numbers.append(int(m.group(1)))
        next_num = max(numbers, default=0) + 1
        next_ver = f"v{next_num}"

        source_ver = inherit_from or self.version
        source_dir = self.runs_dir / source_ver

        next_ws = ProjectWorkspace(
            topic=self.topic,
            project_id=self.project_id,
            version=next_ver,
            base_dir=self.projects_root,
        )
        next_ws.ensure_dirs()

        # Hardlink media and keyframes from source if available
        if source_dir.exists():
            for folder_name in ("keyframes", "media"):
                src_folder = source_dir / folder_name
                dst_folder = next_ws.root / folder_name
                if src_folder.exists():
                    for src_file in src_folder.rglob("*"):
                        if src_file.is_file():
                            rel = src_file.relative_to(src_folder)
                            dst_file = dst_folder / rel
                            _safe_link_or_copy(src_file, dst_file)

            # Copy baseline artifacts
            src_artifacts = source_dir / "artifacts"
            if src_artifacts.exists():
                for art_file in src_artifacts.glob("*.json"):
                    if art_file.is_file():
                        dst_art = next_ws.artifacts_dir / art_file.name
                        shutil.copy2(art_file, dst_art)
                        # Manifests record absolute media paths; retarget them at this version's own
                        # hardlinked copies so the new run stays self-contained (ADR 0007).
                        text = dst_art.read_text(encoding="utf-8")
                        retargeted = text.replace(str(source_dir), str(next_ws.root))
                        if retargeted != text:
                            dst_art.write_text(retargeted, encoding="utf-8")

        next_ws.update_project_meta(active_version=next_ver)
        return next_ws

    def save_artifact(self, filename: str, data: Union[BaseModel, Dict[str, Any]]) -> Path:
        """Save a Pydantic model or dict as a JSON artifact in artifacts_dir."""
        self.ensure_dirs()
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        target_path = self.artifacts_dir / filename

        if isinstance(data, BaseModel):
            payload = data.model_dump(mode="json")
        elif isinstance(data, dict):
            payload = data
        else:
            raise TypeError(f"data must be a BaseModel instance or dict, got {type(data)}")

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return target_path

    def load_artifact(self, filename: str, model_cls: Type[T]) -> T:
        """Load and validate a JSON artifact from artifacts_dir using model_cls."""
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        target_path = self.artifacts_dir / filename
        if not target_path.exists():
            raise FileNotFoundError(f"Artifact not found at {target_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return model_cls.model_validate(data)

    def inject_artifact(self, name: str, source: Union[Path, str]) -> Path:
        """Validate an agent-supplied canonical artifact and install it in artifacts_dir.

        Raises ``ValueError`` for an unknown name, unreadable JSON or a schema violation and
        ``FileNotFoundError`` for a missing source; the workspace is untouched on any failure.
        """
        models = canonical_artifact_models()
        model_cls = models.get(name)
        if model_cls is None:
            raise ValueError(f"Unknown artifact '{name}'; injectable artifacts: {', '.join(sorted(models))}")
        src = Path(source)
        if not src.is_file():
            raise FileNotFoundError(f"Artifact file not found: {src}")
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name}: {src} is not valid JSON ({exc})") from exc
        try:
            model_cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"{name}: {src} violates the {model_cls.__name__} schema: {_first_error(exc)}") from exc

        self.ensure_dirs()
        target = self.artifacts_dir / f"{name}.json"
        tmp = target.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        return target

    def check_prerequisites(self, stage: int) -> List[str]:
        """Problems that would stop ``stage`` from starting; empty when it can run.

        Each entry is a sentence an agent can act on: what is missing or invalid and how to supply it.
        """
        problems: List[str] = []
        loaded: Dict[str, BaseModel] = {}
        models = canonical_artifact_models()
        for name in STAGE_PREREQUISITES.get(stage, ()):
            path = self.artifacts_dir / f"{name}.json"
            hint = f"run the earlier stages or supply it with --inject {name}=PATH"
            if not path.is_file():
                problems.append(f"{name}.json is missing from {self.artifacts_dir} ({hint})")
                continue
            try:
                loaded[name] = models[name].model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                detail = _first_error(exc) if isinstance(exc, ValidationError) else str(exc)
                problems.append(f"{name}.json is invalid: {detail} ({hint})")

        manifest = loaded.get("asset_manifest")
        if manifest is not None:
            if stage == 6:
                problems.extend(_missing_media("raw_video_clips", manifest.raw_video_clips))
            if stage in (7, 8):
                problems.extend(_missing_media("synced_video_clips", manifest.synced_video_clips))
        if stage == 8 and not self.master_video_path.is_file():
            problems.append(f"master video is missing at {self.master_video_path} (run stage 7)")
        return problems

    def write_prompt_ledger(self, ledger_data: Dict[str, Any]) -> Path:
        """Atomically persist prompt_ledger.json inside the active run directory."""
        self.ensure_dirs()
        tmp = self.prompt_ledger_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ledger_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.prompt_ledger_path)
        return self.prompt_ledger_path

    @classmethod
    def from_campaign_id(
        cls,
        campaign_id: str,
        topic: Optional[Union[str, ProductArchetype]] = None,
        version: Optional[str] = None,
        base_dir: Optional[Union[Path, str]] = None,
    ) -> "ProjectWorkspace":
        """Instantiate workspace from a campaign_id, inferring topic and active version."""
        if base_dir is not None:
            raw_base = Path(base_dir).resolve()
            if raw_base.name == "projects":
                projects_dir = raw_base
            elif (raw_base / "projects").is_dir():
                projects_dir = raw_base / "projects"
            else:
                projects_dir = raw_base / "projects"
        else:
            projects_dir = PROJECTS_DIR.resolve()

        resolved_topic: str = ProductArchetype.GENERAL_COMMERCIAL.value
        if topic is not None:
            resolved_topic = topic.value if isinstance(topic, ProductArchetype) else str(topic).strip()
        elif projects_dir.exists():
            for topic_dir in projects_dir.iterdir():
                if topic_dir.is_dir():
                    candidate = topic_dir / campaign_id
                    if candidate.is_dir():
                        resolved_topic = topic_dir.name
                        break

        # Check existing project.json for active_version if version was not explicitly passed
        resolved_version = version
        if resolved_version is None:
            project_json = projects_dir / resolved_topic / campaign_id / "project.json"
            if project_json.exists():
                try:
                    with open(project_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    resolved_version = meta.get("active_version") or "v1"
                except Exception:
                    resolved_version = "v1"
            else:
                resolved_version = "v1"

        return cls(
            topic=resolved_topic,
            project_id=campaign_id,
            version=resolved_version,
            base_dir=projects_dir,
        )

    @classmethod
    def list_projects(
        cls,
        topic: Optional[Union[str, ProductArchetype]] = None,
        base_dir: Optional[Union[Path, str]] = None,
    ) -> List["ProjectWorkspace"]:
        """Discover existing project workspaces under projects/."""
        if base_dir is not None:
            raw_base = Path(base_dir).resolve()
            if raw_base.name == "projects":
                projects_dir = raw_base
            elif (raw_base / "projects").is_dir():
                projects_dir = raw_base / "projects"
            else:
                projects_dir = raw_base / "projects"
        else:
            projects_dir = PROJECTS_DIR.resolve()

        workspaces: List[ProjectWorkspace] = []
        if not projects_dir.exists():
            return workspaces

        filter_topic_str: Optional[str] = None
        if topic is not None:
            filter_topic_str = topic.value if isinstance(topic, ProductArchetype) else str(topic).strip()

        for topic_dir in sorted(projects_dir.iterdir()):
            if not topic_dir.is_dir():
                continue
            if filter_topic_str is not None and topic_dir.name != filter_topic_str:
                continue

            for project_dir in sorted(topic_dir.iterdir()):
                if project_dir.is_dir():
                    workspaces.append(
                        cls.from_campaign_id(
                            campaign_id=project_dir.name,
                            topic=topic_dir.name,
                            base_dir=projects_dir,
                        )
                    )

        return workspaces
