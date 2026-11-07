"""
Ni-Oh Server Gateway & Portal Application
-----------------------------------------
1. DESKTOP APP = CỔNG SERVER (Server Gateway):
   - Đăng nhập tài khoản liên kết Cloudflare (1-chạm Quick Tunnel, API Token, hoặc Web OAuth)
   - Kích hoạt cổng server và XUẤT LINK WEB QUẢN LÝ THIẾT BỊ
   - Cung cấp cổng WSS và OTA cho ESP32

2. WEB PORTAL = QUẢN LÝ THIẾT BỊ:
   - Đăng nhập tài khoản Google / Zalo / Email cá nhân lưu trữ SQLite
   - Ghép đôi thiết bị bằng MÃ 6 CHỮ SỐ trên màn hình ESP32
   - Chọn Model AI phù hợp cho từng con bot (DeepSeek V3, Gemini Flash 2.0 Free, GPT-4o Mini...)
   - Cài đặt API Key cá nhân, giọng đọc tiếng Việt, câu lệnh Prompt nhân cách

3. WEBSOCKET VOICE ENGINE:
   - Nhận kết nối trực tiếp từ ESP32 tại /xiaozhi/v1/
   - Bắt tay Hello Handshake chuẩn Xiaozhi
   - Xử lý câu thoại, gọi LLM, trả về kết quả
"""

import os
import sys

# Khắc phục lỗi pythonw.exe trên Windows khi stdout/stderr là None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

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
    GATEWAY_STATE,
    api_get_gateway_status,
    api_link_quick,
    api_link_token,
    api_link_key,
    api_start_cloudflare_login,
    api_unlink_cloudflare,
    api_toggle_gateway
)
from server.web_portal import (
    HTML_XIAOZHI_PORTAL,
    api_portal_login,
    api_portal_register,
    api_portal_get_devices,
    api_portal_bind_device,
    api_portal_update_device,
    api_portal_delete_device
)
from server.voice_engine import handle_xiaozhi_websocket

logger = logging.getLogger("nioh.main_app")


def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_browser(url: str):
    try:
        if hasattr(os, "startfile"):
            os.startfile(url)
        elif sys.platform == "win32":
            os.system(f'start "" "{url}"')
        else:
            webbrowser.open(url)
    except Exception as e:
        logger.warning(f"Không thể tự mở trình duyệt: {e}")


async def handle_ota_request(request):
    """Endpoint trả về cấu hình OTA cho ESP32 khi kết nối qua Cloudflare."""
    ws_url = GATEWAY_STATE.get("wss_url", f"ws://localhost:{request.app['port']}/xiaozhi/v1/")
    return web.json_response({
        "firmware": {
            "version": os.environ.get("NIOH_FIRMWARE_VERSION", "2.5.3"),
            "url": os.environ.get("NIOH_FIRMWARE_URL", "")
        },
        "websocket": {
            "url": ws_url
        }
    })


def create_application(port: int = 8001):
    app = web.Application()
    app["port"] = port

    # ── 1. CỔNG SERVER (Desktop App) ─────────────────────────
    app.router.add_get("/", lambda req: web.Response(text=HTML_GATEWAY_APP, content_type="text/html"))
    app.router.add_get("/api/gateway/status", api_get_gateway_status)
    app.router.add_post("/api/gateway/cf-link-quick", api_link_quick)
    app.router.add_post("/api/gateway/cf-link-token", api_link_token)
    app.router.add_post("/api/gateway/cf-link-key", api_link_key)
    app.router.add_post("/api/gateway/cf-start-login", api_start_cloudflare_login)
    app.router.add_post("/api/gateway/cf-unlink", api_unlink_cloudflare)
    app.router.add_post("/api/gateway/toggle", api_toggle_gateway)

    # ── 2. WEB PORTAL QUẢN LÝ THIẾT BỊ ──────────────────────
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_XIAOZHI_PORTAL, content_type="text/html"))
    app.router.add_post("/api/portal/login", api_portal_login)
    app.router.add_post("/api/portal/register", api_portal_register)
    app.router.add_get("/api/portal/devices", api_portal_get_devices)
    app.router.add_post("/api/portal/bind", api_portal_bind_device)
    app.router.add_post("/api/portal/update-device", api_portal_update_device)
    app.router.add_post("/api/portal/delete-device", api_portal_delete_device)

    # ── 3. CỔNG OTA & WEBSOCKET VOICE CHO ESP32 ───────────────
    app.router.add_get("/xiaozhi/ota/", handle_ota_request)
    app.router.add_get("/xiaozhi/v1/", handle_xiaozhi_websocket)

    return app


async def run_server(port: int = 8001):
    if is_port_in_use(port):
        open_browser(f"http://localhost:{port}")
        return

    try:
        app = create_application(port)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        open_browser(f"http://localhost:{port}")

        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error(f"Lỗi khởi chạy máy chủ: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(run_server(8001))
    except KeyboardInterrupt:
        pass
