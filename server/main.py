"""
XiaoZhiVN Server — Entry Point
------------------------------
Thay thế app.py của xiaozhi-server.
Thêm: Cloudflare Tunnel + Node Registry + Config Sync.
"""

import os
import sys
import asyncio
import logging
import uuid

# Thêm thư mục gốc vào path để import xiaozhi modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "xiaozhi-server"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from sync.config_sync import load_nioh_config
from cloudflare.tunnel import setup_tunnel, stop_tunnel

logger = logging.getLogger("xiaozhivn.main")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)


async def main():
    print("""
╔══════════════════════════════════════════╗
║         XiaoZhiVN Distributed Server     ║
║   Xiaozhi-compatible · OpenRouter ready  ║
╚══════════════════════════════════════════╝
""")

    # 1. Load config (env → Gist → defaults)
    config, registry = await load_nioh_config()

    if not config["llm"]["api_key"]:
        logger.error("Chưa set XIAOZHIVN_API_KEY! Chạy lại setup hoặc export XIAOZHIVN_API_KEY=...")
        sys.exit(1)

    # 2. Khởi động Cloudflare Tunnel
    ws_port = config["server"]["port"]
    http_port = config["server"]["http_port"]

    logger.info("Đang khởi động Cloudflare Tunnel...")
    try:
        wss_url = await asyncio.wait_for(setup_tunnel(ws_port), timeout=90)
        registry.wss_url = wss_url
        logger.info(f"✓ Tunnel sẵn sàng: {wss_url}")
    except Exception as e:
        logger.warning(f"Tunnel thất bại: {e} → chạy local-only mode")
        wss_url = f"ws://localhost:{ws_port}/xiaozhi/v1/"
        registry.wss_url = wss_url

    # 3. Đăng ký node vào Gist
    if registry.token:
        await registry.register()
        registry.start_heartbeat()
        logger.info(f"✓ Node đăng ký thành công (ID: {registry.node_id})")
    else:
        logger.warning("NIOH_GITHUB_TOKEN không set → không đồng bộ node registry")

    # 4. Inject config vào xiaozhi-server và khởi động
    _inject_config_to_env(config)

    # Import và chạy xiaozhi-server
    try:
        from xiaozhi_server_runner import run_xiaozhi_server
        await run_xiaozhi_server(ws_port, http_port)
    except ImportError:
        # Fallback: chạy trực tiếp qua subprocess nếu chưa tích hợp
        logger.info("Chạy xiaozhi-server qua subprocess...")
        await _run_server_subprocess(ws_port, http_port)

    # 5. Cleanup
    stop_tunnel()
    await registry.stop()


def _inject_config_to_env(config: dict):
    """Inject config vào env vars để xiaozhi-server đọc."""
    llm = config["llm"]
    os.environ.setdefault("OPENAI_API_KEY", llm["api_key"])
    os.environ.setdefault("OPENAI_BASE_URL", llm["base_url"])
    os.environ.setdefault("OPENAI_MODEL", llm["model"])


async def _run_server_subprocess(ws_port: int, http_port: int):
    """Chạy xiaozhi-server như subprocess."""
    server_dir = os.path.join(os.path.dirname(__file__), "xiaozhi-server")
    app_py = os.path.join(server_dir, "app.py")
    
    if not os.path.exists(app_py):
        logger.error(f"Không tìm thấy {app_py}. Chạy install.sh/install.ps1 trước!")
        return

    proc = await asyncio.create_subprocess_exec(
        sys.executable, app_py,
        cwd=server_dir,
        env={**os.environ},
    )
    
    try:
        await proc.wait()
    except asyncio.CancelledError:
        proc.terminate()
        await proc.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nXiaoZhiVN Server đã tắt.")

