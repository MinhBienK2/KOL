# Vòng lặp QA tiền kỳ: brief → script → storyboard → gói prompt (không tạo ảnh/video)

Chạy trong session mới:
```
/loop Đọc và làm theo harness/preprod_qa_loop.md. Trả lời tôi bằng tiếng Việt.
```
Mỗi lần được đánh thức, **đọc lại file này và `projects/qa/preprod/state.json` trước tiên**.

## 0. Mục tiêu

Bạn là **khách hàng kiêm trưởng QA tiền kỳ**. omp là **đạo diễn**. Vòng này dừng ở bước **chuẩn bị tài
nguyên prompt** cho ảnh và video: **không** tạo keyframe, ảnh nhân vật, clip hay giọng (không Stage 4–8,
không gọi Flow2API/MiniMax). Mục tiêu là tiền kỳ tốt tới mức nếu bấm nút sản xuất thì ảnh và video có
lý do để đẹp: ý tưởng rõ, kịch bản có mạch, mỗi shot có ý đồ máy quay, mỗi prompt đúng loại (ảnh tĩnh
khác prompt chuyển động) và không tự mâu thuẫn.

Ba tầng cải thiện giống `harness/qa_loop_prompt.md` mục 0: (1) phản hồi omp làm lại bước, (2) sửa repo
từ nguyên nhân gốc (có test), (3) sửa chính file này.

Cơ sở nghiên cứu: `docs/research/preproduction_best_practices.md`. Mọi tiêu chí ở mục 3 nên dẫn về một
mục trong đó; khi phát hiện vấn đề mới mà chưa có căn cứ, research rồi bổ sung file đó.

## 1. Trạng thái (`projects/qa/preprod/state.json`)

```json
{"round": 1, "phase": "brief|stage1|stage2|stage3|prompt_pack|score|improve|done",
 "campaign": "pp_r1", "topic": "<archetype>", "run_dir": "projects/<topic>/pp_r1/runs/v1",
 "omp_session": "<.jsonl>", "consecutive_passes": 0, "attempts": {"stage2": 1}, "notes": "..."}
```

## 2. Một vòng

1. **Ra đề** `projects/qa/preprod/rN/BRIEF.md`: sản phẩm thật có ảnh (`input/product_hero.*`, chép vào
   `projects/<topic>/pp_rN/input/`), chữ in trên sản phẩm, claim được phép, claim cấm, nhân vật `kol_main`,
   khán giả, 20–30 s, 9:16. **Không** đưa ý tưởng, cảnh hay câu thoại: đó là việc của omp. Mỗi vòng đổi ít
   nhất hai biến (ngành hàng/archetype, khán giả, cảm xúc, bối cảnh, thời điểm, thể loại). Cài ít nhất một
   **bẫy** kiểm chứng được (mô tả shop sai so với ảnh, claim hấp dẫn nhưng không có căn cứ, chữ in khó).
2. **Giao omp** (chạy nền, log vào `projects/qa/preprod/rN/omp_turnK.log`):
   ```
   cd /home/minhbien/Documents/KOL && omp -p --auto-approve "<lệnh>" < /dev/null > projects/qa/preprod/rN/omp_turn1.log 2>&1
   ```
   Lệnh đầu = BRIEF + "Đọc harness/systemprompt.md, tool_guidance.md, guardrails.md. Dùng tools/director.py
   với `--campaign pp_rN --topic <archetype> --url <mô tả sản phẩm>`, chạy `--check` trước, rồi
   `--pause-after-stage 1`, dừng báo; sau đó Stage 2, Stage 3 cũng vậy. **Tuyệt đối không chạy Stage 4 trở
   đi** (không `--from-stage 4`, không tạo ảnh/video). Bạn là đạo diễn: dùng `--beats`, `--shot-overrides`,
   `--inject` để đưa ý đồ vào. Sau Stage 3 chạy `python3 tools/prompt_pack.py --run <run_dir>` và đọc
   `artifacts/prompt_pack.md`." Các lượt sau: `omp -c -p --auto-approve "<phản hồi>" < /dev/null`. **Luôn `< /dev/null`**: chạy nền không có
   nó thì omp treo vô hạn ở `phase: readPipedInput` (vòng 1 mất 30 phút). Log có dòng `Still starting` sau 60 s là treo.
3. **Duyệt từng bước** theo mục 3. Bước trượt thì gửi phản hồi cụ thể (sai gì, bằng chứng, yêu cầu gì) và
   omp làm lại; tối đa 3 lần mỗi bước. Một lỗi lặp 2 lần cùng nguyên nhân = lỗi hệ thống → sửa tầng 2.
4. **Gói prompt**: tự chạy lại `tools/prompt_pack.py` (không tin bản omp đưa), đọc **toàn văn** từng prompt.
5. **Chấm** (mục 4), **cải thiện** (mục 5), ghi sổ (mục 6).

Kiểm transcript omp: `grep -E "from-stage (4|5|6|7|8)|keyframe|flow2api|render" <log>`: thấy omp chạy
Stage ≥ 4 là lỗi Quy trình nặng (dừng tiến trình ngay).

## 3. Cổng duyệt (bạn tự đọc artifact, không tin omp tự khen)

### Stage 1 · `brief.json`, `competitor_research.json`, `creative_concept.json`
- USP và mọi thông số khớp ảnh + claim cho phép; không bịa giá, số, chứng nhận (kể cả trong research/concept).
- Persona cụ thể (ai, lúc nào, ở đâu, đang khó chịu điều gì) chứ không phải nhân khẩu học chung chung.
- Concept có **ý tưởng chủ đạo 1 câu** và một **hình ảnh then chốt** (visual hook) chứ không chỉ một câu VO.
- Whitespace thật: nêu được 2–3 sáo mòn của ngành hàng và concept tránh chúng.

### Stage 2 · `script.json`
- Hook 0–3 s bằng **hình** (và chữ/âm), không mở bằng chào hỏi; sản phẩm xuất hiện sớm (≤ 3–5 s hoặc có lý do).
- Mạch khán giả: dừng lướt → hiểu → tin → muốn → hành động. Ý tưởng chủ đạo hiện trong hình, có nỗi đau và
  phần thưởng; không đúng khuôn 6 nhịp một cách máy móc nếu concept cần cấu trúc khác.
- Thời gian vật lý nhất quán giữa các shot; mỗi shot **một hành động chính** vừa thời lượng clip (~6 s).
- VO tiếng Việt tự nhiên, nói được: ≤ ~4 âm tiết/giây; không kê lại điều hình đã nói; chỉ claim cho phép; không
  từ tuyệt đối ("nhất", "số 1", "100%", "tuyệt đối") (Luật Quảng cáo, xem research).
- CTA cụ thể, hợp kênh. Tổng thời lượng trong khoảng brief.

### Stage 3 · `scene_plan.json` (đọc **`prompt_6part` từng shot**) + `storyboard_contact_sheet.jpg`
- Mỗi shot minh họa đúng nhịp; cỡ cảnh/góc/ống kính/chuyển động máy **có động cơ** và đa dạng có chủ đích.
- Không mâu thuẫn trong prompt: một bối cảnh (SET), một kiểu tóc (WEAR vs identity), ánh sáng khớp thời điểm
  (giờ vàng/bình minh ~2500–3500 K, ban ngày trung tính ~5000–6500 K; không "studio portrait lighting" trong cảnh
  đời thường), vai nhân vật khớp hành động (đang bế con/lái xe thì không "direct eye contact, speaking").
- Liên tục: hướng nhìn, hướng chuyển động, đạo cụ, trang phục giữa các shot cùng bối cảnh.
- Sản phẩm: shot sản phẩm dùng ảnh sản phẩm thật, đúng chữ in/hình dáng; không có sản phẩm khi kịch bản là đồ cũ.
- Khung hình: ở frame đầu VÀ frame cuối, sản phẩm, bàn tay đang làm việc và miệng người nói có nằm trong cỡ cảnh
  không (medium cắt ngang eo, cowboy giữa đùi, wide toàn thân; khung chốt CTA phải thấy trọn sản phẩm).
- Trạng thái vật có thể xảy ra ở frame đầu (nắp còn đóng thì chưa thấy seal; seal còn dán thì chưa thấy kem) và đi đúng
  thứ tự qua các shot; tay luôn có điểm tựa (cầm quai, chạm vật), không chỉ trỏ giữa không trung; không orbit quanh
  người đang đi bộ.
- An toàn khung 9:16 (Meta Reels): mặt, sản phẩm, chữ in trong vùng y 14–65%, x 6–94% (tránh 35% dưới và mép phải nơi
  nút TikTok đè).

### Gói prompt · `artifacts/prompt_pack.json|md` (`tools/prompt_pack.py`)
- **Prompt ảnh (first frame)**: tả một khoảnh khắc tĩnh bằng câu văn; reference đúng vai (mặt / sản phẩm),
  đúng shot (shot đồ cũ không có ảnh sản phẩm); không tag rác ("8k", "masterpiece"); không mâu thuẫn.
- **Prompt video (I2V)** = `motion_prompt` của shot (từ `motion_cue_en` của beat, hoặc `motion_direction` +
  `camera_command` trong `--shot-overrides`): mở bằng lệnh máy quay Hailuo trong ngoặc vuông (`[Push in]`,
  `[Truck left]`, `[Pan left,Pedestal up]`, tối đa 3 lệnh đồng thời); rồi **một** hành động có từ chỉ tốc độ, chuyển
  động nền nếu có, **trạng thái kết thúc**; ~20–60 từ; không tả mặt, tóc, trang phục, bối cảnh, ánh sáng (ảnh đầu đã
  có); không đòi điều ảnh đầu không có; vật lý phức tạp (ném, nảy, rót) là rủi ro, cần lý do.
- Nhịp dựng: clip sinh ra 6 s nhưng shot dùng 1.5–4 s thì storyboard phải nói đoạn nào dùng (hành động chính rơi
  vào đoạn đó). ≥ 2 shot trong 5 s đầu (Google ABCD).
- Thời lượng, chế độ (I2V/R2V), model từng shot hợp lý; tổng thời lượng khớp kịch bản.

## 4. Thẻ điểm cuối vòng (0–10, mỗi điểm kèm bằng chứng: file, shot, câu trích)

1. Quy trình omp (đúng bước, dừng đúng, không chạy Stage ≥ 4, báo trung thực, ít thử mù).
2. Brief & concept. 3. Kịch bản. 4. Storyboard & ngôn ngữ máy quay. 5. Prompt ảnh. 6. Prompt video.
7. Tuân thủ (claim, Luật Quảng cáo, an toàn khung). 8. Sáng tạo: so với **mọi** vòng trước trong sổ và các
   campaign trong `projects/*/` (cấu trúc nhịp, motif, bối cảnh, máy quay, công thức VO/CTA); liệt kê điểm trùng.

**Đạt** khi: trung bình ≥ 8.5, không mục nào < 8, và omp không chạy Stage ≥ 4.

## 5. Cải thiện cuối vòng (bắt buộc)

- **Tầng 2** (repo: `pipeline/`, `tools/`, `harness/`, test): với mỗi lỗi, tìm nguyên nhân gốc (hướng dẫn mơ hồ,
  template sinh prompt sai, thiếu lint, LLM prompt kém), sửa ở gốc, có test, `python3 -m pytest -q` và
  `python3 tools/qa_regression.py` phải xanh. Lỗi do template (ví dụ câu cố định trong archetype) sửa template,
  không vá từng run. Không commit trừ khi người dùng bảo.
- **Tầng 3**: lọt lỗi (phát hiện muộn ở bước sau), báo động giả, kiểm tốn công vô ích, đề quá dễ → sửa mục 3 và
  ghi mục 7 bên dưới. Kiểm nào làm tay 2 lần thì tự động hóa (lint trong `tools/prompt_pack.py` hoặc pipeline).

## 6. Sổ và điều kiện dừng

Sổ: `projects/qa/preprod/ledger.md` (brief, lỗi theo bước, thẻ điểm có bằng chứng, sửa tầng 2/3, dấu vân tay
sáng tạo).

Dừng khi: **2 vòng liên tiếp đạt** và vòng gần nhất không phải sửa tầng 2; hoặc tối đa 6 vòng; hoặc bị chặn
(gateway LLM hỏng, omp không chạy được). Khi dừng: tắt loop, báo cáo bảng điểm qua các vòng, mọi sửa repo,
điểm mạnh/yếu còn lại, đề xuất.

Bất biến: không bao giờ chạy Stage ≥ 4 trong loop này; tiêu chí đạt chỉ được làm chặt hơn.

## 7. Nhật ký thay đổi

- 2026-10-22 · v3 · Vòng 3–4: thêm kiểm tra khung hình/trạng thái vật/điểm tựa tay vào cổng Stage 3; prompt_pack
  chạy gate slideshow của Stage 8 (gate cũ đọc sai trường sau khi tách motion_prompt nên từ chối nhầm).

- 2026-10-22 · v2 · Vòng 1: omp `-c` chạy nền treo ở `readPipedInput` 30 phút → bắt buộc `< /dev/null`.

- 2026-10-22 · v1 · Tạo. Phát hiện ban đầu khi đọc `qa_r1/v2` (đã "đạt" Stage 3 ở loop cũ): `prompt_6part` dùng
  chung cho ảnh và video; "studio portrait lighting" trong cảnh bếp; "8k"; vai
  presenter ("direct eye contact, speaking") ghép với hành động giữ tay con; "Căn Hộ Bắc Âu" cho bếp Việt.
