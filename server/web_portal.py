"""
Ni-Oh Web Server (Agent & Device Portal — xiaozhi.me style)
------------------------------------------------------------
Thành phần 2: WEB SERVER (Dành cho người dùng cuối)
- Người dùng truy cập bằng đường LINK WEB được xuất ra từ App Server
- Đăng ký & Đăng nhập tài khoản cá nhân
- QUẢN LÝ AGENT (Tạo/Sửa các trợ lý AI: Model, Voice, Prompt, API Key riêng)
- QUẢN LÝ THIẾT BỊ (Ghép đôi mạch Xiaozhi bằng mã PIN 6 số, Gán mạch vào Agent)
- Giám sát trạng thái Online/Offline của từng con bot theo thời gian thực
"""

import os
import sys
import json
import sqlite3
import hashlib
import uuid
import logging
from aiohttp import web

logger = logging.getLogger("nioh.web_server")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")


# ── KHỞI TẠO CƠ SỞ DỮ LIỆU ĐẦY ĐỦ CHO AGENT & THIẾT BỊ ─────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Bảng người dùng
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        password_hash TEXT,
        name TEXT,
        avatar TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 2. Bảng Agent (Trợ lý AI - nhân vật)
    c.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        name TEXT,
        avatar TEXT,
        model TEXT DEFAULT 'deepseek/deepseek-chat',
        api_key TEXT DEFAULT '',
        voice TEXT DEFAULT 'vi-VN-HoaiMyNeural',
        prompt TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    
    # 3. Bảng thiết bị ghép đôi (Devices)
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


# ── REST API XÁC THỰC NGƯỜI DÙNG ───────────────────────────

async def api_portal_register(request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip() or email.split("@")[0]

    if not email or "@" not in email:
        return web.json_response({"success": False, "message": "Email không hợp lệ!"})
    if len(password) < 6:
        return web.json_response({"success": False, "message": "Mật khẩu phải từ 6 ký tự trở lên!"})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        user_id = f"usr_{hashlib.md5(email.encode()).hexdigest()[:12]}"
        avatar = f"https://ui-avatars.com/api/?name={name}&background=2563eb&color=fff"
        c.execute("INSERT INTO users (id, email, password_hash, name, avatar) VALUES (?, ?, ?, ?, ?)",
                  (user_id, email, _hash_pw(password), name, avatar))
        
        # Tự động tạo 1 Agent mặc định cho người dùng mới
        agent_id = f"ag_{uuid.uuid4().hex[:10]}"
        c.execute("""
        INSERT INTO agents (id, user_id, name, avatar, model, voice, prompt)
        VALUES (?, ?, 'Trợ Lý Ni-Oh', '🤖', 'deepseek/deepseek-chat', 'vi-VN-HoaiMyNeural',
                'Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính, hài hước và nhiệt tình hỗ trợ.')
        """, (agent_id, user_id))

        conn.commit()
        user = {"user_id": user_id, "email": email, "name": name, "avatar": avatar}
        return web.json_response({"success": True, "message": "Đăng ký tài khoản thành công!", "user": user})
    except sqlite3.IntegrityError:
        return web.json_response({"success": False, "message": "Email này đã được đăng ký!"})
    finally:
        conn.close()


async def api_portal_login(request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, email, name, avatar FROM users WHERE email = ? AND password_hash = ?", (email, _hash_pw(password)))
    row = c.fetchone()
    conn.close()

    if row:
        user = {"user_id": row[0], "email": row[1], "name": row[2], "avatar": row[3]}
        return web.json_response({"success": True, "user": user})
    return web.json_response({"success": False, "message": "Sai email hoặc mật khẩu!"})


# ── REST API QUẢN LÝ AGENT (Trợ lý AI - nhân vật) ──────────

async def api_portal_get_agents(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "agents": []})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, avatar, model, api_key, voice, prompt FROM agents WHERE user_id = ? ORDER BY created_at ASC", (user_id,))
    rows = c.fetchall()
    
    # Đếm số thiết bị đang gắn với mỗi agent
    agents = []
    for r in rows:
        ag_id = r[0]
        c.execute("SELECT count(*) FROM devices WHERE agent_id = ?", (ag_id,))
        dev_count = c.fetchone()[0]
        agents.append({
            "id": ag_id,
            "name": r[1],
            "avatar": r[2] or "🤖",
            "model": r[3],
            "api_key": r[4],
            "voice": r[5],
            "prompt": r[6],
            "device_count": dev_count
        })
    conn.close()
    return web.json_response({"success": True, "agents": agents})


async def api_portal_save_agent(request):
    """Tạo mới hoặc cập nhật thông tin Agent."""
    data = await request.json()
    user_id = data.get("user_id")
    agent_id = data.get("id") or f"ag_{uuid.uuid4().hex[:10]}"
    name = data.get("name", "Trợ Lý Mới").strip()
    avatar = data.get("avatar", "🤖").strip()
    model = data.get("model", "deepseek/deepseek-chat")
    api_key = data.get("api_key", "").strip()
    voice = data.get("voice", "vi-VN-HoaiMyNeural")
    prompt = data.get("prompt", "Bạn là trợ lý AI thông minh.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO agents (id, user_id, name, avatar, model, api_key, voice, prompt)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (agent_id, user_id, name, avatar, model, api_key, voice, prompt))
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": f"Đã lưu Agent '{name}' thành công!"})


async def api_portal_delete_agent(request):
    data = await request.json()
    user_id = data.get("user_id")
    agent_id = data.get("id")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id))
    # Gỡ agent khỏi các thiết bị
    c.execute("UPDATE devices SET agent_id = NULL WHERE agent_id = ?", (agent_id,))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã xóa Agent thành công!"})


# ── REST API QUẢN LÝ THIẾT BỊ (Ghép đôi 6 số & Gán Agent) ──

async def api_portal_get_devices(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "devices": []})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    SELECT d.device_id, d.name, d.pairing_code, d.status, d.agent_id, a.name as agent_name, a.avatar as agent_avatar
    FROM devices d
    LEFT JOIN agents a ON d.agent_id = a.id
    WHERE d.user_id = ?
    ORDER BY d.created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    devices = []
    for r in rows:
        devices.append({
            "device_id": r[0],
            "name": r[1],
            "pairing_code": r[2],
            "status": r[3],
            "agent_id": r[4] or "",
            "agent_name": r[5] or "Chưa gán Agent",
            "agent_avatar": r[6] or "❓",
        })
    return web.json_response({"success": True, "devices": devices})


async def api_portal_bind_device(request):
    data = await request.json()
    user_id = data.get("user_id")
    code = data.get("pairing_code", "").strip()
    name = data.get("bot_name", "Xiaozhi S3").strip()
    agent_id = data.get("agent_id", "")

    if not user_id:
        return web.json_response({"success": False, "message": "Vui lòng đăng nhập trước!"})
    if len(code) != 6 or not code.isdigit():
        return web.json_response({"success": False, "message": "Mã PIN phải đúng 6 chữ số trên màn hình mạch!"})

    device_id = f"ESP32-{code}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT user_id FROM devices WHERE device_id = ?", (device_id,))
    if c.fetchone():
        conn.close()
        return web.json_response({"success": False, "message": f"Mạch có mã '{code}' đã được thêm trước đó!"})

    # Nếu chưa chỉ định agent_id thì gán cho agent đầu tiên của user
    if not agent_id:
        c.execute("SELECT id FROM agents WHERE user_id = ? LIMIT 1", (user_id,))
        first_ag = c.fetchone()
        if first_ag: agent_id = first_ag[0]

    c.execute("""
    INSERT INTO devices (device_id, user_id, agent_id, name, pairing_code, status)
    VALUES (?, ?, ?, ?, ?, 'offline')
    """, (device_id, user_id, agent_id, name, code))
    conn.commit()
    conn.close()

    return web.json_response({"success": True, "message": f"Đã ghép đôi mạch '{name}' thành công!"})


async def api_portal_assign_agent(request):
    """Gán mạch Xiaozhi vào 1 Agent cụ thể."""
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")
    agent_id = data.get("agent_id")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE devices SET agent_id = ? WHERE device_id = ? AND user_id = ?", (agent_id, device_id, user_id))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã đổi Agent cho mạch thành công!"})


async def api_portal_delete_device(request):
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE device_id = ? AND user_id = ?", (device_id, user_id))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã hủy ghép đôi mạch khỏi tài khoản!"})


# ── GIAO DIỆN WEB SERVER (HTML/CSS/JS CHUẨN XIAOZHI.ME) ─────

HTML_XIAOZHI_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Web Server — Quản Lý Agent & Thiết Bị (xiaozhi.me)</title>
    <style>
        :root {
            --primary: #2563eb; --primary-hover: #1d4ed8; --bg: #f8fafc;
            --panel: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0;
            --success: #16a34a; --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); min-height: 100vh; padding-bottom: 60px; }
        
        .navbar { background: var(--panel); border-bottom: 1px solid var(--border); padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
        .brand { font-size: 20px; font-weight: 800; color: var(--primary); display: flex; align-items: center; gap: 8px; }
        .container { max-width: 1000px; margin: 30px auto; padding: 0 16px; }

        /* Auth Card */
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
        
        .btn { width: 100%; padding: 11px; background: var(--primary); color: white; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; transition: 0.2s; }
        .btn:hover { background: var(--primary-hover); }
        .btn-sm { width: auto; padding: 8px 16px; font-size: 13px; }
        .btn-secondary { background: #f1f5f9; color: #334155; }
        .btn-secondary:hover { background: #e2e8f0; }

        /* Dashboard Tabs (Agents vs Devices) */
        .nav-tabs { display: flex; gap: 10px; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        .nav-tab-btn { background: none; border: none; font-size: 16px; font-weight: 700; padding: 8px 16px; border-radius: 8px; cursor: pointer; color: var(--muted); }
        .nav-tab-btn.active { background: #eff6ff; color: var(--primary); }

        /* Grid */
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 22px; cursor: pointer; transition: 0.2s; position: relative; }
        .card:hover { border-color: var(--primary); transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05); }

        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
        .dot-online { background: var(--success); box-shadow: 0 0 6px rgba(34,197,94,0.6); }
        .dot-offline { background: var(--muted); }

        /* Modal */
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 200; backdrop-filter: blur(2px); }
        .modal { background: var(--panel); border-radius: 16px; width: 100%; max-width: 520px; padding: 28px; }

        .endpoint-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; padding: 16px; margin-top: 24px; font-size: 13px; line-height: 1.6; }
        .code-tag { background: white; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 6px; font-family: monospace; font-size: 12px; color: #0369a1; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="brand">
            <span>⚡ Ni-Oh Web Server</span>
            <span style="font-size: 12px; background: #eff6ff; color: var(--primary); padding: 4px 8px; border-radius: 6px; font-weight: 700;">xiaozhi.me clone</span>
        </div>
        <div id="userNavbar" style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 13px; color: var(--muted);">Chưa đăng nhập</span>
        </div>
    </div>

    <div class="container">
        <!-- 1. MÀN HÌNH ĐĂNG NHẬP / ĐĂNG KÝ -->
        <div id="authScreen" class="auth-card">
            <div class="auth-title">Quản Lý Agent & Thiết Bị</div>
            <div class="auth-desc">Đăng nhập tài khoản để thiết lập các nhân vật AI và gán mạch Xiaozhi</div>

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

        <!-- 2. MÀN HÌNH CHÍNH (Sau khi đăng nhập) -->
        <div id="dashboardScreen" style="display: none;">
            <!-- Menu chuyển giữa AGENTS và THIẾT BỊ -->
            <div class="nav-tabs">
                <button class="nav-tab-btn active" id="btnTabAgents" onclick="switchMainTab('agents')">🤖 1. Agent Của Tôi</button>
                <button class="nav-tab-btn" id="btnTabDevices" onclick="switchMainTab('devices')">📱 2. Mạch Xiaozhi Đã Ghép Đôi</button>
                <button class="nav-tab-btn" id="btnTabGuide" onclick="switchMainTab('guide')">📡 3. Cấu Hình Firmware</button>
            </div>

            <!-- TAB 1: DANH SÁCH AGENT -->
            <div id="sectionAgents">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <div>
                        <h2 style="font-size: 20px; font-weight: 800;">Danh Sách Trợ Lý AI (Agents)</h2>
                        <span style="font-size: 13px; color: var(--muted);">Tạo các tính cách, model AI và giọng đọc khác nhau để gán vào từng mạch Xiaozhi</span>
                    </div>
                    <button class="btn btn-sm" onclick="openAgentModal()">+ Tạo Agent Mới</button>
                </div>
                <div class="grid" id="agentGrid"></div>
            </div>

            <!-- TAB 2: DANH SÁCH THIẾT BỊ -->
            <div id="sectionDevices" style="display: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <div>
                        <h2 style="font-size: 20px; font-weight: 800;">Mạch Xiaozhi Của Tôi</h2>
                        <span style="font-size: 13px; color: var(--muted);">Ghép đôi bằng mã 6 số từ màn hình và chọn Agent tương ứng để robot nói chuyện</span>
                    </div>
                    <button class="btn btn-sm" onclick="openBindModal()">+ Ghép Đôi Mạch Mới</button>
                </div>
                <div class="grid" id="deviceGrid"></div>
            </div>

            <!-- TAB 3: HƯỚNG DẪN KẾT NỐI -->
            <div id="sectionGuide" style="display: none;">
                <div class="endpoint-box">
                    <strong style="font-size: 15px;">📡 Thông Số Kết Nối Server Dành Cho Firmware ESP32:</strong><br>
                    <p style="margin: 8px 0; color: var(--muted);">
                        Để mạch Xiaozhi của bạn kết nối về server này và nhận lệnh từ các Agent ở trên, hãy cấu hình endpoint tương ứng vào firmware:
                    </p>
                    <div style="margin-top: 10px;">
                        • <strong>WebSocket Audio Server (WSS):</strong> <span class="code-tag" id="liveWssTag">wss://.../xiaozhi/v1/</span><br>
                        • <strong>OTA Firmware Server:</strong> <span class="code-tag" id="liveOtaTag">https://.../xiaozhi/ota/</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- MODAL: TẠO / SỬA AGENT -->
    <div class="modal-overlay" id="agentModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 16px;" id="agentModalTitle">🤖 Tạo Trợ Lý AI Mới</h3>
            
            <div class="input-group">
                <label>Tên Agent (ví dụ: Gia Sư Tiếng Anh, Bạn Tâm Sự...)</label>
                <input type="text" id="agNameInput" placeholder="Trợ Lý Thông Minh">
            </div>

            <div class="input-group">
                <label>Mô Hình AI (Model):</label>
                <select id="agModelSelect">
                    <option value="deepseek/deepseek-chat">⭐ DeepSeek V3 (Nhanh, Tiếng Việt chuẩn xác)</option>
                    <option value="google/gemini-2.0-flash:free">🎁 Google Gemini 2.0 Flash (FREE 100%, Siêu tốc)</option>
                    <option value="openai/gpt-4o-mini">⚡ GPT-4o Mini (Phản hồi tức thì)</option>
                    <option value="anthropic/claude-3.5-sonnet">👑 Claude 3.5 Sonnet (Thông minh nhất)</option>
                    <option value="meta-llama/llama-3.3-70b-instruct">🧠 Llama 3.3 70B</option>
                    <option value="deepseek/deepseek-r1">🔬 DeepSeek R1 (Lý luận sâu)</option>
                </select>
            </div>

            <div class="input-group">
                <label>Giọng Đọc Tiếng Việt (TTS Neural):</label>
                <select id="agVoiceSelect">
                    <option value="vi-VN-HoaiMyNeural">Hoài My (Nữ miền Bắc - Trong trẻo, tự nhiên)</option>
                    <option value="vi-VN-NamMinhNeural">Nam Minh (Nam miền Bắc - Trầm ấm, truyền cảm)</option>
                </select>
            </div>

            <div class="input-group">
                <label>API Key Riêng Của Bạn (Tùy chọn - Bỏ trống để dùng key mặc định của Server):</label>
                <input type="password" id="agApiKeyInput" placeholder="sk-xxxx">
            </div>

            <div class="input-group">
                <label>Tính Cách Nhân Vật / System Prompt:</label>
                <textarea id="agPromptInput" rows="3" placeholder="Bạn là một trợ lý vui tính..."></textarea>
            </div>

            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="btn" onclick="submitSaveAgent()">Lưu Agent</button>
                <button class="btn btn-secondary" style="width: auto;" onclick="closeAgentModal()">Đóng</button>
            </div>
        </div>
    </div>

    <!-- MODAL: GHÉP ĐÔI MẠCH MỚI QUA MÃ 6 SỐ -->
    <div class="modal-overlay" id="bindModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 10px;">🔗 Ghép Đôi Mạch Xiaozhi Mới</h3>
            <p style="color: var(--muted); font-size: 13px; margin-bottom: 18px;">
                Bật nguồn mạch ESP32, màn hình LCD sẽ hiện <strong>mã 6 chữ số</strong>. Hãy nhập mã đó vào đây:
            </p>
            <div class="input-group">
                <label>Mã 6 Số trên màn hình mạch:</label>
                <input type="text" id="pinInput" maxlength="6" style="font-size: 26px; font-weight: 800; text-align: center; letter-spacing: 8px;" placeholder="123456">
            </div>
            <div class="input-group">
                <label>Đặt tên cho mạch robot này:</label>
                <input type="text" id="botNameInput" value="Robot Xiaozhi S3">
            </div>
            <div class="input-group">
                <label>Gán Agent điều khiển mạch:</label>
                <select id="bindAgentSelect"></select>
            </div>
            <div style="display: flex; gap: 10px; margin-top: 22px;">
                <button class="btn" onclick="submitBindDevice()">Ghép Đôi Mạch</button>
                <button class="btn btn-secondary" style="width: auto;" onclick="closeBindModal()">Hủy</button>
            </div>
        </div>
    </div>

    <script>
        let currentUser = null;
        let currentAuthMode = 'login';
        let userAgents = [];
        let userDevices = [];
        let editingAgentId = null;

        function updateEndpointsDisplay() {
            const loc = window.location;
            const wssProto = (loc.protocol === 'https:') ? 'wss:' : 'ws:';
            document.getElementById('liveWssTag').innerText = `${wssProto}//${loc.host}/xiaozhi/v1/`;
            document.getElementById('liveOtaTag').innerText = `${loc.protocol}//${loc.host}/xiaozhi/ota/`;
        }

        function switchTab(mode) {
            currentAuthMode = mode;
            document.getElementById('tabLogin').className = (mode === 'login') ? 'active' : '';
            document.getElementById('tabRegister').className = (mode === 'register') ? 'active' : '';
            document.getElementById('nameGroup').style.display = (mode === 'register') ? 'block' : 'none';
            document.getElementById('submitBtn').innerText = (mode === 'login') ? 'Đăng Nhập Ngay' : 'Tạo Tài Khoản Mới';
        }

        function switchMainTab(tab) {
            document.querySelectorAll('.nav-tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('sectionAgents').style.display = (tab === 'agents') ? 'block' : 'none';
            document.getElementById('sectionDevices').style.display = (tab === 'devices') ? 'block' : 'none';
            document.getElementById('sectionGuide').style.display = (tab === 'guide') ? 'block' : 'none';
            if (tab === 'agents') document.getElementById('btnTabAgents').classList.add('active');
            if (tab === 'devices') document.getElementById('btnTabDevices').classList.add('active');
            if (tab === 'guide') document.getElementById('btnTabGuide').classList.add('active');
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
            loadAllData();
        }

        function logout() {
            sessionStorage.removeItem('nioh_user');
            currentUser = null;
            location.reload();
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
            
            const grid = document.getElementById('agentGrid');
            if (userAgents.length === 0) {
                grid.innerHTML = `<div style="grid-column: span 3; text-align: center; padding: 40px; color: var(--muted);">Chưa có Agent nào. Nhấp "+ Tạo Agent Mới" để bắt đầu.</div>`;
                return;
            }
            grid.innerHTML = userAgents.map(a => `
                <div class="card" onclick="editAgent('${a.id}')">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                        <span style="font-size: 28px;">${a.avatar}</span>
                        <div>
                            <strong style="font-size: 16px;">${a.name}</strong><br>
                            <small style="color: var(--muted);">Model: ${a.model.split('/')[1] || a.model}</small>
                        </div>
                    </div>
                    <div style="font-size: 13px; color: #475569; margin-bottom: 12px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">
                        "${a.prompt || 'Chưa có prompt...'}"
                    </div>
                    <div style="font-size: 12px; background: #eff6ff; color: var(--primary); padding: 6px 10px; border-radius: 6px; display: flex; justify-content: space-between;">
                        <span>📱 Mạch đang dùng: <strong>${a.device_count} thiết bị</strong></span>
                        <span>Sửa ⚙️</span>
                    </div>
                </div>
            `).join('');

            // Cập nhật dropdown chọn agent trong modal ghép đôi
            const sel = document.getElementById('bindAgentSelect');
            sel.innerHTML = userAgents.map(a => `<option value="${a.id}">${a.avatar} ${a.name}</option>`).join('');
        }

        async function loadDevices() {
            const res = await fetch(`/api/portal/devices?user_id=${currentUser.user_id}`);
            const data = await res.json();
            userDevices = data.devices || [];

            const grid = document.getElementById('deviceGrid');
            if (userDevices.length === 0) {
                grid.innerHTML = `<div style="grid-column: span 3; text-align: center; padding: 40px; color: var(--muted); border: 2px dashed var(--border); border-radius: 12px;">Bạn chưa ghép đôi mạch nào.<br>Bấm <strong>"+ Ghép Đôi Mạch Mới"</strong> và nhập mã 6 số từ màn hình mạch để gán Agent.</div>`;
                return;
            }
            grid.innerHTML = userDevices.map(d => {
                const isOnline = (d.status === 'online');
                const dotClass = isOnline ? 'dot-online' : 'dot-offline';
                const statusText = isOnline ? '🟢 Đang Online' : '⚪ Offline';
                
                // Tạo dropdown chọn Agent trực tiếp trên từng thiết bị
                const agentOptions = userAgents.map(a => `
                    <option value="${a.id}" ${a.id === d.agent_id ? 'selected' : ''}>${a.avatar} ${a.name}</option>
                `).join('');

                return `
                <div class="card" style="cursor: default;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <strong style="font-size: 16px;">${d.name}</strong>
                        <span style="font-size: 12px; font-weight: 700; color: ${isOnline ? 'var(--success)' : 'var(--muted)'};">
                            <span class="status-dot ${dotClass}"></span>${statusText}
                        </span>
                    </div>
                    <div style="font-size: 12px; color: var(--muted); margin-bottom: 14px;">Mã PIN: <strong>${d.pairing_code}</strong> | ID: ${d.device_id}</div>
                    
                    <div style="background: #f8fafc; padding: 10px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 12px;">
                        <label style="font-size: 12px; color: var(--muted); margin-bottom: 4px;">Agent đang điều khiển mạch này:</label>
                        <select onchange="changeDeviceAgent('${d.device_id}', this.value)" style="padding: 6px 10px; font-size: 13px; font-weight: 600;">
                            ${agentOptions}
                        </select>
                    </div>

                    <button class="btn btn-secondary" style="font-size: 12px; padding: 6px; color: #ef4444;" onclick="deleteDevice('${d.device_id}', '${d.name}')">Hủy Ghép Đôi</button>
                </div>
            `}).join('');
        }

        function openAgentModal() {
            editingAgentId = null;
            document.getElementById('agentModalTitle').innerText = '🤖 Tạo Trợ Lý AI Mới';
            document.getElementById('agNameInput').value = 'Gia Sư AI';
            document.getElementById('agModelSelect').value = 'deepseek/deepseek-chat';
            document.getElementById('agVoiceSelect').value = 'vi-VN-HoaiMyNeural';
            document.getElementById('agApiKeyInput').value = '';
            document.getElementById('agPromptInput').value = 'Bạn là một gia sư thông thái, giải thích dễ hiểu và khích lệ người học.';
            document.getElementById('agentModal').style.display = 'flex';
        }

        function editAgent(agentId) {
            const ag = userAgents.find(a => a.id === agentId);
            if (!ag) return;
            editingAgentId = ag.id;
            document.getElementById('agentModalTitle').innerText = `⚙️ Sửa Agent: ${ag.name}`;
            document.getElementById('agNameInput').value = ag.name;
            document.getElementById('agModelSelect').value = ag.model;
            document.getElementById('agVoiceSelect').value = ag.voice;
            document.getElementById('agApiKeyInput').value = ag.api_key || '';
            document.getElementById('agPromptInput').value = ag.prompt || '';
            document.getElementById('agentModal').style.display = 'flex';
        }

        function closeAgentModal() { document.getElementById('agentModal').style.display = 'none'; }

        async function submitSaveAgent() {
            const payload = {
                user_id: currentUser.user_id,
                id: editingAgentId,
                name: document.getElementById('agNameInput').value.trim() || 'Trợ Lý AI',
                model: document.getElementById('agModelSelect').value,
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
            alert(data.message);
            closeAgentModal();
            loadAllData();
        }

        function openBindModal() { document.getElementById('bindModal').style.display = 'flex'; }
        function closeBindModal() { document.getElementById('bindModal').style.display = 'none'; }

        async function submitBindDevice() {
            const pin = document.getElementById('pinInput').value.trim();
            const name = document.getElementById('botNameInput').value.trim();
            const agentId = document.getElementById('bindAgentSelect').value;
            if (pin.length !== 6) { alert('Mã PIN phải đúng 6 số trên màn hình mạch!'); return; }

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
            const res = await fetch('/api/portal/assign-agent', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, device_id: deviceId, agent_id: agentId })
            });
            const data = await res.json();
            loadAllData();
        }

        async function deleteDevice(deviceId, name) {
            if (!confirm(`Bạn có chắc muốn hủy ghép đôi mạch "${name}"?`)) return;
            const res = await fetch('/api/portal/delete-device', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, device_id: deviceId })
            });
            const data = await res.json();
            alert(data.message);
            loadDevices();
        }

        // Khôi phục phiên làm việc
        const saved = sessionStorage.getItem('nioh_user');
        if (saved) {
            try { onLoginSuccess(JSON.parse(saved)); } catch(e){}
        }
    </script>
</body>
</html>
"""
