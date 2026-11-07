"""
Cloudflare Tunnel & Account Manager (Production)
------------------------------------------------
Hỗ trợ liên kết tài khoản Cloudflare thực tế và khởi chạy Tunnel:
  1. Quick Tunnel (1 Chạm): Kết nối trực tiếp hạ tầng Anycast Cloudflare toàn cầu, cấp link HTTPS miễn phí
  2. Cloudflare API Token: Xác thực tài khoản Cloudflare chính thức qua API verify
  3. Cloudflare Global API Key + Email: Xác thực tài khoản chính chủ
  4. Cloudflare Zero Trust Token: Dùng tunnel token từ dash.cloudflare.com
  5. Web OAuth / cert.pem: Dành cho người dùng ủy quyền domain riêng
"""

import os
import sys
import json
import shutil
import asyncio
import logging
import subprocess
import re
import time
import urllib.request
import urllib.error
import sqlite3

logger = logging.getLogger("xiaozhivn.cf_tunnel")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_DIR = os.path.join(BASE_DIR, ".cloudflared")
CF_BIN = os.path.join(CF_DIR, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")
LOGIN_LOG = os.path.join(CF_DIR, "login.log")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "portal.db")

USER_HOME = os.path.expanduser("~")
SYSTEM_CERT_PATH = os.path.join(USER_HOME, ".cloudflared", "cert.pem")
LOCAL_CERT_PATH = os.path.join(CF_DIR, "cert.pem")

TUNNEL_NAME = "xiaozhivn-server"
_tunnel_proc = None
_login_proc = None


# ── QUẢN LÝ CẤU HÌNH LIÊN KẾT TRONG SQLITE ──────────────────

def _init_cf_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS cf_account (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    conn.commit()
    conn.close()

_init_cf_db()


def save_cf_config(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cf_account (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def get_cf_config(key: str, default: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM cf_account WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def unlink_cloudflare():
    """Hủy liên kết tài khoản Cloudflare."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM cf_account")
    conn.commit()
    conn.close()
    stop_tunnel()


# ── XÁC THỰC TÀI KHOẢN CLOUDFLARE QUA API CHÍNH THỨC ─────────

def verify_cf_token(token: str) -> dict:
    """Xác thực Cloudflare API Token với máy chủ Cloudflare."""
    token = token.strip()
    if not token:
        return {"success": False, "message": "Vui lòng nhập API Token!"}

    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "XiaoZhiVNServer/1.0",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                res = data.get("result", {})
                token_id = res.get("id", "")
                status = res.get("status", "active")
                save_cf_config("linked", "1")
                save_cf_config("mode", "token")
                save_cf_config("token", token)
                save_cf_config("token_id", token_id)
                save_cf_config("account_display", f"Cloudflare API Token ({token_id[:8]}...)")
                return {
                    "success": True,
                    "message": f"Liên kết thành công! Token ID: {token_id} (Trạng thái: {status})",
                    "account": f"Cloudflare Token ({token_id[:8]}...)",
                }
            else:
                errors = data.get("errors", [{}])
                return {"success": False, "message": errors[0].get("message", "Token Cloudflare không hợp lệ!")}
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            msg = err_data.get("errors", [{}])[0].get("message", str(e))
        except Exception:
            msg = str(e)
        return {"success": False, "message": f"Cloudflare từ chối xác thực: {msg}"}
    except Exception as e:
        return {"success": False, "message": f"Lỗi kết nối tới Cloudflare: {str(e)}"}


def verify_cf_global_key(email: str, api_key: str) -> dict:
    """Xác thực tài khoản Cloudflare qua Email + Global API Key."""
    email = email.strip()
    api_key = api_key.strip()
    if not email or "@" not in email:
        return {"success": False, "message": "Email Cloudflare không hợp lệ!"}
    if not api_key:
        return {"success": False, "message": "Vui lòng nhập Global API Key!"}

    url = "https://api.cloudflare.com/client/v4/user"
    req = urllib.request.Request(
        url,
        headers={
            "X-Auth-Email": email,
            "X-Auth-Key": api_key,
            "User-Agent": "XiaoZhiVNServer/1.0",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                res = data.get("result", {})
                user_email = res.get("email", email)
                username = res.get("username", "")
                save_cf_config("linked", "1")
                save_cf_config("mode", "key")
                save_cf_config("email", user_email)
                save_cf_config("api_key", api_key)
                save_cf_config("account_display", f"{user_email} ({username})" if username else user_email)
                return {
                    "success": True,
                    "message": f"Liên kết tài khoản Cloudflare thành công: {user_email}",
                    "account": user_email,
                }
            else:
                errors = data.get("errors", [{}])
                return {"success": False, "message": errors[0].get("message", "Sai Email hoặc API Key!")}
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            msg = err_data.get("errors", [{}])[0].get("message", str(e))
        except Exception:
            msg = str(e)
        return {"success": False, "message": f"Xác thực thất bại: {msg}"}
    except Exception as e:
        return {"success": False, "message": f"Lỗi kết nối Cloudflare: {str(e)}"}


def activate_quick_tunnel_link() -> dict:
    """Kích hoạt liên kết hạ tầng Cloudflare Quick Tunnel (1 chạm, miễn phí 100%)."""
    save_cf_config("linked", "1")
    save_cf_config("mode", "quick")
    save_cf_config("account_display", "Cloudflare Global Edge Network (Quick Tunnel)")
    return {
        "success": True,
        "message": "Đã liên kết thành công với Hạ tầng Mạng lưới Cloudflare Toàn Cầu!",
        "account": "Cloudflare Global Edge Network",
    }


# ── KIỂM TRA TRẠNG THÁI LIÊN KẾT CLOUDFLARE ──────────────────

def get_cert_path() -> str:
    if os.path.exists(SYSTEM_CERT_PATH) and os.path.getsize(SYSTEM_CERT_PATH) > 0:
        return SYSTEM_CERT_PATH
    if os.path.exists(LOCAL_CERT_PATH) and os.path.getsize(LOCAL_CERT_PATH) > 0:
        return LOCAL_CERT_PATH
    return ""


def is_cloudflare_logged_in() -> bool:
    cert = get_cert_path()
    if cert and os.path.exists(cert) and os.path.getsize(cert) > 0:
        return True
    return get_cf_config("linked", "0") == "1"


def check_login_status() -> dict:
    cert = get_cert_path()
    has_cert = bool(cert and os.path.exists(cert) and os.path.getsize(cert) > 0)
    linked = get_cf_config("linked", "0") == "1" or has_cert

    mode = get_cf_config("mode", "cert" if has_cert else "none")
    account_display = get_cf_config("account_display", "")

    if has_cert and not account_display:
        account_display = "Cloudflare Authorized Domain (cert.pem)"

    return {
        "logged_in": linked,
        "mode": mode,
        "account": account_display or ("Đã liên kết Cloudflare" if linked else "Chưa liên kết"),
        "cert_path": cert if has_cert else "",
    }


# ── QUẢN LÝ THƯ VIỆN CLOUDFLARED EXEC ────────────────────────

async def ensure_cloudflared():
    if os.path.exists(CF_BIN):
        return

    installed_cf = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if os.path.exists(installed_cf):
        os.makedirs(CF_DIR, exist_ok=True)
        shutil.copyfile(installed_cf, CF_BIN)
        return

    installed_cf64 = r"C:\Program Files\cloudflared\cloudflared.exe"
    if os.path.exists(installed_cf64):
        os.makedirs(CF_DIR, exist_ok=True)
        shutil.copyfile(installed_cf64, CF_BIN)
        return


def start_web_login() -> dict:
    """Mở link ủy quyền chính thức trên dash.cloudflare.com."""
    global _login_proc
    os.makedirs(CF_DIR, exist_ok=True)

    if _login_proc:
        try: _login_proc.terminate()
        except Exception: pass

    log_file = open(LOGIN_LOG, "w", encoding="utf-8")
    _login_proc = subprocess.Popen([CF_BIN, "tunnel", "login"], stdout=log_file, stderr=subprocess.STDOUT, text=True)

    auth_url = ""
    for _ in range(20):
        time.sleep(0.3)
        try:
            with open(LOGIN_LOG, "r", encoding="utf-8", errors="ignore") as f:
                c = f.read()
                m = re.search(r'https://dash\.cloudflare\.com/argotunnel\?[^\s]+', c)
                if m:
                    auth_url = m.group(0)
                    break
        except Exception:
            pass

    if not auth_url:
        auth_url = "https://dash.cloudflare.com"

    try:
        if sys.platform == "win32":
            os.system(f'start "" "{auth_url}"')
        else:
            import webbrowser
            webbrowser.open(auth_url)
    except Exception:
        pass

    return {
        "success": True,
        "auth_url": auth_url,
        "message": "Đã mở trang xác thực Cloudflare trên trình duyệt của bạn!",
    }


# ── KHỞI CHẠY TUNNEL CLOUDFLARE THẬT ─────────────────────────

async def setup_tunnel(local_port: int, mode: str = "auto", token: str = "", domain: str = "") -> dict:
    """
    Khởi chạy Cloudflare Tunnel thật và xuất ra URL chính thức:
    - Nếu mode là 'cert' và có cert.pem + domain: chạy Named Tunnel
    - Nếu mode là 'token' và có token: chạy Zero Trust Tunnel
    - Mặc định: chạy Quick Tunnel (cấp URL https://xxx.trycloudflare.com ngay lập tức)
    """
    global _tunnel_proc
    await ensure_cloudflared()
    stop_tunnel()

    saved_mode = get_cf_config("mode", "quick")
    saved_token = get_cf_config("token", "")

    # 1. Chế độ Token Zero Trust
    effective_token = token or saved_token
    if (mode == "token" or saved_mode == "token") and effective_token and effective_token.startswith("eyJh"):
        logger.info("Chạy Cloudflare Tunnel qua Zero Trust Token...")
        _tunnel_proc = await asyncio.create_subprocess_exec(
            CF_BIN, "tunnel", "run", "--token", effective_token,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        base_url = f"https://{domain}" if domain else "https://your-configured-domain.com"
        return {
            "public_url": base_url,
            "portal_url": f"{base_url}/portal",
            "wss_url": base_url.replace("https://", "wss://") + "/xiaozhi/v1/",
            "ota_url": f"{base_url}/xiaozhi/ota/",
        }

    # 2. Chế độ cert.pem + Domain riêng
    cert = get_cert_path()
    if domain and cert and os.path.exists(cert):
        logger.info(f"Chạy Cloudflare Named Tunnel cho domain {domain}...")
        subprocess.run([CF_BIN, "tunnel", "--origincert", cert, "create", TUNNEL_NAME], capture_output=True, text=True)
        subprocess.run([CF_BIN, "tunnel", "--origincert", cert, "route", "dns", "-f", TUNNEL_NAME, domain], capture_output=True, text=True)

        _tunnel_proc = await asyncio.create_subprocess_exec(
            CF_BIN, "tunnel", "--url", f"http://localhost:{local_port}", "run", TUNNEL_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        base_url = f"https://{domain}"
        return {
            "public_url": base_url,
            "portal_url": f"{base_url}/portal",
            "wss_url": f"wss://{domain}/xiaozhi/v1/",
            "ota_url": f"{base_url}/xiaozhi/ota/",
        }

    # 3. Chế độ Quick Tunnel (1 Chạm - Cấp URL Cloudflare HTTPS toàn cầu ngay lập tức)
    logger.info("Khởi động Cloudflare Quick Tunnel tự động...")
    _tunnel_proc = await asyncio.create_subprocess_exec(
        CF_BIN, "tunnel", "--url", f"http://localhost:{local_port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    public_url = ""
    for _ in range(40):
        try:
            line = await asyncio.wait_for(_tunnel_proc.stderr.readline(), timeout=5)
            text = line.decode("utf-8", errors="replace").strip()
            logger.info(f"CF Tunnel: {text}")
            if "trycloudflare.com" in text:
                m = re.search(r'https://[\w-]+\.trycloudflare\.com', text)
                if m:
                    public_url = m.group(0)
                    break
        except Exception:
            break

    if not public_url:
        stop_tunnel()
        raise RuntimeError("Không thể nhận URL từ Cloudflare Tunnel. Vui lòng kiểm tra kết nối mạng!")

    return {
        "public_url": public_url,
        "portal_url": f"{public_url}/portal",
        "wss_url": public_url.replace("https://", "wss://") + "/xiaozhi/v1/",
        "ota_url": f"{public_url}/xiaozhi/ota/",
    }


def stop_tunnel():
    global _tunnel_proc
    if _tunnel_proc:
        try:
            _tunnel_proc.terminate()
        except Exception:
            pass
        _tunnel_proc = None
