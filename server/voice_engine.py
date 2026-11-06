"""
Xiaozhi WebSocket Voice Engine for Ni-Oh Server
------------------------------------------------
Xử lý giao thức WebSocket âm thanh cho mạch ESP32 Xiaozhi/Ni-Oh:
- Handshake 'hello' chuẩn giao thức Xiaozhi v1/v2
- Nhận diện thiết bị và cập nhật trạng thái 'online' vào database SQLite
- Tự động điều phối hội thoại tới LLM (DeepSeek, Gemini, OpenRouter)
- Tích hợp công cụ: Thời tiết (Open-Meteo), Tìm kiếm (DuckDuckGo), Điều khiển PC, Nhạc
- Phản hồi TTS văn bản/âm thanh về màn hình và loa của mạch ESP32
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging
import aiohttp
from aiohttp import web

logger = logging.getLogger("nioh.voice_engine")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")

# Import các công cụ miễn phí
from server.tools.free_weather import get_weather
from server.tools.free_search import search_web
from server.tools.pc_control import execute_pc_command


def get_device_config(device_id: str) -> dict:
    """Lấy cấu hình riêng của thiết bị từ database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT model, api_key, voice, prompt FROM devices WHERE device_id = ?", (device_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "model": row[0] or "deepseek/deepseek-chat",
            "api_key": row[1] or os.environ.get("NIOH_API_KEY", ""),
            "voice": row[2] or "vi-VN-HoaiMyNeural",
            "prompt": row[3] or "Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính và thân thiện.",
        }
    return {
        "model": os.environ.get("NIOH_MODEL", "deepseek/deepseek-chat"),
        "api_key": os.environ.get("NIOH_API_KEY", ""),
        "voice": "vi-VN-HoaiMyNeural",
        "prompt": "Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính và thân thiện.",
    }


def update_device_status(device_id: str, status: str = "online"):
    """Cập nhật trạng thái kết nối của mạch ESP32."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE devices SET status = ? WHERE device_id = ?", (status, device_id))
    conn.commit()
    conn.close()


async def call_llm(user_text: str, cfg: dict) -> str:
    """Gọi LLM (DeepSeek / Gemini / OpenRouter) để sinh phản hồi."""
    api_key = cfg.get("api_key") or os.environ.get("NIOH_API_KEY", "")
    model = cfg.get("model", "deepseek/deepseek-chat")
    system_prompt = cfg.get("prompt", "Bạn là Ni-Oh, trợ lý giọng nói tiếng Việt thân thiện.")

    # 1. Kiểm tra nếu câu lệnh là công cụ (Tool calling)
    lower = user_text.lower()
    if any(k in lower for k in ["thời tiết", "mưa không", "nhiệt độ", "bao nhiêu độ"]):
        # Lấy thời tiết miễn phí qua Open-Meteo
        loc = "Hà Nội"
        for c in ["hà nội", "hồ chí minh", "sài gòn", "đà nẵng", "hải phòng", "cần thơ", "đà lạt", "nha trang"]:
            if c in lower:
                loc = c.title()
                break
        w = await get_weather(loc)
        if w.get("success"):
            return f"Thời tiết tại {w['location']} hiện tại là {w['description']}, nhiệt độ khoảng {w['temperature']} độ C, độ ẩm {w['humidity']}%."

    if any(k in lower for k in ["tắt máy tính", "khóa máy", "chụp màn hình", "tăng âm lượng", "giảm âm lượng"]):
        pc_res = execute_pc_command(lower)
        if pc_res.get("success"):
            return pc_res.get("message", "Đã thực hiện lệnh trên máy tính của bạn!")

    # 2. Gọi OpenRouter / OpenAI API
    base_url = os.environ.get("NIOH_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    if not api_key:
        return "Xin chào! Bạn chưa nhập API Key cho bot trong Web Quản Lý Thiết Bị, vui lòng vào web để cài đặt nhé!"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nioh-server.local",
        "X-Title": "Ni-Oh Voice Assistant"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt + " Hãy trả lời ngắn gọn, tự nhiên, thích hợp để đọc thành giọng nói (dưới 3 câu)."},
            {"role": "user", "content": user_text}
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=15) as resp:
                data = await resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
                else:
                    err = data.get("error", {}).get("message", "Lỗi phản hồi từ AI")
                    return f"Dạ, server AI thông báo: {err}"
    except Exception as e:
        logger.error(f"Lỗi gọi LLM: {e}")
        return f"Dạ, tạm thời không kết nối được tới mô hình AI: {str(e)}"


async def handle_xiaozhi_websocket(request: web.Request) -> web.WebSocketResponse:
    """Xử lý kết nối WebSocket chuẩn từ mạch ESP32 Xiaozhi/Ni-Oh."""
    ws = web.WebSocketResponse(protocols=["xiaozhi"])
    await ws.prepare(request)

    device_id = request.headers.get("Device-Id", "ESP32-DEV")
    logger.info(f"ESP32 kết nối WebSocket: {device_id} (Client IP: {request.remote})")
    update_device_status(device_id, "online")

    cfg = get_device_config(device_id)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                msg_type = data.get("type", "")

                # 1. Bắt tay Hello Handshake
                if msg_type == "hello":
                    reply = {
                        "type": "hello",
                        "transport": "websocket",
                        "version": 1,
                        "session_id": f"sess_{os.urandom(4).hex()}",
                        "audio_params": {
                            "format": "opus",
                            "sample_rate": 16000,
                            "channels": 1,
                            "frame_duration": 60
                        }
                    }
                    await ws.send_json(reply)

                # 2. Bắt đầu lắng nghe
                elif msg_type == "listen":
                    state = data.get("state", "")
                    text = data.get("text", "")
                    if text:
                        # Nhận được text từ client/STT
                        ai_reply = await call_llm(text, cfg)
                        await ws.send_json({"type": "tts", "state": "start"})
                        await ws.send_json({"type": "tts", "state": "sentence_start", "text": ai_reply})
                        await ws.send_json({"type": "tts", "state": "stop"})

                # 3. Tin nhắn chat văn bản trực tiếp
                elif msg_type == "chat" or msg_type == "stt":
                    user_msg = data.get("text", "")
                    if user_msg:
                        ai_reply = await call_llm(user_msg, cfg)
                        await ws.send_json({"type": "tts", "state": "start"})
                        await ws.send_json({"type": "tts", "state": "sentence_start", "text": ai_reply})
                        await ws.send_json({"type": "tts", "state": "stop"})

                # 4. Yêu cầu hủy
                elif msg_type == "abort":
                    await ws.send_json({"type": "tts", "state": "stop"})

            elif msg.type == web.WSMsgType.BINARY:
                # Dữ liệu âm thanh thô/opus từ ESP32
                pass

            elif msg.type == web.WSMsgType.ERROR:
                logger.warning(f"Lỗi WebSocket ESP32: {ws.exception()}")

    finally:
        logger.info(f"ESP32 ngắt kết nối WebSocket: {device_id}")
        update_device_status(device_id, "offline")

    return ws
