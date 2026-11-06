# Ni-Oh Server & Control Center

> **Hệ sinh thái máy chủ giọng nói AI phân tán tương thích Xiaozhi ESP32.**  
> Hỗ trợ đa nhà cung cấp LLM (OpenRouter, DeepSeek, OpenAI, Groq, Ollama...), Cloudflare Tunnel tự động, quản lý thiết bị qua mã 6 số (thay thế xiaozhi.me) và bộ công cụ phản hồi phần cứng hoàn toàn miễn phí.

---

## 🌟 Tính Năng Nổi Bật

### 1. Mô Hình 2 Dashboard Độc Lập
* **Desktop App (Dashboard 1 - Server Host Control Center):**
  * Dành cho người quản trị/chủ máy chủ.
  * Quản lý tài nguyên, trạng thái Server, nút bấm 1-click khởi chạy Cloudflare Tunnel.
  * Không khóa cứng provider: Hỗ trợ bất kỳ API key nào (OpenRouter, DeepSeek, OpenAI, Groq, Ollama chạy local...).
  * Bảng công tắc (Toggle Switches) bật/tắt toàn bộ các Tool và MCP.
* **Web Portal (Dashboard 2 - Tương tự xiaozhi.me):**
  * Đăng nhập ở bất kỳ đâu (điện thoại, máy tính bảng, ngoài mạng LAN).
  * Ghép đôi mạch ESP32 bằng **mã 6 chữ số (Pin Code)** hiển thị trên màn hình LCD.
  * Tùy biến nhân vật AI: Đổi tên bot, cấu hình tính cách (System Prompt), chọn giọng đọc TTS.

### 2. Kiến Trúc Phân Tán (Multi-Node Không Node Chính)
* Tất cả các máy cài đặt server đều bình đẳng, đóng vai trò là server dự phòng cho nhau.
* Đồng bộ cấu hình và danh sách node qua **GitHub Gist cá nhân** — không cần thuê database hay server trung gian.
* ESP32 tự động nhận danh sách tất cả các node đang online qua OTA Endpoint để kết nối.

### 3. Bộ Tool Tích Hợp Miễn Phí 100% (Phản hồi tín hiệu mạch)
* 💻 **Điều khiển PC (`pc_control`):** Tắt máy, ngủ (Sleep), khởi động lại, khóa màn hình Windows, tăng/giảm âm lượng, mở ứng dụng/web, gửi gói tin **Wake-on-LAN (WOL)** bật nguồn PC khác trong mạng LAN qua địa chỉ MAC.
* 🌤️ **Thời tiết Free (`free_weather`):** Tích hợp **Open-Meteo**, tự động nhận diện mọi tỉnh thành Việt Nam, cập nhật nhiệt độ/độ ẩm/gió không cần bất kỳ API Key nào.
* 🔎 **Tìm kiếm Web Free (`free_search`):** Tích hợp **DuckDuckGo Search**, cập nhật tin tức thời gian thực không giới hạn, không cần tài khoản.
* 🎵 **Nghe nhạc YouTube Free (`free_music`):** Tìm kiếm và trích xuất luồng audio YouTube qua **yt-dlp**, stream trực tiếp về loa ESP32 (nghe nhạc trẻ, remix, lofi, podcast...).
* 📡 **Giao tiếp ESP-NOW (`esp_now`):** Đóng gói lệnh JSON gửi ngược về ESP32 để chip phần cứng phát sóng 2.4GHz điều khiển các công tắc phụ không dây.
* 🏠 **Quét mạng LAN IoT (`smart_home`):** Tự động quét mDNS phát hiện Home Assistant nội bộ, sinh mã QR để quét bằng điện thoại và nhập Access Token.

---

## 🚀 Cài Đặt Nhanh (1-Click Install)

### Trên Windows (PowerShell)
Mở PowerShell và chạy lệnh:
```powershell
irm https://raw.githubusercontent.com/Neito112/nioh-server/main/scripts/install.ps1 | iex
```

### Trên Linux / macOS / Raspberry Pi / TV Box
Mở Terminal và chạy lệnh:
```bash
curl -fsSL https://raw.githubusercontent.com/Neito112/nioh-server/main/scripts/install.sh | bash
```

---

## 🖥️ Hướng Dẫn Sử Dụng

### 1. Khởi động Giao diện Desktop App (Dashboard 1)
Chạy lệnh trong thư mục dự án:
```bash
python -m server.desktop_app
```
Giao diện **Ni-Oh Server Control Center** sẽ tự động mở tại:
* **URL Cục bộ:** `http://localhost:8001`

Tại đây bạn có thể:
1. Chọn nhà cung cấp LLM (OpenRouter, DeepSeek, OpenAI...) và dán API Key.
2. Bấm nút **"Khởi động Server"** -> Cloudflare Tunnel tự động cấp WSS URL.
3. Bật/tắt các Tool theo mong muốn.
4. Bấm **"Mở Web Quản Lý Thiết Bị"** để vào Dashboard 2.

### 2. Quản lý Thiết Bị (Dashboard 2 - Web Portal)
* **Truy cập tại:** `http://localhost:8001/portal` (hoặc qua domain Cloudflare từ điện thoại).
* **Cách ghép đôi ESP32:**
  1. Bật nguồn mạch ESP32 đã nạp firmware Ni-Oh.
  2. Màn hình mạch sẽ hiển thị mã PIN 6 số.
  3. Nhập 6 số này vào Web Portal và bấm **"Kích hoạt & Ghép đôi"**.
  4. Mạch lập tức kết nối vào server và bắt đầu trò chuyện.

---

## ⚙️ Cấu Hình Nâng Cao (.env)

Các thông số có thể tùy biến trong file `.env`:

```env
# ── Cấu hình LLM ──
NIOH_API_KEY=sk-...               # API Key của bạn
NIOH_LLM_BASE_URL=https://...     # Endpoint OpenAI-compatible
NIOH_MODEL=deepseek/deepseek-chat  # Tên model

# ── Node Registry (Đồng bộ nhiều máy) ──
NIOH_GITHUB_TOKEN=ghp_...         # GitHub Token (chỉ cần quyền 'gist')
NIOH_GIST_ID=                     # Tự sinh sau lần đầu chạy
NIOH_NODE_ID=node-1               # Tên định danh của máy này

# ── Cloudflare Tunnel ──
NIOH_CF_DOMAIN=                   # Để trống = dùng trycloudflare.com (free)

# ── Cổng dịch vụ ──
NIOH_WS_PORT=8000                 # Cổng WebSocket âm thanh
NIOH_HTTP_PORT=8003               # Cổng OTA Firmware
```

---

## 📂 Cấu Trúc Dự Án

```
nioh-server/
├── cloudflare/
│   └── tunnel.py            # Tự động tải & chạy Cloudflare Tunnel
├── server/
│   ├── desktop_app.py       # Desktop App Dashboard 1 & Web Portal Dashboard 2
│   ├── main.py              # Entrypoint chạy server dạng daemon/headless
│   ├── ota_server.py        # OTA endpoint trả về danh sách WebSocket cho ESP32
│   ├── config_patcher.py    # Patch cấu hình động không hardcode key
│   └── tools/               # Bộ Tool & MCP phản hồi tín hiệu từ mạch
│       ├── pc_control.py        # Điều khiển PC & Wake-on-LAN
│       ├── free_weather.py      # Thời tiết Open-Meteo Free
│       ├── free_search.py       # Tìm kiếm DuckDuckGo Free
│       ├── free_music.py        # Stream nhạc YouTube yt-dlp Free
│       ├── esp_now_handler.py   # Đóng gói frame lệnh ESP-NOW
│       └── iot_discovery.py     # Quét mDNS LAN & tạo QR Home Assistant
├── sync/
│   ├── node_registry.py     # Đồng bộ multi-node qua GitHub Gist
│   └── config_sync.py       # Thứ tự ưu tiên nạp config (env > gist > default)
├── scripts/
│   ├── install.ps1          # 1-Click Installer cho Windows
│   └── install.sh           # 1-Click Installer cho Linux/macOS
├── requirements.txt         # Thư viện Python
└── README.md
```

---

## 📄 Bản Quyền & Giấy Phép
Phát hành theo giấy phép MIT. Phát triển dựa trên nền tảng kiến trúc mở tương thích với Xiaozhi ESP32.
