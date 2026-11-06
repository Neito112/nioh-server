"""
OTA Endpoint for Ni-Oh Firmware
--------------------------------
ESP32 gọi vào đây để lấy danh sách WSS endpoints từ node registry.
Thay thế OTA server của xiaozhi, trả thêm field `websocket_endpoints`.
"""

import os
import json
import asyncio
import aiohttp
from aiohttp import web
import logging

logger = logging.getLogger("nioh.ota")


class NiOhOtaServer:
    def __init__(self, registry, http_port: int = 8003):
        self.registry = registry
        self.http_port = http_port
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/xiaozhi/ota/", self.handle_ota)
        self.app.router.add_get("/nioh/nodes", self.handle_nodes)
        self.app.router.add_get("/health", self.handle_health)

    async def handle_ota(self, request: web.Request) -> web.Response:
        """
        Trả về OTA response compatible với firmware xiaozhi/Ni-Oh.
        Firmware check firmware_url để update, và dùng websocket để connect.
        """
        nodes = await self.registry.get_all_nodes()
        
        # Lấy node đầu tiên available
        ws_url = nodes[0] if nodes else f"ws://localhost:{int(os.environ.get('NIOH_WS_PORT', 8000))}/xiaozhi/v1/"

        response = {
            "firmware": {
                "version": os.environ.get("NIOH_FIRMWARE_VERSION", "2.5.3"),
                "url": os.environ.get("NIOH_FIRMWARE_URL", ""),
            },
            "websocket": {
                "url": ws_url,
            },
            # Ni-Oh extension: tất cả node URLs để firmware chọn
            "nioh_nodes": nodes,
        }
        return web.json_response(response)

    async def handle_nodes(self, request: web.Request) -> web.Response:
        """API endpoint trả về tất cả node đang online."""
        nodes = await self.registry.get_all_nodes()
        return web.json_response({"nodes": nodes, "count": len(nodes)})

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "node_id": self.registry.node_id})

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.http_port)
        await site.start()
        logger.info(f"OTA server chạy tại port {self.http_port}")

