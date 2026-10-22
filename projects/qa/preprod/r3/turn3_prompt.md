QA Stage 2: ĐẠT CÓ ĐIỀU KIỆN. Ý tưởng chủ đạo mới tốt, claim chứng minh bằng hành động, quy tắc orbit/tracking và điểm tựa tay đúng. Sửa nhỏ rồi làm luôn Stage 3. Cấm: Stage ≥4, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, Python inject_artifact.

A. Kịch bản (projects/qa/preprod/r3/script_v2.json, validate ra []):
1. Chuyển cảnh: fade 0.3s ở mọi cut làm nhịp fashion chậm và cũ. Dùng cut gọn (transition null) là mặc định; tối đa 1 chuyển cảnh có chủ đích (vd match cut giữa túi trên bàn và túi trên tay).
2. shot_05: visual_cue tiếng Việt đang tả 4 hành động (cất đồ, bấm cúc, đổi vai→tay, bước ra) trong khi visual_cue_en/motion chỉ có bước ra. Động tác đổi từ đeo vai sang xách tay là bằng chứng cho caption "ĐEO VAI HOẶC XÁCH TAY" nhưng chưa xuất hiện trên hình. Chọn MỘT hành động cho shot_05: frame đầu túi trên vai phải, tay nắm quai; motion: cô ấy tuột quai xuống và cầm túi bằng quai ở tay phải (trạng thái kết thúc: xách tay). Máy đứng yên hoặc dịch rất nhẹ, không pedestal khi người đang đổi động tác. Giữ visual_cue VN khớp EN ở mọi beat.
3. Liên tục đồ vật: shot_01 sổ và áo khoác đã vào túi; shot_03 chúng lại nằm trên bàn mà không ai lấy ra. Sửa sao cho frame đầu shot_03 chỉ có túi đóng trên bàn (hoặc nói rõ đồ đã được lấy ra), và shot_04/05 khớp theo.
4. Caption: "CANVAS MỘC TỰ NHIÊN" gần với claim hữu cơ (bị cấm) → dùng "CANVAS MỘC" hoặc ý cảm xúc. "THAO TÁC DỄ DÀNG" chung chung → caption bổ sung cho hình (vd "MỘT CÚC BẤM"). Caption 2–4 chữ, không lặp VO.
5. CTA VO ≤ ~10 âm tiết/3s: vd "Bấm giỏ hàng, chọn túi tote sọc navy."
6. shot_06 vai model: không nhìn/mỉm cười vào ống kính (bản VN đang ghi "về phía ống kính"); ánh mắt nhìn theo phố hoặc xuống túi.

B. Stage 3: archetype fashion_apparel mặc định là phòng khiêu vũ Paris ("env_paris_ballroom", editorial 5000K rim light) và váy satin dạ hội → sai hoàn toàn. Tạo projects/qa/preprod/r3/shot_overrides.json:
- set_direction theo từng cảnh (MỘT câu tiếng Anh cho mỗi địa điểm, dùng y hệt cho các shot cùng địa điểm): hè phố cổ Hà Nội chiều muộn (vỉa hè, tường vàng cũ, cây, ghế gỗ) và quán cà phê nhỏ (bàn gỗ sát cửa sổ mở ra phố). Không "studio", "runway", "ballroom", "rim light", "softbox".
- wear_direction: MỘT câu cho mọi shot có người: áo linen kem không tay, quần ống rộng màu ngà, không logo, không trang sức nổi.
- generation_mode: shot model mà túi chiếm phần lớn khung → "i2v" (R2V chỉ nhận mặt, túi sẽ bị vẽ lại từ chữ). Giải thích từng lựa chọn.
- camera_command nếu lệnh tự suy ra không đúng ý (đặc biệt orbit shot_04 và tracking shot_02).
Chạy: inject script_v2 với --pause-after-stage 2, rồi --from-stage 3 --pause-after-stage 3 --shot-overrides ... --json < /dev/null, rồi python3 tools/prompt_pack.py --run projects/fashion_apparel/pp_r3/runs/v1. Đọc toàn văn prompt_pack.md: 0 error; mọi warn phải có lý do. Kiểm tra từng prompt ảnh: túi đúng ảnh (canvas mộc, ba sọc navy, đáy navy, quai navy, một cúc bấm kim loại, nhãn be TRƠN không chữ), không còn chữ "ballroom/runway/satin/gala/rim light", ánh sáng chiều muộn.
Báo cáo: lệnh + exit code, shot_overrides.json, bảng beat (visual_cue_en, motion_cue_en, VO, caption, vai, camera, generation_mode, transition), lint còn lại + lý do, và prompt nào bạn thấy yếu nhất.
