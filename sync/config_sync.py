"""
Ni-Oh Config Sync
-----------------
Load config theo thứ tự ưu tiên:
  1. Biến môi trường (NIOH_*)
  2. File .env local
  3. GitHub Gist (shared config — đồng bộ giữa các nodes)
  4. File config.yaml mặc định của xiaozhi-server

Không có giá trị nào hardcode vào source code.
"""

import os
import logging
from dotenv import load_dotenv
from sync.node_registry import NodeRegistry

logger = logging.getLogger("nioh.config_sync")


async def load_nioh_config() -> dict:
    """
    Trả về dict config đầy đủ để inject vào xiaozhi-server.
    Ghi đè các key quan trọng từ Gist/env.
    """
    # 1. Load .env
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(env_path, override=False)

    registry = NodeRegistry()
    remote_cfg = {}

    # 2. Lấy config từ Gist nếu có token
    if registry.token and registry.gist_id:
        try:
            remote_cfg = await registry.get_shared_config()
            logger.info(f"Đã load config từ Gist ({len(remote_cfg)} keys)")
        except Exception as e:
            logger.warning(f"Không lấy được config từ Gist: {e}")

    # 3. Merge: env > Gist > default
    def _get(key: str, default: str = "") -> str:
        return os.environ.get(key) or remote_cfg.get(key, default)

    cfg = {
        "llm": {
            "type": "openai",
            "base_url": _get("NIOH_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            "api_key": _get("NIOH_API_KEY"),
            "model": _get("NIOH_MODEL", "deepseek/deepseek-chat"),
        },
        "asr": {
            "type": _get("NIOH_ASR_TYPE", "doubao"),
            "api_key": _get("NIOH_ASR_KEY"),
        },
        "tts": {
            "type": _get("NIOH_TTS_TYPE", "doubao"),
            "api_key": _get("NIOH_TTS_KEY"),
        },
        "server": {
            "port": int(_get("NIOH_WS_PORT", "8000")),
            "http_port": int(_get("NIOH_HTTP_PORT", "8003")),
        },
    }

    return cfg, registry

