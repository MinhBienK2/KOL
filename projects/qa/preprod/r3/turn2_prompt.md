QA Stage 1: ĐẠT CÓ ĐIỀU KIỆN. Xử lý mô tả shop và nhãn thương hiệu rất tốt. Cần sửa trước khi viết kịch bản:
1. controlling_idea và narrative_arc của angle được chọn đang SO SÁNH với túi khác ("không cần túi mini chật chội hay balo cồng kềnh", "không còn balo cồng kềnh hay túi xách chật chội"). Brief cấm so sánh với túi khác. Viết lại theo hướng khẳng định, quay được bằng hình: ví dụ "Cả buổi chiều nằm gọn trong một chiếc túi: cô ấy cứ thế đi, cần gì lấy nấy." Pain point của khán giả giữ trong đầu bạn, không nói ra trong video.
2. Arc 3–7s "nhẹ nhõm khi không còn balo" là cảm xúc không quay được → thay bằng hành động thấy được.
3. Âm thanh: brief cho phép nhạc + tối đa 2 câu VO ngắn → dùng off_camera_vo cho đúng 2 beat có lời (hook-ish và CTA), các beat khác music_and_sfx_only. Không beat nào on_camera_speech; không vai presenter (archetype fashion không cho phép).
Sửa creative_concept bằng: python3 tools/director.py --campaign pp_r3 --topic fashion_apparel --inject creative_concept=<file> --pause-after-stage 1 --json < /dev/null

Sau đó làm Stage 2 (kịch bản) rồi dừng. Cấm: Stage ≥3 lúc này, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, gọi Python inject_artifact.
Yêu cầu kịch bản:
- 12–18s, 5–6 beat (2.5–4.5s/beat), ≥2 shot trong 5 giây đầu. Hook bằng hình trong ≤1.5s đầu, gắn với ý "đựng vừa cả buổi" (không chỉ túi đung đưa chung chung).
- Vai: chỉ model hoặc product_only.
- lighting_contract: `golden_hour` cho mọi beat ngoài trời; nếu có cảnh quán cà phê thì vẫn là nắng chiều vàng chiếu qua cửa (golden_hour), không dùng editorial_fashion/studio cho cảnh phố. Ghi rõ "late afternoon" trong visual_cue_en, không có từ midday/noon/overcast.
- Chứng minh claim bằng hành động: lấy sổ / bình nước / áo khoác mỏng ra hoặc cất vào qua miệng túi rộng; bấm cúc bấm; chuyển từ đeo vai sang xách tay. Túi phải đúng ảnh: canvas mộc, ba sọc navy ngang thân, đáy navy, quai vải navy, một cúc bấm kim loại ở miệng túi, nhãn vải be TRƠN không chữ.
- Cử chỉ tay luôn có điểm tựa: tay nắm quai, chạm thân túi, cầm đồ vật. Không chỉ tay/vẫy tay giữa không trung.
- Chuyển động: KHÔNG kết hợp orbit với người đang đi bộ trong cùng một beat (mô hình video dễ trượt chân/biến dạng). Người đi bộ → máy tracking song song hoặc máy đứng yên; orbit chỉ khi người/túi đứng yên.
- Liên tục: một bộ trang phục tông sáng không logo (ghi rõ trong visual_cue_en mọi beat có cô ấy), túi ở cùng một bên vai trừ beat chủ đích đổi; đồ đã lấy ra phải nằm đâu đó ở beat sau hoặc được cất lại.
- visual_cue_en = khoảnh khắc first frame đứng yên ở giây 0 (không từ máy quay/khung hình/ánh sáng, không "then"); motion_cue_en bắt đầu từ chính khoảnh khắc đó, hành động chính xảy ra ngay đầu clip (clip sinh 6s rồi cắt theo beat), một hành động chính + trạng thái kết thúc.
- VO ≤2 câu, tự nhiên, ≤ ~4 âm tiết/giây; caption 2–4 chữ bổ sung chứ không lặp VO; CTA "bấm giỏ hàng" dùng tên ngắn "túi tote sọc navy".
- Đa dạng camera và shot_scale có lý do; CTA tĩnh.
Viết script ra projects/qa/preprod/r3/script_v1.json, tự validate:
python3 -c "import json;from pipeline.schemas import ScriptArtifact;from pipeline.scriptwriter import validate_script;print(validate_script(ScriptArtifact.model_validate(json.load(open('projects/qa/preprod/r3/script_v1.json'))).beats))"  → phải in []
Rồi: python3 tools/director.py --campaign pp_r3 --topic fashion_apparel --inject script=projects/qa/preprod/r3/script_v1.json --pause-after-stage 2 --json < /dev/null (exit 4 = đạt).
Báo cáo: controlling_idea mới, bảng beat (thời lượng, vai, audio, camera, shot_scale, lighting, VO, caption, visual_cue_en, motion_cue_en), tổng thời lượng, và vì sao cấu trúc này giữ người xem.
