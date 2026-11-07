"""
Ni-Oh Server Node Registry
--------------------------
Dùng GitHub Gist làm config store miễn phí.
Mỗi node đăng ký WSS endpoint của mình vào Gist khi khởi động.
ESP32 lấy danh sách endpoints từ Gist qua HTTP.

Flow:
  1. Node khởi động → đọc NIOH_GITHUB_TOKEN + NIOH_GIST_ID từ env
  2. Nếu chưa có GIST_ID → tạo Gist mới → lưu ID vào .env
  3. Đọc danh sách nodes hiện có → thêm node này → ghi lại
  4. Khi tắt → xóa node này khỏi danh sách
"""

import os
import json
import uuid
import socket
import asyncio
import aiohttp
import logging

logger = logging.getLogger("xiaozhivn.node_registry")

GIST_API = "https://api.github.com/gists"
GIST_FILENAME = "xiaozhivn_nodes.json"
HEARTBEAT_INTERVAL = 60  # seconds


class NodeRegistry:
    def __init__(self):
        self.token = os.environ.get("NIOH_GITHUB_TOKEN", "")
        self.gist_id = os.environ.get("NIOH_GIST_ID", "")
        self.node_id = os.environ.get("NIOH_NODE_ID", str(uuid.uuid4())[:8])
        self.wss_url = os.environ.get("NIOH_WSS_URL", "")  # set sau khi CF tunnel up
        self._heartbeat_task = None

    @property
    def _headers(self):
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

    async def _get_gist(self, session: aiohttp.ClientSession) -> dict:
        async with session.get(f"{GIST_API}/{self.gist_id}", headers=self._headers) as r:
            r.raise_for_status()
            return await r.json()

    async def _update_gist(self, session: aiohttp.ClientSession, nodes: dict):
        payload = {
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps(nodes, indent=2, ensure_ascii=False)
                }
            }
        }
        async with session.patch(
            f"{GIST_API}/{self.gist_id}", headers=self._headers, json=payload
        ) as r:
            r.raise_for_status()

    async def _create_gist(self, session: aiohttp.ClientSession) -> str:
        """Tạo Gist mới nếu chưa có, trả về gist_id."""
        payload = {
            "description": "Ni-Oh Server Node Registry",
            "public": False,
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps({"nodes": {}, "config": {}}, indent=2)
                }
            },
        }
        async with session.post(GIST_API, headers=self._headers, json=payload) as r:
            r.raise_for_status()
            data = await r.json()
            return data["id"]

    async def _read_nodes(self, session: aiohttp.ClientSession) -> dict:
        try:
            gist = await self._get_gist(session)
            content = gist["files"][GIST_FILENAME]["content"]
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Không đọc được node list: {e}")
            return {"nodes": {}, "config": {}}

    async def register(self):
        """Đăng ký node này vào Gist. Gọi sau khi CF tunnel đã có URL."""
        if not self.token:
            logger.warning("NIOH_GITHUB_TOKEN không được set → bỏ qua đồng bộ node")
            return

        async with aiohttp.ClientSession() as session:
            # Tạo Gist nếu chưa có
            if not self.gist_id:
                self.gist_id = await self._create_gist(session)
                logger.info(f"Đã tạo Gist mới: {self.gist_id}")
                # Lưu vào .env để lần sau dùng lại
                _append_env("NIOH_GIST_ID", self.gist_id)

            data = await self._read_nodes(session)
            nodes = data.get("nodes", {})
            nodes[self.node_id] = {
                "wss_url": self.wss_url,
                "hostname": socket.gethostname(),
                "last_seen": _now_iso(),
                "version": "1.0.0",
            }
            data["nodes"] = nodes
            await self._update_gist(session, data)
            logger.info(f"Node {self.node_id} đã đăng ký → {self.wss_url}")

    async def unregister(self):
        """Xóa node này khỏi danh sách khi tắt."""
        if not self.token or not self.gist_id:
            return
        async with aiohttp.ClientSession() as session:
            data = await self._read_nodes(session)
            data.get("nodes", {}).pop(self.node_id, None)
            await self._update_gist(session, data)
            logger.info(f"Node {self.node_id} đã unregister")

    async def heartbeat_loop(self):
        """Cập nhật last_seen mỗi 60s để node không bị coi là offline."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await self.register()
            except Exception as e:
                logger.warning(f"Heartbeat lỗi: {e}")

    def start_heartbeat(self):
        self._heartbeat_task = asyncio.create_task(self.heartbeat_loop())

    async def stop(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self.unregister()

    async def get_all_nodes(self) -> list[str]:
        """Trả về danh sách WSS URLs của tất cả nodes đang online."""
        if not self.token or not self.gist_id:
            return []
        async with aiohttp.ClientSession() as session:
            data = await self._read_nodes(session)
            return [v["wss_url"] for v in data.get("nodes", {}).values() if v.get("wss_url")]

    async def get_shared_config(self) -> dict:
        """Lấy config chung (api_key, model...) từ Gist."""
        if not self.token or not self.gist_id:
            return {}
        async with aiohttp.ClientSession() as session:
            data = await self._read_nodes(session)
            return data.get("config", {})

    async def push_config(self, cfg: dict):
        """Đẩy config lên Gist để tất cả nodes đồng bộ."""
        if not self.token or not self.gist_id:
            return
        async with aiohttp.ClientSession() as session:
            data = await self._read_nodes(session)
            data["config"] = cfg
            await self._update_gist(session, data)


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _append_env(key: str, value: str):
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = []
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    # Xóa dòng cũ nếu có
    lines = [l for l in lines if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}\n")
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

