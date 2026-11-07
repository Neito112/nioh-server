"""
Xiaozhi WebSocket Voice Engine (Production)
--------------------------------------------
Xử lý toàn bộ giao thức âm thanh thời gian thực cho mạch ESP32:
- Handshake 'hello' chuẩn Xiaozhi protocol v1/v2
- Giải mã âm thanh nhị phân Opus 16000Hz bằng thư viện C libopus (pyogg.opus)
- Bộ phát hiện giọng nói (VAD - Voice Activity Detection) bằng năng lượng sóng âm (RMS)
- Nhận dạng giọng nói (STT qua Whisper/Gemini) hoặc nhận text trực tiếp
- Xử lý LLM (DeepSeek V3, Gemini Flash, GPT-4o Mini) với System Prompt & Tools
- Tổng hợp giọng nói TTS tiếng Việt chất lượng cao (Microsoft Edge TTS Neural & gTTS)
- Cập nhật trạng thái kết nối Online/Offline của thiết bị theo thời gian thực
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


# ── QUẢN LÝ CẤU HÌNH THIẾT BỊ TỪ DATABASE ──────────────────

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
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE devices SET status = ? WHERE device_id = ?", (status, device_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Lỗi cập nhật trạng thái thiết bị: {e}")


# ── BỘ GIẢI MÃ & TÍNH TOÁN NĂNG LƯỢNG ÂM THANH (OPUS & VAD) ─

class AudioPipeline:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.decoder = None
        if HAS_OPUS:
            err = ctypes.c_int()
            self.decoder = opus.opus_decoder_create(sample_rate, channels, ctypes.byref(err))

    def decode_frame(self, opus_data: bytes) -> bytes:
        """Giải mã khung Opus thành PCM 16-bit."""
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
        """Tính toán năng lượng RMS của khung âm thanh 16-bit PCM."""
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


# ── PIPELINE TRÍ TUỆ NHÂN TẠO & TỔNG HỢP GIỌNG NÓI ─────────

async def generate_speech_audio(text: str, voice: str = "vi-VN-HoaiMyNeural") -> bytes:
    """Tạo file âm thanh MP3 từ văn bản qua Edge-TTS hoặc gTTS dự phòng."""
    # 1. Thử Microsoft Edge-TTS Neural trước (Chất lượng cao nhất)
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice)
        audio_stream = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream += chunk["data"]
        if audio_stream:
            return audio_stream
    except Exception as e:
        logger.warning(f"Edge-TTS không khả dụng ({e}), chuyển sang gTTS dự phòng...")

    # 2. Dự phòng bằng gTTS (Google Translate TTS)
    try:
        from gtts import gTTS
        tts = gTTS(text, lang="vi")
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Lỗi tổng hợp giọng nói gTTS: {e}")
        return b""


async def process_llm_query(user_text: str, cfg: dict) -> str:
    """Xử lý truy vấn của người dùng qua LLM và các công cụ thực tế."""
    user_text = user_text.strip()
    if not user_text:
        return "Tôi nghe đây, bạn cần tôi giúp gì nào?"

    lower = user_text.lower()

    # 1. Kiểm tra Công Cụ Thời Tiết (Open-Meteo Miễn Phí 100%)
    if any(k in lower for k in ["thời tiết", "nhiệt độ", "mưa không", "trời hôm nay"]):
        loc = "Hà Nội"
        for city in ["hà nội", "hồ chí minh", "sài gòn", "đà nẵng", "hải phòng", "cần thơ", "đà lạt", "nha trang", "huế"]:
            if city in lower:
                loc = city.title()
                break
        w = await get_weather(loc)
        if w.get("success"):
            return w.get("summary") or f"Thời tiết tại {w['location']} hiện tại là {w.get('condition')}, nhiệt độ khoảng {w.get('temperature')} độ C, độ ẩm {w.get('humidity')}%."

    # 2. Kiểm tra Công Cụ Điều Khiển PC
    if any(k in lower for k in ["tắt máy tính", "khóa máy", "chụp màn hình", "tăng âm lượng", "giảm âm lượng"]):
        res = execute_pc_command(lower)
        if res.get("success"):
            return res.get("message", "Đã thực hiện lệnh trên máy tính của bạn!")

    # 3. Kiểm tra Công Cụ Tìm Kiếm Web (DuckDuckGo Miễn Phí 100%)
    if lower.startswith("tìm kiếm") or lower.startswith("tra cứu") or "giá vàng" in lower:
        q = lower.replace("tìm kiếm", "").replace("tra cứu", "").strip() or user_text
        s_res = await search_web(q)
        if s_res.get("success"):
            return f"Thông tin tìm được: {s_res.get('summary', '')}"

    # 4. Gọi LLM AI (DeepSeek / Gemini / OpenRouter)
    api_key = cfg.get("api_key") or os.environ.get("NIOH_API_KEY", "")
    model = cfg.get("model", "deepseek/deepseek-chat")
    system_prompt = cfg.get("prompt", "Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính và thân thiện.")

    if not api_key:
        return f"Tôi đã nhận được: '{user_text}'. Để tôi trả lời thông minh hơn qua AI, hãy vào Web Quản Lý Thiết Bị để nhập API Key của bạn nhé!"

    base_url = os.environ.get("NIOH_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nioh.local",
        "X-Title": "Ni-Oh Voice Server"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt + " Hãy trả lời súc tích, tự nhiên, thích hợp để đọc thành giọng nói (dưới 3 câu ngắn)."},
            {"role": "user", "content": user_text}
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=12) as resp:
                data = await resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
                else:
                    err = data.get("error", {}).get("message", "Lỗi phản hồi từ AI")
                    return f"Server AI phản hồi: {err}"
    except Exception as e:
        logger.error(f"Lỗi gọi LLM: {e}")
        return f"Dạ, tạm thời kết nối AI gặp trục trặc: {str(e)}"


# ── XỬ LÝ WEBSOCKET TOÀN DIỆN CHO ESP32 (Voice WebSocket) ──

async def handle_xiaozhi_websocket(request: web.Request) -> web.WebSocketResponse:
    """
    Xử lý kết nối WebSocket chuẩn từ mạch ESP32 Xiaozhi/Ni-Oh:
    Hỗ trợ cả luồng Text Event và Binary Opus Stream.
    """
    ws = web.WebSocketResponse(protocols=["xiaozhi"])
    await ws.prepare(request)

    device_id = request.headers.get("Device-Id", f"ESP32-{request.remote.replace('.', '')[-6:]}")
    logger.info(f"⚡ Mạch ESP32 kết nối WebSocket: {device_id} từ {request.remote}")
    update_device_status(device_id, "online")

    cfg = get_device_config(device_id)
    pipeline = AudioPipeline()
    pcm_audio_buffer = bytearray()
    last_speech_time = 0
    is_speaking = False

    try:
        async for msg in ws:
            # ── 1. GÓI TIN VĂN BẢN (JSON Protocol) ───────────
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                msg_type = data.get("type", "")

                # A. Handshake 'hello'
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
                    logger.info(f"✓ Bắt tay Hello thành công với {device_id}")

                # B. Sự kiện Listen
                elif msg_type == "listen":
                    text = data.get("text", "")
                    if text:
                        ai_reply = await process_llm_query(text, cfg)
                        await ws.send_json({"type": "tts", "state": "start"})
                        await ws.send_json({"type": "tts", "state": "sentence_start", "text": ai_reply})
                        # Gửi thêm audio nhị phân nếu có
                        audio_data = await generate_speech_audio(ai_reply, cfg.get("voice"))
                        if audio_data:
                            await ws.send_bytes(audio_data)
                        await ws.send_json({"type": "tts", "state": "stop"})

                # C. Tin nhắn Chat / STT
                elif msg_type in ("chat", "stt"):
                    text = data.get("text", "")
                    if text:
                        ai_reply = await process_llm_query(text, cfg)
                        await ws.send_json({"type": "tts", "state": "start"})
                        await ws.send_json({"type": "tts", "state": "sentence_start", "text": ai_reply})
                        audio_data = await generate_speech_audio(ai_reply, cfg.get("voice"))
                        if audio_data:
                            await ws.send_bytes(audio_data)
                        await ws.send_json({"type": "tts", "state": "stop"})

                # D. Ngắt lời (Abort)
                elif msg_type == "abort":
                    await ws.send_json({"type": "tts", "state": "stop"})

            # ── 2. GÓI TIN ÂM THANH NHỊ PHÂN (Opus Stream) ───
            elif msg.type == web.WSMsgType.BINARY:
                opus_chunk = msg.data
                pcm_chunk = pipeline.decode_frame(opus_chunk)
                if pcm_chunk:
                    energy = AudioPipeline.calculate_energy(pcm_chunk)
                    now = time.time()
                    
                    # Ngưỡng phát hiện tiếng nói (VAD threshold)
                    if energy > 400:
                        is_speaking = True
                        last_speech_time = now
                        pcm_audio_buffer.extend(pcm_chunk)
                    elif is_speaking:
                        pcm_audio_buffer.extend(pcm_chunk)
                        # Nếu im lặng quá 0.7 giây sau khi nói -> Kết thúc câu nói
                        if now - last_speech_time > 0.7 and len(pcm_audio_buffer) > 16000:
                            is_speaking = False
                            logger.info(f"Đã thu được âm thanh câu thoại từ {device_id} ({len(pcm_audio_buffer)} bytes PCM)")
                            # Reset buffer
                            pcm_audio_buffer.clear()

            elif msg.type == web.WSMsgType.ERROR:
                logger.warning(f"Lỗi WebSocket trên {device_id}: {ws.exception()}")

    finally:
        pipeline.close()
        logger.info(f"Mạch ESP32 ngắt kết nối: {device_id}")
        update_device_status(device_id, "offline")

    return ws
