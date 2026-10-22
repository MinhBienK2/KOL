QA Stage 2 (kịch bản) – lần 1: KHÔNG ĐẠT. Hãy viết lại script.json rồi chạy lại Stage 2 bằng CLI, dừng sau Stage 2. Tuyệt đối không chạy Stage ≥3, không tạo ảnh/video/TTS, không sửa tay file trong artifacts/, không gọi Python inject_artifact.

Repo vừa có thay đổi bạn phải dùng:
- LightingContract mới: `natural_daylight` (5600K, nắng ban ngày/phòng có nắng) và `overcast_soft` (6500K, trời âm u/sau mưa). `golden_hour` chỉ dành cho bình minh/hoàng hôn. Không dùng nordic_minimalist/editorial_fashion/studio_3point cho ngõ, phố, phòng trọ.
- `--inject script=...` giờ từ chối script có beat on_camera_speech mà hình không có mặt cô ấy, hoặc golden_hour trong cảnh trưa/âm u/mưa. Tự kiểm trước bằng: `python3 -c "import json;from pipeline.schemas import ScriptArtifact;from pipeline.scriptwriter import validate_script;print(validate_script(ScriptArtifact.model_validate(json.load(open('<file>'))).beats))"` → phải in `[]`.

Lỗi cần sửa:
1. Vai & âm thanh: cận lốp/phuộc/phanh/xích không có mặt người thì không thể lip-sync. Những beat đó là `model` hoặc `product_only` + `off_camera_vo`. Chỉ dùng `presenter`+`on_camera_speech` khi mặt và miệng cô ấy ở trong khung (medium → close-up) và visual_cue_en nói rõ "she". Kịch bản tốt nên có 1–2 beat nói trước máy (hook và/hoặc CTA), còn lại là VO.
2. Ánh sáng: một bối cảnh = một lighting. 11h45 trưa ngoài phố = natural_daylight; nếu muốn cảm xúc "sau cơn mưa" thì overcast_soft cho cả phân đoạn đó. Không nhảy Kelvin giữa các beat cùng địa điểm.
3. Kịch tính: hiện chưa có xung đột thật. Cho thấy (bằng hình, không phải lời) một khoảnh khắc "tự lo" cụ thể của sinh viên năm nhất ở trọ, ví dụ: tan ca muộn/lỡ xe buýt, đường ngõ có ổ gà/nước đọng, phải chở balo + túi đồ. Không tạo cảnh suýt va chạm giao thông, không chê phương tiện khác, không đồng hồ đếm giờ.
4. VO phải khớp hình: shot_02 nói "Lên xe là đạp ngay" trong khi cô ấy đang dắt xe → sửa để lời nói trùng hành động trên màn hình (hoặc đổi hành động).
5. Liên tục: mũ bảo hiểm xuất hiện ở shot_06 mà chưa được thiết lập. Hoặc đội từ đầu, hoặc cho cảnh cô ấy đội mũ trước khi đạp. Giữ nguyên trang phục và balo suốt video; ghi rõ trong visual_cue_en.
6. Máy quay: hiện truck ×5 rồi orbit, locked_off → đơn điệu. Đa dạng có lý do: hook cần chuyển động mạnh/góc lạ trong 3 giây đầu, chi tiết sản phẩm dùng zoom_in/macro, cảnh đạp xe dùng tracking/truck, CTA tĩnh (locked_off). Đổi shot_scale xen kẽ (wide → close → medium), ≥2 shot trong 5 giây đầu.
7. Caption: đừng lặp lại VO. Caption ngắn 2–4 chữ bổ sung ý (cảm xúc/lợi ích), đặt sao cho vẫn đọc được trong vùng an toàn.
8. CTA: VO "Thống Nhất MTB 26-02" khó đọc cho TTS → nói "xe Thống Nhất" hoặc "xe đạp Thống Nhất", CTA hướng tới "bấm giỏ hàng".
9. visual_cue_en: tiếng Anh đúng ngữ pháp (shot_04 sai), mỗi beat một hành động, không chứa lệnh camera mâu thuẫn với camera_choreography. Thêm `motion_cue_en` (8–40 từ, chỉ chuyển động + tốc độ + trạng thái kết thúc, không mô tả ngoại hình/bối cảnh/ánh sáng/camera).
10. Claim: chỉ dùng claim được phép trong BRIEF. Không "an toàn tuyệt đối", không "bền", không "không hỏng vặt". Tốc độ nói ≤ ~4 âm tiết/giây; nếu validate báo "spoken line needs ~Xs" thì rút câu hoặc tăng duration (2.5–6s/beat, tổng ≤ 30s, hook ≤ 3s).

Cách chạy: viết script mới ra file ngoài artifacts (vd `projects/qa/preprod/r1/script_v2.json`), tự validate ra `[]`, rồi:
`python3 tools/director.py --campaign pp_r1 --topic general_commercial --inject script=projects/qa/preprod/r1/script_v2.json --pause-after-stage 2 --json < /dev/null`
(dùng đúng flag campaign/topic/run như lần trước). Exit 4 = đạt checkpoint.

Báo cáo: bảng beat (thời lượng, vai, audio, camera, shot_scale, lighting, VO, caption, visual_cue_en, motion_cue_en), giải thích ngắn bạn đã sửa từng mục 1–10 thế nào, và tổng thời lượng.
