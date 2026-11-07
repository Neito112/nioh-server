"""
Ni-Oh Voice Engine (Vietnamese Xiaozhi-Compatible Core)
-------------------------------------------------------
Chuẩn hóa theo kiến trúc của máy chủ mẫu "xinnan-tech/xiaozhi-esp32-server":
1. Bắt tay WebSocket Hello Handshake chuẩn giao thức Xiaozhi (Version 1 & 2)
2. Luồng ghép đôi mã PIN 6 chữ số: tự động xuất mã lên màn hình LCD mạch ESP32
   và phát giọng nói hướng dẫn tiếng Việt khi mạch chưa được kích hoạt
3. Bộ câu lệnh đánh thức (Wake-word) và phản hồi thân thiện thuần Việt
4. Bộ câu lệnh thoát (Exit commands) và lời chào tạm biệt tiếng Việt
5. Tích hợp các công cụ chuyên biệt cho người Việt:
   - Thời tiết 63 tỉnh thành Việt Nam qua Open-Meteo (Miễn phí 100%)
   - Tin tức nóng trong ngày từ VnExpress và Báo Tuổi Trẻ (RSS Feed)
   - Ngày giờ Dương lịch & Âm lịch Việt Nam (Múi giờ GMT+7 Asia/Ho_Chi_Minh)
   - Điều khiển lệnh máy tính (PC Control) và thiết bị phần cứng (Xiaozhi IoT)
6. Động cơ đàm thoại AI thông minh (OpenAI-compatible: DeepSeek, Gemini, OpenAI, Ollama)
7. Động cơ giọng đọc Microsoft Edge-TTS Neural chuẩn tiếng Việt (Hoài My & Nam Minh)
"""

import os
import sys
import json
import math
import struct
import io
import time
import random
import asyncio
import sqlite3
import logging
import aiohttp
from aiohttp import web

logger = logging.getLogger("nioh.voice_engine")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")

# Import các công cụ chuyên biệt cho người Việt
from server.tools.free_weather import get_weather
from server.tools.free_search import search_web
from server.tools.pc_control import execute_pc_command
from server.tools.vietnam_datetime import get_vietnam_time_summary
from server.tools.vietnam_news import get_vietnam_news

# Thử nạp thư viện C libopus qua pyogg để giải mã âm thanh nhị phân từ ESP32
HAS_OPUS = False
try:
    import ctypes
    import pyogg.opus as opus
    HAS_OPUS = True
    logger.info("Thư viện libopus C (pyogg) đã sẵn sàng phục vụ giải mã âm thanh ESP32!")
except Exception as e:
    logger.warning(f"Chưa nạp được libopus C: {e}")


# ── BỘ TỪ KHÓA & CÂU THOẠI ĐÁNH THỨC / THOÁT THUẦN VIỆT ───────────

VIETNAMESE_WAKE_WORDS = [
    "chào ni-oh", "chào nioh", "chào xiaozhi", "xiaozhi ơi", "ni-oh ơi", "nioh ơi",
    "bạn ơi", "alo bot", "alô bot", "trợ lý ơi", "ê bot", "chào bạn", "bật bot", "alô"
]

VIETNAMESE_WAKE_RESPONSES = [
    "Dạ, em nghe đây ạ!",
    "Chào bạn, mình có thể giúp gì cho bạn hôm nay?",
    "Mình ở đây, bạn cứ nói nhé!",
    "Dạ, em sẵn sàng rồi ạ!",
    "Em có mặt, mời bạn ra lệnh ạ.",
    "Sẵn sàng lắng nghe bạn!"
]

VIETNAMESE_EXIT_COMMANDS = [
    "tạm biệt", "thoát", "tắt máy", "dừng lại", "nghỉ ngơi đi", "hẹn gặp lại",
    "bye bye", "kết thúc", "ngủ đi", "im lặng", "dừng cuộc trò chuyện"
]

VIETNAMESE_EXIT_RESPONSES = [
    "Tạm biệt bạn, chúc bạn một ngày thật tuyệt vời!",
    "Hẹn gặp lại bạn sau nhé, tạm biệt!",
    "Em xin phép tạm dừng, khi nào cần bạn cứ gọi em nhé!"
]


# ── BỘ GIÁM SÁT KẾT NỐI REAL-TIME (LIVE SESSION REGISTRY) ─────────

ACTIVE_CONNECTIONS: dict[str, dict] = {}


def get_live_connections() -> dict:
    """Trả về danh sách kết nối WebSocket thực tế đang hoạt động."""
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


# ── QUẢN LÝ THIẾT BỊ VÀ CẤU HÌNH TRONG SQLITE ───────────────────────

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
        "enable_news": rows.get("enable_news", "1") == "1",
        "enable_datetime": rows.get("enable_datetime", "1") == "1",
    }


def get_device_info(device_id: str) -> dict:
    """
    Kiểm tra trạng thái thiết bị trong SQLite:
    - Nếu đã gán Trợ lý AI: trả về thông tin cấu hình của Agent đó.
    - Nếu chưa gán hoặc chưa có: trả về is_bound=False cùng mã PIN 6 số.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, name TEXT, pairing_code TEXT, status TEXT DEFAULT 'offline', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    c.execute("""
        SELECT d.device_id, d.user_id, d.agent_id, d.name, d.pairing_code,
               a.name, a.model, a.api_key, a.voice, a.prompt
        FROM devices d
        LEFT JOIN agents a ON d.agent_id = a.id
        WHERE d.device_id = ?
    """, (device_id,))
    row = c.fetchone()

    server_cfg = get_server_runtime_config()

    if not row:
        # Thiết bị mới hoàn toàn -> sinh mã PIN 6 số ngẫu nhiên
        pin = f"{random.randint(100000, 999999)}"
        c.execute(
            "INSERT INTO devices (device_id, user_id, agent_id, name, pairing_code, status) VALUES (?, NULL, NULL, 'Thiết Bị ESP32', ?, 'unbound')",
            (device_id, pin)
        )
        conn.commit()
        conn.close()
        return {
            "is_bound": False,
            "device_id": device_id,
            "pairing_code": pin,
            "bot_name": "Thiết Bị ESP32",
            "model": server_cfg["model"],
            "voice": server_cfg["voice"],
            "api_key": server_cfg["api_key"],
            "prompt": "Bạn là trợ lý AI thông minh, hỗ trợ bằng tiếng Việt tự nhiên và súc tích."
        }

    is_bound = bool(row[1] and row[2])
    pin = row[4] or f"{random.randint(100000, 999999)}"

    # Cập nhật mã PIN nếu trước đó bị rỗng
    if not row[4]:
        c.execute("UPDATE devices SET pairing_code = ? WHERE device_id = ?", (pin, device_id))
        conn.commit()

    conn.close()

    return {
        "is_bound": is_bound,
        "device_id": device_id,
        "pairing_code": pin,
        "bot_name": row[3] or "Thiết Bị ESP32",
        "agent_name": row[5] or "Trợ Lý Mặc Định",
        "model": row[6] or server_cfg["model"],
        "api_key": row[7] or server_cfg["api_key"],
        "voice": row[8] or server_cfg["voice"],
        "prompt": row[9] or "Bạn là trợ lý AI thông minh, hỗ trợ bằng tiếng Việt tự nhiên và súc tích."
    }


def update_device_status(device_id: str, status: str = "online"):
    """Cập nhật trạng thái trực tuyến của thiết bị."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE devices SET status = ? WHERE device_id = ?", (status, device_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Lỗi cập nhật trạng thái thiết bị {device_id}: {e}")


# ── XỬ LÝ ÂM THANH OPUS & BỘ PHÁT HIỆN GIỌNG NÓI VAD ───────────────

class AudioPipeline:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.decoder = None
        if HAS_OPUS:
            try:
                err = ctypes.c_int()
                self.decoder = opus.opus_decoder_create(sample_rate, channels, ctypes.byref(err))
            except Exception:
                self.decoder = None

    def decode_frame(self, opus_data: bytes) -> bytes:
        if not self.decoder or not opus_data:
            return b""
        try:
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
        except Exception:
            pass
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
            try:
                opus.opus_decoder_destroy(self.decoder)
            except Exception:
                pass
            self.decoder = None


# ── TỔNG HỢP GIỌNG ĐỌC TTS CHUẨN TIẾNG VIỆT (EDGE-TTS NEURAL) ──────

async def generate_speech_audio(text: str, voice: str = "vi-VN-HoaiMyNeural", rate: str = "+0%") -> bytes:
    """Tạo âm thanh phát qua loa ESP32 bằng Microsoft Edge-TTS Neural chuẩn tiếng Việt."""
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()
    if not clean_text:
        return b""

    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, voice, rate=rate)
        audio_stream = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream += chunk["data"]
        if audio_stream:
            return audio_stream
    except Exception as e:
        logger.warning(f"Edge-TTS không phản hồi ({e}), sử dụng phương án dự phòng gTTS...")

    try:
        from gtts import gTTS
        tts = gTTS(clean_text, lang="vi")
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Lỗi tổng hợp giọng nói gTTS: {e}")
        return b""


# ── BỘ XỬ LÝ TRUY VẤN TIẾNG VIỆT, CÔNG CỤ & LLM ─────────────────────

async def process_vietnamese_query(user_text: str, dev_info: dict) -> str:
    """Xử lý câu thoại người dùng qua các công cụ Việt hóa hoặc mô hình LLM."""
    query = user_text.strip()
    if not query:
        return random.choice(VIETNAMESE_WAKE_RESPONSES)

    lower = query.lower()
    server_cfg = get_server_runtime_config()

    # 1. Kiểm tra Lệnh Đánh thức (Wake-word)
    if any(lower == w or lower.startswith(w) for w in VIETNAMESE_WAKE_WORDS):
        return random.choice(VIETNAMESE_WAKE_RESPONSES)

    # 2. Kiểm tra Lệnh Thoát / Tạm biệt (Exit Intent)
    if any(cmd in lower for cmd in VIETNAMESE_EXIT_COMMANDS):
        return random.choice(VIETNAMESE_EXIT_RESPONSES)

    # 3. Công cụ Ngày Giờ & Lịch Âm Việt Nam
    if any(k in lower for k in ["mấy giờ", "bây giờ là mấy giờ", "hôm nay ngày mấy", "ngày bao nhiêu", "âm lịch", "lịch âm", "năm nay năm con gì"]):
        dt_res = get_vietnam_time_summary()
        if dt_res.get("success"):
            return dt_res.get("summary")

    # 4. Công cụ Thời Tiết Việt Nam (Open-Meteo)
    if server_cfg.get("enable_weather") and any(k in lower for k in ["thời tiết", "nhiệt độ", "mưa không", "trời hôm nay", "thời tiết ở"]):
        loc = "Hà Nội"
        for city in ["hà nội", "hồ chí minh", "sài gòn", "đà nẵng", "hải phòng", "cần thơ", "đà lạt", "nha trang", "huế", "vũng tàu", "quy nhơn", "quảng ninh", "nghệ an", "bình dương"]:
            if city in lower:
                loc = city.title()
                break
        w = await get_weather(loc)
        if w.get("success"):
            return w.get("summary") or f"Thời tiết tại {w['location']} hiện tại là {w.get('condition')}, nhiệt độ khoảng {w.get('temperature')} độ C, độ ẩm {w.get('humidity')}%."

    # 5. Công cụ Tin Tức Báo Chí Việt Nam (VnExpress & Tuổi Trẻ)
    if server_cfg.get("enable_news") and any(k in lower for k in ["tin tức", "tin nóng", "đọc báo", "thời sự", "tin mới nhất"]):
        cat = "tin-nong"
        if "công nghệ" in lower:
            cat = "cong-nghe"
        elif "kinh doanh" in lower or "kinh tế" in lower:
            cat = "kinh-doanh"
        elif "thể thao" in lower:
            cat = "the-thao"
        news = await get_vietnam_news(cat, max_items=3)
        if news.get("success"):
            return news.get("summary")

    # 6. Công cụ Điều Khiển PC
    if server_cfg.get("enable_pc_control") and any(k in lower for k in ["tắt máy tính", "khóa máy", "chụp màn hình", "tăng âm lượng", "giảm âm lượng"]):
        pc_res = execute_pc_command(lower)
        if pc_res.get("success"):
            return pc_res.get("message", "Đã thực hiện lệnh trên máy tính.")

    # 7. Công cụ Tìm Kiếm Web (DuckDuckGo)
    if server_cfg.get("enable_search") and (lower.startswith("tìm kiếm") or lower.startswith("tra cứu") or "giá vàng" in lower):
        q = lower.replace("tìm kiếm", "").replace("tra cứu", "").strip() or query
        s_res = await search_web(q)
        if s_res.get("success"):
            return f"Thông tin tìm được: {s_res.get('summary', '')[:200]}..."

    # 8. Gọi LLM AI Đàm Thoại
    api_key = dev_info.get("api_key") or server_cfg.get("api_key") or os.environ.get("NIOH_API_KEY", "")
    model = dev_info.get("model") or server_cfg.get("model", "deepseek-chat")
    base_url = server_cfg.get("base_url", "https://api.deepseek.com").rstrip("/")
    system_prompt = dev_info.get("prompt") or "Bạn là Ni-Oh, trợ lý ảo thông minh cho thiết bị ESP32 tại Việt Nam."

    if not api_key:
        return f"Tôi đã nghe rõ: '{query}'. Để tôi có thể trả lời thông minh, vui lòng đăng nhập Web Console và cài đặt API Key cho Trợ lý của bạn."

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n"
                    "QUY TẮC PHÁT ÂM TIẾNG VIỆT:\n"
                    "- Trả lời hoàn toàn bằng tiếng Việt tự nhiên, súc tích (1 đến 2 câu ngắn).\n"
                    "- Không dùng emoji, dấu hoa thị, markdown hoặc ký tự đặc biệt vì câu trả lời sẽ được đọc trực tiếp qua loa của mạch ESP32."
                )
            },
            {"role": "user", "content": query}
        ],
        "temperature": 0.7,
        "max_tokens": 256
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=12) as resp:
                data = await resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    ans = data["choices"][0]["message"]["content"].strip()
                    # Lọc sạch markdown trước khi trả về
                    return ans.replace("*", "").replace("#", "").replace("`", "")
                else:
                    err = data.get("error", {}).get("message", "Máy chủ AI chưa phản hồi.")
                    return f"Lỗi từ dịch vụ AI: {err}"
    except Exception as e:
        logger.error(f"Lỗi gọi LLM API ({url}): {e}")
        return "Kết nối tới dịch vụ AI đang bị gián đoạn, bạn vui lòng thử lại sau nhé."


# ── ĐỘNG CƠ WEBSOCKET VOICE CHUẨN GIAO THỨC XIAOZHI ─────────────────

async def handle_xiaozhi_websocket(request: web.Request) -> web.WebSocketResponse:
    """
    Xử lý kết nối WebSocket từ mạch phần cứng ESP32 theo chuẩn giao thức Xiaozhi:
    - Bắt tay Hello Handshake (Protocol version 1)
    - Quản lý mã PIN ghép đôi 6 số trên màn hình LCD khi chưa liên kết
    - Xử lý bản tin điều khiển Text (listen, abort, iot, ping)
    - Xử lý luồng âm thanh nhị phân (Binary Opus Audio Stream)
    """
    ws = web.WebSocketResponse(protocols=["xiaozhi"])
    await ws.prepare(request)

    # Lấy Device ID từ Headers hoặc Query Parameters
    device_id = (
        request.headers.get("Device-Id")
        or request.headers.get("device-id")
        or request.headers.get("Client-Id")
        or request.query.get("device-id")
        or f"ESP32-{request.remote.replace('.', '')[-6:]}"
    )

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

    pipeline = AudioPipeline()
    dev_info = get_device_info(device_id)
    session_id = f"sess_{os.urandom(6).hex()}"

    # Luồng kiểm tra ghép đôi thiết bị (Device Binding Flow)
    if not dev_info["is_bound"]:
        pin_code = dev_info["pairing_code"]
        logger.info(f"Thiết bị {device_id} chưa ghép đôi. Mã PIN 6 số xuất ra màn hình: {pin_code}")

        # Gửi bản tin STT để màn hình LCD của ESP32 hiển thị mã PIN
        display_msg = {
            "type": "stt",
            "text": f"Mã PIN: {pin_code} - Nhập trên Web Console để kích hoạt",
            "session_id": session_id
        }
        await ws.send_json(display_msg)

        # Phát âm thanh hướng dẫn bằng tiếng Việt
        voice_guide = f"Chào bạn! Vui lòng truy cập trang quản lý và nhập mã PIN gồm sáu chữ số: {pin_code} để kết nối thiết bị của bạn."
        audio_bytes = await generate_speech_audio(voice_guide, dev_info["voice"])
        if audio_bytes:
            await ws.send_json({"type": "tts", "state": "start", "session_id": session_id})
            await ws.send_json({"type": "tts", "state": "sentence_start", "text": voice_guide, "session_id": session_id})
            await ws.send_bytes(audio_bytes)
            await ws.send_json({"type": "tts", "state": "stop", "session_id": session_id})

    try:
        async for msg in ws:
            if device_id in ACTIVE_CONNECTIONS:
                ACTIVE_CONNECTIONS[device_id]["rx_packets"] += 1

            # ── 1. GÓI TIN ĐIỀU KHIỂN JSON TEXT ────────────────────
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                msg_type = data.get("type", "")

                # 1.1. Bắt tay Hello Handshake
                if msg_type == "hello":
                    client_audio = data.get("audio_params", {})
                    sample_rate = client_audio.get("sample_rate", 16000)
                    channels = client_audio.get("channels", 1)
                    frame_dur = client_audio.get("frame_duration", 60)

                    hello_reply = {
                        "type": "hello",
                        "transport": "websocket",
                        "version": 1,
                        "session_id": session_id,
                        "audio_params": {
                            "format": "opus",
                            "sample_rate": sample_rate,
                            "channels": channels,
                            "frame_duration": frame_dur
                        }
                    }
                    await ws.send_json(hello_reply)
                    if device_id in ACTIVE_CONNECTIONS:
                        ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 1
                    logger.info(f"Hoàn tất bắt tay Hello với {device_id} (SampleRate: {sample_rate}Hz)")

                # 1.2. Nhận bản tin thoại Listen / Chat / STT
                elif msg_type in ("listen", "chat", "stt"):
                    state = data.get("state", "")

                    if state == "start":
                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["status"] = "listening"

                    elif state == "stop":
                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["status"] = "processing"

                    # Khi nhận diện được văn bản giọng nói
                    text = data.get("text", "").strip()
                    if text:
                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["status"] = "processing"

                        # Nạp lại cấu hình thiết bị mới nhất phòng khi vừa được ghép đôi trên web
                        dev_info = get_device_info(device_id)

                        # Xử lý nội dung người dùng nói
                        reply_text = await process_vietnamese_query(text, dev_info)

                        # Gửi bản tin STT cập nhật nội dung phản hồi lên màn hình LCD mạch ESP32
                        await ws.send_json({
                            "type": "stt",
                            "text": reply_text,
                            "session_id": session_id
                        })

                        # Phát âm thanh tổng hợp tiếng Việt qua TTS
                        await ws.send_json({"type": "tts", "state": "start", "session_id": session_id})
                        await ws.send_json({
                            "type": "tts",
                            "state": "sentence_start",
                            "text": reply_text,
                            "session_id": session_id
                        })

                        audio_bytes = await generate_speech_audio(reply_text, dev_info["voice"])
                        if audio_bytes:
                            await ws.send_bytes(audio_bytes)

                        await ws.send_json({"type": "tts", "state": "stop", "session_id": session_id})

                        if device_id in ACTIVE_CONNECTIONS:
                            ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 4
                            ACTIVE_CONNECTIONS[device_id]["status"] = "connected"

                # 1.3. Ngắt ngang câu thoại (Abort / Cut-in)
                elif msg_type == "abort":
                    await ws.send_json({"type": "tts", "state": "stop", "session_id": session_id})
                    if device_id in ACTIVE_CONNECTIONS:
                        ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 1
                        ACTIVE_CONNECTIONS[device_id]["status"] = "connected"

                # 1.4. Nhịp tim giữ kết nối (Ping / Pong)
                elif msg_type == "ping":
                    await ws.send_json({"type": "pong", "session_id": session_id})
                    if device_id in ACTIVE_CONNECTIONS:
                        ACTIVE_CONNECTIONS[device_id]["tx_packets"] += 1

                # 1.5. Thiết bị IoT điều khiển phần cứng
                elif msg_type == "iot":
                    # Xử lý báo cáo trạng thái phần cứng của ESP32 (pin, âm lượng, wifi)
                    descriptors = data.get("descriptors") or []
                    states = data.get("states") or []
                    logger.debug(f"Nhận bản tin IoT từ {device_id}: {descriptors} {states}")

            # ── 2. GÓI TIN ÂM THANH NHỊ PHÂN (BINARY OPUS FRAME) ───
            elif msg.type == web.WSMsgType.BINARY:
                if device_id in ACTIVE_CONNECTIONS:
                    ACTIVE_CONNECTIONS[device_id]["audio_frames"] += 1

                opus_frame = msg.data
                pcm_frame = pipeline.decode_frame(opus_frame)
                if pcm_frame:
                    energy = AudioPipeline.calculate_energy(pcm_frame)
                    if energy > 350 and device_id in ACTIVE_CONNECTIONS:
                        ACTIVE_CONNECTIONS[device_id]["status"] = "speaking"

            elif msg.type == web.WSMsgType.ERROR:
                logger.warning(f"Lỗi socket {device_id}: {ws.exception()}")

    finally:
        pipeline.close()
        ACTIVE_CONNECTIONS.pop(device_id, None)
        update_device_status(device_id, "offline")
        logger.info(f"Đã đóng kết nối client {device_id}")

    return ws
