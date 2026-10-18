"""Director's Wardrobe, Costume Library & Environmental Staging System.

Implements DramaClaw's identity_costume and stage_manifest separation:
- Decouples Character Facial Identity from Costume (WEAR) and Background Environment (SET).
- Provides a reusable wardrobe catalog covering Haute Couture, Techwear, Luxury Executive,
  Beauty Spa, and Home Lifestyle.
- Maintains spatial continuity and color temperature across all shots.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from pipeline.archetypes import LightingContract, ProductArchetype


class CostumeStyle(str, Enum):
    HAUTE_COUTURE = "haute_couture"
    STREETWEAR = "streetwear"
    TECHWEAR = "techwear"
    SMART_CASUAL = "smart_casual"
    LUXURY_EXECUTIVE = "luxury_executive"
    MINIMALIST_SPA = "minimalist_spa"
    COZY_HOMELIVING = "cozy_homeliving"


class WardrobeItem(BaseModel):
    """A distinct costume outfit profile from the Director's Wardrobe Catalog."""
    costume_id: str
    name: str
    archetype: ProductArchetype
    style: CostumeStyle
    color_palette: List[str]
    fabric_materials: List[str]
    garment_description: str
    hair_styling: str
    accessories: List[str] = Field(default_factory=list)
    prompt_wear_directive: str
    reference_image_path: Optional[str] = None
    shot_references: Dict[str, str] = Field(default_factory=dict)

class EnvironmentSetting(BaseModel):
    """An architectural 3D environment setting with spatial anchors and lighting."""
    env_id: str
    name: str
    archetype: ProductArchetype
    location_type: str  # "interior", "exterior", "studio_cyclorama"
    nominal_color_temp_kelvin: int
    lighting_contract: LightingContract
    foreground_elements: List[str] = Field(default_factory=list)
    midground_elements: List[str] = Field(default_factory=list)
    background_elements: List[str] = Field(default_factory=list)
    prompt_set_directive: str


# ==============================================================================
# Director's Wardrobe Catalog (Pre-built industry-standard production wardrobe)
# ==============================================================================

WARDROBE_CATALOG: Dict[str, WardrobeItem] = {
    # 1. Fashion / Apparel: Evening Gala & Runway
    "costume_french_satin_dress": WardrobeItem(
        costume_id="costume_french_satin_dress",
        name="Đầm Dạ Hội Lụa Satin Pháp Grace Noir",
        archetype=ProductArchetype.FASHION_APPAREL,
        style=CostumeStyle.HAUTE_COUTURE,
        color_palette=["Midnight Noir Black", "Liquid Gold Accents"],
        fabric_materials=["High-grade French mulberry satin silk with luminous sheen"],
        garment_description=(
            "Floor-length black silk satin evening gown with an elegant high asymmetrical leg slit, "
            "bias-cut contouring that hugs the waist, cowl neckline, and a subtle sweeping mini-train."
        ),
        hair_styling="Sleek polished chignon bun with delicate face-framing tendrils",
        accessories=["Minimalist platinum drop earrings", "Thin strappy metallic stiletto heels"],
        prompt_wear_directive=(
            "WEAR: Wearing an exquisite haute-couture midnight noir French satin silk evening gown with "
            "asymmetrical high leg slit, fluid bias-cut drape, elegant neckline, sleek polished chignon hair, "
            "minimalist platinum jewelry, editorial Parisian gala fashion standard."
        ),
        reference_image_path="assets/wardrobe/fashion_french_dress/01_wide_runway.jpg",
        shot_references={
            "shot_01": "assets/wardrobe/fashion_french_dress/01_wide_runway.jpg",
            "shot_02": "assets/wardrobe/fashion_french_dress/02_cowboy_reveal.jpg",
            "shot_03": "assets/wardrobe/fashion_french_dress/03_fabric_macro.jpg",
            "shot_04": "assets/wardrobe/fashion_french_dress/04_movement_walk.jpg",
            "shot_05": "assets/wardrobe/fashion_french_dress/05_styling_versatility.jpg",
            "shot_06": "assets/wardrobe/fashion_french_dress/06_cta_closer.jpg",
        },
    ),
    # 1b. Fashion / Apparel: French Vintage Cherry Dress
    "costume_french_cherry_dress": WardrobeItem(
        costume_id="costume_french_cherry_dress",
        name="Đầm Xòe Nơ Quả Cherry Vintage Kiểu Pháp",
        archetype=ProductArchetype.FASHION_APPAREL,
        style=CostumeStyle.SMART_CASUAL,
        color_palette=["Ivory Cream", "Cherry Scarlet Red", "Emerald Leaf Green"],
        fabric_materials=["Textured embossed waffle cotton-jacquard, silk satin ribbon ties"],
        garment_description=(
            "French vintage coquette A-line sundress in textured cream fabric with charming ripe red cherry print, "
            "corseted sweetheart bustier neckline, cinched waist, flowing flare pleated skirt, and delicate scarlet red ribbon shoulder ties."
        ),
        hair_styling="Soft romantic French wavy curls with delicate red ribbon bow",
        accessories=["Dainty pearl cherry necklace", "Mini woven straw picnic basket bag", "Red mary jane heels"],
        prompt_wear_directive=(
            "WEAR: Wearing French vintage coquette A-line sundress in textured cream waffle fabric with charming red cherry print, "
            "corseted sweetheart bustier neckline, cinched waist, flowing flare pleated skirt, and delicate scarlet red ribbon tie shoulder straps, "
            "romantic French soft wavy hair, delicate pearl-cherry accessories, Parisian summer picnic chic."
        ),
        reference_image_path="assets/wardrobe/fashion_cherry_dress/01_hero_cherry_dress.jpg",
        shot_references={
            "shot_01": "assets/wardrobe/fashion_cherry_dress/01_wide_runway.jpg",
            "shot_02": "assets/wardrobe/fashion_cherry_dress/02_cowboy_reveal.jpg",
            "shot_03": "assets/wardrobe/fashion_cherry_dress/03_fabric_macro.jpg",
            "shot_04": "assets/wardrobe/fashion_cherry_dress/04_movement_walk.jpg",
            "shot_05": "assets/wardrobe/fashion_cherry_dress/05_styling_versatility.jpg",
            "shot_06": "assets/wardrobe/fashion_cherry_dress/06_cta_closer.jpg",
        },
    ),

    # 2. Tech / Gadgets: Cyberpunk & Creative Studio
    "costume_techwear_minimalist": WardrobeItem(
        costume_id="costume_techwear_minimalist",
        name="Set Techwear Tối Giản Đen Nhám",
        archetype=ProductArchetype.TECH_GADGETS,
        style=CostumeStyle.TECHWEAR,
        color_palette=["Matte Obsidian", "Graphite Grey", "Subtle Cyan Accent"],
        fabric_materials=["Water-resistant ripstop tech fabric, bonded cotton jersey"],
        garment_description=(
            "Sleek architectural techwear zip hoodie in matte obsidian black over a fitted charcoal crewneck, "
            "clean tapered technical trousers with concealed zip pockets, ultra-modern creator aesthetic."
        ),
        hair_styling="Modern textured crop / neat low ponytail with clean undercut lines",
        accessories=["Titanium cybernetic smartwatch", "Matte black wireless in-ear monitors"],
        prompt_wear_directive=(
            "WEAR: Wearing modern minimalist obsidian black designer techwear hoodie, clean architectural tailoring, "
            "fitted charcoal base, titanium smartwatch on wrist, sleek contemporary creative technologist look."
        ),
        reference_image_path="assets/wardrobe/tech_hoodie.png",
    ),

    # 3. Beauty / Skincare: Minimalist Clean Girl & Spa
    "costume_minimalist_spa_silk": WardrobeItem(
        costume_id="costume_minimalist_spa_silk",
        name="Áo Choàng Lụa Trắng Sữa Spa Tối Giản",
        archetype=ProductArchetype.BEAUTY_SKINCARE,
        style=CostumeStyle.MINIMALIST_SPA,
        color_palette=["Pearl White", "Soft Warm Ivory"],
        fabric_materials=["Pure 100% natural Mulberry silk, soft waffle-weave trim"],
        garment_description=(
            "Relaxed luxury pearl white silk spa wrap robe, wide kimono sleeves, delicate tied waist sash, "
            "revealing graceful collarbones and glowing bare shoulders for skincare demonstration."
        ),
        hair_styling="Soft effortless claw clip updo with gentle sunlit wisps around face",
        accessories=["Bare skin aesthetic, zero chunky jewelry, natural healthy lip gloss"],
        prompt_wear_directive=(
            "WEAR: Wearing relaxed luxury pearl-white silk wrap robe with loose kimono sleeves, dewy bare shoulders "
            "and collarbones, effortless hair claw clip updo, glowing healthy glass-skin skincare aesthetic."
        ),
        reference_image_path="assets/wardrobe/beauty_spa_robe.png",
    ),

    # 4. Home / Lifestyle: Cozy Scandinavian Knits
    "costume_cozy_nordic_knit": WardrobeItem(
        costume_id="costume_cozy_nordic_knit",
        name="Áo Len Cashmere Dệt Kim Ấm Áp",
        archetype=ProductArchetype.HOME_LIFESTYLE,
        style=CostumeStyle.COZY_HOMELIVING,
        color_palette=["Oatmeal Cream", "Warm Biscuit", "Heather Grey"],
        fabric_materials=["Chunky ribbed 100% pure cashmere yarn, soft brushed wool"],
        garment_description=(
            "Oversized chunky knit oatmeal cashmere sweater with rolled cuffs and slouchy crewneck, "
            "paired with relaxed cream linen lounge pants, warm domestic comfort."
        ),
        hair_styling="Casual half-up messy bun, soft natural texture",
        accessories=["Ceramic handcrafted ring, warm woolen indoor socks"],
        prompt_wear_directive=(
            "WEAR: Wearing cozy oversized oatmeal cashmere knit sweater with chunky ribbed cuffs, relaxed cream "
            "linen trousers, casual natural messy bun, warm comforting home sanctuary aesthetic."
        ),
        reference_image_path="assets/wardrobe/cozy_knitwear.png",
    ),

    # 5. General Commercial / Direct Response: Executive Presenter
    "costume_executive_blazer": WardrobeItem(
        costume_id="costume_executive_blazer",
        name="Blazer Công Sở Thanh Lịch Cao Cấp",
        archetype=ProductArchetype.GENERAL_COMMERCIAL,
        style=CostumeStyle.LUXURY_EXECUTIVE,
        color_palette=["Deep Slate Grey", "Crisp White", "Brushed Brass"],
        fabric_materials=["Italian virgin wool blend, silk lining"],
        garment_description=(
            "Sharp tailored single-breasted blazer in slate grey over an elegant silk-chiffon camisole, "
            "structured power shoulders with slim notched lapels, confident professional demeanor."
        ),
        hair_styling="Polished shoulder-length blowout with soft inward curl",
        accessories=["Brushed gold minimal watch, subtle geometric stud earrings"],
        prompt_wear_directive=(
            "WEAR: Wearing tailored slate-grey designer executive blazer, crisp silk inner camisole, structured "
            "sharp tailoring, polished shoulder-length blowout, minimalist gold watch, high-trust presenter aesthetic."
        ),
        reference_image_path="assets/wardrobe/executive_blazer.png",
    ),
}


# ==============================================================================
# Director's Environment Catalog (Photorealistic Staging Sets)
# ==============================================================================

ENVIRONMENT_CATALOG: Dict[str, EnvironmentSetting] = {
    # 1. Fashion Gala Ballroom & High-End Runway
    "env_paris_ballroom": EnvironmentSetting(
        env_id="env_paris_ballroom",
        name="Sảnh Tiệc Gala Đèn Chùm Paris Grand Palais",
        archetype=ProductArchetype.FASHION_APPAREL,
        location_type="interior",
        nominal_color_temp_kelvin=5000,
        lighting_contract=LightingContract.EDITORIAL_FASHION,
        foreground_elements=["Polished dark marble floor with glossy light reflections"],
        midground_elements=["Runway red-carpet stage, architectural Corinthian marble pillars"],
        background_elements=["Massive arched palace glass windows overlooking Paris evening skyline, warm crystal chandeliers"],
        prompt_set_directive=(
            "SET: Grand Parisian luxury palace ballroom at twilight, glossy black marble floor reflecting warm amber "
            "crystal chandeliers, soaring Corinthian columns, grand arched French windows overlooking city twilight, "
            "editorial fashion event staging with crisp 5000K rim lighting."
        ),
    ),
    # 1b. Parisian Cafe Terrace & Haussmann Street
    "env_paris_cafe_terrace": EnvironmentSetting(
        env_id="env_paris_cafe_terrace",
        name="Góc Quán Cà Phê & Ban Công Paris Buổi Sáng",
        archetype=ProductArchetype.FASHION_APPAREL,
        location_type="exterior",
        nominal_color_temp_kelvin=5200,
        lighting_contract=LightingContract.GOLDEN_HOUR,
        foreground_elements=["Sunlit cobblestone street, wrought-iron bistro chair with fresh basket of cherries"],
        midground_elements=["Parisian cafe terrace with striped awning, limestone Haussmann building facade"],
        background_elements=["Classic Parisian architecture, soft morning sunlight filtering through summer plane trees"],
        prompt_set_directive=(
            "SET: Sun-drenched Parisian cafe terrace on cobblestone street, warm natural golden morning sunlight (5200K), "
            "wrought-iron bistro table with fresh cherries, soft cinematic bokeh, romantic French summer street ambiance."
        ),
    ),

    # 2. Tech / Gadgets: Cyberpunk Battle-Station & Creator Studio
    "env_cyberpunk_desk": EnvironmentSetting(
        env_id="env_cyberpunk_desk",
        name="Phòng Studio Công Nghệ Cyberpunk & Bàn Gỗ Tối Giản",
        archetype=ProductArchetype.TECH_GADGETS,
        location_type="interior",
        nominal_color_temp_kelvin=5500,
        lighting_contract=LightingContract.STUDIO_3POINT,
        foreground_elements=["Dark walnut wooden desk surface with frosted desk mat"],
        midground_elements=["Minimalist ultrawide monitor with ambient backlight, custom mechanical keyboard resting center"],
        background_elements=["Acoustic slat wooden wall panels, subtle dual-tone cyan and amber LED edge wash lights"],
        prompt_set_directive=(
            "SET: Modern high-end creator desk setup, solid dark walnut tabletop, matte acoustic felt desk pad, "
            "ambient curved monitor glow in background, architectural dark acoustic wood slat wall, clean 5500K studio "
            "diffused softbox key light with subtle cyan edge separation."
        ),
    ),

    # 3. Beauty / Skincare: Minimalist Sunlit Marble Penthouse Bath
    "env_minimalist_marble_bath": EnvironmentSetting(
        env_id="env_minimalist_marble_bath",
        name="Phòng Tắm Penthouse Đá Cẩm Thạch Ngập Tràn Ánh Sáng",
        archetype=ProductArchetype.BEAUTY_SKINCARE,
        location_type="interior",
        nominal_color_temp_kelvin=5600,
        lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
        foreground_elements=["Flawless white Calacatta marble countertop with delicate grey veining, crystal water dish"],
        midground_elements=["Frameless circular LED vanity mirror with soft diffused illumination"],
        background_elements=["Floor-to-ceiling frosted glass bathroom windows with bright morning daylight, lush potted eucalyptus"],
        prompt_set_directive=(
            "SET: Ultra-luxury minimalist penthouse bathroom, white Calacatta gold marble countertops, soft glowing circular "
            "vanity mirror, floor-to-ceiling window bay casting bright 5600K diffused morning natural daylight, pure pristine spa ambiance."
        ),
    ),

    # 4. Home / Lifestyle: Scandinavian Sunlit Living Sanctuary
    "env_nordic_kitchen": EnvironmentSetting(
        env_id="env_nordic_kitchen",
        name="Căn Hộ Bắc Âu Gỗ Sồi Ấm Áp Buổi Sáng",
        archetype=ProductArchetype.HOME_LIFESTYLE,
        location_type="interior",
        nominal_color_temp_kelvin=3200,
        lighting_contract=LightingContract.GOLDEN_HOUR,
        foreground_elements=["Solid white oak dining table with linen runner, ceramic mug"],
        midground_elements=["Sheer cream linen curtains billowing gently in light breeze"],
        background_elements=["Sun-drenched living room with Monstera plant, soft textured rug, warm Scandinavian oak shelves"],
        prompt_set_directive=(
            "SET: Sunlit Scandinavian modern apartment living room, warm natural white oak furniture, soft sheer linen curtains, "
            "golden morning sunbeams (3200K) casting volumetric dust rays across the room, peaceful domestic sanctuary."
        ),
    ),

    # 5. General Commercial: High-Rise Executive Studio
    "env_studio_infinity_cyclorama": EnvironmentSetting(
        env_id="env_studio_infinity_cyclorama",
        name="Studio Phim Trường Cao Cấp Chuẩn Thương Mại",
        archetype=ProductArchetype.GENERAL_COMMERCIAL,
        location_type="studio_cyclorama",
        nominal_color_temp_kelvin=5500,
        lighting_contract=LightingContract.STUDIO_3POINT,
        foreground_elements=["Clean reflective glossy presentation pedestal"],
        midground_elements=["Presenter standing confidently beside hero product"],
        background_elements=["Seamless neutral gradient cyclorama wall, calibrated studio light grids overhead"],
        prompt_set_directive=(
            "SET: Premium commercial broadcast studio, seamless neutral grey cyclorama backdrop, calibrated 3-point 5500K "
            "softbox lighting, glossy reflection stage pedestal, tack-sharp commercial commercial advertising finish."
        ),
    ),
}


# ==============================================================================
# Director Resolution Gateway
# ==============================================================================

def resolve_wardrobe_and_environment(
    archetype: ProductArchetype,
    custom_costume_id: Optional[str] = None,
    custom_env_id: Optional[str] = None,
) -> tuple[WardrobeItem, EnvironmentSetting]:
    """Resolves the authoritative wardrobe outfit and environment setting for an archetype."""
    # 1. Resolve Wardrobe
    if custom_costume_id and custom_costume_id in WARDROBE_CATALOG:
        wardrobe = WARDROBE_CATALOG[custom_costume_id]
    else:
        # Match by archetype
        archetype_map = {
            ProductArchetype.FASHION_APPAREL: "costume_french_satin_dress",
            ProductArchetype.TECH_GADGETS: "costume_techwear_minimalist",
            ProductArchetype.BEAUTY_SKINCARE: "costume_minimalist_spa_silk",
            ProductArchetype.HOME_LIFESTYLE: "costume_cozy_nordic_knit",
            ProductArchetype.GENERAL_COMMERCIAL: "costume_executive_blazer",
        }
        costume_key = archetype_map.get(archetype, "costume_executive_blazer")
        wardrobe = WARDROBE_CATALOG[costume_key]

    # 2. Resolve Environment
    if custom_env_id and custom_env_id in ENVIRONMENT_CATALOG:
        environment = ENVIRONMENT_CATALOG[custom_env_id]
    else:
        env_map = {
            ProductArchetype.FASHION_APPAREL: "env_paris_ballroom",
            ProductArchetype.TECH_GADGETS: "env_cyberpunk_desk",
            ProductArchetype.BEAUTY_SKINCARE: "env_minimalist_marble_bath",
            ProductArchetype.HOME_LIFESTYLE: "env_nordic_kitchen",
            ProductArchetype.GENERAL_COMMERCIAL: "env_studio_infinity_cyclorama",
        }
        env_key = env_map.get(archetype, "env_studio_infinity_cyclorama")
        environment = ENVIRONMENT_CATALOG[env_key]

    return wardrobe, environment
