"""
Ni-Oh Server Gateway & Portal Application
-----------------------------------------
1. DESKTOP APP = CỔNG SERVER (Server Gateway):
   - Đăng nhập tài khoản liên kết Cloudflare
   - Kích hoạt cổng server (WebSocket 8000 & OTA 8003)
   - Tự động XUẤT LINK WEB QUẢN LÝ THIẾT BỊ

2. WEB PORTAL = QUẢN LÝ THIẾT BỊ:
   - Đăng nhập tài khoản Google thật qua Google Identity Services
   - Đăng ký / Đăng nhập tài khoản cá nhân thật lưu vào cơ sở dữ liệu SQLite
   - Ghép đôi thiết bị bằng MÃ 6 CHỮ SỐ trên màn hình ESP32
   - Chọn Model AI phù hợp cho từng con bot (DeepSeek V3, Gemini Flash, GPT-4o-mini...)
   - Cài đặt API Key cá nhân, giọng đọc tiếng Việt, câu lệnh Prompt
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

from server.gateway_app import (
    HTML_GATEWAY_APP,
    api_get_gateway_status,
    api_start_cloudflare_login,
    api_check_cloudflare_login,
    api_toggle_gateway
)
from server.web_portal import (
    HTML_XIAOZHI_PORTAL,
    api_portal_google_auth,
    api_portal_login,
    api_portal_register,
    api_portal_get_devices,
    api_portal_bind_device,
    api_portal_update_device
)

logger = logging.getLogger("nioh.main_app")


def create_application():
    app = web.Application()

    # ── 1. CỔNG SERVER (Desktop App) ─────────────────────────
    app.router.add_get("/", lambda req: web.Response(text=HTML_GATEWAY_APP, content_type="text/html"))
    app.router.add_get("/api/gateway/status", api_get_gateway_status)
    app.router.add_post("/api/gateway/cf-start-login", api_start_cloudflare_login)
    app.router.add_get("/api/gateway/cf-check-login", api_check_cloudflare_login)
    app.router.add_post("/api/gateway/toggle", api_toggle_gateway)

    # ── 2. WEB PORTAL QUẢN LÝ THIẾT BỊ ──────────────────────
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_XIAOZHI_PORTAL, content_type="text/html"))
    app.router.add_post("/api/portal/auth-google", api_portal_google_auth)
    app.router.add_post("/api/portal/login", api_portal_login)
    app.router.add_post("/api/portal/register", api_portal_register)
    app.router.add_get("/api/portal/devices", api_portal_get_devices)
    app.router.add_post("/api/portal/bind", api_portal_bind_device)
    app.router.add_post("/api/portal/update-device", api_portal_update_device)

    return app


def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_browser(url: str):
    try:
        if sys.platform == "win32":
            os.system(f'start "" "{url}"')
        else:
            webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    port = 8001
    if is_port_in_use(port):
        print(f"[INFO] Server đã chạy sẵn tại http://localhost:{port}. Đang mở trình duyệt...")
        open_browser(f"http://localhost:{port}")
        sys.exit(0)

    app = create_application()
    print(f"\n[OK] Ni-Oh Server Gateway đang chạy tại: http://localhost:{port}")
    print(f"[OK] Web Portal Quản lý Thiết bị tại: http://localhost:{port}/portal\n")
    
    open_browser(f"http://localhost:{port}")
    web.run_app(app, host="0.0.0.0", port=port, print=None, access_log=None)
