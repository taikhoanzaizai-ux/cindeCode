# CindeCode AI Studio

Bản desktop Windows thử nghiệm **0.1.0**, chạy portable từ thư mục tùy chọn như ổ D: hoặc E:. Đây là dự án desktop mới, chưa phải bản tích hợp đầy đủ của [CineCode gốc](https://github.com/sarpstar/cinecode).

## Chức năng đã viết

- Chọn video, mở preview (FFplay hoặc trình phát hệ thống).
- Cắt video theo mốc thời gian, đổi khung hình 16:9 / 9:16 / 1:1 và xuất MP4 bằng FFmpeg.
- Chèn một dòng chữ bằng phụ đề SRT nếu FFmpeg có filter subtitles/libass.
- Kết nối Ollama tại 127.0.0.1:11434, kiểm tra model, tải Qwen Coder theo xác nhận và nhận **kế hoạch dựng video** bằng tiếng Việt.
- Nút **Kiểm tra cập nhật** kiểm tra GitHub Releases; mở trang tải bản mới. Chưa tự ghi đè chương trình đang chạy.
- Thư mục xuất video tùy chọn, dữ liệu ứng dụng đặt cạnh EXE.

**Chưa làm:** AI tự tạo video hoàn chỉnh, timeline kéo thả, tự phân tích/cắt khoảng lặng, clone giọng Việt, TTS, tích hợp engine CineCode gốc và cập nhật tự động một chạm. Không nhầm bản này với editor hoàn thiện.

## Tải và chạy trên Windows

1. Vào tab **Actions** trong repository, chọn workflow **Windows portable build**, chọn run thành công, tải artifact \`CindeCodeStudio-Windows-portable.zip\`.
2. Giải nén vào thư mục bạn muốn, ví dụ \`D:\CindeCodeStudio\`. Chạy \`CindeCodeStudio.exe\` trong thư mục đã giải nén. Không cần cài chương trình vào ổ C:.
3. Tải FFmpeg từ nhà phát hành và thêm vào PATH, hoặc đặt \`ffmpeg.exe\`, \`ffplay.exe\` trong thư mục \`tools\` cạnh EXE.
4. Cài Ollama tại https://ollama.com/download/windows và khởi chạy. Tải mô hình bằng lệnh \`ollama pull qwen2.5-coder:7b\`, hoặc bằng nút trong tab AI của ứng dụng.
5. Chọn video để biên tập; hoặc mở tab AI, nhập prompt và bấm **Tạo kế hoạch với Qwen**.

**Quan trọng:** Ollama là phần mềm cài riêng; cài app vào D: không tự động dời Ollama/models ra khỏi C:. Để dời kho models có thể đặt biến môi trường \`OLLAMA_MODELS=D:\OllamaModels\` theo tài liệu Ollama, rồi khởi động lại Ollama. Máy cần đủ RAM/VRAM. Chạy model local không thu phí token nhưng tốn điện và tài nguyên.

## Build trên máy của bạn

Cần Python 3.10+:

\`\`\`powershell
py -3 app.py
\`\`\`

Bản portable được đóng gói tự động trên GitHub Actions qua \`.github/workflows/windows.yml\` bằng PyInstaller. Build thành công mới có ZIP tải về.

## Quy trình cập nhật

Push code lên GitHub -> GitHub Actions build ZIP mới -> kiểm thử -> tạo GitHub Release theo số phiên bản và đính kèm ZIP đã duyệt. Nút **Kiểm tra cập nhật** xem GitHub Releases và mở trang download. Để cài bản mới: thoát app, giải nén phiên bản mới vào thư mục bạn chọn (sao lưu \`data\` trước). Không tự chạy mã tải trực tiếp từ nhánh main vì lý do an toàn. Bản đầu chưa có thay thế file tự động.

## Bảo mật và giới hạn

AI chỉ tạo văn bản kế hoạch, không tự thực thi lệnh/câu trả lời. Chỉ dùng bản phát hành đáng tin cậy và kiểm tra checksum/chữ ký nếu có. Chưa kiểm chứng ứng dụng trên máy Windows của người dùng.

CineCode gốc MIT: https://github.com/sarpstar/cinecode. Khi tích hợp mã gốc cần giữ bản quyền và giấy phép tương ứng.
