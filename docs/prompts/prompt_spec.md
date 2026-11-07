# QUY CHUẨN PROMPT CHO VIDEO DIFFUSION (FL2VA & REF2VA SPECIFICATION)

Tài liệu tham chiếu chuẩn cho AI Director Agent, Storyboard Planner, và Storyboard Reviewer về cấu trúc prompt tạo video chất lượng cao.

---

## 1. MẪU PROMPT LOẠI FL2VA (FIRST-FRAME / LAYOUT-TO-VIDEO)

Sử dụng khi: Video được sinh từ First Frame (ảnh khởi đầu) đã khóa bố cục hoặc layout có sẵn, yêu cầu chuyển động vật lý chính xác và ánh xạ thời gian (temporal mapping).

### Cấu trúc bắt buộc:
1. **Reference Picture Alignment:** Khai báo rõ vị trí khớp nối của từng ảnh tham chiếu với mốc thời gian của clip video (ví dụ: Picture 1 khớp 0.00s, Picture 2 khớp 5.17s).
2. **Integrated Multimodal Description:** 
   - Phong cách điện ảnh và xử lý chất liệu (vật liệu thực vs chi tiết đồ họa/in ấn).
   - Thiết lập ánh sáng (hướng sáng, độ bóng, độ tương phản).
   - Mô tả hành động theo từng mốc thời gian cụ thể:
     - `At 0.00s`: Bố cục bắt đầu, trang phục, góc nhìn, điểm nhìn của nhân vật.
     - `At ~0.5s`: Hành động kích hoạt ban đầu (hành động động năng, tương tác vật thể).
     - `At ~1.5s`: Chuyển động xoay hoặc biến đổi hình thái.
     - `At ~2.5s`: Chuyển động nhảy/lao về phía ống kính kết hợp camera pull-back.
     - `At ~3.5s`: Tiếp đất và định hình tư thế kết thúc.
     - `Settling beat`: Khung hình ổn định vào bố cục đích.
3. **Overall Soundscape (Diegetic Audio):** Tiếng động thực tế khớp từng giây với hành động thị giác (tiếng cắn, tiếng xé vật liệu, tiếng rít gió, tiếng tiếp đất, tiếng cười...).
4. **Non-diegetic Music:** Mô tả tiết tấu nhạc, hợp âm đánh trúng vào khoảnh khắc hành động quan trọng và kết thúc khớp lúc dừng hình.

### Ví dụ tham khảo chuẩn (Gold Standard):
```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 5.17-second mark of the target video.

integrated_multimodal_description: [Shot 1] Editorial pop-art photography and printed-graphic hybrid: the woman and her clothing stay photographic with real skin texture, while everything printed — the sticker pizza, the stars, the halftone dots, the sticker tiles on the floor — stays flat printed card with heavy black outlines and no thickness. Flat hard frontal light, seamless process-red field, no gloss on the red. The shot begins exactly on Picture 1: tight portrait framing, red cat-eye sunglasses on her face, black and white checkerboard top, lips just touching the tip of the flat sticker pizza held at chin height, deadpan behind the dark lenses. At about half a second she bites the sticker and pulls her head back, and the red field behind her behaves like printed paper: a ragged tear opens behind her shoulders and curls at its edges. At about one and a half seconds she spins a full turn on the spot, clockwise, the sticker turning with her so its black outline draws a full circle against the red. At about two and a half seconds she jumps up through the tear toward the lens, and the camera pulls back with small amplitude at slow speed, coming to rest exactly when her raised arms fit inside the frame. At about three and a half seconds she lands facing the lens in the pose of Picture 2: arms overhead holding the sticker pizza, its bitten edge toward camera, the red cat-eye sunglasses airborne above and to her left, tumbling end over end with one lens catching the light, her face breaking into a wide open laugh. Flat yellow stars and small sticker pizza tiles populate the red field exactly as in Picture 2, and the halftone dot pattern resolves into visible print grain. The shot settles into the final composition of Picture 2 and holds, with only the sunglasses still turning in the air.

overall_soundscape: A crisp papery bite, then the dry rasping tear of thick printed stock splitting and curling, one short airy whoosh for the spin, a light thump of her landing, the plastic clatter of sunglasses tumbling above her, and her open laugh arriving on the landing over a dry studio room with no reverb.

non_diegetic_music: A fast bright brass-and-clarinet figure that hits on the spin, cuts to a single sustained note through the jump, and lands on one resolved chord with her laugh.
```

---

## 2. MẪU PROMPT LOẠI REF2VA (REFERENCE-TO-VIDEO)

Sử dụng khi: Video được sinh từ các ảnh tham chiếu đối tượng (KOL Mai Ly face anchor, sản phẩm thật product_hero), yêu cầu chuyển động camera liền mạch (unbroken move) và kiểm soát bảo toàn danh tính đối tượng.

### Cấu trúc bắt buộc:
1. **Subject Definitions:**
   - `<Subject 1>`: Định nghĩa thực thể 1 (bối cảnh, phương tiện, hoặc sản phẩm). Vai trò tham chiếu (form/material anchor). Các đặc điểm buộc phải tuân thủ chính xác.
   - `<Subject 2>`: Định nghĩa thực thể 2 (nhân vật KOL Mai Ly). Vai trò tham chiếu (identity/gear anchor). Các đặc điểm nhận diện khuôn mặt, trang phục buộc phải giữ. Chỉ rõ loại bỏ phông nền của ảnh chân dung studio gốc.
   - `<Subject 3>`: Thực thể phát sinh hoặc không gian tương tác (nội thất, môi trường tương thích màu sắc và ngôn ngữ thiết kế).
2. **Summary:** Tóm tắt 1 câu về cú máy (thời lượng, chuyển động máy quay liền mạch, không cắt cảnh).
3. **Retention Analysis:** 
   - `<Subject X>`: `fully_preserved` (giữ nguyên những chi tiết nào).
   - `<Subject Y>`: `attribute_transfer` (chuyển đổi những thuộc tính chất liệu/ánh sáng nào).
   - Nền ảnh tham chiếu: `weak_reference only` (loại bỏ hoàn toàn phông nền cũ).
4. **Detailed Description:**
   - Phong cách điện ảnh và bảng màu chủ đạo (ví dụ: cold blue ambient vs warm orange interior light).
   - Diễn tiến cú máy theo thời gian:
     - `Mở đầu`: Cỡ cảnh ban đầu, vị trí chủ thể, hướng chuyển động camera.
     - `At ~1.5s`: Biến đổi trạng thái hoặc chuyển vùng không gian.
     - `At ~3.0s`: Camera lướt vào cự ly gần, tốc độ trượt, phối cảnh.
     - `At ~4.5s`: Camera giảm tốc, định hình khung hình cận cảnh nhân vật/sản phẩm.
     - `Held beat`: Giữ tĩnh tư thế chốt cuối clip.
5. **Overall Soundscape:** Thiết kế âm thanh môi trường theo diễn tiến camera di chuyển qua các vùng không gian.
6. **Non-diegetic Music:** Giai điệu và nhịp điệu nâng đỡ chuyển động thị giác.

### Ví dụ tham khảo chuẩn (Gold Standard):
```text
subject_definitions:
<Subject 1> is the station exterior in <Picture 2>. Reference role: form and material anchor. Features to follow exactly: a wide white saucer-shaped upper hull with visible panel seams and small antennas on top, a lit yellow-orange window band running around the rim, a cluster of white cylindrical modules hanging beneath the saucer with thin antenna spars at the bottom, weathered white paint with dark seams between plates, and the blue limb of a planet with white cloud bands behind it.
<Subject 2> is the pilot in <Picture 1>. Reference role: identity and gear anchor. Features to follow exactly: a dark matte flight helmet with a wide glossy black visor, one thin orange glowing ring on the left side of the visor and two horizontal orange glowing bars on the right side, a segmented metal collar ring under the jaw, and a bulky dark flight suit with a soft padded cowl. Do not carry over the light grey studio background of <Picture 1>.
<Subject 3> is the station interior, invented to match <Subject 1>: a dark rectangular hangar bay with ribbed white-metal walls, deep structural ribs, a grated catwalk running across the middle distance, small cargo clamps along the walls, and orange strip lights recessed between the ribs that match the colour of the pilot's visor glow.

summary:
[reference generation] A five-second single continuous shot: the station of <Picture 2> hangs in orbit, the camera pushes in toward its saucer rim, the bay mouth opens and the camera travels inside, where the hangar lights come up to reveal the pilot of <Picture 1> standing on the catwalk. Exterior and interior are one move, no cut.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - saucer hull, panel seams, yellow-orange rim band, hanging module cluster, antenna spars.
<Subject 2> (appears at the end of [Shot 1]): fully_preserved - helmet silhouette, glossy visor, the orange ring and two orange bars, collar ring and padded cowl.
<Subject 3> (appears at the end of [Shot 1]): attribute_transfer - the ribbed white-metal language and window-band orange of <Subject 1> are carried inside as hull ribs and strip lights; the bay layout itself is new.
<Picture 1> background: weak_reference only - its light grey studio backdrop is discarded entirely.
No audio reference is used in this generation.

detailed_description:
Refined retro-futurist cinematography in a single unbroken move, cold blue ambient outside against warm orange interior light, deep blacks in both halves, fine grain and no lens flares; the camera is the only thing that travels and it never cuts.

[Shot 1] Wide establishing frame: the station of <Subject 1> hangs in the black, centred and slightly below eye level, the planet's blue limb and white cloud bands filling the lower third behind it. The saucer's rim band glows a soft orange, the hanging module cluster underneath reads as a dense white cylinder mass with thin spars, and the hull plates are weathered white with dark seams. The camera pushes in with small amplitude at slow speed, straight toward the saucer rim, and the station grows until the window band fills the upper half of the frame.

At about one and a half seconds a rectangular bay mouth opens in the rim below the band: two armour plates slide apart, spilling a warm orange rectangle of light into the vacuum, and a faint haze of vented gas drifts out of it. The camera does not stop and does not slow down; it continues into the opening, the frame going completely black for a beat as it crosses the threshold, then the interior lights of <Subject 3> come up in rows from the far end toward the lens, stripping in along the ribs one section at a time.

At about three seconds the camera is inside, gliding down the length of the ribbed hangar at chest height, the grated catwalk beneath it, cargo clamps and rib shadows sliding past on both sides, and the orange strip lights drawing long converging lines toward the far bulkhead. The camera decelerates and comes to rest at about four and a half seconds, framing <Subject 2> standing on the catwalk in three-quarter profile: dark helmet, glossy black visor with the orange ring and the two orange bars lit, padded cowl, suit reading as a soft dark mass against the white ribs. The last beat holds completely still while the pilot turns their head a few degrees toward the lens and the visor glow spills a thin orange edge onto the nearest rib.

overall_soundscape:
Deep vacuum silence outside with only a low sub-bass hum from the station's structure, then a hard change as the camera crosses the threshold: pressurised air rushing past the lens, the hydraulic whine of the bay plates closing behind, distant bulkhead clanks, the hum of the hangar settling into a steady tone, and one soft suit life-support hiss from the pilot at the end.

non_diegetic_music:
A slow retro synthwave pad that holds one low chord through the exterior, drops to near silence for the threshold crossing, and returns as a warm rising two-note figure as the hangar lights come up, ending on the held final frame.
```
