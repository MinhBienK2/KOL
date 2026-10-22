# BRIEF vòng tiền kỳ 4 (chỉ đến storyboard + gói prompt, KHÔNG tạo ảnh/video)

## Sản phẩm
- Tên: Kem dưỡng ẩm hũ thuỷ tinh.
- Ảnh hero (sự thật duy nhất về hình dáng): `projects/beauty_skincare/pp_r4/input/product_hero.jpg`
  (Wikimedia Commons "Day cream 02", CC BY-SA 4.0; chỉ dùng nội bộ QA). Tự mở ảnh và chỉ mô tả những gì ảnh cho thấy.
- Chữ mờ in trên hũ trong ảnh: KHÔNG tái tạo. Trong mọi prompt, hũ không có chữ/nhãn.
- Mô tả shop (dán nguyên văn, có thể sai): "Kem dưỡng trắng da cấp tốc, trị mụn, xoá nám sau 7 ngày, chuẩn FDA Hoa Kỳ,
  100% thiên nhiên an toàn cho bà bầu. Trước/sau thấy rõ! Mua 1 tặng 1."
- Claim được phép dùng trong VO/phụ đề/lời nói (chỉ những ý này):
  - hũ thuỷ tinh trong, nắp vặn xanh dương, màng seal bạc khi mở lần đầu
  - kem màu trắng ngà, kết cấu mềm, tán mỏng nhẹ
  - dưỡng ẩm cho da
  - cảm giác: da mềm, dễ chịu khi ngồi điều hoà cả ngày (lời kể cảm nhận cá nhân, không hứa hiệu quả)
- Cấm: trắng da, trị mụn, xoá/mờ nám, mọi từ điều trị/đặc trị, FDA/chứng nhận, thiên nhiên/organic, bà bầu/an toàn
  tuyệt đối, trước/sau, thời hạn hiệu quả, mọi con số, giá, khuyến mãi, so sánh với kem khác, "nhất".

## Nhân vật
- `kol_main`, vai người dẫn (presenter) kể trải nghiệm. Trang phục buổi sáng ở nhà, gọn gàng. Không người thứ hai.

## Định dạng
- Archetype: `beauty_skincare`. Campaign: `pp_r4`.
- 15–22 s, 9:16, TikTok/Reels, tiếng Việt.
- Khán giả: nữ 25–30 tuổi, nhân viên văn phòng ở TP.HCM, ngồi phòng điều hoà cả ngày, da khô căng vào cuối giờ chiều;
  chu trình dưỡng da buổi sáng ngắn, ngại kem bết dính.
- Cảm xúc: "buổi sáng nhẹ tênh": gọn, mềm, tự tin bước ra khỏi nhà.
- Bối cảnh: buổi sáng, bàn trang điểm/kệ cạnh cửa sổ căn hộ, nắng sớm tự nhiên.
- Âm thanh: 2–3 beat presenter nói trước máy (mặt và miệng trong khung, tay không che miệng); còn lại lời đọc ngoài hình hoặc
  ASMR (vặn nắp, bóc seal, tán kem).
- Kênh hành động: "bấm giỏ hàng" dưới video.

## Ràng buộc
- Chỉ Stage 1–3 của director.py rồi `tools/prompt_pack.py`. Không Stage 4–8.
- Mỗi stage tối đa 3 lần chạy lại.
