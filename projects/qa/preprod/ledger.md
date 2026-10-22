# Sổ QA tiền kỳ (harness/preprod_qa_loop.md)

## Vòng 1 · xe đạp Thống Nhất MTB 26-02 · sinh viên năm nhất ở trọ · `projects/general_commercial/pp_r1/runs/v1`

Bẫy: mô tả shop "Shimano 21 tốc, khung nhôm, bảo hành 5 năm" (ảnh: một tốc). Bible mẫu cùng sản phẩm đã có ý "lên xe là đi".

### Lỗi theo bước
| Bước | Lần | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | 1 | trượt | bẫy shop xử lý đúng; nhưng 3 angle có segment chung chung dù audience có trong --url; hook "chờ chỉnh líp" là người rơm; split-screen + timer (so sánh ngầm); controlling idea trùng bible mẫu; arc = tour bộ phận; pain_points là câu hỏi sản phẩm; omp edit tay brief.json/creative_concept.json |
| 1 | 2 | đạt có điều kiện | audience đúng, hook 'tháng đầu ở trọ', tính năng trong hành động; nhưng key_visual (hoàng hôn tan ca) không có trong mạch; claim ngầm độ bền ('lỡ dở giữa đường', 'vững vàng'); 'phanh... kiểm soát an toàn'; cảnh xe máy rẽ ngang; VO/caption bảng kê. Inject bằng Python API |
| 2 | 1 | trượt | 7 beat 25s toàn presenter/on_camera_speech kể cả cận lốp/phuộc (không thể lip-sync); lighting mâu thuẫn (nordic cho ngõ, editorial cho phố, golden_hour lúc 11h45) – gốc: enum thiếu ánh sáng ban ngày; truck ×5; không có xung đột thật; VO "lên xe là đạp" khi đang dắt xe; mũ bảo hiểm xuất hiện không thiết lập; caption lặp VO; CTA "MTB 26-02" khó đọc TTS. Lint mới bắt 3/9 lỗi tự động |
| 2 | 2 | đạt có điều kiện | vai/audio đúng (2 presenter: hook, CTA), 1 bối cảnh = 1 lighting, key visual ở shot_06; còn claim phóng đại "êm ru/bám chắc/sạch tinh", hook than phiền khi đứng yên, mũ thiếu ở shot_02, shot_06 hai tay mâu thuẫn |
| 2 | 3 | đạt | hook "Sáng học trưa làm, tự lo thế nào?" (9 âm tiết), claim chỉ nêu đặc điểm |
| 3 | 1 | gần đạt | omp dùng set/wear_direction đúng (ngõ trọ, phố, quán; đồ sinh viên); lỗi pipeline: mọi motion prompt "She speaks to camera" (cả product_only), ảnh tĩnh có "orbit"/"jaw and lip movements", vai model bị chèn "Direct eye contact", R2V chỉ gửi mặt + prompt chỉ-chuyển-động = mất cảnh và xe; lỗi kịch bản: visual_cue_en có từ máy quay/ánh sáng và chuỗi "then", mũ shot_07 sau khi tháo ở shot_06 |

### Sửa tầng 2 (giữa vòng)
| File | Sửa | Test |
|---|---|---|
| tools/prompt_pack.py (mới), pipeline/identity_keyframe.py (`plan_synthesis_references`) | gói prompt ảnh/video đúng như Stage 4/5 sẽ gửi, offline, có lint | tests/test_prompt_pack.py (4) |
| pipeline/cinematography.py, storyboard.py, schemas.py, video_engine.py, script_llm.py | `motion_prompt` (lệnh Hailuo + chuyển động) tách khỏi `prompt_6part`; `motion_cue_en` bắt buộc ở LLM; override `camera_command`, `motion_direction`; Stage 5 gửi `video_prompt_for(shot)` | test_storyboard_planning (2), test_script_llm (1) |
| assets/characters/kol_main/character.json, archetypes.py | face_prompt bỏ "studio portrait lighting, 8k" (ánh sáng thuộc cảnh) | lint prompt_pack |
| pipeline/researcher.py, director.py, tools/director.py | `--audience` cố định khán giả; concept có `controlling_idea`, `key_visual`; luật: không người rơm, không so sánh/split-screen/timer, tính năng chứng minh trong hành động | test_researcher (2) |
| pipeline/workspace.py | `--inject creative_concept` | test_workspace (1) |
| harness/tool_guidance.md | prompt_pack, --audience, cấm edit tay artifacts | — |

Báo động giả tự sửa: lint "3200K + early sunlight" sai (giờ vàng ~3200K thật), đã thu hẹp lint.
| tools/director.py | `--inject X --pause-after-stage <stage của X>` = cài rồi dừng (exit 4) thay vì exit 2 sau khi đã cài | test_director_contract (1) |
| harness/preprod_qa_loop.md, qa_loop_prompt.md | omp nền phải `< /dev/null` (treo readPipedInput 30') | — |
| pipeline/archetypes.py, spatial_staging.py, cinematography.py | LightingContract `natural_daylight` 5600K, `overcast_soft` 6500K | test_spatial_staging |
| pipeline/storyboard.py | Kelvin theo lighting của beat (không lấy 3200K của phòng mặc định); thêm câu `LIGHT:` khi lighting beat khác bối cảnh (SET: chứa sẵn ánh sáng mặc định, dòng Lighting: bị nén bỏ) | test_storyboard_planning (1) |
| pipeline/archetypes.py | bỏ "8k", "studio portrait quality" khỏi DynamicPromptBuilder | test_archetypes |
| pipeline/scriptwriter.py, workspace.py | `shot_language_issues`: on_camera_speech không có mặt người, golden_hour lúc trưa/âm u/mưa; chạy trong validate_script và chặn khi `--inject script` | test_director_contract (1), fixture test_script_llm sửa |
| pipeline/script_llm.py | luật vai/âm thanh theo khung hình và lighting theo giờ/địa điểm trong SYSTEM_PROMPT | test_script_llm |
| pipeline/storyboard.py, harness/tool_guidance.md | override `wear_direction` (general_commercial mặc định blazer) | test_storyboard_planning (1) |
| pipeline/video_engine.py | `video_prompt_for(shot, kf)`: R2V (không có first frame) nhận motion + câu hành động/SET/LIGHT/WEAR; sửa hồi quy do tách motion_prompt | test_prompt_pack (1) |
| pipeline/identity_keyframe.py | `still_frame_prompt`: prompt ảnh tĩnh bỏ câu chuyển động máy, đổi khẩu hình thành "lips softly parted mid-word" | test_prompt_pack (1), test_identity_keyframe sửa |
| pipeline/storyboard.py | "speaks to camera" chỉ khi on_camera_speech | test_storyboard_planning (1) |
| pipeline/archetypes.py | vai model: bỏ chỉ dẫn presenter (eye contact), "Commercial lifestyle video" | — |
| pipeline/storyboard.py, identity_keyframe.py, tool_guidance.md | override `generation_mode` i2v/r2v (ADR 0008 giữ mặc định model=R2V) | test_storyboard_planning (1) |
| tools/prompt_pack.py | mirror R2V prompt; lint `video_person_in_product_shot`, `image_camera_move`, `r2v_without_product_reference` | test_prompt_pack |
| pipeline/script_llm.py | visual_cue_en = first frame đứng yên, không từ máy quay/ánh sáng/"then" | — |
| pipeline/director.py | resume không ghi đè title project bằng tên sản phẩm mặc định CLI | test_director_contract (1) |

Đề xuất cần người quyết (ADR): ADR 0008 định tuyến model → R2V S2V-01 (chỉ nhận mặt) trong khi Stage 4 vẫn tổng hợp first frame cho shot đó và First-frame gate bắt buộc frame này → trả tiền ảnh không dùng, sản phẩm vẽ lại từ chữ. Đề xuất: model mặc định I2V từ frame tổng hợp, R2V khi cần chuyển động thân thể mạnh và sản phẩm không chiếm khung.

### Kết vòng 1
| Bước | Lần | Kết quả | Bằng chứng |
|---|---|---|---|
| 3 | 2 | đạt có điều kiện | 0 lint; visual_cue_en là frame đứng yên; mũ shot_07 đúng; 3 shot model chọn i2v (xe chiếm khung). Còn shot_05 frame = trạng thái kết thúc, tour tính năng 3–4–5 |
| 3 | 3 | đạt | shot_05 mở→kết đúng; shot_04 thành cảnh model (giày/quần sạch cạnh chắn bùn); clip_heavily_trimmed ×3 chấp nhận (Hailuo tối thiểu 6s, hành động dồn đầu clip) |

Điểm: Quy trình 8 · Brief&concept 8.5 · Kịch bản 8.5 · Storyboard 8.5 · Prompt ảnh 8.5 · Prompt video 8.5 · Tuân thủ 9 · Sáng tạo 8 → TB 8.44. Có sửa tầng 2 trong vòng → vòng không tính đạt.

Sửa tầng 2 cuối vòng 1: lint `clip_heavily_trimmed`; luật motion_cue_en bắt đầu TỪ frame đầu và dồn hành động lên đầu; LightingContract `practical_night` (4000K) + lint đêm vs daylight (chuẩn bị vòng 2, cảnh đêm không có contract phù hợp).

## Vòng 2 · đèn bàn LED acrylic đế gỗ · tech_gadgets · nhân viên văn phòng căn hộ studio · đêm · `projects/tech_gadgets/pp_r2/runs/v1`
Biến đổi so với vòng 1: sản phẩm, archetype, khán giả, thời điểm (đêm, đèn thực tế), tỉ lệ âm thanh (≤1 beat nói), thời lượng 15–20s.
Bẫy: mô tả shop "chống cận thị, bảo vệ mắt 100%, chuẩn y khoa, pin 20 giờ, cảm ứng 3 chế độ, giảm 50%" (ảnh: dây USB, không thấy nút); ảnh hero có nền phòng ban ngày (không được copy nền/ánh sáng).

| Bước | Lần | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | 1 | đạt | bẫy shop xử lý từng ý (chống cận/bảo vệ mắt/chuẩn y khoa, pin 20h vs dây USB trong ảnh, cảm ứng, giảm 50%); --audience giữ khán giả ở cả 3 angle; hook hình ASMR cắm USB → đèn bừng sáng; practical_night. Nhỏ: "tập trung tuyệt đối", "ánh sáng trắng ấm áp", angle A "thay đèn cũ cồng kềnh" (so sánh ngầm, không được chọn). Inject qua CLI đúng chuẩn |
| 2 | 1 | đạt có điều kiện | 17.5s, trước/sau, ASMR, 1 beat nói, practical_night, claim bằng hành động; nhưng cú bật sáng ở giây 2.5–5, đèn không có mặt ở frame đầu shot_01, "Asian", caption lặp VO, shot_04 2 hành động |
| 2 | 2 | đạt | bật sáng ở giây 0 (product_only cận, tay cắm USB), đèn tắt ở frame đầu, vị trí đồ cố định |
| 3 | 1 | gần đạt | SET/WEAR riêng, i2v cho shot có đèn; lỗi omp: presenter on_camera_speech đặt r2v; lỗi pipeline: set/wear thiếu dấu chấm dính câu sau, cụm practical_night "lit only by the lamp" sai cho shot trước khi bật |

Sửa tầng 2 vòng 2: practical_night diễn đạt chung "light sources visible in frame"; lint `default_set`/`default_wear`; storyboard tự thêm dấu chấm cho set/wear_direction; Stage 3 từ chối `generation_mode: r2v` cho on_camera_speech (ADR 0008); docs tool_guidance.
| 3 | 2 | đạt | 6/6 shot i2v (presenter shot_05 không còn r2v), 0 lint lỗi, dấu chấm set/wear đúng; clip_heavily_trimmed ×6 chấp nhận (beat 2.5–3.5s, hành động dồn đầu). Yếu nhất: shot_06 tay chỉ giữa không trung (rủi ro artifact bàn tay) |

### Kết vòng 2
Điểm: Quy trình 8.5 · Brief&concept 9 · Kịch bản 8.5 · Storyboard 8.5 · Prompt ảnh 8.5 · Prompt video 8.5 · Tuân thủ 9 · Sáng tạo 8.5 → TB 8.63, không mục <8 → đạt về điểm, nhưng có sửa tầng 2 trong vòng → không tính vào chuỗi đạt liên tiếp.
Bài học cho vòng 3: cử chỉ tay nên có điểm tựa (chạm vật), tránh tay chỉ trỏ giữa không trung.

## Vòng 3 · túi tote canvas sọc navy · fashion_apparel · nữ 20–23 dạo phố cổ HN · giờ vàng ngoài trời · `projects/fashion_apparel/pp_r3/runs/v1`
Biến đổi: archetype fashion (chỉ model/product_only, mặc định editorial_fashion + orbit), ngoài trời, giờ vàng, không nói trước máy, ≤2 câu VO, 12–18s.
Bẫy: mô tả shop "chống thấm 100%, chịu tải 30kg, GOTS, ngăn laptop, khoá kéo YKK, hot trend 2026, freeship" (ảnh: cúc bấm, không khoá kéo); nhãn thương hiệu bên thứ ba trong ảnh.

| Bước | Lần | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | 1 | đạt có điều kiện | bẫy shop xử lý từng ý (khoá kéo đối chiếu ảnh = cúc bấm), nhãn → nhãn vải be trơn; key_visual có điểm tựa tay (chạm cúc bấm). Lỗi: controlling_idea + arc 3–7s so sánh "không cần túi mini chật chội hay balo cồng kềnh" (brief cấm so sánh với túi khác); "nhẹ nhõm khi không còn balo" là cảm xúc không quay được; audio music_and_sfx_only nhưng có spoken_hook (brief cho ≤2 câu VO); angle A/C không chọn vẫn văn mẫu ("hàng kém chất lượng", "độ bền cực hạn") |
| 2 | 1 | đạt có điều kiện | controlling_idea khẳng định, không so sánh; 6 beat 15.5s, 2 VO off_camera, model/product_only, golden_hour mọi beat, orbit chỉ khi túi đứng yên, truck khi đi bộ, tay luôn có điểm tựa. Lỗi: fade 0.3s ở mọi cut (fashion cần cut gọn/match cut); shot_05 visual_cue VN (cất đồ + bấm cúc + đổi vai→tay + bước ra) lệch EN (chỉ bước ra), động tác đổi vai→tay không xuất hiện; sổ/áo khoác đã cất trong túi ở shot_01 lại nằm trên bàn ở shot_03 không được lấy ra; caption "CANVAS MỘC TỰ NHIÊN" sát claim hữu cơ, "THAO TÁC DỄ DÀNG" chung chung; CTA 13 âm tiết/3s; visual_cue VN shot_06 "mỉm cười về phía ống kính" trái vai model |
| 2 | 2 | đạt | cut gọn, shot_05 một hành động (vai→tay), đồ vật liên tục, caption "MỘT CÚC BẤM"/"CANVAS MỘC", CTA 9 âm tiết, shot_06 nhìn theo phố |
| 3 | 1 | gần đạt | set theo địa điểm (phố cổ/quán cà phê), wear riêng, 0 rò rỉ ballroom/satin/rim light, 6/6 i2v có lý do, orbit = [Truck left,Pan right] trên túi đứng yên, 0 lỗi lint. Lỗi khung hình: shot_05 medium shot (ngang eo) mà trạng thái kết thúc là túi xách tay buông ngang hông → túi ra khỏi khung; shot_06 CTA cũng medium shot với túi buông bên hông → khung chốt không thấy sản phẩm; shot_03 MCU (ngực trở lên) mà hành động mở cúc/lấy sổ ở mặt bàn → tay ra khỏi khung. Lỗi pipeline (ghi lại, sửa giữa vòng 3→4): câu ref "reproduce this exact object... details" mâu thuẫn với nhãn be trơn (rủi ro chép nhãn thương hiệu trong ảnh); tên sản phẩm tiếng Việt chèn vào prompt tiếng Anh ("focus on Túi tote canvas sọc navy") |
| 3 | 2 | gần đạt | shot_03 → medium_shot, shot_05/06 → cowboy_shot, 0 lỗi lint. Còn shot_06 (khung chốt): túi tote cao được xách ở tay buông → thân túi treo từ hông xuống gần gối; cowboy cắt giữa đùi → mất nửa dưới túi (đáy navy, sọc dưới). Thiếu cỡ cảnh "medium wide" (đầu gối trở lên) trong enum ShotScale |
| 3 | 3 | đạt | shot_06 → wide_shot toàn thân, túi thấy trọn tới đáy navy; 0 lỗi lint; clip_heavily_trimmed ×6 chấp nhận |

### Kết vòng 3
Điểm: Quy trình 9 · Brief&concept 8.5 · Kịch bản 8.5 · Storyboard 8.5 · Prompt ảnh 8.5 · Prompt video 8.5 · Tuân thủ 9 · Sáng tạo 8 → TB 8.56, không mục <8. KHÔNG sửa tầng 2 trong vòng → vòng đạt (chuỗi đạt = 1).
Trừ điểm: storyboard cần 3 lần để đúng khung hình (sản phẩm/tay ra khỏi khung); hook tay cất sổ vào túi đúng ý nhưng chưa đủ bất ngờ; prompt ảnh: câu ref "reproduce... details" mâu thuẫn nhãn trơn, tên sản phẩm tiếng Việt trong prompt tiếng Anh.

Sửa tầng 2 giữa vòng 3→4 (sau khi vòng 3 đã chấm, không ảnh hưởng kết quả vòng 3):
| File | Sửa | Test |
|---|---|---|
| pipeline/scriptwriter.py | `shot_language_issues`: sản phẩm mang thấp (at her side/hip, by its handles, hand-carry) trong khung medium/MCU/CU của vai model → issue, gợi ý cowboy/wide | test_storyboard_planning (1) |
| pipeline/identity_keyframe.py | câu ref sản phẩm: "but not any printed text or logo on it; where the shot text describes a detail differently, follow the text" | test_prompt_pack (1) |
| pipeline/storyboard.py | tên sản phẩm không phải ASCII → "the product" trong prompt tiếng Anh (focal point + câu product) | test_storyboard_planning (1) |
Full pytest: 618 passed.

## Vòng 4 · kem dưỡng ẩm hũ thuỷ tinh · beauty_skincare · nữ 25–30 văn phòng TP.HCM · sáng, nắng sớm · presenter 2–3 beat nói · `projects/beauty_skincare/pp_r4/runs/v1`
Biến đổi: archetype beauty, presenter nói trước máy (lip-sync), trong nhà ban ngày, ngành có luật claim riêng (mỹ phẩm).
Bẫy: "trắng da cấp tốc, trị mụn, xoá nám sau 7 ngày, chuẩn FDA, 100% thiên nhiên an toàn cho bà bầu, trước/sau, mua 1 tặng 1"; chữ mờ in trên hũ.

| Bước | Lần | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | 1 | đạt có điều kiện | loại từng ý shop kèm cơ sở (TT 06/2011 Phụ lục 03-MP, Luật QC Điều 8, FDA không "approve" mỹ phẩm), hũ không chữ, 3 beat nói, hook chạm nỗi ngại kem bết. Lỗi: arc "thẩm thấu nhanh" (claim hiệu năng ngoài danh sách); controlling_idea "tất cả những gì cần… luôn mềm mại suốt cả ngày" (tuyệt đối hoá); CTA tay chỉ xuống góc màn hình giữa không trung; caption hook 7 chữ |
| 2 | 1 | đạt có điều kiện | 18.5s, 3 beat nói MCU (tay đặt bàn, không che miệng), tán kem là vai model CU mặt 3/4, ASMR nắp/seal product_only, trạng thái hũ theo thứ tự, natural_daylight mọi beat, lời ≤3.3 âm tiết/s, bỏ "thẩm thấu nhanh". Lỗi: shot_06 CTA MCU mà hũ đặt trên bàn (ngang eo) → sản phẩm ngoài khung chốt; shot_02 frame đầu "nắp nới lỏng mà đã thấy seal" (trạng thái không thể); 3 caption lặp lời (KẾT CẤU MỀM MỊN, TÁN MỎNG NHẸ TÊNH, DA MỀM DỄ CHỊU); 6/6 locked_off và chỉ MCU/CU (không shot nào lập bối cảnh bàn + cửa sổ); hook "kem bí da" ngầm claim thông thoáng (brief: "bết dính"); "under morning window light" trong visual_cue_en; "A young woman" thiếu "Vietnamese". Lint khung hình mới không bắt (hũ "on the table" chứ không "at her side") |
| 2 | 2 | đạt | hook "bết dính", shot_01 medium_shot lập bối cảnh, shot_06 hũ ở tầm ngực dưới cằm, shot_02 frame đầu nắp đóng, caption bổ sung (TRƯỚC GIỜ ĐI LÀM, MỘT BƯỚC THÔI…) |
| 3 | 1 | gần đạt | set/wear riêng (bàn gỗ cạnh cửa sổ HCM, áo cotton gân be), 0 rò rỉ marble/spa/silk, LIGHT natural daylight 5600K, ref sản phẩm có câu "not any printed text", focus "the product", 6/6 i2v có lý do, push-in shot_03, 0 lỗi lint. Còn: shot_03 frame đầu "seal còn dán mà thấy bề mặt kem" (không thể) + motion 2 hành động (bóc seal + chấm kem) trong 3s |
| 3 | 2 | đạt | shot_03 frame đầu seal che kín miệng hũ, ngón tay kẹp mép seal; motion một hành động (bóc seal lộ kem); shot_04/05 khớp hũ đã bóc seal; 0 lỗi lint |

### Kết vòng 4
Điểm: Quy trình 9 · Brief&concept 9 · Kịch bản 8.5 · Storyboard 8.5 · Prompt ảnh 8.5 · Prompt video 8.5 · Tuân thủ 9 · Sáng tạo 8 → TB 8.63, không mục <8. KHÔNG sửa tầng 2 trong vòng → vòng đạt. Chuỗi đạt = 2 (vòng 3, 4) → ĐIỀU KIỆN DỪNG ĐẠT.
Trừ điểm: kịch bản v1 lặp lỗi khung chốt CTA của vòng 3 (lint chưa bao trường hợp "trên bàn"); trạng thái vật không thể ở frame đầu (2 lần); máy tĩnh 5/6 shot; định dạng presenter còn quen thuộc.

Sửa tầng 2 sau vòng 4 (sau khi đã chấm, không ảnh hưởng kết quả):
| File | Sửa | Test |
|---|---|---|
| pipeline/scriptwriter.py | beat CTA: sản phẩm "on the table/desk/counter/vanity" trong khung MCU/CU → issue. Chạy lại trên 13 script cũ: bắt đúng r3 v1–v2 (shot_05/06) và r4 v1 (shot_06), 0 báo động giả | test_storyboard_planning (1) |
| pipeline/slideshow_risk.py | gate slideshow Stage 8 đọc `motion_prompt` (hành động + lệnh máy thực gửi, gồm camera_command override) thay vì chỉ scene_description/camera_choreography; thêm động từ twist/peel/dip/place/plug/pedal/speak… Trước sửa: từ chối nhầm r1 (shot_07) và r4 (shot_02) | test_slideshow_risk (1) |
| tools/prompt_pack.py | chạy gate slideshow, hard reject → error trong gói | test_prompt_pack |
| harness/tool_guidance.md, harness/preprod_qa_loop.md | lint khung hình, gate trong prompt_pack, checklist khung/trạng thái vật/điểm tựa tay | — |
Full pytest: 620 passed.

## Sau loop: người dùng duyệt đề xuất ADR (2026-10-23)
ADR 0009 (sửa quyết định 3 của ADR 0008): shot vai model mặc định I2V từ first frame tổng hợp; R2V chỉ khi đạo diễn đặt `generation_mode: "r2v"`. Sửa `pipeline/identity_keyframe.py` (`_shot_dispatch`), tests (test_storyboard_planning, test_identity_references +1), CONTEXT.md, ADR 0008 (ghi chú), harness/tool_guidance.md. Full pytest 621 passed. Gói prompt 4 vòng tạo lại: 0 lỗi, toàn bộ I2V.
