# Pre-production Best Practices: AI KOL 9:16 Product Commercials

Researched: 2026-10-22. Scope: brief → script → storyboard → keyframe (Gemini image) → I2V (MiniMax Hailuo 2.3).
Every rule is phrased as a checkable criterion and links to its source.

Confidence tags:
- **[official]**: from the vendor's or regulator's own docs.
- **[secondary]**: from a reputable third party, not confirmed against the primary source.
- **[inference]**: our own synthesis of several sources. Check it with an A/B test before you rely on it.

---

## 0. Headline finding: split the keyframe prompt from the motion prompt

The current pipeline sends one long prompt (identity + set + wardrobe + action + camera) to both the keyframe model and the I2V model. Every I2V guide we found says this is wrong:

- Runway: in image-to-video, the image already sets subject, composition, lighting and style. The text prompt should be almost entirely about motion, and you do not need to describe the image's contents. [official, via search snippet; page returned 403 to fetch] https://help.runwayml.com/hc/en-us/articles/39789879462419
- Kling: "Subject + Movement". Do not describe the scene, because the image already supplies it. A prompt that contradicts the image can trigger a **camera cut or transition**. [official] https://kling.ai/quickstart/image-to-video-guide
- Hailuo third-party guides: re-describing static elements wastes tokens and confuses the motion generator. [secondary] https://akool.com/blog-posts/minimax-hailuo-video-prompt-guide

Checklist:
- [ ] The storyboard stores **two** prompts per shot: `keyframe_prompt` (the full still description) and `motion_prompt` (motion only). [inference from the three sources above]
- [ ] The `motion_prompt` contains no identity description (face, hair, ethnicity), no wardrobe, and no set description. It refers to the subject only by a short handle such as "the woman" or "the bottle". [official: Kling, Runway]
- [ ] Nothing in the `motion_prompt` contradicts the first frame. For example, it must not name a different outfit, location or time of day, which risks an unwanted cut. [official: Kling]

---

## 1. Image-to-video prompting (MiniMax Hailuo 2.3, plus Runway, Kling and Veo)

### 1.1 MiniMax Hailuo 2.3 API facts [official] https://platform.minimax.io/docs/api-reference/video-generation-i2v
- [ ] The prompt is **≤ 2,000 characters**, which is the hard limit.
- [ ] Model names are `MiniMax-Hailuo-2.3` and `MiniMax-Hailuo-2.3-Fast`. Duration is 6 s (default) or 10 s. **1080P is available only at 6 s**, and 10 s runs only at 768P.
- [ ] Camera moves use the bracket commands, which are more accurate than free text. The 15 commands are:
  `[Truck left]` `[Truck right]` `[Pan left]` `[Pan right]` `[Push in]` `[Pull out]` `[Pedestal up]` `[Pedestal down]` `[Tilt up]` `[Tilt down]` `[Zoom in]` `[Zoom out]` `[Shake]` `[Tracking shot]` `[Static shot]`.
- [ ] Simultaneous moves go **inside one bracket**, comma-separated, e.g. `[Pan left,Pedestal up]`, with **≤ 3** moves per bracket.
- [ ] Sequential moves are written in time order in the prose, e.g. `... [Push in], then ... [Pull out]`.
- [ ] The command sits **at the point in the sentence where the move happens**. The source for this is the Replicate readme for the Director model; we assume it carries over to 2.3. [secondary] https://replicate.com/minimax/video-01-director/readme
- [ ] `prompt_optimizer` is a deliberate choice. It defaults to `true` and rewrites your prompt. Set it to `false` when the exact wording and bracket commands must be kept. [official]
- [ ] Spelling matters: use `[Push in]` / `[Pull out]` for dolly moves and `[Zoom in]` / `[Zoom out]` for focal-length changes, because they are separate commands. Veo's guide draws the same zoom vs dolly distinction. [official] https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/video-gen-prompt-guide
- MiniMax says 2.3 improves physics, command following, body motion and micro-expressions. The announcement gives no prompting rules. [official] https://www.minimax.io/news/minimax-hailuo-23

### 1.2 Content of a motion prompt
- [ ] Structure: **subject handle + one action (verb + adverb) + camera command + optional background motion + end state**. Kling's formula is "Subject + Movement, Background + Movement". [official: Kling] The end state is our addition. [inference]
- [ ] Each clip has **one primary action**. If several subjects move, list them in order. [official: Kling; secondary: Artlist https://artlist.io/ai/models/hailuo]
- [ ] Action verbs are concrete and physically plausible. "She lifts the bottle to eye level with her right hand" beats "she shows the product". Kling: vague prompts make the model treat the photo as a still and give static or pan-only output. Complex physics such as throwing or bouncing is unreliable. [official: Kling]
- [ ] Use simple words and short sentences. Full sentences work better than comma tags. [official: Kling; secondary: Akool]
- [ ] Speed and pacing are stated explicitly ("slowly", "in one smooth motion", "gentle"). Veo lists pacing as a prompt element, and subtle actions like a slow blink add life. [official: Veo guide]
- [ ] The prompt names the **ending pose or framing**, e.g. "...ending with the label facing camera, centered". This lets the next shot's keyframe match it for match-on-action. [inference]
- [ ] Phrasing is positive. Veo says to avoid "no" or "don't" and to describe what you want. Runway and Google image docs say the same. [official: Veo guide]
- [ ] Length: there is no official word count. Aim for **~20–60 words / under 400 characters** for a 6 s clip. One community post suggests 80–120 words [secondary, low confidence] and Hedra suggests <200 words [secondary]. Start simple and add one layer at a time (subject motion → camera → scene motion → style), as Runway advises. [official via snippet: Runway] [length = inference]
- [ ] Lip-sync or dialogue lines are kept out of the Hailuo prompt. Hailuo 2.3 does not generate native audio in this API. VO and lip-sync are separate stages. [inference from API doc parameters]

Example motion prompt (≈45 words):
`The woman smiles, then slowly raises the serum bottle from her chest to beside her cheek with her right hand, turning the label toward camera. Her hair moves slightly in the breeze. [Push in] Ends on a medium close-up, label centered and sharp.`

---

## 2. Keyframe stills: Gemini Flash Image ("Nano Banana")

Sources:
- Google Developers blog [official] https://developers.googleblog.com/en/how-to-prompt-gemini-2-5-flash-image-generation-for-the-best-results/
- Google Cloud "Ultimate prompting guide for Nano Banana" [official] https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-nano-banana
- Gemini API image-generation docs [official] https://ai.google.dev/gemini-api/docs/image-generation

### 2.1 Prompt style
- [ ] The prompt is a **narrative paragraph, not a keyword list**: "Describe the scene, don't just list keywords." [official]
- [ ] It follows Google's photoreal template: "A photorealistic [shot type] of [subject] in [setting]. [Light description]. Shot from a [camera angle] with a [lens type]." [official: API docs]
- [ ] It states context and intent, e.g. "a frame for a 9:16 TikTok skincare ad, with empty space in the top third". Google's own example is that a "high-end, minimalist skincare brand" logo beats a bare "logo". [official]
- [ ] It uses photographic terms: shot scale, angle ("low angle", "eye-level"), lens ("85mm portrait", "macro", "wide-angle"), aperture ("shallow depth of field (f/1.8)"), lighting ("three-point softbox", "golden hour backlight") and film or camera look ("Fujifilm colour", "disposable-camera flash" for a UGC feel). [official: Cloud guide]
- [ ] Materials are named precisely, e.g. "frosted glass dropper bottle" rather than "bottle". [official: Cloud guide]
- [ ] Negatives are phrased positively, e.g. "empty street" not "no cars", "plain unbranded background" not "no text". [official]
- [ ] There are **no "8k / 4k / masterpiece / ultra-detailed" tags**. Google's guides never recommend them, and resolution is an API parameter (`image_size` "1K"/"2K"/"4K", uppercase K). Treat such tags as no-ops at best. [official for the parameter; "no-op" = inference]
- [ ] Aspect ratio is set via `aspect_ratio: "9:16"` in config. 9:16 is supported. Do not rely on prompt text alone. **When reference images are given, the output may adopt the aspect ratio of the last input image**, so set it explicitly, or make the last reference 9:16. [official: Dev blog, API docs]

### 2.2 Multiple reference images (face anchor + product hero)
- [ ] Each reference's **role is named in the prompt**: "[Reference images] + [Relationship instruction] + [New scenario]". For example: "Use image 1 as the woman's face and identity; use image 2 as the exact product, keeping its label, shape and colour unchanged; place her in ...". [official: Cloud guide]
- [ ] The number of references stays within the model limit. Docs list up to 14 references total. For 3.1 Flash Image the table reads roughly **≤ 10 object images and ≤ 5 character images**. [official; table was flattened in our fetch, so re-check the docs]
- [ ] The prompt says what must stay **exactly the same** (face, product label, logo) when editing or compositing. [official: API docs editing section]
- [ ] When identity drifts after many edit turns, restart a fresh conversation with a full description and the references, instead of continuing to patch. [official: Dev blog]
- Note: Google's API docs (as fetched 2026-10-22) call `gemini-3.1-flash-image` "Nano Banana 2" and recommend a newer "Nano Banana 2.1" for new projects. Evaluate before switching. [official, verify]

### 2.3 Text in frames
- [ ] The keyframe contains **no burned-in captions or prices**. Captions are added in post so they stay legible, editable and inside the safe zone. [inference] If text must be rendered, put it in quotes, describe the font, and generate the text concept first. [official: Cloud guide]
- [ ] Product label text comes from the product reference image, not from prompt text. This avoids misspelled brand names. [inference]

---

## 3. Short-form ad creative (TikTok, Meta Reels, YouTube ABCD)

### 3.1 Hook and brand timing
- [ ] Shot 1 hooks in ≤ 3 s. TikTok: "Introduce your content proposition in the first 3 seconds" and "prioritize your hook in the first 6 seconds". [official] https://ads.tiktok.com/help/article/creative-best-practices
- [ ] The **product or brand appears in the first 5 s**. [official: Google ABCD] https://thinkwithgoogle.com/_qs/documents/8472/ABCD_Complete_V7b_HR_1.pdf
- [ ] There are **≥ 2 shots in the first 5 s**. ABCD reports this as a positive factor for ad recall and consideration. [official: ABCD]
- [ ] The video opens with the KOL's **face on screen**, addressing the viewer directly where it fits. "Faces attract immediate attention." [official: ABCD]
- [ ] Framing on the person or product is tight, with non-obscure angles. [official: ABCD]
- [ ] The **KOL says the brand name on camera**. Brand audio mentions by on-screen people are more impactful. [official: ABCD]
- TikTok Creative Codes reportedly says 90% of ad-recall impact is captured in the first 6 s. [secondary] https://ads.tiktok.com/business/library/Creative_Codes_ENG.pdf

### 3.2 Structure, pacing, CTA
- [ ] The script follows **hook → USPs → clear CTA**. [official: TikTok]
- [ ] The CTA is specific and reinforced by a text card or VO, ideally with urgency (offer or deadline). [official: ABCD "Direct"]
- [ ] Pacing is fast. Neither TikTok nor Google gives an official cuts-per-second figure. For 20–30 s, aim for a new shot about every **1.5–3 s (≈ 8–15 shots)**. [inference] The ≥ 2 shots in 5 s rule is the only official number. Note that each 6 s Hailuo clip will usually be **trimmed** to 1.5–3 s in the edit. Storyboard the useful window, not the full 6 s.
- [ ] On-screen text runs at **5–10 words per second at most**. [official: TikTok]
- [ ] The video is planned **sound-on** (VO + music + SFX). TikTok treats sound as a basic requirement. YouTube reports 95% of watched video is played with sound on. [official: TikTok, ABCD]
- [ ] Captions or subtitles are present. They are recommended, not required, by Meta. [official: Meta ads guide]
- [ ] The look is native and creator-led: "DIY or not overly polished", a real person talking to camera, trends where they fit. [official: TikTok] For the AI KOL this argues for handheld-feel, natural-light, eye-level framing over glossy studio CGI in most shots. [inference]
- [ ] 3–5 creative variants are produced per ad group, with "big differences" between them for testing. [official: TikTok]

### 3.3 9:16 specs and UI safe zones
- [ ] Delivery is 9:16, ≥ 720p (TikTok minimum). Our 1080×1920 is fine. [official: TikTok] Meta lists H.264 and AAC stereo ≥ 128 kb/s. [official] https://www.facebook.com/business/ads-guide/update/video/instagram-reels
- [ ] Captions, logo, product label and face sit **outside the top 14%, the bottom 35% and 6% on each side**, which is Meta's Reels safe zone. On 1080×1920 that means y ≈ 269–1248 px and x ≈ 65–1015 px. [official: Meta]
- [ ] TikTok's safe zone also clears the **right-side action column** (like/comment/share). Third-party readings of TikTok's template differ (e.g. top ~130–240 px, bottom ~480–660 px, right ~140 px at 1080×1920). Using Meta's stricter box plus a clear right margin is the safe superset. [secondary] https://www.socialync.io/tools/safe-zones/tiktok
- [ ] Keyframe prompts for talking shots place the face in the **upper-middle** of the frame (eyes ≈ 30–40% from top), leaving the lower third free for captions above the UI band. [inference from the safe-zone geometry]

---

## 4. Storyboard and shot-list craft

### 4.1 Shot design
- [ ] Each shot has **one clear action** and one camera behaviour. This matches the I2V one-action rule in §1.2. [official: Kling; craft convention]
- [ ] Shot scale varies across adjacent shots (e.g. MCU → ECU product → MS). Avoid cutting between two shots of the same scale and angle on the same subject, which reads as a jump cut. [craft convention; secondary] https://www.studiobinder.com/blog/what-is-continuity-editing/
- [ ] Every camera move is **motivated** by revealing the product, following a hand, or emphasising a reaction. `[Static shot]` is a valid choice for talking-head lines. [craft convention / inference]
- [ ] A product hero shot exists by ~5 s and again at the CTA. It is a tight or macro frame, sharp focus on the label or key detail, with clean studio-style light. Google's product-mockup template uses "three-point softbox" and "sharp focus on [key detail]". [official: Gemini API docs; ABCD]

### 4.2 Continuity
- [ ] **180° rule**: all shots in a scene keep the camera on one side of the axis between the KOL and what she interacts with (camera or product), so left and right stay consistent. [secondary] https://en.wikipedia.org/wiki/180-degree_rule
- [ ] **Screen direction**: a hand or product moving left→right in shot N keeps that direction in shot N+1. [secondary] https://howtofilmschool.com/dictionary/180-degree-rule/
- [ ] **Eyeline match**: if the KOL looks off-screen at the product, the next shot shows the product from a matching direction and height. [secondary: StudioBinder]
- [ ] **Match on action**: when cutting mid-action, shot N's motion prompt end state equals shot N+1's keyframe start pose (same hand, same product orientation). [secondary] https://www.descript.com/blog/article/the-importance-of-continuity-editing-in-film-and-video
- [ ] Wardrobe, hair, props and product position are fixed per scene in a continuity sheet and reused verbatim in every `keyframe_prompt` (not in motion prompts). [inference]

### 4.3 Light and colour consistency
- [ ] Each scene declares **one** key-light colour temperature and time of day, and every keyframe in that scene uses it. Reference values: tungsten ~3200 K (warm), daylight ~5500–5600 K (neutral), overcast or shade ~6500 K+ (cool), golden hour ~3000–3500 K. [secondary] https://cloud.wikis.utexas.edu/wiki/spaces/rtf318/pages/80023039 , https://www.backstage.com/magazine/article/what-is-color-temperature-75608/
- [ ] "Morning daylight" scenes don't mix with "warm tungsten lamp" descriptions unless a practical lamp is a deliberate, motivated second source. [craft convention]
- [ ] Light direction (e.g. "soft window light from frame left") stays the same across shots in a scene, consistent with the 180° axis. [craft convention / inference]

---

## 5. Vietnamese advertising law: script checks

**Legal basis:** Luật Quảng cáo 16/2012/QH13, as amended by **Luật 75/2025/QH15, in force since 01/01/2026**. Amended article numbers may shift, so consult the consolidated text before final legal review. This section is **not legal advice**.
- Article 8 (2012): [secondary translation] https://hethongphapluat.com/law-no-16-2012-qh13-ofjune-21-2012-on-advertising/dieu-8
- English text: https://thuvienphapluat.vn/van-ban/EN/Thuong-mai/No-16-2012-QH13-On-advertising/142879/tieng-anh.aspx
- Summary of the 2025 amendments: https://luatvietnam.vn/linh-vuc-khac/diem-moi-cua-luat-quang-cao-sua-doi-2025-883-102813-article.html

### 5.1 Claims and wording
- [ ] **No "nhất", "duy nhất", "tốt nhất", "số một" or equivalent** ("đỉnh nhất", "No.1", "#1") unless the brief supplies legal proof (Art. 8(11)). Per Thông tư 10/2013/TT-BVHTTDL, valid proof is a market survey by a lawful market-research organisation, or a certificate from a regional or national contest or exhibition. It is valid **1 year** and the source must be cited in the ad. [secondary] https://luatvietnam.vn/tin-phap-luat/khi-nao-duoc-dung-tu-nhat-so-1-trong-quang-cao-230-18080-article.html
- [ ] No claim is untrue or misleading about quality, price, function (công dụng), origin, packaging or warranty versus what is registered or declared (Art. 8(9)). Every functional claim in VO must trace to the brief's product documents. [secondary]
- [ ] **No direct comparison** of price, quality or effectiveness with a named or identifiable competitor (Art. 8(10)). [secondary]
- [ ] No content that is discriminatory, culturally offensive or reinforces gender stereotypes (Art. 8(3), 8(6)). [secondary]
- [ ] No real person's image, voice or writing is used without consent (Art. 8(8)). This matters for face anchors: the AI KOL must not resemble a real identifiable person without a licence. [secondary; resemblance point = inference]

### 5.2 KOL and online-ad duties (2025 amendment)
- [ ] The ad is **clearly labelled as advertising** before and during the content, with a clear identifier in text, symbol, image or sound (amended Art. 23, new Art. 15a). [secondary] https://lsvn.vn/mang-xa-hoi-phai-co-tinh-nang-giup-phan-biet-noi-dung-quang-cao-a162505.html
- [ ] "Người chuyển tải sản phẩm quảng cáo" (influencer / KOL) duties: verify the advertiser, check product documents, and do not endorse products not used or understood. False advertising risks fines, correction orders and compensation (Art. 15a). How this applies to a **virtual / AI KOL** is untested. Treat the brand as fully responsible and avoid first-person "I've used this for 3 months" testimony unless it is true for the brand. [secondary; AI-KOL point = uncertain] https://voh.com.vn/phap-luat/nguoi-chuyen-tai-quang-cao-ai-duoc-lam-va-phai-chiu-trach-nhiem-gi-tu-nam-2026-646186.html
- Implementing decree was in draft at the time of the sources we read. Check for issued guidance. [uncertain]

### 5.3 Category rules
- [ ] **Health-protection food / supplements (TPBVSK)**: ad content is **registered (xác nhận nội dung) before running**. Claims match the declared uses exactly. The mandatory line **"Thực phẩm này không phải là thuốc, không có tác dụng thay thế thuốc chữa bệnh"** is shown clearly in contrasting colour (and read aloud in audio ads, per secondary sources). There are no images or names of doctors, pharmacists, medical staff or facilities. Basis: Nghị định 15/2018/NĐ-CP Art. 26–27. Fine for a missing disclaimer is 10–20 million VND. [secondary] https://luatminhkhue.vn/muc-xu-phat-danh-nghiep-quang-cao-thuc-pham-bao-ve-suc-khoe-khong-khuyen-cao.aspx , https://lsvn.vn/bac-si-duoc-si-nhan-vien-y-te-khong-duoc-tham-gia-quang-cao-thuc-pham-thuc-pham-chuc-nang-a156624.html
- [ ] **Cosmetics**: no wording or visuals that imply the product is a drug or treats disease (e.g. "trị mụn", "chữa nám", "điều trị"). Claims stay within the cosmetic notification (Thông tư 06/2011/TT-BYT, ad-content article). [secondary; check current validity] https://caselaw.vn/van-ban-phap-luat/268290-thong-tu-06-2011-tt-byt-quy-dinh-ve-quan-ly-my-pham-do-bo-y-te-ban-hanh
- [ ] **Children**: nothing leads children to think, speak or act against ethics or customs, or harms their health, safety or development (Art. 8(14)). Avoid children in supplement, cosmetics or food-claim scenes. Breast-milk substitutes and products for children under 24 months have separate strict bans; flag these and do not script them. [secondary; the under-24-month detail = from memory of Luật Quảng cáo Art. 7, verify]
- [ ] Prohibited categories (Art. 7, e.g. cigarettes, spirits ≥ 15% ABV, prescription drugs) are rejected at the brief stage. [secondary, verify against the consolidated text]

---

## 6. Quick per-shot QA gate (copy into storyboard validation)

- [ ] `keyframe_prompt` is narrative, has photographic terms, names reference-image roles, sets 9:16 in config, has no 8k tags and no captions.
- [ ] `motion_prompt` is ≤ ~400 chars, has one action, a subject handle only, a Hailuo bracket command at the right position, a speed adverb and an end state, and nothing contradicting the image.
- [ ] Shot scale and angle differ from the previous shot. The 180° side, screen direction and Kelvin value match the scene sheet.
- [ ] Face, product and caption zones sit inside the safe box (top 14%, bottom 35%, sides 6%).
- [ ] The script has: brand or product by 5 s, ≥ 2 shots by 5 s, hook by 3 s, a CTA in text + VO, an ad label, and no unsupported superlative, comparison or medical claim. The supplement disclaimer is present when relevant.

## Bổ sung (QA tiền kỳ vòng 2): claim công dụng sức khoẻ cho hàng thông thường
- Quảng cáo sai sự thật = thông tin không đúng về chất lượng, giá, **công dụng**, kiểu dáng, xuất xứ (Luật Quảng cáo 2012,
  Điều 8 các hành vi bị cấm). Xử phạt hành chính theo Nghị định 38/2021/NĐ-CP (sửa đổi bởi Nghị định 128/2022);
  nghiêm trọng có thể truy cứu Điều 197 BLHS 2015 (quảng cáo gian dối). Mức phạt cụ thể giữa các nguồn chưa thống nhất:
  kiểm tra văn bản gốc trước khi trích dẫn.
- Hệ quả cho kịch bản: đèn bàn, ghế, gối… không được nói "chống cận", "bảo vệ mắt", "chuẩn y khoa" nếu không có giấy
  chứng nhận trong brief; chỉ mô tả đặc điểm nhìn thấy được (vật liệu, hình dáng, cách cấp nguồn, ánh sáng trắng).
- Nguồn: https://daibieunhandan.vn/quang-cao-sai-su-that-bi-xu-phat-the-nao-10310937.html ,
  https://thuvienphapluat.vn/hoi-dap-phap-luat/quang-cao-sai-su-that-ve-chat-luong-san-pham-bi-xu-phat-nhu-the-nao-138046115.html ,
  https://advertisingvietnam.com/article/luu-y-danh-cho-marketer-de-tranh-quang-cao-sai-su-that-vi-khong-ro-luat-p20359

## Vòng 3 (fashion/phụ kiện): ghi chú bổ sung
- Chuyển động máy: đặt lệnh camera ở đầu prompt (mô hình coi trọng token đầu), thêm "slowly/smoothly" để giảm giật; Kling khuyên phủ định jitter, sliding, extra limbs, distortion. Chưa có nguồn riêng cho orbit quanh người đang đi bộ; suy luận nội bộ: không kết hợp orbit + đi bộ trong một clip 6s (hai chuyển động đồng thời → trượt chân/biến dạng), chọn tracking song song hoặc máy đứng yên. Nguồn: https://www.atlabs.ai/blog/ultimate-prompt-guide-best-camera-movement-prompts-for-ai-videos-2026 , https://picsart.com/blog/kling-ai-prompts/ , https://www.veed.io/learn/hailuo-prompts
- TikTok: hook trong vài giây đầu, cấu trúc hook → điểm bán → CTA, phong cách không quá bóng bẩy, giữ sản phẩm/chữ ngoài vùng UI phải/dưới, 9–15s là độ dài an toàn. Nguồn: https://ads.tiktok.com/help/article/creative-best-practices , https://influencermarketinghub.com/video-advertising/tiktok-video-ad-specs/
- Phụ kiện túi: "đựng vừa gì" phải chứng minh bằng hình (đồ đặt vào/lấy ra), không bằng lời. Quai/tay là điểm dễ hỏng: tay nên nắm quai hoặc chạm thân túi, tránh tay lơ lửng.
- Cỡ cảnh quyết định thứ gì nằm trong khung: medium shot cắt ngang eo; cowboy shot cắt giữa đùi, sinh ra để giữ bao súng ở hông trong khung; medium wide ~ đầu gối; full shot đầu–chân. Hệ quả: sản phẩm mang ở hông/tay buông (túi xách tay, đồng hồ khi tay buông) cần ≥ cowboy shot; hành động trên mặt bàn khi ngồi cần ≥ medium shot. Nguồn: https://www.studiobinder.com/blog/ultimate-guide-to-camera-shots/ , https://artlist.io/blog/shot-sizes/ , https://filmdaft.com/camera-shots-moves-angles-overview-guide/

## Vòng 4 (mỹ phẩm): pháp lý claim
- Mỹ phẩm VN: Thông tư 06/2011/TT-BYT (thực thi Hiệp định mỹ phẩm ASEAN); tính năng phải theo Hướng dẫn ASEAN về công bố tính năng (Phụ lục 03-MP); mỹ phẩm chỉ tạo hiệu quả không vĩnh viễn, không được gây hiểu nhầm là thuốc. Từ cấm thường gặp: điều trị, đặc trị, trị mụn, trị nám, chữa khỏi (nguồn thứ cấp, đối chiếu Phụ lục 03-MP). Quảng cáo phải đăng ký với Sở Y tế. Có dự thảo sửa TT 06/2011 năm 2025 (chưa xác nhận hiệu lực).
  Nguồn: https://thuvienphapluat.vn/cong-van/The-thao-Y-te/Official-Dispatch-No-1609-QLD-MP-on-guiding-the-cosmetic-classification-138279.aspx , https://soyte.hatinh.gov.vn/upload/1000030/20220811/M-pham_10_08_2022_10h22p14__signed_8799e9b5ae.pdf , https://thuonghieucongluan.com.vn/thuong-hieu-mq-skin-quang-cao-my-pham-nhu-thuoc-dac-tri-co-dau-hieu-lua-doi-nguoi-tieu-dung-a234172.html
- Hệ quả cho pipeline: claim mỹ phẩm chỉ nêu cảm quan/tính năng mỹ phẩm (dưỡng ẩm, kết cấu, cảm giác khi thoa); không trước/sau, không thời hạn hiệu quả, không "an toàn cho bà bầu", không chứng nhận không có hồ sơ.
- Rủi ro video AI (suy luận nội bộ, chưa có nguồn): tay chạm mặt/tán kem là vùng dễ biến dạng (ngón tay xuyên da, mặt đổi danh tính); beat nói trước máy không nên có tay che miệng/má.
