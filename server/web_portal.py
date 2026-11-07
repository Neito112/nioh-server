"""
Ni-Oh Device Management Web Portal (Production)
------------------------------------------------
Hệ thống Quản lý Thiết bị & Xác thực Người dùng:
- Thiết kế chuẩn mực, chuyên nghiệp, hiện đại (tương tự xiaozhi.me)
- Xác thực người dùng thực tế qua cơ sở dữ liệu SQLite (data/portal.db)
- Quản lý danh sách thiết bị, trạng thái kết nối thời gian thực (Online / Offline)
- Ghép đôi mạch ESP32 bằng MÃ PIN 6 SỐ hiển thị trên màn hình bo mạch
- Cấu hình từng thiết bị: Mô hình AI (DeepSeek, Gemini...), API Key, Giọng nói TTS, System Prompt
- Bảng thông số kết nối trực tiếp cho mạch ESP32 (WSS & OTA Endpoint)
"""

import os
import sys
import json
import sqlite3
import hashlib
import logging
from aiohttp import web

logger = logging.getLogger("nioh.web_portal")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "portal.db")


# ── KHỞI TẠO DATABASE SQLITE THỰC TẾ ────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Bảng người dùng thực tế
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        password_hash TEXT,
        name TEXT,
        avatar TEXT,
        provider TEXT DEFAULT 'local',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Bảng thiết bị ghép đôi
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        user_id TEXT,
        name TEXT,
        model TEXT DEFAULT 'deepseek/deepseek-chat',
        api_key TEXT DEFAULT '',
        voice TEXT DEFAULT 'vi-VN-HoaiMyNeural',
        prompt TEXT,
        status TEXT DEFAULT 'offline',
        pairing_code TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    
    conn.commit()
    conn.close()

init_db()


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ── REST API XÁC THỰC NGƯỜI DÙNG THỰC TẾ ───────────────────

async def api_portal_register(request):
    """Đăng ký tài khoản người dùng mới vào database."""
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip() or email.split("@")[0]

    if not email or "@" not in email:
        return web.json_response({"success": False, "message": "Vui lòng nhập Email hợp lệ!"})
    if len(password) < 6:
        return web.json_response({"success": False, "message": "Mật khẩu phải từ 6 ký tự trở lên!"})

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        user_id = f"usr_{hashlib.md5(email.encode()).hexdigest()[:12]}"
        avatar = f"https://ui-avatars.com/api/?name={name}&background=2563eb&color=fff"
        cursor.execute(
            "INSERT INTO users (id, email, password_hash, name, avatar, provider) VALUES (?, ?, ?, ?, ?, 'local')",
            (user_id, email, _hash_pw(password), name, avatar)
        )
        conn.commit()
        user = {"user_id": user_id, "email": email, "name": name, "avatar": avatar}
        return web.json_response({"success": True, "message": "Đăng ký tài khoản thành công!", "user": user})
    except sqlite3.IntegrityError:
        return web.json_response({"success": False, "message": "Email này đã được sử dụng. Vui lòng chuyển sang tab Đăng Nhập!"})
    finally:
        conn.close()


async def api_portal_login(request):
    """Đăng nhập tài khoản bằng email và mật khẩu."""
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, email, name, avatar FROM users WHERE email = ? AND password_hash = ?",
        (email, _hash_pw(password))
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        user = {"user_id": row[0], "email": row[1], "name": row[2], "avatar": row[3]}
        return web.json_response({"success": True, "user": user})
    else:
        return web.json_response({"success": False, "message": "Sai email hoặc mật khẩu!"})


# ── REST API QUẢN LÝ THIẾT BỊ ──────────────────────────────

async def api_portal_get_devices(request):
    """Lấy danh sách thiết bị của tài khoản đang đăng nhập."""
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "devices": []})

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT device_id, name, model, api_key, voice, prompt, status, pairing_code FROM devices WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    devices = []
    for r in rows:
        devices.append({
            "device_id": r[0],
            "name": r[1],
            "model": r[2],
            "api_key": r[3],
            "voice": r[4],
            "prompt": r[5],
            "status": r[6],
            "pairing_code": r[7],
        })
    return web.json_response({"success": True, "devices": devices})


async def api_portal_bind_device(request):
    """Ghép đôi thiết bị bằng mã PIN 6 số hiển thị trên màn hình mạch."""
    data = await request.json()
    user_id = data.get("user_id")
    code = data.get("pairing_code", "").strip()
    bot_name = data.get("bot_name", "Ni-Oh S3 Bot").strip()

    if not user_id:
        return web.json_response({"success": False, "message": "Vui lòng đăng nhập trước khi ghép đôi thiết bị!"})
    if len(code) != 6 or not code.isdigit():
        return web.json_response({"success": False, "message": "Mã ghép đôi phải đúng 6 chữ số hiển thị trên màn hình mạch!"})

    device_id = f"ESP32-{code}"
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, name FROM devices WHERE device_id = ?", (device_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return web.json_response({"success": False, "message": f"Mạch mang mã '{code}' đã được ghép đôi trong hệ thống!"})

    prompt_default = "Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính, hài hước và nhiệt tình hỗ trợ."
    cursor.execute(
        "INSERT INTO devices (device_id, user_id, name, model, voice, prompt, pairing_code, status) VALUES (?, ?, ?, 'deepseek/deepseek-chat', 'vi-VN-HoaiMyNeural', ?, ?, 'offline')",
        (device_id, user_id, bot_name, prompt_default, code)
    )
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": f"Ghép đôi thiết bị '{bot_name}' thành công!"})


async def api_portal_update_device(request):
    """Cập nhật cài đặt riêng cho thiết bị."""
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE devices SET name = ?, model = ?, api_key = ?, voice = ?, prompt = ? WHERE device_id = ? AND user_id = ?",
        (data.get("name"), data.get("model"), data.get("api_key"), data.get("voice"), data.get("prompt"), device_id, user_id)
    )
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": "Đã lưu cài đặt cho thiết bị thành công!"})


async def api_portal_delete_device(request):
    """Hủy ghép đôi thiết bị."""
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM devices WHERE device_id = ? AND user_id = ?", (device_id, user_id))
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": "Đã hủy ghép đôi thiết bị khỏi tài khoản!"})


# ── GIAO DIỆN WEB PORTAL (HTML/CSS/JS) ──────────────────────

HTML_XIAOZHI_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Device Portal</title>
    <style>
        :root {
            --primary: #2563eb; --primary-hover: #1d4ed8; --bg: #f8fafc;
            --panel: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0;
            --success: #16a34a; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding-bottom: 60px; min-height: 100vh; }
        .navbar { background: var(--panel); border-bottom: 1px solid var(--border); padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
        .brand { font-size: 20px; font-weight: 800; color: var(--primary); display: flex; align-items: center; gap: 8px; }
        .container { max-width: 950px; margin: 30px auto; padding: 0 16px; }
        
        .auth-card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 36px; max-width: 440px; margin: 40px auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        .auth-title { font-size: 22px; font-weight: 800; margin-bottom: 8px; text-align: center; }
        .auth-desc { font-size: 13px; color: var(--muted); text-align: center; margin-bottom: 24px; }
        
        .auth-tab { display: flex; border-bottom: 2px solid var(--border); margin-bottom: 20px; }
        .auth-tab button { flex: 1; padding: 10px; background: none; border: none; font-weight: 700; cursor: pointer; color: var(--muted); font-size: 14px; }
        .auth-tab button.active { color: var(--primary); border-bottom: 2px solid var(--primary); margin-bottom: -2px; }
        
        .input-group { margin-bottom: 14px; }
        label { display: block; font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 6px; }
        input, select, textarea { width: 100%; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; outline: none; transition: 0.2s; }
        input:focus, select:focus, textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
        
        .btn { width: 100%; padding: 11px; background: var(--primary); color: white; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; transition: 0.2s; }
        .btn:hover { background: var(--primary-hover); }
        .btn-secondary { background: #f1f5f9; color: #334155; }
        .btn-secondary:hover { background: #e2e8f0; }

        .device-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 20px; margin-top: 20px; }
        .device-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px; cursor: pointer; transition: 0.2s; position: relative; }
        .device-card:hover { border-color: var(--primary); transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05); }
        
        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
        .dot-online { background: var(--success); box-shadow: 0 0 6px rgba(34,197,94,0.5); }
        .dot-offline { background: var(--muted); }
        
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 200; backdrop-filter: blur(2px); }
        .modal { background: var(--panel); border-radius: 16px; width: 100%; max-width: 520px; padding: 28px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); }
        
        .info-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; padding: 16px; margin-top: 24px; font-size: 13px; line-height: 1.6; }
        .endpoint-code { background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 6px; font-family: monospace; font-size: 12px; color: #0369a1; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="brand">
            <span>⚡ Ni-Oh Device Portal</span>
        </div>
        <div id="userNavbar" style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 13px; color: var(--muted);">Chưa đăng nhập</span>
        </div>
    </div>

    <div class="container">
        <!-- MÀN HÌNH ĐĂNG NHẬP / ĐĂNG KÝ -->
        <div id="authScreen" class="auth-card">
            <div class="auth-title">Cổng Quản Lý Thiết Bị</div>
            <div class="auth-desc">Đăng nhập tài khoản để quản lý và cấu hình robot giọng nói của bạn</div>

            <div class="auth-tab">
                <button id="tabLogin" class="active" onclick="switchTab('login')">Đăng Nhập</button>
                <button id="tabRegister" onclick="switchTab('register')">Đăng Ký Mới</button>
            </div>

            <form id="authForm" onsubmit="handleAuthSubmit(event)">
                <div class="input-group" id="nameGroup" style="display: none;">
                    <label>Họ và tên của bạn</label>
                    <input type="text" id="authName" placeholder="Nguyễn Văn A">
                </div>
                <div class="input-group">
                    <label>Email cá nhân</label>
                    <input type="email" id="authEmail" required placeholder="user@gmail.com">
                </div>
                <div class="input-group">
                    <label>Mật khẩu</label>
                    <input type="password" id="authPassword" required placeholder="••••••••">
                </div>
                <button type="submit" class="btn" id="submitBtn">Đăng Nhập Ngay</button>
            </form>
        </div>

        <!-- MÀN HÌNH QUẢN LÝ THIẾT BỊ (Sau khi đăng nhập) -->
        <div id="dashboardScreen" style="display: none;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <div>
                    <h2 style="font-size: 22px; font-weight: 800;">Thiết Bị Của Tôi</h2>
                    <span style="color: var(--muted); font-size: 13px;">Ghép đôi thiết bị bằng mã PIN 6 số trên màn hình mạch</span>
                </div>
                <button class="btn" style="width: auto; padding: 10px 20px;" onclick="openBindModal()">+ Thêm Thiết Bị Mới</button>
            </div>

            <div class="device-grid" id="deviceGrid"></div>

            <!-- Bảng thông số kết nối Endpoint cho mạch ESP32 -->
            <div class="info-box">
                <strong>📡 Thông Số Kết Nối Server Dành Cho Firmware ESP32:</strong><br>
                <div style="margin-top: 8px;">
                    • <strong>WebSocket Audio (WSS):</strong> <span class="endpoint-code" id="liveWssEndpoint">wss://.../xiaozhi/v1/</span><br>
                    • <strong>OTA Firmware Update:</strong> <span class="endpoint-code" id="liveOtaEndpoint">https://.../xiaozhi/ota/</span>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal Ghép Đôi 6 Số -->
    <div class="modal-overlay" id="bindModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 10px;">🔗 Ghép Đôi Thiết Bị Mới</h3>
            <p style="color: var(--muted); font-size: 13px; margin-bottom: 18px;">
                Bật nguồn mạch ESP32, màn hình LCD sẽ hiện <strong>mã 6 chữ số</strong>. Hãy nhập mã đó vào đây:
            </p>
            <div class="input-group">
                <label>Mã 6 Số trên màn hình mạch</label>
                <input type="text" id="pinInput" maxlength="6" style="font-size: 26px; font-weight: 800; text-align: center; letter-spacing: 8px;" placeholder="123456">
            </div>
            <div class="input-group">
                <label>Đặt tên cho thiết bị</label>
                <input type="text" id="botNameInput" value="Ni-Oh S3 Bot">
            </div>
            <div style="display: flex; gap: 10px; margin-top: 22px;">
                <button class="btn" onclick="submitBindDevice()">Ghép Đôi Thiết Bị</button>
                <button class="btn btn-secondary" onclick="closeBindModal()">Hủy</button>
            </div>
        </div>
    </div>

    <!-- Modal Cấu Hình Thiết Bị -->
    <div class="modal-overlay" id="configModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 16px;" id="configModalTitle">⚙️ Cấu Hình Thiết Bị</h3>
            
            <div class="input-group">
                <label>Tên Thiết Bị</label>
                <input type="text" id="cfgName">
            </div>

            <div class="input-group">
                <label>Mô Hình AI (Model):</label>
                <select id="cfgModel">
                    <option value="deepseek/deepseek-chat">⭐ DeepSeek V3 (Nhanh, Tiếng Việt chuẩn xác)</option>
                    <option value="google/gemini-2.0-flash:free">🎁 Google Gemini 2.0 Flash (FREE 100%, Siêu tốc)</option>
                    <option value="openai/gpt-4o-mini">⚡ GPT-4o Mini (Phản hồi cực nhanh)</option>
                    <option value="anthropic/claude-3.5-sonnet">👑 Claude 3.5 Sonnet (Thông minh nhất)</option>
                    <option value="meta-llama/llama-3.3-70b-instruct">🧠 Llama 3.3 70B</option>
                    <option value="deepseek/deepseek-r1">🔬 DeepSeek R1 (Lý luận sâu)</option>
                </select>
            </div>

            <div class="input-group">
                <label>API Key Cá Nhân Của Bạn (Tùy chọn)</label>
                <input type="password" id="cfgApiKey" placeholder="sk-xxxx (Bỏ trống = dùng key mặc định của server)">
            </div>

            <div class="input-group">
                <label>Giọng Nói Tiếng Việt (TTS Neural):</label>
                <select id="cfgVoice">
                    <option value="vi-VN-HoaiMyNeural">Hoài My (Nữ miền Bắc - Trong trẻo, tự nhiên)</option>
                    <option value="vi-VN-NamMinhNeural">Nam Minh (Nam miền Bắc - Trầm ấm, truyền cảm)</option>
                </select>
            </div>

            <div class="input-group">
                <label>Tính Cách / System Prompt</label>
                <textarea id="cfgPrompt" rows="3"></textarea>
            </div>

            <div style="display: flex; gap: 10px; margin-top: 22px;">
                <button class="btn" onclick="submitSaveDeviceConfig()">Lưu Cấu Hình</button>
                <button class="btn" style="background: #ef4444; color: white; width: auto; padding: 10px 16px;" onclick="submitDeleteDevice()">Hủy Ghép Đôi</button>
                <button class="btn btn-secondary" style="width: auto; padding: 10px 16px;" onclick="closeConfigModal()">Đóng</button>
            </div>
        </div>
    </div>

    <script>
        let currentAuthMode = 'login';
        let currentUser = null;
        let userDevices = [];
        let selectedDevice = null;

        function updateEndpointsDisplay() {
            const loc = window.location;
            const wssProto = (loc.protocol === 'https:') ? 'wss:' : 'ws:';
            document.getElementById('liveWssEndpoint').innerText = `${wssProto}//${loc.host}/xiaozhi/v1/`;
            document.getElementById('liveOtaEndpoint').innerText = `${loc.protocol}//${loc.host}/xiaozhi/ota/`;
        }

        function switchTab(mode) {
            currentAuthMode = mode;
            document.getElementById('tabLogin').className = (mode === 'login') ? 'active' : '';
            document.getElementById('tabRegister').className = (mode === 'register') ? 'active' : '';
            document.getElementById('nameGroup').style.display = (mode === 'register') ? 'block' : 'none';
            document.getElementById('submitBtn').innerText = (mode === 'login') ? 'Đăng Nhập Ngay' : 'Tạo Tài Khoản Mới';
        }

        async function handleAuthSubmit(e) {
            e.preventDefault();
            const email = document.getElementById('authEmail').value;
            const password = document.getElementById('authPassword').value;
            const name = document.getElementById('authName').value;

            const endpoint = (currentAuthMode === 'login') ? '/api/portal/login' : '/api/portal/register';
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ email, password, name })
            });
            const data = await res.json();
            if (data.success) {
                onLoginSuccess(data.user);
            } else {
                alert(data.message);
            }
        }

        function onLoginSuccess(user) {
            currentUser = user;
            sessionStorage.setItem('nioh_user', JSON.stringify(user));
            document.getElementById('authScreen').style.display = 'none';
            document.getElementById('dashboardScreen').style.display = 'block';

            document.getElementById('userNavbar').innerHTML = `
                <img src="${user.avatar || 'https://ui-avatars.com/api/?name=' + encodeURIComponent(user.name)}" style="width: 32px; height: 32px; border-radius: 50%;">
                <div style="font-size: 13px;"><strong>${user.name}</strong><br><small style="color: var(--muted);">${user.email}</small></div>
                <button onclick="logout()" style="background: none; border: 1px solid var(--border); padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 12px; margin-left: 8px;">Thoát</button>
            `;
            updateEndpointsDisplay();
            loadUserDevices();
        }

        function logout() {
            sessionStorage.removeItem('nioh_user');
            currentUser = null;
            location.reload();
        }

        async function loadUserDevices() {
            if (!currentUser) return;
            const res = await fetch(`/api/portal/devices?user_id=${currentUser.user_id}`);
            const data = await res.json();
            userDevices = data.devices || [];
            const grid = document.getElementById('deviceGrid');
            if (userDevices.length === 0) {
                grid.innerHTML = `<div style="grid-column: span 3; text-align: center; padding: 40px; color: var(--muted); border: 2px dashed var(--border); border-radius: 12px;">Bạn chưa ghép đôi thiết bị nào.<br>Hãy bấm <strong>"+ Thêm Thiết Bị Mới"</strong> để kết nối bằng mã 6 số hiển thị trên màn hình mạch ESP32.</div>`;
                return;
            }
            grid.innerHTML = userDevices.map(d => {
                const isOnline = (d.status === 'online');
                const dotClass = isOnline ? 'dot-online' : 'dot-offline';
                const statusText = isOnline ? 'Đang hoạt động (Online)' : 'Ngoại tuyến (Offline)';
                const statusColor = isOnline ? 'var(--success)' : 'var(--muted)';
                return `
                <div class="device-card" onclick="openConfigModal('${d.device_id}')">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <strong style="font-size: 15px;">${d.name}</strong>
                        <span style="font-size: 12px; color: ${statusColor}; font-weight: 600;"><span class="status-dot ${dotClass}"></span>${statusText}</span>
                    </div>
                    <div style="font-size: 12px; color: var(--muted); margin-bottom: 12px;">Mã PIN: <strong>${d.pairing_code}</strong> | ID: ${d.device_id}</div>
                    <div style="font-size: 13px; background: #f1f5f9; padding: 8px 12px; border-radius: 6px; display: flex; justify-content: space-between;">
                        <span>🤖 Model: <strong>${d.model.split('/')[1] || d.model}</strong></span>
                        <span style="color: var(--primary); font-size: 12px;">Cài đặt ⚙️</span>
                    </div>
                </div>
            `}).join('');
        }

        function openBindModal() { document.getElementById('bindModal').style.display = 'flex'; }
        function closeBindModal() { document.getElementById('bindModal').style.display = 'none'; }

        async function submitBindDevice() {
            const pin = document.getElementById('pinInput').value.trim();
            const name = document.getElementById('botNameInput').value.trim();
            if (pin.length !== 6) { alert('Vui lòng nhập đúng mã 6 số hiển thị trên màn hình mạch!'); return; }
            const res = await fetch('/api/portal/bind', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, pairing_code: pin, bot_name: name })
            });
            const data = await res.json();
            alert(data.message);
            if (data.success) {
                closeBindModal();
                loadUserDevices();
            }
        }

        function openConfigModal(deviceId) {
            selectedDevice = userDevices.find(d => d.device_id === deviceId);
            if (!selectedDevice) return;
            document.getElementById('configModalTitle').innerText = `⚙️ Cấu Hình: ${selectedDevice.name}`;
            document.getElementById('cfgName').value = selectedDevice.name;
            document.getElementById('cfgModel').value = selectedDevice.model;
            document.getElementById('cfgApiKey').value = selectedDevice.api_key || "";
            document.getElementById('cfgVoice').value = selectedDevice.voice || "vi-VN-HoaiMyNeural";
            document.getElementById('cfgPrompt').value = selectedDevice.prompt || "";
            document.getElementById('configModal').style.display = 'flex';
        }
        function closeConfigModal() { document.getElementById('configModal').style.display = 'none'; }

        async function submitSaveDeviceConfig() {
            if (!selectedDevice) return;
            const payload = {
                user_id: currentUser.user_id,
                device_id: selectedDevice.device_id,
                name: document.getElementById('cfgName').value,
                model: document.getElementById('cfgModel').value,
                api_key: document.getElementById('cfgApiKey').value,
                voice: document.getElementById('cfgVoice').value,
                prompt: document.getElementById('cfgPrompt').value,
            };
            const res = await fetch('/api/portal/update-device', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            alert(data.message);
            closeConfigModal();
            loadUserDevices();
        }

        async function submitDeleteDevice() {
            if (!selectedDevice) return;
            if (!confirm(`Bạn có chắc muốn hủy ghép đôi thiết bị "${selectedDevice.name}"?`)) return;
            const res = await fetch('/api/portal/delete-device', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, device_id: selectedDevice.device_id })
            });
            const data = await res.json();
            alert(data.message);
            closeConfigModal();
            loadUserDevices();
        }

        // Khôi phục phiên đăng nhập
        const saved = sessionStorage.getItem('nioh_user');
        if (saved) {
            try { onLoginSuccess(JSON.parse(saved)); } catch(e){}
        }
    </script>
</body>
</html>
"""
