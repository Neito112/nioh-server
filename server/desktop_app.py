"""
Ni-Oh Server Engine & Desktop Application (Dashboard 1)
------------------------------------------------------
Giao diện Desktop App quản lý máy chủ tổng (Server Host Dashboard):
- 100% cấu hình trực quan trên giao diện, KHÔNG CẦN CHỈNH FILE .ENV
- Danh sách Model chọn lọc chuyên dụng cho trợ lý giọng nói (Voice Assistant)
- Hỗ trợ nút tự động tải danh sách Model thực tế từ API Key của người dùng
- Không khóa cứng OpenRouter (hỗ trợ DeepSeek, OpenAI, Groq, Ollama...)
- Bật/tắt Cloudflare Tunnel chỉ với 1 click
- Bảng công tắc Toggle bật/tắt toàn bộ các Tools (PC Control, Weather, Search, Music, ESP-NOW, Smart Home)
- Phục vụ Web Portal Quản lý Thiết bị (Dashboard 2)
"""

import os
import sys
import json
import asyncio
import logging
import webbrowser
import aiohttp
from aiohttp import web
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from server.tools.pc_control import execute_pc_command
from server.tools.free_weather import get_weather
from server.tools.free_search import search_web
from server.tools.free_music import search_and_get_audio_stream
from server.tools.esp_now_handler import build_esp_now_packet
from server.tools.iot_discovery import scan_local_iot_devices, generate_auth_qr_link
from cloudflare.tunnel import setup_tunnel, stop_tunnel

logger = logging.getLogger("nioh.desktop_app")

ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

# Cấu hình trạng thái Runtime
STATE = {
    "server_running": False,
    "tunnel_url": "",
    "wss_url": "",
    "host_account": os.environ.get("NIOH_HOST_ACCOUNT", "admin@nioh.local"),
    "llm_provider": os.environ.get("NIOH_LLM_PROVIDER", "openrouter"),
    "llm_base_url": os.environ.get("NIOH_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    "llm_api_key": os.environ.get("NIOH_API_KEY", ""),
    "llm_model": os.environ.get("NIOH_MODEL", "deepseek/deepseek-chat"),
    "github_token": os.environ.get("NIOH_GITHUB_TOKEN", ""),
    "custom_domain": os.environ.get("NIOH_CF_DOMAIN", ""),
    "ws_port": int(os.environ.get("NIOH_WS_PORT", "8000")),
    "http_port": int(os.environ.get("NIOH_HTTP_PORT", "8003")),
    "tools": {
        "pc_control": True,
        "weather": True,
        "web_search": True,
        "music": True,
        "esp_now": True,
        "smart_home": True,
    },
    "bound_devices": [],
    "pairing_codes": {},
}


# ── REST API cho Desktop App Dashboard ──────────────────────

async def api_get_status(request):
    return web.json_response(STATE)


async def api_save_config(request):
    data = await request.json()
    STATE["host_account"] = data.get("host_account", STATE["host_account"])
    STATE["llm_provider"] = data.get("provider", STATE["llm_provider"])
    STATE["llm_base_url"] = data.get("base_url", STATE["llm_base_url"])
    STATE["llm_api_key"] = data.get("api_key", STATE["llm_api_key"])
    STATE["llm_model"] = data.get("model", STATE["llm_model"])
    STATE["github_token"] = data.get("github_token", STATE["github_token"])
    STATE["custom_domain"] = data.get("custom_domain", STATE["custom_domain"])
    if "ws_port" in data: STATE["ws_port"] = int(data["ws_port"])
    if "tools" in data: STATE["tools"].update(data["tools"])

    _save_to_env()
    return web.json_response({"success": True, "message": "Đã lưu cài đặt trực tiếp vào hệ thống!"})


async def api_fetch_live_models(request):
    """Lấy danh sách model thực tế từ API endpoint bằng API Key của người dùng."""
    data = await request.json()
    base_url = data.get("base_url", "").rstrip("/")
    api_key = data.get("api_key", "").strip()

    if not base_url:
        return web.json_response({"success": False, "message": "Vui lòng nhập API Base URL!"})

    models_endpoint = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(models_endpoint, headers=headers, timeout=6) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    models_data = result.get("data", [])
                    model_ids = [m.get("id") for m in models_data if isinstance(m, dict) and "id" in m]
                    return web.json_response({"success": True, "models": sorted(model_ids)})
                else:
                    return web.json_response({"success": False, "message": f"Máy chủ API báo lỗi {resp.status}."})
    except Exception as e:
        logger.warning(f"Lỗi lấy model từ {models_endpoint}: {e}")
        return web.json_response({"success": False, "message": f"Không thể lấy danh sách từ API: {str(e)}"})


async def api_toggle_server(request):
    data = await request.json()
    action = data.get("action")
    if action == "start":
        STATE["server_running"] = True
        try:
            wss_url = await setup_tunnel(STATE["ws_port"])
            STATE["wss_url"] = wss_url
            STATE["tunnel_url"] = wss_url.replace("wss://", "https://").replace("/xiaozhi/v1/", "")
        except Exception as e:
            logger.warning(f"Tunnel lỗi hoặc đang chạy offline: {e}")
            STATE["wss_url"] = f"ws://localhost:{STATE['ws_port']}/xiaozhi/v1/"
            STATE["tunnel_url"] = f"http://localhost:{STATE['http_port']}"
    else:
        STATE["server_running"] = False
        stop_tunnel()
        STATE["tunnel_url"] = ""
        STATE["wss_url"] = ""

    return web.json_response({"success": True, "state": STATE})


async def api_scan_iot(request):
    res = await scan_local_iot_devices()
    return web.json_response(res)


# ── REST API cho Web Portal (Dashboard 2) ───────────────────

async def api_device_bind(request):
    data = await request.json()
    code = data.get("pairing_code", "").strip()
    user_id = data.get("user_id", "guest")
    bot_name = data.get("bot_name", "Ni-Oh S3 Mini")

    if code in STATE["pairing_codes"]:
        device_info = STATE["pairing_codes"].pop(code)
        device_info["bot_name"] = bot_name
        device_info["owner"] = user_id
        STATE["bound_devices"].append(device_info)
        return web.json_response({"success": True, "message": f"Ghép đôi thiết bị '{bot_name}' thành công!"})
    else:
        new_dev = {
            "device_id": f"nioh-{code if code else 'device-1'}",
            "bot_name": bot_name,
            "owner": user_id,
            "status": "online",
            "prompt": "Bạn là trợ lý Ni-Oh thông minh, vui vẻ và thân thiện.",
            "voice": "vi-VN-HoaiMyNeural",
            "model": STATE["llm_model"],
        }
        STATE["bound_devices"].append(new_dev)
        return web.json_response({"success": True, "message": f"Đã kết nối thiết bị với mã {code}!"})


async def api_get_my_devices(request):
    return web.json_response({"devices": STATE["bound_devices"]})


def _save_to_env():
    lines = [
        f"NIOH_HOST_ACCOUNT={STATE['host_account']}\n",
        f"NIOH_LLM_PROVIDER={STATE['llm_provider']}\n",
        f"NIOH_API_KEY={STATE['llm_api_key']}\n",
        f"NIOH_LLM_BASE_URL={STATE['llm_base_url']}\n",
        f"NIOH_MODEL={STATE['llm_model']}\n",
        f"NIOH_GITHUB_TOKEN={STATE['github_token']}\n",
        f"NIOH_CF_DOMAIN={STATE['custom_domain']}\n",
        f"NIOH_WS_PORT={STATE['ws_port']}\n",
        f"NIOH_HTTP_PORT={STATE['http_port']}\n",
    ]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ── Giao diện HTML Dashboard 1 ──────────────────────────────

HTML_DESKTOP_DASHBOARD = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Server Control Center</title>
    <style>
        :root {
            --bg: #0b0f19; --panel: #151d30; --panel-hover: #1e293b; --accent: #38bdf8;
            --text: #f8fafc; --muted: #94a3b8; --border: #232f48; --success: #22c55e; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; max-width: 1100px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .title { font-size: 22px; font-weight: 800; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .badge { background: #0369a1; color: white; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: normal; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
        .card-title { font-size: 15px; font-weight: 700; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; color: #e2e8f0; }
        .btn { background: var(--accent); color: #0b0f19; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.2s; font-size: 14px; }
        .btn:hover { filter: brightness(1.1); }
        .btn-sm { padding: 6px 12px; font-size: 12px; border-radius: 6px; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-portal { background: #8b5cf6; color: white; }
        .input-group { margin-bottom: 14px; }
        label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
        input, select { width: 100%; background: #070a12; border: 1px solid var(--border); color: white; padding: 10px 12px; border-radius: 8px; font-size: 14px; outline: none; }
        input:focus, select:focus { border-color: var(--accent); }
        .switch-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #1c263d; }
        .status-box { padding: 12px; background: #070a12; border: 1px solid var(--border); border-radius: 8px; font-family: monospace; font-size: 13px; word-break: break-all; margin-top: 6px; color: #38bdf8; }
        .status-online { color: var(--success); font-weight: bold; }
        .status-offline { color: var(--danger); font-weight: bold; }
        .collapsible-header { cursor: pointer; user-select: none; color: var(--accent); font-size: 13px; margin-top: 10px; display: inline-block; }
        .label-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span>⚡ Ni-Oh Server Engine</span>
            <span class="badge" id="hostAccountDisplay">Host: admin@nioh.local</span>
        </div>
        <div style="display: flex; gap: 10px;">
            <button class="btn btn-portal" onclick="openDevicePortal()">🌐 Mở Web Quản Lý Thiết Bị</button>
            <button class="btn" id="serverToggleBtn" onclick="toggleServer()">Khởi động Server</button>
        </div>
    </div>

    <div class="grid">
        <!-- Cột 1: Cấu hình LLM & Chọn Model Chuyên Dụng -->
        <div class="card">
            <div class="card-title">🤖 Cấu hình Trí Tuệ Nhân Tạo (AI Engine)</div>
            
            <div class="input-group">
                <label>Tài khoản Quản lý Máy chủ (Host Account)</label>
                <input type="text" id="hostAccountInput" placeholder="admin@domain.com">
            </div>

            <div class="input-group">
                <label>Nhà cung cấp AI (Provider)</label>
                <select id="providerSelect" onchange="onProviderChange()">
                    <option value="openrouter">OpenRouter (Kho 100+ Models)</option>
                    <option value="deepseek">DeepSeek (Chính thức)</option>
                    <option value="openai">OpenAI (ChatGPT)</option>
                    <option value="groq">Groq (Siêu tốc độ - Độ trễ cực thấp)</option>
                    <option value="ollama">Ollama (Chạy Offline nội bộ)</option>
                    <option value="custom">Tùy chỉnh (OpenAI-compatible)</option>
                </select>
            </div>
            
            <div class="input-group">
                <label>API Base URL</label>
                <input type="text" id="baseUrlInput" placeholder="https://openrouter.ai/api/v1">
            </div>

            <div class="input-group">
                <div class="label-row">
                    <label>API Key</label>
                    <button class="btn btn-sm" style="background: #1e293b; color: var(--accent);" onclick="fetchLiveModels()">🔄 Quét Model từ Key</button>
                </div>
                <input type="password" id="apiKeyInput" placeholder="Dán API Key của bạn vào đây">
            </div>

            <!-- CHỌN MODEL TỪ DANH SÁCH PHÙ HỢP -->
            <div class="input-group">
                <label>Mô hình AI (Chọn từ danh sách phù hợp nhất):</label>
                <select id="modelSelect" onchange="onModelSelectChange()">
                    <!-- Sẽ được điền tự động qua JavaScript -->
                </select>
            </div>

            <!-- Ô nhập tay dự phòng (chỉ hiện khi chọn 'Khác') -->
            <div class="input-group" id="customModelGroup" style="display: none;">
                <label>Nhập tên Model thủ công:</label>
                <input type="text" id="modelCustomInput" placeholder="ví dụ: meta-llama/llama-3.2-3b-instruct">
            </div>

            <!-- Cài đặt nâng cao -->
            <span class="collapsible-header" onclick="toggleAdvanced()">⚙️ Cài đặt đồng bộ & Domain nâng cao ▼</span>
            <div id="advancedSection" style="display: none; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border);">
                <div class="input-group">
                    <label>GitHub Token (Đồng bộ nhiều máy qua Gist)</label>
                    <input type="password" id="githubTokenInput" placeholder="ghp_xxxx">
                </div>
                <div class="input-group">
                    <label>Domain riêng cho Cloudflare (Bỏ trống = Tự cấp free)</label>
                    <input type="text" id="customDomainInput" placeholder="server.yourdomain.com">
                </div>
            </div>

            <button class="btn" style="width: 100%; margin-top: 14px;" onclick="saveConfig()">💾 Lưu Cài Đặt (Áp dụng ngay)</button>
        </div>

        <!-- Cột 2: Trạng thái & Cloudflare Tunnel -->
        <div class="card">
            <div class="card-title">📡 Trạng Thái Kết Nối & Mạng</div>
            <div class="switch-row">
                <span>Trạng thái Máy Chủ:</span>
                <span id="serverStatusText" class="status-offline">ĐÃ TẮT</span>
            </div>
            <div class="input-group" style="margin-top: 12px;">
                <label>Địa chỉ WebSocket (ESP32 kết nối âm thanh):</label>
                <div class="status-box" id="wssUrlBox">Chưa khởi động server</div>
            </div>
            <div class="input-group">
                <label>Địa chỉ OTA Endpoint (Cập nhật firmware):</label>
                <div class="status-box" id="otaUrlBox">Chưa khởi động server</div>
            </div>
            <div style="margin-top: 16px;">
                <button class="btn" style="width: 100%; background: #0284c7; color: white;" onclick="scanIoT()">🔍 Quét Thiết Bị Nhà Thông Minh Trong LAN</button>
                <div id="iotScanResult" style="margin-top: 8px; font-size: 13px; color: var(--muted);"></div>
            </div>
        </div>

        <!-- Bảng điều khiển Tools (100% Free Toggles) -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-title">🛠️ Công cụ & MCP Tích hợp (Tất cả đều phản hồi tín hiệu từ mạch)</div>
            <div class="grid" style="grid-template-columns: 1fr 1fr 1fr; gap: 14px;">
                <div class="switch-row">
                    <div>
                        <strong>💻 Điều khiển PC</strong><br><small style="color: var(--muted)">Tắt máy, ngủ, khóa màn hình, volume</small>
                    </div>
                    <input type="checkbox" id="tool_pc" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🌤️ Thời tiết Free</strong><br><small style="color: var(--muted)">Open-Meteo không cần key</small>
                    </div>
                    <input type="checkbox" id="tool_weather" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🔎 Tìm kiếm Web Free</strong><br><small style="color: var(--muted)">DuckDuckGo không cần key</small>
                    </div>
                    <input type="checkbox" id="tool_search" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🎵 Nghe nhạc YouTube Free</strong><br><small style="color: var(--muted)">yt-dlp stream âm thanh</small>
                    </div>
                    <input type="checkbox" id="tool_music" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>📡 Giao tiếp ESP-NOW</strong><br><small style="color: var(--muted)">Bắn lệnh qua mạch slave</small>
                    </div>
                    <input type="checkbox" id="tool_espnow" checked onchange="saveTools()">
                </div>
                <div class="switch-row">
                    <div>
                        <strong>🏠 Quét Smart Home LAN</strong><br><small style="color: var(--muted)">mDNS & Home Assistant</small>
                    </div>
                    <input type="checkbox" id="tool_smarthome" checked onchange="saveTools()">
                </div>
            </div>
        </div>
    </div>

    <script>
        // Danh mục Model chọn lọc chuẩn chuyên cho Trợ lý giọng nói (Tối ưu tốc độ, Tiếng Việt, giá rẻ)
        const CURATED_MODELS = {
            openrouter: [
                { id: "deepseek/deepseek-chat", name: "⭐ DeepSeek V3 (Khuyên dùng: Nhanh, Siêu rẻ, Tiếng Việt đỉnh)" },
                { id: "google/gemini-2.0-flash:free", name: "🎁 Google Gemini 2.0 Flash (FREE 100%, Siêu tốc độ)" },
                { id: "openai/gpt-4o-mini", name: "⚡ GPT-4o Mini (Phản hồi cực nhanh, ổn định)" },
                { id: "meta-llama/llama-3.3-70b-instruct", name: "🧠 Llama 3.3 70B (Mạnh mẽ, thông minh)" },
                { id: "anthropic/claude-3.5-sonnet", name: "👑 Claude 3.5 Sonnet (Xử lý thông minh nhất)" },
                { id: "deepseek/deepseek-r1", name: "🔬 DeepSeek R1 (Lý luận & suy nghĩ sâu)" },
                { id: "custom", name: "✏️ Khác (Nhập tên model thủ công)..." }
            ],
            deepseek: [
                { id: "deepseek-chat", name: "⭐ DeepSeek V3 (Chính thức - Khuyên dùng)" },
                { id: "deepseek-reasoner", name: "🔬 DeepSeek R1 (Suy luận sâu)" },
                { id: "custom", name: "✏️ Khác (Nhập tên model thủ công)..." }
            ],
            openai: [
                { id: "gpt-4o-mini", name: "⭐ GPT-4o Mini (Tối ưu tốc độ & đàm thoại)" },
                { id: "gpt-4o", name: "👑 GPT-4o Đầy Đủ" },
                { id: "gpt-3.5-turbo", name: "⚡ GPT-3.5 Turbo" },
                { id: "custom", name: "✏️ Khác (Nhập tên model thủ công)..." }
            ],
            groq: [
                { id: "llama-3.3-70b-versatile", name: "⭐ Llama 3.3 70B (Siêu tốc ~300 tokens/s)" },
                { id: "llama-3.1-8b-instant", name: "⚡ Llama 3.1 8B (Độ trễ gần như số 0)" },
                { id: "mixtral-8x7b-32768", name: "🌀 Mixtral 8x7B" },
                { id: "custom", name: "✏️ Khác (Nhập tên model thủ công)..." }
            ],
            ollama: [
                { id: "qwen2.5:7b", name: "⭐ Qwen 2.5 7B (Khuyên dùng: Hỗ trợ tiếng Việt tốt nhất)" },
                { id: "llama3.2:3b", name: "⚡ Llama 3.2 3B (Siêu nhẹ cho máy yếu)" },
                { id: "gemma2:9b", name: "💎 Google Gemma 2 9B" },
                { id: "custom", name: "✏️ Khác (Nhập tên model thủ công)..." }
            ],
            custom: [
                { id: "custom", name: "✏️ Nhập tên model của bạn..." }
            ]
        };

        const PRESET_URLS = {
            openrouter: "https://openrouter.ai/api/v1",
            deepseek: "https://api.deepseek.com/v1",
            openai: "https://api.openai.com/v1",
            groq: "https://api.groq.com/openai/v1",
            ollama: "http://localhost:11434/v1",
            custom: ""
        };

        function populateModelSelect(provider, selectedModel) {
            const select = document.getElementById('modelSelect');
            const models = CURATED_MODELS[provider] || CURATED_MODELS.custom;
            select.innerHTML = "";

            let found = false;
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.innerText = m.name;
                if (m.id === selectedModel) {
                    opt.selected = true;
                    found = true;
                }
                select.appendChild(opt);
            });

            // Nếu model đang lưu không nằm trong list có sẵn, gán vào custom
            const customGroup = document.getElementById('customModelGroup');
            const customInput = document.getElementById('modelCustomInput');
            if (!found && selectedModel) {
                select.value = "custom";
                customGroup.style.display = "block";
                customInput.value = selectedModel;
            } else if (select.value === "custom") {
                customGroup.style.display = "block";
                customInput.value = selectedModel || "";
            } else {
                customGroup.style.display = "none";
            }
        }

        function onModelSelectChange() {
            const select = document.getElementById('modelSelect');
            const customGroup = document.getElementById('customModelGroup');
            if (select.value === "custom") {
                customGroup.style.display = "block";
            } else {
                customGroup.style.display = "none";
            }
        }

        function onProviderChange() {
            const provider = document.getElementById('providerSelect').value;
            if (PRESET_URLS[provider] !== undefined && PRESET_URLS[provider] !== "") {
                document.getElementById('baseUrlInput').value = PRESET_URLS[provider];
            }
            populateModelSelect(provider, null);
        }

        async function fetchLiveModels() {
            const baseUrl = document.getElementById('baseUrlInput').value;
            const apiKey = document.getElementById('apiKeyInput').value;
            if (!baseUrl) { alert("Vui lòng nhập API Base URL trước!"); return; }

            const res = await fetch('/api/models/live', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ base_url: baseUrl, api_key: apiKey })
            });
            const data = await res.json();
            if (data.success && data.models.length > 0) {
                const select = document.getElementById('modelSelect');
                select.innerHTML = "";
                data.models.forEach(id => {
                    const opt = document.createElement('option');
                    opt.value = id;
                    opt.innerText = id;
                    select.appendChild(opt);
                });
                const customOpt = document.createElement('option');
                customOpt.value = "custom";
                customOpt.innerText = "✏️ Khác (Nhập tên thủ công)...";
                select.appendChild(customOpt);
                alert(`Đã quét thấy ${data.models.length} model từ tài khoản của bạn!`);
            } else {
                alert(data.message || "Không thể quét danh sách model.");
            }
        }

        async function loadStatus() {
            const res = await fetch('/api/status');
            const data = await res.json();
            document.getElementById('hostAccountDisplay').innerText = "Host: " + (data.host_account || "admin@nioh.local");
            document.getElementById('hostAccountInput').value = data.host_account || "";
            
            const provider = data.llm_provider || 'openrouter';
            document.getElementById('providerSelect').value = provider;
            document.getElementById('baseUrlInput').value = data.llm_base_url || "";
            document.getElementById('apiKeyInput').value = data.llm_api_key || "";
            document.getElementById('githubTokenInput').value = data.github_token || "";
            document.getElementById('customDomainInput').value = data.custom_domain || "";

            // Populate danh sách model phù hợp
            populateModelSelect(provider, data.llm_model);

            const isRun = data.server_running;
            const statusTxt = document.getElementById('serverStatusText');
            const btn = document.getElementById('serverToggleBtn');
            if (isRun) {
                statusTxt.innerText = "ĐANG HOẠT ĐỘNG (ONLINE)"; statusTxt.className = "status-online";
                btn.innerText = "Dừng Server"; btn.className = "btn btn-danger";
                document.getElementById('wssUrlBox').innerText = data.wss_url || "Đang cấp phát...";
                document.getElementById('otaUrlBox').innerText = (data.tunnel_url ? data.tunnel_url + "/xiaozhi/ota/" : "");
            } else {
                statusTxt.innerText = "ĐÃ TẮT"; statusTxt.className = "status-offline";
                btn.innerText = "Khởi động Server"; btn.className = "btn";
                document.getElementById('wssUrlBox').innerText = "Chưa khởi động";
                document.getElementById('otaUrlBox').innerText = "Chưa khởi động";
            }
        }

        function toggleAdvanced() {
            const el = document.getElementById('advancedSection');
            el.style.display = (el.style.display === 'none') ? 'block' : 'none';
        }

        async function saveConfig() {
            let selectedModel = document.getElementById('modelSelect').value;
            if (selectedModel === "custom") {
                selectedModel = document.getElementById('modelCustomInput').value.trim();
            }

            const payload = {
                host_account: document.getElementById('hostAccountInput').value,
                provider: document.getElementById('providerSelect').value,
                base_url: document.getElementById('baseUrlInput').value,
                api_key: document.getElementById('apiKeyInput').value,
                model: selectedModel,
                github_token: document.getElementById('githubTokenInput').value,
                custom_domain: document.getElementById('customDomainInput').value
            };
            const res = await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
            const data = await res.json();
            alert(data.message);
            loadStatus();
        }

        async function saveTools() {
            const tools = {
                pc_control: document.getElementById('tool_pc').checked,
                weather: document.getElementById('tool_weather').checked,
                web_search: document.getElementById('tool_search').checked,
                music: document.getElementById('tool_music').checked,
                esp_now: document.getElementById('tool_espnow').checked,
                smart_home: document.getElementById('tool_smarthome').checked
            };
            await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ tools }) });
        }

        async function toggleServer() {
            const isRunning = document.getElementById('serverStatusText').innerText.includes("ONLINE");
            const action = isRunning ? "stop" : "start";
            await fetch('/api/server/toggle', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ action }) });
            setTimeout(loadStatus, 1500);
        }

        async function scanIoT() {
            const el = document.getElementById('iotScanResult');
            el.innerText = "Đang quét mạng nội bộ...";
            const res = await fetch('/api/iot/scan');
            const data = await res.json();
            el.innerText = data.message;
        }

        function openDevicePortal() {
            window.open('/portal', '_blank');
        }

        loadStatus();
    </script>
</body>
</html>
"""


# ── Giao diện HTML Dashboard 2 (Web Portal) ─────────────────

HTML_DEVICE_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Device Portal</title>
    <style>
        :root { --bg: #f8fafc; --panel: #ffffff; --primary: #2563eb; --text: #1e293b; --border: #e2e8f0; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 20px; max-width: 900px; margin: 0 auto; }
        .nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid var(--border); }
        .logo { font-size: 20px; font-weight: 800; color: var(--primary); }
        .card { background: var(--panel); border-radius: 12px; border: 1px solid var(--border); padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
        .card-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; }
        .pin-container { display: flex; gap: 8px; justify-content: center; margin: 16px 0; }
        .pin-box { width: 220px; height: 50px; font-size: 24px; text-align: center; font-weight: bold; border: 2px solid var(--border); border-radius: 8px; letter-spacing: 8px; }
        .btn { background: var(--primary); color: white; border: none; padding: 12px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; width: 100%; font-size: 15px; }
        .device-item { border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .online-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; display: inline-block; margin-right: 6px; }
    </style>
</head>
<body>
    <div class="nav">
        <div class="logo">📱 Ni-Oh Portal (xiaozhi.me Alternative)</div>
        <div style="font-size: 14px; color: #64748b;">Đăng nhập: <strong>user@nioh.io</strong></div>
    </div>

    <div class="card">
        <div class="card-title">🔗 Ghép đôi thiết bị mới (Mã 6 chữ số)</div>
        <p style="font-size: 14px; color: #64748b;">Nhập mã 6 chữ số hiển thị trên màn hình mạch ESP32 để kích hoạt:</p>
        <div class="pin-container">
            <input type="text" maxlength="6" id="pairingInput" class="pin-box" placeholder="123456">
        </div>
        <div style="margin-bottom: 14px;">
            <label style="font-size: 13px; color: #64748b;">Đặt tên cho Bot:</label>
            <input type="text" id="botNameInput" style="width: 100%; padding: 8px; margin-top: 4px; border: 1px solid var(--border); border-radius: 6px;" value="Ni-Oh S3 Mini">
        </div>
        <button class="btn" onclick="bindDevice()">Kích hoạt & Ghép đôi</button>
    </div>

    <div class="card">
        <div class="card-title">🤖 Thiết bị của tôi</div>
        <div id="deviceList">
            <p style="color: #94a3b8; font-size: 14px;">Chưa có thiết bị nào. Nhập mã 6 số phía trên để kết nối.</p>
        </div>
    </div>

    <script>
        async function loadDevices() {
            const res = await fetch('/api/portal/my-devices');
            const data = await res.json();
            const list = document.getElementById('deviceList');
            if (data.devices.length === 0) {
                list.innerHTML = `<p style="color: #94a3b8; font-size: 14px;">Chưa có thiết bị nào được gán.</p>`;
                return;
            }
            list.innerHTML = data.devices.map(d => `
                <div class="device-item">
                    <div>
                        <strong><span class="online-dot"></span>${d.bot_name}</strong>
                        <div style="font-size: 12px; color: #64748b; margin-top: 4px;">ID: ${d.device_id} | Giọng: ${d.voice || 'Mặc định'}</div>
                    </div>
                    <button style="padding: 6px 12px; border: 1px solid #cbd5e1; background: white; border-radius: 6px; cursor: pointer;">Cài đặt</button>
                </div>
            `).join('');
        }

        async function bindDevice() {
            const code = document.getElementById('pairingInput').value;
            const bot_name = document.getElementById('botNameInput').value;
            if (!code) { alert('Vui lòng nhập mã 6 số!'); return; }
            const res = await fetch('/api/portal/bind', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ pairing_code: code, bot_name: bot_name })
            });
            const data = await res.json();
            alert(data.message);
            loadDevices();
        }

        loadDevices();
    </script>
</body>
</html>
"""


def create_desktop_app():
    app = web.Application()
    app.router.add_get("/", lambda req: web.Response(text=HTML_DESKTOP_DASHBOARD, content_type="text/html"))
    app.router.add_get("/portal", lambda req: web.Response(text=HTML_DEVICE_PORTAL, content_type="text/html"))

    app.router.add_get("/api/status", api_get_status)
    app.router.add_post("/api/config", api_save_config)
    app.router.add_post("/api/models/live", api_fetch_live_models)
    app.router.add_post("/api/server/toggle", api_toggle_server)
    app.router.add_get("/api/iot/scan", api_scan_iot)
    app.router.add_post("/api/portal/bind", api_device_bind)
    app.router.add_get("/api/portal/my-devices", api_get_my_devices)

    return app


async def run_desktop_app_server(port: int = 8001):
    app = create_desktop_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"\n[OK] Ni-Oh Desktop App đang chạy tại: http://localhost:{port}")
    print(f"[OK] Web Portal Quản lý Thiết bị tại: http://localhost:{port}/portal\n")
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_desktop_app_server(8001))
    loop.run_forever()
