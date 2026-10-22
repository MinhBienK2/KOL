QA Stage 2: ĐẠT CÓ ĐIỀU KIỆN. Phân vai nói/không nói, trạng thái hũ, nhịp lời đều tốt. Sửa rồi làm luôn Stage 3. Cấm: Stage ≥4, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, Python inject_artifact.

A. Kịch bản (projects/qa/preprod/r4/script_v2.json, validate ra []):
1. Khung chốt shot_06 là MCU (ngực trở lên) nhưng hũ đặt trên mặt bàn ngang eo → sản phẩm ra khỏi khung đúng lúc CTA. Sửa: cô ấy cầm hũ ở tầm ngực (tay dưới cằm, KHÔNG che miệng) trong MCU, hoặc medium_shot thấy cả mặt và hũ trên bàn. Áp dụng câu hỏi "frame đầu và frame cuối: sản phẩm có trong khung không?" cho mọi beat.
2. shot_02 frame đầu: "nắp nới lỏng mà đã lộ seal" là trạng thái không thể. Frame đầu = hũ đóng nắp, tay đặt trên nắp; motion = vặn mở nắp, đặt nắp xuống, seal lộ ra.
3. Caption không lặp lời: "KẾT CẤU MỀM MỊN", "TÁN MỎNG NHẸ TÊNH", "DA MỀM DỄ CHỊU" đang lặp lời đọc. Caption 2–4 chữ bổ sung (cảm xúc/bối cảnh), ví dụ "7 GIỜ SÁNG" (không, cấm con số) → ví dụ "TRƯỚC GIỜ ĐI LÀM", "MỘT BƯỚC THÔI".
4. Hook: "kem bí da" là claim ngầm về độ thông thoáng (không có trong danh sách). Dùng nỗi ngại trong brief: "bết dính".
5. Camera/cỡ cảnh: 6/6 locked_off và chỉ MCU/CU → đơn điệu, chưa có shot nào cho thấy bàn trang điểm cạnh cửa sổ. Đổi ít nhất: một shot medium_shot lập bối cảnh (hook hoặc CTA), một chuyển động có lý do (vd push-in rất chậm vào bề mặt kem ở shot_03). Beat nói giữ máy tĩnh hoặc push rất nhẹ.
6. visual_cue_en: bỏ từ ánh sáng ("under morning window light"); nhân vật là "a young Vietnamese woman".

B. Stage 3: archetype beauty_skincare mặc định là phòng tắm đá cẩm thạch tối giản (env_minimalist_marble_bath, beauty_high_key) và áo lụa spa → sai. Tạo projects/qa/preprod/r4/shot_overrides.json:
- set_direction: MỘT câu tiếng Anh dùng y hệt mọi shot: bàn trang điểm gỗ nhỏ kê sát cửa sổ căn hộ TP.HCM buổi sáng, vài vật dụng cố định (gương nhỏ, chậu cây, khăn), vị trí cố định. Không "studio", "marble", "spa", "softbox", "high-key".
- wear_direction: MỘT câu cho mọi shot có người: đồ buổi sáng ở nhà gọn gàng (màu, chất liệu), tóc theo nhân vật, không trang sức nổi.
- generation_mode: beat nói (presenter on_camera_speech) KHÔNG được r2v (Stage 3 sẽ từ chối). Shot model tán kem: i2v hay r2v, giải thích.
- camera_command nếu lệnh tự suy ra không đúng ý.
Chạy: inject script_v2 với --pause-after-stage 2, rồi --from-stage 3 --pause-after-stage 3 --shot-overrides projects/qa/preprod/r4/shot_overrides.json --json < /dev/null, rồi python3 tools/prompt_pack.py --run projects/beauty_skincare/pp_r4/runs/v1. Đọc toàn văn prompt_pack.md: 0 error; mọi warn có lý do. Kiểm tra từng prompt ảnh: hũ đúng ảnh và KHÔNG chữ/nhãn; không còn "marble/spa/silk/high-key"; trạng thái hũ đúng từng shot; prompt ảnh beat nói không có tay che miệng.
Báo cáo: lệnh + exit code, shot_overrides.json, bảng beat (shot_scale, camera, frame đầu, frame cuối, sản phẩm trong khung ở cả hai?, vai, generation_mode), lint còn lại + lý do, prompt yếu nhất.
