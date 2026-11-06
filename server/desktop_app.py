"""
Ni-Oh Server Engine & Desktop Application (Dashboard 1)
------------------------------------------------------
Giao diện Desktop App quản lý máy chủ tổng (Server Host Dashboard):
- Không khóa cứng OpenRouter (hỗ trợ DeepSeek, OpenAI, Groq, Ollama...)
- Bật/tắt Cloudflare Tunnel chỉ với 1 click
- Bảng công tắc Toggle bật/tắt toàn bộ các Tools (PC Control, Weather, Search, Music, ESP-NOW, Smart Home)
- Phục vụ Web Portal Quản lý Thiết bị (Dashboard 2)
"""

import os
import sys
import json
import asyncio
import logging
import webbrowser
from aiohttp import web
from dotenv import load_dotenv

# Thêm đường dẫn gốc
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from server.tools.pc_control import execute_pc_command
from server.tools.free_weather import get_weather
from server.tools.free_search import search_web
from server.tools.free_music import search_and_get_audio_stream
from server.tools.esp_now_handler import build_esp_now_packet
from server.tools.iot_discovery import scan_local_iot_devices, generate_auth_qr_link
from cloudflare.tunnel import setup_tunnel, stop_tunnel

logger = logging.getLogger("nioh.desktop_app")

ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

# Cấu hình trạng thái Runtime
STATE = {
    "server_running": False,
    "tunnel_url": "",
    "wss_url": "",
    "host_account": os.environ.get("NIOH_HOST_ACCOUNT", "admin@nioh.local"),
    "llm_provider": "openrouter",
    "llm_base_url": os.environ.get("NIOH_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    "llm_api_key": os.environ.get("NIOH_API_KEY", ""),
    "llm_model": os.environ.get("NIOH_MODEL", "deepseek/deepseek-chat"),
    "tools": {
        "pc_control": True,
        "weather": True,
        "web_search": True,
        "music": True,
        "esp_now": True,
        "smart_home": True,
    },
    "bound_devices": [],
    "pairing_codes": {},  # {"123456": {"device_id": "esp32-abc", "created_at": ...}}
}


# ── REST API cho Desktop App Dashboard ──────────────────────

async def api_get_status(request):
    return web.json_response(STATE)


async def api_save_config(request):
    data = await request.json()
    STATE["llm_provider"] = data.get("provider", STATE["llm_provider"])
    STATE["llm_base_url"] = data.get("base_url", STATE["llm_base_url"])
    STATE["llm_api_key"] = data.get("api_key", STATE["llm_api_key"])
    STATE["llm_model"] = data.get("model", STATE["llm_model"])
    if "tools" in data:
        STATE["tools"].update(data["tools"])

    # Lưu lại vào .env
    _save_to_env()
    return web.json_response({"success": True, "message": "Đã lưu cấu hình server thành công!"})


async def api_toggle_server(request):
    data = await request.json()
    action = data.get("action")
    if action == "start":
        STATE["server_running"] = True
        try:
            # Khởi động Tunnel
            wss_url = await setup_tunnel(8000)
            STATE["wss_url"] = wss_url
            STATE["tunnel_url"] = wss_url.replace("wss://", "https://").replace("/xiaozhi/v1/", "")
        except Exception as e:
            logger.warning(f"Tunnel lỗi hoặc đang chạy offline: {e}")
            STATE["wss_url"] = "ws://localhost:8000/xiaozhi/v1/"
            STATE["tunnel_url"] = "http://localhost:8003"
    else:
        STATE["server_running"] = False
        stop_tunnel()
        STATE["tunnel_url"] = ""
        STATE["wss_url"] = ""

    return web.json_response({"success": True, "state": STATE})


async def api_scan_iot(request):
    res = await scan_local_iot_devices()
    return web.json_response(res)


# ── REST API cho Web Portal (Dashboard 2 - Quản lý thiết bị qua mã 6 số) ──

async def api_device_bind(request):
    """Người dùng nhập mã 6 số để ghép đôi ESP32 vào tài khoản."""
    data = await request.json()
    code = data.get("pairing_code", "").strip()
    user_id = data.get("user_id", "guest")
    bot_name = data.get("bot_name", "Ni-Oh S3 Mini")

    # Kiểm tra mã
    if code in STATE["pairing_codes"]:
        device_info = STATE["pairing_codes"].pop(code)
        device_info["bot_name"] = bot_name
        device_info["owner"] = user_id
        STATE["bound_devices"].append(device_info)
        return web.json_response({"success": True, "message": f"Ghép đôi thiết bị '{bot_name}' thành công!"})
    else:
        # Nếu chưa có thiết bị nào phát mã, mô phỏng chấp nhận trực tiếp cho thiết bị demo
        new_dev = {
            "device_id": f"nioh-{code if code else 'device-1'}",
            "bot_name": bot_name,
            "owner": user_id,
            "status": "online",
            "prompt": "Bạn là trợ lý Ni-Oh thông minh, vui vẻ và thân thiện.",
            "voice": "vi-VN-HoaiMyNeural",
            "model": STATE["llm_model"],
        }
        STATE["bound_devices"].append(new_dev)
        return web.json_response({"success": True, "message": f"Đã kết nối thiết bị với mã {code}!"})


async def api_get_my_devices(request):
    return web.json_response({"devices": STATE["bound_devices"]})


# ── Helper lưu .env ──────────────────────────────────────────

def _save_to_env():
    lines = [
        f"NIOH_API_KEY={STATE['llm_api_key']}\n",
        f"NIOH_LLM_BASE_URL={STATE['llm_base_url']}\n",
        f"NIOH_MODEL={STATE['llm_model']}\n",
        f"NIOH_HOST_ACCOUNT={STATE['host_account']}\n",
    ]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ── Giao diện HTML Dashboard 1 (Desktop Server App) ─────────

HTML_DESKTOP_DASHBOARD = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Server Host Control Center</title>
    <style>
        :root {
            --bg: #0f172a; --panel: #1e293b; --accent: #38bdf8; --text: #f8fafc;
            --muted: #94a3b8; --border: #334155; --success: #22c55e; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .title { font-size: 24px; font-weight: 700; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .badge { background: #0284c7; color: white; padding: 4px 10px; border-radius: 999px; font-size: 12px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
        .card-title { font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
        .btn { background: var(--accent); color: #000; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .btn:hover { opacity: 0.9; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-portal { background: #8b5cf6; color: white; }
        .input-group { margin-bottom: 14px; }
        label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
        input, select { width: 100%; background: #0b1120; border: 1px solid var(--border); color: white; padding: 10px; border-radius: 6px; font-size: 14px; }
        .switch-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #283548; }
        .status-box { padding: 12px; background: #0b1120; border-radius: 8px; font-family: monospace; font-size: 13px; word-break: break-all; margin-top: 10px; }
        .status-online { color: var(--success); }
        .status-offline { color: var(--danger); }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span>⚡ Ni-Oh Server Engine</span>
            <span class="badge" id="hostAccount">Host Account</span>
        </div>
        <div style="display: flex; gap: 10px;">
            <button class="btn btn-portal" onclick="openDevicePortal()">🌐 Mở Web Quản Lý Thiết Bị</button>
            <button class="btn" id="serverToggleBtn" onclick="toggleServer()">Khởi động Server</button>
        </div>
    </div>

    <div class="grid">
        <!-- Cột 1: Cấu hình Model & Provider -->
        <div class="card">
            <div class="card-title">🤖 Cấu hình LLM (Không khóa cứng)</div>
            <div class="input-group">
                <label>Nhà cung cấp AI (Provider)</label>
                <select id="providerSelect" onchange="onProviderChange()">
                    <option value="openrouter">OpenRouter (100+ Models)</option>
                    <option value="deepseek">DeepSeek (Chính thức)</option>
                    <option value="openai">OpenAI (ChatGPT)</option>
                    <option value="groq">Groq (Siêu tốc độ)</option>
                    <option value="ollama">Ollama (Chạy Offline tại nhà)</option>
                    <option value="custom">Tùy chỉnh (OpenAI-compatible)</option>
                </select>
            </div>
            <div class="input-group">
                <label>API Base URL</label>
                <input type="text" id="baseUrlInput" placeholder="https://api.openai.com/v1">
            </div>
            <div class="input-group">
                <label>API Key</label>
                <input type="password" id="apiKeyInput" placeholder="Dán API Key của bạn vào đây">
            </div>
            <div class="input-group">
                <label>Tên Model</label>
                <input type="text" id="modelInput" placeholder="deepseek/deepseek-chat">
            </div>
            <button class="btn" style="width: 100%; margin-top: 8px;" onclick="saveConfig()">💾 Lưu Cấu Hình</button>
        </div>

        <!-- Cột 2: Trạng thái & Cloudflare Tunnel -->
        <div class="card">
            <div class="card-title">📡 Kết nối & Mạng (Cloudflare Tunnel)</div>
            <div class="switch-row">
                <span>Trạng thái Server</span>
                <strong id="serverStatusText" class="status-offline">ĐÃ DỪNG</strong>
            </div>
            <div class="input-group" style="margin-top: 12px;">
                <label>Địa chỉ WebSocket nạp vào ESP32:</label>
                <div class="status-box" id="wssUrlBox">Chưa khởi động server</div>
            </div>
            <div class="input-group">
                <label>Địa chỉ OTA Endpoint:</label>
                <div class="status-box" id="otaUrlBox">Chưa khởi động server</div>
            </div>
            <div style="margin-top: 14px;">
                <button class="btn" style="width: 100%; background: #3b82f6; color: white;" onclick="scanIoT()">🔍 Quét Thiết Bị Nhà Thông Minh Trong LAN</button>
                <div id="iotScanResult" style="margin-top: 8px; font-size: 13px; color: var(--muted);"></div>
            </div>
        </div>

        <!-- Bảng điều khiển Tools (100% Free Toggles) -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-title">🛠️ Công cụ & MCP Tích hợp (Tất cả phản hồi từ mạch)</div>
            <div class="grid" style="grid-template-columns: 1fr 1fr 1fr; gap: 12px;">
                <div class="switch-row">
                    <div>
                        <strong>💻 Điều khiển PC</strong><br><small style="color: var(--muted)">Tắt máy, ngủ, khóa màn hình, volume</small>
                    </div>
                    <input type="checkbox" id="tool_pc" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🌤️ Thời tiết Free</strong><br><small style="color: var(--muted)">Open-Meteo không cần key</small>
                    </div>
                    <input type="checkbox" id="tool_weather" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🔎 Tìm kiếm Web Free</strong><br><small style="color: var(--muted)">DuckDuckGo không cần key</small>
                    </div>
                    <input type="checkbox" id="tool_search" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🎵 Nghe nhạc YouTube Free</strong><br><small style="color: var(--muted)">yt-dlp stream âm thanh</small>
                    </div>
                    <input type="checkbox" id="tool_music" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>📡 Giao tiếp ESP-NOW</strong><br><small style="color: var(--muted)">Bắn lệnh qua mạch slave</small>
                    </div>
                    <input type="checkbox" id="tool_espnow" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🏠 Quét Smart Home LAN</strong><br><small style="color: var(--muted)">mDNS & Home Assistant</small>
                    </div>
                    <input type="checkbox" id="tool_smarthome" checked onchange="saveTools()">
                </div>
            </div>
        </div>
    </div>

    <script>
        const PRESETS = {
            openrouter: { url: "https://openrouter.ai/api/v1", model: "deepseek/deepseek-chat" },
            deepseek: { url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
            openai: { url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
            groq: { url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile" },
            ollama: { url: "http://localhost:11434/v1", model: "qwen2.5:7b" },
            custom: { url: "", model: "" }
        };

        async function loadStatus() {
            const res = await fetch('/api/status');
            const data = await res.json();
            document.getElementById('hostAccount').innerText = data.host_account;
            document.getElementById('providerSelect').value = data.llm_provider || 'openrouter';
            document.getElementById('baseUrlInput').value = data.llm_base_url;
            document.getElementById('apiKeyInput').value = data.llm_api_key;
            document.getElementById('modelInput').value = data.llm_model;

            // Update UI status
            const isRun = data.server_running;
            const statusTxt = document.getElementById('serverStatusText');
            const btn = document.getElementById('serverToggleBtn');
            if (isRun) {
                statusTxt.innerText = "ONLINE"; statusTxt.className = "status-online";
                btn.innerText = "Dừng Server"; btn.className = "btn btn-danger";
                document.getElementById('wssUrlBox').innerText = data.wss_url || "Đang tạo...";
                document.getElementById('otaUrlBox').innerText = (data.tunnel_url ? data.tunnel_url + "/xiaozhi/ota/" : "");
            } else {
                statusTxt.innerText = "ĐÃ DỪNG"; statusTxt.className = "status-offline";
                btn.innerText = "Khởi động Server"; btn.className = "btn";
                document.getElementById('wssUrlBox').innerText = "Chưa khởi động";
                document.getElementById('otaUrlBox').innerText = "Chưa khởi động";
            }
        }

        function onProviderChange() {
            const val = document.getElementById('providerSelect').value;
            if (PRESETS[val]) {
                document.getElementById('baseUrlInput').value = PRESETS[val].url;
                if (PRESETS[val].model) document.getElementById('modelInput').value = PRESETS[val].model;
            }
        }

        async function saveConfig() {
            const payload = {
                provider: document.getElementById('providerSelect').value,
                base_url: document.getElementById('baseUrlInput').value,
                api_key: document.getElementById('apiKeyInput').value,
                model: document.getElementById('modelInput').value
            };
            const res = await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
            const data = await res.json();
            alert(data.message);
        }

        async function saveTools() {
            const tools = {
                pc_control: document.getElementById('tool_pc').checked,
                weather: document.getElementById('tool_weather').checked,
                web_search: document.getElementById('tool_search').checked,
                music: document.getElementById('tool_music').checked,
                esp_now: document.getElementById('tool_espnow').checked,
                smart_home: document.getElementById('tool_smarthome').checked
            };
            await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ tools }) });
        }

        async function toggleServer() {
            const isRunning = document.getElementById('serverStatusText').innerText === "ONLINE";
            const action = isRunning ? "stop" : "start";
            await fetch('/api/server/toggle', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ action }) });
            setTimeout(loadStatus, 1500);
        }

        async function scanIoT() {
            const el = document.getElementById('iotScanResult');
            el.innerText = "Đang quét mạng nội bộ...";
            const res = await fetch('/api/iot/scan');
            const data = await res.json();
            el.innerText = data.message;
        }

        function openDevicePortal() {
            window.open('/portal', '_blank');
        }

        loadStatus();
    </script>
</body>
</html>
"""


# ── Giao diện HTML Dashboard 2 (Web Portal - Tương tự xiaozhi.me) ─────────

HTML_DEVICE_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Device Portal (Quản lý thiết bị)</title>
    <style>
        :root { --bg: #f8fafc; --panel: #ffffff; --primary: #2563eb; --text: #1e293b; --border: #e2e8f0; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 20px; max-width: 900px; margin: 0 auto; }
        .nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid var(--border); }
        .logo { font-size: 20px; font-weight: 800; color: var(--primary); }
        .card { background: var(--panel); border-radius: 12px; border: 1px solid var(--border); padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
        .card-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; }
        .pin-container { display: flex; gap: 8px; justify-content: center; margin: 16px 0; }
        .pin-box { width: 45px; height: 55px; font-size: 24px; text-align: center; font-weight: bold; border: 2px solid var(--border); border-radius: 8px; }
        .btn { background: var(--primary); color: white; border: none; padding: 12px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; width: 100%; font-size: 15px; }
        .device-item { border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .online-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; display: inline-block; margin-right: 6px; }
    </style>
</head>
<body>
    <div class="nav">
        <div class="logo">📱 Ni-Oh Portal (xiaozhi.me Alternative)</div>
        <div style="font-size: 14px; color: #64748b;">Đăng nhập: <strong>user@nioh.io</strong></div>
    </div>

    <!-- Hộp nhập mã 6 số để ghép đôi -->
    <div class="card">
        <div class="card-title">🔗 Ghép đôi thiết bị mới (Mã 6 chữ số)</div>
        <p style="font-size: 14px; color: #64748b;">Nhập mã 6 chữ số hiển thị trên màn hình mạch ESP32 để gán vào tài khoản:</p>
        <div class="pin-container">
            <input type="text" maxlength="6" id="pairingInput" class="pin-box" style="width: 220px; letter-spacing: 10px;" placeholder="123456">
        </div>
        <div style="margin-bottom: 14px;">
            <label style="font-size: 13px; color: #64748b;">Đặt tên cho Bot:</label>
            <input type="text" id="botNameInput" style="width: 100%; padding: 8px; margin-top: 4px; border: 1px solid var(--border); border-radius: 6px;" value="Ni-Oh S3 Mini">
        </div>
        <button class="btn" onclick="bindDevice()">Kích hoạt & Ghép đôi</button>
    </div>

    <!-- Danh sách thiết bị đã ghép đôi -->
    <div class="card">
        <div class="card-title">🤖 Thiết bị của tôi</div>
        <div id="deviceList">
            <p style="color: #94a3b8; font-size: 14px;">Chưa có thiết bị nào. Nhập mã 6 số phía trên để kết nối.</p>
        </div>
    </div>

    <script>
        async function loadDevices() {
            const res = await fetch('/api/portal/my-devices');
            const data = await res.json();
            const list = document.getElementById('deviceList');
            if (data.devices.length === 0) {
                list.innerHTML = `<p style="color: #94a3b8; font-size: 14px;">Chưa có thiết bị nào được gán.</p>`;
                return;
            }
            list.innerHTML = data.devices.map(d => `
                <div class="device-item">
                    <div>
                        <strong><span class="online-dot"></span>${d.bot_name}</strong>
                        <div style="font-size: 12px; color: #64748b; margin-top: 4px;">ID: ${d.device_id} | Giọng: ${d.voice || 'Mặc định'}</div>
                    </div>
                    <button style="padding: 6px 12px; border: 1px solid #cbd5e1; background: white; border-radius: 6px; cursor: pointer;">Cài đặt</button>
                </div>
            `).join('');
        }

        async function bindDevice() {
            const code = document.getElementById('pairingInput').value;
            const bot_name = document.getElementById('botNameInput').value;
            if (!code) { alert('Vui lòng nhập mã 6 số!'); return; }
            const res = await fetch('/api/portal/bind', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ pairing_code: code, bot_name: bot_name })
            });
            const data = await res.json();
            alert(data.message);
            loadDevices();
        }

        loadDevices();
    </script>
</body>
</html>
"""


# ── Xây dựng Web App ────────────────────────────────────────

def create_desktop_app():
    app = web.Application()
    # Route HTML
    app.router.add_get("/", lambda req: web.Response(text=HTML_DESKTOP_DASHBOARD, content_type="text/html"))
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_DEVICE_PORTAL, content_type="text/html"))

    # Route API
    app.router.add_get("/api/status", api_get_status)
    app.router.add_post("/api/config", api_save_config)
    app.router.add_post("/api/server/toggle", api_toggle_server)
    app.router.add_get("/api/iot/scan", api_scan_iot)
    app.router.add_post("/api/portal/bind", api_device_bind)
    app.router.add_get("/api/portal/my-devices", api_get_my_devices)

    return app


async def run_desktop_app_server(port: int = 8001):
    app = create_desktop_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"\n[OK] Ni-Oh Desktop App đang chạy tại: http://localhost:{port}")
    print(f"[OK] Web Portal Quản lý Thiết bị tại: http://localhost:{port}/portal\n")
    # Tự động mở trình duyệt
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_desktop_app_server(8001))
    loop.run_forever()
