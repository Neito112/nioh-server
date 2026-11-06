"""
Ni-Oh Device Management Web Portal (Dashboard 2)
------------------------------------------------
Giao diện Web Quản lý Thiết bị y hệt xiaozhi.me:
- Đăng nhập tài khoản cá nhân bằng liên kết GOOGLE hoặc ZALO
- Ghép đôi thiết bị ESP32 bằng MÃ 6 CHỮ SỐ hiển thị trên mạch
- Chọn Model AI phù hợp cho từng thiết bị
- Nhập API Key cá nhân
- Chọn giọng đọc tiếng Việt (TTS) & Cài đặt tính cách (System Prompt)
- Xem trạng thái Online/Offline & Lịch sử trò chuyện
"""

import os
import sys
import json
import logging
from aiohttp import web

logger = logging.getLogger("nioh.web_portal")

# Bộ nhớ lưu trữ thiết bị theo từng User ID
# Cấu trúc: { "user_google_123": [ { "device_id": "...", "name": "...", "model": "..." } ] }
USER_DEVICES_DB = {}


# ── REST API cho Web Portal ─────────────────────────────────

async def api_portal_auth(request):
    """Giả lập đăng nhập qua liên kết Google hoặc Zalo."""
    data = await request.json()
    provider = data.get("provider", "google")  # 'google' hoặc 'zalo'
    email = data.get("email") or ("user_google@gmail.com" if provider == "google" else "user_zalo@zalo.me")
    name = data.get("name") or ("Người dùng Google" if provider == "google" else "Người dùng Zalo")
    avatar = "https://lh3.googleusercontent.com/a/default-user" if provider == "google" else "https://zalo.me/favicon.ico"

    user_info = {
        "user_id": f"{provider}_{abs(hash(email)) % 1000000}",
        "name": name,
        "email": email,
        "provider": provider,
        "avatar": avatar,
    }
    return web.json_response({"success": True, "user": user_info})


async def api_portal_get_devices(request):
    user_id = request.query.get("user_id", "guest")
    devices = USER_DEVICES_DB.get(user_id, [])
    return web.json_response({"success": True, "devices": devices})


async def api_portal_bind_device(request):
    """Nhập mã 6 chữ số để ghép đôi mạch vào tài khoản cá nhân."""
    data = await request.json()
    user_id = data.get("user_id")
    code = data.get("pairing_code", "").strip()
    bot_name = data.get("bot_name", "Ni-Oh Bot")

    if not user_id:
        return web.json_response({"success": False, "message": "Vui lòng đăng nhập trước khi ghép đôi!"})

    if len(code) != 6 or not code.isdigit():
        return web.json_response({"success": False, "message": "Mã ghép đôi phải là 6 chữ số trên màn hình mạch!"})

    new_device = {
        "device_id": f"ESP32-{code}",
        "name": bot_name,
        "status": "online",
        "model": "deepseek/deepseek-chat",
        "api_key": "",
        "voice": "vi-VN-HoaiMyNeural",
        "prompt": "Bạn là Ni-Oh, trợ lý giọng nói thông minh, vui tính và thân thiện.",
        "pairing_code": code,
    }

    if user_id not in USER_DEVICES_DB:
        USER_DEVICES_DB[user_id] = []

    # Kiểm tra xem đã bind chưa
    existing = [d for d in USER_DEVICES_DB[user_id] if d["device_id"] == new_device["device_id"]]
    if existing:
        return web.json_response({"success": False, "message": "Thiết bị này đã được ghép đôi trong tài khoản của bạn!"})

    USER_DEVICES_DB[user_id].append(new_device)
    return web.json_response({"success": True, "message": f"Ghép đôi thiết bị '{bot_name}' thành công!", "device": new_device})


async def api_portal_update_device(request):
    """Cập nhật model, prompt, giọng nói cho từng thiết bị."""
    data = await request.json()
    user_id = data.get("user_id")
    device_id = data.get("device_id")

    devices = USER_DEVICES_DB.get(user_id, [])
    for dev in devices:
        if dev["device_id"] == device_id:
            dev["name"] = data.get("name", dev["name"])
            dev["model"] = data.get("model", dev["model"])
            dev["api_key"] = data.get("api_key", dev["api_key"])
            dev["voice"] = data.get("voice", dev["voice"])
            dev["prompt"] = data.get("prompt", dev["prompt"])
            return web.json_response({"success": True, "message": "Đã lưu cài đặt cho thiết bị thành công!"})

    return web.json_response({"success": False, "message": "Không tìm thấy thiết bị cần cập nhật!"})


# ── Giao diện HTML Web Portal (Y hệt xiaozhi.me) ─────────────

HTML_XIAOZHI_PORTAL = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ni-Oh Device Portal | xiaozhi.me Clone</title>
    <style>
        :root {
            --primary: #2563eb; --primary-hover: #1d4ed8; --bg: #f8fafc;
            --panel: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0;
            --success: #16a34a; --google: #ea4335; --zalo: #0068ff;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding-bottom: 50px; }
        
        /* Navbar */
        .navbar { background: var(--panel); border-bottom: 1px solid var(--border); padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
        .brand { font-size: 20px; font-weight: 800; color: var(--primary); display: flex; align-items: center; gap: 8px; }
        .user-section { display: flex; align-items: center; gap: 12px; }
        
        /* Main Container */
        .container { max-width: 950px; margin: 30px auto; padding: 0 16px; }
        .auth-banner { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 40px; text-align: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        .auth-btn-row { display: flex; justify-content: center; gap: 16px; margin-top: 24px; }
        .btn-auth { border: none; padding: 12px 24px; border-radius: 8px; font-size: 15px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 10px; color: white; transition: 0.2s; }
        .btn-google { background: var(--google); }
        .btn-zalo { background: var(--zalo); }
        
        /* Dashboard view */
        .header-actions { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
        .btn-primary { background: var(--primary); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; }
        
        /* Device List */
        .device-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
        .device-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px; cursor: pointer; transition: 0.2s; position: relative; }
        .device-card:hover { border-color: var(--primary); transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05); }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: var(--success); margin-right: 6px; }
        
        /* Modal & Config */
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 200; }
        .modal { background: var(--panel); border-radius: 16px; width: 100%; max-width: 520px; padding: 28px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); }
        .input-group { margin-bottom: 16px; }
        label { display: block; font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 6px; }
        input, select, textarea { width: 100%; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; outline: none; }
        input:focus, select:focus, textarea:focus { border-color: var(--primary); }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="brand">
            <span>⚡ Ni-Oh Device Portal</span>
            <span style="font-size: 11px; background: #e0f2fe; color: #0284c7; padding: 2px 8px; border-radius: 999px;">xiaozhi.me Style</span>
        </div>
        <div id="userSection" class="user-section">
            <span style="color: var(--muted); font-size: 14px;">Chưa đăng nhập</span>
        </div>
    </div>

    <div class="container">
        <!-- Màn hình Đăng Nhập Tài Khoản Cá Nhân -->
        <div id="authScreen" class="auth-banner">
            <h2 style="font-size: 26px; font-weight: 800; margin-bottom: 12px;">Quản Lý Thiết Bị Trợ Lý Giọng Nói</h2>
            <p style="color: var(--muted); max-width: 500px; margin: 0 auto;">
                Đăng nhập tài khoản cá nhân qua <strong>Google</strong> hoặc <strong>Zalo</strong> để kích hoạt và tùy biến các con bot ESP32 của bạn.
            </p>
            <div class="auth-btn-row">
                <button class="btn-auth btn-google" onclick="loginSocial('google')">
                    <span>Đăng nhập bằng Google</span>
                </button>
                <button class="btn-auth btn-zalo" onclick="loginSocial('zalo')">
                    <span>Đăng nhập bằng Zalo</span>
                </button>
            </div>
        </div>

        <!-- Màn hình Quản Lý Thiết Bị (Sau khi đăng nhập) -->
        <div id="dashboardScreen" style="display: none;">
            <div class="header-actions">
                <div>
                    <h2 style="font-size: 22px; font-weight: 800;">Thiết Bị Của Tôi</h2>
                    <span style="color: var(--muted); font-size: 13px;">Ghép đôi bằng mã 6 số hiện trên màn hình mạch</span>
                </div>
                <button class="btn-primary" onclick="openBindModal()">+ Thêm Thiết Bị Mới</button>
            </div>

            <!-- Danh sách các con bot -->
            <div class="device-grid" id="deviceGrid">
                <!-- Thiết bị sẽ được render ở đây -->
            </div>
        </div>
    </div>

    <!-- Modal Ghép Đôi Thiết Bị (Mã 6 Số) -->
    <div class="modal-overlay" id="bindModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 16px;">🔗 Thêm Thiết Bị Mới</h3>
            <p style="color: var(--muted); font-size: 13px; margin-bottom: 16px;">
                Bật nguồn mạch ESP32, màn hình sẽ hiển thị <strong>mã 6 chữ số</strong>. Hãy nhập mã đó vào đây:
            </p>
            <div class="input-group">
                <label>Mã PIN 6 Chữ Số trên Màn Hình</label>
                <input type="text" id="pinInput" maxlength="6" style="font-size: 24px; font-weight: bold; text-align: center; letter-spacing: 8px;" placeholder="123456">
            </div>
            <div class="input-group">
                <label>Đặt tên cho con bot</label>
                <input type="text" id="botNameInput" value="Ni-Oh S3 Mini">
            </div>
            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="btn-primary" style="flex: 1;" onclick="submitBindDevice()">Xác Nhận Ghép Đôi</button>
                <button class="btn-primary" style="background: #e2e8f0; color: #475569;" onclick="closeBindModal()">Hủy</button>
            </div>
        </div>
    </div>

    <!-- Modal Cài Đặt Chi Tiết Cho Từng Thiết Bị -->
    <div class="modal-overlay" id="configModal">
        <div class="modal">
            <h3 style="font-size: 18px; margin-bottom: 16px;" id="configModalTitle">⚙️ Cấu Hình Thiết Bị</h3>
            
            <div class="input-group">
                <label>Tên Thiết Bị</label>
                <input type="text" id="cfgName">
            </div>

            <!-- CHỌN MODEL PHÙ HỢP -->
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
                <input type="password" id="cfgApiKey" placeholder="sk-xxxx (Bỏ trống = dùng key trạm server)">
            </div>

            <div class="input-group">
                <label>Giọng Nói (TTS Tiếng Việt):</label>
                <select id="cfgVoice">
                    <option value="vi-VN-HoaiMyNeural">Hoài My (Nữ miền Bắc - Dịu dàng)</option>
                    <option value="vi-VN-NamMinhNeural">Nam Minh (Nam miền Bắc - Tự nhiên)</option>
                    <option value="vi-VN-BanMai">Ban Mai (Nữ miền Trung)</option>
                </select>
            </div>

            <div class="input-group">
                <label>Tính Cách / System Prompt</label>
                <textarea id="cfgPrompt" rows="3"></textarea>
            </div>

            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="btn-primary" style="flex: 1;" onclick="submitSaveDeviceConfig()">Lưu Cấu Hình</button>
                <button class="btn-primary" style="background: #e2e8f0; color: #475569;" onclick="closeConfigModal()">Đóng</button>
            </div>
        </div>
    </div>

    <script>
        let currentUser = null;
        let selectedDevice = null;
        let userDevices = [];

        async function loginSocial(provider) {
            const res = await fetch('/api/portal/auth', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ provider: provider })
            });
            const data = await res.json();
            if (data.success) {
                currentUser = data.user;
                renderNavbarUser();
                document.getElementById('authScreen').style.display = 'none';
                document.getElementById('dashboardScreen').style.display = 'block';
                loadUserDevices();
            }
        }

        function renderNavbarUser() {
            const el = document.getElementById('userSection');
            el.innerHTML = `
                <img src="${currentUser.avatar}" style="width: 32px; height: 32px; border-radius: 50%;" onerror="this.src='https://ui-avatars.com/api/?name=${currentUser.name}'">
                <div style="font-size: 13px;"><strong>${currentUser.name}</strong><br><small style="color: var(--muted);">${currentUser.email}</small></div>
                <button onclick="logout()" style="background: none; border: 1px solid var(--border); padding: 4px 8px; border-radius: 6px; cursor: pointer; font-size: 12px; margin-left: 8px;">Thoát</button>
            `;
        }

        function logout() {
            currentUser = null;
            document.getElementById('authScreen').style.display = 'block';
            document.getElementById('dashboardScreen').style.display = 'none';
            document.getElementById('userSection').innerHTML = `<span style="color: var(--muted); font-size: 14px;">Chưa đăng nhập</span>`;
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
                    <div style="font-size: 12px; color: var(--muted); margin-bottom: 12px;">ID: ${d.device_id}</div>
                    <div style="font-size: 13px; background: #f1f5f9; padding: 6px 10px; border-radius: 6px;">
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
    </script>
</body>
</html>
"""
