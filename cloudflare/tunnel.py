"""
Cloudflare Tunnel Manager
-------------------------
Tự động:
  1. Download cloudflared nếu chưa có
  2. Tạo tunnel named (lưu UUID vào .env)
  3. Start tunnel → lấy public WSS URL
  4. Trả về URL để NodeRegistry dùng
"""

import os
import sys
import json
import shutil
import asyncio
import platform
import logging
import subprocess
import tempfile

logger = logging.getLogger("nioh.cf_tunnel")

CF_DIR = os.path.join(os.path.dirname(__file__), "..", ".cloudflared")
CF_BIN = os.path.join(CF_DIR, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")

CLOUDFLARED_RELEASES = {
    ("linux", "x86_64"): "cloudflared-linux-amd64",
    ("linux", "aarch64"): "cloudflared-linux-arm64",
    ("linux", "armv7l"): "cloudflared-linux-arm",
    ("darwin", "arm64"): "cloudflared-darwin-arm64.tgz",
    ("darwin", "x86_64"): "cloudflared-darwin-amd64.tgz",
    ("windows", "AMD64"): "cloudflared-windows-amd64.exe",
}

TUNNEL_NAME = "nioh-server"


def _cf_asset_name() -> str:
    sys_os = sys.platform
    machine = platform.machine()
    if sys_os.startswith("linux"):
        key = ("linux", machine)
    elif sys_os == "darwin":
        key = ("darwin", machine)
    elif sys_os == "win32":
        key = ("windows", machine)
    else:
        raise RuntimeError(f"Hệ điều hành không được hỗ trợ: {sys_os}")
    name = CLOUDFLARED_RELEASES.get(key)
    if not name:
        raise RuntimeError(f"Không tìm thấy cloudflared cho {key}")
    return name


async def ensure_cloudflared():
    """Download cloudflared nếu chưa có."""
    if os.path.exists(CF_BIN):
        return
    os.makedirs(CF_DIR, exist_ok=True)
    asset = _cf_asset_name()
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
    logger.info(f"Đang tải cloudflared từ {url} ...")

    if shutil.which("curl"):
        proc = await asyncio.create_subprocess_exec(
            "curl", "-fsSL", "-o", CF_BIN, url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Tải cloudflared thất bại: {err.decode()}")
    else:
        # Dùng Python urllib
        import urllib.request
        urllib.request.urlretrieve(url, CF_BIN)

    if sys.platform != "win32":
        os.chmod(CF_BIN, 0o755)
    logger.info("cloudflared đã tải xong.")


async def setup_tunnel(local_port: int) -> str:
    """
    Tạo / khởi động Cloudflare Tunnel.
    Trả về public WSS URL (wss://xxxx.trycloudflare.com hoặc tên domain nếu đã cấu hình).
    
    Mode:
    - Nếu NIOH_CF_DOMAIN được set → dùng named tunnel với domain tùy chỉnh
    - Nếu không → dùng quick tunnel (trycloudflare.com) — không cần đăng nhập
    """
    await ensure_cloudflared()

    cf_domain = os.environ.get("NIOH_CF_DOMAIN", "")

    if cf_domain:
        return await _named_tunnel(local_port, cf_domain)
    else:
        return await _quick_tunnel(local_port)


async def _quick_tunnel(local_port: int) -> str:
    """
    Quick tunnel — không cần account Cloudflare.
    Tự động lấy URL từ log output.
    """
    logger.info("Dùng Cloudflare Quick Tunnel (trycloudflare.com) ...")
    proc = await asyncio.create_subprocess_exec(
        CF_BIN, "tunnel", "--url", f"http://localhost:{local_port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Đọc output để tìm URL
    url = None
    for _ in range(60):  # timeout 60s
        line = await asyncio.wait_for(proc.stderr.readline(), timeout=5)
        line = line.decode("utf-8", errors="replace")
        logger.debug(f"CF: {line.strip()}")
        if "trycloudflare.com" in line:
            # Parse URL từ line
            import re
            m = re.search(r'https://[\w-]+\.trycloudflare\.com', line)
            if m:
                url = m.group(0)
                break

    if not url:
        proc.kill()
        raise RuntimeError("Không lấy được URL từ Cloudflare Quick Tunnel")

    # Store process globally để kill khi tắt
    _store_tunnel_proc(proc)
    wss_url = url.replace("https://", "wss://") + "/xiaozhi/v1/"
    logger.info(f"Tunnel URL: {wss_url}")
    return wss_url


async def _named_tunnel(local_port: int, domain: str) -> str:
    """
    Named tunnel với domain tùy chỉnh.
    Cần đã chạy `cloudflared tunnel login` trước.
    """
    tunnel_uuid = os.environ.get("NIOH_CF_TUNNEL_UUID", "")
    
    if not tunnel_uuid:
        # Tạo tunnel mới
        logger.info(f"Tạo named tunnel: {TUNNEL_NAME}")
        result = subprocess.run(
            [CF_BIN, "tunnel", "create", TUNNEL_NAME],
            capture_output=True, text=True
        )
        # Parse UUID từ output
        import re
        m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', result.stdout)
        if m:
            tunnel_uuid = m.group(0)
            _append_env("NIOH_CF_TUNNEL_UUID", tunnel_uuid)

    # Tạo config file cho cloudflared
    config_path = os.path.join(CF_DIR, "config.yml")
    cred_path = os.path.join(CF_DIR, f"{tunnel_uuid}.json")
    
    cf_config = f"""tunnel: {tunnel_uuid}
credentials-file: {cred_path}

ingress:
  - hostname: {domain}
    service: http://localhost:{local_port}
    originRequest:
      noTLSVerify: true
  - service: http_status:404
"""
    with open(config_path, "w") as f:
        f.write(cf_config)

    # Route DNS
    subprocess.run([CF_BIN, "tunnel", "route", "dns", TUNNEL_NAME, domain], check=False)

    # Start tunnel
    proc = await asyncio.create_subprocess_exec(
        CF_BIN, "tunnel", "--config", config_path, "run",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _store_tunnel_proc(proc)
    
    wss_url = f"wss://{domain}/xiaozhi/v1/"
    logger.info(f"Named tunnel URL: {wss_url}")
    return wss_url


_tunnel_proc = None

def _store_tunnel_proc(proc):
    global _tunnel_proc
    _tunnel_proc = proc


def stop_tunnel():
    global _tunnel_proc
    if _tunnel_proc:
        try:
            _tunnel_proc.kill()
        except Exception:
            pass


def _append_env(key: str, value: str):
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = []
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    lines = [l for l in lines if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}\n")
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

