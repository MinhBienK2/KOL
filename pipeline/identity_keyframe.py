"""Step 4: KOL Identity Locking & Clean Keyframe Generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import numpy as np
from PIL import Image

from pipeline import telemetry
from pipeline.config import ARTIFACTS_DIR, BASE_DIR, CHARACTER_PATH, KEYFRAMES_DIR
from pipeline.archetypes import CharacterRole, ProductArchetype
from pipeline.wardrobe import resolve_wardrobe_and_environment
from pipeline.schemas import AssetManifestArtifact, KeyframeAsset, ScenePlanArtifact
from pipeline.workspace import ProjectWorkspace
from tools.dramaclaw_shot_builder import inpaint_watermark_array

STAGE_IDENTITY_KEYFRAMES = telemetry.stage_number("identity_keyframes")

# Pre-flight minimum long edge (px) per canonical identity asset (ADR 0008).
MIN_LONG_EDGE = {"character_sheet": 2048, "face_anchor": 1536, "product_hero": 1024}


#: Appended to every synthesized first frame: a still moment the video model can start from.
SYNTH_FRAME_SUFFIX = (
    "Vertical 9:16 photograph: the very first frame of this commercial shot, a still moment with no "
    "motion blur. Photoreal, natural skin texture, true-to-life colours. No text, no captions, no "
    "subtitles, no logos, no watermark."
)


def compose_synthesis_prompt(shot: Any, reference_roles: List[str]) -> str:
    """Scene prompt for a first-frame image: reference roles first, then the shot's own prompt."""
    roles = {
        "face_anchor": "is the woman: keep her exact face, facial proportions and hairstyle",
        "product_hero": "is the product: reproduce this exact object, its shape, colour, surface and details",
    }
    lines = [
        f"Reference image {i} {roles.get(role, 'is a visual reference')}." for i, role in enumerate(reference_roles, 1)
    ]
    if lines:
        lines.append("Do not copy any reference's background, lighting or framing.")
    return "\n".join([*lines, f"SHOT: {shot.prompt_6part}", SYNTH_FRAME_SUFFIX])


def synthesize_first_frame(prompt: str, out_path: Path, reference_paths: List[Path]) -> Path:
    """Render a scene first frame from references (Flow2API, several images in one message)."""
    from pipeline.continuity import media

    media.flow2api_image(prompt, out_path, reference_paths=reference_paths)
    raw = cv2.imread(str(out_path))
    if raw is None:
        raise IdentityReferenceError(f"Synthesized frame is unreadable: {out_path}")
    cleaned, _ = inpaint_watermark_array(raw)
    cv2.imwrite(str(out_path), cleaned)
    return out_path


def _identity_vs_anchor(face_anchor: Optional[Path], image: Path) -> Optional[float]:
    if face_anchor is None:
        return None
    try:
        from pipeline import face_identity

        sim = face_identity.identity_similarity(face_anchor, image)
    except Exception:  # noqa: BLE001 - face models unavailable must not block the stage
        return None
    return round(sim, 4) if sim is not None else None


class IdentityReferenceError(RuntimeError):
    """An identity/product reference is missing or unusable. Never papered over with a fallback."""


class FirstFrameSynthesisError(RuntimeError):
    """A shot's first frame could not be rendered. Stage 4 stops; no reference is padded in its place."""


ARCHETYPE_IDENTITY_MAP = {
    ProductArchetype.FASHION_APPAREL: "kol_main_fashion",
    ProductArchetype.TECH_GADGETS: "kol_main_techwear",
    ProductArchetype.BEAUTY_SKINCARE: "kol_main_spa",
    ProductArchetype.HOME_LIFESTYLE: "kol_main_cozy",
    ProductArchetype.GENERAL_COMMERCIAL: "kol_main_office",
}


def resolve_canonical_identity_reference(
    archetype: ProductArchetype,
    char_data: dict,
    default_portrait: Path,
) -> Path:
    """Binds character shots uniformly to the campaign's archetype identity sheet."""
    identities = {ident["identity_id"]: ident for ident in char_data.get("identities", [])}
    ident_id = ARCHETYPE_IDENTITY_MAP.get(archetype, "kol_main_office")
    ident = identities.get(ident_id, {})
    sheet_rel = ident.get("character_sheet") or ident.get("reference_sheet") or char_data.get("character_sheet")
    if sheet_rel:
        sheet_path = BASE_DIR / sheet_rel
        if sheet_path.exists():
            return sheet_path
    return default_portrait


def resolve_canonical_character_sheet(
    archetype: ProductArchetype,
    char_data: dict,
    default_sheet: Path | None = None,
) -> Path:
    """Resolves the canonical multi-panel character sheet for the active identity.

    Raises IdentityReferenceError rather than silently substituting a portrait (or another
    persona's sheet): a "sheet" that is not a sheet breaks the R2V identity contract.
    """
    identities = {ident["identity_id"]: ident for ident in char_data.get("identities", [])}
    ident_id = ARCHETYPE_IDENTITY_MAP.get(archetype, "kol_main_office")
    ident = identities.get(ident_id, {})
    sheet_rel = ident.get("character_sheet") or ident.get("reference_sheet") or char_data.get("character_sheet")
    if sheet_rel:
        sheet_path = BASE_DIR / sheet_rel
        if sheet_path.exists():
            return sheet_path
    if default_sheet and default_sheet.exists():
        return default_sheet
    raise IdentityReferenceError(
        f"character_sheet not found for identity '{ident_id}' (declared: {sheet_rel!r}). "
        "Add a 'character_sheet' to the character.json or pass reference_overrides={'character_sheet': <path>}."
    )


def resolve_canonical_face_anchor(
    char_data: dict,
    default_portrait: Path,
) -> Path:
    """Resolves the canonical neutral face anchor portrait."""
    face_rel = char_data.get("face_anchor") or char_data.get("portrait_image")
    if face_rel:
        p = BASE_DIR / face_rel
        if p.exists():
            return p
    if default_portrait.exists():
        return default_portrait
    raise IdentityReferenceError(
        f"face_anchor not found (declared: {face_rel!r}). "
        "Add 'face_anchor' to the character.json or pass reference_overrides={'face_anchor': <path>}."
    )


def is_multi_panel_sheet(path: Path) -> bool:
    """Landscape turnaround grids are references, not usable single-view First Frames."""
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return False
    return w / max(h, 1) > 1.2


def resolve_presenter_first_frame(identity_reference: Path, face_anchor: Path) -> Path:
    """Presenter I2V needs one clean, camera-facing view, never a padded multi-panel sheet."""
    if is_multi_panel_sheet(identity_reference):
        return face_anchor
    return identity_reference


def resolve_product_hero_reference(
    wardrobe: Optional[Any] = None,
    workspace: Optional[ProjectWorkspace] = None,
) -> Path:
    """Resolves a pure product visual reference free of character facial features.

    Product Isolation (ADR 0006): never falls back to a human portrait. Priority: input
    image named like product/hero, then any input image.
    """
    if workspace and hasattr(workspace, "input_dir") and workspace.input_dir.exists():
        candidates: List[Path] = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            candidates.extend(workspace.input_dir.glob(ext))
        candidates = sorted(candidates)
        named = [c for c in candidates if any(k in c.stem.lower() for k in ("product", "hero"))]
        if named or candidates:
            return (named or candidates)[0]
    raise IdentityReferenceError(
        "No product reference available for product_only shots: drop a product image in the "
        "project input/ directory or pass reference_overrides={'product_hero': <path>}. "
        "Character portraits are never substituted (Product Isolation)."
    )


def _resolve_user_path(value: str | Path, label: str, workspace: Optional[Any] = None) -> Path:
    """Resolves an agent-supplied reference: absolute, repo-relative, or relative to project input/."""
    raw = Path(str(value))
    candidates = [raw] if raw.is_absolute() else [BASE_DIR / raw]
    input_dir = getattr(workspace, "input_dir", None)
    if input_dir is not None and not raw.is_absolute():
        candidates.append(Path(input_dir) / raw)
    for c in candidates:
        if c.is_file():
            return c
    raise IdentityReferenceError(f"Reference override '{label}' not found: {value}")


def load_reference_overrides(
    artifacts_dir: Path,
    explicit: Optional[Dict[str, Any]] = None,
    workspace: Optional[Any] = None,
) -> Dict[str, Any]:
    """Merges agent-supplied reference overrides: input/ file < artifacts file < explicit argument.

    Schema: {"character_sheet", "face_anchor", "product_hero": path,
             "shots": {shot_id: {"first_frame": path, "references": [path, ...]}}}
    """
    merged: Dict[str, Any] = {"shots": {}}
    sources: List[Path] = []
    input_dir = getattr(workspace, "input_dir", None)
    if input_dir is not None:
        sources.append(Path(input_dir) / "reference_overrides.json")
    sources.append(artifacts_dir / "reference_overrides.json")
    layers: List[Dict[str, Any]] = []
    for src in sources:
        if src.exists():
            try:
                data = json.loads(src.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise IdentityReferenceError(f"Invalid JSON in {src}: {exc}") from exc
            if not isinstance(data, dict):
                raise IdentityReferenceError(f"{src} must contain a JSON object")
            layers.append(data)
    if explicit:
        layers.append(explicit)
    for layer in layers:
        merged.update({k: v for k, v in layer.items() if k != "shots"})
        merged["shots"].update(layer.get("shots") or {})
    return merged


def preflight_identity_assets(
    assets: Dict[str, Path],
    strict_resolution: bool = False,
) -> Dict[str, Any]:
    """Pre-flight Gate (ADR 0008): asset completeness and minimum resolution before diffusion.

    Missing/unreadable assets always raise. Low resolution is a warning unless
    strict_resolution=True. The raised error carries the report as `.report`.
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    detail: Dict[str, Any] = {}
    for name, path in assets.items():
        path = Path(path)
        if not path.is_file():
            errors.append({"asset": name, "issue": "missing", "path": str(path)})
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
        except Exception as exc:
            errors.append({"asset": name, "issue": f"unreadable image: {exc}", "path": str(path)})
            continue
        detail[name] = {"path": _repo_rel(path), "width": w, "height": h}
        minimum = MIN_LONG_EDGE.get(name)
        if minimum and max(w, h) < minimum:
            warnings.append(
                {
                    "asset": name,
                    "issue": f"long edge {max(w, h)}px below minimum resolution {minimum}px",
                    "path": str(path),
                }
            )
    report = {"ok": not errors, "assets": detail, "errors": errors, "warnings": warnings}
    failure: Optional[str] = None
    if errors:
        failure = "Identity pre-flight gate failed, unusable assets: " + ", ".join(e["asset"] for e in errors)
    elif strict_resolution and warnings:
        failure = "Identity pre-flight gate failed, below minimum resolution: " + ", ".join(
            w["asset"] for w in warnings
        )
    if failure:
        err = IdentityReferenceError(failure)
        err.report = report  # type: ignore[attr-defined]
        raise err
    return report


def _repo_rel(path: str | Path) -> str:
    """Path relative to the repo root (identity anchors live outside the run root)."""
    try:
        return str(Path(path).resolve().relative_to(BASE_DIR))
    except Exception:
        return str(path)


def prepare_9_16_frame(
    src_img_path: str | Path,
    out_img_path: str | Path,
    target_width: int = 1080,
    target_height: int = 1920,
    stats: Optional[Dict[str, Any]] = None,
) -> tuple[int, int]:
    """Pads or resizes image to exact 9:16 target dimensions (1080x1920) with blurred ambient background.

    The Telea watermark pass runs on the scaled source (where a watermark actually lives),
    not on the padded frame. When `stats` is given it receives `watermark_pixels`.
    """
    src_path = Path(src_img_path)
    if not src_path.is_absolute():
        src_path = BASE_DIR / src_path
    if not src_path.exists():
        raise FileNotFoundError(f"Source image not found: {src_path}")

    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size

    # Target 9:16 aspect ratio
    target_ratio = target_width / target_height
    src_ratio = src_w / src_h

    # Create background by stretching and heavily blurring original
    bg = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    bg_cv = cv2.cvtColor(np.array(bg), cv2.COLOR_RGB2BGR)
    bg_cv = cv2.GaussianBlur(bg_cv, (99, 99), 30)

    # Scale original image to fit within target frame while maintaining aspect ratio
    if src_ratio > target_ratio:
        # Source is wider than 9:16 -> scale to target width
        new_w = target_width
        new_h = int(target_width / src_ratio)
    else:
        # Source is taller or equal -> scale to target height
        new_h = target_height
        new_w = int(target_height * src_ratio)

    img_scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    img_cv = cv2.cvtColor(np.array(img_scaled), cv2.COLOR_RGB2BGR)
    # Clean bottom-right watermark area with Telea Inpainting (guarded against bright content)
    img_cv, wm_pixels = inpaint_watermark_array(img_cv)
    if stats is not None:
        stats["watermark_pixels"] = wm_pixels

    # Center overlay onto blurred background
    x_offset = (target_width - new_w) // 2
    y_offset = (target_height - new_h) // 2
    bg_cv[y_offset : y_offset + new_h, x_offset : x_offset + new_w] = img_cv

    out_path = Path(out_img_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        cv2.imwrite(str(out_path), bg_cv, [cv2.IMWRITE_JPEG_QUALITY, 92])
    else:
        cv2.imwrite(str(out_path), bg_cv)

    return target_width, target_height


def _shot_dispatch(shot: Any) -> str:
    """Directorial Dispatch: product_hero | r2v | i2v for a storyboard shot."""
    role = getattr(shot, "character_role", None)
    role_val = getattr(role, "value", role)
    if role_val == CharacterRole.PRODUCT_ONLY.value:
        return "product_hero"
    if role_val == CharacterRole.MODEL.value or getattr(shot, "generation_mode", None) == "r2v":
        return "r2v"
    return "i2v"


def generate_clean_keyframes(
    scene_plan: ScenePlanArtifact | None = None,
    scene_plan_path: Path | None = None,
    output_dir: Path | None = None,
    keyframes_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
    reference_overrides: Optional[Dict[str, Any]] = None,
    character_path: Optional[Path] = None,
    strict_resolution: bool = False,
    synthesize_frames: bool = False,
) -> AssetManifestArtifact:
    """Generates identity-locked, watermark-cleaned keyframes for all storyboard shots.

    With ``synthesize_frames`` each shot's first frame is rendered from its scene prompt with the
    face anchor and/or product hero as references (assets are references, never frames), unless the
    shot has an explicit ``first_frame`` override. A failed synthesis raises
    :class:`FirstFrameSynthesisError` and no manifest is written: a padded studio portrait or
    catalogue photo is not the planned scene, so it is never used as a stand-in. Without
    ``synthesize_frames`` (offline / ``ffmpeg`` placeholder runs only) the reference is padded into
    9:16 and marked ``keyframe_source: "reference_pad"``; Stage 5 refuses such frames for real video.

    Agents can direct identity with `reference_overrides` (or a `reference_overrides.json`
    in the artifacts/ or input/ directory), see `load_reference_overrides`, and a custom
    `character_path`. Missing/unusable references raise IdentityReferenceError before any
    keyframe is written (Pre-flight Gate); nothing is silently faked.
    """
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (output_dir or ARTIFACTS_DIR)
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)
    target_keyframes_dir = workspace.keyframes_dir if workspace is not None else (keyframes_dir or KEYFRAMES_DIR)
    target_keyframes_dir.mkdir(parents=True, exist_ok=True)

    if scene_plan is None:
        source_plan = scene_plan_path or (target_artifacts_dir / "scene_plan.json")
        if not source_plan.exists():
            raise FileNotFoundError(f"Scene plan file not found at {source_plan}")
        with open(source_plan, "r", encoding="utf-8") as f:
            scene_plan = ScenePlanArtifact.model_validate(json.load(f))

    with open(character_path or CHARACTER_PATH, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    default_portrait = BASE_DIR / char_data.get("portrait_image", "assets/characters/kol_main/portrait.png")
    # Resolve active wardrobe and staging profile from script.json
    script_file = target_artifacts_dir / "script.json"
    archetype_val = ProductArchetype.GENERAL_COMMERCIAL
    if script_file.exists():
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                s_data = json.load(f)
                archetype_val = ProductArchetype(s_data.get("archetype", "general_commercial"))
        except Exception:
            pass

    wardrobe, environment = resolve_wardrobe_and_environment(archetype_val)

    # ---- Resolve every reference the plan needs up front (agent overrides win) -----------------
    overrides = load_reference_overrides(target_artifacts_dir, reference_overrides, workspace)
    dispatch = {shot.shot_id: _shot_dispatch(shot) for shot in scene_plan.shots}
    modes = set(dispatch.values())

    def _override(key: str) -> Optional[Path]:
        return _resolve_user_path(overrides[key], key, workspace) if overrides.get(key) else None

    shot_overrides: Dict[str, Dict[str, Any]] = {}
    for shot_id, entry in (overrides.get("shots") or {}).items():
        if shot_id not in dispatch:
            continue
        shot_overrides[shot_id] = {
            "first_frame": _resolve_user_path(entry["first_frame"], f"{shot_id}.first_frame", workspace)
            if entry.get("first_frame")
            else None,
            "references": [
                _resolve_user_path(r, f"{shot_id}.references", workspace) for r in (entry.get("references") or [])
            ],
            "synthesis_references": [
                _resolve_user_path(r, f"{shot_id}.synthesis_references", workspace)
                for r in (entry.get("synthesis_references") or [])
            ],
        }
        if entry.get("synthesize") is False:
            raise IdentityReferenceError(
                f'{shot_id}: "synthesize": false is not supported: a padded reference is not a first frame; '
                f'give "first_frame" to supply the frame yourself'
            )

    face_anchor: Optional[Path] = None
    char_sheet: Optional[Path] = None
    identity_ref: Optional[Path] = None
    product_hero_ref: Optional[Path] = None
    if modes & {"i2v", "r2v"}:
        face_anchor = _override("face_anchor") or resolve_canonical_face_anchor(char_data, default_portrait)
        identity_ref = resolve_canonical_identity_reference(archetype_val, char_data, face_anchor)
    if "r2v" in modes:
        char_sheet = _override("character_sheet") or resolve_canonical_character_sheet(archetype_val, char_data)
    if "product_hero" in modes or synthesize_frames:
        product_hero_ref = _override("product_hero") or resolve_product_hero_reference(wardrobe, workspace=workspace)

    needed = {
        "character_sheet": char_sheet,
        "face_anchor": face_anchor,
        "product_hero": product_hero_ref,
    }
    preflight_error: Optional[IdentityReferenceError] = None
    try:
        preflight = preflight_identity_assets(
            {k: v for k, v in needed.items() if v is not None}, strict_resolution=strict_resolution
        )
    except IdentityReferenceError as exc:
        preflight_error = exc
        preflight = getattr(exc, "report", {"ok": False, "errors": [str(exc)], "warnings": []})
    with open(target_artifacts_dir / "identity_preflight.json", "w", encoding="utf-8") as f:
        json.dump(preflight, f, ensure_ascii=False, indent=2)
    if preflight_error is not None:
        telemetry.note(f"Identity pre-flight gate FAILED: {preflight_error}", ok=False)
        raise preflight_error
    if preflight["warnings"]:
        telemetry.note(
            f"Identity pre-flight: {len(preflight['warnings'])} low-resolution reference warning(s)",
            warnings=preflight["warnings"],
        )

    keyframe_assets: List[KeyframeAsset] = []
    telea_inpainted = 0
    fallback_references = 0

    for idx, shot in enumerate(scene_plan.shots, start=1):
        gen_mode = dispatch[shot.shot_id]
        per_shot = shot_overrides.get(shot.shot_id, {})
        frame_override: Optional[Path] = per_shot.get("first_frame")
        extra_refs: List[Path] = per_shot.get("references") or []
        reference_is_fallback = False
        origin = "override" if frame_override else "canonical"

        if gen_mode == "product_hero":
            # Product isolation: strictly avoid character face injection in product macro shots
            ref_path = frame_override or product_hero_ref
            ref_assets = [_repo_rel(p) for p in (extra_refs or [ref_path])]
        elif gen_mode == "r2v":
            # Model role / kinetic action: Directorial Dispatch routes to R2V with Dual-Anchor.
            # The multi-panel sheet is a reference, never a frame: the clean frame is the single-view face anchor.
            ref_path = frame_override or face_anchor
            ref_assets = [_repo_rel(p) for p in (extra_refs or [char_sheet, face_anchor])]
        else:
            # Presenter role (or direct speech): Directorial Dispatch routes to I2V with First Frame
            if frame_override:
                ref_path = frame_override
            elif shot.reference_expression and (BASE_DIR / shot.reference_expression).exists():
                ref_path = BASE_DIR / shot.reference_expression
                origin = "expression"
            else:
                if shot.reference_expression:
                    reference_is_fallback = True  # declared expression asset is missing: surfaced, not hidden
                    origin = "fallback"
                ref_path = resolve_presenter_first_frame(identity_ref, face_anchor)
            ref_assets = [_repo_rel(p) for p in (extra_refs or [ref_path])]
        clean_keyframe_path = target_keyframes_dir / f"{shot.shot_id}_clean.jpg"

        keyframe_source = "override" if frame_override else "reference_pad"
        identity_score: Optional[float] = None
        synth_refs: List[Path] = []
        if synthesize_frames and not frame_override:
            if per_shot.get("synthesis_references"):
                synth_refs = list(per_shot["synthesis_references"])
                synth_roles = ["reference"] * len(synth_refs)
            elif gen_mode == "product_hero":
                synth_refs, synth_roles = [product_hero_ref], ["product_hero"]
            else:
                synth_refs, synth_roles = [face_anchor], ["face_anchor"]
                if product_hero_ref is not None:
                    synth_refs.append(product_hero_ref)
                    synth_roles.append("product_hero")
            synth_path = target_keyframes_dir / f"{shot.shot_id}_synth.png"
            try:
                synthesize_first_frame(compose_synthesis_prompt(shot, synth_roles), synth_path, synth_refs)
            except Exception as exc:
                telemetry.note(f"{shot.shot_id}: first-frame synthesis failed: {str(exc)[:300]}", ok=False)
                raise FirstFrameSynthesisError(
                    f"{shot.shot_id}: first-frame synthesis failed ({exc}). Stage 4 stopped; fix the image "
                    f"provider and resume with --from-stage 4"
                ) from exc
            ref_path = synth_path
            keyframe_source = "synthesized"
            if gen_mode != "product_hero":
                identity_score = _identity_vs_anchor(face_anchor, synth_path)
            if gen_mode != "r2v" and not extra_refs:
                ref_assets = [_repo_rel(ref_path)]

        # Format and fit into 9:16 target with Telea Inpainting (guarded; raises on unreadable input).
        wm_stats: Dict[str, Any] = {}
        w, h = prepare_9_16_frame(ref_path, clean_keyframe_path, target_width=1080, target_height=1920, stats=wm_stats)
        telea_inpainted += 1
        if reference_is_fallback:
            fallback_references += 1

        recorder = telemetry.current()
        keyframe_record = (
            recorder.register_artifact(
                clean_keyframe_path,
                stage=STAGE_IDENTITY_KEYFRAMES,
                label=f"{shot.shot_id} clean 9:16 keyframe",
            )
            if recorder is not None
            else None
        )
        telemetry.stage_progress(
            STAGE_IDENTITY_KEYFRAMES,
            idx,
            len(scene_plan.shots),
            unit="shots",
            label=f"Keyframe {shot.shot_id}",
            item={
                "id": shot.shot_id,
                "status": "keyframe_ready",
                "source_image": _repo_rel(ref_path),
                "cleaned_image": (keyframe_record or {}).get("rel_path") or str(clean_keyframe_path),
                "watermark_removed": True,
                "telea_inpaint": True,
                "watermark_pixels": wm_stats.get("watermark_pixels", 0),
                "width": w,
                "height": h,
                "fallback_reference": reference_is_fallback,
                "reference_origin": origin,
                "generation_mode": gen_mode,
                "reference_assets": ref_assets,
                "keyframe_source": keyframe_source,
                "identity_vs_anchor": identity_score,
            },
        )

        keyframe_assets.append(
            KeyframeAsset(
                shot_id=shot.shot_id,
                image_path=str(ref_path),
                cleaned_image_path=str(clean_keyframe_path),
                watermark_removed=True,
                width=w,
                height=h,
                generation_mode=gen_mode,
                reference_assets=ref_assets,
                keyframe_source=keyframe_source,
                synthesis_references=[_repo_rel(p) for p in synth_refs] or None,
                identity_vs_anchor=identity_score,
            )
        )
    total_shots = len(scene_plan.shots)
    telemetry.note(
        f"Telea watermark pass applied to {telea_inpainted}/{total_shots} keyframes "
        f"({fallback_references} identity anchors resolved from fallback references)",
        telea_inpaint_applied=telea_inpainted,
        total_keyframes=total_shots,
        fallback_references=fallback_references,
    )
    manifest = AssetManifestArtifact(
        campaign_id=scene_plan.campaign_id,
        keyframes=keyframe_assets,
    )

    out_file = target_artifacts_dir / "asset_manifest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    return manifest
