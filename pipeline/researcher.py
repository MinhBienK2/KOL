"""Step 1 (Upgraded): Competitor & Viral Angle Research Engine.

Replaces the naive static briefing with an autonomous research engine that:
1. Ingests and unshortens any affiliate/product link (TikTok Shop, Shopee, Amazon, Shopify, or raw text).
2. Scrapes HTML, OpenGraph, JSON-LD microdata, or accepts raw product copy with anti-bot fallback.
3. Extracts structured Product Intelligence (title, specs, pricing, target persona, objection matrix, sensory anchors).
4. Discovers competitor angles & synthesizes top-performing TikTok/Reels/Shorts viral hooks across 3 proven archetypes:
   - Angle A: Shock / Pattern Interrupt / Contrarian
   - Angle B: Aesthetic / Sensory / ASMR Demonstration
   - Angle C: Direct Problem-Agitation / Value Tear-Down (Hard DR)
5. Delivers canonical CompetitorResearchArtifact and CreativeConceptArtifact with an objective winning angle selection.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from pipeline import telemetry
from pipeline.archetypes import (
    AudioStrategy,
    CharacterRole,
    ProductArchetype,
    classify_product_archetype,
    get_archetype_config,
)
from pipeline.workspace import ProjectWorkspace
from pipeline.config import ARTIFACTS_DIR
from pipeline import llm
from pipeline.offline import OfflineNetworkError, guard_network, guarded_urlopen, is_offline

STAGE_RESEARCH = telemetry.stage_number("research_briefing")
RESEARCH_PHASES = ("ingest_product_input", "product_intelligence", "competitor_hooks", "creative_concepts")


# ==============================================================================
# Research & Creative Concept Data Structures (Schemas)
# ==============================================================================

class ProductPricing(BaseModel):
    """Normalized pricing and price-anchoring metrics."""
    current_price: float = 0.0
    original_price: Optional[float] = None
    currency: str = "VND"
    discount_percent: Optional[int] = None
    price_tier: str = "mid-range"  # "budget", "mid-range", "premium", "luxury"


class ObjectionProof(BaseModel):
    """Customer purchase hesitation mapped to physical proof."""
    objection: str
    counter_evidence: str
    demonstration_technique: str


class ProductIntel(BaseModel):
    """Deep product intelligence extracted from affiliate URL or product text."""
    title: str
    brand: str = "Generic / OEM"
    category: str = "General"
    product_archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL
    pricing: ProductPricing = Field(default_factory=ProductPricing)
    features: List[str] = Field(default_factory=list)
    dramatic_benefits: List[str] = Field(default_factory=list)
    target_personas: List[str] = Field(default_factory=list)
    awareness_level: str = "Problem Aware"  # Unaware, Problem Aware, Solution Aware, Product Aware, Most Aware
    objection_matrix: List[ObjectionProof] = Field(default_factory=list)
    sensory_anchors: List[str] = Field(default_factory=list)
    # "llm" = model-extracted; "heuristic_fallback" = deterministic extraction from the raw input only
    # (generic placeholders where the input was silent; no invented prices or numeric proof).
    source: str = "llm"


class ViralHookCandidate(BaseModel):
    """A viral hook candidate scored for short-form retention."""
    hook_type: str  # "shock_interrupt", "contrarian_debunking", "sensory_asmr", "problem_agitation", "pov_story"
    spoken_line: str
    visual_action: str
    on_screen_text: str
    retention_mechanism: str
    projected_stop_ratio: float = 0.85  # Estimated 0-3s retention rate (0.0 - 1.0)


class CompetitorLandscape(BaseModel):
    """Analysis of rival products, saturated tropes, and market whitespace."""
    saturated_angles: List[str] = Field(default_factory=list)
    competitor_weaknesses: List[str] = Field(default_factory=list)
    whitespace_opportunities: List[str] = Field(default_factory=list)


class CompetitorResearchArtifact(BaseModel):
    """Canonical artifact storing complete competitor and product research."""
    campaign_id: str
    product_url: Optional[str] = None
    product_intel: ProductIntel
    competitor_landscape: CompetitorLandscape = Field(default_factory=CompetitorLandscape)
    viral_hook_library: List[ViralHookCandidate] = Field(default_factory=list)
    primary_persona: str = ""
    price_anchor_strategy: str = ""


class HookStrategy(BaseModel):
    """The 0-3 second audiovisual hook structure."""
    spoken_hook: str
    visual_hook: str
    on_screen_text: str
    retention_trigger: str


class DirectorialDirectives(BaseModel):
    """Downstream instructions for Director, Storyboarder, and Video Engine."""
    camera_pacing: str
    lighting_mood: str
    key_visual_anchor: str
    audio_mix_priority: str = "dialogue_first"


class CreativeAngle(BaseModel):
    """A complete commercial concept direction."""
    angle_id: str  # e.g., "angle_a_shock_interrupt", "angle_b_aesthetic_sensory", "angle_c_problem_agitation"
    angle_archetype: str
    title: str
    target_audience_segment: str
    character_role: CharacterRole = CharacterRole.PRESENTER
    audio_strategy: AudioStrategy = AudioStrategy.ON_CAMERA_SPEECH
    hook_strategy: HookStrategy
    narrative_arc: List[str] = Field(default_factory=list)
    conversion_thesis: str
    # One sentence about the audience's life the whole film argues (not a feature list), and the one
    # image that carries it on screen.
    controlling_idea: Optional[str] = None
    key_visual: Optional[str] = None
    projected_retention_score: float = 8.0  # 1.0 - 10.0
    projected_conversion_score: float = 8.0  # 1.0 - 10.0


class SelectedWinningAngle(BaseModel):
    """The autonomously chosen winning angle for final production."""
    selected_angle_id: str
    selection_rationale: str
    confidence_score: float = 0.90
    directorial_directives: DirectorialDirectives


class CreativeConceptArtifact(BaseModel):
    """Canonical artifact delivering 3 distinct creative angles and the winning selection."""
    campaign_id: str
    product_name: str
    concept_options: List[CreativeAngle] = Field(..., min_length=3)
    winning_concept: SelectedWinningAngle
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# Affiliate Link Fetcher & Normalizer
# ==============================================================================

def resolve_affiliate_url(url: str, timeout: int = 10) -> str:
    """Follows HTTP redirects to resolve shortened affiliate links (e.g. vt.tiktok.com, amzn.to)."""
    if not url.startswith("http://") and not url.startswith("https://"):
        return url
    if is_offline():
        return url
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
            },
        )
        with guarded_urlopen(req, operation="research.resolve_affiliate_url", timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        return url


_META_TAG_RE = re.compile(r"<meta\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


def _meta_tags(html: str) -> Dict[str, str]:
    """Index ``<meta>`` tags by their property/name key regardless of attribute order."""
    tags: Dict[str, str] = {}
    for match in _META_TAG_RE.finditer(html):
        attrs = {m.group(1).lower(): (m.group(2) if m.group(2) is not None else m.group(3)) for m in _ATTR_RE.finditer(match.group(1))}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content")
        if key and content is not None and key not in tags:
            tags[key] = content.strip()
    return tags


def extract_metadata_from_html(html: str) -> Dict[str, Any]:
    """Lightweight regex extractor for title, OpenGraph tags, JSON-LD, and body text."""
    data: Dict[str, Any] = {}

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        data["title"] = title_match.group(1).strip()

    tags = _meta_tags(html)
    if tags.get("og:title"):
        data["og_title"] = tags["og:title"]
    if tags.get("og:description"):
        data["og_description"] = tags["og:description"]
    if tags.get("description") and "og_description" not in data:
        data["meta_description"] = tags["description"]

    # JSON-LD Schema.org parsing
    json_ld_matches = re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL
    )
    json_ld_list = []
    for raw_json in json_ld_matches:
        try:
            parsed = json.loads(raw_json.strip())
            json_ld_list.append(parsed)
        except Exception:
            pass
    if json_ld_list:
        data["json_ld"] = json_ld_list

    # Clean text payload (strip scripts, styles, html tags)
    clean = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<style.*?</style>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    data["body_text"] = clean[:3000]

    return data


# ==============================================================================
# Deterministic price extraction (no invented pricing)
# ==============================================================================

_VND_PRICE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*(?:đ|₫|vnd|vnđ)(?![a-zA-Z])", re.IGNORECASE)
_USD_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")


def extract_prices_from_text(text: str) -> List[tuple[float, str]]:
    """Return every explicit ``(amount, currency)`` price mentioned in free text, in order."""
    found: List[tuple[float, str]] = []
    for m in _VND_PRICE_RE.finditer(text or ""):
        found.append((float(re.sub(r"[.,]", "", m.group(1))), "VND"))
    for m in _USD_PRICE_RE.finditer(text or ""):
        found.append((float(m.group(1).replace(",", "")), "USD"))
    return found


def extract_price_from_text(text: str) -> tuple[float, str]:
    """Return ``(lowest explicit price, currency)`` found in text, or ``(0.0, "VND")`` when none."""
    prices = extract_prices_from_text(text)
    if not prices:
        return 0.0, "VND"
    return min(prices, key=lambda p: p[0])


def extract_price_from_json_ld(json_ld: Any) -> Optional[tuple[float, str]]:
    """Pull an offer price out of schema.org JSON-LD (Product / @graph / list forms)."""
    def _walk(node: Any):
        if isinstance(node, list):
            for item in node:
                yield from _walk(item)
        elif isinstance(node, dict):
            yield node
            for value in node.values():
                if isinstance(value, (dict, list)):
                    yield from _walk(value)

    for node in _walk(json_ld):
        raw = node.get("price", node.get("lowPrice"))
        if raw in (None, ""):
            continue
        try:
            amount = float(str(raw).replace(",", ""))
        except ValueError:
            continue
        if amount > 0:
            return amount, str(node.get("priceCurrency") or "VND")
    return None


def build_page_content(meta: Dict[str, Any]) -> str:
    """Render scraped page metadata (incl. structured JSON-LD price) into LLM / heuristic input text."""
    title = meta.get("og_title") or meta.get("title", "")
    description = meta.get("og_description") or meta.get("meta_description", "")
    lines = [f"Title: {title}", f"Description: {description}"]
    price = extract_price_from_json_ld(meta.get("json_ld", []))
    if price:
        lines.append(f"Price: {price[0]:.0f} {price[1]}")
    lines.append(f"Text: {meta.get('body_text', '')}")
    return "\n".join(lines)


# ==============================================================================
# LLM Integration Helpers
# ==============================================================================

DEFAULT_RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL") or llm.default_model()


def call_llm(system_prompt: str, user_prompt: str, model: Optional[str] = None, timeout: int = 90) -> Optional[str]:
    """Invokes the configured LLM (MiniMax via nine-router by default, see ``pipeline.llm``).

    Returns the cleaned completion text, or ``None`` when every model failed so callers use their
    deterministic fallbacks. Raises ``OfflineNetworkError`` when offline.
    """
    model = model or DEFAULT_RESEARCH_MODEL
    request_meta = {
        "model": model,
        "system_prompt_chars": len(system_prompt),
        "user_prompt_chars": len(user_prompt),
        "timeout_seconds": timeout,
    }
    started = time.monotonic()
    try:
        result = llm.chat(system_prompt, user_prompt, model=model, timeout=timeout)
    except OfflineNetworkError:
        raise
    except Exception as e:
        telemetry.record_api_call(
            "llm.chat_completion",
            request=request_meta,
            response={"error": str(e)},
            status="error",
            ok=False,
            duration_seconds=time.monotonic() - started,
            stage=STAGE_RESEARCH,
        )
        telemetry.note(f"LLM call failed ({e}); deterministic fallback will be used", model=model, error=str(e))
        return None
    telemetry.record_api_call(
        "llm.chat_completion",
        request={**request_meta, "model_used": result["model"]},
        response={"content_chars": len(result["content"]), "usage": result["usage"]},
        status=200,
        ok=True,
        duration_seconds=time.monotonic() - started,
        stage=STAGE_RESEARCH,
    )
    return result["content"]


# ==============================================================================
# Product Intelligence & Objection Extractor
# ==============================================================================

PRODUCT_INTEL_SYSTEM_PROMPT = """You are a World-Class E-Commerce Research Director and Direct-Response Copywriting Strategist.
Analyze the provided product raw metadata/description. Extract rich structured selling intelligence.
Map cold physical specifications into dramatic everyday emotional benefits.
Anticipate the top buyer objections and formulate tangible visual demonstrations that instantly prove them wrong.
Identify sensory anchors (textures, crisp audio clicks, steam, tactile feel) crucial for video diffusion models.
Use ONLY facts, prices and numbers present in the raw content; never invent discounts, certifications or test results (use 0 / empty for unknown values).
Always respond in strict JSON adhering to the target schema. No explanation or markdown fences.
"""

def extract_product_intel(
    raw_content: str,
    product_url: Optional[str] = None,
    product_archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL,
    use_llm: bool = True,
) -> ProductIntel:
    """Extracts deep product intelligence and objection handling matrix."""
    use_llm = use_llm and not is_offline()  # offline: deterministic fallbacks only
    if use_llm:
        user_prompt = f"""Target Product Archetype: {product_archetype.value}
Product URL: {product_url or 'N/A'}
Raw Product Content:
{raw_content}

Output JSON schema:
{{
  "title": "string",
  "brand": "string",
  "category": "string",
  "product_archetype": "{product_archetype.value}",
  "pricing": {{
    "current_price": 0.0,
    "original_price": 0.0,
    "currency": "VND",
    "discount_percent": 0,
    "price_tier": "mid-range"
  }},
  "features": ["spec 1", "spec 2", "spec 3"],
  "dramatic_benefits": ["benefit 1", "benefit 2", "benefit 3"],
  "target_personas": ["persona 1", "persona 2"],
  "awareness_level": "Problem Aware",
  "objection_matrix": [
    {{
      "objection": "Top customer doubt",
      "counter_evidence": "Concrete engineering or proof fact",
      "demonstration_technique": "Extreme visual action to prove it on camera"
    }}
  ],
  "sensory_anchors": ["visceral sound or tactile visual 1", "anchor 2"]
}}
"""
        res = call_llm(PRODUCT_INTEL_SYSTEM_PROMPT, user_prompt)
        if res:
            try:
                parsed = llm.extract_json(res)
                intel = ProductIntel.model_validate(parsed)
                # Explicit prices in the source always beat model-reported ones (no hallucinated pricing).
                explicit = extract_prices_from_text(raw_content)
                if explicit:
                    intel.pricing = _heuristic_product_intel(raw_content, product_archetype).pricing
                return intel
            except Exception:
                pass
        telemetry.note(
            "Deterministic fallback replaced LLM output for product intelligence extraction",
            phase="product_intelligence",
            fallback="heuristic_product_intel",
        )

    # Heuristic / deterministic fallback if LLM is offline: ground everything possible in the raw input
    # and never invent prices, discounts or numeric proof.
    return _heuristic_product_intel(raw_content, product_archetype)


_FIELD_PREFIX_RE = re.compile(r"^(title|description|text|price)\s*:\s*", re.IGNORECASE)


def _price_tier(amount: float, currency: str) -> str:
    if amount <= 0:
        return "unknown"
    vnd = amount if currency.upper() == "VND" else amount * 25000
    if vnd < 200_000:
        return "budget"
    if vnd < 800_000:
        return "mid-range"
    if vnd < 3_000_000:
        return "premium"
    return "luxury"


def _heuristic_product_intel(raw_content: str, product_archetype: ProductArchetype) -> ProductIntel:
    lines = [_FIELD_PREFIX_RE.sub("", ln.strip()) for ln in raw_content.splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln]

    title = "Sản Phẩm Cao Cấp"
    for ln in lines:
        if len(ln) > 5:
            title = ln[:80]
            break

    # Grounded features: sentences / lines from the input other than the title and bare prices.
    candidates: List[str] = []
    for ln in lines[1:]:
        for sentence in re.split(r"(?<=[.!?])\s+|\s[|•·]\s", ln):
            sentence = sentence.strip(" -•*\t")
            if 8 <= len(sentence) <= 140 and not re.fullmatch(r"(giá|gia|price)?\s*:?\s*[\d.,\s]*(đ|₫|vnd|vnđ|\$)?", sentence, re.IGNORECASE):
                candidates.append(sentence)
    features = candidates[:5]
    generic_features = [
        "Chất liệu và hoàn thiện được chăm chút",
        "Thiết kế tối giản, dễ dùng hằng ngày",
        "Trải nghiệm sử dụng ổn định, đáng tin cậy",
    ]
    features = (features + generic_features)[: max(3, len(features))]

    prices = extract_prices_from_text(raw_content)
    pricing = ProductPricing(current_price=0.0, original_price=None, currency="VND", discount_percent=None, price_tier="unknown")
    if prices:
        currency = prices[0][1]
        same = sorted({amt for amt, cur in prices if cur == currency})
        current = same[0]
        original = same[-1] if len(same) >= 2 and current < same[-1] <= current * 5 else None
        pricing = ProductPricing(
            current_price=current,
            original_price=original,
            currency=currency,
            discount_percent=round((1 - current / original) * 100) if original else None,
            price_tier=_price_tier(current, currency),
        )

    return ProductIntel(
        title=title,
        brand="Premium Selection",
        category="Commercial Goods",
        product_archetype=product_archetype,
        pricing=pricing,
        features=features,
        dramatic_benefits=[
            "Một thói quen hằng ngày gọn gàng và dễ chịu hơn",
            "Nâng tầm phong cách cá nhân với thiết kế tinh xảo",
            "Bớt phiền toái, thêm yên tâm khi sử dụng",
        ],
        target_personas=[
            "Người tiêu dùng hiện đại 22-38 tuổi chú trọng chất lượng cuộc sống",
            "Dân công sở và người bận rộn cần giải pháp tiện lợi, thẩm mỹ",
        ],
        awareness_level="Problem Aware",
        objection_matrix=[
            ObjectionProof(
                objection="Liệu sản phẩm có thực sự bền như quảng cáo?",
                counter_evidence="Chứng minh trực quan bằng thao tác thật trước ống kính (không nêu số liệu chưa được xác minh)",
                demonstration_technique="Quay cận cảnh thử thách va đập hoặc chịu tải thực tế",
            ),
            ObjectionProof(
                objection="Giá thành có xứng đáng so với các sản phẩm trôi nổi giá rẻ?",
                counter_evidence="So sánh chi tiết hoàn thiện và trải nghiệm sử dụng thực tế với hàng giá rẻ",
                demonstration_technique="So sánh trực diện bên cạnh sản phẩm giá rẻ ọp ẹp",
            ),
        ],
        sensory_anchors=["Tiếng click chắc chắn khi thao tác", "Ánh sáng bóng loáng phản chiếu bề mặt tinh tế"],
        source="heuristic_fallback",
    )


# ==============================================================================
# Competitor Landscape & Viral Hook Synthesizer
# ==============================================================================

COMPETITOR_HOOK_SYSTEM_PROMPT = """You are a Master Viral Video Producer specializing in TikTok, Instagram Reels, and YouTube Shorts.
You understand why viewers swipe away in 0.8 seconds and how to engineer pattern interrupts that halt thumbs.
Identify what competitors in this category are spamming (saturated angles) and exploit competitor weaknesses.
Synthesize top-performing viral hooks categorized by psychological hook type:
1. Shock / Pattern Interrupt: High adrenaline, counter-intuitive action in 0.5s.
2. Contrarian / Debunking: "Don't buy X until you know this", exposing dirty secrets of cheap alternatives.
3. Sensory / ASMR / Aesthetic: Visceral macro audio-visual satisfaction.
4. Problem Agitation: Relatable acute pain, magnifying daily frustration.
5. POV Story: High-empathy social situational drama.
Always respond in strict JSON adhering to the target schema.
"""

def _short_name(title: str, max_words: int = 5) -> str:
    """Spoken-friendly product name: cut at the first separator and cap the word count."""
    head = re.split(r"\s[-–—|,]\s|\s*[|,]\s*", title.strip(), maxsplit=1)[0]
    words = head.split()
    return " ".join(words[:max_words]) or title.strip()


def synthesize_competitor_and_hooks(product: ProductIntel, use_llm: bool = True) -> tuple[CompetitorLandscape, List[ViralHookCandidate]]:
    """Synthesizes competitor landscape and generates categorized viral hooks."""
    use_llm = use_llm and not is_offline()  # offline: deterministic fallbacks only
    if use_llm:
        user_prompt = f"""Product: {product.title}
Category: {product.category} ({product.product_archetype.value})
Features: {', '.join(product.features)}
Benefits: {', '.join(product.dramatic_benefits)}
Key Objections: {', '.join(o.objection for o in product.objection_matrix)}

Generate Competitor Landscape and 5 Viral Hook Candidates.
Output JSON schema:
{{
  "landscape": {{
    "saturated_angles": ["Angle competitors overuse 1", "Angle 2"],
    "competitor_weaknesses": ["Common customer complaint about rival products 1", "Weakness 2"],
    "whitespace_opportunities": ["Untapped winning angle 1", "Opportunity 2"]
  }},
  "hooks": [
    {{
      "hook_type": "shock_interrupt",
      "spoken_line": "Spoken line under 15 words in Vietnamese",
      "visual_action": "Visceral cinematic visual action in first 1.5 seconds",
      "on_screen_text": "High-contrast all-caps kinetic caption",
      "retention_mechanism": "Why this prevents swipe-away",
      "projected_stop_ratio": 0.88
    }}
  ]
}}
"""
        res = call_llm(COMPETITOR_HOOK_SYSTEM_PROMPT, user_prompt)
        if res:
            try:
                parsed = llm.extract_json(res)
                landscape = CompetitorLandscape.model_validate(parsed.get("landscape", {}))
                hooks = [ViralHookCandidate.model_validate(h) for h in parsed.get("hooks", [])]
                if hooks:
                    return landscape, hooks
            except Exception:
                pass
        telemetry.note(
            "Deterministic fallback replaced LLM output for competitor landscape and viral hooks",
            phase="competitor_hooks",
            fallback="deterministic_hook_library",
        )

    # Deterministic fallback
    short_name = _short_name(product.title)
    landscape = CompetitorLandscape(
        saturated_angles=[
            "KOL cầm sản phẩm đứng trước gương nói chuyện chung chung không có điểm nhấn",
            "Review theo phong cách mở hộp nhàm chán đọc bảng thông số kỹ thuật",
            "Quảng cáo giật gân thiếu căn cứ khoa học hoặc chứng minh trực quan",
        ],
        competitor_weaknesses=[
            "Chất lượng hoàn thiện kém, dễ ọp ẹp sau 2 tuần sử dụng",
            "Mùi nhựa nồng hoặc vị kim loại ám vào thực phẩm/nước uống",
            "Chế độ bảo hành mập mờ, không có hỗ trợ đổi trả",
        ],
        whitespace_opportunities=[
            "Thử thách cực hạn phá hủy (stress test) ngay trong 2 giây đầu tiên",
            "Quay macro ASMR siêu cận chi tiết vật liệu và âm thanh thao tác thỏa mãn",
            "So sánh đối đầu trực diện split-screen giữa sản phẩm rẻ tiền và sản phẩm này",
        ],
    )
    hooks = [
        ViralHookCandidate(
            hook_type="shock_interrupt",
            spoken_line=f"Đừng dại mua {short_name} trừ khi bạn biết rõ điều này!",
            visual_action="Góc máy cận cảnh thực hiện thao tác thử thách va đập hoặc rót nước sốt dội ngược",
            on_screen_text=f"CẢNH BÁO: ĐỪNG MUA {short_name.upper()}!",
            retention_mechanism="Pattern interrupt tạo cảm giác tò mò và lo sợ rủi ro (loss aversion)",
            projected_stop_ratio=0.91,
        ),
        ViralHookCandidate(
            hook_type="contrarian_debunking",
            spoken_line="Tại sao món đồ vài trăm nghìn này lại thay thế hoàn toàn hàng triệu đồng?",
            visual_action="Hai sản phẩm đặt cạnh nhau, bên trái hàng đắt tiền bị bóc trần nhược điểm",
            on_screen_text="SỰ THẬT ĐẰNG SAU MÓN ĐỒ TIỀN TRIỆU",
            retention_mechanism="Đánh vào tâm lý thông minh tiêu dùng và tò mò về giá trị thực",
            projected_stop_ratio=0.87,
        ),
        ViralHookCandidate(
            hook_type="sensory_asmr",
            spoken_line="Âm thanh và cảm giác này... dân mê decor và tinh tế chắc chắn sẽ nghiện.",
            visual_action="Chuyển động camera Macro Orbit siêu mượt, âm thanh click và chất liệu bóng mờ cực nét",
            on_screen_text="THỰC SỰ THỎA MÃN TỪNG CHI TIẾT",
            retention_mechanism="Kích thích dopamine bằng thị giác và thính giác ASMR cao cấp",
            projected_stop_ratio=0.85,
        ),
        ViralHookCandidate(
            hook_type="problem_agitation",
            spoken_line="Bạn có phát chán khi mỗi ngày đều phải chịu đựng sự phiền toái này?",
            visual_action="Dramatize cảnh tượng bừa bộn hoặc sự cố hỏng hóc gây ức chế tột độ",
            on_screen_text="BẠN CÓ ĐANG CHỊU ĐỰNG ĐIỀU NÀY?",
            retention_mechanism="Kích hoạt nỗi đau trực tiếp khiến người xem nhận ra chính mình",
            projected_stop_ratio=0.89,
        ),
    ]
    return landscape, hooks


# ==============================================================================
# 3-Angle Creative Concept Generator & Winning Angle Selection
# ==============================================================================

CREATIVE_CONCEPT_SYSTEM_PROMPT = """You are an Executive Commercial Director.
You formulate 3 DISTINCT, un-compromised commercial video concepts for an e-commerce campaign:
- Angle A: Shock / Pattern Interrupt / Contrarian (High energy, immediate disruption, stress test or debunking)
- Angle B: Aesthetic / Sensory / ASMR Demonstration (Cinematic macro visuals, aspirational lifestyle, tactile immersion)
- Angle C: Direct Problem-Agitation (Hard DR, a relatable daily frustration of the audience vs the moment it is solved)

For each angle:
0. Write controlling_idea: ONE sentence about the target audience's life that the whole film argues (not a list of
   features, not a slogan), and key_visual: the ONE concrete image that carries that idea on screen without words.
1. Define character_role ("presenter", "model", or "product_only") and audio_strategy ("on_camera_speech", "off_camera_vo", "music_and_sfx_only", "asmr_hybrid").
2. Construct the 0-3s Hook Strategy (spoken, visual, text overlay, retention mechanism).
3. Outline the 5-beat Narrative Arc (0-3s hook, 3-7s agitation, 7-15s demonstration, 15-20s objection proof, 20-25s cta).
4. Score projected retention (1-10) and conversion (1-10).

Rules:
- If a client-fixed target audience is given, every angle targets exactly that audience and dramatizes a concrete
  moment of THEIR day (where, when, what goes wrong), not a generic product objection.
- The pain must be one the audience really has. Never invent a strawman problem the product category does not cause
  (e.g. "waiting to adjust gears" for a bike nobody adjusts before riding).
- No comparison with, or depiction of, a competitor or "other product" (Vietnamese advertising law bans direct
  comparison), no split-screen versus shots, no on-screen timers or numbers that are not in the facts.
- Features are proven inside the story's action (she brakes hard at a real moment), never as a tour of parts.
- Avoid the category's cliches listed in Whitespace and in your own knowledge; say which one each angle avoids.

Finally, evaluate and select the WINNING concept based on category dynamics, audience awareness, and conversion probability. Provide precise directorial directives for camera, lighting, and pacing.
Always output strict JSON adhering to schema.
"""

def generate_creative_concepts(
    research: CompetitorResearchArtifact,
    use_llm: bool = True,
    audience: Optional[str] = None,
) -> CreativeConceptArtifact:
    """Generates 3 distinct creative concepts and objectively selects the winning angle.

    ``audience`` is the client-fixed target audience: the LLM must write every angle for it and every
    angle's ``target_audience_segment`` is set to it (models drift to generic segments otherwise).
    """
    product = research.product_intel
    use_llm = use_llm and not is_offline()  # offline: deterministic fallbacks only
    artifact: Optional[CreativeConceptArtifact] = None
    if use_llm:
        audience_line = f"Client-fixed target audience (write every angle for exactly them): {audience}\n" if audience else ""
        user_prompt = f"""{audience_line}Campaign ID: {research.campaign_id}
Product: {product.title} ({product.category})
Archetype: {product.product_archetype.value}
Price: {product.pricing.current_price} {product.pricing.currency} (Discount: {product.pricing.discount_percent}%)
Features: {', '.join(product.features)}
Benefits: {', '.join(product.dramatic_benefits)}
Objections: {', '.join(o.objection for o in product.objection_matrix)}
Whitespace: {', '.join(research.competitor_landscape.whitespace_opportunities)}
Awareness level: {product.awareness_level}
Allowed character roles / audio strategies for this archetype: {', '.join(r.value for r in _allowed_roles(product.product_archetype))} / {', '.join(a.value for a in _allowed_audio(product.product_archetype))} (presenter <=> on_camera_speech only)

Output JSON schema:
{{
  "concept_options": [
    {{
      "angle_id": "angle_a_shock_interrupt",
      "angle_archetype": "shock_pattern_interrupt",
      "title": "Compelling Title",
      "target_audience_segment": "Audience segment",
      "controlling_idea": "One sentence about the audience's life the film argues",
      "key_visual": "The one image that carries the idea",
      "character_role": "presenter",
      "audio_strategy": "on_camera_speech",
      "hook_strategy": {{
        "spoken_hook": "Vietnamese spoken line under 15 words",
        "visual_hook": "Specific camera and physical action description",
        "on_screen_text": "ALL-CAPS TEXT OVERLAY",
        "retention_trigger": "Psychological trigger"
      }},
      "narrative_arc": ["0-3s beat", "3-7s beat", "7-15s beat", "15-20s beat", "20-25s beat"],
      "conversion_thesis": "Why this specific angle drives conversion",
      "projected_retention_score": 8.8,
      "projected_conversion_score": 9.2
    }},
    {{
      "angle_id": "angle_b_aesthetic_sensory",
      "angle_archetype": "aesthetic_sensory_asmr",
      "title": "Compelling Title",
      "target_audience_segment": "Audience segment",
      "character_role": "model",
      "audio_strategy": "asmr_hybrid",
      "hook_strategy": {{
        "spoken_hook": "Vietnamese line",
        "visual_hook": "Macro lighting and motion description",
        "on_screen_text": "TEXT",
        "retention_trigger": "Aesthetic aspiration"
      }},
      "narrative_arc": ["0-3s beat", "3-7s beat", "7-15s beat", "15-20s beat", "20-25s beat"],
      "conversion_thesis": "Thesis",
      "projected_retention_score": 8.5,
      "projected_conversion_score": 8.7
    }},
    {{
      "angle_id": "angle_c_problem_agitation",
      "angle_archetype": "direct_problem_agitation",
      "title": "Compelling Title",
      "target_audience_segment": "Audience segment",
      "character_role": "presenter",
      "audio_strategy": "on_camera_speech",
      "hook_strategy": {{
        "spoken_hook": "Vietnamese line",
        "visual_hook": "Acute pain and failure dramatization",
        "on_screen_text": "TEXT",
        "retention_trigger": "Problem identification"
      }},
      "narrative_arc": ["0-3s beat", "3-7s beat", "7-15s beat", "15-20s beat", "20-25s beat"],
      "conversion_thesis": "Thesis",
      "projected_retention_score": 8.7,
      "projected_conversion_score": 9.4
    }}
  ],
  "winning_concept": {{
    "selected_angle_id": "angle_a_shock_interrupt",
    "selection_rationale": "Detailed reason why this angle won",
    "confidence_score": 0.93,
    "directorial_directives": {{
      "camera_pacing": "Fast kinetic whip pans into locked macro push",
      "lighting_mood": "High contrast commercial rim lighting",
      "key_visual_anchor": "Specific hero visual element",
      "audio_mix_priority": "dialogue_first"
    }}
  }}
}}
"""
        res = call_llm(CREATIVE_CONCEPT_SYSTEM_PROMPT, user_prompt)
        if res:
            try:
                parsed = llm.extract_json(res)
                options = [CreativeAngle.model_validate(c) for c in parsed.get("concept_options", [])]
                try:
                    winning: Optional[SelectedWinningAngle] = SelectedWinningAngle.model_validate(
                        parsed.get("winning_concept", {})
                    )
                except Exception:
                    winning = None
                artifact = _finalize_concepts(research, options, winning, generator="llm_gemini")
            except Exception:
                artifact = None
        if artifact is None:
            telemetry.note(
                "Deterministic fallback replaced LLM output for the 3-angle creative concept selection",
                phase="creative_concepts",
                fallback="deterministic_creative_concepts",
            )

    if artifact is None:
        artifact = _finalize_concepts(research, _deterministic_angles(research), None, generator="deterministic_fallback")
    if audience:
        for angle in artifact.concept_options:
            angle.target_audience_segment = audience
    return artifact


# ------------------------------------------------------------------------------
# Archetype-aware angle conformance, winner selection and hook linting
# ------------------------------------------------------------------------------

# How naturally each creative angle (a = shock, b = sensory, c = problem agitation) fits each archetype.
ANGLE_ARCHETYPE_AFFINITY: Dict[ProductArchetype, Dict[str, float]] = {
    ProductArchetype.FASHION_APPAREL: {"a": 0.4, "b": 1.0, "c": 0.3},
    ProductArchetype.TECH_GADGETS: {"a": 1.0, "b": 0.6, "c": 0.8},
    ProductArchetype.BEAUTY_SKINCARE: {"a": 0.4, "b": 1.0, "c": 0.7},
    ProductArchetype.HOME_LIFESTYLE: {"a": 0.4, "b": 0.9, "c": 0.8},
    ProductArchetype.GENERAL_COMMERCIAL: {"a": 1.0, "b": 0.6, "c": 0.9},
}

# Audience awareness shifts which angle converts best (cold -> interrupt, warm -> proof / value).
ANGLE_AWARENESS_BONUS: Dict[str, Dict[str, float]] = {
    "unaware": {"a": 0.2},
    "problem": {"a": 0.1, "c": 0.15},
    "solution": {"a": 0.1, "b": 0.1},
    "product": {"b": 0.15, "c": 0.1},
    "most": {"c": 0.2},
}

HOOK_MAX_SPOKEN_WORDS = 15
HOOK_MAX_CAPTION_WORDS = 12


def _angle_key(angle_id: str) -> str:
    m = re.match(r"angle_([abc])", angle_id or "")
    return m.group(1) if m else ""


def _awareness_key(level: str) -> str:
    lowered = (level or "").lower()
    for key in ANGLE_AWARENESS_BONUS:
        if key in lowered:
            return key
    return "problem"


def _allowed_roles(archetype: ProductArchetype) -> List[CharacterRole]:
    return list(get_archetype_config(archetype).allowed_character_roles)


def _allowed_audio(archetype: ProductArchetype) -> List[AudioStrategy]:
    return list(get_archetype_config(archetype).allowed_audio_strategies)


def conform_angle_to_archetype(angle: CreativeAngle, archetype: ProductArchetype) -> List[str]:
    """Force an angle's Character Role / Audio Strategy to obey its Directorial Archetype (in place).

    Rules: role and audio must be allowed by the archetype; on-camera speech requires a Presenter and
    a Presenter always speaks on camera (lip-sync contract). Returns a list of human-readable changes.
    """
    cfg = get_archetype_config(archetype)
    changes: List[str] = []
    role, audio = angle.character_role, angle.audio_strategy

    if role not in cfg.allowed_character_roles:
        role = cfg.default_character_role
    if audio not in cfg.allowed_audio_strategies:
        audio = cfg.default_audio_strategy

    if role == CharacterRole.PRESENTER:
        if AudioStrategy.ON_CAMERA_SPEECH in cfg.allowed_audio_strategies:
            audio = AudioStrategy.ON_CAMERA_SPEECH
        else:
            role = cfg.default_character_role
    if role != CharacterRole.PRESENTER and audio == AudioStrategy.ON_CAMERA_SPEECH:
        audio = next(
            (a for a in (cfg.default_audio_strategy, AudioStrategy.OFF_CAMERA_VO, *cfg.allowed_audio_strategies)
             if a != AudioStrategy.ON_CAMERA_SPEECH and a in cfg.allowed_audio_strategies),
            AudioStrategy.OFF_CAMERA_VO,
        )

    if role != angle.character_role:
        changes.append(f"{angle.angle_id}: character_role {angle.character_role.value} -> {role.value}")
        angle.character_role = role
    if audio != angle.audio_strategy:
        changes.append(f"{angle.angle_id}: audio_strategy {angle.audio_strategy.value} -> {audio.value}")
        angle.audio_strategy = audio
    return changes


def lint_hook_strategy(angle: CreativeAngle) -> List[str]:
    """Flag hooks that break short-form rules (TikTok: proposition within 3s, ~5-10 words/second of text)."""
    issues: List[str] = []
    hs = angle.hook_strategy
    spoken_words = len(hs.spoken_hook.split())
    if spoken_words > HOOK_MAX_SPOKEN_WORDS:
        issues.append(f"spoken_hook has {spoken_words} words (max {HOOK_MAX_SPOKEN_WORDS} for a 0-3s hook)")
    caption_words = len(hs.on_screen_text.split())
    if caption_words > HOOK_MAX_CAPTION_WORDS:
        issues.append(f"on_screen_text has {caption_words} words (max {HOOK_MAX_CAPTION_WORDS})")
    if not hs.visual_hook.strip():
        issues.append("visual_hook is empty (the hook must be visible with sound off)")
    return issues


def _score_angle(angle: CreativeAngle, research: CompetitorResearchArtifact) -> float:
    product = research.product_intel
    key = _angle_key(angle.angle_id)
    affinity = ANGLE_ARCHETYPE_AFFINITY.get(product.product_archetype, {}).get(key, 0.5)
    affinity += ANGLE_AWARENESS_BONUS.get(_awareness_key(product.awareness_level), {}).get(key, 0.0)
    return (
        0.3 * angle.projected_retention_score / 10.0
        + 0.3 * angle.projected_conversion_score / 10.0
        + 0.4 * affinity
    )


_ANGLE_DIRECTIVE_STYLE: Dict[str, Dict[str, str]] = {
    "a": {
        "pacing": "Snap zoom đột ngột trong 1.5s đầu, sau đó chuyển sang chuyển động mượt khi trình diễn tính năng",
        "light": "tương phản sắc nét làm nổi bật cấu trúc sản phẩm",
        "mix": "dialogue_first",
    },
    "b": {
        "pacing": "Nhịp cắt chậm, chuyển động macro mượt bám theo nhịp nhạc, giữ nhịp thở thị giác",
        "light": "ánh sáng khuếch tán mềm làm nổi chất liệu và bề mặt",
        "mix": "foley_and_music_first",
    },
    "c": {
        "pacing": "Handheld cận cảnh cho khoảnh khắc khủng hoảng, cắt nhanh sang dolly sạch khi giải pháp xuất hiện",
        "light": "tương phản lạnh cho cảnh vấn đề, chuyển ấm sáng khi giải pháp xuất hiện",
        "mix": "dialogue_first",
    },
}


def _directives_for(angle: CreativeAngle, research: CompetitorResearchArtifact) -> DirectorialDirectives:
    product = research.product_intel
    cfg = get_archetype_config(product.product_archetype)
    key = _angle_key(angle.angle_id)
    style = _ANGLE_DIRECTIVE_STYLE.get(key, _ANGLE_DIRECTIVE_STYLE["a"])
    motions = ", ".join(m.value for m in cfg.primary_camera_motions[:2])
    if key == "b" and product.sensory_anchors:
        anchor = product.sensory_anchors[0]
    elif product.objection_matrix:
        anchor = product.objection_matrix[0].demonstration_technique
    elif product.sensory_anchors:
        anchor = product.sensory_anchors[0]
    else:
        anchor = angle.hook_strategy.visual_hook
    if angle.audio_strategy == AudioStrategy.ON_CAMERA_SPEECH:
        mix = "dialogue_first"
    elif angle.audio_strategy == AudioStrategy.MUSIC_AND_SFX_ONLY:
        mix = "music_and_sfx_beat_sync"
    elif angle.audio_strategy == AudioStrategy.ASMR_HYBRID:
        mix = "foley_and_music_first"
    else:
        mix = "voiceover_first"
    return DirectorialDirectives(
        camera_pacing=f"{style['pacing']} (chuyển động chính: {motions})",
        lighting_mood=f"{cfg.default_lighting.value} @ {cfg.nominal_color_temp_kelvin}K, {style['light']}",
        key_visual_anchor=anchor,
        audio_mix_priority=mix,
    )


def _finalize_concepts(
    research: CompetitorResearchArtifact,
    options: List[CreativeAngle],
    winning: Optional[SelectedWinningAngle],
    generator: str,
) -> CreativeConceptArtifact:
    """Validate, conform to the archetype, score, and order angles so the winner is ``concept_options[0]``."""
    product = research.product_intel

    unique: List[CreativeAngle] = []
    seen: set[str] = set()
    for angle in options:
        if angle.angle_id not in seen:
            seen.add(angle.angle_id)
            unique.append(angle)
    if len(unique) < 3:
        raise ValueError("fewer than 3 distinct creative angles")

    adjustments: List[str] = []
    hook_lint: Dict[str, List[str]] = {}
    for angle in unique:
        angle.projected_retention_score = min(10.0, max(1.0, angle.projected_retention_score))
        angle.projected_conversion_score = min(10.0, max(1.0, angle.projected_conversion_score))
        adjustments.extend(conform_angle_to_archetype(angle, product.product_archetype))
        issues = lint_hook_strategy(angle)
        if issues:
            hook_lint[angle.angle_id] = issues

    scores = {a.angle_id: round(_score_angle(a, research), 4) for a in unique}
    ranked = sorted(unique, key=lambda a: scores[a.angle_id], reverse=True)
    repaired = winning is None or winning.selected_angle_id not in scores
    if repaired:
        best = ranked[0]
        margin = scores[ranked[0].angle_id] - scores[ranked[1].angle_id]
        winning = SelectedWinningAngle(
            selected_angle_id=best.angle_id,
            selection_rationale=(
                f"Chọn '{best.title}': phù hợp archetype {product.product_archetype.value}, "
                f"mức nhận thức '{product.awareness_level}', điểm kỳ vọng retention "
                f"{best.projected_retention_score:.1f}/conversion {best.projected_conversion_score:.1f}; "
                f"vai trò {best.character_role.value} và audio {best.audio_strategy.value} hợp lệ với archetype."
            ),
            confidence_score=round(min(0.95, 0.7 + 3 * margin), 2),
            directorial_directives=_directives_for(best, research),
        )
    else:
        winning.confidence_score = min(1.0, max(0.0, winning.confidence_score))

    chosen = next(a for a in unique if a.angle_id == winning.selected_angle_id)
    ordered = [chosen] + [a for a in ranked if a.angle_id != chosen.angle_id]

    return CreativeConceptArtifact(
        campaign_id=research.campaign_id,
        product_name=product.title,
        concept_options=ordered,
        winning_concept=winning,
        metadata={
            "generator": generator,
            "research_grounded": True,
            "angle_scores": scores,
            "winner_repaired": repaired,
            "role_adjustments": adjustments,
            "hook_lint": hook_lint,
        },
    )


def _deterministic_angles(research: CompetitorResearchArtifact) -> List[CreativeAngle]:
    """Three archetype-agnostic angles grounded in the product's own objections and sensory anchors."""
    product = research.product_intel
    short = _short_name(product.title)
    objection = product.objection_matrix[0] if product.objection_matrix else None
    pain = _truncate_words(objection.objection if objection else (product.features[0] if product.features else "điều phiền toái hằng ngày"), 7)
    proof_action = objection.demonstration_technique if objection else "thao tác thử thách thực tế trước ống kính"
    sensory = product.sensory_anchors[0] if product.sensory_anchors else "âm thanh thao tác thỏa mãn"

    opt_a = CreativeAngle(
        angle_id="angle_a_shock_interrupt",
        angle_archetype="shock_pattern_interrupt",
        title=f"Thử Thách Cực Hạn: Phá Vỡ Mọi Giới Hạn Của {short}",
        target_audience_segment="Người trẻ thích khám phá, người mua thực tế đòi hỏi độ bền tuyệt đối",
        character_role=CharacterRole.PRESENTER,
        audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
        hook_strategy=HookStrategy(
            spoken_hook=f"Đừng dại mua {short} nếu bạn chưa xem màn thử thách này!",
            visual_hook=f"Mở đầu bằng khoảnh khắc gây sốc: {proof_action}",
            on_screen_text="THỬ THÁCH ĐỘ BỀN CỰC HẠN!",
            retention_trigger="Pattern interrupt gây sốc thị giác, phá tan phản xạ lướt qua",
        ),
        narrative_arc=[
            f"0-3s: {proof_action}",
            "3-7s: Vạch trần sự phiền toái của các loại hàng kém chất lượng trên thị trường",
            "7-15s: Mổ xẻ các điểm khác biệt giải quyết triệt để vấn đề",
            "15-20s: Bẻ gãy nỗi lo của khách hàng bằng bằng chứng thị giác thực tế",
            "20-25s: Kêu gọi hành động rõ ràng, nhấp link giỏ hàng bên dưới",
        ],
        conversion_thesis="Bằng chứng thị giác trực diện (Proof-First) thuyết phục ngay cả những khách hàng hoài nghi nhất.",
        projected_retention_score=9.1,
        projected_conversion_score=9.3,
    )
    opt_b = CreativeAngle(
        angle_id="angle_b_aesthetic_sensory",
        angle_archetype="aesthetic_sensory_asmr",
        title=f"Chuẩn Mực Tinh Tế: Trải Nghiệm Cùng {short}",
        target_audience_segment="Tín đồ phong cách sống tinh tế, thích thẩm mỹ tối giản và chi tiết hoàn thiện",
        character_role=CharacterRole.MODEL,
        audio_strategy=AudioStrategy.ASMR_HYBRID,
        hook_strategy=HookStrategy(
            spoken_hook="Từng chi tiết nhỏ... nâng tầm toàn bộ trải nghiệm mỗi ngày của bạn.",
            visual_hook=f"Cú lướt camera macro siêu nét bắt sáng bề mặt chất liệu; âm thanh: {sensory}",
            on_screen_text="ĐẲNG CẤP TỪNG ĐƯỜNG NÉT",
            retention_trigger="Kích thích dopamine thị giác và thính giác ASMR sang trọng",
        ),
        narrative_arc=[
            "0-3s: Cận cảnh macro bóng bẩy với âm thanh thao tác thỏa mãn",
            "3-7s: Người mẫu hòa mình trong không gian sống tối giản, hiện đại",
            "7-15s: Từng chi tiết vận hành mượt mà, tĩnh lặng và đẳng cấp",
            "15-20s: Cảm giác tự hào và thăng hoa khi sở hữu món đồ tinh xảo",
            "20-25s: CTA thanh lịch, nâng cấp trải nghiệm ngay hôm nay",
        ],
        conversion_thesis="Tạo khao khát sở hữu phong cách sống (lifestyle aspiration), giảm nhạy cảm về giá.",
        projected_retention_score=8.7,
        projected_conversion_score=8.8,
    )
    opt_c = CreativeAngle(
        angle_id="angle_c_problem_agitation",
        angle_archetype="direct_problem_agitation",
        title=f"Chấm Dứt Phiền Toái Cùng {short}",
        target_audience_segment="Người bận rộn thường xuyên gặp sự cố phiền toái hằng ngày",
        character_role=CharacterRole.PRESENTER,
        audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
        hook_strategy=HookStrategy(
            spoken_hook=f"Từng phát điên vì chuyện này chưa: {pain}?",
            visual_hook=f"Dựng lại tình huống khó chịu quen thuộc: {pain}; nhân vật bất lực, bực bội",
            on_screen_text="THẢM CẢNH QUEN THUỘC?",
            retention_trigger="Khơi gợi cảm xúc ức chế và sự đồng cảm tình huống sâu sắc",
        ),
        narrative_arc=[
            "0-3s: Tái hiện tình huống khó chịu quen thuộc",
            "3-7s: Phân tích tổn thất về thời gian, tiền bạc và tâm trạng khi dùng đồ kém phù hợp",
            f"7-15s: {short} xuất hiện như giải pháp cứu cánh",
            "15-20s: Chứng minh hiệu quả bằng thao tác thực tế trước ống kính",
            "20-25s: Kêu gọi hành động rõ ràng, nhấp link giỏ hàng bên dưới",
        ],
        conversion_thesis="Kỹ thuật Agitate Pain -> Relieve Solution kinh điển của Direct Response, thôi thúc mua ngay để giải thoát.",
        projected_retention_score=8.9,
        projected_conversion_score=9.5,
    )
    return [opt_a, opt_b, opt_c]


def _truncate_words(text: str, max_words: int) -> str:
    words = text.strip().rstrip("?.!").split()
    return " ".join(words[:max_words])


# ==============================================================================
# Full Research Pipeline Orchestration
# ==============================================================================

def _price_anchor_strategy(pricing: ProductPricing) -> str:
    """Describe price anchoring ONLY from verified pricing; never invent a discount."""
    if pricing.current_price <= 0:
        return ""
    text = f"Giá bán {pricing.current_price:,.0f} {pricing.currency}"
    if pricing.original_price and pricing.original_price > pricing.current_price:
        pct = pricing.discount_percent or round((1 - pricing.current_price / pricing.original_price) * 100)
        text += f", giảm {pct}% so với giá gốc {pricing.original_price:,.0f} {pricing.currency}"
    return text


def run_research_pipeline(
    product_input: str,
    campaign_id: str = "campaign_auto_01",
    archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL,
    output_dir: Optional[Path] = None,
    use_llm: bool = True,
    workspace: Optional[ProjectWorkspace] = None,
    auto_detect_archetype: bool = True,
    audience: Optional[str] = None,
) -> tuple[CompetitorResearchArtifact, CreativeConceptArtifact]:
    """Autonomous entry point: analyzes affiliate link or raw product text,

    discovers competitor landscape, synthesizes hooks, and outputs both artifacts.
    ``audience`` (client-fixed target audience) becomes the primary persona and every angle's segment.
    """
    if workspace is not None:
        target_dir = workspace.artifacts_dir
        if campaign_id == "campaign_auto_01" and workspace.project_id:
            campaign_id = workspace.project_id
    else:
        target_dir = output_dir or ARTIFACTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    product_url = None
    raw_content = product_input.strip()

    # Detect if input starts with a URL
    parts = raw_content.split(maxsplit=1)
    first_token = parts[0]
    accompanying_text = parts[1] if len(parts) > 1 else ""

    telemetry.stage_progress(
        STAGE_RESEARCH,
        1,
        len(RESEARCH_PHASES),
        unit="phases",
        label="Ingesting product input",
        item={
            "id": RESEARCH_PHASES[0],
            "status": "running",
            "product_url": first_token if first_token.startswith("http") else None,
            "input_chars": len(product_input),
            "has_accompanying_text": bool(accompanying_text),
        },
    )

    use_llm = use_llm and not is_offline()  # offline: deterministic fallbacks only
    if first_token.startswith("http://") or first_token.startswith("https://"):
        product_url = first_token
        try:
            if is_offline():
                raise ConnectionError("offline mode: product page not fetched")
            product_url = resolve_affiliate_url(first_token, timeout=4)
            req = urllib.request.Request(
                product_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    )
                },
            )
            with guarded_urlopen(req, operation="research.fetch_product_page", timeout=4) as resp:
                html_body = resp.read().decode("utf-8", errors="replace")
                meta = extract_metadata_from_html(html_body)
                page_content = build_page_content(meta)
                raw_content = f"{accompanying_text}\n{page_content}".strip()
        except Exception:
            # Network blocked, offline, or mock URL -> prioritize accompanying product text
            raw_content = accompanying_text if accompanying_text else f"Product URL: {product_url}"
        telemetry.stage_progress(
            STAGE_RESEARCH,
            1,
            len(RESEARCH_PHASES),
            unit="phases",
            label="Product page ingested",
            item={
                "id": RESEARCH_PHASES[0],
                "status": "done",
                "product_url": product_url,
                "scraped_chars": len(raw_content),
            },
        )
    # An unspecified (GENERAL) archetype is auto-detected from the ingested product text so the
    # Directorial Archetype (roles, audio, lighting, beats) matches the product instead of defaulting to generic.
    # The Director decides the archetype once, up front, and passes ``auto_detect_archetype=False``.
    if auto_detect_archetype and archetype == ProductArchetype.GENERAL_COMMERCIAL:
        detected = classify_product_archetype(raw_content)
        if detected != archetype:
            telemetry.note(
                f"Auto-detected Directorial Archetype '{detected.value}' from product text",
                phase="ingest_product_input",
                detected_archetype=detected.value,
            )
            archetype = detected

    # Step 1: Product Intel Extraction
    product_intel = extract_product_intel(
        raw_content=raw_content,
        product_url=product_url,
        product_archetype=archetype,
        use_llm=use_llm,
    )
    telemetry.stage_progress(
        STAGE_RESEARCH,
        2,
        len(RESEARCH_PHASES),
        unit="phases",
        label="Product intelligence",
        item={
            "id": RESEARCH_PHASES[1],
            "status": "extracted",
            "title": product_intel.title,
            "features": len(product_intel.features),
            "objections": len(product_intel.objection_matrix),
        },
    )

    # Step 2: Competitor Angles & Viral Hooks
    landscape, hooks = synthesize_competitor_and_hooks(product_intel, use_llm=use_llm)
    telemetry.stage_progress(
        STAGE_RESEARCH,
        3,
        len(RESEARCH_PHASES),
        unit="phases",
        label="Competitor landscape & viral hooks",
        item={
            "id": RESEARCH_PHASES[2],
            "status": "synthesized",
            "hooks": len(hooks),
            "whitespace_opportunities": len(landscape.whitespace_opportunities),
        },
    )

    # Build CompetitorResearchArtifact
    research_artifact = CompetitorResearchArtifact(
        campaign_id=campaign_id,
        product_url=product_url,
        product_intel=product_intel,
        competitor_landscape=landscape,
        viral_hook_library=hooks,
        primary_persona=audience or (product_intel.target_personas[0] if product_intel.target_personas else "Người tiêu dùng hiện đại"),
        price_anchor_strategy=_price_anchor_strategy(product_intel.pricing),
    )

    # Step 3: 3-Angle Creative Concepts & Winning Angle Selection
    creative_concept_artifact = generate_creative_concepts(research_artifact, use_llm=use_llm, audience=audience)
    telemetry.stage_progress(
        STAGE_RESEARCH,
        4,
        len(RESEARCH_PHASES),
        unit="phases",
        label="Creative concepts & winning angle",
        item={
            "id": RESEARCH_PHASES[3],
            "status": "selected",
            "options": len(creative_concept_artifact.concept_options),
            "winning_angle": creative_concept_artifact.winning_concept.selected_angle_id,
            "generator": (creative_concept_artifact.metadata or {}).get("generator"),
        },
    )

    # Persist artifacts to disk
    research_file = target_dir / "competitor_research.json"
    with open(research_file, "w", encoding="utf-8") as f:
        json.dump(research_artifact.model_dump(), f, ensure_ascii=False, indent=2)

    concept_file = target_dir / "creative_concept.json"
    with open(concept_file, "w", encoding="utf-8") as f:
        json.dump(creative_concept_artifact.model_dump(), f, ensure_ascii=False, indent=2)

    return research_artifact, creative_concept_artifact
