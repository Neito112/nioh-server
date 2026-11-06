# Ni-Oh Server & Device Portal

> **Hệ thống Cổng Server AI phân tán & Web Quản lý thiết bị.**  
> Chuẩn hóa theo mô hình 2 tầng độc lập:
> 1. **Desktop App = CỔNG SERVER:** Đăng nhập liên kết Cloudflare để kích hoạt cổng và **XUẤT RA LINK WEB**.
> 2. **Web Portal = QUẢN LÝ THIẾT BỊ:** Đăng nhập tài khoản cá nhân qua **Google / Email cá nhân**, ghép đôi bằng **mã 6 chữ số**, chọn Model AI phù hợp cho từng con bot.

---

## 🏗️ Kiến Trúc Hệ Thống

```
┌────────────────────────────────────────────────────────┐
│             1. DESKTOP APP = CỔNG SERVER               │
│  - Người dùng: Người vận hành / Chủ trạm server        │
│  - Đăng nhập: Tài khoản CLOUDFLARE                     │
│  - Chức năng: Kích hoạt tunnel, mở cổng WebSocket/OTA  │
│  - Kết quả: Tự động XUẤT RA LINK WEB QUẢN LÝ           │
└───────────────────────────┬────────────────────────────┘
                            │
               Xuất ra Public Web Portal
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│             2. TRANG WEB QUẢN LÝ THIẾT BỊ              │
│  - Người dùng: Bất kỳ ai sở hữu con bot ESP32          │
│  - Đăng nhập: Tài khoản GOOGLE hoặc EMAIL CÁ NHÂN      │
│  - Chức năng:                                          │
│    + Ghép đôi mạch bằng MÃ 6 CHỮ SỐ trên màn hình      │
│    + Chọn Model AI (Menu chọn các model phù hợp)       │
│    + Nhập API Key cá nhân của người dùng               │
│    + Chọn Giọng nói (TTS), Cài đặt tính cách (Prompt)  │
│    + Xem trạng thái Online/Offline của thiết bị        │
└───────────────────────────▲────────────────────────────┘
                            │
                   Cấu hình đồng bộ xuống
                            │
┌───────────────────────────┴────────────────────────────┐
│                    3. MẠCH ESP32                       │
│  - Bật nguồn: Hiện mã 6 số                             │
│  - Kết nối âm thanh trực tiếp về CỔNG SERVER (App)     │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Cài Đặt Nhanh (1-Click)

### Trên Windows
Mở **PowerShell** và chạy:
```powershell
irm https://raw.githubusercontent.com/Neito112/nioh-server/main/scripts/install.ps1 | iex
```
*Script tự động cài đặt và tạo icon **"Ni-Oh Server"** trên màn hình Desktop.*

Hoặc tải repo về và nhấp đúp file: **`Khởi Động Ni-Oh.bat`**.

---

## 🖥️ Hướng Dẫn Vận Hành

### Bước 1: Vận hành Cổng Server (Desktop App)
1. Mở icon **Ni-Oh Server** trên Desktop.
2. Nhập thông tin tài khoản Cloudflare (Token / Account).
3. Nhấp nút **"BẬT CỔNG SERVER & XUẤT LINK WEB"**:
   * Hệ thống tự động kích hoạt Cloudflare Tunnel.
   * **Xuất ra đường link Web Quản Lý Thiết Bị** (Ví dụ: `https://xxxx.trycloudflare.com/portal`).
   * Bạn chỉ cần sao chép link này chia sẻ cho người dùng hoặc tự truy cập.

### Bước 2: Quản lý thiết bị trên Web Portal (Người dùng)
1. Truy cập vào link web vừa xuất ra từ bất kỳ đâu (điện thoại hoặc máy tính).
2. Bấm **"Đăng nhập bằng Google"** hoặc **"Đăng nhập bằng Zalo"**.
3. Bấm nút **"+ Thêm Thiết Bị Mới"**:
   * Nhập **mã 6 chữ số** đang hiện trên màn hình mạch ESP32.
   * Thiết bị sẽ được gán ngay vào tài khoản cá nhân của bạn.
4. Nhấp vào con bot để cấu hình:
   * **Chọn Model AI:** Menu chọn sẵn các model tối ưu (DeepSeek V3, Gemini Flash 2.0 Free, GPT-4o-mini, Claude 3.5 Sonnet...).
   * **API Key:** Tùy chọn nhập key riêng của bạn.
   * **Giọng đọc:** Chọn giọng Hoài My, Nam Minh, Ban Mai...
   * **Tính cách:** Cài đặt Prompt xưng hô và phong cách trò chuyện.

---

## 🛠️ Bộ Tool & MCP Tích Hợp Miễn Phí (Phản Hồi Mạch)

* 💻 **Điều khiển PC:** Tắt máy, ngủ, khóa màn hình, volume, Wake-on-LAN bật máy qua card mạng.
* 🌤️ **Thời tiết Free:** Open-Meteo cập nhật toàn bộ tỉnh thành Việt Nam không cần key.
* 🔎 **Tìm kiếm Web Free:** DuckDuckGo Search tra cứu tin tức thời gian thực không cần key.
* 🎵 **Nghe nhạc YouTube Free:** Stream âm thanh YouTube qua `yt-dlp`.
* 📡 **Giao tiếp ESP-NOW:** Đóng gói lệnh vô tuyến 2.4GHz bắn về mạch ESP32 điều khiển công tắc phụ.
* 🏠 **Quét mạng LAN IoT:** Tự động quét mDNS phát hiện Home Assistant & sinh mã QR kết nối.

---

## 📄 Bản Quyền
Phát hành theo giấy phép MIT. Mã nguồn lưu trữ tại [Neito112/nioh-server](https://github.com/Neito112/nioh-server).
