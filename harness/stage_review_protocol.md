# QUY TRÌNH REVIEW ĐỘC LẬP & VÒNG LẶP HOÀN THIỆN VIDEO (STAGE REVIEW PROTOCOL)

Tài liệu quy chuẩn kiến trúc về việc phối hợp giữa **Agent cha (Tổng Đạo Diễn / Producer)** và các **Subagent Reviewer độc lập** nhằm kiểm soát chất lượng qua từng chặng sản xuất video commercial.

---

## 1. NGUYÊN TẮC BẤT BIẾN (CANONICAL INVARIANTS)

1. **Luôn sử dụng nhân vật KOL có sẵn trong repo:**
   - Nhân vật chuẩn tắc duy nhất: **Mai Ly (`kol_main`)** định nghĩa tại `assets/characters/kol_main/character.json`.
   - Tag nhận diện: `[KOL_MAIN]` (hoặc các biến thể outfit: `[KOL_MAIN_OFFICE]`, `[KOL_MAIN_SPA]`, `[KOL_MAIN_COZY]`).
   - Tài nguyên neo mặt bắt buộc: `assets/characters/kol_main/face_anchor.png` và `portrait.png`.
   - Ánh xạ outfit theo ngành hàng (Archetype):
     - `general_commercial` / `fashion_apparel`: `studio_chic_black` (`kol_main_office`).
     - `beauty_skincare`: `minimalist_spa_silk` (`kol_main_spa`).
     - `home_lifestyle`: `cozy_kitchen_knit` (`kol_main_cozy`).
   - **CẤM:** Tự ý tạo persona mới, lấy avatar ngoài, hoặc dùng hình ảnh không có mỏ neo nhận diện trong repo.

2. **Tách biệt vai trò độc lập (Independent Separation of Duties):**
   - **Agent cha (Producer / AI Director):** Điều phối pipeline, soạn brief, dựng kịch bản, lên storyboard, staging keyframe, compose video.
   - **Subagent Reviewer (Stage Critic / Supervisor):** Không làm thay, không đồng lõa; đứng ở góc độ người phê bình và khách hàng khó tính để soi lỗi, chấm điểm (0 - 10) và đưa ra hành động khắc phục cụ thể.

3. **Cơ chế Vòng Lặp Tối Đa 3 Lần (Max 3-Iteration Review Loop):**
   - Điểm chuẩn nghiệm thu: **Score >= 8.0 / 10** và không dính lỗi nghiêm trọng (hard blockers).
   - Nếu `Score >= 8.0`: **APPROVED** -> Cho phép Agent cha chuyển tiếp sang stage kế tiếp.
   - Nếu `Score < 8.0`: **NEEDS_REVISION** -> Reviewer trả về danh sách `problems` và `actionable_feedback` chi tiết. Agent cha nhận feedback, chỉnh sửa artifact (Refine), và đệ trình lại.
   - **Giới hạn trần:** Tối đa 3 vòng lặp (Iteration 1 -> Feedback 1 -> Revise 1 -> Iteration 2 -> Feedback 2 -> Revise 2 -> Iteration 3 -> Final verdict). Sau 3 vòng nếu vẫn chưa đạt, hệ thống dừng lại báo cáo lỗi rõ ràng (Escalation), không được chạy cố vào các bước tốn tiền (render video).

---

## 2. QUY TRÌNH PHỐI HỢP AGENT CHA & SUBAGENT REVIEWER

```
[Agent cha (Producer)]                   [Subagent Reviewer Độc Lập]
       │                                              │
       ├──────── 1. Tạo Draft Artifact ──────────────>│
       │    (script.json / scene_plan.json / ...)     │
       │                                              ├─ Soi chiếu Rubric
       │                                              ├─ Chấm điểm (0 - 10)
       │                                              └─ Lập Actionable Feedback
       │<─────── 2. Trả kết quả Review ───────────────┤
       │     (Score, Status, Problems, Feedback)      │
       │                                              │
  [Kiểm tra Score]                                    │
  ├── Score >= 8.0 ──> [APPROVED: Chuyển Stage tiếp]  │
  │                                                   │
  └── Score < 8.0  ──> [NEEDS_REVISION]               │

### 6. QUY CHUẨN PROMPT CHO VIDEO DIFFUSION (FL2VA & REF2VA STANDARDS)
Storyboard Reviewer BẮT BUỘC kiểm tra các prompt phải tuân thủ nghiêm ngặt cấu trúc FL2VA hoặc REF2VA:

1. **Subject Definitions:** Phải định nghĩa đối tượng anchor bằng thẻ `<Subject X>` (hình dạng, vật liệu, chi tiết đặc trưng cần giữ).
2. **Temporal Mapping (Bắt buộc cho Shot dài > 2s):** Phải map chi tiết hành động với thời gian (vd: "At 1.5s...", "At about 3.5s..."). Hành động phải cụ thể, có động năng (kinetic).
3. **Retention & Transfer Analysis:** Phải có phân tích rõ thành phần nào `fully_preserved` (giữ nguyên), thành phần nào `attribute_transfer` (chuyển đổi tính chất, vật liệu).
4. **Integrated Soundscape/Music:** Phải mô tả tiếng động (diegetic - vd: "papery bite", "pressurised air") và nhạc (non-diegetic) khớp từng mốc thời gian của visual.
5. **Detailed Description (Materiality/Lighting):** Phải đạt mức chi tiết cực cao (vd: "halftone dot pattern", "weathered white paint", "glossy black visor").

**Storyboard Reviewer phải reject nếu prompt:**
- Thiếu cấu trúc `<Subject X>` hoặc phân tích lưu giữ (Retention Analysis).
- Prompt cho shot dài mà thiếu mốc thời gian (At 0.0s, At 1.5s...).
- Mô tả âm thanh/nhạc không khớp hoặc chung chung.
- Thiếu chi tiết vật liệu (texture) hoặc ánh sáng (chỉ mô tả chung chung).

Agent cha BẮT BUỘC phải truyền prompt theo format này vào `scene_plan.json`.
       │                                              │
       ├──────── 3. Agent cha sửa chữa (Refine) ─────>│
       │     (Dựa trên chính xác feedback nhận được)  │
       │                                              │
       │<─────── 4. Re-review (Lần 2, tối đa 3 lần)───┤
       │                                              │
```

Lịch sử toàn bộ các lần review được tự động ghi nhận vào `artifacts/stage_reviews.json`.

---

## 3. RUBRIC CHẤM ĐIỂM CHI TIẾT THEO TỪNG STAGE

### A. Stage 2: Kịch Bản (Script Reviewer)
*Mục tiêu: Đảm bảo kịch bản chuẩn chuyển đổi cao, lời thoại tự nhiên của KOL Mai Ly, không bịa đặt số liệu.*

| Chiều kích đánh giá | Điểm tối đa | Tiêu chuẩn đạt |
|---|---|---|
| **1. Cấu trúc chuyển đổi 6 nhịp** | 2.5 | Beat 1 bắt buộc là Hook (thời lượng <= 4.0s). Beat cuối bắt buộc là CTA rõ ràng. Tổng 4-8 beats. |
| **2. Không bịa đặt & Khớp Brief (No-fabrication)** | 2.5 | Không tự bịa giá, voucher, % giảm giá, bảo hành, cam kết 5 sao nếu brief không cấp. Dùng đúng thông số USP. |
| **3. Giọng thoại KOL & Khớp nhịp nói (Pacing)** | 2.5 | Tiếng Việt tự nhiên, đàm thoại ấm áp của KOL. Thời lượng đọc (`estimate_speech_seconds`) <= thời lượng cảnh (`estimated_duration`). Không quá 22 từ/beat. |
| **4. Chỉ dẫn thị giác kịch bản** | 2.5 | `visual_cue` và `visual_cue_en` đầy đủ, mô tả rõ hành động chủ thể, không để trống. |
| **TỔNG ĐIỂM** | **10.0** | **Đạt khi: Tổng >= 8.0, Hook <= 4s, không có bịa đặt claim.** |

### B. Stage 3: Phân Cảnh & Prompt Tạo Video (Storyboard Reviewer)
*Mục tiêu: Đảm bảo prompt tạo video đủ chi tiết, dẫn xuất chính xác từ kịch bản, bối cảnh chuẩn cho KOL Mai Ly, triệt tiêu nguy cơ slideshow.*

| Chiều kích đánh giá | Điểm tối đa | Tiêu chuẩn đạt |
|---|---|---|
| **1. Khớp kịch bản 1:1** | 2.0 | Số lượng shot phân cảnh khớp 1:1 với số beat kịch bản. Mỗi shot giải quyết đúng mục tiêu tự sự (`narrative_purpose`). |
| **2. Nhất quán KOL & Bối cảnh (SET / WEAR)** | 2.5 | Tag nhân vật chuẩn `[KOL_MAIN]`. Bối cảnh (SET) và trang phục (WEAR) đúng archetype, không có 2 bối cảnh mâu thuẫn trong cùng một shot. |
| **3. Độ chi tiết của Video Prompt (6-Part)** | 3.0 | Prompt tạo video (`prompt_6part` và `visual_cue_en`) >= 25 từ, đủ 6 thành tố DramaClaw: Tỉ lệ 9:16 dọc, Nhân vật Mai Ly, Khóa diện mạo, Style ánh sáng/studio, Hành động động năng cụ thể (kinetic action, tránh thụ động), Chuyển động máy quay rõ ràng. |
| **4. Ngôn ngữ Camera & Nguy cơ Slideshow** | 2.5 | Khai báo rõ `camera_motion` (orbit, truck, pan, push-in...). Điểm Slideshow Risk <= 2.8/5.0, verdict: PASSED. Không bị cảm giác ảnh tĩnh zoom lướt. |
| **TỔNG ĐIỂM** | **10.0** | **Đạt khi: Tổng >= 8.0, prompt chi tiết, slideshow risk đạt chuẩn.** |

### C. Stage 4: Ảnh Keyframe & Khóa Nhận Diện (Keyframe Reviewer)
*Mục tiêu: Đảm bảo ảnh First Frame đúng diện mạo Mai Ly, ảnh sản phẩm độc lập, sạch watermark AI.*

| Chiều kích đánh giá | Điểm tối đa | Tiêu chuẩn đạt |
|---|---|---|
| **1. Khóa diện mạo KOL Mai Ly** | 3.0 | Neo mặt chuẩn vào `assets/characters/kol_main/face_anchor.png` và outfit sheet. Không trỏ ra asset ngoài repo. |
| **2. Cô lập sản phẩm (Product Isolation)** | 2.5 | Cảnh quay sản phẩm (`product_hero`) phải dùng ảnh sản phẩm thật, tuyệt đối không lấy chân dung người thay thế. |
| **3. Chất lượng ảnh & Khử Watermark** | 2.5 | Đúng tỉ lệ 9:16 dọc (1080x1920 pixels). Đã chạy thuật toán Telea Inpainting khử sạch watermark AI. Không có lỗi `synthesis_error`. |
| **4. Độ bao phủ phân cảnh** | 2.0 | Đủ First Frame sạch cho toàn bộ các shot chuẩn bị render video. |
| **TỔNG ĐIỂM** | **10.0** | **Đạt khi: Tổng >= 8.0, không có lỗi render, sạch watermark.** |

---

## 4. HỢP ĐỒNG GỌI CÔNG CỤ REVIEW TỰ ĐỘNG (`tools/review_stage.py`)

Cả Agent cha và Subagent có thể chạy công cụ chấm điểm độc lập qua CLI:

```bash
# Review kịch bản:
python3 tools/review_stage.py --stage script --workspace <workspace_path> --json

# Review phân cảnh và prompt video:
python3 tools/review_stage.py --stage storyboard --workspace <workspace_path> --json

# Review keyframe ảnh:
python3 tools/review_stage.py --stage keyframe --workspace <workspace_path> --json

# Review toàn diện:
python3 tools/review_stage.py --stage all --workspace <workspace_path> --json
```

### Bảng mã thoát của `review_stage.py`:
- **Exit 0 (`EXIT_APPROVED`):** Đạt chuẩn (Score >= 8.0). Sẵn sàng chuyển stage.
- **Exit 3 (`EXIT_NEEDS_REVISION`):** Chưa đạt (Score < 8.0). Cần Agent cha sửa chữa theo feedback.
- **Exit 2 (`EXIT_MISSING`):** Thiếu file artifact tiền đề (ví dụ chưa có `script.json`).
- **Exit 1 (`EXIT_FATAL`):** Lỗi crash kỹ thuật.

### Cấu trúc kết quả JSON:
```json
{
  "ok": false,
  "status": "needs_revision",
  "exit_code": 3,
  "average_score": 7.2,
  "max_iterations": 3,
  "stages_reviewed": [
    {
      "stage": "storyboard",
      "iteration": 1,
      "score": 7.2,
      "status": "needs_revision",
      "passed": false,
      "rubric_scores": {
        "script_alignment": 2.0,
        "kol_and_context_fit": 2.5,
        "video_prompt_detail": 1.5,
        "camera_motion_and_cinematography": 1.2
      },
      "problems": [
        "shot_02: Prompt 6-part quá ngắn (18 từ), thiếu chi tiết cho video model.",
        "shot_03: Thiếu chỉ đạo chuyển động camera (camera_motion)."
      ],
      "actionable_feedback": [
        "shot_02: Bổ sung chi tiết chuyển động, chủ thể, bối cảnh và ánh sáng vào prompt 6-part.",
        "shot_03: Khai báo rõ chuyển động máy quay (e.g. slow push-in, tracking pan)."
      ]
    }
  ]
}
```

---

## 5. MẪU PROMPT CHO SUBAGENT REVIEWER (TASK AGENT)

Khi Đạo Diễn AI kích hoạt Subagent qua tool `task`:

```markdown
# Context: Độc lập thẩm định chất lượng kịch bản / phân cảnh thương mại
Bạn là Chuyên Viên Thẩm Định Độc Lập (Senior Creative & Technical Reviewer). Bạn không được đồng thuận dễ dãi.
Nhiệm vụ: Đọc kịch bản/storyboard tại artifacts/, soi xét đối chiếu với brief và quy chuẩn KOL Mai Ly.

# Quy tắc chấm:
1. Chấm điểm trên thang 0 - 10 theo đúng rubric của Stage Review Protocol.
2. Nêu rõ từng vấn đề (problems) kèm số giây, tên shot cụ thể.
3. Cung cấp actionable feedback trực tiếp để tác giả (Agent cha) sửa được ngay.
4. Ngưỡng đạt: Điểm >= 8.0/10. Nếu trượt, ghi rõ "STATUS: NEEDS_REVISION".
```
