"""
Cloudflare Tunnel Manager & Web OAuth Login
-------------------------------------------
Tự động:
  1. Kiểm tra / Tải cloudflared chính thức
  2. Đăng nhập qua Web chính thức: https://dash.cloudflare.com
  3. Quản lý chứng chỉ cert.pem và Named Tunnel
  4. Hỗ trợ fallback Quick Tunnel (trycloudflare.com) nếu chưa đăng nhập
"""

import os
import sys
import json
import shutil
import asyncio
import platform
import logging
import subprocess
import re

logger = logging.getLogger("nioh.cf_tunnel")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_DIR = os.path.join(BASE_DIR, ".cloudflared")
CF_BIN = os.path.join(CF_DIR, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")

# Đường dẫn chứng chỉ gốc của Cloudflare sau khi đăng nhập web
USER_HOME = os.path.expanduser("~")
SYSTEM_CERT_PATH = os.path.join(USER_HOME, ".cloudflared", "cert.pem")
LOCAL_CERT_PATH = os.path.join(CF_DIR, "cert.pem")

TUNNEL_NAME = "nioh-server"
_login_proc = None
_tunnel_proc = None


def get_cert_path() -> str:
    """Trả về đường dẫn cert.pem nếu đã tồn tại."""
    if os.path.exists(SYSTEM_CERT_PATH):
        return SYSTEM_CERT_PATH
    if os.path.exists(LOCAL_CERT_PATH):
        return LOCAL_CERT_PATH
    return ""


def is_cloudflare_logged_in() -> bool:
    """Kiểm tra xem máy này đã đăng nhập và cấp chứng chỉ từ Cloudflare chưa."""
    cert = get_cert_path()
    return bool(cert and os.path.exists(cert) and os.path.getsize(cert) > 0)


async def ensure_cloudflared():
    """Đảm bảo cloudflared có sẵn."""
    if os.path.exists(CF_BIN):
        return

    # Kiểm tra trong Program Files nếu là Windows
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


async def start_web_login() -> dict:
    """
    Gọi `cloudflared tunnel login`.
    Mở trình duyệt trực tiếp vào https://dash.cloudflare.com/argotunnel?...
    để người dùng đăng nhập tài khoản Cloudflare chính chủ.
    """
    global _login_proc
    await ensure_cloudflared()

    if is_cloudflare_logged_in():
        return {
            "success": True,
            "status": "already_logged_in",
            "message": "Máy này đã liên kết tài khoản Cloudflare từ trước (cert.pem hợp lệ)!",
            "cert_path": get_cert_path(),
        }

    # Hủy tiến trình login cũ nếu đang chạy dở
    if _login_proc:
        try:
            _login_proc.terminate()
        except Exception:
            pass

    _login_proc = await asyncio.create_subprocess_exec(
        CF_BIN, "tunnel", "login",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    auth_url = ""
    # Đọc output để trích xuất URL đăng nhập Cloudflare
    for _ in range(25):
        line = await asyncio.wait_for(_login_proc.stderr.readline(), timeout=5)
        text = line.decode("utf-8", errors="replace").strip()
        logger.info(f"CF Login: {text}")
        if "dash.cloudflare.com" in text:
            m = re.search(r'https://dash\.cloudflare\.com/argotunnel\?[^\s]+', text)
            if m:
                auth_url = m.group(0)
                break

    if not auth_url:
        auth_url = "https://dash.cloudflare.com"

    # Mở trình duyệt vào trang web chính thức Cloudflare
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
        "message": "Đã mở trang đăng nhập Cloudflare trên trình duyệt. Vui lòng chọn domain để ủy quyền!",
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
    - Nếu đã đăng nhập Cloudflare và có domain -> chạy Named Tunnel chính chủ
    - Nếu chưa -> tự động chạy Quick Tunnel (trycloudflare.com)
    """
    global _tunnel_proc
    await ensure_cloudflared()

    if is_cloudflare_logged_in() and domain:
        return await _run_named_tunnel(local_port, domain)
    else:
        return await _run_quick_tunnel(local_port)


async def _run_quick_tunnel(local_port: int) -> str:
    global _tunnel_proc
    logger.info(f"Chạy Cloudflare Quick Tunnel cho port {local_port}...")

    _tunnel_proc = await asyncio.create_subprocess_exec(
        CF_BIN, "tunnel", "--url", f"http://localhost:{local_port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    url = None
    for _ in range(60):
        line = await asyncio.wait_for(_tunnel_proc.stderr.readline(), timeout=5)
        text = line.decode("utf-8", errors="replace")
        if "trycloudflare.com" in text:
            m = re.search(r'https://[\w-]+\.trycloudflare\.com', text)
            if m:
                url = m.group(0)
                break

    if not url:
        _tunnel_proc.kill()
        raise RuntimeError("Không thể nhận URL từ Cloudflare Tunnel.")

    wss_url = url.replace("https://", "wss://") + "/xiaozhi/v1/"
    logger.info(f"Quick Tunnel sẵn sàng: {wss_url}")
    return wss_url


async def _run_named_tunnel(local_port: int, domain: str) -> str:
    global _tunnel_proc
    cert = get_cert_path()
    logger.info(f"Chạy Named Tunnel '{TUNNEL_NAME}' với domain {domain}...")

    # Tạo tunnel nếu chưa có
    subprocess.run([CF_BIN, "tunnel", "--origincert", cert, "create", TUNNEL_NAME], capture_output=True, text=True)
    subprocess.run([CF_BIN, "tunnel", "--origincert", cert, "route", "dns", TUNNEL_NAME, domain], capture_output=True, text=True)

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
