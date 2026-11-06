"""
Cloudflare Tunnel Manager & Web OAuth Login
-------------------------------------------
1. Kiểm tra / Tải cloudflared chính thức
2. Mở web chính thức https://dash.cloudflare.com để người dùng đăng nhập & cấp chứng chỉ cert.pem
3. Quản lý chứng chỉ cert.pem và Named Tunnel
4. Yêu cầu bắt buộc đăng nhập Cloudflare trước khi tạo tunnel công khai
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

logger = logging.getLogger("nioh.cf_tunnel")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_DIR = os.path.join(BASE_DIR, ".cloudflared")
CF_BIN = os.path.join(CF_DIR, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")
LOGIN_LOG = os.path.join(CF_DIR, "login.log")

USER_HOME = os.path.expanduser("~")
SYSTEM_CERT_PATH = os.path.join(USER_HOME, ".cloudflared", "cert.pem")
LOCAL_CERT_PATH = os.path.join(CF_DIR, "cert.pem")

TUNNEL_NAME = "nioh-server"
_login_proc = None
_tunnel_proc = None


def get_cert_path() -> str:
    """Trả về đường dẫn cert.pem nếu đã tồn tại."""
    if os.path.exists(SYSTEM_CERT_PATH) and os.path.getsize(SYSTEM_CERT_PATH) > 0:
        return SYSTEM_CERT_PATH
    if os.path.exists(LOCAL_CERT_PATH) and os.path.getsize(LOCAL_CERT_PATH) > 0:
        return LOCAL_CERT_PATH
    return ""


def is_cloudflare_logged_in() -> bool:
    """Kiểm tra máy này đã đăng nhập và cấp chứng chỉ từ Cloudflare chưa."""
    cert = get_cert_path()
    return bool(cert and os.path.exists(cert) and os.path.getsize(cert) > 0)


async def ensure_cloudflared():
    """Đảm bảo cloudflared có sẵn."""
    if os.path.exists(CF_BIN):
        return

    # Kiểm tra trong Program Files
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
    """
    Gọi `cloudflared tunnel login`.
    Mở trình duyệt trực tiếp vào https://dash.cloudflare.com/argotunnel?...
    để người dùng đăng nhập tài khoản Cloudflare chính chủ.
    """
    global _login_proc
    os.makedirs(CF_DIR, exist_ok=True)

    if is_cloudflare_logged_in():
        return {
            "success": True,
            "status": "already_logged_in",
            "message": "Máy này đã liên kết tài khoản Cloudflare từ trước (cert.pem hợp lệ)!",
            "cert_path": get_cert_path(),
        }

    # Hủy tiến trình login cũ nếu đang chạy
    if _login_proc:
        try:
            _login_proc.terminate()
        except Exception:
            pass

    # Ghi log ra file để đọc URL không bị nghẽn buffer trên Windows
    log_file = open(LOGIN_LOG, "w", encoding="utf-8")
    _login_proc = subprocess.Popen(
        [CF_BIN, "tunnel", "login"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Đợi 2 giây để cloudflared in URL
    time.sleep(2)
    auth_url = ""
    try:
        with open(LOGIN_LOG, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            m = re.search(r'https://dash\.cloudflare\.com/argotunnel\?[^\s]+', content)
            if m:
                auth_url = m.group(0)
    except Exception as e:
        logger.warning(f"Lỗi đọc login log: {e}")

    if not auth_url:
        auth_url = "https://dash.cloudflare.com"

    # Mở trình duyệt vào link chính thức của Cloudflare
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
        "status": "waiting_user_auth",
        "auth_url": auth_url,
        "message": "Đang mở trang web dash.cloudflare.com trên trình duyệt. Vui lòng đăng nhập và chọn domain để ủy quyền!",
    }


def check_login_status() -> dict:
    """Kiểm tra trạng thái xác thực Cloudflare."""
    logged_in = is_cloudflare_logged_in()
    return {
        "logged_in": logged_in,
        "cert_path": get_cert_path() if logged_in else "",
        "message": "Đã liên kết tài khoản Cloudflare thành công!" if logged_in else "Chưa liên kết tài khoản Cloudflare.",
    }


async def setup_tunnel(local_port: int, domain: str = "") -> str:
    """
    Tạo và chạy Cloudflare Tunnel:
    BẮT BUỘC phải đăng nhập tài khoản Cloudflare trước.
    """
    global _tunnel_proc
    await ensure_cloudflared()

    if not is_cloudflare_logged_in():
        raise RuntimeError("CHƯA ĐĂNG NHẬP CLOUDFLARE: Bạn cần nhấp nút 'ĐĂNG NHẬP QUA WEB CLOUDFLARE' trước!")

    cert = get_cert_path()
    if not domain:
        # Nếu chưa điền domain, tự động lấy domain đầu tiên hoặc cảnh báo
        raise RuntimeError("Vui lòng nhập tên miền riêng (Domain) bạn đã ủy quyền trên Cloudflare (ví dụ: voice.yourdomain.com)!")

    logger.info(f"Khởi tạo Named Tunnel '{TUNNEL_NAME}' với domain {domain}...")

    # Tạo tunnel nếu chưa có
    subprocess.run([CF_BIN, "tunnel", "--origincert", cert, "create", TUNNEL_NAME], capture_output=True, text=True)
    subprocess.run([CF_BIN, "tunnel", "--origincert", cert, "route", "dns", "-f", TUNNEL_NAME, domain], capture_output=True, text=True)

    _tunnel_proc = await asyncio.create_subprocess_exec(
        CF_BIN, "tunnel", "--url", f"http://localhost:{local_port}", "run", TUNNEL_NAME,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    wss_url = f"wss://{domain}/xiaozhi/v1/"
    return wss_url


def stop_tunnel():
    global _tunnel_proc
    if _tunnel_proc:
        try:
            _tunnel_proc.terminate()
        except Exception:
            pass
        _tunnel_proc = None
