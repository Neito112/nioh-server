# Ni-Oh Distributed Server

> Xiaozhi-compatible AI voice server, hỗ trợ OpenRouter, chạy phân tán qua Cloudflare Tunnel.  
> Mỗi máy cài = 1 node dự phòng. Không có node nào là "server chính". Config đồng bộ qua GitHub Gist.

---

## Tính năng

- **1-click install** — Windows/Linux/macOS
- **Phân tán thực sự** — Tất cả nodes bình đẳng, không có primary server
- **Cloudflare Tunnel** — Tự động expose WSS ra internet, không cần port forwarding
- **OpenRouter** — Hỗ trợ 100+ LLM models qua 1 API key
- **Config sync** — Đăng nhập GitHub một lần, config tự đồng bộ qua Gist
- **Không hardcode** — API key, model, URL đều lấy từ env/account

---

## Cài đặt nhanh

### Linux / macOS
```bash
curl -fsSL https://raw.githubusercontent.com/Neito112/nioh-server/main/scripts/install.sh | bash
```

### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/Neito112/nioh-server/main/scripts/install.ps1 | iex
```

---

## Cấu hình

Sau khi cài, chỉnh file `.env`:

| Biến | Mô tả | Bắt buộc |
|------|-------|----------|
| `NIOH_API_KEY` | OpenRouter/OpenAI API key | ✓ |
| `NIOH_LLM_BASE_URL` | Base URL của LLM API | ✓ |
| `NIOH_MODEL` | Tên model (vd: `deepseek/deepseek-chat`) | ✓ |
| `NIOH_GITHUB_TOKEN` | GitHub token (scope: `gist`) cho node sync | Multi-node |
| `NIOH_CF_DOMAIN` | Domain tùy chỉnh cho Cloudflare Tunnel | Không |

### Dùng OpenRouter

1. Lấy API key tại [openrouter.ai/keys](https://openrouter.ai/keys)
2. Set trong `.env`:
```
NIOH_API_KEY=sk-or-...
NIOH_LLM_BASE_URL=https://openrouter.ai/api/v1
NIOH_MODEL=deepseek/deepseek-chat
```

### Đồng bộ nhiều máy

1. Tạo GitHub token tại [github.com/settings/tokens](https://github.com/settings/tokens) — chỉ cần scope `gist`
2. Set `NIOH_GITHUB_TOKEN` trên tất cả các máy
3. Chạy server lần đầu → `NIOH_GIST_ID` tự động tạo và lưu vào `.env`
4. Copy `NIOH_GIST_ID` sang các máy khác (hoặc để installer tự tìm)

---

## Kiến trúc

```
ESP32 Firmware (Ni-Oh)
       │
       ▼ OTA: https://node-X.trycloudflare.com/xiaozhi/ota/
       │        (trả về danh sách WSS endpoints từ tất cả nodes)
       │
       ▼ WSS: wss://node-X.trycloudflare.com/xiaozhi/v1/
       │
╔═══════════════════════════════════════╗
║           Node A (nhà)                ║
║  xiaozhi-server + Cloudflare Tunnel   ║
╚═══════════════════╤═══════════════════╝
                    │  GitHub Gist (node registry + config)
╔═══════════════════╧═══════════════════╗
║           Node B (VPS/TV Box)         ║
║  xiaozhi-server + Cloudflare Tunnel   ║
╚═══════════════════════════════════════╝
```

Mỗi node:
- Tự đăng ký WSS URL của mình vào Gist khi khởi động
- Heartbeat mỗi 60s để xác nhận còn online
- Unregister khỏi Gist khi tắt
- ESP32 lấy danh sách tất cả nodes từ OTA endpoint, kết nối node nào available

---

## Chạy thủ công

```bash
cd ~/nioh-server
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
python -m server.main
```

---

## Firmware Ni-Oh

Sau khi server chạy, URL OTA sẽ hiện trên console:
```
OTA URL: https://xxxx.trycloudflare.com/xiaozhi/ota/
WSS URL: wss://xxxx.trycloudflare.com/xiaozhi/v1/
```

Flash firmware và nhập OTA URL vào cấu hình Ni-Oh firmware.

---

## License

MIT — dựa trên [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
