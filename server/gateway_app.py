"""
Ni-Oh Server Gateway (Desktop App)
----------------------------------
Đóng vai trò là CỔNG SERVER:
- Đăng nhập tài khoản CLOUDFLARE (Tunnel Token / Zero Trust / Cloudflare Account)
- Mở cổng WebSocket (8000) và OTA (8003) cho các mạch ESP32 kết nối
- Tự động XUẤT LINK WEB QUẢN LÝ THIẾT BỊ (Web Portal cho người dùng cuối)
- Giám sát trạng thái trạm máy chủ và lưu lượng thiết bị
"""

import os
import sys
import json
import asyncio
import logging
import webbrowser
from aiohttp import web
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from cloudflare.tunnel import setup_tunnel, stop_tunnel

logger = logging.getLogger("nioh.server_gateway")

ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

# Trạng thái Cổng Server
GATEWAY_STATE = {
    "server_running": False,
    "cf_account_name": os.environ.get("NIOH_CF_ACCOUNT", "Cloudflare Account"),
    "cf_tunnel_token": os.environ.get("NIOH_CF_TOKEN", ""),
    "cf_domain": os.environ.get("NIOH_CF_DOMAIN", ""),
    "portal_web_url": "",
    "wss_url": "",
    "ota_url": "",
    "active_connections": 0,
    "uptime_seconds": 0,
}


# ── REST API cho Cổng Server ────────────────────────────────

async def api_get_gateway_status(request):
    return web.json_response(GATEWAY_STATE)


async def api_save_cloudflare_auth(request):
    data = await request.json()
    GATEWAY_STATE["cf_account_name"] = data.get("account_name", GATEWAY_STATE["cf_account_name"])
    GATEWAY_STATE["cf_tunnel_token"] = data.get("tunnel_token", GATEWAY_STATE["cf_tunnel_token"])
    GATEWAY_STATE["cf_domain"] = data.get("custom_domain", GATEWAY_STATE["cf_domain"])

    # Lưu cấu hình Cloudflare
    _save_cf_env()
    return web.json_response({"success": True, "message": "Đã lưu tài khoản Cloudflare thành công!"})


async def api_toggle_gateway(request):
    data = await request.json()
    action = data.get("action")

    if action == "start":
        GATEWAY_STATE["server_running"] = True
        try:
            # Thiết lập Cloudflare Tunnel
            wss = await setup_tunnel(8000)
            base_http = wss.replace("wss://", "https://").replace("/xiaozhi/v1/", "")
            
            GATEWAY_STATE["wss_url"] = wss
            GATEWAY_STATE["ota_url"] = f"{base_http}/xiaozhi/ota/"
            GATEWAY_STATE["portal_web_url"] = f"{base_http}/portal"
        except Exception as e:
            logger.warning(f"Chạy ở chế độ Local Tunnel: {e}")
            GATEWAY_STATE["wss_url"] = "ws://localhost:8000/xiaozhi/v1/"
            GATEWAY_STATE["ota_url"] = "http://localhost:8003/xiaozhi/ota/"
            GATEWAY_STATE["portal_web_url"] = "http://localhost:8001/portal"
    else:
        GATEWAY_STATE["server_running"] = False
        stop_tunnel()
        GATEWAY_STATE["portal_web_url"] = ""
        GATEWAY_STATE["wss_url"] = ""
        GATEWAY_STATE["ota_url"] = ""

    return web.json_response({"success": True, "state": GATEWAY_STATE})


def _save_cf_env():
    lines = [
        f"NIOH_CF_ACCOUNT={GATEWAY_STATE['cf_account_name']}\n",
        f"NIOH_CF_TOKEN={GATEWAY_STATE['cf_tunnel_token']}\n",
        f"NIOH_CF_DOMAIN={GATEWAY_STATE['cf_domain']}\n",
    ]
    with open(ENV_FILE, "a+", encoding="utf-8") as f:
        f.writelines(lines)


# ── Giao diện Desktop App: CỔNG SERVER (Server Gateway) ─────

HTML_GATEWAY_APP = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Server Gateway</title>
    <style>
        :root {
            --bg: #090d16; --panel: #131b2e; --accent: #38bdf8; --cf: #f38020;
            --text: #f8fafc; --muted: #94a3b8; --border: #1e293b; --success: #22c55e; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; max-width: 950px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .title { font-size: 22px; font-weight: 800; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .cf-badge { background: var(--cf); color: white; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
        .card-title { font-size: 15px; font-weight: 700; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
        .btn { background: var(--accent); color: #090d16; border: none; padding: 12px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.2s; font-size: 14px; width: 100%; }
        .btn:hover { filter: brightness(1.1); }
        .btn-cf { background: var(--cf); color: white; }
        .btn-danger { background: var(--danger); color: white; }
        .input-group { margin-bottom: 14px; }
        label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
        input { width: 100%; background: #070a12; border: 1px solid var(--border); color: white; padding: 10px 12px; border-radius: 8px; font-size: 14px; outline: none; }
        input:focus { border-color: var(--accent); }
        .portal-result-box { background: #070a12; border: 2px dashed #0284c7; border-radius: 10px; padding: 18px; margin-top: 16px; text-align: center; }
        .portal-url { font-size: 16px; font-weight: bold; color: #38bdf8; word-break: break-all; margin: 10px 0; text-decoration: none; display: inline-block; }
        .status-pill { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: bold; }
        .status-online { background: #14532d; color: #4ade80; }
        .status-offline { background: #450a0a; color: #f87171; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span>⚡ Ni-Oh Server Gateway</span>
            <span class="cf-badge">CLOUDFLARE LINKED</span>
        </div>
        <div id="statusBadge" class="status-pill status-offline">CỔNG SERVER: ĐÃ TẮT</div>
    </div>

    <div class="grid">
        <!-- Cột 1: Đăng nhập liên kết Cloudflare -->
        <div class="card">
            <div class="card-title">☁️ Tài Khoản Liên Kết Cloudflare</div>
            <div class="input-group">
                <label>Tên định danh / Email Cloudflare</label>
                <input type="text" id="cfAccountInput" placeholder="admin@domain.com">
            </div>
            <div class="input-group">
                <label>Cloudflare Tunnel Token / API Key</label>
                <input type="password" id="cfTokenInput" placeholder="eyJhIjoiOGRi...">
            </div>
            <div class="input-group">
                <label>Tên miền riêng (Custom Domain - Bỏ trống = Tự cấp free)</label>
                <input type="text" id="cfDomainInput" placeholder="xiaozhi.yourdomain.com">
            </div>
            <button class="btn btn-cf" onclick="saveCfAuth()">🔗 Lưu Liên Kết Cloudflare</button>
        </div>

        <!-- Cột 2: Bật Cổng & Xuất Link Web Quản Lý -->
        <div class="card">
            <div class="card-title">🚀 Kích Hoạt Cổng & Xuất Link Web</div>
            <p style="font-size: 13px; color: var(--muted); margin-bottom: 16px;">
                Nhấp nút bên dưới để mở cổng WebSocket âm thanh cho mạch ESP32 và xuất đường link trang web quản lý thiết bị.
            </p>

            <button class="btn" id="gatewayToggleBtn" onclick="toggleGateway()">BẬT CỔNG SERVER & XUẤT LINK WEB</button>

            <!-- Hộp hiển thị Link Web sau khi kích hoạt -->
            <div class="portal-result-box" id="portalBox" style="display: none;">
                <span style="font-size: 13px; color: var(--muted);">🌐 Link Web Quản Lý Thiết Bị (Chia sẻ cho người dùng):</span><br>
                <a href="#" target="_blank" id="portalLink" class="portal-url">https://...</a>
                <br>
                <button class="btn" style="background: #8b5cf6; color: white; width: auto; padding: 6px 14px; font-size: 12px;" onclick="copyPortalLink()">📋 Sao chép Link</button>
                <button class="btn" style="background: #0284c7; color: white; width: auto; padding: 6px 14px; font-size: 12px; margin-left: 8px;" onclick="openPortal()">Mở Web Ngay</button>
            </div>
        </div>

        <!-- Giám sát thông số cổng -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-title">📊 Thông Số Cổng Kết Nối Mạch ESP32</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; font-size: 13px;">
                <div>
                    <span style="color: var(--muted)">WebSocket Voice:</span><br>
                    <code id="wssDisplay" style="color: var(--accent)">Chưa kích hoạt</code>
                </div>
                <div>
                    <span style="color: var(--muted)">OTA Endpoint:</span><br>
                    <code id="otaDisplay" style="color: var(--accent)">Chưa kích hoạt</code>
                </div>
                <div>
                    <span style="color: var(--muted)">Số mạch ESP32 đang online:</span><br>
                    <strong style="font-size: 16px; color: var(--success);" id="connCount">0 thiết bị</strong>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function loadGatewayStatus() {
            const res = await fetch('/api/gateway/status');
            const data = await res.json();
            document.getElementById('cfAccountInput').value = data.cf_account_name || "";
            document.getElementById('cfTokenInput').value = data.cf_tunnel_token || "";
            document.getElementById('cfDomainInput').value = data.cf_domain || "";

            const isRun = data.server_running;
            const badge = document.getElementById('statusBadge');
            const btn = document.getElementById('gatewayToggleBtn');
            const portalBox = document.getElementById('portalBox');
            const portalLink = document.getElementById('portalLink');

            if (isRun) {
                badge.innerText = "CỔNG SERVER: HOẠT ĐỘNG (ONLINE)";
                badge.className = "status-pill status-online";
                btn.innerText = "DỪNG CỔNG SERVER";
                btn.className = "btn btn-danger";

                portalBox.style.display = "block";
                portalLink.href = data.portal_web_url;
                portalLink.innerText = data.portal_web_url;

                document.getElementById('wssDisplay').innerText = data.wss_url;
                document.getElementById('otaDisplay').innerText = data.ota_url;
            } else {
                badge.innerText = "CỔNG SERVER: ĐÃ TẮT";
                badge.className = "status-pill status-offline";
                btn.innerText = "BẬT CỔNG SERVER & XUẤT LINK WEB";
                btn.className = "btn";

                portalBox.style.display = "none";
                document.getElementById('wssDisplay').innerText = "Chưa kích hoạt";
                document.getElementById('otaDisplay').innerText = "Chưa kích hoạt";
            }
        }

        async function saveCfAuth() {
            const payload = {
                account_name: document.getElementById('cfAccountInput').value,
                tunnel_token: document.getElementById('cfTokenInput').value,
                custom_domain: document.getElementById('cfDomainInput').value
            };
            const res = await fetch('/api/gateway/cf-auth', {
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
            await fetch('/api/gateway/toggle', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ action })
            });
            setTimeout(loadGatewayStatus, 1500);
        }

        function copyPortalLink() {
            const url = document.getElementById('portalLink').innerText;
            navigator.clipboard.writeText(url);
            alert("Đã sao chép link web quản lý!");
        }

        function openPortal() {
            window.open(document.getElementById('portalLink').href, '_blank');
        }

        loadGatewayStatus();
    </script>
</body>
</html>
"""
