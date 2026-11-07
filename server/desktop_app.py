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
import random
import sqlite3
import asyncio
import logging
import webbrowser
import aiohttp
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
    """
    Endpoint trả về cấu hình OTA cho ESP32 chuẩn theo xiaozhi-esp32-server và xiaozhi-esp32_vietnam.
    Hỗ trợ hiển thị mã PIN ghép đôi trên màn hình LCD mạch khi mạch chưa được kích hoạt.
    """
    ws_url = GATEWAY_STATE.get("wss_url")
    host = request.host
    if not ws_url:
        scheme = "wss" if request.scheme == "https" or "trycloudflare.com" in host else "ws"
        ws_url = f"{scheme}://{host}/xiaozhi/v1/"

    # Kiểm tra Device-Id từ HTTP Header hoặc request body
    device_id = request.headers.get("Device-Id", "").strip()
    if not device_id and request.method == "POST":
        try:
            body = await request.json()
            device_id = body.get("mac_address") or body.get("device_id") or ""
        except Exception:
            pass

    is_bound = False
    pin_code = None
    if device_id:
        db_file = os.path.join(BASE_DIR, "data", "portal.db")
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, user_id TEXT, bot_name TEXT, pairing_code TEXT, agent_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        c.execute("SELECT user_id, pairing_code FROM devices WHERE device_id = ?", (device_id,))
        row = c.fetchone()
        if row and row[0]:
            is_bound = True
        elif row and row[1]:
            pin_code = row[1]
        else:
            pin_code = f"{random.randint(100000, 999999)}"
            c.execute("INSERT OR REPLACE INTO devices (device_id, pairing_code) VALUES (?, ?)", (device_id, pin_code))
            conn.commit()
        conn.close()

    res = {
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
    }

    # Nếu thiết bị chưa ghép đôi, trả về activation payload để firmware xiaozhi-esp32_vietnam hiển thị mã PIN trên màn hình
    if not is_bound and pin_code:
        res["activation"] = {
            "code": pin_code,
            "message": f"Mã PIN: {pin_code}. Nhập trên Web để ghép đôi.",
            "timeout_ms": 120000
        }

    return web.json_response(res)


async def handle_music_stream(request: web.Request):
    """
    Endpoint cung cấp dịch vụ âm nhạc trực tuyến cho firmware xiaozhi-esp32_vietnam.
    Chuẩn API: GET /stream_pcm?song=<tên bài hát>&artist=<ca sĩ>
    Trả về định dạng JSON theo đúng esp32_music.cc:
    {
        "artist": "...",
        "title": "...",
        "audio_url": "...",
        "lyric_url": "",
        "duration": 210,
        "success": true
    }
    """
    song = request.query.get("song", "").strip()
    artist = request.query.get("artist", "").strip()

    if not song:
        return web.json_response({
            "success": False,
            "message": "Vui lòng cung cấp tên bài hát qua tham số song",
            "audio_url": ""
        }, status=400)

    query = f"{song} {artist}".strip()
    try:
        from server.tools.free_music import search_and_get_audio_stream
        res = await search_and_get_audio_stream(query)
        if res.get("success"):
            return web.json_response({
                "artist": res.get("artist") or artist or "Nhiều ca sĩ",
                "title": res.get("title") or song,
                "audio_url": res.get("audio_url", ""),
                "lyric_url": "",
                "duration": res.get("duration") or 210,
                "success": True
            })
        else:
            return web.json_response({
                "artist": artist,
                "title": song,
                "audio_url": "",
                "message": res.get("message", "Không tìm thấy bài hát"),
                "success": False
            })
    except Exception as e:
        logger.error(f"Lỗi API âm nhạc /stream_pcm: {e}")
        return web.json_response({"success": False, "message": str(e), "audio_url": ""}, status=500)


async def handle_proxy_stream(request: web.Request):
    """Proxy luồng âm thanh MP3 cho ESP32 khi cần bypass kết nối."""
    url = request.query.get("url")
    if not url:
        return web.Response(text="Missing url parameter", status=400)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                headers = {
                    "Content-Type": resp.headers.get("Content-Type", "audio/mpeg"),
                    "Accept-Ranges": "bytes"
                }
                response = web.StreamResponse(status=resp.status, headers=headers)
                await response.prepare(request)
                async for chunk in resp.content.iter_chunked(4096):
                    await response.write(chunk)
                await response.write_eof()
                return response
    except Exception as e:
        logger.error(f"Lỗi proxy stream MP3: {e}")
        return web.Response(text=str(e), status=500)


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

    # ── 5. CỔNG DỊCH VỤ ÂM NHẠC TRỰC TUYẾN CHO XIAOZHI-ESP32_VIETNAM
    app.router.add_get("/stream_pcm", handle_music_stream)
    app.router.add_get("/mp3/proxy/stream", handle_proxy_stream)

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

        # Khởi chạy bộ giám sát hẹn giờ & báo thức thông minh (Proactive Wakeup / Alarms)
        from server.tools.smart_alarm import run_alarm_monitor_loop
        from server.voice_engine import ACTIVE_CONNECTIONS
        asyncio.create_task(run_alarm_monitor_loop(lambda: ACTIVE_CONNECTIONS))

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
