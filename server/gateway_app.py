"""
Ni-Oh Server Gateway (Desktop App)
----------------------------------
Đóng vai trò là CỔNG SERVER:
- Bước 1: Liên kết tài khoản Cloudflare (1-chạm Quick Tunnel, API Token, hoặc Web OAuth domain)
- Bước 2: Kích hoạt hạ tầng mạng Cloudflare và XUẤT LINK WEB QUẢN LÝ THIẾT BỊ
- Bước 3: Cung cấp thông số WSS và OTA cho mạch ESP32
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
    verify_cf_token,
    verify_cf_global_key,
    activate_quick_tunnel_link,
    unlink_cloudflare,
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


# ── REST API CHO CỔNG SERVER ─────────────────────────────────

async def api_get_gateway_status(request):
    cf_status = check_login_status()
    return web.json_response({
        **GATEWAY_STATE,
        "cf_logged_in": cf_status["logged_in"],
        "cf_account": cf_status["account"],
        "cf_mode": cf_status["mode"],
        "cf_cert_path": cf_status.get("cert_path", ""),
    })


async def api_link_quick(request):
    """Liên kết tức thì bằng hạ tầng Cloudflare Quick Tunnel."""
    res = activate_quick_tunnel_link()
    return web.json_response(res)


async def api_link_token(request):
    """Xác thực và liên kết bằng Cloudflare API Token."""
    data = await request.json()
    token = data.get("token", "")
    res = verify_cf_token(token)
    return web.json_response(res)


async def api_link_key(request):
    """Xác thực và liên kết bằng Cloudflare Email + Global API Key."""
    data = await request.json()
    email = data.get("email", "")
    api_key = data.get("api_key", "")
    res = verify_cf_global_key(email, api_key)
    return web.json_response(res)


async def api_start_cloudflare_login(request):
    """Mở trang xác thực web dash.cloudflare.com."""
    res = start_web_login()
    return web.json_response(res)


async def api_unlink_cloudflare(request):
    """Hủy liên kết Cloudflare."""
    unlink_cloudflare()
    GATEWAY_STATE["server_running"] = False
    GATEWAY_STATE["portal_web_url"] = ""
    GATEWAY_STATE["wss_url"] = ""
    GATEWAY_STATE["ota_url"] = ""
    return web.json_response({"success": True, "message": "Đã hủy liên kết Cloudflare!"})


async def api_toggle_gateway(request):
    data = await request.json()
    action = data.get("action")
    domain = data.get("custom_domain", "").strip() or GATEWAY_STATE["cf_domain"]

    if action == "start":
        # Kiểm tra trạng thái liên kết
        if not is_cloudflare_logged_in():
            return web.json_response({
                "success": False,
                "message": "BẠN CHƯA LIÊN KẾT CLOUDFLARE!\nVui lòng chọn 1 trong các cách ở Bước 1 (ví dụ: '1-Chạm Siêu Tốc' hoặc 'Nhập Token') để liên kết trước."
            })

        try:
            # Khởi chạy Cloudflare Tunnel thật
            tunnel_res = await setup_tunnel(8001, domain=domain)
            
            GATEWAY_STATE["server_running"] = True
            GATEWAY_STATE["cf_domain"] = domain
            GATEWAY_STATE["portal_web_url"] = tunnel_res["portal_url"]
            GATEWAY_STATE["wss_url"] = tunnel_res["wss_url"]
            GATEWAY_STATE["ota_url"] = tunnel_res["ota_url"]

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
            --bg: #090d16; --panel: #131b2e; --panel-sub: #0c1222;
            --accent: #38bdf8; --cf: #f38020; --cf-hover: #fa6400;
            --text: #f8fafc; --muted: #94a3b8; --border: #1e293b;
            --success: #22c55e; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; max-width: 950px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .title { font-size: 22px; font-weight: 800; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 22px; }
        .card-title { font-size: 15px; font-weight: 700; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
        
        .btn { background: var(--accent); color: #090d16; border: none; padding: 12px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.2s; font-size: 14px; width: 100%; text-align: center; }
        .btn:hover { filter: brightness(1.1); }
        .btn-cf { background: var(--cf); color: white; }
        .btn-cf:hover { background: var(--cf-hover); }
        .btn-danger { background: var(--danger); color: white; }
        .btn-secondary { background: #1e293b; color: #cbd5e1; border: 1px solid #334155; }
        .btn-secondary:hover { background: #334155; }

        .input-group { margin-bottom: 12px; }
        label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
        input { width: 100%; background: #070a12; border: 1px solid var(--border); color: white; padding: 10px 12px; border-radius: 8px; font-size: 13px; outline: none; }
        input:focus { border-color: var(--accent); }

        .portal-result-box { background: #050b18; border: 2px solid #38bdf8; box-shadow: 0 0 20px rgba(56, 189, 248, 0.2); border-radius: 12px; padding: 20px; margin-top: 18px; text-align: center; }
        .portal-url { font-size: 16px; font-weight: 800; color: #38bdf8; word-break: break-all; margin: 12px 0; text-decoration: none; display: block; padding: 10px; background: rgba(56, 189, 248, 0.1); border-radius: 8px; }
        .status-pill { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: bold; }
        .status-online { background: #14532d; color: #4ade80; border: 1px solid #22c55e; }
        .status-offline { background: #450a0a; color: #f87171; border: 1px solid #ef4444; }
        
        .auth-status-card { border: 1px solid #334155; border-radius: 8px; padding: 14px; background: var(--panel-sub); margin-bottom: 16px; }
        .step-tag { display: inline-block; background: #0284c7; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-bottom: 8px; }
        
        .tab-buttons { display: flex; gap: 6px; margin-bottom: 14px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
        .tab-btn { background: none; border: none; color: var(--muted); font-size: 12px; font-weight: 600; padding: 6px 10px; cursor: pointer; border-radius: 6px; }
        .tab-btn.active { color: white; background: #1e293b; border-bottom: 2px solid var(--cf); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span>⚡ Ni-Oh Server Gateway</span>
            <span style="background: #1e293b; color: var(--cf); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid var(--cf);">CLOUDFLARE</span>
        </div>
        <div id="statusBadge" class="status-pill status-offline">CỔNG SERVER: ĐÃ TẮT</div>
    </div>

    <div class="grid">
        <!-- BƯỚC 1: Liên kết Cloudflare -->
        <div class="card">
            <span class="step-tag">BƯỚC 1</span>
            <div class="card-title">☁️ Liên Kết Tài Khoản Cloudflare</div>
            
            <div class="auth-status-card">
                <div style="font-size: 12px; color: var(--muted); margin-bottom: 4px;">Trạng thái liên kết:</div>
                <div id="cfAuthText" style="font-weight: bold; font-size: 14px; color: #f87171;">❌ Chưa liên kết Cloudflare</div>
                <div id="cfAccountDetail" style="font-size: 12px; color: var(--muted); margin-top: 4px; word-break: break-all;">Vui lòng chọn 1 cách bên dưới để kích hoạt.</div>
                <div id="unlinkBox" style="display: none; margin-top: 10px;">
                    <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 12px; width: auto;" onclick="unlinkCf()">🔄 Hủy liên kết / Đổi tài khoản</button>
                </div>
            </div>

            <!-- Các lựa chọn liên kết -->
            <div id="cfMethodsBox">
                <div class="tab-buttons">
                    <button class="tab-btn active" onclick="switchCfTab('quick')">⚡ 1-Chạm Siêu Tốc</button>
                    <button class="tab-btn" onclick="switchCfTab('token')">🔑 API Token</button>
                    <button class="tab-btn" onclick="switchCfTab('oauth')">🌐 Web OAuth</button>
                </div>

                <!-- Tab 1: Quick Tunnel 1 chạm -->
                <div id="tab-quick" class="tab-content active">
                    <p style="font-size: 13px; color: var(--muted); margin-bottom: 14px; line-height: 1.5;">
                        <strong>Khuyên dùng:</strong> Kết nối trực tiếp vào hạ tầng Anycast toàn cầu của Cloudflare. Cấp link Web Quản Lý và WSS bảo mật HTTPS miễn phí tức thì, không cần mua domain.
                    </p>
                    <button class="btn btn-cf" onclick="linkQuickTunnel()">
                        ⚡ LIÊN KẾT 1-CHẠM BẰNG CLOUDFLARE NGAY
                    </button>
                </div>

                <!-- Tab 2: Cloudflare API Token -->
                <div id="tab-token" class="tab-content">
                    <p style="font-size: 13px; color: var(--muted); margin-bottom: 12px; line-height: 1.4;">
                        Nhập API Token tài khoản Cloudflare của bạn để xác thực chính chủ:
                    </p>
                    <div class="input-group">
                        <input type="password" id="cfTokenInput" placeholder="Dán Cloudflare API Token vào đây...">
                    </div>
                    <div style="font-size: 11px; margin-bottom: 14px;">
                        <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" style="color: var(--accent); text-decoration: none;">👉 Tạo Token miễn phí trong 30 giây tại Cloudflare</a>
                    </div>
                    <button class="btn btn-cf" onclick="linkWithToken()">
                        🔐 XÁC THỰC & LIÊN KẾT TOKEN
                    </button>
                </div>

                <!-- Tab 3: Web OAuth / Domain riêng -->
                <div id="tab-oauth" class="tab-content">
                    <p style="font-size: 13px; color: var(--muted); margin-bottom: 14px; line-height: 1.5;">
                        Dành cho người dùng có sẵn tên miền (Domain) quản lý trên Cloudflare Dashboard:
                    </p>
                    <button class="btn btn-secondary" onclick="triggerCfWebLogin()">
                        🌐 MỞ TRANG XÁC THỰC DASH.CLOUDFLARE.COM
                    </button>
                </div>
            </div>
        </div>

        <!-- BƯỚC 2: Bật Cổng & Xuất Link Web -->
        <div class="card">
            <span class="step-tag" style="background: #16a34a;">BƯỚC 2</span>
            <div class="card-title">🚀 Kích Hoạt Cổng & Xuất Link Web</div>
            
            <div class="input-group">
                <label>Tên miền riêng (Tùy chọn - Bỏ trống sẽ dùng link Cloudflare tự động):</label>
                <input type="text" id="cfDomainInput" placeholder="ví dụ: voice.yourdomain.com">
            </div>

            <p style="font-size: 13px; color: var(--muted); margin-bottom: 16px; line-height: 1.5;">
                Nhấp nút bên dưới để mở luồng kết nối Cloudflare và <strong>xuất ra đường link Web Quản Lý Thiết Bị</strong> cho người dùng từ xa.
            </p>

            <button class="btn" id="gatewayToggleBtn" onclick="toggleGateway()">
                🚀 BẬT CỔNG SERVER & XUẤT LINK WEB
            </button>

            <!-- Hộp kết quả Link Web Quản Lý xuất ra -->
            <div class="portal-result-box" id="portalBox" style="display: none;">
                <span style="font-size: 13px; color: #38bdf8; font-weight: bold;">🌐 LINK WEB QUẢN LÝ THIẾT BỊ (XUẤT BẢN THÀNH CÔNG):</span>
                <a href="#" target="_blank" id="portalLink" class="portal-url">https://...</a>
                <div style="display: flex; gap: 8px; justify-content: center; margin-top: 10px;">
                    <button class="btn" style="background: #8b5cf6; color: white; width: auto; padding: 8px 16px; font-size: 13px;" onclick="copyPortalLink()">📋 Sao chép Link Web</button>
                    <button class="btn" style="background: #0284c7; color: white; width: auto; padding: 8px 16px; font-size: 13px;" onclick="openPortal()">Mở Web Quản Lý</button>
                </div>
            </div>
        </div>

        <!-- Thông số kỹ thuật cho ESP32 -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-title">📊 Thông Số Cổng Kết Nối Mạch ESP32</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; font-size: 13px;">
                <div>
                    <span style="color: var(--muted)">WebSocket Voice:</span><br>
                    <code id="wssDisplay" style="color: var(--accent); font-size: 12px; word-break: break-all;">Chưa kích hoạt</code>
                </div>
                <div>
                    <span style="color: var(--muted)">OTA Endpoint:</span><br>
                    <code id="otaDisplay" style="color: var(--accent); font-size: 12px; word-break: break-all;">Chưa kích hoạt</code>
                </div>
                <div>
                    <span style="color: var(--muted)">Tình trạng Cổng:</span><br>
                    <strong style="font-size: 14px; color: var(--success);" id="connStatus">Sẵn sàng nhận kết nối</strong>
                </div>
            </div>
        </div>
    </div>

    <script>
        let isCfLoggedIn = false;
        let checkAuthInterval = null;

        function switchCfTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
        }

        async function loadGatewayStatus() {
            try {
                const res = await fetch('/api/gateway/status');
                const data = await res.json();
                
                isCfLoggedIn = data.cf_logged_in;
                const authText = document.getElementById('cfAuthText');
                const accountDetail = document.getElementById('cfAccountDetail');
                const unlinkBox = document.getElementById('unlinkBox');
                const methodsBox = document.getElementById('cfMethodsBox');

                if (isCfLoggedIn) {
                    authText.innerText = "✅ ĐÃ LIÊN KẾT TÀI KHOẢN CLOUDFLARE";
                    authText.style.color = "#4ade80";
                    accountDetail.innerText = "Hạ tầng kết nối: " + (data.cf_account || "Cloudflare Network Active");
                    unlinkBox.style.display = "block";
                    methodsBox.style.display = "none";
                    if (checkAuthInterval) clearInterval(checkAuthInterval);
                } else {
                    authText.innerText = "❌ Chưa liên kết Cloudflare";
                    authText.style.color = "#f87171";
                    accountDetail.innerText = "Vui lòng chọn 1 cách bên dưới để kích hoạt xuất link.";
                    unlinkBox.style.display = "none";
                    methodsBox.style.display = "block";
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
                    btn.innerText = "🛑 DỪNG CỔNG SERVER";
                    btn.className = "btn btn-danger";

                    portalBox.style.display = "block";
                    portalLink.href = data.portal_web_url;
                    portalLink.innerText = data.portal_web_url;

                    document.getElementById('wssDisplay').innerText = data.wss_url;
                    document.getElementById('otaDisplay').innerText = data.ota_url;
                } else {
                    badge.innerText = "CỔNG SERVER: ĐÃ TẮT";
                    badge.className = "status-pill status-offline";
                    btn.innerText = "🚀 BẬT CỔNG SERVER & XUẤT LINK WEB";
                    btn.className = "btn";

                    portalBox.style.display = "none";
                    document.getElementById('wssDisplay').innerText = "Chưa kích hoạt";
                    document.getElementById('otaDisplay').innerText = "Chưa kích hoạt";
                }
            } catch (e) {
                console.error("Lỗi tải trạng thái:", e);
            }
        }

        async function linkQuickTunnel() {
            const res = await fetch('/api/gateway/cf-link-quick', { method: 'POST' });
            const data = await res.json();
            alert(data.message);
            loadGatewayStatus();
        }

        async function linkWithToken() {
            const token = document.getElementById('cfTokenInput').value.trim();
            if (!token) {
                alert("Vui lòng nhập Cloudflare API Token!");
                return;
            }
            const res = await fetch('/api/gateway/cf-link-token', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ token: token })
            });
            const data = await res.json();
            alert(data.message);
            if (data.success) {
                loadGatewayStatus();
            }
        }

        async function triggerCfWebLogin() {
            const res = await fetch('/api/gateway/cf-start-login', { method: 'POST' });
            const data = await res.json();
            alert(data.message);

            if (checkAuthInterval) clearInterval(checkAuthInterval);
            checkAuthInterval = setInterval(async () => {
                const chk = await fetch('/api/gateway/status');
                const chkData = await chk.json();
                if (chkData.cf_logged_in) {
                    clearInterval(checkAuthInterval);
                    loadGatewayStatus();
                    alert("Ủy quyền tài khoản Cloudflare thành công!");
                }
            }, 3000);
        }

        async function unlinkCf() {
            if (!confirm("Bạn có chắc chắn muốn hủy liên kết tài khoản Cloudflare này?")) return;
            const res = await fetch('/api/gateway/cf-unlink', { method: 'POST' });
            const data = await res.json();
            alert(data.message);
            loadGatewayStatus();
        }

        async function toggleGateway() {
            if (!isCfLoggedIn) {
                alert("BẠN CHƯA LIÊN KẾT CLOUDFLARE!\\nVui lòng chọn 1 trong các cách ở Bước 1 (ví dụ: '1-Chạm Siêu Tốc') để liên kết trước!");
                return;
            }

            const isRunning = document.getElementById('statusBadge').innerText.includes("ONLINE");
            const action = isRunning ? "stop" : "start";
            const domain = document.getElementById('cfDomainInput').value.trim();

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

        function copyPortalLink() {
            const url = document.getElementById('portalLink').innerText;
            navigator.clipboard.writeText(url);
            alert("Đã sao chép link Web Quản Lý Thiết Bị vào bộ nhớ đệm!");
        }

        function openPortal() {
            window.open(document.getElementById('portalLink').href, '_blank');
        }

        loadGatewayStatus();
    </script>
</body>
</html>
"""
