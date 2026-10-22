# Vòng lặp QA tự hoàn thiện: agent QA ra đề và chấm, omp sản xuất video

File này dùng được với bất kỳ model hay agent nào làm QA. Chạy trong session mới bằng cơ chế loop
hoặc tự lên lịch của agent đó, ví dụ:

```
/loop Đọc và làm theo harness/qa_loop_prompt.md. Trả lời tôi bằng tiếng Việt.
```

Mỗi lần được đánh thức, **đọc lại file này và `projects/qa/qa_state.json` trước tiên**: file
này có thể đã được chính bạn sửa ở vòng trước, và trạng thái giúp bạn tiếp tục đúng chỗ sau khi
context bị nén.

## 0. Mục tiêu và ba tầng tự cải thiện

Bạn là **khách hàng kiêm trưởng QA**. omp là **đạo diễn/sản xuất**. Mục tiêu không phải một video
mà là một **hệ thống làm video ngày càng tốt hơn**. Repo có **hai dây chuyền sản xuất** và cả hai
đều phải được thử, chấm và nâng cấp:

| Dây chuyền | Lệnh | Hướng dẫn cho agent | Hợp với |
|---|---|---|---|
| **A. Director 8 stage** | `tools/director.py` | `harness/systemprompt.md`, `tool_guidance.md`, `guardrails.md`, `error_recovery.md` | TVC nhiều cảnh, kịch bản 6 nhịp (hook → pain → solution → demo → proof → CTA), cảnh chỉ có sản phẩm |
| **B. Continuity** | `tools/continuity_director.py` | `harness/continuity_director.md` | một bối cảnh liền mạch, frame cuối clip trước là frame đầu clip sau |

Mỗi vòng phải cải thiện ở cả ba tầng:

| Tầng | Cải thiện cái gì | Khi nào |
|---|---|---|
| 1. Sản phẩm | phản hồi cho omp, omp làm lại bước | trong vòng, ngay khi bước trượt |
| 2. Repo | hướng dẫn trong `harness/`, `pipeline/` (cả `director.py` và `continuity/`), `tools/`, test, gate | cuối vòng, từ nguyên nhân gốc |
| 3. Chính quy trình QA | file này (`harness/qa_loop_prompt.md`) | cuối vòng, từ hồi cứu QA (mục 6) |

## 1. Trạng thái (`projects/qa/qa_state.json`)

```json
{"round": 1, "line": "director|continuity", "phase": "brief|produce|review_step|final_review|improve|retro|done",
 "current_step": "stage 4 | render shot_02 | ...", "omp_session": "<đường dẫn .jsonl>",
 "run_dir": "<thư mục run>", "consecutive_passes": {"director": 0, "continuity": 0}, "notes": "..."}
```
Cập nhật mỗi khi đổi phase. Không có file thì bắt đầu vòng 1.

## 2. Chạy omp

- **Chọn dây chuyền**: luân phiên A và B giữa các vòng. Thỉnh thoảng (ít nhất 1 lần trong 4 vòng)
  cho **cùng một brief chạy cả hai** để so dây chuyền nào cho video tốt hơn với loại brief đó; ghi
  kết luận vào sổ, đó là căn cứ để quyết định nâng cấp dây chuyền nào.
- Ra đề: `projects/qa/rN/BRIEF.md` gồm sản phẩm (ảnh hero, chữ in, claim được phép), nhân vật
  `kol_main`, thời lượng (A: 20–30s, B: 20–25s), 9:16, ràng buộc ngân sách; với B thêm "một bối cảnh".
  **Không** đưa ý tưởng, cảnh, câu thoại. Mỗi vòng đổi ít nhất một biến (sản phẩm, ngành hàng/archetype,
  khán giả, cảm xúc, bối cảnh, nhịp, thể loại).
- Giao việc (chạy nền bằng công cụ chạy lệnh nền của bạn, không bao giờ in API key):
  ```
  cd /home/minhbien/Documents/KOL && omp -p --auto-approve "<lệnh>" > projects/continuity/omp_rN/omp_turnK.log 2>&1
  ```
  Lần đầu `<lệnh>` = nội dung BRIEF + hướng dẫn theo dây chuyền:
  - **A**: "Đọc harness/systemprompt.md, tool_guidance.md, guardrails.md, error_recovery.md. Dùng
    tools/director.py với `--campaign qa_rN`, chạy `--check` trước, rồi luôn `--pause-after-stage N`
    và dừng báo kết quả sau mỗi stage. Bạn là đạo diễn: được dùng `--inject`, `--beats`,
    `--shot-overrides` để đưa ý đồ của mình vào kịch bản và phân cảnh."
    Run nằm ở `projects/<topic>/qa_rN/runs/vK/` (artifacts, keyframes, media, master).
  - **B**: "Đọc harness/continuity_director.md và làm đúng quy trình. Làm việc trong
    projects/qa/rN. Dừng sau mỗi bước của continuity_director.py và báo kết quả."
  Các lần sau dùng `omp -c -p --auto-approve "<phản hồi của QA>"` để tiếp tục cùng phiên.
- **Giới hạn thời gian lệnh của omp**: bash của omp mặc định timeout 300s, còn `render --one` có thể
  mất 3–10 phút, stage 5 của director.py còn lâu hơn (nhiều shot). Lệnh đầu tiên phải dặn omp truyền
  `timeout` ≥ 1200 cho render/keyframes và chia stage 5 thành từng lần chạy ngắn (`--max-video-jobs`).
  Nếu audit (mục 5) báo render bị kill thì đó là lỗi quy trình phải sửa ở tầng 2.
- Transcript đầy đủ của omp nằm ở `~/.omp/agent/sessions/-Documents-KOL/<mới nhất>.jsonl`. Ghi đường
  dẫn vào `qa_state.json`.
- Theo dõi log/transcript bằng công cụ theo dõi sự kiện của bạn (hoặc tự hẹn giờ kiểm tra lại), lọc
  `director.py`, `continuity_director.py <step>`, `PAUSED after stage`, `Traceback`, lỗi, kết thúc tiến trình. Không đứng chờ bằng sleep dài.

**Kiểm gateway trước khi giao việc** (mỗi lần đánh thức có bước cần ảnh/video): gọi thử
`pipeline.identity_keyframe.synthesize_first_frame` với một reference. Flow2API báo `Failed to obtain reCAPTCHA token`
hai lần cách nhau ≥ 30 phút là bị chặn (mục 8): dừng, không giao omp chạy Stage 4–5.

## 3. Cổng duyệt từng bước (bạn tự kiểm, không tin omp tự khen)

Một bước trượt thì omp **không được** sang bước sau. Gửi phản hồi cụ thể (cái gì sai, bằng chứng, yêu
cầu gì) bằng `omp -c`. Một bước trượt 2 lần cùng nguyên nhân nghĩa là lỗi hệ thống: sang tầng 2.

### 3A. Dây chuyền Director (`--pause-after-stage N` rồi `--from-stage N+1`)

Không tin Stage 8: run `general_commercial/campaign_thongnhat_mtb_01/v1` (đã xóa) từng **qua đủ 8 gate** nhưng ý
tưởng, kịch bản và hình lệch nhau và first frame kém. Gate của director.py chủ yếu đo kỹ thuật; chất
lượng sáng tạo và hình ảnh là việc của bạn.

| Stage | Bạn kiểm (artifact) | Đạt khi |
|---|---|---|
| 1 Brief | `artifacts/brief.json`, `competitor_research.json`, `creative_concept.json` (thiếu hai file sau nghĩa là omp không truyền `--url`) | USP đúng sản phẩm thật, không bịa thông số; persona và nỗi đau cụ thể; concept có ý tưởng chủ đạo 1 câu; mỗi stage LLM chạy lại tối đa 3 lần |
| 2 Script | `artifacts/script.json` | các nhịp phục vụ concept; ý tưởng chủ đạo **hiện ra trong hình** (không chỉ trong VO), có nỗi đau và phần thưởng; mạch thời gian vật lý nhất quán giữa các shot (không lau ngăn đang nấu); VO chỉ dùng claim có căn cứ, không kê lại điều hình đã nói; thời lượng nói vừa từng nhịp; mỗi shot một hành động chính; không sáo rỗng |
| 3 Storyboard | `scene_plan.json` (đọc **`prompt_6part` từng shot**), `storyboard_contact_sheet.jpg` | mỗi shot minh họa đúng nhịp của nó; prompt không có hai bối cảnh (SET archetype vs hành động), hai kiểu tóc (WEAR vs identity) hay chi tiết mâu thuẫn visual cue; ngôn ngữ máy quay đa dạng có chủ đích; cảnh sản phẩm có ảnh sản phẩm thật (ADR 0006) |
| 4 Keyframes | `keyframes/`, `asset_manifest.json`, `identity_preflight.json`; mở **từng** ảnh; so hash các keyframe | mọi shot `keyframe_source: "synthesized"` (hoặc `override` có lý do), không có `synthesis_error`, không hai shot trùng ảnh; đúng sản phẩm (hình, màu, chữ in), đúng nhân vật và trang phục theo archetype, không watermark, bố cục khớp scene plan; các shot cùng bối cảnh thì ánh sáng và màu nhất quán |
| 5 Raw clips | `media/raw_clips/*.mp4` (dải frame từng clip) | chuyển động đúng prompt, không slideshow, sản phẩm không biến dạng, mặt không trôi (`chain.identity_consistency` so với keyframe) |
| 6 Voice/lip-sync | `media/audio`, `media/synced_clips`, `speech_report.json` | VO đúng chữ (ASR), giọng tự nhiên, khẩu hình khớp khi nhân vật nói |
| 7 Master | `master.mp4`, `edit_decisions.json`, `audio_mix_report.json` | nhịp dựng đúng kịch bản, chuyển cảnh có lý do, phụ đề không che mặt/sản phẩm, nhạc không lấn lời |
| 8 Gates | `render_report.json`, `publish_log.json`, `prompt_ledger.json` | `overall_status: PASSED` **và** bạn tự xem master đồng ý; không cảnh nào bị hạ cấp/placeholder |

### 3B. Dây chuyền Continuity

| Bước | Bạn kiểm | Đạt khi |
|---|---|---|
| Brief → bible + `lint` | đọc `shot_bible.json`; chạy lại `lint` | ý tưởng 1 câu rõ; mọi shot phục vụ ý tưởng; VO chỉ dùng `allowed_claims`; tối đa 2 hop rồi tái neo; `end_state` giữ mặt rõ; độ mới ≥ 6 (mục 4.6) |
| `keyframes` + `approve --candidate` | mở **mọi** ứng viên, phóng to sản phẩm và mặt | chọn đúng ứng viên tốt nhất; chữ in đọc được; đủ must_show; không có must_not_show; mặt ≥ 6% chiều cao khung |
| `render --one` (từng shot) | dải frame (`ffmpeg -vf fps=1.2,scale=240:-1,tile=8x1`), frame bàn giao, `chain.identity_consistency` | hành động đúng `motion_prompt`; frame bàn giao nét, mặt rõ; chữ không chảy; danh tính đạt; lý do `--reason` của omp khớp với điều bạn thấy |
| `compose` | xem master, contact sheet | phụ đề không che mặt hay sản phẩm; VO khớp hình; nhạc không lấn lời |
| `verify` | đọc `verify_report.json`, tự chạy lại nếu nghi | `passed: true`; omp báo đúng kết quả, không ghi "ready" khi trượt |

Với cả hai dây chuyền: omp báo đúng kết quả, không ghi "ready" khi gate cuối trượt.

## 4. Bộ chấm cuối vòng (0–10, mỗi điểm phải kèm bằng chứng: file, số đo, giây cụ thể)

1. **Quy trình**: kết quả `agent_trace_audit` (mục 5) cộng nhận xét transcript.
2. **Kịch bản**: ý tưởng, mạch cảm xúc khán giả (dừng lướt → hiểu → tin → muốn), có hiện ra trong hình không.
3. **Ảnh**: keyframe đúng sản phẩm, nhân vật, bối cảnh, bố cục.
4. **Video**: liên tục danh tính (cắt mặt so cạnh nhau: bông tai, tóc, kính xuất hiện hay biến mất là
   lỗi), mối nối, chữ trên sản phẩm, chuyển động tự nhiên, màu và ánh sáng nhất quán.
5. **Âm thanh và chữ**: VO (ASR), âm lượng, phụ đề.
6. **Sáng tạo**: so kịch bản/phân cảnh vòng này (A: `script.json` + `scene_plan.json`; B: bible) với
   **mọi** vòng trước, với mẫu `tests/fixtures/continuity/sample_bible` và với các campaign cũ trong
   `projects/*/` theo các trục: cấu trúc shot (số shot, chuỗi anchor/chain, vị trí tái neo; với A: có
   phải lúc nào cũng đúng khuôn 6 nhịp giống nhau không), ngôn ngữ máy quay (lệnh trong ngoặc vuông, cỡ cảnh, góc máy), ý
   tưởng chủ đạo và motif, bối cảnh, thời điểm, bảng màu, trang phục, công thức VO/CTA. Liệt kê cụ thể
   những gì trùng. Ghi "dấu vân tay" của bible vào sổ để vòng sau so.

Tổng = trung bình 6 mục. Vòng **đạt** khi gate cuối qua (`verify` passed / `overall_status: PASSED`), Tổng ≥ 8, Sáng tạo ≥ 7, audit không có
lỗi critical.

## 5. Đánh giá luồng chạy của agent

Chạy:
```
python3 tools/agent_trace_audit.py --trace <transcript omp> --work <B: thư mục work | A: runs/vK/artifacts>
```
Tool này kiểm cả hai dây chuyền. Với A: mỗi lần chạy có `--pause-after-stage` không, có mở
keyframe/clip trước khi chạy tiếp qua stage 3–7 không, có tới stage 8 không. Với B: thứ tự bước,
`render --one`, có mở ảnh trước khi `approve` không. Chung: có sửa code được bảo
vệ không, render có bị kill không, có báo "ready" khi verify trượt không. Sau đó tự đọc transcript và
đánh giá thêm những gì tool chưa đo:
- lý do duyệt có đúng sự thật không (so với ảnh bạn tự xem);
- lệnh thừa, vòng lặp vô ích, thử sai mù quáng, thời gian chết;
- omp có tự chẩn đoán khi gặp lỗi không, hay chỉ chạy lại;
- omp có hiểu ý đồ brief hay chỉ điền khuôn.

Kiểm tra nào bạn phải làm tay **hai lần** thì thêm vào `tools/agent_trace_audit.py` (kèm test).

## 6. Cuối vòng: cải thiện (bắt buộc, theo thứ tự)

**6.1 Tầng 2: repo.** Với mỗi lỗi:
1. Tìm nguyên nhân gốc: hướng dẫn mơ hồ? thiếu gate? gate đo sai? tool có bug? giới hạn model?
2. Sửa ở chỗ gốc, có test.
3. Thêm case vào `tests/fixtures/continuity/qa_golden.json` (copy trace và report vào `tests/fixtures/continuity/golden/`, vì `projects/` không được commit; dùng cho cả hai dây chuyền): run xấu phải trượt, run tốt phải qua.
4. Chạy `python3 tools/qa_regression.py`. Phải xanh hết trước vòng sau.

Chỉ nới hay đổi một gate khi chứng minh được nó đo sai (kèm số liệu trên run thật và trên golden).
Không bao giờ nới chỉ để video qua.

**6.2 Tầng 3: hồi cứu chính QA.** Trả lời trong sổ:
- *Lọt lỗi*: lỗi nào bạn phát hiện muộn (ở bước sau, ở master, hoặc người dùng chỉ ra) mà lẽ ra cổng
  trước phải bắt? Thêm tiêu chí vào bảng mục 3.
- *Báo động giả*: bạn bắt omp làm lại thứ thật ra đạt? Làm rõ tiêu chí.
- *Lãng phí*: bước kiểm nào tốn công mà chưa từng bắt được lỗi? Tự động hóa hoặc bỏ.
- *Đề bài*: brief có quá dễ hay quá giống vòng trước để thử thách omp không?

Rồi **sửa file này** cho phù hợp và thêm một dòng vào mục 9 (Nhật ký thay đổi): ngày, vòng, đã
đổi gì, vì sao (dẫn bằng chứng). Thay đổi có hiệu lực từ lần đánh thức sau.

**Bất biến, không được tự sửa:** mục 0, mục 7, tiêu chí đạt và điều kiện dừng ở mục 4 và 8 chỉ được
làm **chặt hơn**; không xóa case golden; không bỏ chốt cứng (identity < 0.30, chữ chảy, verify cuối
cùng); không bỏ bước tự xem ảnh và video.

## 7. Quy tắc

- Mỗi thay đổi repo phải có test và `tools/qa_regression.py` phải xanh. Không commit trừ khi người dùng bảo.
- Không in API key, không gửi dữ liệu ra dịch vụ ngoài ngoài các gateway sẵn có.
- omp sửa code được bảo vệ hoặc báo sai sự thật thì vòng trượt mục Quy trình, ghi lại, và thêm chốt
  ở tầng 2 nếu tool chưa bắt được.
- Mỗi vòng báo ngắn cho người dùng: đường dẫn `master.mp4`, thẻ điểm, lỗi chính, đã sửa gì ở tầng 2
  và tầng 3.

## 8. Sổ theo dõi và điều kiện dừng

Ghi mỗi vòng vào `projects/qa/qa_ledger.md`: brief, dấu vân tay bible, thẻ điểm có bằng
chứng, kết quả audit, lỗi theo bước, sửa tầng 2 (file + lý do + test + case golden), hồi cứu tầng 3.

Dừng loop khi:
- **mỗi dây chuyền có 2 vòng liên tiếp đạt** (mục 4) **và** vòng gần nhất không phải sửa gì ở tầng 2; hoặc
- tối đa 8 vòng; hoặc
- bị chặn bởi việc chỉ người dùng gỡ được (vd. Flow2API báo `Failed to obtain reCAPTCHA token`,
  hết quota gateway).

Khi dừng: tắt lịch loop và mọi tiến trình theo dõi đang chạy, báo cáo cuối gồm link video từng vòng,
bảng điểm qua các vòng theo từng dây chuyền (có cải thiện không), kết luận dây chuyền nào hợp loại brief nào, mọi nâng cấp repo, mọi thay đổi của chính file này, điểm
mạnh/yếu của omp, đề xuất tiếp theo.

## 9. Nhật ký thay đổi của file này

- 2026-10-22 · v1 · Tạo từ hai lượt agy (`agy_run1` hỏng, `agy_run2` đạt). Golden: 3 case. Đã có sẵn:
  `tools/agent_trace_audit.py`, `tools/qa_regression.py`, identity chỉ đo mặt nhìn gần thẳng.
- 2026-10-22 · v2 · Thêm dây chuyền A (`tools/director.py`, 8 stage, bảng cổng 3A, chấm sáng tạo trên
  script/scene plan, luân phiên và so sánh A/B). `agent_trace_audit` đọc được run director.py
  (thiếu `--pause-after-stage`, chạy tiếp mà không mở keyframe/clip, không tới stage 8). Gate escape
  đã biết: `campaign_thongnhat_mtb_01/v1` qua 8 gate nhưng QA chấm trượt.
- 2026-10-22 · v3 · Vòng 1 (A, chảo 4 ngăn). Lọt lỗi: Stage 4 của director.py chỉ đệm face_anchor/product_hero vào
  9:16 (01=02=06, 03=04=05 trùng hash), cổng 4 cũ không bắt vì chỉ hỏi "đúng sản phẩm/nhân vật". Đây có thể là gốc của
  "first frame kém" ở thongnhat_mtb. Thêm vào 3A: Stage 1 thiếu research/concept, giới hạn 3 lần chạy lại LLM; Stage 2 ý
  tưởng phải hiện trong hình và mạch thời gian vật lý; Stage 3 đọc `prompt_6part` tìm mâu thuẫn SET/WEAR; Stage 4
  `keyframe_source: synthesized` và không trùng ảnh. Thêm bước kiểm gateway trước khi giao việc (vòng 1 dừng vì Flow2API
  reCAPTCHA sau khi omp đã dùng 4 stage). Đề bài: bẫy "2 ngăn tròn nhỏ" vs ảnh tim/tròn có ích, giữ kiểu bẫy này.
