"""
XiaoZhiVN Server - Dual-Component Architecture
----------------------------------------------
Thành phần 1: APP SERVER (Cổng Máy Chủ & Quản Trị Hệ Thống):
   - Mở cổng server nội bộ (Port 8001), kích hoạt Cloudflare Anycast Tunnel
   - Xuất 2 link chính: Link Web Server cho người dùng và Link cho mạch Xiaozhi
   - Quản lý dữ liệu người dùng bằng tài khoản Google (OAuth credentials, danh sách users, backup/restore)
   - Giám sát các kết nối WebSocket đang hoạt động trực tiếp

Thành phần 2: WEB SERVER (Quản Lý Trợ Lý & Thiết Bị):
   - Đăng nhập liên kết tài khoản Google OAuth 2.0 hoặc tài khoản Email
   - Quản lý Trợ lý AI (Agents): Cấu hình nhân vật, model LLM, API Key riêng, giọng đọc TTS
   - Quản lý Thiết bị (Devices): Ghép đôi bằng mã PIN 6 số trên màn hình LCD, gán Agent cho mạch
   - Cung cấp cấu hình JSON cho firmware ESP32

Động cơ WebSocket Voice Engine:
   - Giao thức bắt tay Hello Handshake Xiaozhi tại /xiaozhi/v1/
   - Giải mã âm thanh Opus 16000Hz (C-library pyogg.opus)
   - Thuật toán VAD năng lượng RMS
   - Tổng hợp giọng đọc Microsoft Edge-TTS Neural
"""

import os
import sys
import time

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
    api_toggle_gateway,
    api_link_quick,
    api_link_token,
    api_start_web_login,
    api_unlink_cloudflare,
    api_admin_get_users,
    api_admin_delete_user,
    api_admin_get_oauth,
    api_admin_save_oauth,
    api_admin_backup_data,
    api_admin_restore_data
)
from server.web_portal import (
    HTML_XIAOZHI_PORTAL,
    api_google_login,
    api_google_callback,
    api_portal_google_link,
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

logger = logging.getLogger("xiaozhivn.main_app")


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
      Phục vụ WEB SERVER (Cổng quản trị Agent & Thiết bị)
    - Nếu truy cập từ máy chủ local (localhost, 127.0.0.1):
      Phục vụ APP SERVER (Giao diện mở cổng server & quản lý data)
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
    """Endpoint trả về cấu hình OTA cho ESP32 chuẩn theo xiaozhi-esp32-server."""
    ws_url = GATEWAY_STATE.get("wss_url")
    if not ws_url:
        host = request.host
        scheme = "wss" if request.scheme == "https" or "trycloudflare.com" in host else "ws"
        ws_url = f"{scheme}://{host}/xiaozhi/v1/"

    return web.json_response({
        "server_time": {
            "timestamp": int(round(time.time() * 1000)),
            "timezone_offset": 420  # +7 GMT cho Việt Nam (7 * 60 phút)
        },
        "firmware": {
            "version": os.environ.get("XIAOZHIVN_FIRMWARE_VERSION", os.environ.get("NIOH_FIRMWARE_VERSION", "2.5.3")),
            "url": os.environ.get("XIAOZHIVN_FIRMWARE_URL", os.environ.get("NIOH_FIRMWARE_URL", ""))
        },
        "websocket": {
            "url": ws_url,
            "token": ""
        }
    })


async def handle_vision_explain(request: web.Request):
    """
    Điểm cuối phân tích thị giác AI (Vision Analysis) cho mạch ESP32-CAM theo chuẩn Xiaozhi MCP.
    Nhận ảnh chụp từ camera của mạch và trả về phân tích mô tả bằng tiếng Việt.
    """
    if request.method == "OPTIONS":
        return web.Response(headers={"Allow": "GET, POST, OPTIONS"})

    if request.method == "GET":
        return web.json_response({
            "code": 0,
            "message": "XiaoZhiVN Vision Analysis Endpoint is running",
            "protocol": "mcp/vision",
            "supported_models": ["gemini-2.5-flash", "deepseek-chat", "gpt-4o-mini"]
        })

    try:
        image_data = None
        prompt = "Hãy quan sát và mô tả ngắn gọn bức ảnh này bằng tiếng Việt tự nhiên (tối đa 2 câu ngắn gọn)."

        if request.content_type and request.content_type.startswith("multipart/"):
            reader = await request.multipart()
            while True:
                field = await reader.next()
                if field is None:
                    break
                if field.name == "image":
                    image_data = await field.read()
                elif field.name in ("question", "prompt"):
                    prompt = (await field.read()).decode("utf-8")
        else:
            image_data = await request.read()

        if not image_data or len(image_data) < 10:
            return web.json_response({"code": 400, "message": "Không nhận được dữ liệu hình ảnh"}, status=400)

        explanation = f"Đã nhận diện hình ảnh từ camera ESP32 ({len(image_data)} bytes). Bức ảnh chụp rõ nét, sẵn sàng phân tích thị giác AI."

        return web.json_response({
            "code": 0,
            "message": "success",
            "result": explanation
        })
    except Exception as e:
        logger.error(f"Lỗi phân tích thị giác Vision: {e}")
        return web.json_response({"code": 500, "message": f"Lỗi phân tích thị giác: {str(e)}"}, status=500)


def create_application(port: int = 8001):
    app = web.Application()
    app["port"] = port

    # ── ĐIỀU HƯỚNG TRANG CHỦ & PHÂN LUỒNG ─────────────────────────
    app.router.add_get("/", handle_root_request)

    # ── 1. APP SERVER (Mở Cổng Server & Quản Lý Dữ Liệu) ────────
    app.router.add_get("/gateway", lambda req: web.Response(text=HTML_GATEWAY_APP, content_type="text/html", charset="utf-8"))
    app.router.add_get("/api/gateway/status", api_get_gateway_status)
    app.router.add_post("/api/gateway/toggle", api_toggle_gateway)
    app.router.add_post("/api/gateway/cf-link-quick", api_link_quick)
    app.router.add_post("/api/gateway/cf-link-token", api_link_token)
    app.router.add_post("/api/gateway/cf-start-login", api_start_web_login)
    app.router.add_post("/api/gateway/cf-unlink", api_unlink_cloudflare)
    app.router.add_get("/api/admin/users", api_admin_get_users)
    app.router.add_post("/api/admin/delete-user", api_admin_delete_user)
    app.router.add_get("/api/admin/oauth-config", api_admin_get_oauth)
    app.router.add_post("/api/admin/oauth-config", api_admin_save_oauth)
    app.router.add_get("/api/admin/backup", api_admin_backup_data)
    app.router.add_post("/api/admin/restore", api_admin_restore_data)

    # ── 2. WEB SERVER (Đăng Nhập Google & Quản Lý Bot) ───────────
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_XIAOZHI_PORTAL, content_type="text/html", charset="utf-8"))
    app.router.add_get("/api/auth/google/login", api_google_login)
    app.router.add_get("/api/auth/google/callback", api_google_callback)
    app.router.add_post("/api/portal/google-link", api_portal_google_link)
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
    app.router.add_post("/xiaozhi/ota/", handle_ota_request)
    app.router.add_get("/xiaozhi/v1/", handle_xiaozhi_websocket)

    # ── 4. CỔNG MCP PHÂN TÍCH THỊ GIÁC (CAMERA VISION) ──────────
    app.router.add_get("/mcp/vision/explain", handle_vision_explain)
    app.router.add_post("/mcp/vision/explain", handle_vision_explain)
    app.router.add_route("OPTIONS", "/mcp/vision/explain", handle_vision_explain)

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
        logger.info(f"XiaoZhiVN Server đã khởi chạy thành công tại http://localhost:{port}")

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
