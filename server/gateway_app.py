"""
Ni-Oh App Server (Desktop Setup & Control Center)
-------------------------------------------------
Thành phần 1: APP SERVER (Dành cho chủ máy chủ)
- Setup những gì server sẽ cung cấp:
  + Cấu hình Model AI mặc định & Server API Key
  + Bật/tắt các công cụ (Thời tiết, Tìm kiếm web, Điều khiển PC, Âm nhạc)
- Kích hoạt Cloudflare Tunnel
- XUẤT LINK SERVER cho các mạch Xiaozhi trỏ đến (WSS & OTA)
- XUẤT LINK WEB SERVER cho người dùng vào quản lý Agent như xiaozhi.me
- Theo dõi trạng thái hoạt động và các thiết bị đang kết nối
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging
from aiohttp import web
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from cloudflare.tunnel import (
    start_web_login,
    check_login_status,
    is_cloudflare_logged_in,
    activate_quick_tunnel_link,
    unlink_cloudflare,
    setup_tunnel,
    stop_tunnel
)

logger = logging.getLogger("nioh.app_server")
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")


# ── QUẢN LÝ CẤU HÌNH DỊCH VỤ MÁY CHỦ (SERVER SETUP) ────────

def get_server_config() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("SELECT key, value FROM server_config")
    rows = c.fetchall()
    conn.close()
    cfg = dict(rows)
    return {
        "default_model": cfg.get("default_model", os.environ.get("NIOH_MODEL", "deepseek/deepseek-chat")),
        "server_api_key": cfg.get("server_api_key", os.environ.get("NIOH_API_KEY", "")),
        "enable_weather": cfg.get("enable_weather", "1") == "1",
        "enable_search": cfg.get("enable_search", "1") == "1",
        "enable_pc_control": cfg.get("enable_pc_control", "1") == "1",
        "enable_music": cfg.get("enable_music", "1") == "1",
    }


def save_server_config(data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for k, v in data.items():
        c.execute("INSERT OR REPLACE INTO server_config (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()
    if "server_api_key" in data and data["server_api_key"]:
        os.environ["NIOH_API_KEY"] = data["server_api_key"]
    if "default_model" in data and data["default_model"]:
        os.environ["NIOH_MODEL"] = data["default_model"]


def count_connected_devices() -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM devices WHERE status = 'online'")
        online_count = c.fetchone()[0]
        c.execute("SELECT count(*) FROM devices")
        total_count = c.fetchone()[0]
        c.execute("SELECT device_id, name, status, pairing_code FROM devices ORDER BY status DESC LIMIT 10")
        recent_devices = [{"id": r[0], "name": r[1], "status": r[2], "pin": r[3]} for r in c.fetchall()]
        conn.close()
        return {"online": online_count, "total": total_count, "devices": recent_devices}
    except Exception:
        return {"online": 0, "total": 0, "devices": []}


# Trạng thái Cổng Server
GATEWAY_STATE = {
    "server_running": False,
    "cf_domain": "",
    "portal_web_url": "",
    "wss_url": "",
    "ota_url": "",
}


# ── REST API CHO APP SERVER ─────────────────────────────────

async def api_get_gateway_status(request):
    cf_status = check_login_status()
    server_cfg = get_server_config()
    stats = count_connected_devices()

    return web.json_response({
        **GATEWAY_STATE,
        "cf_logged_in": cf_status["logged_in"],
        "cf_account": cf_status["account"],
        "server_setup": server_cfg,
        "device_stats": stats,
    })


async def api_save_server_setup(request):
    """Lưu các dịch vụ và thiết lập máy chủ sẽ cung cấp."""
    data = await request.json()
    save_server_config(data)
    return web.json_response({"success": True, "message": "Đã lưu thiết lập dịch vụ máy chủ thành công!"})


async def api_toggle_gateway(request):
    """Bật/tắt Cloudflare và xuất các đường link server."""
    data = await request.json()
    action = data.get("action")
    domain = data.get("custom_domain", "").strip()

    if action == "start":
        # Tự động kích hoạt liên kết Cloudflare
        activate_quick_tunnel_link()
        try:
            tunnel_res = await setup_tunnel(8001, domain=domain)
            
            GATEWAY_STATE["server_running"] = True
            GATEWAY_STATE["cf_domain"] = domain
            GATEWAY_STATE["portal_web_url"] = tunnel_res["public_url"]
            GATEWAY_STATE["wss_url"] = tunnel_res["wss_url"]
            GATEWAY_STATE["ota_url"] = tunnel_res["ota_url"]

            return web.json_response({"success": True, "state": GATEWAY_STATE})
        except Exception as e:
            GATEWAY_STATE["server_running"] = False
            logger.error(f"Lỗi khởi chạy Cloudflare Tunnel: {e}")
            return web.json_response({"success": False, "message": f"Lỗi khởi chạy Cloudflare: {str(e)}"})
    else:
        GATEWAY_STATE["server_running"] = False
        stop_tunnel()
        GATEWAY_STATE["portal_web_url"] = ""
        GATEWAY_STATE["wss_url"] = ""
        GATEWAY_STATE["ota_url"] = ""
        return web.json_response({"success": True, "state": GATEWAY_STATE})


# ── GIAO DIỆN APP SERVER (DESKTOP CONTROL CENTER) ───────────

HTML_GATEWAY_APP = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh App Server — Cổng Điều Khiển Máy Chủ</title>
    <style>
        :root {
            --bg: #090d16; --panel: #131b2e; --panel-sub: #0c1222;
            --accent: #38bdf8; --cf: #f38020; --cf-hover: #fa6400;
            --text: #f8fafc; --muted: #94a3b8; --border: #1e293b;
            --success: #22c55e; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; max-width: 1000px; margin: 0 auto; }
        
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .title { font-size: 22px; font-weight: 800; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .status-pill { display: inline-block; padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: bold; }
        .status-online { background: #14532d; color: #4ade80; border: 1px solid #22c55e; }
        .status-offline { background: #450a0a; color: #f87171; border: 1px solid #ef4444; }

        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 22px; }
        .card-title { font-size: 16px; font-weight: 700; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
        
        .btn { background: var(--accent); color: #090d16; border: none; padding: 12px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.2s; font-size: 14px; width: 100%; text-align: center; }
        .btn:hover { filter: brightness(1.1); }
        .btn-cf { background: var(--cf); color: white; font-size: 15px; padding: 14px; }
        .btn-cf:hover { background: var(--cf-hover); }
        .btn-danger { background: var(--danger); color: white; }
        .btn-sm { width: auto; padding: 6px 14px; font-size: 12px; }

        .input-group { margin-bottom: 14px; }
        label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
        input, select { width: 100%; background: #070a12; border: 1px solid var(--border); color: white; padding: 10px 14px; border-radius: 8px; font-size: 13px; outline: none; }
        input:focus, select:focus { border-color: var(--accent); }

        .checkbox-item { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 13px; cursor: pointer; }
        .checkbox-item input { width: auto; cursor: pointer; }

        /* Hộp xuất link Cloudflare to và nổi bật */
        .export-result-box { background: #050b18; border: 2px solid #38bdf8; box-shadow: 0 0 25px rgba(56, 189, 248, 0.25); border-radius: 12px; padding: 20px; margin-top: 20px; }
        .export-item { margin-bottom: 14px; }
        .export-label { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; margin-bottom: 4px; }
        .export-url { font-size: 15px; font-weight: 800; color: #38bdf8; word-break: break-all; padding: 8px 12px; background: rgba(56, 189, 248, 0.1); border-radius: 6px; display: flex; justify-content: space-between; align-items: center; gap: 10px; }

        .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
        .stat-card { background: var(--panel-sub); border: 1px solid var(--border); border-radius: 10px; padding: 14px; text-align: center; }
        .stat-number { font-size: 24px; font-weight: 800; color: var(--accent); }
        .stat-desc { font-size: 12px; color: var(--muted); margin-top: 4px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span>⚡ Ni-Oh App Server</span>
            <span style="background: #1e293b; color: var(--accent); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid var(--border);">CỔNG ĐIỀU KHIỂN MÁY CHỦ</span>
        </div>
        <div id="statusBadge" class="status-pill status-offline">CỔNG SERVER: ĐÃ TẮT</div>
    </div>

    <!-- HÀNG 1: THIẾT LẬP DỊCH VỤ MÁY CHỦ & KÍCH HOẠT CLOUDFLARE -->
    <div class="grid">
        <!-- KHỐI 1: Thiết lập những gì Server sẽ cung cấp -->
        <div class="card">
            <div class="card-title">
                <span>⚙️ 1. Thiết Lập Dịch Vụ Máy Chủ Cung Cấp</span>
            </div>
            
            <div class="input-group">
                <label>Mô hình AI mặc định của Server:</label>
                <select id="serverModel">
                    <option value="deepseek/deepseek-chat">⭐ DeepSeek V3 (Khuyên dùng: Nhanh, Tiếng Việt chuẩn)</option>
                    <option value="google/gemini-2.0-flash:free">🎁 Google Gemini 2.0 Flash (FREE 100%, Siêu tốc)</option>
                    <option value="openai/gpt-4o-mini">⚡ GPT-4o Mini (Phản hồi tức thì)</option>
                    <option value="anthropic/claude-3.5-sonnet">👑 Claude 3.5 Sonnet (Thông minh nhất)</option>
                    <option value="meta-llama/llama-3.3-70b-instruct">🧠 Llama 3.3 70B</option>
                </select>
            </div>

            <div class="input-group">
                <label>Server API Key (Key của chủ máy chủ cấp cho người dùng):</label>
                <input type="password" id="serverApiKey" placeholder="sk-xxxx (Cấp để người dùng không cần mua key riêng)">
            </div>

            <label style="margin-bottom: 8px;">Các công cụ (Tools) Server mở cho mạch Xiaozhi:</label>
            <div style="background: var(--panel-sub); padding: 12px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 16px;">
                <label class="checkbox-item"><input type="checkbox" id="toolWeather" checked> 🌤️ Tra cứu thời tiết tiếng Việt (Open-Meteo miễn phí)</label>
                <label class="checkbox-item"><input type="checkbox" id="toolSearch" checked> 🔍 Tìm kiếm thông tin Internet (DuckDuckGo miễn phí)</label>
                <label class="checkbox-item"><input type="checkbox" id="toolPC" checked> 💻 Điều khiển máy tính PC (Tắt máy, âm lượng, khóa máy)</label>
                <label class="checkbox-item"><input type="checkbox" id="toolMusic" checked> 🎵 Phát nhạc qua mạng (yt-dlp stream)</label>
            </div>

            <button class="btn" style="background: #1e293b; color: #cbd5e1; border: 1px solid #334155;" onclick="saveServerSetup()">💾 Lưu Thiết Lập Dịch Vụ Máy Chủ</button>
        </div>

        <!-- KHỐI 2: Kích hoạt Cloudflare & Xuất Link Server -->
        <div class="card">
            <div class="card-title">
                <span>🚀 2. Kích Hoạt Cloudflare & Xuất Link Server</span>
            </div>

            <div class="input-group">
                <label>Tên miền riêng (Tùy chọn - Bỏ trống sẽ dùng link Cloudflare tự động):</label>
                <input type="text" id="customDomainInput" placeholder="ví dụ: voice.yourdomain.com">
            </div>

            <p style="font-size: 13px; color: var(--muted); margin-bottom: 16px; line-height: 1.5;">
                Nhấp nút bên dưới để khởi động toàn bộ động cơ WebSocket âm thanh và kích hoạt Cloudflare Anycast toàn cầu để <strong>xuất ra đường link kết nối</strong>.
            </p>

            <button class="btn btn-cf" id="gatewayToggleBtn" onclick="toggleGateway()">
                🚀 KÍCH HOẠT SERVER & XUẤT LINK CLOUDFLARE
            </button>

            <!-- HỘP KẾT QUẢ XUẤT LINK ĐẦY ĐỦ -->
            <div class="export-result-box" id="exportBox" style="display: none;">
                <!-- 1. Link Web Server cho người dùng -->
                <div class="export-item">
                    <div class="export-label">🌐 LINK WEB SERVER (Quản lý Agent như xiaozhi.me):</div>
                    <div class="export-url">
                        <span id="portalLinkText">https://...</span>
                        <div>
                            <button class="btn btn-sm" style="background: #8b5cf6; color: white;" onclick="copyText('portalLinkText')">📋 Sao chép</button>
                            <button class="btn btn-sm" style="background: #0284c7; color: white; margin-left: 4px;" onclick="openPortalLink()">Mở Web</button>
                        </div>
                    </div>
                </div>

                <!-- 2. Link WebSocket cho mạch Xiaozhi -->
                <div class="export-item">
                    <div class="export-label">📡 LINK SERVER CHO CÁC MẠCH XIAOZHI TRỎ ĐẾN:</div>
                    <div class="export-url">
                        <span id="wssLinkText">wss://.../xiaozhi/v1/</span>
                        <button class="btn btn-sm" style="background: #1e293b; color: white;" onclick="copyText('wssLinkText')">📋 Sao chép</button>
                    </div>
                </div>

                <!-- 3. Link OTA Firmware -->
                <div class="export-item" style="margin-bottom: 0;">
                    <div class="export-label">🔄 CỔNG CẬP NHẬT OTA CHO ESP32:</div>
                    <div class="export-url">
                        <span id="otaLinkText">https://.../xiaozhi/ota/</span>
                        <button class="btn btn-sm" style="background: #1e293b; color: white;" onclick="copyText('otaLinkText')">📋 Sao chép</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- HÀNG 2: BẢNG THEO DÕI THIẾT BỊ XIAOZHI ĐANG KẾT NỐI -->
    <div class="card" style="margin-top: 20px;">
        <div class="card-title">
            <span>📊 Giám Sát Kết Nối Mạch Xiaozhi Thời Gian Thực</span>
            <button class="btn btn-sm" style="background: #1e293b; color: #94a3b8;" onclick="loadGatewayStatus()">🔄 Làm mới</button>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number" id="statOnline">0</div>
                <div class="stat-desc">Mạch Xiaozhi đang Online</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="statTotal">0</div>
                <div class="stat-desc">Tổng thiết bị đã ghép đôi</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="statEngine">Sẵn sàng</div>
                <div class="stat-desc">Động cơ WebSocket (16kHz Opus)</div>
            </div>
        </div>

        <div id="deviceListDisplay" style="font-size: 13px; color: var(--muted); border-top: 1px solid var(--border); padding-top: 14px;">
            Chưa có mạch Xiaozhi nào kết nối.
        </div>
    </div>

    <script>
        async function loadGatewayStatus() {
            try {
                const res = await fetch('/api/gateway/status');
                const data = await res.json();

                const isRun = data.server_running;
                const badge = document.getElementById('statusBadge');
                const btn = document.getElementById('gatewayToggleBtn');
                const exportBox = document.getElementById('exportBox');

                if (isRun) {
                    badge.innerText = "CỔNG SERVER: HOẠT ĐỘNG (ONLINE)";
                    badge.className = "status-pill status-online";
                    btn.innerText = "🛑 DỪNG CỔNG SERVER";
                    btn.className = "btn btn-danger";

                    exportBox.style.display = "block";
                    document.getElementById('portalLinkText').innerText = data.portal_web_url;
                    document.getElementById('wssLinkText').innerText = data.wss_url;
                    document.getElementById('otaLinkText').innerText = data.ota_url;
                } else {
                    badge.innerText = "CỔNG SERVER: ĐÃ TẮT";
                    badge.className = "status-pill status-offline";
                    btn.innerText = "🚀 KÍCH HOẠT SERVER & XUẤT LINK CLOUDFLARE";
                    btn.className = "btn btn-cf";

                    exportBox.style.display = "none";
                }

                // Cập nhật cấu hình server
                if (data.server_setup) {
                    const s = data.server_setup;
                    document.getElementById('serverModel').value = s.default_model || "deepseek/deepseek-chat";
                    document.getElementById('serverApiKey').value = s.server_api_key || "";
                    document.getElementById('toolWeather').checked = s.enable_weather;
                    document.getElementById('toolSearch').checked = s.enable_search;
                    document.getElementById('toolPC').checked = s.enable_pc_control;
                    document.getElementById('toolMusic').checked = s.enable_music;
                }

                // Cập nhật thống kê thiết bị
                if (data.device_stats) {
                    const st = data.device_stats;
                    document.getElementById('statOnline').innerText = st.online;
                    document.getElementById('statTotal').innerText = st.total;
                    
                    const devList = document.getElementById('deviceListDisplay');
                    if (st.devices && st.devices.length > 0) {
                        devList.innerHTML = st.devices.map(d => `
                            <div style="display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #1e293b;">
                                <span>🤖 <strong>${d.name}</strong> (Mã PIN: ${d.pin})</span>
                                <span style="color: ${d.status === 'online' ? '#4ade80' : '#94a3b8'}; font-weight: 600;">
                                    ${d.status === 'online' ? '🟢 Đang Online' : '⚪ Offline'}
                                </span>
                            </div>
                        `).join('');
                    } else {
                        devList.innerText = "Chưa có mạch Xiaozhi nào kết nối.";
                    }
                }
            } catch (e) {
                console.error("Lỗi cập nhật trạng thái:", e);
            }
        }

        async function saveServerSetup() {
            const payload = {
                default_model: document.getElementById('serverModel').value,
                server_api_key: document.getElementById('serverApiKey').value.trim(),
                enable_weather: document.getElementById('toolWeather').checked ? "1" : "0",
                enable_search: document.getElementById('toolSearch').checked ? "1" : "0",
                enable_pc_control: document.getElementById('toolPC').checked ? "1" : "0",
                enable_music: document.getElementById('toolMusic').checked ? "1" : "0"
            };
            const res = await fetch('/api/gateway/save-setup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            alert(data.message);
        }

        async function toggleGateway() {
            const isRunning = document.getElementById('statusBadge').innerText.includes("ONLINE");
            const action = isRunning ? "stop" : "start";
            const domain = document.getElementById('customDomainInput').value.trim();

            const btn = document.getElementById('gatewayToggleBtn');
            btn.innerText = "⏳ Đang kết nối hạ tầng Cloudflare...";
            btn.disabled = true;

            try {
                const res = await fetch('/api/gateway/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ action: action, custom_domain: domain })
                });
                const data = await res.json();
                if (!data.success) {
                    alert(data.message);
                }
            } catch (e) {
                alert("Lỗi kết nối máy chủ: " + e);
            } finally {
                btn.disabled = false;
                loadGatewayStatus();
            }
        }

        function copyText(elementId) {
            const txt = document.getElementById(elementId).innerText;
            navigator.clipboard.writeText(txt);
            alert("Đã sao chép vào bộ nhớ đệm: " + txt);
        }

        function openPortalLink() {
            const url = document.getElementById('portalLinkText').innerText;
            window.open(url, '_blank');
        }

        loadGatewayStatus();
        setInterval(loadGatewayStatus, 5000);
    </script>
</body>
</html>
"""
