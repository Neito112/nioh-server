"""
Ni-Oh Server Gateway (Desktop App)
----------------------------------
Thành phần 1: APP SERVER (Cổng Máy Chủ & Quản Trị Hệ Thống)
Chức năng:
1. Mở Cổng Server & Kích Hoạt Cloudflare Anycast Tunnel
   - Quản lý cổng nội bộ (Port 8001) và đường truyền WebSocket/OTA
   - Kích hoạt Cloudflare và XUẤT LINK SERVER cho Web quản lý và Mạch Xiaozhi
   - Giám sát các kết nối WebSocket đang hoạt động thời gian thực

2. Quản Lý Data Người Dùng Bằng Tài Khoản Google
   - Cấu hình Google OAuth (Client ID & Client Secret) để cấp quyền cho Web Portal
   - Quản lý danh sách người dùng đăng nhập hệ thống (Google / Local)
   - Sao lưu (Backup) và Phục hồi (Restore) toàn bộ cơ sở dữ liệu hệ thống
"""

import os
import sys
import json
import sqlite3
import time
import asyncio
import logging
from aiohttp import web

logger = logging.getLogger("nioh.gateway_app")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")

from cloudflare.tunnel import (
    activate_quick_tunnel_link,
    setup_tunnel,
    stop_tunnel
)
from server.voice_engine import get_live_connections

# Trạng thái Cổng Server
GATEWAY_STATE = {
    "server_running": False,
    "cf_domain": "",
    "portal_web_url": "",
    "wss_url": "",
    "ota_url": "",
}


def get_oauth_config() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS oauth_config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("SELECT key, value FROM oauth_config")
    rows = dict(c.fetchall())
    conn.close()
    return {
        "google_client_id": rows.get("google_client_id", os.environ.get("GOOGLE_CLIENT_ID", "")),
        "google_client_secret": rows.get("google_client_secret", os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    }


def save_oauth_config(data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS oauth_config (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in data.items():
        c.execute("INSERT OR REPLACE INTO oauth_config (key, value) VALUES (?, ?)", (k, str(v).strip()))
    conn.commit()
    conn.close()


# ── REST API MỞ CỔNG VÀ ĐIỀU KHIỂN GATEWAY ─────────────────────────

async def api_get_gateway_status(request):
    live_stats = get_live_connections()
    oauth_cfg = get_oauth_config()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT, password_hash TEXT, name TEXT, avatar TEXT, provider TEXT, google_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("SELECT count(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, name TEXT, pairing_code TEXT, status TEXT DEFAULT 'offline', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("SELECT count(*) FROM devices")
    total_devices = c.fetchone()[0]
    conn.close()

    return web.json_response({
        **GATEWAY_STATE,
        "local_port": request.app.get("port", 8001),
        "live_clients": live_stats["connections"],
        "active_clients_count": live_stats["active_count"],
        "total_users_count": total_users,
        "total_devices_count": total_devices,
        "oauth": oauth_cfg,
    })


async def api_toggle_gateway(request):
    """Mở cổng Cloudflare và xuất các đường link server."""
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
            logger.error(f"Lỗi mở cổng Cloudflare Tunnel: {e}")
            return web.json_response({"success": False, "message": f"Lỗi mở cổng Cloudflare: {str(e)}"})
    else:
        GATEWAY_STATE["server_running"] = False
        stop_tunnel()
        GATEWAY_STATE["portal_web_url"] = ""
        GATEWAY_STATE["wss_url"] = ""
        GATEWAY_STATE["ota_url"] = ""
        return web.json_response({"success": True, "state": GATEWAY_STATE})


# ── REST API QUẢN LÝ DỮ LIỆU NGƯỜI DÙNG & GOOGLE OAUTH ────────────

async def api_admin_get_users(request):
    """Lấy danh sách người dùng đăng nhập hệ thống và số lượng bot sở hữu."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    SELECT u.id, u.email, u.name, u.avatar, u.provider, u.created_at,
           (SELECT count(*) FROM agents WHERE user_id = u.id) as agent_count,
           (SELECT count(*) FROM devices WHERE user_id = u.id) as device_count
    FROM users u
    ORDER BY u.created_at DESC
    """)
    rows = c.fetchall()
    conn.close()

    users = []
    for r in rows:
        users.append({
            "id": r[0],
            "email": r[1],
            "name": r[2],
            "avatar": r[3] or "",
            "provider": r[4] or "local",
            "created_at": r[5],
            "agent_count": r[6],
            "device_count": r[7]
        })
    return web.json_response({"success": True, "users": users})


async def api_admin_delete_user(request):
    """Xóa tài khoản người dùng và dọn sạch dữ liệu liên quan."""
    data = await request.json()
    user_id = data.get("user_id")
    if not user_id:
        return web.json_response({"success": False, "message": "Thiếu user_id"})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM agents WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "message": "Đã xóa người dùng thành công."})


async def api_admin_save_oauth(request):
    """Lưu cấu hình Google OAuth credentials."""
    data = await request.json()
    save_oauth_config({
        "google_client_id": data.get("google_client_id", "").strip(),
        "google_client_secret": data.get("google_client_secret", "").strip()
    })
    return web.json_response({"success": True, "message": "Đã lưu cấu hình Google OAuth thành công."})


async def api_admin_backup_data(request):
    """Xuất toàn bộ cơ sở dữ liệu SQLite sang tệp JSON sao lưu."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    data = {}
    for tbl in ["users", "agents", "devices", "server_config", "oauth_config"]:
        try:
            c.execute(f"SELECT * FROM {tbl}")
            cols = [d[0] for d in c.description] if c.description else []
            rows = c.fetchall()
            data[tbl] = [dict(zip(cols, r)) for r in rows]
        except Exception:
            data[tbl] = []
    conn.close()

    filename = f"backup_portal_data_{time.strftime('%Y%m%d_%H%M%S')}.json"
    return web.Response(
        text=json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json",
        charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


async def api_admin_restore_data(request):
    """Phục hồi cơ sở dữ liệu từ tệp JSON sao lưu."""
    try:
        data = await request.json()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        if "users" in data:
            c.execute("DELETE FROM users")
            for u in data["users"]:
                c.execute("""
                INSERT OR REPLACE INTO users (id, email, password_hash, name, avatar, provider, google_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (u.get("id"), u.get("email"), u.get("password_hash"), u.get("name"), u.get("avatar"), u.get("provider", "local"), u.get("google_id"), u.get("created_at")))

        if "agents" in data:
            c.execute("DELETE FROM agents")
            for a in data["agents"]:
                c.execute("""
                INSERT OR REPLACE INTO agents (id, user_id, name, model, api_key, voice, prompt, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (a.get("id"), a.get("user_id"), a.get("name"), a.get("model"), a.get("api_key"), a.get("voice"), a.get("prompt"), a.get("created_at")))

        if "devices" in data:
            c.execute("DELETE FROM devices")
            for d in data["devices"]:
                c.execute("""
                INSERT OR REPLACE INTO devices (device_id, user_id, agent_id, name, pairing_code, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (d.get("device_id"), d.get("user_id"), d.get("agent_id"), d.get("name"), d.get("pairing_code"), d.get("status", "offline"), d.get("created_at")))

        if "oauth_config" in data:
            for o in data["oauth_config"]:
                c.execute("INSERT OR REPLACE INTO oauth_config (key, value) VALUES (?, ?)", (o.get("key"), o.get("value")))

        conn.commit()
        conn.close()
        return web.json_response({"success": True, "message": "Đã phục hồi dữ liệu thành công."})
    except Exception as e:
        logger.error(f"Lỗi phục hồi dữ liệu: {e}")
        return web.json_response({"success": False, "message": f"Lỗi phục hồi dữ liệu: {str(e)}"})


# ── GIAO DIỆN APP SERVER (HOST SERVER & DATA MANAGEMENT CONSOLE) ──

HTML_GATEWAY_APP = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Server — Cổng Máy Chủ & Quản Trị Hệ Thống</title>
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
        .brand-title { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }
        .brand-subtitle { font-size: 13px; color: var(--text-muted); margin-top: 2px; }
        .status-badge { font-size: 12px; font-weight: 600; padding: 6px 14px; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.5px; }
        .status-badge.online { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
        .status-badge.offline { background: rgba(148, 163, 184, 0.15); color: var(--text-muted); border: 1px solid rgba(148, 163, 184, 0.3); }

        /* Stats Bar */
        .stats-bar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 24px; }
        .stat-box { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 10px; padding: 16px; text-align: center; }
        .stat-val { font-size: 24px; font-weight: 700; font-family: var(--mono); color: var(--accent); }
        .stat-lbl { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

        /* Cards */
        .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 22px; margin-bottom: 24px; }
        .card-header { font-size: 16px; font-weight: 600; border-bottom: 1px solid var(--panel-border); padding-bottom: 12px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }

        /* Form */
        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 6px; }
        input[type="text"], input[type="password"] {
            width: 100%; padding: 10px 12px; background: #0b1120; border: 1px solid var(--panel-border); border-radius: 8px; color: var(--text-main); font-size: 13px; outline: none;
        }
        input:focus { border-color: var(--accent); }
        .mono-input { font-family: var(--mono); font-size: 12px; }

        /* Buttons */
        .btn { padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; transition: 0.15s; }
        .btn-primary { background: var(--accent); color: white; }
        .btn-primary:hover { background: var(--accent-hover); }
        .btn-danger { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.3); }
        .btn-danger:hover { background: rgba(239, 68, 68, 0.25); }
        .btn-secondary { background: #1f293d; color: var(--text-main); }
        .btn-secondary:hover { background: #2d3b55; }
        .btn-sm { padding: 6px 12px; font-size: 12px; }

        /* Endpoints Box */
        .endpoints-box { margin-top: 18px; background: #070a12; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; }
        .endpoint-row { margin-bottom: 14px; }
        .endpoint-row:last-child { margin-bottom: 0; }
        .endpoint-title { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px; }
        .endpoint-value-wrap { display: flex; justify-content: space-between; align-items: center; gap: 8px; background: #0f172a; padding: 8px 12px; border-radius: 6px; border: 1px solid #1e293b; }
        .endpoint-value { font-family: var(--mono); font-size: 13px; color: #38bdf8; word-break: break-all; }

        /* Table */
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        td { padding: 12px; border-bottom: 1px solid var(--panel-border); }
        .empty-table { padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px; }

        .avatar-small { width: 24px; height: 24px; border-radius: 50%; vertical-align: middle; margin-right: 8px; }
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="header">
            <div>
                <div class="brand-title">Ni-Oh Server — Cổng Máy Chủ & Quản Trị Hệ Thống</div>
                <div class="brand-subtitle">Mở cổng dịch vụ máy chủ, xuất link Cloudflare và quản lý tài khoản người dùng</div>
            </div>
            <div id="gatewayBadge" class="status-badge offline">CỔNG SERVER: ĐÃ TẮT</div>
        </div>

        <div class="stats-bar">
            <div class="stat-box">
                <div class="stat-val" id="statLocalPort">8001</div>
                <div class="stat-lbl">Cổng Nội Bộ (Local WebSocket & API)</div>
            </div>
            <div class="stat-box">
                <div class="stat-val" id="statActiveCount">0</div>
                <div class="stat-lbl">Mạch Xiaozhi Đang Kết Nối Trực Tiếp</div>
            </div>
            <div class="stat-box">
                <div class="stat-val" id="statUserCount">0</div>
                <div class="stat-lbl">Tài Khoản Người Dùng Đã Đăng Ký</div>
            </div>
        </div>

        <!-- KHỐI 1: MỞ CỔNG SERVER & XUẤT LINK CLOUDFLARE -->
        <div class="card">
            <div class="card-header">
                <span>1. Mở Cổng Server & Kích Hoạt Cloudflare Anycast</span>
            </div>

            <div style="display: flex; gap: 12px; align-items: flex-end; margin-bottom: 16px;">
                <div style="flex: 1;">
                    <label>Tên Miền Riêng (Tùy Chọn - Bỏ trống để dùng link Cloudflare tự động):</label>
                    <input type="text" id="customDomain" class="mono-input" placeholder="ví dụ: voice.yourdomain.com">
                </div>
                <button id="toggleBtn" class="btn btn-primary" onclick="toggleGateway()" style="white-space: nowrap; height: 38px;">
                    Mở Cổng Server & Xuất Link Cloudflare
                </button>
            </div>

            <div id="endpointsBox" class="endpoints-box" style="display: none;">
                <div class="endpoint-row">
                    <div class="endpoint-title">🌐 Link Web Server (Gửi cho người dùng truy cập quản lý Bot & Agent):</div>
                    <div class="endpoint-value-wrap">
                        <span class="endpoint-value" id="urlWebPortal">https://...</span>
                        <div style="display: flex; gap: 6px;">
                            <button class="btn btn-secondary btn-sm" onclick="copyValue('urlWebPortal')">Copy Link</button>
                            <button class="btn btn-secondary btn-sm" onclick="openUrl('urlWebPortal')">Mở Web Quản Lý</button>
                        </div>
                    </div>
                </div>

                <div class="endpoint-row">
                    <div class="endpoint-title">📡 Link Server Cho Mạch Xiaozhi Trỏ Đến (WebSocket Voice Endpoint):</div>
                    <div class="endpoint-value-wrap">
                        <span class="endpoint-value" id="urlWebSocket">wss://.../xiaozhi/v1/</span>
                        <button class="btn btn-secondary btn-sm" onclick="copyValue('urlWebSocket')">Copy Link</button>
                    </div>
                </div>

                <div class="endpoint-row">
                    <div class="endpoint-title">🔄 Link Cổng Cập Nhật OTA Cho Firmware ESP32:</div>
                    <div class="endpoint-value-wrap">
                        <span class="endpoint-value" id="urlOTA">https://.../xiaozhi/ota/</span>
                        <button class="btn btn-secondary btn-sm" onclick="copyValue('urlOTA')">Copy Link</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- KHỐI 2: QUẢN LÝ DỮ LIỆU NGƯỜI DÙNG & TÀI KHOẢN GOOGLE -->
        <div class="card">
            <div class="card-header">
                <span>2. Quản Lý Data Người Dùng & Cấu Hình Google OAuth</span>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-secondary btn-sm" onclick="backupData()">Sao Lưu Dữ Liệu (Backup JSON)</button>
                    <label class="btn btn-secondary btn-sm" style="cursor: pointer; margin: 0;">
                        Phục Hồi Dữ Liệu (Restore)
                        <input type="file" id="restoreFileInput" style="display: none;" onchange="restoreData(event)">
                    </label>
                </div>
            </div>

            <!-- Thiết lập Google OAuth Credentials -->
            <div style="background: #0b1120; border: 1px solid var(--panel-border); border-radius: 8px; padding: 16px; margin-bottom: 20px;">
                <div style="font-size: 13px; font-weight: 600; margin-bottom: 10px; color: var(--accent);">
                    Cấu Hình Google OAuth (Dùng để cấp quyền đăng nhập Google cho Web Server)
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
                    <div>
                        <label>Google Client ID:</label>
                        <input type="text" id="googleClientId" class="mono-input" placeholder="xxxxx.apps.googleusercontent.com">
                    </div>
                    <div>
                        <label>Google Client Secret:</label>
                        <input type="password" id="googleClientSecret" class="mono-input" placeholder="GOCSPX-xxxxx">
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 12px; color: var(--text-muted);">
                        Redirect URI cần thêm vào Google Cloud Console: <code id="redirectUriHint" style="color: #38bdf8; font-family: var(--mono);">/api/auth/google/callback</code>
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="saveOAuthConfig()">Lưu Cấu Hình Google</button>
                </div>
            </div>

            <!-- Bảng Người Dùng -->
            <div class="card-header" style="font-size: 14px; border-bottom: none; padding-bottom: 0; margin-bottom: 10px;">
                <span>Danh Sách Người Dùng Đã Đăng Nhập Hệ Thống</span>
                <button class="btn btn-secondary btn-sm" onclick="loadUsersTable()">Làm Mới</button>
            </div>
            <div id="usersTableContainer">
                <div class="empty-table">Chưa có người dùng nào đăng ký hoặc đăng nhập.</div>
            </div>
        </div>

        <!-- KHỐI 3: THEO DÕI KẾT NỐI MẠCH THỜI GIAN THỰC -->
        <div class="card">
            <div class="card-header">
                <span>3. Giám Sát Mạch ESP32 Đang Kết Nối Trực Tiếp (Live WebSocket)</span>
                <button class="btn btn-secondary btn-sm" onclick="loadStatus()">Làm Mới</button>
            </div>
            <div id="clientsTableContainer">
                <div class="empty-table">Không có mạch ESP32 nào đang kết nối tới cổng WebSocket.</div>
            </div>
        </div>
    </div>

    <script>
        async function loadStatus() {
            try {
                const res = await fetch('/api/gateway/status');
                const data = await res.json();

                const isRun = data.server_running;
                const badge = document.getElementById('gatewayBadge');
                const btn = document.getElementById('toggleBtn');
                const box = document.getElementById('endpointsBox');

                if (isRun) {
                    badge.innerText = 'CỔNG SERVER: HOẠT ĐỘNG (ONLINE)';
                    badge.className = 'status-badge online';
                    btn.innerText = 'Đóng Cổng Server (Dừng Cloudflare)';
                    btn.className = 'btn btn-danger';
                    box.style.display = 'block';
                    document.getElementById('urlWebPortal').innerText = data.portal_web_url;
                    document.getElementById('urlWebSocket').innerText = data.wss_url;
                    document.getElementById('urlOTA').innerText = data.ota_url;

                    document.getElementById('redirectUriHint').innerText = `${data.portal_web_url}/api/auth/google/callback`;
                } else {
                    badge.innerText = 'CỔNG SERVER: ĐÃ TẮT';
                    badge.className = 'status-badge offline';
                    btn.innerText = 'Mở Cổng Server & Xuất Link Cloudflare';
                    btn.className = 'btn btn-primary';
                    box.style.display = 'none';

                    document.getElementById('redirectUriHint').innerText = `http://localhost:${data.local_port}/api/auth/google/callback`;
                }

                document.getElementById('statLocalPort').innerText = data.local_port || 8001;
                document.getElementById('statActiveCount').innerText = data.active_clients_count || 0;
                document.getElementById('statUserCount').innerText = data.total_users_count || 0;

                if (data.oauth) {
                    document.getElementById('googleClientId').value = data.oauth.google_client_id || '';
                    document.getElementById('googleClientSecret').value = data.oauth.google_client_secret || '';
                }

                renderClientsTable(data.live_clients || []);
            } catch (e) {
                console.error("Lỗi lấy trạng thái:", e);
            }
        }

        async function toggleGateway() {
            const isRunning = document.getElementById('gatewayBadge').innerText.includes("ONLINE");
            const action = isRunning ? "stop" : "start";
            const domain = document.getElementById('customDomain').value.trim();

            const btn = document.getElementById('toggleBtn');
            btn.innerText = "Đang kích hoạt hạ tầng mạng Cloudflare...";
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
                alert("Lỗi khi mở cổng: " + e);
            } finally {
                btn.disabled = false;
                loadStatus();
            }
        }

        async function saveOAuthConfig() {
            const cid = document.getElementById('googleClientId').value.trim();
            const csec = document.getElementById('googleClientSecret').value.trim();

            const res = await fetch('/api/admin/oauth-config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ google_client_id: cid, google_client_secret: csec })
            });
            const data = await res.json();
            alert(data.message);
        }

        async function loadUsersTable() {
            try {
                const res = await fetch('/api/admin/users');
                const data = await res.json();
                const users = data.users || [];
                const container = document.getElementById('usersTableContainer');

                if (users.length === 0) {
                    container.innerHTML = '<div class="empty-table">Chưa có người dùng nào đăng ký hoặc đăng nhập.</div>';
                    return;
                }

                let html = `<table>
                    <thead>
                        <tr>
                            <th>Người Dùng</th>
                            <th>Email</th>
                            <th>Phương Thức</th>
                            <th>Số Bot / Agent</th>
                            <th>Số Mạch Ghép Đôi</th>
                            <th>Ngày Đăng Ký</th>
                            <th>Thao Tác</th>
                        </tr>
                    </thead>
                    <tbody>`;

                users.forEach(u => {
                    const avatar = u.avatar ? `<img src="${u.avatar}" class="avatar-small">` : '';
                    const providerBadge = u.provider === 'google' 
                        ? `<span style="background: rgba(66, 133, 244, 0.15); color: #60a5fa; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;">Google</span>`
                        : `<span style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;">Email</span>`;

                    html += `<tr>
                        <td style="font-weight: 600;">${avatar}${u.name}</td>
                        <td style="font-family: var(--mono); color: var(--text-muted);">${u.email}</td>
                        <td>${providerBadge}</td>
                        <td style="font-family: var(--mono);">${u.agent_count}</td>
                        <td style="font-family: var(--mono);">${u.device_count}</td>
                        <td style="font-size: 12px; color: var(--text-muted);">${u.created_at}</td>
                        <td><button class="btn btn-danger btn-sm" onclick="deleteUser('${u.id}', '${u.name}')">Xóa</button></td>
                    </tr>`;
                });

                html += `</tbody></table>`;
                container.innerHTML = html;
            } catch (e) {
                console.error("Lỗi lấy danh sách người dùng:", e);
            }
        }

        async function deleteUser(id, name) {
            if (!confirm(`Bạn có chắc chắn muốn xóa người dùng "${name}" cùng toàn bộ dữ liệu liên quan?`)) return;
            const res = await fetch('/api/admin/delete-user', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: id })
            });
            const data = await res.json();
            alert(data.message);
            loadUsersTable();
            loadStatus();
        }

        function backupData() {
            window.location.href = '/api/admin/backup';
        }

        async function restoreData(event) {
            const file = event.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = async function(e) {
                try {
                    const jsonData = JSON.parse(e.target.result);
                    if (!confirm("Thao tác này sẽ ghi đè dữ liệu hiện tại bằng dữ liệu trong tệp sao lưu. Bạn có muốn tiếp tục?")) return;

                    const res = await fetch('/api/admin/restore', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(jsonData)
                    });
                    const data = await res.json();
                    alert(data.message);
                    loadStatus();
                    loadUsersTable();
                } catch (err) {
                    alert("Tệp JSON không hợp lệ: " + err);
                }
            };
            reader.readAsText(file);
        }

        function renderClientsTable(clients) {
            const container = document.getElementById('clientsTableContainer');
            if (!clients || clients.length === 0) {
                container.innerHTML = '<div class="empty-table">Không có mạch ESP32 nào đang kết nối tới cổng WebSocket.</div>';
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
        loadUsersTable();
        setInterval(loadStatus, 4000);
    </script>
</body>
</html>
"""
