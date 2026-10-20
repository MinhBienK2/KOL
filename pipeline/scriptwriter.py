"""Step 2: High-Conversion Commercial Scriptwriting."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from pipeline import telemetry
from pipeline.config import ARTIFACTS_DIR
from pipeline.offline import is_offline
from pipeline.schemas import BriefArtifact, ScriptArtifact, ScriptBeat
from pipeline.workspace import ProjectWorkspace
from pipeline.cinematography import camera_phrase
from pipeline.archetypes import (
    AudioStrategy,
    CameraChoreography,
    CharacterRole,
    LightingContract,
    ProductArchetype,
    get_archetype_config,
)

STAGE_SCRIPTWRITING = telemetry.stage_number("scriptwriting")

LEGACY_MUG_CAMPAIGN_ID = "campaign_lumina_mug_01"
LEGACY_MUG_SCENE_IDS = ["shot_01_hook", "shot_02_pain", "shot_03_solution", "shot_04_cta"]

# ProductIntel.source values meaning the research numbers were synthesized rather than
# scraped/supplied, so they must not be advertised as real offers.
_UNTRUSTED_SOURCES = ("fallback", "heuristic", "synthetic", "mock", "template", "default", "unknown", "guess")

# Short English camera labels for visual_cue_en. Deliberately not bare enum words ("orbit", "pan",
# "tilt", "truck") so prompt humanisation never rewrites them.
_CAMERA_LABEL_EN = {
    "orbit": "orbiting",
    "truck": "tracking",
    "pedestal": "rising",
    "pan": "panning",
    "tilt": "tilting",
    "zoom_in": "push-in",
    "drone_flythrough": "fly-through",
    "dutch_angle": "dutch-angle",
    "macro_push_in": "macro push-in",
    "top_down_flat_lay": "top-down",
}

# A short fade leads into the CTA; every other beat is a hard cut. Types come from
# pipeline.composer.SUPPORTED_TRANSITIONS.
_CTA_TRANSITION = {"type": "fade", "duration": 0.4}
_CUT_TRANSITION = {"type": "cut", "duration": 0.0}

# --- Timing contract -----------------------------------------------------------
# Hailuo-2.3 renders 6s or 10s clips (see video_engine); a 6s beat is the cheapest
# clip and the TikTok/Reels sweet spot for one idea per shot, so beats are capped there.
MAX_BEAT_SECONDS = 6.0
MIN_BEAT_SECONDS = 1.5
# Hook must land inside the scroll-decision window (~3s, tolerate 4s with lead-in).
MAX_HOOK_SECONDS = 4.0
# Short-form ads cluster at 15-30s; above ~35s drop-off dominates.
MAX_TOTAL_SECONDS = 35.0
# Conservative Vietnamese TTS pace (syllables per second) plus lead-in/out padding.
VI_SYLLABLES_PER_SECOND = 4.5
SPEECH_PADDING_SECONDS = 0.4
SPEECH_PAUSE_SECONDS = 0.15  # per clause/sentence punctuation mark


def estimate_speech_seconds(text: str) -> float:
    """Estimate how long a Vietnamese line takes to speak with neural TTS.

    Vietnamese words are single syllables, so whitespace tokens approximate syllables;
    long Latin brand tokens (CyberKey, GlowRevive) are counted as several syllables.
    Returns 0.0 for empty text.
    """
    if not text or not text.strip():
        return 0.0
    syllables = 0
    for token in text.split():
        letters = re.sub(r"[^\w]", "", token, flags=re.UNICODE)
        if not letters:
            continue
        syllables += 1
        if letters.isascii() and letters.isalpha() and len(letters) > 6:
            syllables += math.ceil(len(letters) / 3) - 1
    pauses = len(re.findall(r"[,.;:?!…]", text))
    return round(syllables / VI_SYLLABLES_PER_SECOND + pauses * SPEECH_PAUSE_SECONDS + SPEECH_PADDING_SECONDS, 2)


def _speaks(beat: ScriptBeat) -> bool:
    """True when the beat's spoken_text is actually voiced (not a music-only beat)."""
    return bool(beat.spoken_text and beat.spoken_text.strip()) and beat.audio_strategy != AudioStrategy.MUSIC_AND_SFX_ONLY


def fit_beat_durations_to_speech(beats: Iterable[ScriptBeat]) -> List[str]:
    """Stretch beat durations (never shrink) so each voiced line fits, capped at MAX_BEAT_SECONDS.

    The TTS stem is not time-compressed downstream, so a line longer than its clip is
    cut off or bleeds into the next shot. Durations round up to 0.5s steps. Returns
    warnings for lines that still cannot fit inside the cap (the copy must be shortened).
    """
    warnings: List[str] = []
    for beat in beats:
        if not _speaks(beat):
            continue
        need = estimate_speech_seconds(beat.spoken_text)
        if need <= beat.estimated_duration:
            continue
        target = math.ceil(need * 2) / 2
        beat.estimated_duration = min(MAX_BEAT_SECONDS, max(beat.estimated_duration, target))
        if need > MAX_BEAT_SECONDS:
            warnings.append(
                f"{beat.scene_id}: spoken line needs ~{need:.1f}s but a beat is capped at "
                f"{MAX_BEAT_SECONDS:.1f}s; shorten the copy"
            )
    return warnings


def validate_script(beats: List[ScriptBeat]) -> List[str]:
    """Check a beat list against short-form ad structure and video-model limits.

    Returns human-readable issues (empty list = valid). Use it on agent-authored beats.
    """
    issues: List[str] = []
    if not beats:
        return ["script has no beats"]
    if "hook" not in beats[0].beat_type.lower():
        issues.append(f"first beat must be a hook (got '{beats[0].beat_type}')")
    if "cta" not in beats[-1].beat_type.lower():
        issues.append(f"last beat must be a cta (got '{beats[-1].beat_type}')")
    seen: set[str] = set()
    for beat in beats:
        if beat.scene_id in seen:
            issues.append(f"duplicate scene_id '{beat.scene_id}'")
        seen.add(beat.scene_id)
        if not beat.visual_cue.strip():
            issues.append(f"{beat.scene_id}: empty visual_cue (the video model has nothing to render)")
        if beat.estimated_duration > MAX_BEAT_SECONDS:
            issues.append(
                f"{beat.scene_id}: duration {beat.estimated_duration:.1f}s exceeds the {MAX_BEAT_SECONDS:.1f}s "
                "single-clip limit; split it into two beats"
            )
        if beat.estimated_duration < MIN_BEAT_SECONDS:
            issues.append(f"{beat.scene_id}: duration {beat.estimated_duration:.1f}s is below {MIN_BEAT_SECONDS:.1f}s")
        if _speaks(beat):
            need = estimate_speech_seconds(beat.spoken_text)
            if need > beat.estimated_duration + 1e-6:
                issues.append(
                    f"{beat.scene_id}: spoken line needs ~{need:.1f}s but beat lasts {beat.estimated_duration:.1f}s"
                )
    hook = beats[0]
    if "hook" in hook.beat_type.lower() and hook.estimated_duration > MAX_HOOK_SECONDS:
        issues.append(
            f"hook lasts {hook.estimated_duration:.1f}s; keep it within {MAX_HOOK_SECONDS:.1f} seconds "
            "so it lands before the scroll decision"
        )
    total = sum(b.estimated_duration for b in beats)
    if total > MAX_TOTAL_SECONDS:
        issues.append(f"total runtime {total:.1f}s exceeds the {MAX_TOTAL_SECONDS:.0f}s short-form ceiling")
    return issues


# ==============================================================================
# No-fabrication lint (shared by LLM-drafted and agent-authored scripts)
# ==============================================================================

# Offer / statistic / social-proof / guarantee wording. Each phrase is a claim the advertiser must
# have supplied (brief) or research must contain; otherwise it is fabricated.
BANNED_CLAIM_PHRASES = (
    "ưu đãi", "giảm giá", "khuyến mãi", "voucher", "mua 1 tặng 1", "quà tặng", "miễn phí", "freeship",
    "flash sale", "hàng ngàn", "hàng nghìn", "100%", "đánh giá 5 sao", "5 sao", "bán chạy", "số 1",
    "số một", "top 1", "best seller", "bestseller", "lâm sàng", "chuyên gia", "bác sĩ", "da liễu",
    "kiểm chứng", "chứng nhận", "bảo hành", "hoàn tiền", "đổi trả", "chính hãng", "cam kết",
)
# Percent, price, multiplier, "N lần", thousands-separated numbers.
NUMERIC_CLAIM_RE = re.compile(
    r"\d+\s*%|\d[\d.,]*\s*(?:đ|vnd|k\b|nghìn|ngàn|triệu)|\bx\s*\d|\d+\s*lần|\d+[.,]\d{3}", re.IGNORECASE
)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _flatten_strings(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _flatten_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _flatten_strings(v)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield f"{value:g}"
    elif hasattr(value, "model_dump"):
        yield from _flatten_strings(value.model_dump())


def _numbers_in(text: str) -> set:
    """Digit runs normalised without thousands separators ("199.000" -> "199000", "4,5" -> "45")."""
    return {re.sub(r"[.,]", "", m) for m in _NUMBER_RE.findall(text)}


def load_research_context(artifacts_dir: Optional[Path]) -> Dict[str, Any]:
    """Research artifacts a script may legitimately draw facts from (untrusted pricing removed)."""
    context: Dict[str, Any] = {}
    if artifacts_dir is None:
        return context
    research = _load_json(artifacts_dir / "competitor_research.json")
    if research:
        research = dict(research)
        intel = dict(research.get("product_intel") or {})
        source = str(intel.get("source") or "").strip().lower()
        if source and any(tag in source for tag in _UNTRUSTED_SOURCES):
            intel.pop("pricing", None)
        research["product_intel"] = intel
        context["research"] = research
    concept = _load_json(artifacts_dir / "creative_concept.json")
    if concept:
        context["concept"] = concept
    return context


def find_unsupported_claims(
    script: Union[ScriptArtifact, Iterable[ScriptBeat]],
    brief: BriefArtifact,
    research: Any = None,
) -> List[str]:
    """Flag numbers, prices, discounts and proof/offer wording that neither brief nor research supply.

    ``script`` is a ScriptArtifact or an iterable of beats; ``research`` is anything containing the
    allowed source text (dict from :func:`load_research_context`, a list of strings, ...). Spoken and
    on-screen text may use no number that the sources do not contain; visual cues are checked for
    price/percent-style numbers. Returns human-readable issues (empty list = grounded).
    """
    beats = script.beats if isinstance(script, ScriptArtifact) else list(script)
    corpus = " \n ".join(
        _flatten_strings(
            [
                brief.product_name, brief.usps, brief.pain_points, brief.offers, brief.target_persona,
                brief.visual_tone, brief.category, research,
            ]
        )
    ).lower()
    allowed_numbers = _numbers_in(corpus)

    issues: List[str] = []
    for beat in beats:
        voiced = {"spoken_text": beat.spoken_text or "", "on_screen_text": beat.on_screen_text or ""}
        visual = {"visual_cue": beat.visual_cue or "", "visual_cue_en": beat.visual_cue_en or ""}
        for field_name, text in {**voiced, **visual}.items():
            low = text.lower()
            for phrase in BANNED_CLAIM_PHRASES:
                if phrase in low and phrase not in corpus:
                    issues.append(f"{beat.scene_id}.{field_name}: unsupported claim '{phrase}' (not in brief/research)")
            if field_name in voiced:
                unknown = sorted(n for n in _numbers_in(text) if n not in allowed_numbers)
            else:
                unknown = sorted(
                    n for m in NUMERIC_CLAIM_RE.findall(text) for n in _numbers_in(m) if n not in allowed_numbers
                )
            if unknown:
                issues.append(
                    f"{beat.scene_id}.{field_name}: number(s) {', '.join(unknown)} not found in brief/research"
                )
    return list(dict.fromkeys(issues))


# Diacritic-free Vietnamese product words that look like Latin brand tokens ("Tai nghe", "Ly", "Minh").
_VI_PLAIN_WORDS = frozenset({
    "tai", "ly", "minh", "nam", "nu", "kem", "sua", "tui", "ao", "do", "be", "bo", "cap", "sac", "den",
    "dan", "hoa", "mat", "gel", "set", "bot", "bluetooth", "wireless", "smart", "gaming", "mini",
})
_NAME_CUT = re.compile(r"\s[-–—|:]\s|\s*[|,;(]\s*|\s(?:với|dành cho|phức hợp|cho|có|kèm|và)\s")
_MAX_DISPLAY_WORDS = 5


def _is_latin_name_token(word: str) -> bool:
    core = word.strip("()[]{}.,;:!?\"'")
    if not core or not core.isascii() or core.lower() in _VI_PLAIN_WORDS:
        return False
    return core[0].isupper() or any(c.isdigit() for c in core)


def _is_acronym(word: str) -> bool:
    core = word.strip("()[]{}.,;:!?\"'")
    return core.isalpha() and core.isupper() and len(core) <= 4


def derive_display_name(product_name: str, max_words: int = _MAX_DISPLAY_WORDS) -> str:
    """Short spoken/display name for a catalog title: category + brand/model, never a description.

    "Tai nghe chống ồn Sonic Air Pro" -> "Tai nghe Sonic Air Pro";
    "Tai nghe bluetooth chống ồn chủ động ANC, pin 30 giờ" -> "Tai nghe bluetooth chống ồn".
    """
    name = " ".join((product_name or "").split())
    if not name:
        return name
    parts = _NAME_CUT.split(name, maxsplit=1)
    head = parts[0].strip()
    if len(head.split()) >= 2:
        name = head
    words = name.split()
    if len(words) <= max_words:
        return name

    # Last run of Latin brand/model tokens (acronyms such as ANC/RGB may sit inside but not at the edges).
    run_end = None
    for i in range(len(words) - 1, -1, -1):
        if _is_latin_name_token(words[i]) and not _is_acronym(words[i]):
            run_end = i
            break
    if run_end is None:
        return " ".join(words[:max_words])
    run_start = run_end
    while run_start > 0 and _is_latin_name_token(words[run_start - 1]) and run_end - run_start < 2:
        run_start -= 1
    while run_start < run_end and _is_acronym(words[run_start]):
        run_start += 1
    brand = words[run_start : run_end + 1]
    head_words = words[:run_start][: min(3, max_words - len(brand))]
    return " ".join(head_words + brand)


def _clean_spoken_product_name(product: str) -> str:
    """Natural conversational name for voiceover (kept for backwards compatibility)."""
    return derive_display_name(product)


def _clean_caption(text: str, max_len: int = 38) -> str:
    """Clamps on-screen captions to punchy, mobile-safe length."""
    t = text.strip()
    if len(t) <= max_len:
        return t
    parts = t.split(" • ")
    if len(parts) >= 2:
        tag, desc = parts[0], parts[1]
        desc_words = desc.split()
        shortened = ""
        for w in desc_words:
            cand = f"{tag} • {shortened} {w}".strip() if shortened else f"{tag} • {w}"
            if len(cand) <= max_len:
                shortened = f"{shortened} {w}".strip()
            else:
                break
        if shortened:
            return f"{tag} • {shortened}"
        return tag[:max_len]
    return t[:max_len]


# ==============================================================================
# Research-derived inputs (winning concept, supplied offers)
# ==============================================================================

def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def _select_winning_option(cdata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Looks up the angle named by winning_concept.selected_angle_id (fallback: first option)."""
    options = cdata.get("concept_options") or []
    if not options:
        return None
    winning_id = (cdata.get("winning_concept") or {}).get("selected_angle_id")
    if winning_id:
        for opt in options:
            if isinstance(opt, dict) and opt.get("angle_id") == winning_id:
                return opt
    return options[0]


def _format_vnd(amount: float) -> str:
    return f"{int(round(amount)):,}".replace(",", ".") + "đ"


def _resolve_offer(brief: BriefArtifact, artifacts_dir: Optional[Path]) -> Optional[str]:
    """Returns offer copy ONLY if the brief or trusted research supplied one; else None."""
    for offer in getattr(brief, "offers", None) or []:
        if offer and offer.strip():
            return offer.strip()

    if artifacts_dir is None:
        return None
    research = _load_json(artifacts_dir / "competitor_research.json")
    if not research:
        return None
    intel = research.get("product_intel") or {}
    source = str(intel.get("source") or "").strip().lower()
    if source and any(tag in source for tag in _UNTRUSTED_SOURCES):
        return None
    pricing = intel.get("pricing") or {}
    pct = pricing.get("discount_percent")
    if not (isinstance(pct, (int, float)) and pct > 0):
        return None
    offer = f"Đang giảm {int(pct)}%"
    price = pricing.get("current_price") or 0
    currency = str(pricing.get("currency") or "VND")
    if price and price > 0:
        offer += f", chỉ còn {_format_vnd(price)}" if currency.upper() == "VND" else f", chỉ còn {price:g} {currency}"
    return offer


# ==============================================================================
# Beat copy templates (Vietnamese speech/captions, Vietnamese + English visuals)
# ==============================================================================

@dataclass
class _Ctx:
    product: str
    spoken_prod: str
    tag: str
    cam_vi: str
    cam_en: str
    usps: List[str] = field(default_factory=list)
    offer: Optional[str] = None
    concept_hook: Optional[str] = None
    concept_caption: Optional[str] = None
    concept_visual: Optional[str] = None

    @property
    def PU(self) -> str:
        return self.spoken_prod.upper()

    def usp_spoken(self, idx: int, fallback: str) -> str:
        """Spoken sentence derived from the brief's own USP text (never invented)."""
        if not self.usps:
            return fallback
        text = self.usps[idx % len(self.usps)].split(":")[0].strip().rstrip(".")
        words = text.split()
        if len(words) > 16:
            text = " ".join(words[:16])
        return text + "." if text else fallback

    def usp_caption(self, idx: int, fallback: str) -> str:
        if not self.usps:
            return fallback
        words = self.usps[idx % len(self.usps)].split(":")[0].split()[:4]
        return " ".join(words).upper() if words else fallback


def _cta_copy(ctx: _Ctx, neutral_spoken: str, neutral_caption: str) -> Tuple[str, str]:
    """CTA copy: advertises an offer only when one was supplied; otherwise neutral."""
    if ctx.offer:
        return (
            f"{ctx.offer}! Nhấp vào link bên dưới để sở hữu {ctx.spoken_prod} nhé!",
            f"{ctx.offer.upper()} • LINK BIO",
        )
    return neutral_spoken, neutral_caption


def _copy_fashion(bt: str, c: _Ctx) -> Tuple[str, str, str, str]:
    if bt == "hook":
        return (
            c.concept_hook or f"Item thời trang chân ái giúp bạn nâng tầm phong cách: {c.spoken_prod}.",
            c.concept_caption or f"MUST-HAVE • {c.PU}",
            c.concept_visual or f"Góc máy {c.cam_vi} từ thấp lên cao, {c.tag} bước sải chân tự tin với phong thái cuốn hút",
            f"Low-angle shot with {c.cam_en} camera, the model strides confidently toward the camera wearing the {c.product}",
        )
    if bt == "reveal":
        return (
            c.usp_spoken(0, "Phom dáng thanh lịch, tôn dáng và tạo điểm nhấn cho tổng thể trang phục."),
            "PERFECT FIT • FULL SILHOUETTE",
            f"Camera {c.cam_vi} quanh {c.tag}, khoe trọn phom dáng thanh lịch của {c.spoken_prod}",
            f"{c.cam_en.capitalize()} camera revealing the full silhouette of the {c.product} on the model, elegant poses",
        )
    if bt == "fabric_macro":
        return (
            c.usp_spoken(1, "Chất liệu mềm mại, từng đường may được chăm chút tỉ mỉ."),
            "FABRIC DETAIL • CLOSE-UP",
            f"Góc cận cảnh macro {c.cam_vi}, bắt trọn từng thớ vải mịn màng chuyển động mềm mại",
            f"Macro close-up with {c.cam_en} camera, capturing the fabric weave and stitching of the {c.product} swaying softly",
        )
    if bt == "movement_flow":
        return (
            "Từng bước chân chuyển động uyển chuyển, tôn lên tinh thần của cả bộ trang phục.",
            "FLUID MOVEMENT • STREET STYLE",
            f"Camera {c.cam_vi} bám song song khi {c.tag} rảo bước năng động",
            f"Tracking shot with {c.cam_en} camera as the model walks briskly, the garment flowing naturally with each step",
        )
    if bt == "styling_versatility":
        return (
            c.usp_spoken(2, "Dễ dàng phối cùng nhiều phụ kiện cho mọi dịp, từ dạo phố đến hẹn hò."),
            "EASY MIX & MATCH",
            f"Cắt nhanh {c.cam_vi} qua các cách phối đồ linh hoạt cùng phụ kiện",
            f"Quick-cut montage with {c.cam_en} camera showing the {c.product} styled with different accessories",
        )
    spoken, cap = _cta_copy(
        c,
        f"Khám phá {c.spoken_prod} ngay qua link giỏ hàng bên dưới nhé!",
        "XEM NGAY • LINK BIO",
    )
    return (
        spoken,
        cap,
        f"{c.tag} mỉm cười rạng rỡ, khung hình kết thúc với banner kêu gọi mua hàng xuất hiện",
        "The model smiles warmly at the camera, a clean call-to-action banner fades into the frame",
    )


def _copy_tech(bt: str, c: _Ctx) -> Tuple[str, str, str, str]:
    if bt == "hook":
        return (
            c.concept_hook or f"Bàn làm việc còn thiếu món đồ công nghệ xịn? Thử {c.spoken_prod}!",
            c.concept_caption or "NÂNG CẤP BÀN LÀM VIỆC",
            c.concept_visual or f"Camera {c.cam_vi} cận cảnh khuôn mặt {c.tag} đang tìm kiếm món đồ công nghệ phù hợp",
            f"Close-up with {c.cam_en} camera on the presenter's face, searching for the right piece of tech for the desk",
        )
    if bt == "unboxing":
        return (
            f"Mở hộp ngay em {c.spoken_prod} và cảm nhận trải nghiệm đầu tiên.",
            f"UNBOXING • {c.PU}",
            f"Góc quay {c.cam_vi}, bóc lớp seal mờ sang trọng, lộ diện thiết kế tinh xảo của {c.spoken_prod}",
            f"Overhead view, {c.cam_en} camera, peeling off the matte seal to reveal the refined design of the {c.product}",
        )
    if bt == "macro_detail":
        return (
            c.usp_spoken(0, "Từng chi tiết hoàn thiện được chăm chút kỹ lưỡng, cầm lên là thấy chất."),
            c.usp_caption(0, "PREMIUM BUILD • DETAIL"),
            f"Macro {c.cam_vi} chuyển nét mượt mà trên bề mặt vật liệu và các cổng kết nối",
            f"Macro shot with {c.cam_en} camera, focus gliding across the product's surface material and ports",
        )
    if bt == "performance_demo":
        return (
            c.usp_spoken(1, "Thao tác thực tế mượt mà, phản hồi nhanh ngay từ lần dùng đầu tiên."),
            c.usp_caption(1, "TRẢI NGHIỆM THỰC TẾ"),
            f"Camera {c.cam_vi} trình diễn thao tác thực tế trên màn hình, phản hồi tức thì",
            f"Hands-on demo with {c.cam_en} camera, fingers operating the product with smooth, immediate response on screen",
        )
    if bt == "specs_proof":
        return (
            c.usp_spoken(2, "Thiết kế gọn gàng, dễ mang theo mỗi ngày đi làm."),
            c.usp_caption(2, "GỌN GÀNG • DỄ MANG THEO"),
            f"Thao tác cất gọn {c.spoken_prod} vào balo thanh lịch, góc quay {c.cam_vi} nhanh gọn",
            f"Quick shot with {c.cam_en} camera of the {c.product} being tucked neatly into a stylish backpack",
        )
    spoken, cap = _cta_copy(
        c,
        f"Nâng cấp bàn làm việc của bạn cùng {c.spoken_prod} qua link bên dưới nhé!",
        "XEM CHI TIẾT • LINK GIỎ HÀNG",
    )
    return (
        spoken,
        cap,
        f"{c.tag} mỉm cười giơ cao {c.spoken_prod}, đồ họa CTA nổi bật xuất hiện",
        f"The presenter smiles and holds up the {c.product} toward the camera, a bold call-to-action graphic appears",
    )


def _copy_beauty(bt: str, c: _Ctx) -> Tuple[str, str, str, str]:
    if bt == "hook":
        return (
            c.concept_hook or "Chỉ một giọt tinh chất, thói quen chăm da đổi thay thế nào?",
            c.concept_caption or "GLOW SKIN ROUTINE",
            c.concept_visual or f"Góc cận cảnh macro {c.cam_vi}, giọt tinh chất {c.spoken_prod} óng ánh rơi từ ống nhỏ giọt thủy tinh",
            f"Macro close-up with {c.cam_en} camera, a glistening drop of serum falls from a glass dropper",
        )
    if bt == "skin_agitation":
        return (
            "Da xỉn màu, khô ráp và thiếu sức sống mỗi sáng thức dậy?",
            "DA THIẾU SỨC SỐNG?",
            f"Góc {c.cam_vi} cận mặt {c.tag} chạm nhẹ lên gò má bày tỏ nỗi lo",
            f"Close-up with {c.cam_en} camera, the model lightly touches her cheek with a worried expression about dull skin",
        )
    if bt == "texture_macro":
        return (
            c.usp_spoken(0, "Kết cấu mềm mịn, dễ tán đều trên da."),
            "VELVET TEXTURE • CLOSE-UP",
            f"Macro {c.cam_vi} swatch tinh chất sánh mịn trên phiến đá pha lê bắt sáng lấp lánh",
            f"Macro swatch with {c.cam_en} camera, silky product texture spreading across a crystal slab catching the light",
        )
    if bt == "application_method":
        return (
            c.usp_spoken(1, "Thoa nhẹ nhàng lên da, massage đều tay để da cảm nhận trọn vẹn."),
            c.usp_caption(1, "CÁCH SỬ DỤNG • NHẸ NHÀNG"),
            f"Góc nghiêng {c.cam_vi}, {c.tag} thoa tinh chất nhẹ nhàng lên gò má, tạo độ bóng căng mọng",
            f"Angled shot with {c.cam_en} camera, the model gently applies the product on her cheek leaving a dewy finish",
        )
    if bt == "transformation_proof":
        return (
            "Làn da được chăm sóc đều đặn mỗi ngày trông khỏe và rạng rỡ hơn.",
            "DAILY GLOW ROUTINE",
            f"Góc quay {c.cam_vi} bắt trọn ánh sáng tự nhiên trên làn da mịn màng, nụ cười rạng rỡ của {c.tag}",
            f"Shot with {c.cam_en} camera catching natural light on healthy glowing skin as the model smiles brightly",
        )
    spoken, cap = _cta_copy(
        c,
        f"Yêu thương làn da cùng {c.spoken_prod}, xem chi tiết tại link bio nhé!",
        "XEM CHI TIẾT • LINK BIO",
    )
    return (
        spoken,
        cap,
        f"Chai {c.spoken_prod} bên cạnh hoa cỏ thanh khiết, thông điệp kêu gọi xuất hiện nhẹ nhàng",
        "The product bottle sits beside fresh botanicals, a soft call-to-action message fades in",
    )


def _copy_home(bt: str, c: _Ctx) -> Tuple[str, str, str, str]:
    if bt == "hook":
        return (
            c.concept_hook or "Muốn không gian sống luôn ấm cúng, tinh tế và gọn gàng ngăn nắp?",
            c.concept_caption or "TỔ ẤM HIỆN ĐẠI",
            c.concept_visual or f"Góc quay lướt {c.cam_vi} trong căn phòng ngập tràn ánh nắng ấm áp buổi sáng",
            f"Gliding shot with {c.cam_en} camera through a room flooded with warm morning sunlight",
        )
    if bt == "reveal":
        return (
            f"Đây có thể là mảnh ghép hoàn hảo cho ngôi nhà bạn: {c.spoken_prod}.",
            f"{c.PU} • MINIMALIST",
            f"Camera {c.cam_vi} hạ thấp mượt mà, hé lộ vẻ đẹp tối giản của {c.spoken_prod} trên bàn gỗ sồi",
            f"{c.cam_en.capitalize()} camera slowly revealing the minimalist {c.product} on an oak wood table",
        )
    if bt == "functional_demo":
        return (
            c.usp_spoken(0, "Vận hành êm ái, đơn giản, phù hợp với nhịp sống mỗi ngày."),
            c.usp_caption(0, "DỄ DÙNG • TINH GỌN"),
            f"Cận cảnh {c.cam_vi} ngón tay chạm nhẹ vào sản phẩm, cơ chế hoạt động mượt mà",
            f"Close-up with {c.cam_en} camera, a finger lightly operates the {c.product}, smooth and calm",
        )
    if bt == "lifestyle_context":
        return (
            "Tận hưởng những giây phút thư thái sau một ngày dài bận rộn.",
            "COZY LIVING",
            f"Toàn cảnh {c.cam_vi}, {c.tag} ngồi thư giãn trên ghế sofa, không gian ấm cúng bình yên",
            f"Wide lifestyle shot with {c.cam_en} camera, the model relaxes on a cozy sofa in a warm, peaceful living room",
        )
    if bt == "convenience_proof":
        return (
            c.usp_spoken(1, "Dễ dàng vệ sinh và cất gọn gàng trong không gian nhà bạn."),
            c.usp_caption(1, "GỌN GÀNG • DỄ VỆ SINH"),
            f"Thao tác lau chùi nhẹ nhàng {c.cam_vi}, thiết kế thông minh gọn gàng",
            f"Gentle cleaning action with {c.cam_en} camera, showing the tidy practical design of the {c.product}",
        )
    spoken, cap = _cta_copy(
        c,
        f"Nâng tầm không gian sống cùng {c.spoken_prod}, xem chi tiết ở link bên dưới nhé!",
        "XEM CHI TIẾT • LINK ĐẶT HÀNG",
    )
    return (
        spoken,
        cap,
        f"{c.tag} nở nụ cười ấm áp, khung cảnh ngập tràn ánh hoàng hôn và thông điệp CTA",
        "The model smiles warmly in a sunset-lit living room, a soft call-to-action message appears",
    )


def _copy_general(bt: str, c: _Ctx) -> Tuple[str, str, str, str]:
    if bt == "hook":
        return (
            c.concept_hook or "Tìm kiếm giải pháp hoàn hảo cho công việc và đời sống hàng ngày?",
            c.concept_caption or "BẠN ĐANG TÌM GIẢI PHÁP NÀY?",
            c.concept_visual or f"Camera {c.cam_vi} cận cảnh biểu cảm băn khoăn của {c.tag}",
            f"Close-up with {c.cam_en} camera on the presenter's puzzled, searching expression",
        )
    if bt == "pain_agitation":
        return (
            "Những rắc rối bất tiện khiến bạn mất nhiều thời gian và công sức?",
            "RẮC RỐI MỖI NGÀY?",
            f"Góc cận {c.cam_vi} nhấn mạnh vào rắc rối thực tế thường gặp",
            f"Tight shot with {c.cam_en} camera emphasizing an everyday annoyance the product solves",
        )
    if bt == "solution_reveal":
        return (
            f"Và đây là giải pháp dành cho bạn: {c.spoken_prod}!",
            f"GIẢI PHÁP • {c.PU}",
            f"Ánh sáng quét qua sản phẩm {c.cam_vi}, xuất hiện sang trọng đầy ấn tượng",
            f"Light sweeps across the {c.product} with {c.cam_en} camera, a polished hero reveal",
        )
    if bt == "feature_demo":
        return (
            c.usp_spoken(0, "Thiết kế thông minh, thao tác đơn giản ngay từ lần đầu trải nghiệm."),
            c.usp_caption(0, "THIẾT KẾ THÔNG MINH"),
            f"Trình diễn tính năng chi tiết {c.cam_vi}, thao tác mượt mà chính xác",
            f"Feature demonstration with {c.cam_en} camera, smooth and precise hands-on use of the {c.product}",
        )
    if bt == "social_proof":
        return (
            c.usp_spoken(1, f"Một trải nghiệm đáng để thử, hãy xem điều gì khiến {c.spoken_prod} khác biệt."),
            "TRẢI NGHIỆM THỰC TẾ",
            f"{c.tag} mỉm cười hài lòng khi dùng sản phẩm, {c.cam_vi}",
            f"The presenter smiles with satisfaction while using the product, {c.cam_en} camera",
        )
    spoken, cap = _cta_copy(
        c,
        "Nhấp vào link bên dưới để xem chi tiết sản phẩm nhé!",
        "XEM CHI TIẾT • LINK BIO",
    )
    return (
        spoken,
        cap,
        f"{c.tag} giơ cao {c.spoken_prod} rạng rỡ, banner kêu gọi hành động xuất hiện",
        f"The presenter holds the {c.product} up to the camera with a bright smile, a call-to-action banner appears",
    )


_COPY_BY_ARCHETYPE = {
    ProductArchetype.FASHION_APPAREL: _copy_fashion,
    ProductArchetype.TECH_GADGETS: _copy_tech,
    ProductArchetype.BEAUTY_SKINCARE: _copy_beauty,
    ProductArchetype.HOME_LIFESTYLE: _copy_home,
    ProductArchetype.GENERAL_COMMERCIAL: _copy_general,
}


def _transition_for(beat_type: str, index: int) -> Optional[Dict[str, Any]]:
    """First beat has no inbound transition; a short fade leads into the CTA; otherwise hard cut."""
    if index == 0:
        return None
    if beat_type == "cta":
        return dict(_CTA_TRANSITION)
    return dict(_CUT_TRANSITION)


def _build_archetype_beats(
    brief: BriefArtifact,
    archetype: ProductArchetype,
    artifacts_dir: Optional[Path] = None,
) -> List[ScriptBeat]:
    """Build structured commercial beats based on product archetype and brief specs."""
    config = get_archetype_config(archetype)
    product = brief.product_name
    character_tag = brief.presenter.character_tag if brief.presenter else "[KOL]"

    concept_hook = None
    concept_caption = None
    concept_visual = None
    if artifacts_dir is not None:
        cdata = _load_json(artifacts_dir / "creative_concept.json")
        winning = _select_winning_option(cdata) if cdata else None
        if winning:
            hstrat = winning.get("hook_strategy") or {}
            concept_hook = hstrat.get("spoken_hook")
            concept_caption = hstrat.get("on_screen_text")
            concept_visual = hstrat.get("visual_hook")

    offer = _resolve_offer(brief, artifacts_dir)
    copy_fn = _COPY_BY_ARCHETYPE.get(archetype, _copy_general)

    beats: List[ScriptBeat] = []
    for idx, tpl in enumerate(config.beat_templates, start=1):
        scene_id = f"shot_{idx:02d}_{tpl.beat_type}"
        display_name = derive_display_name(product)
        ctx = _Ctx(
            product=display_name,
            spoken_prod=display_name,
            tag=character_tag,
            cam_vi=camera_phrase(tpl.camera_choreography),
            cam_en=_CAMERA_LABEL_EN.get(tpl.camera_choreography.value, "smooth"),
            usps=list(brief.usps or []),
            offer=offer,
            concept_hook=concept_hook,
            concept_caption=concept_caption,
            concept_visual=concept_visual,
        )
        spoken, on_screen, visual, visual_en = copy_fn(tpl.beat_type, ctx)

        beats.append(
            ScriptBeat(
                scene_id=scene_id,
                beat_type=tpl.beat_type,
                spoken_text=spoken,
                on_screen_text=_clean_caption(on_screen),
                visual_cue=visual,
                visual_cue_en=visual_en,
                estimated_duration=tpl.target_duration,
                archetype=archetype,
                character_role=tpl.recommended_role,
                audio_strategy=tpl.audio_strategy,
                camera_choreography=tpl.camera_choreography,
                lighting_contract=tpl.lighting_contract,
                narrative_purpose=tpl.narrative_purpose,
                transition=_transition_for(tpl.beat_type, idx - 1),
            )
        )

    return beats


def _build_legacy_mug_beats(brief: BriefArtifact) -> List[ScriptBeat]:
    """Legacy Lumina mug demo: 4 beats, each at most 6s (the old 12s solution beat exceeded Hailuo's 10s limit)."""
    common = dict(archetype=ProductArchetype.GENERAL_COMMERCIAL, lighting_contract=LightingContract.STUDIO_3POINT)
    return [
        ScriptBeat(
            scene_id="shot_01_hook",
            beat_type="hook",
            spoken_text="Ly cà phê vừa pha xong, 15 phút sau đã nguội ngắt?",
            on_screen_text="CÀ PHÊ NGUỘI NGẮT SAU 15 PHÚT?",
            visual_cue="Extreme close-up ly cà phê nguội, chuyển nhanh sang góc cận KOL Minh Anh lắc đầu ngạc nhiên",
            visual_cue_en="Extreme close-up of a cold cup of coffee, quick cut to a close-up of the presenter shaking her head in surprise",
            estimated_duration=3.5,
            character_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.ZOOM_IN,
            narrative_purpose="Pattern interrupt hook questioning mundane annoyance",
            transition=None,
            **common,
        ),
        ScriptBeat(
            scene_id="shot_02_pain",
            beat_type="pain",
            spoken_text="Chưa kể đá tan chảy nước lênh láng, làm ướt đẫm tài liệu và bàn phím làm việc?",
            on_screen_text="NƯỚC ĐỌNG ƯỚT BÀN & TÀI LIỆU!",
            visual_cue="Góc nhìn bàn làm việc nước ngưng tụ lem nhem hồ sơ, Minh Anh cau mày khó chịu",
            visual_cue_en="Top view of a work desk where condensation drips onto paper reports, the model frowns in annoyance",
            estimated_duration=5.0,
            character_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.ZOOM_IN,
            narrative_purpose="Visceral pain agitation of messy workspace",
            transition=dict(_CUT_TRANSITION),
            **common,
        ),
        ScriptBeat(
            scene_id="shot_03_solution",
            beat_type="solution",
            spoken_text="Giải pháp đây rồi! Ly Lumina Pro, chạm nhẹ nắp LED là biết ngay nhiệt độ!",
            on_screen_text="LUMINA PRO • NẮP CẢM ỨNG LED",
            visual_cue="Góc quay điện ảnh studio sang trọng, Minh Anh chạm nắp LED sáng đèn, nâng ly thưởng thức sảng khoái",
            visual_cue_en="Luxurious cinematic studio shot, the presenter taps the glowing LED lid and lifts the mug with a refreshed smile",
            estimated_duration=6.0,
            character_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.PEDESTAL,
            narrative_purpose="Hero solution reveal of the smart lid",
            transition=dict(_CUT_TRANSITION),
            **common,
        ),
        ScriptBeat(
            scene_id="shot_04_cta",
            beat_type="cta",
            spoken_text="Bảo bối công sở chống tràn tuyệt đối! Nhấp vào link bên dưới để xem chi tiết nhé!",
            on_screen_text="XEM CHI TIẾT • NHẤP LINK BIO",
            visual_cue="Minh Anh mỉm cười rạng rỡ, giơ cao ly Lumina Pro thanh lịch, logo thương hiệu và nút CTA xuất hiện",
            visual_cue_en="The presenter smiles brightly and holds up the elegant Lumina Pro mug, brand logo and a call-to-action button appear",
            estimated_duration=5.0,
            character_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.ZOOM_IN,
            narrative_purpose="Direct high-trust presenter CTA",
            transition=dict(_CTA_TRANSITION),
            **common,
        ),
    ]


def generate_commercial_script(
    brief: BriefArtifact | None = None,
    brief_path: Path | None = None,
    output_dir: Path | None = None,
    archetype: ProductArchetype | str | None = None,
    workspace: Optional[ProjectWorkspace] = None,
    beats: Optional[List[Union[ScriptBeat, dict]]] = None,
    strict: bool = True,
    use_llm: bool = True,
) -> ScriptArtifact:
    """Generates high-conversion TVC script based on brief.json and directorial archetype.

    An orchestrating agent can direct the script itself by passing ``beats`` (ScriptBeat
    objects or plain dicts). They replace the archetype templates, get their durations
    fitted to the spoken line, and are checked with :func:`validate_script`; with
    ``strict=True`` (default) any issue raises ``ValueError``, with ``strict=False`` the
    issues are only recorded in the run telemetry.

    Without ``beats``, and unless offline or ``use_llm=False``, the LLM drafts the script
    (:mod:`pipeline.script_llm`: validated, grounded, one repair retry); any failure falls back to the
    deterministic archetype templates.
    """
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (output_dir or ARTIFACTS_DIR)
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

    if archetype is None and workspace is not None and getattr(workspace, "topic", None):
        archetype = workspace.topic

    if brief is None:
        source_path = brief_path or (target_artifacts_dir / "brief.json")
        if not source_path.exists():
            raise FileNotFoundError(f"Brief file not found at {source_path}")
        with open(source_path, "r", encoding="utf-8") as f:
            brief = BriefArtifact.model_validate(json.load(f))

    # Resolve active archetype
    selected_archetype: ProductArchetype
    if archetype is not None:
        if isinstance(archetype, str):
            try:
                selected_archetype = ProductArchetype(archetype)
            except ValueError:
                selected_archetype = ProductArchetype.GENERAL_COMMERCIAL
        else:
            selected_archetype = archetype
    else:
        selected_archetype = brief.archetype or ProductArchetype.GENERAL_COMMERCIAL

    custom_beats: Optional[List[ScriptBeat]] = None
    if beats is not None:
        custom_beats = [b if isinstance(b, ScriptBeat) else ScriptBeat.model_validate(b) for b in beats]
        for cb in custom_beats:
            if cb.archetype is None:
                cb.archetype = selected_archetype

    generator = "deterministic_beat_templates"
    # If legacy mug campaign is tested without custom archetype override, maintain 4-beat legacy compatibility
    if custom_beats is not None:
        generator = "agent_authored_beats"
        beats = custom_beats  # type: ignore[assignment]
        script_warnings = fit_beat_durations_to_speech(custom_beats)
        script_warnings += validate_script(custom_beats)
        script_warnings = list(dict.fromkeys(script_warnings))
        if script_warnings and strict:
            raise ValueError("Invalid agent-authored script: " + "; ".join(script_warnings))
        if script_warnings:
            telemetry.note("Script validation warnings: " + "; ".join(script_warnings), warnings=script_warnings)
    elif brief.campaign_id == LEGACY_MUG_CAMPAIGN_ID and archetype is None and selected_archetype == ProductArchetype.GENERAL_COMMERCIAL:
        beats = _build_legacy_mug_beats(brief)
        fit_beat_durations_to_speech(beats)
    else:
        llm_beats: Optional[List[ScriptBeat]] = None
        if use_llm and not is_offline():
            from pipeline.script_llm import draft_script_with_llm  # lazy: script_llm imports this module

            llm_beats = draft_script_with_llm(brief, selected_archetype, target_artifacts_dir)
        if llm_beats:
            beats = llm_beats
            generator = "llm_script"
        else:
            beats = _build_archetype_beats(brief, selected_archetype, target_artifacts_dir)
        template_warnings = [] if generator == "llm_script" else fit_beat_durations_to_speech(beats)
        template_warnings += [i for i in validate_script(beats) if "spoken line needs" not in i]
        if template_warnings:
            telemetry.note(
                "Template script advisories: " + "; ".join(template_warnings),
                warnings=template_warnings,
            )

    total_duration = sum(b.estimated_duration for b in beats)

    for index, beat in enumerate(beats, start=1):
        telemetry.stage_progress(
            STAGE_SCRIPTWRITING,
            index,
            len(beats),
            unit="beats",
            label=f"Beat {index} {beat.beat_type}",
            item={
                "id": beat.scene_id,
                "status": "written",
                "beat_type": beat.beat_type,
                "duration_seconds": beat.estimated_duration,
                "has_speech": bool(beat.spoken_text and beat.spoken_text.strip()),
            },
        )
    if generator == "llm_script":
        summary = f"Script drafted by the LLM and validated: {len(beats)} {selected_archetype.value} beats"
    elif generator == "agent_authored_beats":
        summary = f"Script taken from {len(beats)} agent-authored {selected_archetype.value} beats"
    else:
        summary = (
            f"Script rendered deterministically from {len(beats)} {selected_archetype.value} beat templates "
            "(no LLM draft used)"
        )
    telemetry.note(
        f"{summary}, total {total_duration:.1f}s",
        archetype=selected_archetype.value,
        beats=len(beats),
        total_duration_seconds=round(total_duration, 2),
        generator=generator,
    )

    script = ScriptArtifact(
        campaign_id=brief.campaign_id,
        product_name=brief.product_name,
        target_duration=total_duration,
        beats=beats,
        archetype=selected_archetype,
    )

    out_file = target_artifacts_dir / "script.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(script.model_dump(), f, ensure_ascii=False, indent=2)

    return script
