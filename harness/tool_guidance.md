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
- `--keyframe-source auto|synth`: (Stage 4) `synth` vẽ first frame từng shot từ `prompt_6part` với face anchor
  và/hoặc ảnh sản phẩm làm reference (Flow2API). `auto` = synth trừ khi `--video-mode ffmpeg` hoặc `--offline`.
  Trong `--references`, mỗi shot có thể đặt `"synthesis_references": [..]` (vd shot có chảo cũ: chỉ face anchor, không ảnh
  sản phẩm) hoặc `"first_frame": PATH` để tự đưa first frame. Không có chế độ đệm ảnh reference (ảnh chân dung studio, ảnh
  catalogue) làm first frame: `"synthesize": false` bị từ chối. Một shot vẽ lỗi thì Stage 4 dừng với
  `FirstFrameSynthesisError`, không ghi `asset_manifest.json`; sửa gateway ảnh rồi `--from-stage 4`. Stage 5 (video thật)
  từ chối mọi shot có `keyframe_source` khác `synthesized`/`override` (First-frame gate), trước mọi lệnh gọi trả phí.
  Provider ảnh không tự đổi khi lỗi. Flow2API báo `Failed to obtain reCAPTCHA token` là lỗi gateway: dừng và báo, không
  chạy lại vòng lặp.
- `--shot-overrides PATH.json`: (Stage 3) Ghi đè thông số camera motion, framing hoặc lighting cho từng shot cụ thể trong scene plan.
  Khoá hợp lệ theo shot (`shot_01` hoặc `scene_id`): `shot_scale`, `lens`, `angle`, `extra_direction` (nối thêm vào prompt),
  `set_direction` (thay câu `SET:` mặc định của archetype, ví dụ home_lifestyle mặc định là phòng khách; cảnh ở bếp phải ghi
  `set_direction` cho **mọi** shot cùng bối cảnh, cùng một câu). `wear_direction` thay câu `WEAR:` mặc định (general_commercial mặc định là blazer công sở: nhân vật
  đời thường phải ghi `wear_direction` cho **mọi** shot có người, cùng một câu, gồm cả phụ kiện xuyên suốt như mũ, balo). `generation_mode`: mặc định model = I2V từ first frame tổng hợp (ADR 0009); chỉ đặt `"r2v"` khi shot cần chuyển động thân thể lớn và sản phẩm không chiếm khung (R2V/S2V-01 chỉ nhận ảnh mặt, không
  nhận first frame, nên vẽ lại sản phẩm từ chữ). Shot `on_camera_speech` không được `r2v` (lip-sync cần I2V; Stage 3 từ chối). Sau Stage 3 đọc `prompt_6part` từng shot: không được có hai mô
  tả bối cảnh, hai kiểu tóc hay chi tiết mâu thuẫn với visual cue.
- **Gói prompt tiền kỳ** (sau Stage 3, không gọi mạng): `python3 tools/prompt_pack.py --run <run_dir>` ghi
  `artifacts/prompt_pack.json|md`: đúng prompt first frame và reference từng shot mà Stage 4 sẽ gửi, và request video
  (mode, model, giây sinh, prompt) mà Stage 5 sẽ gửi, kèm lint (ánh sáng studio ở bối cảnh thật, Kelvin tungsten với
  nắng, tag rác "8k", prompt quá dài, bối cảnh/trang phục mặc định của archetype chưa được xác nhận `default_set`/`default_wear`, R2V vẽ lại sản phẩm, clip bị cắt nhiều) và kết quả gate slideshow của Stage 8 (shot máy tĩnh mà không có hành động → `error`). Đọc toàn văn trước khi sang Stage 4; lint `error` phải sửa ở Stage 3.
- `validate_script` / `--inject script` còn chặn lỗi khung hình: sản phẩm mang thấp (ở hông, xách quai) trong khung medium/MCU/CU của vai model; sản phẩm của beat CTA đặt trên bàn trong khung MCU/CU.
- `--references PATH.json`: (Stage 4) Ghi đè reference assets cho nhân vật hoặc sản phẩm khi sinh keyframe.
- `--character PATH|ID`: (Stage 3/4) Trỏ đến thư mục character tùy chỉnh hoặc ID persona dưới `assets/characters/`.
- `--strict-resolution`: (Stage 4) Bắt buộc ảnh reference phải đạt chuẩn độ phân giải cao, từ chối ảnh mờ.
- `--strict-tts`: (Stage 6) Ép buộc model Neural TTS chính thức, không cho phép fallback sang giọng chất lượng thấp.
- `--transitions PATH.json`: (Stage 7) Thiết lập danh sách hiệu ứng chuyển cảnh chi tiết giữa các beat.
- `--from-stage N`: Khởi động lại pipeline trực tiếp từ stage N (1-8), giữ nguyên các artifact đã hoàn thành trước đó.
- `--audience "<ai, hoàn cảnh, cảm xúc muốn để lại>"`: (Stage 1) khán giả do khách hàng chốt; mọi concept phải viết cho đúng
  nhóm này (không nhét khán giả vào `--url`: researcher coi `--url` là mô tả sản phẩm).
- `--inject NAME=PATH`: Đạo diễn tự viết artifact (`creative_concept`, `brief`, `script`, `scene_plan`, `asset_manifest`), CLI validate theo schema rồi cài vào `artifacts/` và tự động resume ở stage kế tiếp. **Không bao giờ sửa trực tiếp file
  trong `artifacts/`** (edit tay bỏ qua validate và telemetry): chép ra ngoài, sửa, rồi `--inject`. Muốn đổi ý tưởng thì
  inject `creative_concept` (có `controlling_idea`, `key_visual`) cùng `brief`.
  `--inject X=... --pause-after-stage N` với N là stage sinh ra X (vd brief/creative_concept → 1) chỉ cài rồi dừng (exit 4,
  `next_stage`), không chạy gì: dùng để QA duyệt artifact tự viết. Không gọi `ProjectWorkspace.inject_artifact` bằng Python.
- `--new-version`: Phân nhánh một version mới (v2, v3) kế thừa media đã render qua hardlink để tối ưu chi phí và thời gian.
- `--check`: Chế độ chỉ đọc, kiểm tra tính hợp lệ của plan và artifact tiền đề mà không thực thi bất kỳ stage nào.
- `--offline`: Chế độ offline không dùng mạng, đặt `KOL_OFFLINE=1` và ép `--video-mode ffmpeg` để test logic nhanh.
