"""Project Workspace module for self-contained, topic-driven output management.

Restructures fragmented output trees into:
output/projects/{topic}/{project_id}/
├── artifacts/
├── keyframes/
├── media/
│   ├── raw_clips/
│   ├── synced_clips/
│   └── audio/
├── final_master_{project_id}.mp4
└── thumbnail_{project_id}.jpg
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel

from pipeline.archetypes import ProductArchetype
from pipeline.config import BASE_DIR, OUTPUT_DIR

T = TypeVar("T", bound=BaseModel)


class ProjectWorkspace:
    """Manages the filesystem layout, paths, and serialized artifacts for a project."""

    topic: str
    project_id: str
    root: Path
    artifacts_dir: Path
    keyframes_dir: Path
    media_dir: Path
    raw_clips_dir: Path
    synced_clips_dir: Path
    audio_dir: Path
    master_video_path: Path
    thumbnail_path: Path

    def __init__(
        self,
        topic: Union[str, ProductArchetype],
        project_id: str,
        base_dir: Optional[Union[Path, str]] = None,
    ) -> None:
        self.topic = topic.value if isinstance(topic, ProductArchetype) else str(topic).strip()
        if not self.topic:
            self.topic = ProductArchetype.GENERAL_COMMERCIAL.value

        self.project_id = str(project_id).strip()
        if not self.project_id:
            raise ValueError("project_id cannot be empty")

        if base_dir is not None:
            base_output_dir = Path(base_dir).resolve()
        else:
            base_output_dir = OUTPUT_DIR.resolve()

        self.root = base_output_dir / "projects" / self.topic / self.project_id
        self.artifacts_dir = self.root / "artifacts"
        self.keyframes_dir = self.root / "keyframes"
        self.media_dir = self.root / "media"
        self.raw_clips_dir = self.media_dir / "raw_clips"
        self.synced_clips_dir = self.media_dir / "synced_clips"
        self.audio_dir = self.media_dir / "audio"
        self.master_video_path = self.root / f"final_master_{self.project_id}.mp4"
        self.thumbnail_path = self.root / f"thumbnail_{self.project_id}.jpg"

    def ensure_dirs(self) -> None:
        """Create all subdirectories for this project workspace."""
        for path in (
            self.root,
            self.artifacts_dir,
            self.keyframes_dir,
            self.media_dir,
            self.raw_clips_dir,
            self.synced_clips_dir,
            self.audio_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

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

    @classmethod
    def from_campaign_id(
        cls,
        campaign_id: str,
        topic: Optional[Union[str, ProductArchetype]] = None,
        base_dir: Optional[Union[Path, str]] = None,
    ) -> "ProjectWorkspace":
        """Instantiate workspace from a campaign_id, inferring topic if not provided.

        Inference scans existing project folders under base_dir/projects/*/{campaign_id}.
        If not found, defaults to ProductArchetype.GENERAL_COMMERCIAL.
        """
        resolved_base = Path(base_dir).resolve() if base_dir is not None else OUTPUT_DIR.resolve()
        projects_dir = resolved_base / "projects"

        if topic is not None:
            resolved_topic = topic
        else:
            resolved_topic = ProductArchetype.GENERAL_COMMERCIAL.value
            if projects_dir.exists():
                for topic_dir in projects_dir.iterdir():
                    if topic_dir.is_dir():
                        candidate = topic_dir / campaign_id
                        if candidate.is_dir():
                            resolved_topic = topic_dir.name
                            break

        return cls(topic=resolved_topic, project_id=campaign_id, base_dir=resolved_base)

    @classmethod
    def list_projects(
        cls,
        topic: Optional[Union[str, ProductArchetype]] = None,
        base_dir: Optional[Union[Path, str]] = None,
    ) -> List["ProjectWorkspace"]:
        """Discover existing project workspaces under base_dir/projects/."""
        resolved_base = Path(base_dir).resolve() if base_dir is not None else OUTPUT_DIR.resolve()
        projects_dir = resolved_base / "projects"

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
                        cls(
                            topic=topic_dir.name,
                            project_id=project_dir.name,
                            base_dir=resolved_base,
                        )
                    )

        return workspaces
