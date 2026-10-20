# KOL Character Studio & Autonomous Commercial Video Director

Hệ thống sản xuất video quảng cáo thương mại tự trị (Autonomous Commercial Video Pipeline) tích hợp kiến trúc điều phối của **OpenMontage** và kỹ thuật khóa danh tính nhân vật & kiểm định thị giác của **DramaClaw**.

---

## 1. Kiến trúc Pipeline 8 Bước Thống Nhất

```
[1. Briefing & Phân tích USP]          ──> output/artifacts/brief.json
               │
               ▼
[2. Biên kịch High-Conversion Script]  ──> output/artifacts/script.json
               │
               ▼
[3. Phân cảnh Storyboard 6-Part]      ──> output/artifacts/scene_plan.json
               │
               ▼
[4. Khóa KOL & Keyframe 9:16]          ──> output/artifacts/asset_manifest.json + Telea Inpainting
               │
               ▼
[5. Render Video I2V Phân đoạn]        ──> output/raw_clips/shot_XX.mp4
               │
               ▼
[6. Neural TTS & Lip-sync Match]       ──> output/synced_clips/shot_XX.mp4
               │
               ▼
[7. FFmpeg Dựng phim & Audio Ducking]  ──> output/artifacts/edit_decisions.json + final_commercial_master.mp4
               │
               ▼
[8. Kiểm định Độc lập & Đóng gói]      ──> output/artifacts/render_report.json + publish_log.json
```

---

## 2. Cách Vận Hành Pipeline Tự Trị

### Chạy toàn bộ chiến dịch bằng Director CLI:
```bash
# Chạy toàn bộ pipeline từ Step 1 đến Step 8:
python3 tools/director.py --campaign campaign_lumina_mug_01 --product "Ly Giữ Nhiệt Thông Minh Lumina Pro"

# Chạy với chế độ sinh video qua API MiniMax Hailuo:
python3 tools/director.py --video-mode api

# Phục hồi / chạy tiếp từ một bước cụ thể (ví dụ Step 6):
python3 tools/director.py --from-stage 6

# Chạy offline hoàn toàn (KOL_OFFLINE=1, ép --video-mode ffmpeg):
python3 tools/director.py --offline
```

### Tạo character sheet cho trang phục mới (ADR 0008)

```bash
# Sinh 4 body panels + 2x2 face grid, ghép sheet 2516 px, rồi đăng ký identity:
python3 tools/generate_character_sheet.py \
  --outfit-id minimalist_spa_silk \
  --wardrobe-id costume_minimalist_spa_silk \
  --identity-id kol_main_spa \
  --identity-name "Minimalist Spa Silk" \
  --character-tag "[KOL_MAIN_SPA]" \
  --register
```

- Mặc định dùng `--provider flow2api` (Gemini image / Nano Banana): giữ đúng Face Anchor.
- `--provider minimax` dùng MiniMax `image-01`; proxy hiện bỏ qua nội dung `file_list`, nên mặt sinh ra lệch identity (SFace cosine ~0.16). Chỉ dùng để thử layout, không đăng ký bản MiniMax cho production.
- `--single-pass --aspect-ratio 16:9`: 1 call duy nhất, gửi 2 reference (character sheet gốc + face anchor), model trả thẳng 4 body + 4 face trong 2 hàng. Phải dùng 16:9; model 4:3 đang trả portrait 3:4 và sinh thêm hàng mặt.
- `--from-images BODY FACES` ghép sheet từ ảnh có sẵn, không gọi mạng.
- Mỗi outfit là một identity trong `character.json`; `ARCHETYPE_IDENTITY_MAP` tự chọn sheet theo archetype.

### Chỉ đạo của Agent (tuỳ chọn) và Checkpoint con người

Mọi cờ dưới đây đều tuỳ chọn; không truyền thì pipeline chạy hành vi mặc định. Cũng dùng được qua `python -m pipeline.director`.

| Cờ | Stage | Tác dụng |
|---|---|---|
| `--beats PATH.json` | 2 | Danh sách beat do agent viết, truyền `generate_commercial_script(beats=..., strict=True)` |
| `--shot-overrides PATH.json` | 3 | Ghi đè từng shot cho `generate_scene_plan(shot_overrides=...)` |
| `--references PATH.json` | 4 | `reference_overrides` cho `generate_clean_keyframes` |
| `--character PATH_OR_ID` | 3, 4 | File/thư mục `character.json` hoặc persona id trong `assets/characters/` (vd `kol_main`) |
| `--strict-resolution` | 4 | Lỗi thay vì chấp nhận reference độ phân giải thấp |
| `--strict-tts` | 6 | Lỗi thay vì rơi về giọng TTS suy giảm |
| `--transitions PATH.json` | 7 | Mỗi mối nối một `{"type", "duration"}` (hoặc tên transition); mặc định đọc trường `transition` của từng beat trong `script.json` (transition của beat là mối nối SAU beat đó) |
| `--pause-after-stage N` | 1-7 | Dừng sạch sau stage N, trạng thái `paused`, exit code **4** |
| `--offline` | tất cả | `KOL_OFFLINE=1` + `--video-mode ffmpeg` |

Stage 1 có `--url` sẽ dùng `create_product_brief_from_concept`, nên Character Role, audio strategy của angle thắng đi thẳng vào `brief.json`.

**Kết quả máy đọc được:** object `--json` của CLI cũng được lưu thành `projects/<topic>/<project>/runs/<vN>/run_result.json` (cùng một định dạng). `status`: `completed` / `failed` / `verification_failed` / `paused` / `invalid` / `checked`; khi tạm dừng có thêm `paused_after_stage`, `next_stage`, `resume_hint`. Exit code: `0` hoàn tất, `1` lỗi stage, `2` input sai, `3` Verification Gate từ chối, `4` tạm dừng. `--inject NAME=PATH`, `--check`, `--json` xem `DIRECTOR_AGENT_PROMPT.md`.

```bash
python3 tools/director.py --campaign demo --pause-after-stage 3   # dừng sau storyboard, exit 4
python3 tools/director.py --campaign demo --from-stage 4          # người duyệt xong -> chạy tiếp
```

---

## 3. Chạy Kiểm Thử Tự Động (TDD Test Suite)

Toàn bộ các module đều được kiểm thử tự động với Pytest:

```bash
python3 -m pytest tests/ -v
```

---

## 4. Giám Sát Trực Tiếp: Telemetry, Activity Feed & Dashboard

Mỗi lần chạy pipeline ghi lại **toàn bộ** diễn biến để người giám sát (supervisor) biết chính xác agent đang làm gì, đang tới đâu, tạo ra file gì, và prompt sinh video là gì — không cần đọc terminal.

### 4.1. Ba lớp dữ liệu giám sát

| Lớp | Đường dẫn | Nội dung |
|---|---|---|
| Run State Snapshot | `{workspace}/telemetry/state.json` | Ảnh chụp trạng thái hiện tại: 8 bước (status, thời lượng, progress `i/N`, message, error), danh sách artifact, **prompt ledger**, log gọi API |
| Event Log | `{workspace}/telemetry/events.jsonl` | Dòng sự kiện append-only, `seq` tăng đơn điệu: `run_start`, `stage_start`, `stage_progress`, `stage_message`, `stage_complete`, `stage_failed`, `stage_skipped`, `artifact`, `prompt`, `api_call`, `note`, `log` |
| Supervisor Dashboard | `dashboard/` + `tools/dashboard.py` | Web UI đọc 2 lớp trên (và artifact JSON) để hiển thị realtime |

Workspace = `projects/{topic}/{project_id}/runs/{version}/` (ADR 0007). Mỗi lần chạy hoặc chỉnh sửa sáng tạo là một phiên bản (`v1`, `v2`) khép kín độc lập, kế thừa tài nguyên không đổi qua cơ chế hardlink và lưu đầy đủ **Prompt Ledger** (`prompt_ledger.json`).

### 4.2. Khởi động Dashboard

```bash
# Mở giao diện giám sát (mặc định http://127.0.0.1:8787)
python3 tools/dashboard.py

# Chỉ định host/port và thư mục output khác
python3 tools/dashboard.py --host 0.0.0.0 --port 8790 --out-dir output

# Xem nhanh trạng thái mọi chiến dịch ngay trên terminal
python3 tools/dashboard.py --list

# Kết xuất toàn bộ view-model của một run ra JSON (dùng cho script/CI)
python3 tools/dashboard.py --run-id campaign_cherry_dress_01 --json
```

### 4.3. Người giám sát nhìn thấy gì trên giao diện

- **Sidebar**: tất cả run (run mới + campaign cũ) kèm badge trạng thái, 8 chấm tiến độ, % hoàn thành, thời gian chạy.
- **Header + Live Banner**: đang ở bước nào (`STAGE 5`), tiến độ chi tiết (`3/6 shots`), dòng hoạt động mới nhất, elapsed, đã có master hay chưa, run này có telemetry hay chỉ suy từ artifact.
- **8 Step Cards**: status / thời lượng / progress bar / message / lỗi (nếu fail) / link tới artifact của từng bước.
- **Activity Feed (SSE)**: luồng log realtime (kể cả toàn bộ `print()` cũ của pipeline), tô màu theo mức `info/warning/error`, lọc theo mức, tạm dừng autoscroll, copy feed.
- **Tab chi tiết theo bước**:
  - Bước 1: brief (persona, pain point, USP), competitor landscape, whitespace, winning angle + rationale, hook library.
  - Bước 2: bảng beats (timecode, spoken text, on-screen text, visual cue, camera, lighting, audio strategy).
  - Bước 3: storyboard từng shot + **prompt 6 lớp nguyên văn** (kèm nút copy và phần tách nhãn `Framing / Subject / Wardrobe / Action / Environment / SET / WEAR`), contact sheet, điểm Slideshow Risk.
  - Bước 4: gallery keyframe — **ảnh neo danh tính** (identity anchor) và **keyframe 9:16 đã khử watermark**, cờ fallback.
  - Bước 5: card từng shot — prompt đã gửi, chế độ `I2V/T2V`, model, aspect ratio, duration, attempts, first-frame, `task_id`, log poll, dung lượng file, và player video.
  - Bước 6: audio stem (voice) + clip đã khớp khẩu hình + profile năng lượng giọng nói.
  - Bước 7: timeline dựng (thứ tự clip, transition, caption), audio track với target LUFS / ducking dB, player master.
  - Bước 8: bảng 4 cổng kiểm định, render report, publish log (title/description/hashtags), thumbnail, tải master.

### 4.4. Prompt sinh video (Prompt Ledger)

Với mỗi shot, ledger lưu: nội dung prompt đầy đủ (đúng chuỗi đã gửi tới model), các đoạn chỉ thị tách theo nhãn, `mode` (`I2V` khi có first frame / `T2V` khi không), `model`, `aspect_ratio`, `duration_requested`, đường dẫn first frame, `task_id` trả về, số lần thử (`attempts`), file clip đầu ra và dung lượng. Prompt được ghi **ngay từ Bước 3** (lúc lập storyboard) nên giám sát viên thấy trước khi render, rồi được cập nhật bổ sung ở Bước 5 khi render thực tế.

### 4.5. API cho giám sát tự động (script / CI)

| Endpoint | Trả về |
|---|---|
| `GET /api/health` | `{ok, base_dir, runs}` |
| `GET /api/runs` | Danh sách run + trạng thái, tiến độ, thời gian, có master hay không |
| `GET /api/runs/{run_id}` | View-model đầy đủ: `run`, `stages`, `artifacts`, `prompts`, `shots`, `gates`, `media`, `brief/research/concept/script/scene_plan_summary/edit_decisions/render_report/publish_log`, `events` |
| `GET /api/runs/{run_id}/events?since=&limit=&levels=` | Sự kiện có `seq > since`, lọc theo mức log |
| `GET /api/runs/{run_id}/stream?since=` | SSE realtime (heartbeat ~15s) cho activity feed |
| `GET /api/runs/{run_id}/file?path=` | Nội dung artifact/media (hỗ trợ `Range` để tua video) |
| `GET /api/runs/{run_id}/artifact?name=` | Artifact JSON đã parse |

`run_id` giữ nguyên dấu `/` (ví dụ `fashion_apparel/campaign_cherry_dress_01`); campaign cũ dùng chính tên thư mục (ví dụ `campaign_cherry_dress_01`).

### 4.6. Bảo mật & Vận hành

- Mọi credential (`Authorization`, `api_key`, token, giá trị `sk-...`) được **che tự động** (`***REDACTED***`) trước khi ghi vào `state.json`/`events.jsonl`.
- API file chỉ phục vụ file **nằm trong run workspace** (hoặc trong `output/`, `assets/` khi artifact trỏ tới đó); yêu cầu vượt ranh giới (path traversal) trả `403`.
- Muốn một run bắt đầu lại "sạch" về mặt giám sát: xoá thư mục `telemetry/` của run đó (artifact và media giữ nguyên, dashboard tự chuyển sang chế độ suy từ artifact).
- Telemetry là **fail-safe**: mọi lỗi ghi log đều được nuốt và đếm vào `counters.errors`, không bao giờ làm hỏng render.

---

## 5. Cấu Trúc Thư Mục & Artifacts Chuẩn Hóa

```
KOL/
├── CONTEXT.md                       # Thuật ngữ chuyên ngành (TVC, Hook, I2V, Project Workspace)
├── docs/adr/                        # Hồ sơ quyết định kiến trúc (ADR 0001 - 0007)
├── projects/                        # Không gian dự án sản xuất (ADR 0007)
│   └── {topic}/                     # Ngành hàng: fashion_apparel, tech_gadgets, beauty_skincare...
│       └── {project_id}/            # ID dự án: lumina_mug_pro...
│           ├── project.json         # Metadata dự án (active_version, versions)
│           ├── input/               # Tư liệu đầu vào do user cung cấp
│           └── runs/                # Các phiên bản sản xuất (v1, v2...)
│               └── v1/
│                   ├── master.mp4             # Video commercial hoàn chỉnh (1080x1920)
│                   ├── thumbnail.jpg          # Poster bìa
│                   ├── prompt_ledger.json     # Sổ cái toàn bộ API calls & model prompts
│                   ├── artifacts/             # 7 JSON chuẩn (brief, script, scene_plan...)
│                   ├── keyframes/             # Ảnh First Frame 9:16 sạch đã khử watermark
│                   ├── media/                 # raw_clips/, synced_clips/, audio/
│                   └── telemetry/             # state.json & events.jsonl
├── assets/characters/{persona_id}/  # kol_main (Mai Ly)
│   ├── character.json               # Hồ sơ nhân vật; mỗi identity = 1 trang phục
│   ├── portrait.png                 # Face Anchor
│   └── outfits/{outfit_id}/         # 1 character sheet cho mỗi trang phục (ADR 0008)
│       ├── character_sheet.png      # 4 body panels + 4 face panels, 2516 px wide
│       └── _source/                 # Ảnh gốc MiniMax/Flow2API + generation.json
├── assets/audio/                    # Nhạc nền BGM & hiệu ứng âm thanh SFX
│   ├── music/commercial_bgm.mp3
│   └── sfx/pop.mp3, chime.mp3
├── pipeline/                        # Mã nguồn pipeline tự trị
│   ├── config.py
│   ├── telemetry.py                 # Run state, event log, prompt ledger (fail-safe)
│   ├── schemas.py                   # Canonical Pydantic Schemas
│   ├── briefing.py                  # Step 1: Phân tích USP
│   ├── scriptwriter.py              # Step 2: Kịch bản chuyển đổi cao
│   ├── storyboard.py                # Step 3: Phân cảnh 6 lớp DramaClaw
│   ├── identity_keyframe.py         # Step 4: Khóa danh tính & Telea Inpainting
│   ├── video_engine.py              # Step 5: Render video I2V
│   ├── audio_lip_sync.py            # Step 6: Neural TTS & đồng bộ khẩu hình
│   ├── composer.py                  # Step 7: FFmpeg ducking & typography
│   ├── verification.py              # Step 8: Bộ 4 cổng kiểm định độc lập
│   └── director.py                  # Orchestrator điều phối toàn trình
├── dashboard/                       # Web UI giám sát (FastAPI + vanilla JS, không build step)
│   ├── runs.py                      # Dò run, suy trạng thái từ artifact, dựng view-model
│   ├── server.py                    # REST + SSE + phục vụ file media (chặn path traversal)
│   └── static/                      # index.html, app.js, style.css
├── tools/
│   ├── director.py                  # CLI điều hành Tổng Đạo Diễn
│   ├── dashboard.py                 # CLI giám sát: serve / --list / --run-id --json
│   ├── dramaclaw_shot_builder.py
│   ├── generate_character_sheet.py  # Sinh character sheet theo trang phục + đăng ký identity
│   └── generate_video.py
├── output/
│   ├── final_commercial_master.mp4  # Video thành phẩm xuất xưởng (1080x1920, H.264, AAC)
│   ├── thumbnail_master.jpg         # Poster frame xuất bản
│   └── artifacts/                   # 7 Canonical JSON Artifacts
└── tests/                           # 20 modules test (unit + integration + dashboard API)
```
