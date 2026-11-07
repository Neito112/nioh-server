"""
Ni-Oh Voice Portal (Web Server Console)
---------------------------------------
Thành phần 2: Giao diện Web quản trị dành cho người dùng:
- Truy cập từ xa thông qua đường link Cloudflare được xuất ra từ App Server
- Đăng nhập & Đăng ký tài khoản người dùng
- Quản lý Trợ lý AI (Agents): Cấu hình nhân vật, model LLM, API Key riêng, giọng đọc TTS
- Quản lý Thiết bị (Devices): Ghép đôi thiết bị bằng mã PIN 6 số, gán Agent cho từng mạch
- Theo dõi trạng thái hoạt động thực tế của từng thiết bị
"""

import os
import sys
import json
import sqlite3
import hashlib
import uuid
import logging
from aiohttp import web

logger = logging.getLogger("nioh.web_portal")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")

from server.voice_engine import ACTIVE_CONNECTIONS, get_server_runtime_config


# ── KHỞI TẠO CƠ SỞ DỮ LIỆU ĐẦY ĐỦ ─────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        password_hash TEXT,
        name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        name TEXT,
        model TEXT DEFAULT 'deepseek-chat',
        api_key TEXT DEFAULT '',
        voice TEXT DEFAULT 'vi-VN-HoaiMyNeural',
        prompt TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        user_id TEXT,
        agent_id TEXT,
        name TEXT,
        pairing_code TEXT,
        status TEXT DEFAULT 'offline',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(agent_id) REFERENCES agents(id)
    )
    """)
    conn.commit()
    conn.close()

init_db()


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ── REST API XÁC THỰC NGƯỜI DÙNG ───────────────────────────────────

async def api_portal_register(request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip() or email.split("@")[0]

    if not email or "@" not in email:
        return web.json_response({"success": False, "message": "Địa chỉ email không hợp lệ."})
    if len(password) < 6:
        return web.json_response({"success": False, "message": "Mật khẩu tối thiểu phải từ 6 ký tự trở lên."})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        user_id = f"usr_{uuid.uuid4().hex[:10]}"
        c.execute("INSERT INTO users (id, email, password_hash, name) VALUES (?, ?, ?, ?)",
                  (user_id, email, _hash_pw(password), name))

        # Tự động tạo 1 Agent mặc định cho tài khoản mới
        agent_id = f"ag_{uuid.uuid4().hex[:10]}"
        c.execute("""
        INSERT INTO agents (id, user_id, name, model, voice, prompt)
        VALUES (?, ?, 'Trợ Lý Mặc Định', 'deepseek-chat', 'vi-VN-HoaiMyNeural',
                'Bạn là trợ lý AI thông minh, giao tiếp tiếng Việt tự nhiên và súc tích.')
        """, (agent_id, user_id))

        conn.commit()
        user = {"user_id": user_id, "email": email, "name": name}
        return web.json_response({"success": True, "message": "Đăng ký tài khoản thành công.", "user": user})
    except sqlite3.IntegrityError:
        return web.json_response({"success": False, "message": "Địa chỉ email này đã được đăng ký trước đó."})
    finally:
        conn.close()


async def api_portal_login(request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, email, name FROM users WHERE email = ? AND password_hash = ?", (email, _hash_pw(password)))
    row = c.fetchone()
    conn.close()

    if row:
        user = {"user_id": row[0], "email": row[1], "name": row[2]}
        return web.json_response({"success": True, "user": user})
    return web.json_response({"success": False, "message": "Thông tin email hoặc mật khẩu không chính xác."})


# ── REST API QUẢN LÝ AGENT ─────────────────────────────────────────

async def api_portal_get_agents(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "agents": []})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, model, api_key, voice, prompt FROM agents WHERE user_id = ? ORDER BY created_at ASC", (user_id,))
    rows = c.fetchall()

    agents = []
    for r in rows:
        ag_id = r[0]
        c.execute("SELECT count(*) FROM devices WHERE agent_id = ?", (ag_id,))
        dev_count = c.fetchone()[0]
        agents.append({
            "id": ag_id,
            "name": r[1],
            "model": r[2],
            "api_key": r[3],
            "voice": r[4],
            "prompt": r[5],
            "device_count": dev_count
        })
    conn.close()
    return web.json_response({"success": True, "agents": agents})


async def api_portal_save_agent(request):
    data = await request.json()
    user_id = data.get("user_id")
    agent_id = data.get("id") or f"ag_{uuid.uuid4().hex[:10]}"
    name = data.get("name", "Trợ Lý Mới").strip()
    model = data.get("model", "deepseek-chat").strip()
    api_key = data.get("api_key", "").strip()
    voice = data.get("voice", "vi-VN-HoaiMyNeural")
    prompt = data.get("prompt", "Bạn là trợ lý AI thông minh.").strip()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO agents (id, user_id, name, model, api_key, voice, prompt)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (agent_id, user_id, name, model, api_key, voice, prompt))
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": f"Đã lưu Trợ lý '{name}' thành công."})


async def api_portal_delete_agent(request):
    data = await request.json()
    user_id = data.get("user_id")
    agent_id = data.get("id")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id))
    c.execute("UPDATE devices SET agent_id = NULL WHERE agent_id = ?", (agent_id,))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã xóa Trợ lý thành công."})


# ── REST API QUẢN LÝ THIẾT BỊ ──────────────────────────────────────

async def api_portal_get_devices(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "devices": []})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    SELECT d.device_id, d.name, d.pairing_code, d.agent_id, a.name as agent_name
    FROM devices d
    LEFT JOIN agents a ON d.agent_id = a.id
    WHERE d.user_id = ?
    ORDER BY d.created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    devices = []
    for r in rows:
        dev_id = r[0]
        # Trạng thái online được lấy trực tiếp từ bảng active sessions thực tế
        is_online = dev_id in ACTIVE_CONNECTIONS
        devices.append({
            "device_id": dev_id,
            "name": r[1],
            "pairing_code": r[2],
            "agent_id": r[3] or "",
            "agent_name": r[4] or "Chưa gán Trợ lý",
            "status": "online" if is_online else "offline"
        })
    return web.json_response({"success": True, "devices": devices})


async def api_portal_bind_device(request):
    data = await request.json()
    user_id = data.get("user_id")
    code = data.get("pairing_code", "").strip()
    name = data.get("bot_name", "Thiết Bị ESP32").strip()
    agent_id = data.get("agent_id", "")

    if not user_id:
        return web.json_response({"success": False, "message": "Vui lòng đăng nhập trước khi thực hiện."})
    if len(code) != 6 or not code.isdigit():
        return web.json_response({"success": False, "message": "Mã PIN phải đúng 6 chữ số hiển thị trên màn hình mạch."})

    device_id = f"ESP32-{code}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT user_id FROM devices WHERE device_id = ?", (device_id,))
    if c.fetchone():
        conn.close()
        return web.json_response({"success": False, "message": f"Mạch với mã PIN '{code}' đã được ghép đôi trong hệ thống."})

    if not agent_id:
        c.execute("SELECT id FROM agents WHERE user_id = ? LIMIT 1", (user_id,))
        first_ag = c.fetchone()
        if first_ag:
            agent_id = first_ag[0]

    c.execute("""
    INSERT INTO devices (device_id, user_id, agent_id, name, pairing_code, status)
    VALUES (?, ?, ?, ?, ?, 'offline')
    """, (device_id, user_id, agent_id, name, code))
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": f"Đã ghép đôi thiết bị '{name}' thành công."})


async def api_portal_assign_agent(request):
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")
    agent_id = data.get("agent_id")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE devices SET agent_id = ? WHERE device_id = ? AND user_id = ?", (agent_id, device_id, user_id))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã cập nhật Trợ lý điều khiển cho thiết bị."})


async def api_portal_delete_device(request):
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE device_id = ? AND user_id = ?", (device_id, user_id))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã hủy ghép đôi thiết bị."})


# ── GIAO DIỆN WEB PORTAL (TECHNICAL & PROFESSIONAL CONSOLE) ────────

HTML_XIAOZHI_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Voice Portal — Bảng Quản Trị Thiết Bị & Trợ Lý AI</title>
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
        body { background: var(--bg); color: var(--text-main); min-height: 100vh; padding-bottom: 60px; }
        
        .navbar { background: var(--panel); border-bottom: 1px solid var(--panel-border); padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
        .brand-title { font-size: 18px; font-weight: 700; letter-spacing: -0.5px; }
        .brand-subtitle { font-size: 12px; color: var(--text-muted); }

        .container { max-width: 1050px; margin: 28px auto; padding: 0 16px; }

        /* Auth Card */
        .auth-card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 32px; max-width: 420px; margin: 60px auto; }
        .auth-title { font-size: 20px; font-weight: 700; margin-bottom: 6px; text-align: center; }
        .auth-desc { font-size: 13px; color: var(--text-muted); text-align: center; margin-bottom: 24px; }
        .auth-tab { display: flex; border-bottom: 1px solid var(--panel-border); margin-bottom: 20px; }
        .auth-tab button { flex: 1; padding: 10px; background: none; border: none; font-weight: 600; cursor: pointer; color: var(--text-muted); font-size: 13px; }
        .auth-tab button.active { color: var(--accent); border-bottom: 2px solid var(--accent); margin-bottom: -1px; }

        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 6px; }
        input[type="text"], input[type="password"], select, textarea {
            width: 100%; padding: 10px 12px; background: #0b1120; border: 1px solid var(--panel-border); border-radius: 8px; color: var(--text-main); font-size: 13px; outline: none; transition: border-color 0.15s;
        }
        input:focus, select:focus, textarea:focus { border-color: var(--accent); }
        .mono-input { font-family: var(--mono); font-size: 12px; }

        .btn { padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; transition: 0.15s; }
        .btn-primary { background: var(--accent); color: white; width: 100%; }
        .btn-primary:hover { background: var(--accent-hover); }
        .btn-secondary { background: #1f293d; color: var(--text-main); }
        .btn-secondary:hover { background: #2d3b55; }
        .btn-danger { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.3); }
        .btn-danger:hover { background: rgba(239, 68, 68, 0.25); }
        .btn-sm { padding: 6px 12px; font-size: 12px; }

        /* Tabs */
        .portal-nav { display: flex; gap: 8px; border-bottom: 1px solid var(--panel-border); margin-bottom: 24px; }
        .portal-nav button { padding: 12px 18px; background: none; border: none; font-weight: 600; cursor: pointer; color: var(--text-muted); font-size: 14px; }
        .portal-nav button.active { color: var(--accent); border-bottom: 2px solid var(--accent); margin-bottom: -1px; }

        /* Card / Table */
        .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 22px; margin-bottom: 20px; }
        .card-title { font-size: 16px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }

        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        td { padding: 12px; border-bottom: 1px solid var(--panel-border); }

        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .status-dot.online { background: #10b981; }
        .status-dot.offline { background: #64748b; }

        .agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 16px; }
        .agent-card { background: #0b1120; border: 1px solid var(--panel-border); border-radius: 10px; padding: 18px; display: flex; flex-direction: column; justify-content: space-between; }
        .agent-name { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
        .agent-meta { font-size: 12px; color: var(--text-muted); font-family: var(--mono); margin-bottom: 10px; }
        .agent-prompt { font-size: 12px; color: var(--text-main); line-height: 1.4; margin-bottom: 14px; flex-grow: 1; background: #070a12; padding: 8px 10px; border-radius: 6px; }

        /* Modal */
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 200; justify-content: center; align-items: center; }
        .modal-content { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 24px; width: 480px; max-width: 90%; }
        .modal-header { font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
    </style>
</head>
<body>
    <div class="navbar">
        <div>
            <div class="brand-title">Ni-Oh Voice Portal</div>
            <div class="brand-subtitle">Bảng Quản Trị Thiết Bị & Trợ Lý AI</div>
        </div>
        <div id="userProfile" style="display: none; align-items: center; gap: 14px;">
            <span id="userNameDisplay" style="font-size: 13px; font-weight: 600;"></span>
            <button class="btn btn-secondary btn-sm" onclick="logoutUser()">Đăng Xuất</button>
        </div>
    </div>

    <!-- KHỐI ĐĂNG NHẬP / ĐĂNG KÝ -->
    <div id="authSection" class="auth-card">
        <div class="auth-title">Đăng Nhập Quản Trị</div>
        <div class="auth-desc">Truy cập bảng điều khiển thiết bị Xiaozhi của bạn</div>

        <div class="auth-tab">
            <button id="tabBtnLogin" class="active" onclick="switchAuthTab('login')">Đăng Nhập</button>
            <button id="tabBtnRegister" onclick="switchAuthTab('register')">Đăng Ký</button>
        </div>

        <div class="form-group">
            <label>Địa Chỉ Email:</label>
            <input type="text" id="authEmail" class="mono-input" placeholder="name@example.com">
        </div>
        <div class="form-group">
            <label>Mật Khẩu:</label>
            <input type="password" id="authPassword" placeholder="••••••••">
        </div>
        <div class="form-group" id="nameGroup" style="display: none;">
            <label>Họ Và Tên:</label>
            <input type="text" id="authName" placeholder="Tên hiển thị">
        </div>

        <button id="authSubmitBtn" class="btn btn-primary" onclick="submitAuth()">Đăng Nhập</button>
    </div>

    <!-- KHỐI QUẢN TRỊ CHÍNH (SAU KHI ĐĂNG NHẬP) -->
    <div id="portalSection" class="container" style="display: none;">
        <div class="portal-nav">
            <button id="navAgents" class="active" onclick="switchPortalTab('agents')">Trợ Lý AI (Agents)</button>
            <button id="navDevices" onclick="switchPortalTab('devices')">Thiết Bị Đã Ghép Đôi</button>
            <button id="navFirmware" onclick="switchPortalTab('firmware')">Cấu Hình Firmware</button>
        </div>

        <!-- TAB 1: QUẢN LÝ AGENT -->
        <div id="tabAgents">
            <div class="card">
                <div class="card-title">
                    <span>Danh Sách Trợ Lý AI</span>
                    <button class="btn btn-primary btn-sm" style="width: auto;" onclick="openAgentModal()">+ Thêm Trợ Lý Mới</button>
                </div>
                <div id="agentsGrid" class="agent-grid">
                    <!-- Render dynamically -->
                </div>
            </div>
        </div>

        <!-- TAB 2: QUẢN LÝ THIẾT BỊ -->
        <div id="tabDevices" style="display: none;">
            <div class="card">
                <div class="card-title">
                    <span>Mạch ESP32 Đã Ghép Đôi</span>
                    <button class="btn btn-primary btn-sm" style="width: auto;" onclick="openBindModal()">+ Ghép Đôi Bằng Mã PIN 6 Số</button>
                </div>
                <div id="devicesTableContainer">
                    <!-- Render dynamically -->
                </div>
            </div>
        </div>

        <!-- TAB 3: CẤU HÌNH FIRMWARE -->
        <div id="tabFirmware" style="display: none;">
            <div class="card">
                <div class="card-title">Thông Số Kết Nối Cho Firmware ESP32</div>
                <p style="font-size: 13px; color: var(--text-muted); line-height: 1.6; margin-bottom: 16px;">
                    Cấu hình các tham số bên dưới vào tập tin <code>config.json</code> hoặc phân vùng NVS của mạch Xiaozhi ESP32 để trỏ kết nối trực tiếp về máy chủ này:
                </p>

                <div class="form-group">
                    <label>Địa Chỉ WebSocket Voice Endpoint:</label>
                    <input type="text" id="fwWssUrl" class="mono-input" readonly>
                </div>

                <div class="form-group">
                    <label>Địa Chỉ Cập Nhật OTA Endpoint:</label>
                    <input type="text" id="fwOtaUrl" class="mono-input" readonly>
                </div>

                <div class="form-group">
                    <label>Cấu Trúc JSON Cấu Hình Firmware Mẫu:</label>
                    <textarea id="fwJsonConfig" class="mono-input" rows="6" readonly style="resize: none;"></textarea>
                </div>
            </div>
        </div>
    </div>

    <!-- MODAL THÊM / SỬA AGENT -->
    <div id="agentModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <span id="agentModalTitle">Cấu Hình Trợ Lý AI</span>
                <span style="cursor: pointer; color: var(--text-muted);" onclick="closeAgentModal()">✕</span>
            </div>
            <div class="form-group">
                <label>Tên Trợ Lý:</label>
                <input type="text" id="agNameInput" placeholder="Ví dụ: Trợ Lý Bàn Làm Việc">
            </div>
            <div class="form-group">
                <label>Mô Hình Ngôn Ngữ (Model ID):</label>
                <input type="text" id="agModelSelect" class="mono-input" placeholder="deepseek-chat" list="portalModelPresets">
                <datalist id="portalModelPresets">
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
                <label>Giọng Đọc (Edge-TTS Neural):</label>
                <select id="agVoiceSelect">
                    <option value="vi-VN-HoaiMyNeural">Hoài My (Tiếng Việt - Nữ)</option>
                    <option value="vi-VN-NamMinhNeural">Nam Minh (Tiếng Việt - Nam)</option>
                    <option value="en-US-JennyNeural">Jenny (English - Female)</option>
                    <option value="zh-CN-XiaoxiaoNeural">Xiaoxiao (Chinese - Female)</option>
                </select>
            </div>
            <div class="form-group">
                <label>API Key Riêng (Tùy chọn - Bỏ trống để dùng chung key máy chủ):</label>
                <input type="password" id="agApiKeyInput" class="mono-input" placeholder="sk-...">
            </div>
            <div class="form-group">
                <label>Câu Lệnh Nhân Cách (System Prompt):</label>
                <textarea id="agPromptInput" rows="3" placeholder="Định nghĩa vai trò và cách ứng xử của Trợ lý AI..."></textarea>
            </div>
            <button class="btn btn-primary" onclick="submitSaveAgent()">Lưu Trợ Lý</button>
        </div>
    </div>

    <!-- MODAL GHÉP ĐÔI THIẾT BỊ 6 SỐ -->
    <div id="bindModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <span>Ghép Đôi Mạch ESP32</span>
                <span style="cursor: pointer; color: var(--text-muted);" onclick="closeBindModal()">✕</span>
            </div>
            <div class="form-group">
                <label>Mã PIN 6 Số (Hiển thị trên màn hình mạch):</label>
                <input type="text" id="pinInput" class="mono-input" maxlength="6" placeholder="Ví dụ: 123456" style="font-size: 18px; letter-spacing: 4px; text-align: center;">
            </div>
            <div class="form-group">
                <label>Tên Gợi Nhớ Cho Thiết Bị:</label>
                <input type="text" id="botNameInput" placeholder="Ví dụ: Robot Bàn Học">
            </div>
            <div class="form-group">
                <label>Gán Vào Trợ Lý AI:</label>
                <select id="bindAgentSelect"></select>
            </div>
            <button class="btn btn-primary" onclick="submitBindDevice()">Xác Nhận Ghép Đôi</button>
        </div>
    </div>

    <script>
        let currentUser = null;
        let currentAuthMode = 'login';
        let userAgents = [];
        let userDevices = [];
        let editingAgentId = null;

        function switchAuthTab(mode) {
            currentAuthMode = mode;
            document.getElementById('tabBtnLogin').className = mode === 'login' ? 'active' : '';
            document.getElementById('tabBtnRegister').className = mode === 'register' ? 'active' : '';
            document.getElementById('nameGroup').style.display = mode === 'register' ? 'block' : 'none';
            document.getElementById('authSubmitBtn').innerText = mode === 'login' ? 'Đăng Nhập' : 'Tạo Tài Khoản Mới';
        }

        async function submitAuth() {
            const email = document.getElementById('authEmail').value.trim();
            const password = document.getElementById('authPassword').value.trim();
            const name = document.getElementById('authName').value.trim();

            if (!email || !password) {
                alert("Vui lòng điền đầy đủ email và mật khẩu.");
                return;
            }

            const endpoint = currentAuthMode === 'login' ? '/api/portal/login' : '/api/portal/register';
            const payload = { email, password, name };

            try {
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.success) {
                    onLoginSuccess(data.user);
                } else {
                    alert(data.message);
                }
            } catch (e) {
                alert("Không thể kết nối máy chủ: " + e);
            }
        }

        function onLoginSuccess(user) {
            currentUser = user;
            sessionStorage.setItem('nioh_user', JSON.stringify(user));
            document.getElementById('authSection').style.display = 'none';
            document.getElementById('portalSection').style.display = 'block';
            document.getElementById('userProfile').style.display = 'flex';
            document.getElementById('userNameDisplay').innerText = user.name || user.email;

            loadAllData();
            loadFirmwareEndpoints();
        }

        function logoutUser() {
            currentUser = null;
            sessionStorage.removeItem('nioh_user');
            document.getElementById('portalSection').style.display = 'none';
            document.getElementById('userProfile').style.display = 'none';
            document.getElementById('authSection').style.display = 'block';
        }

        function switchPortalTab(tab) {
            document.getElementById('tabAgents').style.display = tab === 'agents' ? 'block' : 'none';
            document.getElementById('tabDevices').style.display = tab === 'devices' ? 'block' : 'none';
            document.getElementById('tabFirmware').style.display = tab === 'firmware' ? 'block' : 'none';

            document.getElementById('navAgents').className = tab === 'agents' ? 'active' : '';
            document.getElementById('navDevices').className = tab === 'devices' ? 'active' : '';
            document.getElementById('navFirmware').className = tab === 'firmware' ? 'active' : '';
        }

        async function loadAllData() {
            if (!currentUser) return;
            await loadAgents();
            await loadDevices();
        }

        async function loadAgents() {
            const res = await fetch(`/api/portal/agents?user_id=${currentUser.user_id}`);
            const data = await res.json();
            userAgents = data.agents || [];
            renderAgents();
            updateAgentDropdowns();
        }

        function renderAgents() {
            const container = document.getElementById('agentsGrid');
            if (userAgents.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">Chưa có Trợ lý nào. Nhấp "+ Thêm Trợ Lý Mới" để tạo.</div>';
                return;
            }

            container.innerHTML = userAgents.map(ag => `
                <div class="agent-card">
                    <div>
                        <div class="agent-name">${ag.name}</div>
                        <div class="agent-meta">Model: ${ag.model} | Giọng: ${ag.voice.replace('Neural','')}</div>
                        <div class="agent-prompt">${ag.prompt || 'Không có mô tả nhân cách.'}</div>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--panel-border); padding-top: 10px; margin-top: 6px;">
                        <span style="font-size: 11px; color: var(--text-muted);">${ag.device_count} thiết bị đang gắn</span>
                        <div style="display: flex; gap: 6px;">
                            <button class="btn btn-secondary btn-sm" onclick="editAgent('${ag.id}')">Sửa</button>
                            <button class="btn btn-danger btn-sm" onclick="deleteAgent('${ag.id}', '${ag.name}')">Xóa</button>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function updateAgentDropdowns() {
            const sel = document.getElementById('bindAgentSelect');
            sel.innerHTML = userAgents.map(ag => `<option value="${ag.id}">${ag.name}</option>`).join('');
        }

        function openAgentModal() {
            editingAgentId = null;
            document.getElementById('agentModalTitle').innerText = "Thêm Trợ Lý AI Mới";
            document.getElementById('agNameInput').value = "";
            document.getElementById('agModelSelect').value = "deepseek-chat";
            document.getElementById('agVoiceSelect').value = "vi-VN-HoaiMyNeural";
            document.getElementById('agApiKeyInput').value = "";
            document.getElementById('agPromptInput').value = "Bạn là trợ lý AI thông minh, hỗ trợ người dùng bằng tiếng Việt tự nhiên và súc tích.";
            document.getElementById('agentModal').style.display = 'flex';
        }

        function editAgent(id) {
            const ag = userAgents.find(a => a.id === id);
            if (!ag) return;
            editingAgentId = id;
            document.getElementById('agentModalTitle').innerText = `Chỉnh Sửa Trợ Lý: ${ag.name}`;
            document.getElementById('agNameInput').value = ag.name;
            document.getElementById('agModelSelect').value = ag.model;
            document.getElementById('agVoiceSelect').value = ag.voice;
            document.getElementById('agApiKeyInput').value = ag.api_key || "";
            document.getElementById('agPromptInput').value = ag.prompt || "";
            document.getElementById('agentModal').style.display = 'flex';
        }

        function closeAgentModal() {
            document.getElementById('agentModal').style.display = 'none';
        }

        async function submitSaveAgent() {
            const payload = {
                user_id: currentUser.user_id,
                id: editingAgentId,
                name: document.getElementById('agNameInput').value.trim() || 'Trợ Lý AI',
                model: document.getElementById('agModelSelect').value.trim() || 'deepseek-chat',
                voice: document.getElementById('agVoiceSelect').value,
                api_key: document.getElementById('agApiKeyInput').value.trim(),
                prompt: document.getElementById('agPromptInput').value.trim()
            };
            const res = await fetch('/api/portal/agents', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            closeAgentModal();
            loadAllData();
        }

        async function deleteAgent(id, name) {
            if (!confirm(`Bạn có chắc chắn muốn xóa Trợ lý "${name}"?`)) return;
            const res = await fetch('/api/portal/delete-agent', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, id: id })
            });
            loadAllData();
        }

        async function loadDevices() {
            const res = await fetch(`/api/portal/devices?user_id=${currentUser.user_id}`);
            const data = await res.json();
            userDevices = data.devices || [];
            renderDevices();
        }

        function renderDevices() {
            const container = document.getElementById('devicesTableContainer');
            if (userDevices.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; padding: 20px 0;">Chưa có thiết bị nào được ghép đôi. Nhấp "+ Ghép Đôi Bằng Mã PIN 6 Số" để kết nối mạch ESP32.</div>';
                return;
            }

            let html = `<table>
                <thead>
                    <tr>
                        <th>Tên Thiết Bị</th>
                        <th>Mã Định Danh (ID)</th>
                        <th>Mã PIN</th>
                        <th>Trợ Lý AI Điều Khiển</th>
                        <th>Trạng Thái</th>
                        <th>Thao Tác</th>
                    </tr>
                </thead>
                <tbody>`;

            userDevices.forEach(d => {
                const options = userAgents.map(a => `<option value="${a.id}" ${a.id === d.agent_id ? 'selected' : ''}>${a.name}</option>`).join('');
                const isOnline = d.status === 'online';
                html += `<tr>
                    <td style="font-weight: 600;">${d.name}</td>
                    <td style="font-family: var(--mono); color: var(--text-muted);">${d.device_id}</td>
                    <td style="font-family: var(--mono); font-weight: 600;">${d.pairing_code}</td>
                    <td>
                        <select onchange="changeDeviceAgent('${d.device_id}', this.value)" style="padding: 4px 8px; font-size: 12px; width: auto;">
                            ${options}
                        </select>
                    </td>
                    <td>
                        <span class="status-dot ${isOnline ? 'online' : 'offline'}"></span>
                        <span style="font-size: 12px; font-weight: 600; color: ${isOnline ? '#10b981' : '#64748b'};">${isOnline ? 'Online' : 'Offline'}</span>
                    </td>
                    <td>
                        <button class="btn btn-danger btn-sm" onclick="deleteDevice('${d.device_id}', '${d.name}')">Hủy Ghép Đôi</button>
                    </td>
                </tr>`;
            });

            html += `</tbody></table>`;
            container.innerHTML = html;
        }

        function openBindModal() {
            document.getElementById('pinInput').value = "";
            document.getElementById('botNameInput').value = "";
            document.getElementById('bindModal').style.display = 'flex';
        }

        function closeBindModal() {
            document.getElementById('bindModal').style.display = 'none';
        }

        async function submitBindDevice() {
            const pin = document.getElementById('pinInput').value.trim();
            const name = document.getElementById('botNameInput').value.trim() || 'Thiết Bị ESP32';
            const agentId = document.getElementById('bindAgentSelect').value;

            if (pin.length !== 6) {
                alert("Mã PIN phải đúng 6 chữ số.");
                return;
            }

            const res = await fetch('/api/portal/bind', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, pairing_code: pin, bot_name: name, agent_id: agentId })
            });
            const data = await res.json();
            alert(data.message);
            if (data.success) {
                closeBindModal();
                loadDevices();
            }
        }

        async function changeDeviceAgent(deviceId, agentId) {
            await fetch('/api/portal/assign-agent', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, device_id: deviceId, agent_id: agentId })
            });
            loadAllData();
        }

        async function deleteDevice(deviceId, name) {
            if (!confirm(`Bạn có chắc muốn hủy ghép đôi thiết bị "${name}"?`)) return;
            await fetch('/api/portal/delete-device', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, device_id: deviceId })
            });
            loadDevices();
        }

        function loadFirmwareEndpoints() {
            const origin = window.location.origin;
            const wssOrigin = origin.replace('https://', 'wss://').replace('http://', 'ws://');
            const wsUrl = `${wssOrigin}/xiaozhi/v1/`;
            const otaUrl = `${origin}/xiaozhi/ota/`;

            document.getElementById('fwWssUrl').value = wsUrl;
            document.getElementById('fwOtaUrl').value = otaUrl;

            const configObj = {
                "websocket": {
                    "url": wsUrl
                },
                "ota": {
                    "url": otaUrl
                }
            };
            document.getElementById('fwJsonConfig').value = JSON.stringify(configObj, null, 2);
        }

        // Khôi phục phiên làm việc nếu đã đăng nhập
        const saved = sessionStorage.getItem('nioh_user');
        if (saved) {
            try { onLoginSuccess(JSON.parse(saved)); } catch(e){}
        }
    </script>
</body>
</html>
"""
