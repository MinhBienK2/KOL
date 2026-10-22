QA Stage 2: ĐẠT CÓ ĐIỀU KIỆN. Cấu trúc trước/sau, ASMR, 1 beat nói, practical_night, claim chứng minh bằng hành động đều tốt. Sửa nhỏ rồi làm luôn Stage 3. Cấm: Stage ≥4, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, Python inject_artifact.

A. Kịch bản (script_v2.json, validate ra []):
1. Hook: khoảnh khắc đèn bừng sáng đang rơi vào giây 2.5–5; 2.5s đầu cô ấy chỉ ngồi đặt điện thoại xuống. Đưa cú bật sáng vào giây đầu: mở bằng shot cận product_only trong bóng tối (chỉ có ánh điện thoại hắt từ xa), tay cắm USB vào sạc dự phòng và dải LED bừng sáng ngay; shot sau mới lộ cô ấy được ánh đèn mới chiếu lên mặt (cảm giác "trước" vẫn có vì frame đầu tối). Hoặc phương án khác của bạn, miễn đèn sáng trước giây 2.
2. Liên tục: đèn acrylic phải có mặt (tắt) trên bàn ngay từ frame đầu mọi shot trước khi bật; laptop, sổ, sạc dự phòng, cửa sổ đêm cùng vị trí trong mọi shot. Ghi rõ trong visual_cue_en.
3. Nhân vật là người Việt: "A young Vietnamese woman" (không "Asian").
4. Caption "ÁNH SÁNG TRẮNG" lặp VO → đổi thành ý bổ sung (vd cảm xúc "TẬP TRUNG ĐƯỢC RỒI" hoặc lợi ích nhìn thấy).
5. shot_04 motion có 2 hành động (lật trang + gõ phím) → chọn 1.

B. Stage 3: archetype tech_gadgets mặc định là bàn "cyberpunk creator desk" với softbox 5500K và áo techwear hoodie → sai. Tạo projects/qa/preprod/r2/shot_overrides.json:
- set_direction: MỘT câu tiếng Anh dùng y hệt cho mọi shot: căn hộ studio Việt Nam nhỏ, bàn gỗ hẹp sát cửa sổ đêm có đèn thành phố mờ, vị trí cố định của laptop/sổ/sạc dự phòng/đèn. Không "studio lighting", "softbox", "neon", "cyberpunk", "LED wash".
- wear_direction: MỘT câu cho mọi shot có người (đồ ở nhà, màu, chất liệu).
- generation_mode: shot vai model mà đèn chiếm khung → "i2v" (R2V chỉ nhận mặt, đèn sẽ bị vẽ lại từ chữ); giải thích lựa chọn.
- camera_command nếu lệnh tự suy ra không đúng ý.
Chạy: inject script_v2 với --pause-after-stage 2, rồi --from-stage 3 --pause-after-stage 3 --shot-overrides ... --json < /dev/null, rồi python3 tools/prompt_pack.py --run projects/tech_gadgets/pp_r2/runs/v1. Đọc toàn văn prompt_pack.md: 0 error; mọi warn phải có lý do. Kiểm tra từng prompt ảnh: shot trước khi bật đèn phải mô tả đèn TẮT và nguồn sáng là điện thoại; sau khi bật mới có dải LED sáng.
Báo cáo: lệnh + exit code, shot_overrides.json, bảng beat (visual_cue_en, motion_cue_en, VO, caption, vai, generation_mode), lint còn lại + lý do.
