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
```

---

## 3. Chạy Kiểm Thử Tự Động (TDD Test Suite)

Toàn bộ các module đều được kiểm thử tự động với Pytest:

```bash
python3 -m pytest tests/ -v
```

---

## 4. Cấu Trúc Thư Mục & Artifacts Chuẩn Hóa

```
KOL/
├── CONTEXT.md                       # Thuật ngữ chuyên ngành (TVC, Hook, I2V, Telea Inpainting, Ducking)
├── docs/adr/                        # Hồ sơ quyết định kiến trúc (ADR 0001 - 0004)
├── assets/characters/kol_main/      # Hồ sơ và mỏ neo danh tính KOL Minh Anh ([KOL_MA])
│   ├── character.json
│   ├── portrait.png
│   ├── identities/
│   └── expressions/
├── assets/audio/                    # Nhạc nền BGM & hiệu ứng âm thanh SFX
│   ├── music/commercial_bgm.mp3
│   └── sfx/pop.mp3, chime.mp3
├── pipeline/                        # Mã nguồn pipeline tự trị
│   ├── config.py
│   ├── schemas.py                   # Canonical Pydantic Schemas
│   ├── briefing.py                  # Step 1: Phân tích USP
│   ├── scriptwriter.py              # Step 2: Kịch bản chuyển đổi cao
│   ├── storyboard.py                # Step 3: Phân cảnh 6 lớp DramaClaw
│   ├── identity_keyframe.py         # Step 4: Khóa danh tính & Telea Inpainting
│   ├── video_engine.py              # Step 5: Render video I2V
│   ├── audio_lip_sync.py            # Step 6: Neural TTS & đồng bộ khẩu hình
│   ├── composer.py                  # Step 7: FFmpeg ducking & typography
│   ├── verification.py              # Step 8: Bộ 3 cổng kiểm định độc lập
│   └── director.py                  # Orchestrator điều phối toàn trình
├── tools/
│   ├── director.py                  # CLI điều hành Tổng Đạo Diễn
│   ├── dramaclaw_shot_builder.py
│   └── generate_video.py
├── output/
│   ├── final_commercial_master.mp4  # Video thành phẩm xuất xưởng (1080x1920, H.264, AAC)
│   ├── thumbnail_master.jpg         # Poster frame xuất bản
│   └── artifacts/                   # 7 Canonical JSON Artifacts
└── tests/                           # 13 Unit & Integration tests
```
