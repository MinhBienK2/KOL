# DIRECTORIAL GUARDRAILS & QUALITY VERIFICATION STANDARDS (TIÊU CHUẨN KỸ THUẬT & CỔNG KIỂM ĐỊNH)

## 1. TIÊU CHUẨN CONTAINER & HÌNH ẢNH (TECHNICAL SPECIFICATIONS)
- **Tỉ lệ & Độ phân giải:** Bắt buộc 9:16 dọc, độ phân giải chính xác 1080x1920 pixels cho TikTok Shop, Reels, Shorts.
- **Chuẩn mã hóa:** Video codec H.264 (profile High, pixel format yuv420p), Audio codec AAC (48kHz, stereo, bitrate >= 192kbps).
- **Thời lượng video:** Chuẩn TVC quảng cáo từ 15.0s đến 35.0s (mặc định 20–30s).

## 2. TIÊU CHUẨN ÂM THANH & KHẨU HÌNH MIỆNG (AUDIO & LIP-SYNC STANDARDS)
- **Loudness tích hợp:** Chuẩn phát sóng -14 LUFS ± 1 LU (theo kiểm định Composer compliant) hoặc tối đa ± 3 LUFS.
- **True Peak:** Mức đỉnh tối đa True Peak <= -1.5 dBTP; cấm tuyệt đối clipping âm thanh.
- **Sidechain Audio Ducking:** Bắt buộc tự động hạ âm lượng nhạc nền (BGM) xuống -24dB trong các phân đoạn nhân vật nói và trả về bình thường khi ngưng thoại.
- **Độ chính xác Lip-sync:** Độ lệch pha giữa khẩu hình miệng và sóng âm thanh phải nhỏ hơn 50ms (Lip-sync offset < 50ms).
- **Chống câm tiếng (Silence Audit):** Không được xuất hiện digital silence trên các beat kịch bản có lời thoại.

## 3. RÀNG BUỘC CHẤT LƯỢNG THỊ GIÁC & TÍNH LIỀN MẠCH (VISUAL CONTINUITY)
- **Zero Black Frames:** Cấm xuất hiện đoạn khung hình đen kéo dài quá 1.0 giây.
- **No Frozen Holds:** Không được có phân cảnh đứng yên liên tục >= 2.0s hoặc tổng thời lượng đứng hình vượt quá 20% video.
- **Character Identity Consistency (ADR 0008):** Nhân vật đại diện chuẩn tắc là `Mai Ly` (`kol_main`). Tự động ánh xạ trang phục chuyên nghiệp theo archetype ngành hàng:
  - Mỹ phẩm / Spa (`beauty_skincare`): dùng `minimalist_spa_silk` (`kol_main_spa`).
  - Đời sống / Gia dụng (`home_lifestyle`): dùng `cozy_kitchen_knit` (`kol_main_cozy`).
  - Thời trang / Thương mại chung (`fashion_apparel`, `general_commercial`): dùng `studio_chic_black`.
- **Product Isolation (ADR 0006):** Đối với các phân cảnh quay riêng sản phẩm (`product_only`), bắt buộc phải có ảnh sản phẩm mẫu độc lập đặt tại `projects/<topic>/<campaign>/input/product_hero.jpg` hoặc truyền qua `--references '{"product_hero": "..."}'`. Tuyệt đối không bao giờ lấy chân dung nhân vật thay thế cho sản phẩm.
- **Slideshow Risk Gate:** Bắt buộc sử dụng động từ hành động thị giác mạnh mẽ trong prompt; loại bỏ triệt để cảm giác ảnh tĩnh zoom lướt kiểu slideshow.
- **FFmpeg Drawtext Compatibility:** Mọi hiệu ứng chữ/phụ đề gắn qua FFmpeg tuân thủ cú pháp tương thích FFmpeg 4.4+ (căn giữa ngang bằng `x=(w-text_w)/2`).

## 4. BỘ 8 CỔNG KIỂM ĐỊNH NGHIỆM THU ĐỘC LẬP (VERIFICATION GATES - ADR 0004)
1. `technical_integrity_gate`: Chạy `ffprobe` kiểm tra container MP4, codec h264/aac, độ phân giải 1080x1920, sample rate 48kHz.
2. `media_quality_gate`: Chạy ffmpeg `blackdetect` + `freezedetect` + `ebur128` kiểm tra loudness, câm tiếng và giật đứng hình.
3. `character_sheet_integrity_gate`: Kiểm định Face Anchor và character sheet của từng trang phục (đủ file, đủ độ phân giải).
4. `character_consistency_gate`: Soi chiếu sự đồng nhất diện mạo nhân vật và kiểm tra sạch watermark AI.
5. `continuity_gate`: Kiểm tra tính liền mạch nhịp điệu giữa các shot kề nhau và bảo đảm số lượng clip đã sync khớp 1:1 với số beat kịch bản.
6. `slideshow_risk_gate`: Phân tích điểm nguy cơ slideshow trên 6 chiều kích chuyển động camera và hành động chủ thể.
7. `identity_preflight_gate`: Tiền kiểm định độ phân giải và điểm mốc khuôn mặt trước khi đưa vào render.
8. `prompt_ledger_audit_gate`: Hậu kiểm Prompt Ledger đảm bảo không có cảnh quay nào bị hạ cấp (degraded) hoặc dính placeholder trong bản phát hành chính thức.

---

## 5. BỘ TIÊU CHUẨN ĐÁNH GIÁ CHẶNG ĐỘC LẬP (STAGE REVIEW RUBRICS)
Trước khi sang các chặng render tốn kém, bắt buộc phải thẩm định độc lập qua 3 cổng (xem `harness/stage_review_protocol.md` và `tools/review_stage.py`):
1. **Script Review Gate (Stage 2):** Cấu trúc 6 nhịp (Hook <= 4s, CTA cuối), không bịa đặt số liệu (no-fabrication), thời lượng đọc khớp cảnh, chỉ dẫn thị giác rõ ràng. Ngưỡng đạt: Score >= 8.0/10.
2. **Storyboard & Video Prompt Gate (Stage 3):** Khớp kịch bản 1:1, bối cảnh SET/WEAR phù hợp KOL Mai Ly và archetype (không xung đột), prompt tạo video (`prompt_6part` và `visual_cue_en`) chi tiết (động từ hành động mạnh, góc máy, ánh sáng, camera motion), Slideshow Risk score <= 2.8/5.0. Ngưỡng đạt: Score >= 8.0/10.
3. **Keyframe & KOL Lock Gate (Stage 4):** Khóa diện mạo Mai Ly vào assets repo, cô lập sản phẩm (product_hero không thay bằng mặt người), khử sạch watermark AI, định dạng 9:16 (1080x1920). Ngưỡng đạt: Score >= 8.0/10.

**Quy tắc vòng lặp (Review Loop):**
- Subagent Reviewer độc lập chấm điểm và trả feedback cho Agent cha.
- Nếu Score < 8.0/10: Agent cha sửa chữa (Refine) dựa trên feedback.
- Tối đa 3 vòng lặp. Quá 3 vòng chưa đạt -> dừng báo cáo escalation.
