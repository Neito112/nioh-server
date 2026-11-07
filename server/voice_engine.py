"""
Ni-Oh Voice Engine (Production Core)
------------------------------------
Hạt nhân xử lý âm thanh thời gian thực cho chuẩn giao thức Xiaozhi:
- Handshake 'hello' (Protocol version 1 & 2)
- Quản lý phiên kết nối WebSocket thực tế (Live Client Session Registry)
- Giải mã nhị phân Opus 16000Hz qua thư viện C libopus (pyogg.opus)
- Thuật toán VAD năng lượng RMS để phát hiện giọng nói
- Tích hợp công cụ: Thời tiết (Open-Meteo), Tìm kiếm web (DuckDuckGo), Lệnh hệ thống (PC Control)
- Kết nối LLM linh hoạt qua chuẩn OpenAI-compatible (DeepSeek, OpenRouter, OpenAI, Gemini, Ollama)
- Tổng hợp giọng đọc Neural TTS tiếng Việt chất lượng cao (Microsoft Edge-TTS)
"""

import os
import sys
import json
import math
import struct
import io
import time
import asyncio
import sqlite3
import logging
import aiohttp
from aiohttp import web

logger = logging.getLogger("nioh.voice_engine")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")

# Import các công cụ hệ thống
from server.tools.free_weather import get_weather
from server.tools.free_search import search_web
from server.tools.pc_control import execute_pc_command

# Thử nạp thư viện C libopus qua pyogg
HAS_OPUS = False
try:
    import ctypes
    import pyogg.opus as opus
    HAS_OPUS = True
    logger.info("Thư viện libopus C (pyogg) đã sẵn sàng để giải mã âm thanh ESP32!")
except Exception as e:
    logger.warning(f"Chưa nạp được libopus C: {e}")


# ── BỘ ĐẾM VÀ GIÁM SÁT KẾT NỐI REAL-TIME (LIVE SESSION REGISTRY) ──
# Lưu trữ chính xác các client WebSocket đang kết nối thực tế trong bộ nhớ
ACTIVE_CONNECTIONS: dict[str, dict] = {}


def get_live_connections() -> dict:
    """Trả về danh sách và số lượng kết nối WebSocket thời gian thực."""
    now = time.time()
    conns = []
    for dev_id, info in list(ACTIVE_CONNECTIONS.items()):
        conns.append({
            "device_id": dev_id,
            "remote_ip": info.get("remote_ip", ""),
            "connected_at": info.get("connected_at", ""),
            "duration_seconds": int(now - info.get("connected_timestamp", now)),
            "rx_packets": info.get("rx_packets", 0),
            "tx_packets": info.get("tx_packets", 0),
            "audio_frames": info.get("audio_frames", 0),
            "status": info.get("status", "connected")
        })
    return {
        "active_count": len(conns),
        "connections": conns
    }


# ── CẤU HÌNH THIẾT BỊ VÀ SERVER RUNTIME ────────────────────────────

def get_server_runtime_config() -> dict:
    """Lấy cấu hình máy chủ từ database server_config."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("SELECT key, value FROM server_config")
    rows = dict(c.fetchall())
    conn.close()

    return {
        "provider": rows.get("provider", "deepseek"),
        "base_url": rows.get("base_url", os.environ.get("NIOH_LLM_BASE_URL", "https://api.deepseek.com")),
        "api_key": rows.get("api_key", os.environ.get("NIOH_API_KEY", "")),
        "model": rows.get("model", os.environ.get("NIOH_MODEL", "deepseek-chat")),
        "voice": rows.get("voice", "vi-VN-HoaiMyNeural"),
        "speech_rate": rows.get("speech_rate", "+0%"),
        "enable_weather": rows.get("enable_weather", "1") == "1",
        "enable_search": rows.get("enable_search", "1") == "1",
        "enable_pc_control": rows.get("enable_pc_control", "1") == "1",
    }


def get_device_config(device_id: str) -> dict:
    """
    Lấy cấu hình riêng cho thiết bị từ Agent được gán trong database.
    Nếu chưa có Agent riêng, kế thừa cấu hình mặc định từ máy chủ.
    """
    server_cfg = get_server_runtime_config()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT a.model, a.api_key, a.voice, a.prompt, d.name
        FROM devices d
        JOIN agents a ON d.agent_id = a.id
        WHERE d.device_id = ?
    """, (device_id,))
    row = c.fetchone()
    conn.close()

    if row:
        return {
            "model": row[0] or server_cfg["model"],
            "api_key": row[1] or server_cfg["api_key"],
            "voice": row[2] or server_cfg["voice"],
            "prompt": row[3] or "Bạn là trợ lý AI thông minh, giao tiếp tiếng Việt tự nhiên và súc tích.",
            "device_name": row[4] or device_id,
            "base_url": server_cfg["base_url"],
            "speech_rate": server_cfg["speech_rate"]
        }

    return {
        "model": server_cfg["model"],
        "api_key": server_cfg["api_key"],
        "voice": server_cfg["voice"],
        "prompt": "Bạn là trợ lý AI thông minh, giao tiếp tiếng Việt tự nhiên và súc tích.",
        "device_name": device_id,
        "base_url": server_cfg["base_url"],
        "speech_rate": server_cfg["speech_rate"]
    }


def update_device_status(device_id: str, status: str = "online"):
    """Cập nhật trạng thái thiết bị trong SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE devices SET status = ? WHERE device_id = ?", (status, device_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Lỗi cập nhật trạng thái thiết bị {device_id}: {e}")


# ── BỘ GIẢI MÃ & NĂNG LƯỢNG ÂM THANH OPUS / VAD ────────────────────

class AudioPipeline:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.decoder = None
        if HAS_OPUS:
            err = ctypes.c_int()
            self.decoder = opus.opus_decoder_create(sample_rate, channels, ctypes.byref(err))

    def decode_frame(self, opus_data: bytes) -> bytes:
        if not self.decoder or not opus_data:
            return b""
        max_samples = 960  # 60ms tại 16kHz
        pcm_buf = (opus.opus_int16 * (max_samples * self.channels))()
        samples = opus.opus_decode(
            self.decoder,
            opus_data,
            len(opus_data),
            pcm_buf,
            max_samples,
            0
        )
        if samples > 0:
            return bytes(pcm_buf)[:samples * 2 * self.channels]
        return b""

    @staticmethod
    def calculate_energy(pcm_bytes: bytes) -> float:
        if len(pcm_bytes) < 2:
            return 0.0
        count = len(pcm_bytes) // 2
        shorts = struct.unpack(f"<{count}h", pcm_bytes)
        sum_sq = sum(s * s for s in shorts)
        return math.sqrt(sum_sq / count) if count > 0 else 0.0

    def close(self):
        if self.decoder and HAS_OPUS:
            opus.opus_decoder_destroy(self.decoder)
            self.decoder = None


# ── TỔNG HỢP GIỌNG ĐỌC TTS (EDGE-TTS NEURAL) ─────────────────────────

async def generate_speech_audio(text: str, voice: str = "vi-VN-HoaiMyNeural", rate: str = "+0%") -> bytes:
    """Tạo âm thanh MP3 từ văn bản bằng Microsoft Edge-TTS Neural."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        audio_stream = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream += chunk["data"]
        if audio_stream:
            return audio_stream
    except Exception as e:
        logger.warning(f"Edge-TTS không phản hồi ({e}), sử dụng gTTS...")

    try:
        from gtts import gTTS
        tts = gTTS(text, lang="vi")
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Lỗi tổng hợp giọng nói gTTS: {e}")
        return b""


# ── XỬ LÝ TRUY VẤN LLM & CÔNG CỤ (TOOLS) ────────────────────────────

async def process_llm_query(user_text: str, cfg: dict) -> str:
    """Xử lý câu thoại người dùng qua LLM hoặc công cụ chuyên trách."""
    user_text = user_text.strip()
    if not user_text:
        return "Tôi đang lắng nghe bạn đây."

    lower = user_text.lower()
    server_cfg = get_server_runtime_config()

    # 1. Công cụ Thời Tiết (Open-Meteo)
    if server_cfg.get("enable_weather") and any(k in lower for k in ["thời tiết", "nhiệt độ", "mưa không", "trời hôm nay"]):
        loc = "Hà Nội"
        for city in ["hà nội", "hồ chí minh", "sài gòn", "đà nẵng", "hải phòng", "cần thơ", "đà lạt", "nha trang", "huế"]:
            if city in lower:
                loc = city.title()
                break
        w = await get_weather(loc)
        if w.get("success"):
            return w.get("summary") or f"Thời tiết tại {w['location']} hiện tại là {w.get('condition')}, nhiệt độ khoảng {w.get('temperature')} độ C, độ ẩm {w.get('humidity')}%."

    # 2. Công cụ Điều Khiển PC
    if server_cfg.get("enable_pc_control") and any(k in lower for k in ["tắt máy tính", "khóa máy", "chụp màn hình", "tăng âm lượng", "giảm âm lượng"]):
        res = execute_pc_command(lower)
        if res.get("success"):
            return res.get("message", "Đã thực hiện lệnh trên máy tính.")

    # 3. Công cụ Tìm Kiếm Web
    if server_cfg.get("enable_search") and (lower.startswith("tìm kiếm") or lower.startswith("tra cứu") or "giá vàng" in lower):
        q = lower.replace("tìm kiếm", "").replace("tra cứu", "").strip() or user_text
        s_res = await search_web(q)
        if s_res.get("success"):
            return f"Thông tin tìm được: {s_res.get('summary', '')}"

    # 4. Gọi LLM
    api_key = cfg.get("api_key") or os.environ.get("NIOH_API_KEY", "")
    model = cfg.get("model", "deepseek-chat")
    base_url = cfg.get("base_url", "https://api.deepseek.com").rstrip("/")
    system_prompt = cfg.get("prompt", "Bạn là trợ lý AI thông minh, hỗ trợ bằng tiếng Việt tự nhiên và súc tích.")

    if not api_key:
        return f"Đã nhận lệnh: '{user_text}'. Vui lòng cấu hình API Key trong trang quản trị máy chủ để kích hoạt AI."

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nioh.local",
        "X-Title": "Ni-Oh Voice Server"
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt + " Hãy trả lời súc tích, tự nhiên, thích hợp để đọc thành giọng nói (tối đa 2 đến 3 câu ngắn)."
            },
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.7,
        "max_tokens": 512
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                data = await resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    err = data.get("error", {}).get("message", "Không nhận được phản hồi từ AI.")
                    return f"Lỗi từ dịch vụ AI: {err}"
    except Exception as e:
        logger.error(f"Lỗi gọi LLM API ({url}): {e}")
        return f"Kết nối AI gặp gián đoạn: {str(e)}"


# ── XỬ LÝ WEBSOCKET KẾT NỐI XIAOZHI ──────────────────────────────────

async def handle_xiaozhi_websocket(request: web.Request) -> web.WebSocketResponse:
    """Xử lý kết nối WebSocket từ mạch ESP32 chuẩn giao thức Xiaozhi."""
    ws = web.WebSocketResponse(protocols=["xiaozhi"])
    await ws.prepare(request)

    device_id = request.headers.get("Device-Id", f"ESP32-{request.remote.replace('.', '')[-6:]}")
    logger.info(f"Kết nối WebSocket mới: {device_id} từ {request.remote}")

    # Đăng ký vào bảng giám sát kết nối thực tế
    ACTIVE_CONNECTIONS[device_id] = {
        "device_id": device_id,
        "remote_ip": request.remote,
        "connected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "connected_timestamp": time.time(),
        "rx_packets": 0,
        "tx_packets": 0,
        "audio_frames": 0,
        "status": "connected"
    }
    update_device_status(device_id, "online")

    cfg = get_device_config(device_id)
    pipeline = AudioPipeline()
    pcm_audio_buffer = bytearray()
    last_speech_time = 0
    is_speaking = False

    try:
        async for msg in ws:
            if device_id in ACTIVE_CONNECTIONS:
                ACTIVE_CONNECTIONS[device_id]["rx_packets"] += 1

            # 1. Gói tin JSON Text
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                msg_type = data.get("type", "")

                # Handshake Hello
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
                    if device_id in ACTIVE_CONNECTIONS:
                        ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 1
                    logger.info(f"Hoàn tất bắt tay Hello với {device_id}")

                # Nhận Text / Chat / STT
                elif msg_type in ("listen", "chat", "stt"):
                    text = data.get("text", "")
                    if text:
                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["status"] = "processing"
                        ai_reply = await process_llm_query(text, cfg)
                        await ws.send_json({"type": "tts", "state": "start"})
                        await ws.send_json({"type": "tts", "state": "sentence_start", "text": ai_reply})
                        
                        audio_data = await generate_speech_audio(ai_reply, cfg.get("voice"), cfg.get("speech_rate", "+0%"))
                        if audio_data:
                            await ws.send_bytes(audio_data)
                        await ws.send_json({"type": "tts", "state": "stop"})
                        
                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 3
                            ACTIVE_CONNECTIONS[device_id]["status"] = "connected"

                elif msg_type == "abort":
                    await ws.send_json({"type": "tts", "state": "stop"})
                    if device_id in ACTIVE_CONNECTIONS:
                        ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 1

            # 2. Gói tin Âm thanh Nhị phân (Binary Opus Frame)
            elif msg.type == web.WSMsgType.BINARY:
                if device_id in ACTIVE_CONNECTIONS:
                    ACTIVE_CONNECTIONS[device_id]["audio_frames"] += 1
                
                opus_chunk = msg.data
                pcm_chunk = pipeline.decode_frame(opus_chunk)
                if pcm_chunk:
                    energy = AudioPipeline.calculate_energy(pcm_chunk)
                    now = time.time()
                    if energy > 400:
                        is_speaking = True
                        last_speech_time = now
                        pcm_audio_buffer.extend(pcm_chunk)
                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["status"] = "speaking"
                    elif is_speaking:
                        pcm_audio_buffer.extend(pcm_chunk)
                        if now - last_speech_time > 0.7 and len(pcm_audio_buffer) > 16000:
                            is_speaking = False
                            if device_id in ACTIVE_CONNECTIONS:
                                ACTIVE_CONNECTIONS[device_id]["status"] = "connected"
                            pcm_audio_buffer.clear()

            elif msg.type == web.WSMsgType.ERROR:
                logger.warning(f"Lỗi kết nối socket {device_id}: {ws.exception()}")

    finally:
        pipeline.close()
        ACTIVE_CONNECTIONS.pop(device_id, None)
        update_device_status(device_id, "offline")
        logger.info(f"Đã đóng kết nối client {device_id}")

    return ws
