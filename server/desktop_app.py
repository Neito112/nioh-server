"""
Ni-Oh Server - Dual-Component Architecture
------------------------------------------
Thành phần 1: APP SERVER (Desktop Control Center):
   - Mở giao diện setup những gì server sẽ cung cấp (Mô hình AI, Server API Key, Công cụ)
   - Kích hoạt Cloudflare Tunnel và XUẤT 2 ĐƯỜNG LINK SERVER:
     + Link Web Server: Dành cho người dùng/bạn bè truy cập từ xa để quản lý Agent (giống xiaozhi.me)
     + Link WebSocket & OTA: Dành cho các mạch ESP32 Xiaozhi trỏ đến trực tiếp
   - Bảng giám sát thời gian thực các mạch Xiaozhi đang online

Thành phần 2: WEB SERVER (Agent & Device Management Portal — xiaozhi.me):
   - Quản lý Trợ lý AI (Agent): Tạo, sửa nhân vật, chọn Model AI, giọng TTS tiếng Việt, API Key riêng
   - Quản lý Thiết bị (Devices): Ghép đôi mạch bằng MÃ PIN 6 SỐ trên màn hình LCD, gán mạch vào Agent
   - Hướng dẫn cấu hình kết nối firmware

Động cơ WebSocket Voice Engine:
   - Giao thức bắt tay Hello Handshake Xiaozhi chuẩn tại /xiaozhi/v1/
   - Giải mã âm thanh Opus 16000Hz (C-library pyogg.opus)
   - Tích hợp công cụ: Thời tiết (Open-Meteo), Tìm kiếm (DuckDuckGo), Điều khiển PC
   - Giọng đọc Microsoft Edge-TTS Neural tiếng Việt
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
    api_save_server_setup,
    api_toggle_gateway
)
from server.web_portal import (
    HTML_XIAOZHI_PORTAL,
    api_portal_login,
    api_portal_register,
    api_portal_get_agents,
    api_portal_save_agent,
    api_portal_delete_agent,
    api_portal_get_devices,
    api_portal_bind_device,
    api_portal_assign_agent,
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


async def handle_root_request(request):
    """
    Tự động phân luồng URL thông minh:
    - Nếu truy cập từ bên ngoài qua Cloudflare (trycloudflare.com hoặc tên miền riêng):
      Phục vụ WEB SERVER (Cổng quản lý Agent & Thiết bị xiaozhi.me)
    - Nếu truy cập từ máy chủ local (localhost, 127.0.0.1):
      Phục vụ APP SERVER (Giao diện điều khiển & thiết lập máy chủ)
    """
    host = request.host.split(":")[0].lower()
    is_remote = (
        "trycloudflare.com" in host
        or (host != "localhost" and host != "127.0.0.1" and not host.startswith("192.168.") and not host.startswith("10.") and not host.startswith("172."))
    )
    if is_remote:
        return web.Response(text=HTML_XIAOZHI_PORTAL, content_type="text/html", charset="utf-8")
    return web.Response(text=HTML_GATEWAY_APP, content_type="text/html", charset="utf-8")


async def handle_ota_request(request):
    """Endpoint trả về cấu hình OTA cho ESP32 khi kết nối qua Cloudflare."""
    ws_url = GATEWAY_STATE.get("wss_url")
    if not ws_url:
        host = request.host
        scheme = "wss" if request.scheme == "https" or "trycloudflare.com" in host else "ws"
        ws_url = f"{scheme}://{host}/xiaozhi/v1/"

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

    # ── ĐIỀU HƯỚNG TRANG CHỦ & PHÂN LUỒNG ─────────────────────────
    app.router.add_get("/", handle_root_request)

    # ── 1. APP SERVER (Desktop Setup & Control Center) ───────────
    app.router.add_get("/gateway", lambda req: web.Response(text=HTML_GATEWAY_APP, content_type="text/html", charset="utf-8"))
    app.router.add_get("/api/gateway/status", api_get_gateway_status)
    app.router.add_post("/api/gateway/save-setup", api_save_server_setup)
    app.router.add_post("/api/gateway/toggle", api_toggle_gateway)

    # ── 2. WEB SERVER (Agent & Device Management Portal — xiaozhi.me)
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_XIAOZHI_PORTAL, content_type="text/html", charset="utf-8"))
    app.router.add_post("/api/portal/register", api_portal_register)
    app.router.add_post("/api/portal/login", api_portal_login)
    app.router.add_get("/api/portal/agents", api_portal_get_agents)
    app.router.add_post("/api/portal/agents", api_portal_save_agent)
    app.router.add_post("/api/portal/delete-agent", api_portal_delete_agent)
    app.router.add_get("/api/portal/devices", api_portal_get_devices)
    app.router.add_post("/api/portal/bind", api_portal_bind_device)
    app.router.add_post("/api/portal/assign-agent", api_portal_assign_agent)
    app.router.add_post("/api/portal/delete-device", api_portal_delete_device)

    # ── 3. CỔNG OTA & WEBSOCKET VOICE CHO ESP32 ─────────────────
    app.router.add_get("/xiaozhi/ota/", handle_ota_request)
    app.router.add_get("/xiaozhi/v1/", handle_xiaozhi_websocket)

    return app


async def run_server(port: int = 8001):
    if is_port_in_use(port):
        logger.info(f"Cổng {port} đang mở, mở trình duyệt vào ứng dụng...")
        open_browser(f"http://localhost:{port}")
        return

    try:
        app = create_application(port)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Ni-Oh Server đã khởi chạy thành công tại http://localhost:{port}")

        open_browser(f"http://localhost:{port}")

        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error(f"Lỗi khởi chạy máy chủ: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(run_server(8001))
    except KeyboardInterrupt:
        logger.info("Máy chủ đã dừng.")
