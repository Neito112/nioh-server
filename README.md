# Ni-Oh Server & Control Center

> **Hệ sinh thái máy chủ giọng nói AI phân tán tương thích Xiaozhi ESP32.**  
> Ứng dụng Desktop có biểu tượng (Icon) kích hoạt trực tiếp — **toàn bộ cài đặt được quản lý 100% trên giao diện đồ họa trực quan, KHÔNG cần mở code hay sửa file cấu hình thủ công!**

---

## 🌟 Tính Năng Nổi Bật

### 1. Kích Hoạt 1 Chạm & Cấu Hình Trên Giao Diện (Zero-Code Setup)
* **Icon Desktop Tiện Lợi:** Sau khi cài đặt, tự động tạo biểu tượng **"Ni-Oh Server"** ngay trên màn hình Desktop. Chỉ cần nhấp đúp là khởi chạy ngầm, tự mở giao diện điều khiển.
* **Không Đụng File Code:** Toàn bộ việc chọn Provider (OpenRouter, DeepSeek, OpenAI, Groq, Ollama...), dán API Key, chọn Model, đổi cổng, bật/tắt Cloudflare Tunnel... đều thực hiện bằng chuột trên Dashboard.
* **File khởi động nhanh:** Trong thư mục có sẵn file `Khởi Động Ni-Oh.bat` tiện lợi cho mọi người dùng.

### 2. Mô Hình 2 Dashboard Tách Biệt
* **Dashboard 1: Desktop App (Server Host Control Center):**
  * Quản trị hạ tầng máy chủ: Xem trạng thái Server, URL WebSocket, Endpoint OTA.
  * Tùy chọn nhà cung cấp AI không bị khóa cứng (hỗ trợ mọi endpoint OpenAI-compatible).
  * Công tắc gạt (Toggle) bật/tắt toàn bộ các công cụ & MCP.
* **Dashboard 2: Web Portal (Quản lý Thiết bị - Thay thế xiaozhi.me):**
  * Truy cập được từ điện thoại, tablet ở bất kỳ đâu ngoài mạng LAN.
  * Ghép đôi thiết bị ESP32 bằng **mã 6 chữ số** hiển thị trên màn hình LCD mạch.
  * Đổi tên bot, chọn giọng nói TTS, chỉnh sửa câu lệnh nhân vật (System Prompt).

### 3. Bộ Tool Tích Hợp Sẵn Miễn Phí 100% (Phản hồi tín hiệu từ mạch)
* 💻 **Điều khiển PC (`pc_control`):** Tắt máy, ngủ (Sleep), khởi động lại, khóa màn hình Windows, tăng/giảm âm lượng, mở ứng dụng/website, phát gói **Wake-on-LAN (WOL)** bật nguồn các PC khác trong mạng LAN qua địa chỉ MAC.
* 🌤️ **Thời tiết Free (`free_weather`):** Tích hợp **Open-Meteo**, tự động nhận diện mọi tỉnh thành Việt Nam, cập nhật nhiệt độ/độ ẩm/gió không cần bất kỳ API Key nào.
* 🔎 **Tìm kiếm Web Free (`free_search`):** Tích hợp **DuckDuckGo Search**, cập nhật tin tức thời gian thực không giới hạn, không cần tài khoản.
* 🎵 **Nghe nhạc YouTube Free (`free_music`):** Tìm kiếm và trích xuất luồng audio YouTube qua **yt-dlp**, stream trực tiếp về loa ESP32 (nghe nhạc trẻ, remix, lofi, podcast...).
* 📡 **Giao tiếp ESP-NOW (`esp_now`):** Đóng gói lệnh JSON gửi ngược về ESP32 để chip phần cứng phát sóng 2.4GHz điều khiển các công tắc phụ không dây.
* 🏠 **Quét mạng LAN IoT (`smart_home`):** Tự động quét mDNS phát hiện Home Assistant nội bộ, sinh mã QR để quét bằng điện thoại và nhập Access Token.

---

## 🚀 Cài Đặt Nhanh (1-Click Install)

### Trên Windows
Mở **PowerShell** và dán dòng lệnh sau:
```powershell
irm https://raw.githubusercontent.com/Neito112/nioh-server/main/scripts/install.ps1 | iex
```
*Script sẽ tự động chuẩn bị môi trường, tạo icon **"Ni-Oh Server"** trên màn hình Desktop và tự mở ứng dụng lên.*

### Hoặc Tải Trực Tiếp Về Máy
1. Tải mã nguồn về máy hoặc chạy:
   ```bash
   git clone https://github.com/Neito112/nioh-server.git
   ```
2. Nhấp đúp vào file **`Khởi Động Ni-Oh.bat`** để mở giao diện cài đặt!

---

## 🖥️ Cách Sử Dụng

1. **Khởi động:** Nhấp đúp vào icon **Ni-Oh Server** trên Desktop (hoặc chạy `Khởi Động Ni-Oh.bat`).
2. **Cấu hình trên giao diện:**
   * Chọn nhà cung cấp AI trong danh sách (hoặc chọn Tùy chỉnh).
   * Dán API Key và bấm **"Lưu Cài Đặt"**.
   * Bấm **"Khởi động Server"** -> Hệ thống tự động cấp phát địa chỉ WebSocket `wss://...` an toàn qua Cloudflare Tunnel.
3. **Kết nối mạch ESP32:**
   * Lấy mã 6 số hiện trên màn hình mạch ESP32.
   * Bấm nút **"Mở Web Quản Lý Thiết Bị"** trên Dashboard (hoặc vào `http://localhost:8001/portal`).
   * Nhập mã 6 số để kích hoạt mạch và bắt đầu đàm thoại.

---

## 📂 Cấu Trúc Dự Án

```
nioh-server/
├── Khởi Động Ni-Oh.bat      # File nhấp đúp để chạy server ngay lập tức
├── run_silent.vbs           # Khởi chạy ngầm không hiện cửa sổ dòng lệnh đen
├── assets/
│   └── icon.ico             # Biểu tượng ứng dụng cho Shortcut Desktop
├── cloudflare/
│   └── tunnel.py            # Tự động tải & chạy Cloudflare Tunnel
├── server/
│   ├── desktop_app.py       # Desktop App Dashboard 1 & Web Portal Dashboard 2
│   ├── main.py              # Entrypoint server core
│   ├── ota_server.py        # OTA endpoint trả về danh sách WebSocket cho ESP32
│   └── tools/               # Bộ Tool & MCP phản hồi tín hiệu từ mạch
│       ├── pc_control.py        # Điều khiển PC & Wake-on-LAN
│       ├── free_weather.py      # Thời tiết Open-Meteo Free
│       ├── free_search.py       # Tìm kiếm DuckDuckGo Free
│       ├── free_music.py        # Stream nhạc YouTube yt-dlp Free
│       ├── esp_now_handler.py   # Đóng gói frame lệnh ESP-NOW
│       └── iot_discovery.py     # Quét mDNS LAN & tạo QR Home Assistant
├── sync/
│   ├── node_registry.py     # Đồng bộ multi-node qua GitHub Gist
│   └── config_sync.py       # Tự động nạp cấu hình hệ thống
├── scripts/
│   ├── install.ps1          # 1-Click Installer Windows (Tự tạo Icon Desktop)
│   └── install.sh           # 1-Click Installer cho Linux/macOS
├── requirements.txt         # Thư viện Python
└── README.md
```

---

## 📄 Bản Quyền & Giấy Phép
Phát hành theo giấy phép MIT. Phát triển dựa trên nền tảng kiến trúc mở tương thích với Xiaozhi ESP32.
