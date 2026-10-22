QA Stage 3: GẦN ĐẠT. Set/wear/i2v/camera rất tốt, 0 rò rỉ bối cảnh mặc định. Còn lỗi khung hình: hành động hoặc sản phẩm nằm ngoài khung.
1. shot_05 là medium shot (ngang eo) nhưng trạng thái kết thúc là túi xách tay buông ngang hông → túi rơi khỏi khung đúng lúc chứng minh "xách tay". Đổi shot_scale để thấy cả vai lẫn túi ở hông (cowboy_shot hoặc medium_full/full), máy vẫn đứng yên.
2. shot_06 là khung chốt CTA nhưng medium shot + túi buông bên hông → không thấy sản phẩm. Khung CTA phải thấy rõ túi (ba sọc, quai) VÀ người: cowboy_shot/full_shot, hoặc cho cô ấy ôm/giữ túi ở tầm ngực tay chạm thân túi. Giữ tĩnh.
3. shot_03 là MCU (ngực trở lên) nhưng hành động mở cúc + lấy sổ diễn ra ở mặt bàn → tay ra khỏi khung. Dùng medium_shot (hoặc góc hơi cao) để thấy mặt, tay và túi trên bàn.
Nguyên tắc chung: với mỗi shot, tự hỏi "ở frame đầu VÀ frame cuối, sản phẩm và bàn tay đang làm việc có nằm trong khung không?".
Sửa trong script_v3.json (validate ra []), inject với --pause-after-stage 2, chạy lại --from-stage 3 --pause-after-stage 3 --shot-overrides projects/qa/preprod/r3/shot_overrides.json --json < /dev/null, rồi prompt_pack. Cấm như cũ (Stage ≥4, tạo ảnh/video/TTS, sửa tay artifacts/, sửa code, Python inject_artifact).
Báo cáo: exit code, bảng shot (shot_scale, frame đầu, frame cuối, sản phẩm có trong khung không ở cả hai), lint còn lại.
