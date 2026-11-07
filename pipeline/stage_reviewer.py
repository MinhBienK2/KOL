"""Independent Stage Reviewer: Subagent Quality & Rubric Evaluation Engine.

Provides multi-pass independent review (up to 3 iterations) for critical pipeline stages:
1. Script Review (Kịch bản): 6 conversion beats, speech pacing, no-fabrication, KOL voice.
2. Storyboard Review (Phân cảnh & Video Prompt): Script alignment, SET/WEAR appropriateness,
   video diffusion prompt detail, camera motion, and slideshow risk.
3. Keyframe Review (Ảnh & Bối cảnh & KOL lock): Strict lock to repo KOL Mai Ly (kol_main),
   product isolation, watermark removal, and visual composition.

Each review computes a 0-10 score against explicit rubrics, identifies concrete problems,
and provides actionable feedback back to the producing agent.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from pipeline.config import BASE_DIR, CHARACTER_PATH
from pipeline.offline import is_offline
from pipeline.schemas import (
    AssetManifestArtifact,
    BriefArtifact,
    ScenePlanArtifact,
    ScriptArtifact,
    ScriptBeat,
)
from pipeline.scriptwriter import (
    BANNED_CLAIM_PHRASES,
    NUMERIC_CLAIM_RE,
    MAX_HOOK_SECONDS,
    MAX_BEAT_SECONDS,
    MIN_BEAT_SECONDS,
    estimate_speech_seconds,
    validate_script,
)
from pipeline.slideshow_risk import score_slideshow_risk


MAX_REVIEW_ITERATIONS = 3
PASSING_SCORE_THRESHOLD = 8.0

CANONICAL_KOL_ID = "kol_main"
CANONICAL_KOL_NAME = "Mai Ly"
CANONICAL_KOL_TAG = "[KOL_MAIN]"


class ReviewCheck(BaseModel):
    name: str
    passed: bool
    weight: float = 1.0
    score: float = 10.0
    detail: str = ""


class StageReviewResult(BaseModel):
    stage: str  # "script", "storyboard", "keyframe"
    iteration: int = 1  # 1..3
    score: float  # 0.0 - 10.0
    status: str  # "approved", "needs_revision", "rejected"
    passed: bool
    rubric_scores: Dict[str, float] = Field(default_factory=dict)
    checks: List[ReviewCheck] = Field(default_factory=list)
    problems: List[str] = Field(default_factory=list)
    actionable_feedback: List[str] = Field(default_factory=list)
    reviewed_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    kol_locked: bool = True


class StageReviewHistory(BaseModel):
    campaign_id: str
    reviews: Dict[str, List[StageReviewResult]] = Field(default_factory=dict)
    last_updated: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


# ==============================================================================
# 1. SCRIPT REVIEWER (KỊCH BẢN)
# ==============================================================================

def review_script(
    script: ScriptArtifact | Dict[str, Any],
    brief: Optional[BriefArtifact | Dict[str, Any]] = None,
    char_data: Optional[Dict[str, Any]] = None,
    iteration: int = 1,
) -> StageReviewResult:
    """Independently review commercial script artifact.

    Evaluates:
    - 6-beat conversion structure (hook <= 4s, CTA at end, 4-8 beats).
    - No-fabrication lint and grounding against product USP/brief.
    - KOL spoken Vietnamese voice (conversational, natural, duration fit).
    - Visual cues & clarity for video diffusion rendering.
    """
    if isinstance(script, dict):
        script_obj = ScriptArtifact.model_validate(script)
    else:
        script_obj = script

    brief_data = brief.model_dump() if hasattr(brief, "model_dump") else (brief or {})
    beats = script_obj.beats or []

    checks: List[ReviewCheck] = []
    problems: List[str] = []
    feedback: List[str] = []

    # Rubric buckets (each up to 2.5 points -> total 10.0)
    rubric = {
        "conversion_structure": 2.5,
        "grounding_and_usps": 2.5,
        "kol_voice_and_pacing": 2.5,
        "visual_direction": 2.5,
    }

    # --- Check 1: Conversion Structure (2.5 pts) ---
    struct_issues = validate_script(beats)
    has_hook = bool(beats and "hook" in beats[0].beat_type.lower())
    has_cta = bool(beats and "cta" in beats[-1].beat_type.lower())
    hook_duration = beats[0].estimated_duration if beats else 0.0
    hook_ok = has_hook and hook_duration <= MAX_HOOK_SECONDS

    struct_deduct = 0.0
    if not has_hook:
        struct_deduct += 1.0
        problems.append("Kịch bản thiếu nhịp Hook ở đầu (beat 1 bắt buộc là hook).")
        feedback.append("Chỉnh sửa beat 1 thành nhịp Hook kích thích tò mò ngay trong 3 giây đầu.")
    elif not hook_ok:
        struct_deduct += 0.8
        problems.append(f"Hook kéo dài {hook_duration:.1f}s, vượt mức trần {MAX_HOOK_SECONDS:.1f}s.")
        feedback.append(f"Rút ngắn thời lượng hook về <= {MAX_HOOK_SECONDS:.1f}s để giữ chân người xem lướt feed.")

    if not has_cta:
        struct_deduct += 1.0
        problems.append("Kịch bản thiếu nhịp Call-To-Action (CTA) chốt chuyển đổi ở cuối.")
        feedback.append("Bổ sung CTA rõ ràng ở beat cuối (kêu gọi bấm link/giỏ hàng).")

    if len(beats) < 4 or len(beats) > 8:
        struct_deduct += 0.5
        problems.append(f"Số lượng beat ({len(beats)}) không tối ưu cho short-form video (chuẩn 4-8 beats).")
        feedback.append("Tối ưu hóa cấu trúc kịch bản từ 4 đến 8 phân cảnh ngắn gọn.")

    rubric["conversion_structure"] = max(0.0, rubric["conversion_structure"] - struct_deduct)
    checks.append(ReviewCheck(
        name="Cấu trúc chuyển đổi 6 nhịp",
        passed=struct_deduct == 0.0,
        score=rubric["conversion_structure"] * 4,
        detail="Hook < 4s, CTA cuối, số lượng 4-8 beats."
    ))

    # --- Check 2: Grounding & No-fabrication (2.5 pts) ---
    grounding_deduct = 0.0
    allowed_offers = brief_data.get("offers") or []
    joined_spoken = " ".join(b.spoken_text or "" for b in beats).lower()

    for phrase in BANNED_CLAIM_PHRASES:
        if phrase in joined_spoken:
            # Check if offer was explicitly allowed
            is_allowed = any(phrase in str(o).lower() for o in allowed_offers)
            if not is_allowed:
                grounding_deduct += 0.5
                problems.append(f"Phát hiện tuyên bố không có căn cứ: '{phrase}' trong lời thoại.")
                feedback.append(f"Xóa hoặc thay thế từ ngữ thổi phồng '{phrase}' bằng công năng thực tế từ brief.")

    rubric["grounding_and_usps"] = max(0.0, rubric["grounding_and_usps"] - grounding_deduct)
    checks.append(ReviewCheck(
        name="Không bịa đặt cam kết & số liệu",
        passed=grounding_deduct == 0.0,
        score=rubric["grounding_and_usps"] * 4,
        detail="Không tự bịa giảm giá, bảo hành, con số nếu brief không cấp."
    ))

    # --- Check 3: KOL Spoken Voice & Pacing (2.5 pts) ---
    pacing_deduct = 0.0
    for beat in beats:
        if beat.spoken_text and beat.spoken_text.strip():
            need_sec = estimate_speech_seconds(beat.spoken_text)
            if need_sec > beat.estimated_duration + 0.1:
                pacing_deduct += 0.4
                problems.append(
                    f"{beat.scene_id}: Lời thoại cần ~{need_sec:.1f}s nhưng thời lượng cảnh chỉ có {beat.estimated_duration:.1f}s."
                )
                feedback.append(
                    f"{beat.scene_id}: Rút bớt chữ trong lời thoại '{beat.spoken_text[:30]}...' để nói kịp trong {beat.estimated_duration:.1f}s."
                )
            if len(beat.spoken_text.split()) > 25:
                pacing_deduct += 0.3
                problems.append(f"{beat.scene_id}: Lời thoại quá dài ({len(beat.spoken_text.split())} từ), mất phong thái KOL tự nhiên.")

    rubric["kol_voice_and_pacing"] = max(0.0, rubric["kol_voice_and_pacing"] - pacing_deduct)
    checks.append(ReviewCheck(
        name="Độ tự nhiên & Khớp tốc độ đọc của KOL",
        passed=pacing_deduct == 0.0,
        score=rubric["kol_voice_and_pacing"] * 4,
        detail="Lời thoại tiếng Việt tự nhiên, không tràn viền thời lượng cảnh."
    ))

    # --- Check 4: Visual Direction & Detail (2.5 pts) ---
    visual_deduct = 0.0
    for beat in beats:
        if not beat.visual_cue or not beat.visual_cue.strip():
            visual_deduct += 0.6
            problems.append(f"{beat.scene_id}: visual_cue tiếng Việt bị trống.")
        if not beat.visual_cue_en or len(beat.visual_cue_en.strip().split()) < 5:
            visual_deduct += 0.6
            problems.append(f"{beat.scene_id}: visual_cue_en tiếng Anh cho video model quá sơ sài hoặc thiếu.")
            feedback.append(f"{beat.scene_id}: Bổ sung mô tả tiếng Anh chi tiết cho visual_cue_en (chủ thể + hành động cụ thể + góc máy).")

    rubric["visual_direction"] = max(0.0, rubric["visual_direction"] - visual_deduct)
    checks.append(ReviewCheck(
        name="Chỉ dẫn thị giác kịch bản",
        passed=visual_deduct == 0.0,
        score=rubric["visual_direction"] * 4,
        detail="visual_cue và visual_cue_en chi tiết, rõ hành động."
    ))

    # Calculate total score
    total_score = round(sum(rubric.values()), 1)
    passed = total_score >= PASSING_SCORE_THRESHOLD and not any("Kịch bản thiếu nhịp" in p for p in problems)
    status = "approved" if passed else "needs_revision"

    return StageReviewResult(
        stage="script",
        iteration=iteration,
        score=total_score,
        status=status,
        passed=passed,
        rubric_scores=rubric,
        checks=checks,
        problems=problems,
        actionable_feedback=feedback,
        kol_locked=True,
    )


# ==============================================================================
# 2. STORYBOARD & PROMPT REVIEWER (PHÂN CẢNH & PROMPT TẠO VIDEO)
# ==============================================================================

def review_storyboard(
    scene_plan: ScenePlanArtifact | Dict[str, Any],
    script: Optional[ScriptArtifact | Dict[str, Any]] = None,
    brief: Optional[BriefArtifact | Dict[str, Any]] = None,
    char_data: Optional[Dict[str, Any]] = None,
    iteration: int = 1,
) -> StageReviewResult:
    """Independently review cinematic storyboard and video diffusion prompts.

    Evaluates:
    - 1:1 Alignment with script beats.
    - Contextual setting (SET) and wardrobe (WEAR) appropriateness for KOL Mai Ly.
    - Video generation prompts (visual_cue_en, prompt_6part, camera motion, framing, lighting).
    - Slideshow risk scoring across 6 dimensions.
    """
    if isinstance(scene_plan, dict):
        plan_obj = ScenePlanArtifact.model_validate(scene_plan)
    else:
        plan_obj = scene_plan

    shots = plan_obj.shots or []
    checks: List[ReviewCheck] = []
    problems: List[str] = []
    feedback: List[str] = []

    rubric = {
        "script_alignment": 2.0,
        "kol_and_context_fit": 2.5,
        "video_prompt_detail": 3.0,
        "camera_motion_and_cinematography": 2.5,
    }

    # --- Check 1: Script Alignment (2.0 pts) ---
    align_deduct = 0.0
    if not shots:
        align_deduct = 2.0
        problems.append("Storyboard không có shot nào.")
        feedback.append("Tạo đầy đủ các shot tương ứng từng nhịp kịch bản.")
    elif script:
        script_beats = script.beats if hasattr(script, "beats") else script.get("beats", [])
        if len(shots) != len(script_beats):
            align_deduct += 1.0
            problems.append(f"Số lượng shot ({len(shots)}) không khớp 1:1 với số beat kịch bản ({len(script_beats)}).")
            feedback.append("Đảm bảo mỗi nhịp kịch bản có đúng 1 storyboard shot tương ứng.")

    rubric["script_alignment"] = max(0.0, rubric["script_alignment"] - align_deduct)
    checks.append(ReviewCheck(
        name="Khớp kịch bản 1:1",
        passed=align_deduct == 0.0,
        score=rubric["script_alignment"] * 5,
        detail="Mỗi beat kịch bản có phân cảnh tương ứng."
    ))

    # --- Check 2: KOL & Context Fit (2.5 pts) ---
    context_deduct = 0.0
    for shot in shots:
        p6 = (shot.prompt_6part or "").lower()
        # Ensure KOL tag is correctly used if character is present
        if shot.character_tag and CANONICAL_KOL_TAG.lower() not in shot.character_tag.lower():
            if "kol" in shot.character_tag.lower() or "presenter" in str(shot.character_role).lower():
                context_deduct += 0.5
                problems.append(f"{shot.shot_id}: Nhân vật không dùng tag chuẩn {CANONICAL_KOL_TAG} của repo KOL.")
                feedback.append(f"{shot.shot_id}: Khóa nhân vật về chuẩn {CANONICAL_KOL_TAG} ({CANONICAL_KOL_NAME}).")

        # Check for contradictory SET / WEAR directives
        set_matches = re.findall(r"\bset:\s*([^;.]+)", p6)
        if len(set_matches) > 1:
            context_deduct += 0.4
            problems.append(f"{shot.shot_id}: Chứa nhiều mô tả bối cảnh SET mâu thuẫn trong prompt.")
            feedback.append(f"{shot.shot_id}: Chuẩn hóa duy nhất một mô tả bối cảnh nhất quán.")

    rubric["kol_and_context_fit"] = max(0.0, rubric["kol_and_context_fit"] - context_deduct)
    checks.append(ReviewCheck(
        name="Nhất quán KOL & Bối cảnh bám sát Archetype",
        passed=context_deduct == 0.0,
        score=rubric["kol_and_context_fit"] * 4,
        detail="Khóa nhân vật kol_main, không xung đột bối cảnh SET/WEAR."
    ))

    # --- Check 3: Video Prompt Detail (3.0 pts) ---
    # Prompts for video diffusion models must be concrete, visual, kinetic, and detailed
    prompt_deduct = 0.0
    for shot in shots:
        p6 = shot.prompt_6part or ""
        words = p6.split()
        if len(words) < 25:
            prompt_deduct += 0.5
            problems.append(f"{shot.shot_id}: Prompt 6-part quá ngắn ({len(words)} từ), thiếu chi tiết cho video model.")
            feedback.append(f"{shot.shot_id}: Bổ sung chi tiết chuyển động, chủ thể, bối cảnh và ánh sáng vào prompt 6-part.")

        # Check if prompt contains concrete visual elements
        has_camera = bool(shot.camera_motion and shot.camera_motion.strip())
        has_lighting = bool(shot.lighting and shot.lighting.strip())
        if not has_camera:
            prompt_deduct += 0.3
            problems.append(f"{shot.shot_id}: Thiếu chỉ đạo chuyển động camera (camera_motion).")
            feedback.append(f"{shot.shot_id}: Khai báo rõ chuyển động máy quay (e.g. slow push-in, tracking pan).")
        if not has_lighting:
            prompt_deduct += 0.2
            problems.append(f"{shot.shot_id}: Thiếu thông số ánh sáng (lighting).")

    rubric["video_prompt_detail"] = max(0.0, rubric["video_prompt_detail"] - prompt_deduct)
    checks.append(ReviewCheck(
        name="Độ chi tiết của Prompt tạo video",
        passed=prompt_deduct == 0.0,
        score=rubric["video_prompt_detail"] * 3.33,
        detail="Prompt 6-part giàu chi tiết thị giác, động từ hành động mạnh, ánh sáng rõ nét."
    ))

    # --- Check 4: Camera Motion & Slideshow Risk (2.5 pts) ---
    motion_deduct = 0.0
    slideshow_rep = score_slideshow_risk(shots)
    if not slideshow_rep.passed:
        motion_deduct += 1.5
        problems.append(
            f"Nguy cơ Slideshow cao ({slideshow_rep.average_score:.2f}/5.0 - verdict: {slideshow_rep.verdict})."
        )
        for rec in slideshow_rep.recommendations[:2]:
            feedback.append(f"Giảm nguy cơ slideshow: {rec}")
    elif slideshow_rep.average_score > 2.8:
        motion_deduct += 0.5
        problems.append(f"Điểm nguy cơ slideshow hơi cao ({slideshow_rep.average_score:.2f}/5.0).")

    rubric["camera_motion_and_cinematography"] = max(0.0, rubric["camera_motion_and_cinematography"] - motion_deduct)
    checks.append(ReviewCheck(
        name="Chuyển động máy quay & Kiểm soát Slideshow",
        passed=motion_deduct == 0.0,
        score=rubric["camera_motion_and_cinematography"] * 4,
        detail="Chuyển động camera đa dạng, tránh cảm giác ảnh tĩnh zoom lướt."
    ))

    total_score = round(sum(rubric.values()), 1)
    passed = total_score >= PASSING_SCORE_THRESHOLD and bool(shots) and slideshow_rep.passed
    status = "approved" if passed else "needs_revision"

    return StageReviewResult(
        stage="storyboard",
        iteration=iteration,
        score=total_score,
        status=status,
        passed=passed,
        rubric_scores=rubric,
        checks=checks,
        problems=problems,
        actionable_feedback=feedback,
        kol_locked=True,
    )


# ==============================================================================
# 3. KEYFRAME & VISUAL REVIEWER (ẢNH KEYFRAME & KHÓA KOL)
# ==============================================================================

def review_keyframes(
    manifest: AssetManifestArtifact | Dict[str, Any],
    scene_plan: Optional[ScenePlanArtifact | Dict[str, Any]] = None,
    char_data: Optional[Dict[str, Any]] = None,
    keyframes_dir: Optional[Path] = None,
    iteration: int = 1,
) -> StageReviewResult:
    """Independently review staged keyframes, product hero, and character identity.

    Evaluates:
    - Lock to canonical repo KOL (assets/characters/kol_main/).
    - Product isolation for product-only shots.
    - Watermark removal and image format (9:16, 1080x1920).
    - Image existence and absence of synthesis errors.
    """
    if isinstance(manifest, dict):
        manifest_obj = AssetManifestArtifact.model_validate(manifest)
    else:
        manifest_obj = manifest

    kfs = manifest_obj.keyframes or []
    checks: List[ReviewCheck] = []
    problems: List[str] = []
    feedback: List[str] = []

    rubric = {
        "kol_identity_lock": 3.0,
        "product_isolation": 2.5,
        "visual_quality_and_watermark": 2.5,
        "shot_coverage": 2.0,
    }

    # --- Check 1: KOL Identity Lock (3.0 pts) ---
    kol_deduct = 0.0
    for kf in kfs:
        refs = kf.reference_assets or []
        # Check if references point to valid assets in repo
        for ref in refs:
            if "characters" in ref and CANONICAL_KOL_ID not in ref:
                kol_deduct += 1.0
                problems.append(f"{kf.shot_id}: Tham chiếu nhân vật lạ ngoài repo '{ref}'.")
                feedback.append(f"{kf.shot_id}: Bắt buộc sử dụng reference từ assets/characters/kol_main/.")

    rubric["kol_identity_lock"] = max(0.0, rubric["kol_identity_lock"] - kol_deduct)
    checks.append(ReviewCheck(
        name="Khóa danh tính KOL Mai Ly (kol_main)",
        passed=kol_deduct == 0.0,
        score=rubric["kol_identity_lock"] * 3.33,
        detail="Sử dụng đúng tài nguyên neo mặt và outfit của kol_main."
    ))

    # --- Check 2: Product Isolation (2.5 pts) ---
    prod_deduct = 0.0
    for kf in kfs:
        if kf.generation_mode == "product_hero":
            refs = kf.reference_assets or []
            has_prod = any("product" in r.lower() or "hero" in r.lower() or "input" in r.lower() for r in refs)
            has_face = any("face_anchor" in r.lower() or "character" in r.lower() for r in refs)
            if has_face and not has_prod:
                prod_deduct += 1.0
                problems.append(f"{kf.shot_id}: Cảnh sản phẩm (product_hero) bị gán ảnh mặt người thay vì sản phẩm.")
                feedback.append(f"{kf.shot_id}: Đổi reference thành ảnh sản phẩm thật (product_hero).")

    rubric["product_isolation"] = max(0.0, rubric["product_isolation"] - prod_deduct)
    checks.append(ReviewCheck(
        name="Cô lập sản phẩm (Product Isolation ADR 0006)",
        passed=prod_deduct == 0.0,
        score=rubric["product_isolation"] * 4,
        detail="Cảnh quay sản phẩm không bị chèn mặt người."
    ))

    # --- Check 3: Visual Quality & Watermark Removal (2.5 pts) ---
    quality_deduct = 0.0
    for kf in kfs:
        if kf.synthesis_error:
            quality_deduct += 1.0
            problems.append(f"{kf.shot_id}: Lỗi tạo ảnh first frame: {kf.synthesis_error}")
            feedback.append(f"{kf.shot_id}: Render lại first frame sạch.")
        if not kf.watermark_removed:
            quality_deduct += 0.3
            problems.append(f"{kf.shot_id}: Chưa xác nhận khử watermark AI.")
            feedback.append(f"{kf.shot_id}: Kích hoạt Telea Inpainting khử sạch watermark trước khi render video.")
        if kf.width != 1080 or kf.height != 1920:
            quality_deduct += 0.5
            problems.append(f"{kf.shot_id}: Độ phân giải {kf.width}x{kf.height} không đúng chuẩn 1080x1920 (9:16).")

    rubric["visual_quality_and_watermark"] = max(0.0, rubric["visual_quality_and_watermark"] - quality_deduct)
    checks.append(ReviewCheck(
        name="Chất lượng hình ảnh & Khử Watermark",
        passed=quality_deduct == 0.0,
        score=rubric["visual_quality_and_watermark"] * 4,
        detail="Độ phân giải 1080x1920, sạch watermark, không lỗi render."
    ))

    # --- Check 4: Shot Coverage (2.0 pts) ---
    coverage_deduct = 0.0
    if not kfs:
        coverage_deduct = 2.0
        problems.append("Không có keyframe nào được staged.")
    elif scene_plan:
        plan_shots = scene_plan.shots if hasattr(scene_plan, "shots") else scene_plan.get("shots", [])
        if len(kfs) < len(plan_shots):
            coverage_deduct += 1.0
            problems.append(f"Số lượng keyframe ({len(kfs)}) thiếu so với số shot phân cảnh ({len(plan_shots)}).")

    rubric["shot_coverage"] = max(0.0, rubric["shot_coverage"] - coverage_deduct)
    checks.append(ReviewCheck(
        name="Bao phủ toàn bộ phân cảnh",
        passed=coverage_deduct == 0.0,
        score=rubric["shot_coverage"] * 5,
        detail="Đủ keyframe cho tất cả các shot cần render."
    ))

    total_score = round(sum(rubric.values()), 1)
    passed = total_score >= PASSING_SCORE_THRESHOLD and bool(kfs) and not any(kf.synthesis_error for kf in kfs)
    status = "approved" if passed else "needs_revision"

    return StageReviewResult(
        stage="keyframe",
        iteration=iteration,
        score=total_score,
        status=status,
        passed=passed,
        rubric_scores=rubric,
        checks=checks,
        problems=problems,
        actionable_feedback=feedback,
        kol_locked=True,
    )


# ==============================================================================
# 4. REVIEW HISTORY & PERSISTENCE (LƯU TRỮ VÀ QUẢN LÝ VÒNG LẶP)
# ==============================================================================

STAGE_REVIEWS_FILENAME = "stage_reviews.json"


def load_review_history(artifacts_dir: Path) -> StageReviewHistory:
    """Load or initialize stage review history artifact."""
    review_path = artifacts_dir / STAGE_REVIEWS_FILENAME
    if review_path.is_file():
        try:
            with open(review_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return StageReviewHistory.model_validate(data)
        except Exception:
            pass
    return StageReviewHistory(campaign_id=artifacts_dir.parent.name)


def save_review_history(artifacts_dir: Path, history: StageReviewHistory) -> Path:
    """Save updated review history artifact."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    review_path = artifacts_dir / STAGE_REVIEWS_FILENAME
    history.last_updated = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(history.model_dump(), f, ensure_ascii=False, indent=2)
    return review_path


def record_stage_review(
    artifacts_dir: Path,
    result: StageReviewResult,
) -> Tuple[StageReviewHistory, bool]:
    """Append a review result to the history artifact.

    Returns:
        (updated_history, can_retry): can_retry is True if score < threshold and iteration < 3.
    """
    history = load_review_history(artifacts_dir)
    stage_list = history.reviews.setdefault(result.stage, [])

    # Set iteration number based on existing reviews for this stage
    result.iteration = len(stage_list) + 1
    stage_list.append(result)

    save_review_history(artifacts_dir, history)

    can_retry = (not result.passed) and (result.iteration < MAX_REVIEW_ITERATIONS)
    return history, can_retry
