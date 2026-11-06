"""
Ni-Oh Server Gateway (Desktop App)
----------------------------------
Đóng vai trò là CỔNG SERVER:
- Bước 1: Bắt buộc đăng nhập tài khoản CLOUDFLARE qua web chính thức dash.cloudflare.com
- Bước 2: Nhận chứng chỉ ủy quyền cert.pem thật từ Cloudflare
- Bước 3: Tạo Named Tunnel chính chủ và XUẤT LINK WEB QUẢN LÝ THIẾT BỊ
- Không sử dụng link ảo/local khi chưa đăng nhập
"""

import os
import sys
import json
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
    setup_tunnel,
    stop_tunnel
)

logger = logging.getLogger("nioh.server_gateway")

ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

# Trạng thái Cổng Server
GATEWAY_STATE = {
    "server_running": False,
    "cf_domain": os.environ.get("NIOH_CF_DOMAIN", ""),
    "portal_web_url": "",
    "wss_url": "",
    "ota_url": "",
}


# ── REST API CHO CỔNG SERVER ────────────────────────────────

async def api_get_gateway_status(request):
    cf_status = check_login_status()
    return web.json_response({
        **GATEWAY_STATE,
        "cf_logged_in": cf_status["logged_in"],
        "cf_cert_path": cf_status["cert_path"],
    })


async def api_start_cloudflare_login(request):
    """Kích hoạt mở trang web Cloudflare chính thức để đăng nhập."""
    res = start_web_login()
    return web.json_response(res)


async def api_check_cloudflare_login(request):
    """Kiểm tra chứng chỉ ủy quyền từ Cloudflare."""
    res = check_login_status()
    return web.json_response(res)


async def api_toggle_gateway(request):
    data = await request.json()
    action = data.get("action")
    domain = data.get("custom_domain", "").strip() or GATEWAY_STATE["cf_domain"]

    if action == "start":
        # KIỂM TRA BẮT BUỘC: Đã đăng nhập Cloudflare chưa?
        if not is_cloudflare_logged_in():
            return web.json_response({
                "success": False,
                "message": "BẠN CHƯA ĐĂNG NHẬP CLOUDFLARE!\nVui lòng nhấp nút 'ĐĂNG NHẬP QUA WEB CLOUDFLARE' ở Bước 1 trước khi bật cổng."
            })

        if not domain:
            return web.json_response({
                "success": False,
                "message": "Vui lòng nhập tên miền (Domain) bạn đã ủy quyền trên Cloudflare (ví dụ: voice.yourdomain.com)!"
            })

        GATEWAY_STATE["cf_domain"] = domain
        try:
            wss = await setup_tunnel(8000, domain)
            base_http = f"https://{domain}"

            GATEWAY_STATE["server_running"] = True
            GATEWAY_STATE["wss_url"] = wss
            GATEWAY_STATE["ota_url"] = f"{base_http}/xiaozhi/ota/"
            GATEWAY_STATE["portal_web_url"] = f"{base_http}/portal"

            # Lưu domain vào .env
            with open(ENV_FILE, "a+", encoding="utf-8") as f:
                f.write(f"\nNIOH_CF_DOMAIN={domain}\n")

            return web.json_response({"success": True, "state": GATEWAY_STATE})
        except Exception as e:
            GATEWAY_STATE["server_running"] = False
            logger.error(f"Lỗi khởi chạy Tunnel: {e}")
            return web.json_response({"success": False, "message": f"Lỗi khởi chạy Tunnel Cloudflare: {str(e)}"})
    else:
        GATEWAY_STATE["server_running"] = False
        stop_tunnel()
        GATEWAY_STATE["portal_web_url"] = ""
        GATEWAY_STATE["wss_url"] = ""
        GATEWAY_STATE["ota_url"] = ""
        return web.json_response({"success": True, "state": GATEWAY_STATE})


# ── GIAO DIỆN DESKTOP APP: CỔNG SERVER (Server Gateway) ─────

HTML_GATEWAY_APP = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Server Gateway</title>
    <style>
        :root {
            --bg: #090d16; --panel: #131b2e; --accent: #38bdf8; --cf: #f38020; --cf-hover: #fa6400;
            --text: #f8fafc; --muted: #94a3b8; --border: #1e293b; --success: #22c55e; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; max-width: 950px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .title { font-size: 22px; font-weight: 800; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 22px; }
        .card-title { font-size: 15px; font-weight: 700; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
        .btn { background: var(--accent); color: #090d16; border: none; padding: 12px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.2s; font-size: 14px; width: 100%; }
        .btn:hover { filter: brightness(1.1); }
        .btn-cf { background: var(--cf); color: white; }
        .btn-cf:hover { background: var(--cf-hover); }
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
        .auth-status-card { border: 1px solid #334155; border-radius: 8px; padding: 14px; background: #0a0f1d; margin-bottom: 14px; }
        .step-tag { display: inline-block; background: #0284c7; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-bottom: 8px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span>⚡ Ni-Oh Server Gateway</span>
            <span style="background: #1e293b; color: var(--cf); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid var(--cf);">CLOUDFLARE TUNNEL</span>
        </div>
        <div id="statusBadge" class="status-pill status-offline">CỔNG SERVER: ĐÃ TẮT</div>
    </div>

    <div class="grid">
        <!-- BƯỚC 1: Đăng nhập Cloudflare chính thức -->
        <div class="card">
            <span class="step-tag">BƯỚC 1 (BẮT BUỘC)</span>
            <div class="card-title">☁️ Đăng Nhập Tài Khoản Cloudflare</div>
            
            <div class="auth-status-card">
                <div style="font-size: 13px; margin-bottom: 4px;">Trạng thái chứng chỉ:</div>
                <div id="cfAuthText" style="font-weight: bold; font-size: 14px; color: #f87171;">❌ Chưa liên kết tài khoản Cloudflare</div>
                <div id="cfCertDetail" style="font-size: 11px; color: var(--muted); margin-top: 4px; word-break: break-all;">Chưa tìm thấy cert.pem trên máy</div>
            </div>

            <p style="font-size: 13px; color: var(--muted); margin-bottom: 16px; line-height: 1.5;">
                Nhấp nút bên dưới để mở trang web chính thức <strong>dash.cloudflare.com</strong>. Sau khi đăng nhập và chọn domain của bạn, Cloudflare sẽ tự động gửi chứng chỉ về máy.
            </p>

            <button class="btn btn-cf" id="cfLoginBtn" onclick="triggerCfWebLogin()">
                🌐 ĐĂNG NHẬP QUA WEB CLOUDFLARE
            </button>
        </div>

        <!-- BƯỚC 2: Cấu hình Domain & Xuất Link Web -->
        <div class="card">
            <span class="step-tag" style="background: #16a34a;">BƯỚC 2</span>
            <div class="card-title">🚀 Cấu Hình Tên Miền & Bật Cổng</div>
            
            <div class="input-group">
                <label>Tên miền bạn đã ủy quyền trên Cloudflare:</label>
                <input type="text" id="cfDomainInput" placeholder="ví dụ: voice.yourdomain.com">
            </div>

            <p style="font-size: 13px; color: var(--muted); margin-bottom: 16px; line-height: 1.5;">
                Sau khi liên kết Cloudflare và nhập domain, nhấp nút bên dưới để mở cổng WebSocket âm thanh cho ESP32 và <strong>xuất ra đường link Web Quản Lý</strong>.
            </p>

            <button class="btn" id="gatewayToggleBtn" onclick="toggleGateway()">BẬT CỔNG SERVER & XUẤT LINK WEB</button>

            <!-- Hộp kết quả Link Web thật -->
            <div class="portal-result-box" id="portalBox" style="display: none;">
                <span style="font-size: 13px; color: var(--muted);">🌐 Link Web Quản Lý Thiết Bị (Chia sẻ cho người dùng):</span><br>
                <a href="#" target="_blank" id="portalLink" class="portal-url">https://...</a>
                <br>
                <button class="btn" style="background: #8b5cf6; color: white; width: auto; padding: 6px 14px; font-size: 12px;" onclick="copyPortalLink()">📋 Sao chép Link</button>
                <button class="btn" style="background: #0284c7; color: white; width: auto; padding: 6px 14px; font-size: 12px; margin-left: 8px;" onclick="openPortal()">Mở Web Ngay</button>
            </div>
        </div>

        <!-- Thông số cổng kết nối -->
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
                    <span style="color: var(--muted)">Tình trạng Cổng:</span><br>
                    <strong style="font-size: 14px; color: var(--success);" id="connStatus">Sẵn sàng nhận mạch</strong>
                </div>
            </div>
        </div>
    </div>

    <script>
        let checkAuthInterval = null;
        let isCfLoggedIn = false;

        async function loadGatewayStatus() {
            const res = await fetch('/api/gateway/status');
            const data = await res.json();
            
            isCfLoggedIn = data.cf_logged_in;
            const authText = document.getElementById('cfAuthText');
            const certDetail = document.getElementById('cfCertDetail');
            const loginBtn = document.getElementById('cfLoginBtn');

            if (isCfLoggedIn) {
                authText.innerText = "✅ ĐÃ LIÊN KẾT TÀI KHOẢN CLOUDFLARE";
                authText.style.color = "#4ade80";
                certDetail.innerText = "Chứng chỉ cert.pem hợp lệ: " + data.cf_cert_path;
                loginBtn.innerText = "🔄 ĐĂNG NHẬP LẠI TÀI KHOẢN KHÁC";
                loginBtn.style.background = "#1e293b";
                loginBtn.style.color = "#cbd5e1";
                if (checkAuthInterval) clearInterval(checkAuthInterval);
            } else {
                authText.innerText = "❌ Chưa liên kết tài khoản Cloudflare";
                authText.style.color = "#f87171";
                certDetail.innerText = "Chưa có chứng chỉ cert.pem trên máy";
            }

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

        async function triggerCfWebLogin() {
            const authText = document.getElementById('cfAuthText');
            authText.innerText = "⏳ Đang mở trang web Cloudflare trên trình duyệt...";
            authText.style.color = "#38bdf8";

            const res = await fetch('/api/gateway/cf-start-login', { method: 'POST' });
            const data = await res.json();
            alert(data.message);

            if (checkAuthInterval) clearInterval(checkAuthInterval);
            checkAuthInterval = setInterval(async () => {
                const chk = await fetch('/api/gateway/cf-check-login');
                const chkData = await chk.json();
                if (chkData.logged_in) {
                    clearInterval(checkAuthInterval);
                    loadGatewayStatus();
                    alert("Chúc mừng! Bạn đã ủy quyền Cloudflare thành công!");
                }
            }, 2500);
        }

        async function toggleGateway() {
            if (!isCfLoggedIn) {
                alert("BẠN CHƯA ĐĂNG NHẬP CLOUDFLARE!\\nVui lòng nhấp nút 'ĐĂNG NHẬP QUA WEB CLOUDFLARE' ở Bước 1 trước!");
                return;
            }

            const domain = document.getElementById('cfDomainInput').value.trim();
            if (!domain) {
                alert("Vui lòng nhập tên miền riêng của bạn ở Bước 2 (ví dụ: voice.yourdomain.com)!");
                return;
            }

            const isRunning = document.getElementById('statusBadge').innerText.includes("ONLINE");
            const action = isRunning ? "stop" : "start";

            const res = await fetch('/api/gateway/toggle', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ action: action, custom_domain: domain })
            });
            const data = await res.json();
            if (!data.success) {
                alert(data.message);
            }
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
