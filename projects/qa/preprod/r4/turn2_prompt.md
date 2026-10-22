QA Stage 1: ĐẠT CÓ ĐIỀU KIỆN. Xử lý mô tả shop và chữ trên hũ rất tốt. Ghi nhớ khi viết kịch bản (không cần inject lại concept, sửa thẳng trong script):
- "thẩm thấu nhanh" là claim hiệu năng KHÔNG có trong danh sách → bỏ. Chỉ nói: tán mỏng nhẹ, kết cấu mềm, dưỡng ẩm, cảm giác cá nhân.
- Không tuyệt đối hoá ("tất cả những gì cần", "luôn", "suốt cả ngày giữ…"). Lời kể cảm nhận cá nhân ở thì hiện tại, ví dụ "Ngồi điều hoà cả ngày, mình thấy da dễ chịu hơn hẳn" cũng KHÔNG được (so sánh ngầm "hơn hẳn"); dùng "…mà da mình vẫn thấy mềm, dễ chịu".
- CTA: không chỉ tay xuống góc màn hình giữa không trung. Tay cầm hũ kem/đặt hũ xuống; lời nói làm việc kêu gọi.

Làm Stage 2 (kịch bản) rồi dừng. Cấm: Stage ≥3 lúc này, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, Python inject_artifact.
Yêu cầu kịch bản:
- 15–22s, 5–7 beat (2.5–5s/beat), ≥2 shot trong 5 giây đầu; hook nghe + nhìn trong ≤1.5s đầu.
- 2–3 beat presenter + on_camera_speech: mặt và miệng trong khung (medium_close_up/close_up/medium_shot), tay KHÔNG che miệng/má trong lúc nói, không tán kem trong lúc nói. Beat tán kem lên má là vai model (không nói, off_camera_vo hoặc ASMR), giữ ngắn, một ngón tay chạm má, mặt quay 3/4 về phía cửa sổ.
- Còn lại model/product_only: ASMR vặn nắp xanh, bóc seal bạc, đầu ngón tay lấy kem để lộ kết cấu (product_only cận, chỉ thấy tay).
- lighting_contract `natural_daylight` cho mọi beat (cùng một bàn trang điểm cạnh cửa sổ, nắng sớm). Không golden_hour (nắng sáng ở thành phố không phải giờ vàng nếu đã quá sớm? Nếu bạn chọn golden_hour cho ánh nắng sớm thấp, giải thích một câu và giữ thống nhất mọi beat).
- Liên tục: một bàn, một cửa sổ, một bộ đồ buổi sáng (ghi rõ trong visual_cue_en mọi beat có cô ấy); trạng thái hũ (nắp đóng → mở → seal bóc → kem có vệt lấy) phải đi đúng thứ tự qua các beat.
- Hũ đúng ảnh: thuỷ tinh trong, thành dày, nắp vặn xanh dương, màng seal bạc; KHÔNG chữ/nhãn.
- visual_cue_en = khoảnh khắc first frame đứng yên ở giây 0 (không từ máy quay/khung hình/ánh sáng, không "then"); motion_cue_en bắt đầu từ chính khoảnh khắc đó, hành động chính ngay đầu clip, một hành động chính + trạng thái kết thúc. Với beat nói: motion chỉ là nói + một cử chỉ nhỏ có điểm tựa.
- Lời nói ≤ ~4 âm tiết/giây, tự nhiên như kể bạn nghe; caption 2–4 chữ bổ sung chứ không lặp lời; CTA "bấm giỏ hàng" dùng tên ngắn "kem dưỡng hũ thuỷ tinh" hoặc "kem dưỡng ẩm".
- Kiểm tra khung: ở frame đầu VÀ frame cuối, sản phẩm/tay đang làm việc/miệng người nói có trong khung không.
Viết script ra projects/qa/preprod/r4/script_v1.json, tự validate:
python3 -c "import json;from pipeline.schemas import ScriptArtifact;from pipeline.scriptwriter import validate_script;print(validate_script(ScriptArtifact.model_validate(json.load(open('projects/qa/preprod/r4/script_v1.json'))).beats))"  → phải in []
Rồi: python3 tools/director.py --campaign pp_r4 --topic beauty_skincare --inject script=projects/qa/preprod/r4/script_v1.json --pause-after-stage 2 --json < /dev/null (exit 4 = đạt).
Báo cáo: bảng beat (thời lượng, vai, audio, camera, shot_scale, lighting, lời, caption, visual_cue_en, motion_cue_en), tổng thời lượng, số âm tiết/giây các beat có lời, và vì sao cấu trúc này giữ người xem.
