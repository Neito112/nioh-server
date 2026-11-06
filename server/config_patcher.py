"""
Xiaozhi Config Patcher
-----------------------
Patch config.yaml của xiaozhi-server với giá trị từ env/Gist,
không hardcode bất kỳ key nào.
"""

import os
import re
import logging

logger = logging.getLogger("nioh.config_patcher")

XIAOZHI_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "xiaozhi-server", "data", ".config.yaml"
)
TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "xiaozhi-server", "config.yaml"
)


def patch_xiaozhi_config(nioh_cfg: dict):
    """
    Đọc config.yaml gốc, ghi đè các giá trị từ nioh_cfg,
    output ra data/.config.yaml.
    """
    # Đọc template
    cfg_path = TEMPLATE_PATH if not os.path.exists(XIAOZHI_CONFIG_PATH) else XIAOZHI_CONFIG_PATH
    if not os.path.exists(cfg_path):
        logger.warning(f"Không tìm thấy {cfg_path}")
        return

    with open(cfg_path, "r", encoding="utf-8") as f:
        content = f.read()

    llm = nioh_cfg.get("llm", {})
    
    # Patch LLM section
    if llm.get("api_key"):
        content = _patch_yaml_key(content, "api_key", llm["api_key"])
    if llm.get("base_url"):
        content = _patch_yaml_key(content, "base_url", llm["base_url"])
    if llm.get("model"):
        content = _patch_yaml_key(content, "model", llm["model"])

    # Đảm bảo thư mục data tồn tại
    os.makedirs(os.path.dirname(XIAOZHI_CONFIG_PATH), exist_ok=True)
    
    with open(XIAOZHI_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    
    logger.info("✓ config.yaml đã được patch")


def _patch_yaml_key(content: str, key: str, value: str) -> str:
    """Thay thế giá trị của key trong YAML."""
    pattern = rf'^(\s*{re.escape(key)}\s*:\s*)(.+)$'
    replacement = rf'\g<1>{value}'
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    return new_content
