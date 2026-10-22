# RUNTIME DIAGNOSTICS & AUTONOMOUS ERROR RECOVERY PROTOCOL (HỒI PHỤC LỖI TỰ TRỊ)

## 1. NGUYÊN TẮC HỒI PHỤC LỖI TỰ TRỊ
Một AI Director Agent xuất sắc không bao giờ dừng lại đầu hàng khi pipeline gặp sự cố. Khi một lệnh chạy kết thúc với mã thoát khác 0 (exit code != 0), agent lập tức đọc file `run_result.json` và `render_report.json` tại thư mục workspace của run để xác định chính xác nguyên nhân và thực thi chiến lược hồi phục tự động.

## 2. QUY TRÌNH HỒI PHỤC THEO TỪNG MÃ THOÁT

### A. Hồi phục khi Exit Code 1 (`failed` - Lỗi Kỹ Thuật Stage)
- **Hành vi kiểm tra:** Đọc trường `failed_stage` và thông điệp `error` trong `run_result.json`.
- **Phương án khắc phục:**
  1. *Nếu Stage 1 lỗi:* Kiểm tra lại URL sản phẩm hoặc tên sản phẩm. Rerun với `--from-stage 1`.
  2. *Nếu Stage 2 lỗi:* Kiểm tra lại brief hoặc file `--beats` xem có bị vượt quá 6s/beat hoặc sai cấu trúc schema không.
  3. *Nếu Stage 3 lỗi:* Điểm Slideshow Risk vượt ngưỡng cho phép. Bổ sung động từ hành động và chuyển động camera vào `--shot-overrides`, chạy lại với `--from-stage 3`.
  4. *Nếu Stage 4 lỗi (IdentityReferenceError / Thiếu ảnh sản phẩm hoặc nhân vật):*
     - Nếu lỗi báo `No product reference available for product_only shots`: Bổ sung ngay ảnh sản phẩm vào `projects/<topic>/<campaign>/input/product_hero.jpg` hoặc truyền cờ `--references '{"product_hero": <path>}'`.
     - Nếu thiếu ảnh nhân vật hoặc ảnh mờ: Bổ sung ảnh chất lượng cao vào `--references`.
     - Sau khi bổ sung, tiếp tục pipeline bằng lệnh:
       `python3 tools/director.py --campaign <id> --from-stage 4`
     - Nếu lỗi là `FirstFrameSynthesisError` (gateway ảnh Flow2API lỗi khi vẽ first frame): Stage 4 dừng, không có ảnh
       thay thế. Kiểm gateway, rồi chạy lại `--from-stage 4`. Lỗi `Failed to obtain reCAPTCHA token` thì dừng và báo người
       dùng. Không tự đổi sang model ảnh khác trừ khi người dùng yêu cầu.
  5. *Nếu Stage 5 lỗi (Diffusion API 422 / Network Timeout):* Lỗi API dịch vụ sinh video bên ngoài. Kiểm gateway rồi chạy lại `--from-stage 5`. Không chuyển `--video-mode ffmpeg` để đi tiếp: clip placeholder không phải video thật và bị `prompt_ledger_audit_gate` chặn.
     - Nếu lỗi là `First-frame gate`: shot được nêu chưa có first frame đã vẽ. Chạy lại `--from-stage 4`.
  6. *Nếu Stage 6 lỗi:* Audio TTS lỗi kết nối hoặc stem bị rỗng. Chạy lại với `--from-stage 6`.
  7. *Nếu Stage 7 lỗi:* Lỗi ghép FFmpeg hoặc sidechain ducking. Chạy lại với `--from-stage 7`.

### B. Hồi phục khi Exit Code 2 (`invalid` - Thiếu Tiền Đề / Tham Số Sai)
- **Hành vi kiểm tra:** Đọc danh sách `problems` hoặc `error` trong `run_result.json`.
- **Phương án khắc phục:**
  - Nếu thiếu artifact tiền đề của Stage N: Chạy stage N-1 trước để sinh artifact, HOẶC dùng cờ `--inject NAME=PATH` để cài artifact hợp lệ vào hệ thống.
  - Sau khi cài artifact tiền đề, hệ thống sẽ tự động resume từ stage tiếp theo.

### C. Hồi phục khi Exit Code 3 (`verification_failed` - Cổng Kiểm Định Từ Chối Master)
- **Hành vi kiểm tra:** Đọc danh sách `failed_gates` trong `run_result.json` hoặc chi tiết từng cổng trong `artifacts/render_report.json`.
- **Phương án khắc phục:**
  1. *Nếu dính `media_quality_gate` (Loudness lệch chuẩn / Black frame / Freeze):*
     - Master video bị lệch âm lượng so với chuẩn -14 LUFS hoặc có đoạn đứng hình.
     - Tinh chỉnh thông số compose hoặc độ dài clip, sau đó resume lại bằng `--from-stage 7`.
  2. *Nếu dính `prompt_ledger_audit_gate` (Master chứa placeholder / clip hạ cấp):*
     - Các clip video thô ở Stage 5 hoặc audio stem ở Stage 6 bị rơi vào chế độ placeholder/fallback.
     - Kích hoạt sinh lại clip/stem với model chính thức bằng `--from-stage 5` hoặc `--from-stage 6`.
  3. *Nếu dính `continuity_gate`:*
     - Số lượng clip video đã đồng bộ không khớp với số beat kịch bản trong `script.json`.
     - Kiểm tra lại manifest và resume từ `--from-stage 6` hoặc `--from-stage 7`.
  4. *Nếu dính `character_consistency_gate`:*
     - Keyframe chưa tẩy sạch watermark AI hoặc khuôn mặt bị biến dạng.
     - Chạy lại Stage 4 khử watermark rồi resume từ `--from-stage 4`.

### D. Hồi phục khi Exit Code 4 (`paused` - Điểm Dừng Kiểm Tra Con Người)
- **Hành vi kiểm tra:** Đọc `paused_after_stage` và `next_stage` từ kết quả JSON.
- **Phương án khắc phục:**
  - Sau khi kiểm tra xong kết quả giai đoạn, chạy tiếp phần còn lại bằng:
    `python3 tools/director.py --campaign <id> --from-stage <next_stage> --json`

## 3. PHÂN NHÁNH PHIÊN BẢN SÁNG TẠO (`--new-version`)
Khi cần thử nghiệm một hướng sáng tạo mới (thay đổi góc quay hoặc kịch bản mới) mà không muốn phá hỏng kết quả phiên bản hiện tại và không muốn tốn chi phí render lại các phân đoạn đã có:
- Sử dụng cờ `--new-version`: Hệ thống tự động tạo `v2`, `v3` và kế thừa các tài nguyên video/âm thanh cũ bằng hardlink.
