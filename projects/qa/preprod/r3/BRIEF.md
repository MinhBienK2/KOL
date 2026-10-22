# BRIEF vòng tiền kỳ 3 (chỉ đến storyboard + gói prompt, KHÔNG tạo ảnh/video)

## Sản phẩm
- Tên: Túi tote canvas sọc navy.
- Ảnh hero (sự thật duy nhất về hình dáng): `projects/fashion_apparel/pp_r3/input/product_hero.jpg`
  (Wikimedia Commons "Canvas two-tone tote Navy and Natural", CC BY 2.0; chỉ dùng nội bộ QA).
  Tự mở ảnh và chỉ mô tả những gì ảnh cho thấy.
- Nhãn trong ảnh là thương hiệu của người khác: KHÔNG tái tạo chữ/logo đó. Trong mọi prompt, nhãn là một miếng nhãn
  vải màu be trơn, không chữ.
- Mô tả shop (dán nguyên văn, có thể sai): "Túi tote chống thấm nước 100%, chịu tải 30kg, cotton hữu cơ chuẩn GOTS,
  ngăn laptop chống sốc, khoá kéo YKK. Hot trend 2026, freeship toàn quốc!"
- Claim được phép dùng trong VO/phụ đề (chỉ những ý này):
  - vải canvas màu mộc, ba sọc navy ngang thân, đáy navy
  - quai vải navy, đeo vai hoặc xách tay
  - miệng túi rộng, đóng bằng một cúc bấm
  - đựng vừa đồ đi chơi cả ngày (sổ, bình nước, áo khoác mỏng)
- Cấm: chống thấm, tải trọng/số kg, hữu cơ/chứng nhận, ngăn laptop/chống sốc, khoá kéo, "hot trend", "nhất", giá,
  freeship/khuyến mãi, so sánh với túi khác, mọi con số.

## Nhân vật
- `kol_main`, đóng vai người mẫu (không nói trước máy). Trang phục đi dạo cuối tuần, tông sáng, không logo, để túi là
  điểm nhấn. Không người thứ hai thấy mặt.

## Định dạng
- Archetype: `fashion_apparel`. Campaign: `pp_r3`.
- 12–18 s, 9:16, TikTok/Reels, tiếng Việt.
- Khán giả: nữ 20–23 tuổi, sinh viên năm cuối/mới đi làm ở Hà Nội, cuối tuần đi dạo phố cổ, quán cà phê, hiệu sách;
  ghét túi xách nhỏ không đựng nổi đồ, cũng ngại balo trông "đi học".
- Cảm xúc: "một túi cho cả buổi chiều": nhẹ nhõm, thong thả, có gu.
- Bối cảnh: ngoài trời, chiều muộn giờ vàng, phố cổ/hè phố Hà Nội; có thể 1 cảnh trong quán cà phê nắng chiếu qua cửa.
- Âm thanh: nhạc + tối đa 2 câu lời đọc ngoài hình ngắn; không nói trước máy; âm thanh môi trường (tiếng bước, cúc bấm).
- Kênh hành động: "bấm giỏ hàng" dưới video.

## Ràng buộc
- Chỉ Stage 1–3 của director.py rồi `tools/prompt_pack.py`. Không Stage 4–8.
- Mỗi stage tối đa 3 lần chạy lại.
