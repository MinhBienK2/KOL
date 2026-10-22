QA Stage 1: ĐẠT. Xử lý mô tả shop rất tốt. Ghi nhớ khi viết kịch bản: không dùng "tuyệt đối"; ánh sáng là "ánh sáng trắng" (không nói "ấm áp"/nhiệt độ màu, brief không có); không có đèn khác trong khung để tránh so sánh ngầm.

Làm Stage 2 (kịch bản) rồi dừng. Cấm: Stage ≥3 lúc này, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, gọi Python inject_artifact.
Yêu cầu kịch bản:
- 15–20s, 5–6 beat (2.5–6s/beat), ≥2 shot trong 5 giây đầu. Hook bằng hình trong ≤1.5s đầu: phòng tối → dải LED bừng sáng (ASMR cắm USB). Có một "trước" rõ: cô ấy về muộn, phòng tối, chỉ có ánh màn hình điện thoại (không có đèn khác).
- Âm thanh: tối đa 1 beat presenter + on_camera_speech (mặt và miệng trong khung). Còn lại model/product_only với off_camera_vo hoặc music_and_sfx_only (ASMR: tiếng cắm dây, gõ phím, lật trang).
- lighting_contract: `practical_night` cho mọi beat (cùng một căn phòng, đèn trong khung là nguồn sáng chính); trước khi bật đèn, nguồn sáng duy nhất là màn hình điện thoại/ánh thành phố ngoài cửa sổ: vẫn practical_night.
- Chứng minh claim bằng hành động: cắm dây USB vào sạc dự phòng hoặc laptop; đèn chữ L thanh mảnh đứng cạnh laptop + sổ trên bàn hẹp mà vẫn còn chỗ; thân acrylic trong suốt bắt sáng.
- Liên tục: một bàn, một cửa sổ có ánh đèn thành phố mờ phía sau, một bộ đồ ở nhà (ghi rõ trong visual_cue_en mọi beat có cô ấy).
- visual_cue_en = khoảnh khắc first frame đứng yên ở giây 0 (không từ máy quay/khung hình/ánh sáng, không "then"); motion_cue_en bắt đầu từ chính khoảnh khắc đó, hành động chính xảy ra ngay đầu clip (clip sinh 6s rồi cắt theo beat), một hành động chính + trạng thái kết thúc.
- VO tự nhiên, ≤ ~4 âm tiết/giây; caption 2–4 chữ bổ sung chứ không lặp VO; CTA "bấm giỏ hàng" dùng tên ngắn "đèn acrylic".
- Đa dạng camera và shot_scale có lý do; CTA tĩnh.
Viết script ra projects/qa/preprod/r2/script_v1.json, tự validate:
python3 -c "import json;from pipeline.schemas import ScriptArtifact;from pipeline.scriptwriter import validate_script;print(validate_script(ScriptArtifact.model_validate(json.load(open('projects/qa/preprod/r2/script_v1.json'))).beats))"  → phải in []
Rồi: python3 tools/director.py --campaign pp_r2 --topic tech_gadgets --inject script=projects/qa/preprod/r2/script_v1.json --pause-after-stage 2 --json < /dev/null (exit 4 = đạt).
Báo cáo: bảng beat (thời lượng, vai, audio, camera, shot_scale, lighting, VO, caption, visual_cue_en, motion_cue_en), tổng thời lượng, và vì sao cấu trúc này giữ người xem.
