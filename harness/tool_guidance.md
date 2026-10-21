# TOOL GUIDANCE & CLI EXECUTION CONTRACT (`tools/director.py`)

## 1. QUY CHUẨN GỌI CLI TỔNG ĐẠO DIỄN
Tổng Đạo Diễn (Agent) điều phối dây chuyền sản xuất video tự trị thông qua script `tools/director.py`:
```bash
python3 tools/director.py \
  --campaign <campaign_id> \
  --product "<product_name>" \
  --topic <archetype> \
  --video-mode auto \
  --json
```

### Tiền Đề Đầu Vào (Input Prerequisites):
Trước khi khởi chạy pipeline, hãy luôn đảm bảo:
- Thư mục đầu vào của dự án `projects/<topic>/<campaign>/input/` đã có ảnh sản phẩm rõ nét (ví dụ: `product_hero.jpg` hoặc `.png`).
- Nếu chưa có ảnh trong thư mục `input/`, bắt buộc phải truyền cờ:
  `--references '{"product_hero": "duong/dan/anh_san_pham.jpg"}'`
- Nếu thiếu ảnh sản phẩm, Stage 4 sẽ dừng lại với lỗi `IdentityReferenceError` theo đúng chuẩn Product Isolation (ADR 0006).

## 2. HỢP ĐỒNG `--json` & MÃ THOÁT (EXIT CODES)
Khi truyền cờ `--json`, stdout chỉ in ra duy nhất MỘT object JSON duy nhất chứa toàn bộ thông tin run (log chi tiết chuyển sang stderr):
```json
{
  "ok": true,
  "status": "completed",
  "exit_code": 0,
  "project_id": "campaign_lumina_01",
  "topic": "home_lifestyle",
  "version": "v1",
  "from_stage": 1,
  "workspace_root": "projects/home_lifestyle/campaign_lumina_01/runs/v1",
  "artifacts_dir": "projects/home_lifestyle/campaign_lumina_01/runs/v1/artifacts",
  "failed_stage": null,
  "failed_gates": [],
  "error": null
}
```

### Bảng Ý Nghĩa Mã Thoát (Exit Codes):
- **Exit Code 0 (`EXIT_OK`):** Pipeline chạy thành công trọn vẹn và TẤT CẢ 8 Verification Gates đều PASSED.
- **Exit Code 1 (`EXIT_PIPELINE_FAILED`):** Một stage bị lỗi kỹ thuật trong quá trình xử lý (xem `failed_stage`).
- **Exit Code 2 (`EXIT_INVALID_INPUT`):** Đầu vào sai hoặc thiếu artifact tiền đề của stage trước đó.
- **Exit Code 3 (`EXIT_VERIFICATION_FAILED`):** Master video đã được render nhưng bộ kiểm định chất lượng Stage 8 từ chối nghiệm thu (xem `failed_gates`).
- **Exit Code 4 (`EXIT_PAUSED`):** Dừng sạch theo cờ kiểm tra checkpoint `--pause-after-stage N`.

## 3. CÁC CỜ CHỈ ĐẠO CHUYÊN SÂU (AGENT DIRECTION FLAGS)
- `--beats PATH.json`: (Stage 2) Truyền danh sách nhịp thoại kịch bản đã định hình sẵn; hệ thống sẽ validate nghiêm ngặt theo schema.
- `--shot-overrides PATH.json`: (Stage 3) Ghi đè thông số camera motion, framing hoặc lighting cho từng shot cụ thể trong scene plan.
- `--references PATH.json`: (Stage 4) Ghi đè reference assets cho nhân vật hoặc sản phẩm khi sinh keyframe.
- `--character PATH|ID`: (Stage 3/4) Trỏ đến thư mục character tùy chỉnh hoặc ID persona dưới `assets/characters/`.
- `--strict-resolution`: (Stage 4) Bắt buộc ảnh reference phải đạt chuẩn độ phân giải cao, từ chối ảnh mờ.
- `--strict-tts`: (Stage 6) Ép buộc model Neural TTS chính thức, không cho phép fallback sang giọng chất lượng thấp.
- `--transitions PATH.json`: (Stage 7) Thiết lập danh sách hiệu ứng chuyển cảnh chi tiết giữa các beat.
- `--from-stage N`: Khởi động lại pipeline trực tiếp từ stage N (1-8), giữ nguyên các artifact đã hoàn thành trước đó.
- `--inject NAME=PATH`: Đạo diễn tự viết artifact (`brief`, `script`, `scene_plan`, `asset_manifest`), CLI validate theo schema rồi cài vào `artifacts/` và tự động resume ở stage kế tiếp.
- `--new-version`: Phân nhánh một version mới (v2, v3) kế thừa media đã render qua hardlink để tối ưu chi phí và thời gian.
- `--check`: Chế độ chỉ đọc, kiểm tra tính hợp lệ của plan và artifact tiền đề mà không thực thi bất kỳ stage nào.
- `--offline`: Chế độ offline không dùng mạng, đặt `KOL_OFFLINE=1` và ép `--video-mode ffmpeg` để test logic nhanh.
