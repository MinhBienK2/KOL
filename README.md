# KOL Character Studio (DramaClaw Production Standard)

Bộ tài nguyên nhân vật chuẩn hóa theo kiến trúc sản xuất video của **DramaClaw**, phục vụ tạo ảnh cảnh quay (First Frame) và làm video nhất quán (Image-to-Video).

---

## 1. Cấu trúc thư mục chuẩn hóa

```
KOL/
├── assets/characters/kol_main/
│   ├── character.json                   # Hồ sơ nhân vật (Schema DramaClaw: face_prompt + identity)
│   ├── portrait.png                     # Face Anchor 1:1 (khóa nhận diện khuôn mặt bất biến)
│   │
│   ├── identities/                      # Thư mục Identity (trang phục & mỏ neo hình thể)
│   │   ├── default.png                  # Turnaround sheet 4-panel bán thân chuẩn DramaClaw
│   │   ├── turnaround_bust_4panel.png   # 4 góc bán thân (0°, 45°, 90°, 180°)
│   │   └── turnaround_body_3panel.png   # 3 góc toàn thân đứng thẳng (0°, 90°, 180°)
│   │
│   ├── expressions/                     # Bộ biểu cảm khuôn mặt sạch sẽ (không có bàn tay)
│   │   ├── expressions_grid_2x3.png     # Lưới 6 sắc thái: Neutral, Smiling, Surprised, Looking Down...
│   │   ├── 01_neutral.jpg
│   │   ├── 02_smiling.jpg
│   │   ├── 03_surprised.jpg
│   │   └── ...
│   │
│   └── full_body/                       # Ảnh toàn thân đứng thẳng riêng lẻ
│       ├── 01_standing_front_0deg.jpg
│       ├── 02_standing_side_90deg.jpg
│       └── 03_standing_back_180deg.jpg
│
├── tools/
│   └── dramaclaw_shot_builder.py        # Tool tạo prompt DramaClaw + sinh First Frame qua MiniMax + xóa watermark
│
├── output/                              # Thư mục chứa các First Frame đã render
└── archive_raw/                         # Thư mục lưu trữ các file dư thừa/lỗi thời
```

---

## 2. Cách sinh First Frame (Ảnh mốc cảnh quay)

Sử dụng tool `dramaclaw_shot_builder.py` để tự động tạo prompt và gọi model MiniMax:

```bash
# Xem prompt chuẩn DramaClaw:
python3 tools/dramaclaw_shot_builder.py --scene "standing at a minimalist coffee counter, smiling warm"

# Sinh trực tiếp ảnh First Frame sạch (tự động xóa watermark):
python3 tools/dramaclaw_shot_builder.py \
  --scene "standing at a minimalist coffee counter, smiling warm" \
  --output output/shot_coffee_01.png \
  --generate
```

---

## 3. Luồng đưa sang Video (Image-to-Video)

1. Lấy ảnh thành phẩm trong thư mục `output/` (ví dụ: `output/shot_coffee_01.png`).
2. Nạp tấm ảnh này vào **Kling**, **Wan 2.1**, **Runway Gen-3** hoặc **Seedance 2.0**.
3. Nhân vật trong video sẽ chuyển động tự nhiên và đúng 100% diện mạo khuôn mặt gốc.
