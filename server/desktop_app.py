"""
Ni-Oh Server Gateway & Portal Application
-----------------------------------------
1. DESKTOP APP = CỔNG SERVER (Server Gateway):
   - Đăng nhập tài khoản liên kết Cloudflare
   - Kích hoạt cổng server (WebSocket 8000 & OTA 8003)
   - Tự động XUẤT LINK WEB QUẢN LÝ THIẾT BỊ

2. WEB PORTAL = QUẢN LÝ THIẾT BỊ (Y hệt xiaozhi.me):
   - Người dùng đăng nhập tài khoản cá nhân qua GOOGLE hoặc ZALO
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
    api_save_cloudflare_auth,
    api_toggle_gateway
)
from server.web_portal import (
    HTML_XIAOZHI_PORTAL,
    api_portal_auth,
    api_portal_get_devices,
    api_portal_bind_device,
    api_portal_update_device
)

logger = logging.getLogger("nioh.main_app")


def create_application():
    app = web.Application()

    # ── 1. CỔNG SERVER (Desktop App Dashboard 1) ─────────────
    app.router.add_get("/", lambda req: web.Response(text=HTML_GATEWAY_APP, content_type="text/html"))
    app.router.add_get("/api/gateway/status", api_get_gateway_status)
    app.router.add_post("/api/gateway/cf-auth", api_save_cloudflare_auth)
    app.router.add_post("/api/gateway/toggle", api_toggle_gateway)

    # ── 2. WEB PORTAL QUẢN LÝ THIẾT BỊ (Dashboard 2 - xiaozhi.me Clone) ──
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_XIAOZHI_PORTAL, content_type="text/html"))
    app.router.add_post("/api/portal/auth", api_portal_auth)
    app.router.add_get("/api/portal/devices", api_portal_get_devices)
    app.router.add_post("/api/portal/bind", api_portal_bind_device)
    app.router.add_post("/api/portal/update-device", api_portal_update_device)

    return app


async def run_server(port: int = 8001):
    app = create_application()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"\n[OK] Ni-Oh Server Gateway đang chạy tại: http://localhost:{port}")
    print(f"[OK] Web Portal Quản lý Thiết bị (xiaozhi.me style) tại: http://localhost:{port}/portal\n")
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_server(8001))
    loop.run_forever()
