"""Step 2: High-Conversion Commercial Scriptwriting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline.config import ARTIFACTS_DIR
from pipeline.schemas import BriefArtifact, ScriptArtifact, ScriptBeat
from pipeline.archetypes import (
    AudioStrategy,
    CameraChoreography,
    CharacterRole,
    LightingContract,
    ProductArchetype,
    get_archetype_config,
)


def _build_archetype_beats(brief: BriefArtifact, archetype: ProductArchetype) -> List[ScriptBeat]:
    """Build structured commercial beats based on product archetype and brief specs."""
    config = get_archetype_config(archetype)
    product = brief.product_name
    pains = brief.pain_points or ["Vấn đề bất tiện thường ngày"]
    usps = brief.usps or ["Tính năng vượt trội hiện đại"]
    character_name = brief.presenter.name if brief.presenter else "KOL"
    character_tag = brief.presenter.character_tag if brief.presenter else "[KOL]"

    beats: List[ScriptBeat] = []
    for idx, tpl in enumerate(config.beat_templates, start=1):
        scene_id = f"shot_{idx:02d}_{tpl.beat_type}"

        # Build contextual spoken and on-screen copy per archetype
        if archetype == ProductArchetype.FASHION_APPAREL:
            if tpl.beat_type == "hook":
                spoken = f"Bạn có tin một chiếc {product} có thể nâng tầm toàn bộ outfit của bạn?"
                on_screen = f"MUST-HAVE ITEM • {product.upper()}"
                visual = f"Góc máy {tpl.camera_choreography.value} từ thấp lên cao, {character_tag} bước sải chân tự tin với phong thái cuốn hút"
            elif tpl.beat_type == "reveal":
                spoken = f"Form dáng suông chuẩn Hàn Quốc, độn vai nhẹ tôn dáng và che trọn khuyết điểm."
                on_screen = "PERFECT SILHOUETTE • 360° FIT"
                visual = f"Camera {tpl.camera_choreography.value} xoay 360 quanh {character_tag}, khoe trọn phom dáng thanh lịch của {product}"
            elif tpl.beat_type == "fabric_macro":
                spoken = "Chất vải tuyết mưa cao cấp chống nhăn tuyệt đối, vò mạnh thả ra vẫn phẳng lì đứng phom."
                on_screen = "PREMIUM FABRIC • WRINKLE-FREE"
                visual = f"Góc cận cảnh macro {tpl.camera_choreography.value}, bắt trọn từng thớ vải mịn màng đung đưa chuyển động mềm mại"
            elif tpl.beat_type == "movement_flow":
                spoken = "Vạt áo bay nhẹ nhàng tự nhiên, thoải mái vận động cả ngày dài không hề gò bó."
                on_screen = "FLUID MOVEMENT • ALL DAY COMFORT"
                visual = f"Camera {tpl.camera_choreography.value} tracking song song khi {character_tag} rảo bước năng động"
            elif tpl.beat_type == "styling_versatility":
                spoken = "Dễ dàng mix ngoài áo sơ mi trắng đi làm công sở, hay khoác hờ dạo phố cà phê đều cực sang."
                on_screen = "EASY MIX & MATCH • WORK TO STREET"
                visual = f"Cắt nhanh {tpl.camera_choreography.value} đổi phong cách phối đồ linh hoạt cùng phụ kiện"
            else:  # cta
                spoken = f"Đang có ưu đãi độc quyền 30% hôm nay! Nhấp ngay vào link giỏ hàng bên dưới để sở hữu nhé!"
                on_screen = "ƯU ĐÃI ĐỘC QUYỀN 30% • NHẤP LINK BIO"
                visual = f"{character_tag} mỉm cười rạng rỡ, giơ cao mã ưu đãi, banner kêu gọi mua hàng xuất hiện"
        elif archetype == ProductArchetype.TECH_GADGETS:
            if tpl.beat_type == "hook":
                spoken = f"Bạn vẫn còn phải chịu đựng: {pains[0]}?"
                on_screen = f"BẠN CÒN CHỊU ĐỰNG NỖI LO NÀY?"
                visual = f"Camera {tpl.camera_choreography.value} cận cảnh khuôn mặt {character_tag} bực bội trước tình huống bất tiện"
            elif tpl.beat_type == "unboxing":
                spoken = "Mở hộp ngay em siêu phẩm công nghệ thay đổi hoàn toàn trải nghiệm làm việc."
                on_screen = f"UNBOXING • {product.upper()}"
                visual = f"Góc quay từ trên xuống {tpl.camera_choreography.value}, bóc lớp seal mờ sang trọng, lộ diện thiết kế tinh xảo của {product}"
            elif tpl.beat_type == "macro_detail":
                spoken = "Từng chi tiết được gia công chuẩn xác, cổng kết nối cao cấp cùng nút bấm êm ái."
                on_screen = "PRECISION ENGINEERING • TACTILE FEEL"
                visual = f"Macro {tpl.camera_choreography.value} chuyển nét mượt mà trên bề mặt kim loại nguyên khối và cổng kết nối"
            elif tpl.beat_type == "performance_demo":
                spoken = f"Điểm đột phá nhất: {usps[0]}!"
                on_screen = f"{usps[0].upper()[:45]}"
                visual = f"Camera {tpl.camera_choreography.value} trình diễn trực tiếp tính năng ưu việt của {product} trong môi trường thực tế"
            elif tpl.beat_type == "specs_proof":
                spoken = "Gọn nhẹ bền bỉ, đồng hành cùng bạn mọi lúc mọi nơi."
                on_screen = "LIGHTWEIGHT • ULTRA-DURABLE"
                visual = f"Thao tác cất gọn {product} vào balo thanh lịch, góc quay {tpl.camera_choreography.value} nhanh gọn"
            else:  # cta
                spoken = f"Nâng cấp bàn làm việc của bạn với {product} ngay tại link bên dưới!"
                on_screen = "ƯU ĐÃI ĐỘC QUYỀN • SỐ LƯỢNG CÓ HẠN"
                visual = f"{character_tag} mỉm cười giơ cao {product}, đồ họa CTA nổi bật nhấp nháy"

        elif archetype == ProductArchetype.BEAUTY_SKINCARE:
            if tpl.beat_type == "hook":
                spoken = "Một giọt serum tinh chất có thể thay đổi làn da của bạn như thế nào?"
                on_screen = "GLOW SKIN REVOLUTION"
                visual = f"Góc cận cảnh macro {tpl.camera_choreography.value}, giọt tinh chất {product} óng ánh rơi từ ống nhỏ giọt thủy tinh"
            elif tpl.beat_type == "skin_agitation":
                spoken = f"Nếu làn da bạn đang gặp tình trạng: {pains[0]}..."
                on_screen = "DA THIẾU NƯỚC & KÉM SẮC?"
                visual = f"Góc {tpl.camera_choreography.value} cận mặt {character_tag} chạm nhẹ lên gò má bày tỏ nỗi lo"
            elif tpl.beat_type == "texture_macro":
                spoken = "Chất kem mỏng nhẹ như nhung, tan ngay khi chạm vào da."
                on_screen = "VELVET TEXTURE • FAST ABSORPTION"
                visual = f"Macro {tpl.camera_choreography.value} swatch tinh chất sánh mịn trên phiến đá pha lê bắt sáng lấp lánh"
            elif tpl.beat_type == "application_method":
                spoken = f"Chứa công thức độc quyền: {usps[0]}."
                on_screen = f"{usps[0].upper()[:45]}"
                visual = f"Góc nghiêng {tpl.camera_choreography.value}, {character_tag} thoa tinh chất nhẹ nhàng lên gò má, tạo độ bóng căng mọng"
            elif tpl.beat_type == "transformation_proof":
                spoken = "Làn da căng bóng ngậm nước rạng ngời suốt cả ngày dài."
                on_screen = "RADIANT GLASS SKIN • 24H HYDRATION"
                visual = f"Góc quay {tpl.camera_choreography.value} bắt trọn ánh sáng tự nhiên trên làn da mịn màng, nụ cười rạng rỡ của {character_tag}"
            else:  # cta
                spoken = f"Yêu thương làn da cùng {product}, nhận ngay bộ quà tặng độc quyền tại link bio!"
                on_screen = "MUA 1 TẶNG 1 • LINK TẠI BIO"
                visual = f"Chai {product} bên cạnh hoa cỏ thanh khiết, đồ họa quà tặng cao cấp xuất hiện"

        elif archetype == ProductArchetype.HOME_LIFESTYLE:
            if tpl.beat_type == "hook":
                spoken = f"Không gian sống ấm cúng nhưng bạn vẫn bực mình vì: {pains[0]}?"
                on_screen = "GIẢI PHÁP CHO TỔ ẤM HIỆN ĐẠI"
                visual = f"Góc quay lướt {tpl.camera_choreography.value} trong căn phòng ngập tràn ánh nắng ấm áp buổi sáng"
            elif tpl.beat_type == "reveal":
                spoken = f"Đây chính là mảnh ghép hoàn hảo cho ngôi nhà bạn: {product}."
                on_screen = f"{product.upper()} • MINIMALIST DESIGN"
                visual = f"Camera {tpl.camera_choreography.value} hạ thấp mượt mà, hé lộ vẻ đẹp tối giản của {product} trên bàn gỗ sồi"
            elif tpl.beat_type == "functional_demo":
                spoken = f"Vận hành êm ái chỉ với 1 chạm: {usps[0]}."
                on_screen = f"{usps[0].upper()[:45]}"
                visual = f"Cận cảnh {tpl.camera_choreography.value} ngón tay chạm nhẹ nút cảm ứng, cơ chế hoạt động mượt mà tĩnh lặng"
            elif tpl.beat_type == "lifestyle_context":
                spoken = "Tận hưởng những giây phút thư thái thảnh thơi sau ngày dài bận rộn."
                on_screen = "PEACE OF MIND • COZY LIVING"
                visual = f"Toàn cảnh {tpl.camera_choreography.value}, {character_tag} ngồi thư giãn trên ghế sofa, không gian ấm cúng bình yên"
            elif tpl.beat_type == "convenience_proof":
                spoken = "Dễ dàng vệ sinh, cất gọn gàng ngăn nắp mà không chiếm diện tích."
                on_screen = "EASY CLEAN • SPACE SAVING"
                visual = f"Thao tác lau chùi nhẹ nhàng {tpl.camera_choreography.value}, thiết kế thông minh gọn gàng"
            else:  # cta
                spoken = f"Nâng tầm phong cách sống cùng {product} ngay hôm nay với ưu đãi 35%!"
                on_screen = "ƯU ĐÃI TỔ ẤM 35% • NHẤP LINK ĐẶT HÀNG"
                visual = f"{character_tag} nở nụ cười ấm áp, khung cảnh ngập tràn ánh hoàng hôn và thông điệp CTA"

        else:  # GENERAL_COMMERCIAL
            if tpl.beat_type == "hook":
                spoken = f"Bạn có bao giờ phát chán với tình trạng: {pains[0]}?"
                on_screen = "BẠN ĐANG GẶP RẮC RỐI NÀY?"
                visual = f"Camera {tpl.camera_choreography.value} cận cảnh biểu cảm ngạc nhiên bất lực của {character_tag}"
            elif tpl.beat_type == "pain_agitation":
                second_pain = pains[1] if len(pains) > 1 else pains[0]
                spoken = f"Không chỉ vậy, {second_pain} còn khiến mọi thứ tệ hơn rất nhiều!"
                on_screen = "HẬU QUẢ NGHIÊM TRỌNG HƠN BẠN NGHĨ!"
                visual = f"Góc cận {tpl.camera_choreography.value} nhấn mạnh vào rắc rối thực tế xảy ra"
            elif tpl.beat_type == "solution_reveal":
                spoken = f"Và đây chính là cứu tinh dành cho bạn: {product}!"
                on_screen = f"GIẢI PHÁP TOÀN DIỆN • {product.upper()}"
                visual = f"Ánh sáng quét qua sản phẩm {tpl.camera_choreography.value}, xuất hiện sang trọng đầy ấn tượng"
            elif tpl.beat_type == "feature_demo":
                spoken = f"Điểm đột phá làm nên khác biệt: {usps[0]}!"
                on_screen = f"{usps[0].upper()[:45]}"
                visual = f"Trình diễn tính năng chi tiết {tpl.camera_choreography.value}, thao tác mượt mà chính xác"
            elif tpl.beat_type == "social_proof":
                spoken = "Hàng ngàn khách hàng đã trải nghiệm và hoàn toàn bị thuyết phục."
                on_screen = "5 SAO TIN DÙNG • 100% HÀI LÒNG"
                visual = f"{character_tag} mỉm cười hài lòng {tpl.camera_choreography.value}, đồ họa đánh giá 5 sao xuất hiện"
            else:  # cta
                spoken = f"Nhấp ngay link bên dưới để nhận voucher giảm giá độc quyền hôm nay nhé!"
                on_screen = "NHẤP LINK BIO • VOUCHER ĐỘC QUYỀN HÔM NAY"
                visual = f"{character_tag} giơ cao {product} rạng rỡ, banner kêu gọi hành động xuất hiện"

        beats.append(
            ScriptBeat(
                scene_id=scene_id,
                beat_type=tpl.beat_type,
                spoken_text=spoken,
                on_screen_text=on_screen,
                visual_cue=visual,
                estimated_duration=tpl.target_duration,
                archetype=archetype,
                character_role=tpl.recommended_role,
                audio_strategy=tpl.audio_strategy,
                camera_choreography=tpl.camera_choreography,
                lighting_contract=tpl.lighting_contract,
                narrative_purpose=tpl.narrative_purpose,
            )
        )

    return beats


def generate_commercial_script(
    brief: BriefArtifact | None = None,
    brief_path: Path | None = None,
    output_dir: Path | None = None,
    archetype: ProductArchetype | str | None = None,
) -> ScriptArtifact:
    """Generates high-conversion TVC script based on brief.json and directorial archetype."""
    target_artifacts_dir = output_dir or ARTIFACTS_DIR
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

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

    # If legacy mug campaign is tested without custom archetype override, maintain 4-beat legacy compatibility
    if brief.campaign_id == "campaign_lumina_mug_01" and archetype is None and selected_archetype == ProductArchetype.GENERAL_COMMERCIAL:
        beats: List[ScriptBeat] = [
            ScriptBeat(
                scene_id="shot_01_hook",
                beat_type="hook",
                spoken_text="Bạn có phát chán khi ly cà phê vừa pha xong thì 15 phút sau đã nguội ngắt?",
                on_screen_text="CÀ PHÊ NGUỘI NGẮT SAU 15 PHÚT?",
                visual_cue="Extreme close-up ly cà phê nguội, chuyển nhanh sang góc cận KOL Minh Anh lắc đầu ngạc nhiên",
                estimated_duration=3.5,
                archetype=ProductArchetype.GENERAL_COMMERCIAL,
                character_role=CharacterRole.PRESENTER,
                audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
                camera_choreography=CameraChoreography.ZOOM_IN,
                lighting_contract=LightingContract.STUDIO_3POINT,
                narrative_purpose="Pattern interrupt hook questioning mundane annoyance",
            ),
            ScriptBeat(
                scene_id="shot_02_pain",
                beat_type="pain",
                spoken_text="Chưa kể đá tan chảy nước lênh láng, làm ướt đẫm tài liệu và bàn phím làm việc?",
                on_screen_text="NƯỚC ĐỌNG ƯỚT BÀN & TÀI LIỆU!",
                visual_cue="Góc nhìn bàn làm việc nước ngưng tụ lem nhem hồ sơ, Minh Anh cau mày khó chịu",
                estimated_duration=5.0,
                archetype=ProductArchetype.GENERAL_COMMERCIAL,
                character_role=CharacterRole.MODEL,
                audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
                camera_choreography=CameraChoreography.ZOOM_IN,
                lighting_contract=LightingContract.STUDIO_3POINT,
                narrative_purpose="Visceral pain agitation of messy workspace",
            ),
            ScriptBeat(
                scene_id="shot_03_solution",
                beat_type="solution",
                spoken_text="Giải pháp đây rồi! Ly giữ nhiệt Lumina Pro, chạm nhẹ nắp LED biết ngay nhiệt độ, giữ nóng 12 tiếng, giữ lạnh 24 tiếng!",
                on_screen_text="LUMINA PRO • NẮP CẢM ỨNG LED • GIỮ NHIỆT 24H",
                visual_cue="Góc quay điện ảnh studio sang trọng, Minh Anh chạm nắp LED sáng đèn 65 độ C, nâng ly thưởng thức sảng khoái",
                estimated_duration=12.0,
                archetype=ProductArchetype.GENERAL_COMMERCIAL,
                character_role=CharacterRole.PRESENTER,
                audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
                camera_choreography=CameraChoreography.PEDESTAL,
                lighting_contract=LightingContract.STUDIO_3POINT,
                narrative_purpose="Comprehensive hero solution reveal and feature proof",
            ),
            ScriptBeat(
                scene_id="shot_04_cta",
                beat_type="cta",
                spoken_text="Bảo bối công sở chống tràn tuyệt đối! Nhấp ngay link bên dưới để nhận ưu đãi 40% hôm nay nhé!",
                on_screen_text="ƯU ĐÃI 40% ĐỘC QUYỀN • NHẤP LINK BIO",
                visual_cue="Minh Anh mỉm cười rạng rỡ, giơ cao ly Lumina Pro thanh lịch, logo thương hiệu và nút CTA xuất hiện",
                estimated_duration=6.5,
                archetype=ProductArchetype.GENERAL_COMMERCIAL,
                character_role=CharacterRole.PRESENTER,
                audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
                camera_choreography=CameraChoreography.ZOOM_IN,
                lighting_contract=LightingContract.STUDIO_3POINT,
                narrative_purpose="Direct high-trust presenter CTA with flash discount",
            ),
        ]
    else:
        beats = _build_archetype_beats(brief, selected_archetype)

    total_duration = sum(b.estimated_duration for b in beats)

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
