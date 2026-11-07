"""
Ni-Oh Server Console (Desktop App)
----------------------------------
Thành phần 1: Giao diện điều khiển máy chủ & thiết lập dịch vụ:
- Cấu hình nhà cung cấp AI (OpenAI-compatible: DeepSeek, OpenRouter, OpenAI, Gemini, Ollama)
- Cấu hình giọng đọc Edge-TTS Neural và bộ công cụ hệ thống
- Khởi chạy Cloudflare Anycast Tunnel và xuất điểm cuối kết nối
- Giám sát các phiên WebSocket đang kết nối thực tế
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging
from aiohttp import web

logger = logging.getLogger("nioh.server_console")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")

from cloudflare.tunnel import (
    activate_quick_tunnel_link,
    setup_tunnel,
    stop_tunnel
)
from server.voice_engine import (
    get_live_connections,
    get_server_runtime_config
)

# Trạng thái Gateway
GATEWAY_STATE = {
    "server_running": False,
    "cf_domain": "",
    "portal_web_url": "",
    "wss_url": "",
    "ota_url": "",
}


def save_server_config(data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in data.items():
        c.execute("INSERT OR REPLACE INTO server_config (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()

    if "api_key" in data and data["api_key"]:
        os.environ["NIOH_API_KEY"] = data["api_key"]
    if "model" in data and data["model"]:
        os.environ["NIOH_MODEL"] = data["model"]
    if "base_url" in data and data["base_url"]:
        os.environ["NIOH_LLM_BASE_URL"] = data["base_url"]


# ── REST API DÀNH CHO CONSOLE ĐIỀU KHIỂN ───────────────────────────

async def api_get_gateway_status(request):
    server_cfg = get_server_runtime_config()
    live_stats = get_live_connections()

    # Đếm tổng số thiết bị đã ghép đôi trong database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, name TEXT, pairing_code TEXT, status TEXT DEFAULT 'offline', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("SELECT count(*) FROM devices")
    total_paired = c.fetchone()[0]
    conn.close()

    return web.json_response({
        **GATEWAY_STATE,
        "server_setup": server_cfg,
        "live_clients": live_stats["connections"],
        "active_clients_count": live_stats["active_count"],
        "total_paired_count": total_paired,
    })


async def api_save_server_setup(request):
    data = await request.json()
    save_server_config(data)
    return web.json_response({"success": True, "message": "Đã lưu cấu hình dịch vụ máy chủ thành công."})


async def api_toggle_gateway(request):
    data = await request.json()
    action = data.get("action")
    domain = data.get("custom_domain", "").strip()

    if action == "start":
        activate_quick_tunnel_link()
        try:
            tunnel_res = await setup_tunnel(8001, domain=domain)
            GATEWAY_STATE["server_running"] = True
            GATEWAY_STATE["cf_domain"] = domain
            GATEWAY_STATE["portal_web_url"] = tunnel_res["public_url"]
            GATEWAY_STATE["wss_url"] = tunnel_res["wss_url"]
            GATEWAY_STATE["ota_url"] = tunnel_res["ota_url"]
            return web.json_response({"success": True, "state": GATEWAY_STATE})
        except Exception as e:
            GATEWAY_STATE["server_running"] = False
            logger.error(f"Lỗi khởi chạy Cloudflare Tunnel: {e}")
            return web.json_response({"success": False, "message": f"Không thể khởi chạy Cloudflare Tunnel: {str(e)}"})
    else:
        GATEWAY_STATE["server_running"] = False
        stop_tunnel()
        GATEWAY_STATE["portal_web_url"] = ""
        GATEWAY_STATE["wss_url"] = ""
        GATEWAY_STATE["ota_url"] = ""
        return web.json_response({"success": True, "state": GATEWAY_STATE})


# ── GIAO DIỆN APP SERVER (TECHNICAL CONSOLE) ───────────────────────

HTML_GATEWAY_APP = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Voice Server — Host Console</title>
    <style>
        :root {
            --bg: #090d16;
            --panel: #111827;
            --panel-border: #1f293d;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #10b981;
            --danger: #ef4444;
            --mono: "JetBrains Mono", "SF Mono", Consolas, Menlo, monospace;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
        body { background: var(--bg); color: var(--text-main); min-height: 100vh; padding: 24px; }
        .wrapper { max-width: 1100px; margin: 0 auto; }

        /* Header */
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--panel-border); padding-bottom: 16px; margin-bottom: 24px; }
        .brand { display: flex; align-items: center; gap: 12px; }
        .brand-title { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }
        .brand-subtitle { font-size: 13px; color: var(--text-muted); margin-top: 2px; }
        .status-badge { font-size: 12px; font-weight: 600; padding: 6px 14px; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.5px; }
        .status-badge.online { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
        .status-badge.offline { background: rgba(148, 163, 184, 0.15); color: var(--text-muted); border: 1px solid rgba(148, 163, 184, 0.3); }

        /* Grid */
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
        @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }

        /* Card */
        .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 20px; }
        .card-header { font-size: 15px; font-weight: 600; border-bottom: 1px solid var(--panel-border); padding-bottom: 12px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
        
        /* Form */
        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 6px; }
        input[type="text"], input[type="password"], select, textarea {
            width: 100%; padding: 10px 12px; background: #0b1120; border: 1px solid var(--panel-border); border-radius: 8px; color: var(--text-main); font-size: 13px; outline: none; transition: border-color 0.15s;
        }
        input:focus, select:focus, textarea:focus { border-color: var(--accent); }
        .mono-input { font-family: var(--mono); font-size: 12px; }
        
        .checkbox-group { background: #0b1120; border: 1px solid var(--panel-border); border-radius: 8px; padding: 10px 14px; }
        .checkbox-item { display: flex; align-items: center; gap: 10px; font-size: 13px; margin: 6px 0; cursor: pointer; color: var(--text-main); }
        .checkbox-item input { cursor: pointer; }

        /* Buttons */
        .btn { padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; transition: 0.15s; }
        .btn-primary { background: var(--accent); color: white; width: 100%; }
        .btn-primary:hover { background: var(--accent-hover); }
        .btn-danger { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.3); width: 100%; }
        .btn-danger:hover { background: rgba(239, 68, 68, 0.25); }
        .btn-secondary { background: #1f293d; color: var(--text-main); }
        .btn-secondary:hover { background: #2d3b55; }
        .btn-sm { padding: 6px 12px; font-size: 12px; }

        /* Endpoints Box */
        .endpoints-box { margin-top: 16px; background: #070a12; border: 1px solid #1e293b; border-radius: 8px; padding: 14px; }
        .endpoint-row { margin-bottom: 12px; }
        .endpoint-row:last-child { margin-bottom: 0; }
        .endpoint-title { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px; }
        .endpoint-value-wrap { display: flex; justify-content: space-between; align-items: center; gap: 8px; background: #0f172a; padding: 8px 12px; border-radius: 6px; border: 1px solid #1e293b; }
        .endpoint-value { font-family: var(--mono); font-size: 12px; color: #38bdf8; word-break: break-all; }

        /* Stats */
        .stats-bar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 20px; }
        .stat-box { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 10px; padding: 14px; text-align: center; }
        .stat-val { font-size: 24px; font-weight: 700; font-family: var(--mono); color: var(--accent); }
        .stat-lbl { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

        /* Client Table */
        table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }
        th { text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        td { padding: 10px 12px; border-bottom: 1px solid var(--panel-border); }
        .empty-table { padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px; }
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="header">
            <div class="brand">
                <div>
                    <div class="brand-title">Ni-Oh Voice Server</div>
                    <div class="brand-subtitle">Máy chủ giao thức thoại Xiaozhi & Cổng điều khiển hạ tầng</div>
                </div>
            </div>
            <div id="gatewayBadge" class="status-badge offline">GATEWAY: ĐÃ TẮT</div>
        </div>

        <div class="stats-bar">
            <div class="stat-box">
                <div class="stat-val" id="statActiveCount">0</div>
                <div class="stat-lbl">Mạch đang kết nối trực tiếp (Live WebSocket)</div>
            </div>
            <div class="stat-box">
                <div class="stat-val" id="statPairedCount">0</div>
                <div class="stat-lbl">Tổng thiết bị đã ghép đôi trong cơ sở dữ liệu</div>
            </div>
            <div class="stat-box">
                <div class="stat-val" style="color: #10b981;">16 kHz / Opus</div>
                <div class="stat-lbl">Chuẩn âm thanh đàm thoại (Mono 60ms)</div>
            </div>
        </div>

        <div class="grid">
            <!-- CỘT 1: CẤU HÌNH AI & DỊCH VỤ -->
            <div class="card">
                <div class="card-header">
                    <span>1. Cấu Hình Dịch Vụ AI & Giọng Đọc</span>
                </div>

                <div class="form-group">
                    <label>Nhà Cung Cấp LLM (OpenAI-Compatible):</label>
                    <select id="cfgProvider" onchange="onProviderChange()">
                        <option value="deepseek">DeepSeek Official (api.deepseek.com)</option>
                        <option value="openrouter">OpenRouter (openrouter.ai/api/v1)</option>
                        <option value="openai">OpenAI Official (api.openai.com/v1)</option>
                        <option value="gemini">Google Gemini API (OpenAI-compatible)</option>
                        <option value="ollama">Ollama Localhost (127.0.0.1:11434/v1)</option>
                        <option value="custom">Tùy chỉnh Endpoint...</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>API Base URL:</label>
                    <input type="text" id="cfgBaseUrl" class="mono-input" placeholder="https://api.deepseek.com">
                </div>

                <div class="form-group">
                    <label>Server API Key:</label>
                    <input type="password" id="cfgApiKey" class="mono-input" placeholder="sk-...">
                </div>

                <div class="form-group">
                    <label>Mô Hình Ngôn Ngữ Mặc Định (Model ID):</label>
                    <input type="text" id="cfgModel" class="mono-input" placeholder="deepseek-chat" list="modelPresets">
                    <datalist id="modelPresets">
                        <option value="deepseek-chat">
                        <option value="deepseek-reasoner">
                        <option value="gpt-4o-mini">
                        <option value="gpt-4o">
                        <option value="gemini-2.0-flash">
                        <option value="qwen-plus">
                        <option value="claude-3-5-sonnet-20241022">
                        <option value="llama3.2">
                    </datalist>
                </div>

                <div class="form-group">
                    <label>Giọng Đọc TTS Mặc Định (Edge-TTS Neural):</label>
                    <select id="cfgVoice">
                        <option value="vi-VN-HoaiMyNeural">Hoài My (Tiếng Việt - Nữ)</option>
                        <option value="vi-VN-NamMinhNeural">Nam Minh (Tiếng Việt - Nam)</option>
                        <option value="en-US-JennyNeural">Jenny (English - Female)</option>
                        <option value="zh-CN-XiaoxiaoNeural">Xiaoxiao (Chinese - Female)</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Tốc Độ Đọc (Speech Rate):</label>
                    <select id="cfgRate">
                        <option value="-10%">-10% (Chậm vừa)</option>
                        <option value="+0%" selected>0% (Mặc định chuẩn)</option>
                        <option value="+10%">+10% (Nhanh vừa)</option>
                        <option value="+20%">+20% (Nhanh)</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Công Cụ Hệ Thống Tích Hợp:</label>
                    <div class="checkbox-group">
                        <label class="checkbox-item"><input type="checkbox" id="toolWeather" checked> Tra cứu thời tiết (Open-Meteo API)</label>
                        <label class="checkbox-item"><input type="checkbox" id="toolSearch" checked> Tìm kiếm thông tin web (DuckDuckGo API)</label>
                        <label class="checkbox-item"><input type="checkbox" id="toolPC" checked> Điều khiển máy tính chủ (PC Commands)</label>
                    </div>
                </div>

                <button class="btn btn-primary" onclick="saveServerSetup()">Lưu Cấu Hình Dịch Vụ</button>
            </div>

            <!-- CỘT 2: CLOUDFLARE GATEWAY & XUẤT ĐIỂM CUỐI -->
            <div class="card">
                <div class="card-header">
                    <span>2. Cổng Kết Nối Mạng (Cloudflare Anycast)</span>
                </div>

                <div class="form-group">
                    <label>Tên Miền Riêng (Tùy Chọn):</label>
                    <input type="text" id="customDomain" class="mono-input" placeholder="Bỏ trống để cấp link Cloudflare tự động">
                </div>

                <p style="font-size: 13px; color: var(--text-muted); line-height: 1.5; margin-bottom: 16px;">
                    Kích hoạt đường hầm bảo mật Cloudflare Anycast toàn cầu để tạo đường link công khai cho các mạch Xiaozhi kết nối từ xa qua Wi-Fi/4G và mở Web Console quản trị.
                </p>

                <button id="toggleBtn" class="btn btn-primary" onclick="toggleGateway()">Khởi Động Gateway Cloudflare</button>

                <div id="endpointsBox" class="endpoints-box" style="display: none;">
                    <div class="endpoint-row">
                        <div class="endpoint-title">Web Console Quản Lý (Dành cho người dùng):</div>
                        <div class="endpoint-value-wrap">
                            <span class="endpoint-value" id="urlWebPortal">https://...</span>
                            <div style="display: flex; gap: 4px;">
                                <button class="btn btn-secondary btn-sm" onclick="copyValue('urlWebPortal')">Copy</button>
                                <button class="btn btn-secondary btn-sm" onclick="openUrl('urlWebPortal')">Mở Web</button>
                            </div>
                        </div>
                    </div>

                    <div class="endpoint-row">
                        <div class="endpoint-title">Điểm Cuối WebSocket (Cho firmware Xiaozhi):</div>
                        <div class="endpoint-value-wrap">
                            <span class="endpoint-value" id="urlWebSocket">wss://.../xiaozhi/v1/</span>
                            <button class="btn btn-secondary btn-sm" onclick="copyValue('urlWebSocket')">Copy</button>
                        </div>
                    </div>

                    <div class="endpoint-row">
                        <div class="endpoint-title">Điểm Cuối Cập Nhật OTA Firmware:</div>
                        <div class="endpoint-value-wrap">
                            <span class="endpoint-value" id="urlOTA">https://.../xiaozhi/ota/</span>
                            <button class="btn btn-secondary btn-sm" onclick="copyValue('urlOTA')">Copy</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- BẢNG GIÁM SÁT KẾT NỐI REAL-TIME -->
        <div class="card">
            <div class="card-header">
                <span>3. Danh Sách Mạch ESP32 Đang Kết Nối Thời Gian Thực</span>
                <button class="btn btn-secondary btn-sm" onclick="loadStatus()">Làm mới</button>
            </div>

            <div id="clientsTableContainer">
                <div class="empty-table">Không có thiết bị ESP32 nào đang kết nối tới cổng WebSocket.</div>
            </div>
        </div>
    </div>

    <script>
        const PROVIDER_URLS = {
            'deepseek': 'https://api.deepseek.com',
            'openrouter': 'https://openrouter.ai/api/v1',
            'openai': 'https://api.openai.com/v1',
            'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai/',
            'ollama': 'http://localhost:11434/v1',
            'custom': ''
        };

        function onProviderChange() {
            const p = document.getElementById('cfgProvider').value;
            const targetUrl = PROVIDER_URLS[p];
            if (targetUrl) {
                document.getElementById('cfgBaseUrl').value = targetUrl;
            }
        }

        async function loadStatus() {
            try {
                const res = await fetch('/api/gateway/status');
                const data = await res.json();

                const isRun = data.server_running;
                const badge = document.getElementById('gatewayBadge');
                const btn = document.getElementById('toggleBtn');
                const box = document.getElementById('endpointsBox');

                if (isRun) {
                    badge.innerText = 'GATEWAY: HOẠT ĐỘNG (ONLINE)';
                    badge.className = 'status-badge online';
                    btn.innerText = 'Dừng Gateway Cloudflare';
                    btn.className = 'btn btn-danger';
                    box.style.display = 'block';
                    document.getElementById('urlWebPortal').innerText = data.portal_web_url;
                    document.getElementById('urlWebSocket').innerText = data.wss_url;
                    document.getElementById('urlOTA').innerText = data.ota_url;
                } else {
                    badge.innerText = 'GATEWAY: ĐÃ TẮT';
                    badge.className = 'status-badge offline';
                    btn.innerText = 'Khởi Động Gateway Cloudflare';
                    btn.className = 'btn btn-primary';
                    box.style.display = 'none';
                }

                // Cập nhật thống kê
                document.getElementById('statActiveCount').innerText = data.active_clients_count || 0;
                document.getElementById('statPairedCount').innerText = data.total_paired_count || 0;

                // Cập nhật bảng kết nối thực tế
                renderClientsTable(data.live_clients || []);

                // Cập nhật form cài đặt
                if (data.server_setup) {
                    const s = data.server_setup;
                    if (s.provider) document.getElementById('cfgProvider').value = s.provider;
                    if (s.base_url) document.getElementById('cfgBaseUrl').value = s.base_url;
                    if (s.api_key) document.getElementById('cfgApiKey').value = s.api_key;
                    if (s.model) document.getElementById('cfgModel').value = s.model;
                    if (s.voice) document.getElementById('cfgVoice').value = s.voice;
                    if (s.speech_rate) document.getElementById('cfgRate').value = s.speech_rate;
                    document.getElementById('toolWeather').checked = s.enable_weather;
                    document.getElementById('toolSearch').checked = s.enable_search;
                    document.getElementById('toolPC').checked = s.enable_pc_control;
                }
            } catch (e) {
                console.error("Lỗi lấy trạng thái:", e);
            }
        }

        function renderClientsTable(clients) {
            const container = document.getElementById('clientsTableContainer');
            if (!clients || clients.length === 0) {
                container.innerHTML = '<div class="empty-table">Không có thiết bị ESP32 nào đang kết nối tới cổng WebSocket.</div>';
                return;
            }

            let html = `<table>
                <thead>
                    <tr>
                        <th>Mã Thiết Bị</th>
                        <th>Địa Chỉ IP</th>
                        <th>Thời Điểm Kết Nối</th>
                        <th>Thời Lượng</th>
                        <th>Gói Tin (RX / TX / Audio)</th>
                        <th>Trạng Thái</th>
                    </tr>
                </thead>
                <tbody>`;

            clients.forEach(c => {
                const duration = c.duration_seconds < 60 ? `${c.duration_seconds}s` : `${Math.floor(c.duration_seconds/60)}m ${c.duration_seconds%60}s`;
                html += `<tr>
                    <td style="font-family: var(--mono); font-weight: 600;">${c.device_id}</td>
                    <td style="font-family: var(--mono); color: var(--text-muted);">${c.remote_ip}</td>
                    <td>${c.connected_at}</td>
                    <td style="font-family: var(--mono);">${duration}</td>
                    <td style="font-family: var(--mono); font-size: 12px;">${c.rx_packets} / ${c.tx_packets} / ${c.audio_frames}</td>
                    <td><span style="color: #10b981; font-weight: 600;">${c.status}</span></td>
                </tr>`;
            });

            html += `</tbody></table>`;
            container.innerHTML = html;
        }

        async function saveServerSetup() {
            const payload = {
                provider: document.getElementById('cfgProvider').value,
                base_url: document.getElementById('cfgBaseUrl').value.trim(),
                api_key: document.getElementById('cfgApiKey').value.trim(),
                model: document.getElementById('cfgModel').value.trim() || 'deepseek-chat',
                voice: document.getElementById('cfgVoice').value,
                speech_rate: document.getElementById('cfgRate').value,
                enable_weather: document.getElementById('toolWeather').checked ? "1" : "0",
                enable_search: document.getElementById('toolSearch').checked ? "1" : "0",
                enable_pc_control: document.getElementById('toolPC').checked ? "1" : "0"
            };

            const res = await fetch('/api/gateway/save-setup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            alert(data.message);
        }

        async function toggleGateway() {
            const isRunning = document.getElementById('gatewayBadge').innerText.includes("ONLINE");
            const action = isRunning ? "stop" : "start";
            const domain = document.getElementById('customDomain').value.trim();

            const btn = document.getElementById('toggleBtn');
            btn.innerText = "Đang kết nối hạ tầng Cloudflare...";
            btn.disabled = true;

            try {
                const res = await fetch('/api/gateway/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ action: action, custom_domain: domain })
                });
                const data = await res.json();
                if (!data.success) {
                    alert(data.message);
                }
            } catch (e) {
                alert("Lỗi khi kết nối gateway: " + e);
            } finally {
                btn.disabled = false;
                loadStatus();
            }
        }

        function copyValue(elementId) {
            const txt = document.getElementById(elementId).innerText;
            navigator.clipboard.writeText(txt);
            alert("Đã sao chép: " + txt);
        }

        function openUrl(elementId) {
            const url = document.getElementById(elementId).innerText;
            window.open(url, '_blank');
        }

        loadStatus();
        setInterval(loadStatus, 4000);
    </script>
</body>
</html>
"""
