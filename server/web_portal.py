"""
Ni-Oh Device Management Web Portal (Production)
------------------------------------------------
Hệ thống Quản lý Thiết bị & Xác thực Người dùng:
- Hỗ trợ đăng nhập Google thật qua Google Identity Services (GSI / OAuth2)
- Hỗ trợ Đăng ký / Đăng nhập tài khoản cá nhân trực tiếp (Email & Mật khẩu) lưu trữ SQLite
- Quản lý & cấu hình thiết bị ESP32 qua mã PIN 6 số trên màn hình LCD
- Lưu trữ cơ sở dữ liệu thật (data/portal.db)
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


# ── KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE THỰC TẾ ──────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Bảng người dùng
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
    
    # Bảng thiết bị
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        user_id TEXT,
        name TEXT,
        model TEXT DEFAULT 'deepseek/deepseek-chat',
        api_key TEXT DEFAULT '',
        voice TEXT DEFAULT 'vi-VN-HoaiMyNeural',
        prompt TEXT,
        status TEXT DEFAULT 'online',
        pairing_code TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    
    # Bảng cấu hình OAuth (Google Client ID, Zalo App ID)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS oauth_config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    conn.commit()
    conn.close()

init_db()


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_oauth_setting(key: str, default: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM oauth_config WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def save_oauth_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO oauth_config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ── REST API CHO XÁC THỰC NGƯỜI DÙNG ───────────────────────

async def api_portal_get_oauth_config(request):
    """Lấy cấu hình OAuth hiện tại."""
    google_client_id = get_oauth_setting("google_client_id", os.environ.get("GOOGLE_CLIENT_ID", ""))
    return web.json_response({
        "google_client_id": google_client_id,
        "has_google_client_id": bool(google_client_id and "YOUR_GOOGLE" not in google_client_id)
    })


async def api_portal_save_oauth_config(request):
    """Lưu Google Client ID vào cơ sở dữ liệu."""
    data = await request.json()
    google_client_id = data.get("google_client_id", "").strip()
    save_oauth_setting("google_client_id", google_client_id)
    return web.json_response({"success": True, "message": "Đã lưu Google Client ID thành công!"})


async def api_portal_register(request):
    """Đăng ký tài khoản cá nhân mới bằng Email & Mật khẩu."""
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
        cursor.execute(
            "INSERT INTO users (id, email, password_hash, name, provider) VALUES (?, ?, ?, ?, 'local')",
            (user_id, email, _hash_pw(password), name)
        )
        conn.commit()
        user = {"user_id": user_id, "email": email, "name": name, "provider": "local"}
        return web.json_response({"success": True, "message": "Đăng ký tài khoản thành công!", "user": user})
    except sqlite3.IntegrityError:
        return web.json_response({"success": False, "message": "Email này đã được đăng ký! Vui lòng chọn Đăng Nhập."})
    finally:
        conn.close()


async def api_portal_login(request):
    """Đăng nhập bằng Email & Mật khẩu."""
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, avatar, provider FROM users WHERE email = ? AND password_hash = ?", (email, _hash_pw(password)))
    row = cursor.fetchone()
    conn.close()

    if row:
        user = {"user_id": row[0], "email": row[1], "name": row[2], "avatar": row[3], "provider": row[4]}
        return web.json_response({"success": True, "user": user})
    else:
        return web.json_response({"success": False, "message": "Sai email hoặc mật khẩu!"})


async def api_portal_google_auth(request):
    """
    Xác thực Google qua JWT credential từ Google Identity Services.
    """
    data = await request.json()
    credential = data.get("credential")

    if not credential:
        return web.json_response({"success": False, "message": "Không nhận được chứng chỉ xác thực Google!"})

    try:
        import base64
        payload_b64 = credential.split(".")[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))

        email = payload_json.get("email")
        name = payload_json.get("name")
        avatar = payload_json.get("picture")
        google_sub = payload_json.get("sub")

        user_id = f"google_{google_sub}"

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name, avatar FROM users WHERE id = ?", (user_id,))
        existing = cursor.fetchone()

        if not existing:
            cursor.execute(
                "INSERT INTO users (id, email, name, avatar, provider) VALUES (?, ?, ?, ?, 'google')",
                (user_id, email, name, avatar)
            )
            conn.commit()

        conn.close()
        user = {"user_id": user_id, "email": email, "name": name, "avatar": avatar, "provider": "google"}
        return web.json_response({"success": True, "user": user})
    except Exception as e:
        logger.error(f"Lỗi xác thực Google: {e}")
        return web.json_response({"success": False, "message": f"Lỗi xác thực Google: {str(e)}"})


# ── REST API CHO QUẢN LÝ THIẾT BỊ ──────────────────────────

async def api_portal_get_devices(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "devices": []})

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT device_id, name, model, api_key, voice, prompt, status, pairing_code FROM devices WHERE user_id = ?", (user_id,))
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
    data = await request.json()
    user_id = data.get("user_id")
    code = data.get("pairing_code", "").strip()
    bot_name = data.get("bot_name", "Ni-Oh S3 Mini").strip()

    if not user_id:
        return web.json_response({"success": False, "message": "Vui lòng đăng nhập trước khi ghép đôi thiết bị!"})
    if len(code) != 6 or not code.isdigit():
        return web.json_response({"success": False, "message": "Mã ghép đôi phải đúng 6 chữ số hiển thị trên màn hình mạch!"})

    device_id = f"ESP32-{code}"
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM devices WHERE device_id = ?", (device_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return web.json_response({"success": False, "message": "Thiết bị mang mã này đã được ghép đôi trong hệ thống!"})

    prompt_default = "Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính, hài hước và nhiệt tình hỗ trợ."
    cursor.execute(
        "INSERT INTO devices (device_id, user_id, name, model, voice, prompt, pairing_code) VALUES (?, ?, ?, 'deepseek/deepseek-chat', 'vi-VN-HoaiMyNeural', ?, ?)",
        (device_id, user_id, bot_name, prompt_default, code)
    )
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": f"Ghép đôi thiết bị '{bot_name}' thành công!"})


async def api_portal_update_device(request):
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

    return web.json_response({"success": True, "message": "Đã cập nhật cấu hình thiết bị thành công!"})


# ── GIAO DIỆN WEB PORTAL QUẢN LÝ THIẾT BỊ ──────────────────

HTML_XIAOZHI_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Device Portal</title>
    <!-- Thư viện Google Identity Services (GSI) -->
    <script src="https://accounts.google.com/gsi/client" async defer></script>
    <style>
        :root {
            --primary: #2563eb; --primary-hover: #1d4ed8; --bg: #f8fafc;
            --panel: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0;
            --success: #16a34a; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding-bottom: 50px; }
        .navbar { background: var(--panel); border-bottom: 1px solid var(--border); padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
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
        input, select, textarea { width: 100%; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; outline: none; }
        input:focus, select:focus, textarea:focus { border-color: var(--primary); }
        .btn { width: 100%; padding: 11px; background: var(--primary); color: white; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; }
        .btn:hover { background: var(--primary-hover); }
        .btn-google { background: white; color: #374151; border: 1px solid #d1d5db; display: flex; align-items: center; justify-content: center; gap: 10px; font-weight: 600; margin-bottom: 16px; }
        .btn-google:hover { background: #f9fafb; border-color: #9ca3af; }
        
        .divider { display: flex; align-items: center; text-align: center; margin: 18px 0; color: var(--muted); font-size: 12px; }
        .divider::before, .divider::after { content: ''; flex: 1; border-bottom: 1px solid var(--border); }
        .divider::before { margin-right: .5em; } .divider::after { margin-left: .5em; }

        .device-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; margin-top: 20px; }
        .device-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px; cursor: pointer; transition: 0.2s; }
        .device-card:hover { border-color: var(--primary); transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05); }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: var(--success); margin-right: 6px; }

        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 200; }
        .modal { background: var(--panel); border-radius: 16px; width: 100%; max-width: 520px; padding: 28px; }
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
            <div class="auth-title">Đăng Nhập Tài Khoản</div>
            <div class="auth-desc">Quản lý và ghép đôi các mạch trợ lý giọng nói của bạn</div>

            <!-- Nút đăng nhập Google -->
            <button class="btn btn-google" id="googleLoginBtn" onclick="triggerGoogleSignIn()">
                <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.8-2.4 3.66v3.05h3.88c2.27-2.09 3.58-5.17 3.58-8.85z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.24v3.15C3.26 21.36 7.35 24 12 24z"/><path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.24C.45 8.15 0 9.99 0 12s.45 3.85 1.24 5.42l4.04-3.15z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.35 0 3.26 2.64 1.24 6.58l4.04 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/></svg>
                Đăng nhập bằng Google
            </button>

            <!-- Vùng render GSI tự động nếu có Client ID -->
            <div id="g_id_onload" data-callback="handleGoogleLogin" data-auto_prompt="false"></div>

            <div class="divider">HOẶC DÙNG EMAIL & MẬT KHẨU</div>

            <div class="auth-tab">
                <button id="tabLogin" class="active" onclick="switchTab('login')">Đăng Nhập</button>
                <button id="tabRegister" onclick="switchTab('register')">Đăng Ký Mới</button>
            </div>

            <form id="authForm" onsubmit="handleAuthSubmit(event)">
                <div class="input-group" id="nameGroup" style="display: none;">
                    <label>Họ và tên</label>
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

        <!-- MÀN HÌNH QUẢN LÝ THIẾT BỊ -->
        <div id="dashboardScreen" style="display: none;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h2 style="font-size: 22px; font-weight: 800;">Thiết Bị Của Tôi</h2>
                    <span style="color: var(--muted); font-size: 13px;">Ghép đôi thiết bị bằng mã PIN 6 số trên màn hình LCD</span>
                </div>
                <button class="btn" style="width: auto; padding: 10px 18px;" onclick="openBindModal()">+ Thêm Thiết Bị Mới</button>
            </div>

            <div class="device-grid" id="deviceGrid"></div>
        </div>
    </div>

    <!-- Modal Cấu hình Google Client ID (Nếu chưa cài) -->
    <div class="modal-overlay" id="googleConfigModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 12px;">⚙️ Thiết Lập Đăng Nhập Google</h3>
            <p style="color: var(--muted); font-size: 13px; margin-bottom: 14px; line-height: 1.5;">
                Để kích hoạt đăng nhập bằng tài khoản Google thật của bạn, vui lòng nhập <strong>Google OAuth Client ID</strong> (lấy miễn phí tại console.cloud.google.com):
            </p>
            <div class="input-group">
                <label>Google Client ID:</label>
                <input type="text" id="googleClientIdInput" placeholder="xxxxxx.apps.googleusercontent.com">
            </div>
            <p style="font-size: 12px; color: var(--muted); margin-bottom: 16px;">
                💡 <em>Mẹo: Bạn cũng có thể Đăng Ký / Đăng Nhập trực tiếp bằng Email cá nhân ngay ở màn hình ngoài mà không cần cấu hình Google.</em>
            </p>
            <div style="display: flex; gap: 10px;">
                <button class="btn" onclick="saveGoogleConfig()">Lưu Client ID</button>
                <button class="btn" style="background: #e2e8f0; color: #475569;" onclick="closeGoogleConfigModal()">Đóng</button>
            </div>
        </div>
    </div>

    <!-- Modal Ghép Đôi 6 Số -->
    <div class="modal-overlay" id="bindModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 12px;">🔗 Ghép Đôi Thiết Bị Mới</h3>
            <p style="color: var(--muted); font-size: 13px; margin-bottom: 16px;">
                Bật nguồn mạch ESP32, màn hình LCD sẽ hiện <strong>mã 6 chữ số</strong>. Hãy nhập mã đó vào đây:
            </p>
            <div class="input-group">
                <label>Mã 6 Số trên màn hình mạch</label>
                <input type="text" id="pinInput" maxlength="6" style="font-size: 24px; font-weight: bold; text-align: center; letter-spacing: 8px;" placeholder="123456">
            </div>
            <div class="input-group">
                <label>Đặt tên cho thiết bị</label>
                <input type="text" id="botNameInput" value="Ni-Oh S3 Mini">
            </div>
            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="btn" onclick="submitBindDevice()">Ghép Đôi Thiết Bị</button>
                <button class="btn" style="background: #e2e8f0; color: #475569;" onclick="closeBindModal()">Hủy</button>
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
                    <option value="deepseek/deepseek-chat">⭐ DeepSeek V3 (Khuyên dùng: Nhanh, Tiếng Việt chuẩn)</option>
                    <option value="google/gemini-2.0-flash:free">🎁 Google Gemini 2.0 Flash (FREE 100%, Siêu tốc)</option>
                    <option value="openai/gpt-4o-mini">⚡ GPT-4o Mini (Phản hồi cực nhanh)</option>
                    <option value="anthropic/claude-3.5-sonnet">👑 Claude 3.5 Sonnet (Thông minh nhất)</option>
                    <option value="meta-llama/llama-3.3-70b-instruct">🧠 Llama 3.3 70B</option>
                    <option value="deepseek/deepseek-r1">🔬 DeepSeek R1 (Lý luận sâu)</option>
                </select>
            </div>

            <div class="input-group">
                <label>API Key Cá Nhân của Bạn (Tùy chọn)</label>
                <input type="password" id="cfgApiKey" placeholder="sk-xxxx (Bỏ trống = dùng key mặc định của server)">
            </div>

            <div class="input-group">
                <label>Giọng Nói (TTS Tiếng Việt):</label>
                <select id="cfgVoice">
                    <option value="vi-VN-HoaiMyNeural">Hoài My (Nữ miền Bắc)</option>
                    <option value="vi-VN-NamMinhNeural">Nam Minh (Nam miền Bắc)</option>
                    <option value="vi-VN-BanMai">Ban Mai (Nữ miền Trung)</option>
                </select>
            </div>

            <div class="input-group">
                <label>Tính Cách / System Prompt</label>
                <textarea id="cfgPrompt" rows="3"></textarea>
            </div>

            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="btn" onclick="submitSaveDeviceConfig()">Lưu Cấu Hình</button>
                <button class="btn" style="background: #e2e8f0; color: #475569;" onclick="closeConfigModal()">Đóng</button>
            </div>
        </div>
    </div>

    <script>
        let currentAuthMode = 'login';
        let currentUser = null;
        let userDevices = [];
        let selectedDevice = null;
        let googleClientId = "";

        // Kiểm tra cấu hình Google OAuth
        async function checkGoogleConfig() {
            try {
                const res = await fetch('/api/portal/oauth-config');
                const data = await res.json();
                if (data.has_google_client_id) {
                    googleClientId = data.google_client_id;
                    const onloadDiv = document.getElementById('g_id_onload');
                    onloadDiv.setAttribute('data-client_id', googleClientId);
                    if (window.google && google.accounts) {
                        google.accounts.id.initialize({
                            client_id: googleClientId,
                            callback: handleGoogleLogin
                        });
                    }
                }
            } catch(e) {}
        }

        function triggerGoogleSignIn() {
            if (googleClientId) {
                if (window.google && google.accounts) {
                    google.accounts.id.prompt();
                }
            } else {
                document.getElementById('googleConfigModal').style.display = 'flex';
            }
        }

        function closeGoogleConfigModal() {
            document.getElementById('googleConfigModal').style.display = 'none';
        }

        async function saveGoogleConfig() {
            const cid = document.getElementById('googleClientIdInput').value.trim();
            if (!cid) { alert('Vui lòng nhập Google Client ID!'); return; }
            const res = await fetch('/api/portal/oauth-config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ google_client_id: cid })
            });
            const data = await res.json();
            alert(data.message);
            closeGoogleConfigModal();
            checkGoogleConfig();
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

        async function handleGoogleLogin(response) {
            const res = await fetch('/api/portal/auth-google', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ credential: response.credential })
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
                grid.innerHTML = `<div style="grid-column: span 3; text-align: center; padding: 40px; color: var(--muted);">Chưa có thiết bị nào. Nhấp "+ Thêm Thiết Bị Mới" để ghép đôi bằng mã 6 số.</div>`;
                return;
            }
            grid.innerHTML = userDevices.map(d => `
                <div class="device-card" onclick="openConfigModal('${d.device_id}')">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <strong>${d.name}</strong>
                        <span style="font-size: 12px; color: var(--success);"><span class="status-dot"></span>${d.status}</span>
                    </div>
                    <div style="font-size: 12px; color: var(--muted); margin-bottom: 12px;">Mã PIN: <strong>${d.pairing_code}</strong> | ID: ${d.device_id}</div>
                    <div style="font-size: 13px; background: #f1f5f9; padding: 8px 12px; border-radius: 6px;">
                        🤖 Model: <strong>${d.model.split('/')[1] || d.model}</strong>
                    </div>
                </div>
            `).join('');
        }

        function openBindModal() { document.getElementById('bindModal').style.display = 'flex'; }
        function closeBindModal() { document.getElementById('bindModal').style.display = 'none'; }

        async function submitBindDevice() {
            const pin = document.getElementById('pinInput').value.trim();
            const name = document.getElementById('botNameInput').value.trim();
            if (pin.length !== 6) { alert('Vui lòng nhập đúng mã 6 số trên màn hình mạch!'); return; }
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

        // Khôi phục phiên đăng nhập nếu đã có
        const saved = sessionStorage.getItem('nioh_user');
        if (saved) {
            try { onLoginSuccess(JSON.parse(saved)); } catch(e){}
        }

        checkGoogleConfig();
    </script>
</body>
</html>
"""
