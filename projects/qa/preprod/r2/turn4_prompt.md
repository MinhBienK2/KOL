QA Stage 3 lần 1: gần đạt. Hook bật sáng giây 0, đèn tắt ở frame đầu, vị trí laptop/sổ/sạc/đèn cố định, SET/WEAR riêng: tốt.
Một lỗi của bạn: shot_05 là presenter + on_camera_speech nhưng bạn đặt generation_mode "r2v". R2V không có first frame nên đầu/ánh mắt trôi, lip-sync hỏng (ADR 0008: presenter = I2V). Pipeline giờ từ chối tổ hợp này. Đổi shot_05 thành "i2v".
Lỗi pipeline tôi đã sửa: set_direction/wear_direction thiếu dấu chấm bị dính câu sau; giờ tự thêm dấu chấm.
Chạy lại: --from-stage 3 --pause-after-stage 3 --shot-overrides projects/qa/preprod/r2/shot_overrides.json --json < /dev/null, rồi tools/prompt_pack.py --run projects/tech_gadgets/pp_r2/runs/v1. Cấm Stage ≥4 / tạo ảnh / sửa code / sửa tay artifacts.
Báo cáo ngắn: exit code, mode từng shot, lint còn lại + lý do, và 1 câu bạn thấy prompt nào còn yếu nhất.
