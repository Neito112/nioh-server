import asyncio
import os
import sys
import uuid
import random
import unittest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from server.desktop_app import create_application


class TestNiOhDualServer(AioHTTPTestCase):

    async def get_application(self):
        return create_application(port=8001)

    async def test_01_routing_separation(self):
        # 1. Localhost gets Desktop App Server Console
        resp_local = await self.client.get("/")
        self.assertEqual(resp_local.status, 200)
        text_local = await resp_local.text()
        self.assertIn("Ni-Oh Voice Server", text_local)
        self.assertIn("Host Console", text_local)

        # 2. Remote Cloudflare host gets Web Portal
        resp_cf = await self.client.get("/", headers={"Host": "super-tunnel.trycloudflare.com"})
        self.assertEqual(resp_cf.status, 200)
        text_cf = await resp_cf.text()
        self.assertIn("Ni-Oh Voice Portal", text_cf)
        self.assertIn("Bảng Quản Trị Thiết Bị", text_cf)

        # 3. /portal path always returns Web Portal
        resp_portal = await self.client.get("/portal")
        self.assertEqual(resp_portal.status, 200)
        text_p = await resp_portal.text()
        self.assertIn("Ni-Oh Voice Portal", text_p)

    async def test_02_app_server_apis(self):
        # GET /api/gateway/status
        resp = await self.client.get("/api/gateway/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("server_running", data)
        self.assertIn("server_setup", data)
        self.assertIn("live_clients", data)
        self.assertIn("active_clients_count", data)

        # POST /api/gateway/save-setup with real technical parameters
        save_resp = await self.client.post("/api/gateway/save-setup", json={
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-real-test-key",
            "model": "deepseek-chat",
            "voice": "vi-VN-HoaiMyNeural",
            "speech_rate": "+0%",
            "enable_weather": "1",
            "enable_search": "1",
            "enable_pc_control": "1"
        })
        self.assertEqual(save_resp.status, 200)
        save_data = await save_resp.json()
        self.assertTrue(save_data["success"])

        # Check that status reflects updated setup
        resp2 = await self.client.get("/api/gateway/status")
        data2 = await resp2.json()
        self.assertEqual(data2["server_setup"]["model"], "deepseek-chat")
        self.assertEqual(data2["server_setup"]["base_url"], "https://api.deepseek.com")

    async def test_03_web_server_agent_and_device_flow(self):
        u_suffix = uuid.uuid4().hex[:6]
        email = f"user_{u_suffix}@example.com"

        # 1. Register test user
        reg_resp = await self.client.post("/api/portal/register", json={
            "email": email,
            "password": "securePassword123",
            "name": f"Developer {u_suffix}"
        })
        reg_data = await reg_resp.json()
        self.assertTrue(reg_data["success"])
        user_id = reg_data["user"]["user_id"]

        # 2. Get default agent created automatically
        ag_resp = await self.client.get(f"/api/portal/agents?user_id={user_id}")
        ag_data = await ag_resp.json()
        self.assertTrue(ag_data["success"])
        self.assertGreaterEqual(len(ag_data["agents"]), 1)
        default_agent_id = ag_data["agents"][0]["id"]

        # 3. Create a custom Agent (e.g. English Tutor)
        custom_ag_resp = await self.client.post("/api/portal/agents", json={
            "user_id": user_id,
            "name": "Trợ Lý Ngôn Ngữ",
            "model": "deepseek-chat",
            "voice": "vi-VN-NamMinhNeural",
            "api_key": "",
            "prompt": "Bạn là giáo viên ngoại ngữ hỗ trợ giải đáp thắc mắc ngữ pháp."
        })
        self.assertTrue((await custom_ag_resp.json())["success"])

        # Check agents list has 2 agents now
        ag_resp2 = await self.client.get(f"/api/portal/agents?user_id={user_id}")
        ag_data2 = await ag_resp2.json()
        self.assertEqual(len(ag_data2["agents"]), 2)
        new_agent = [a for a in ag_data2["agents"] if a["name"] == "Trợ Lý Ngôn Ngữ"][0]

        # 4. Pair device via 6-digit PIN
        pin_code = str(random.randint(100000, 999999))
        bind_resp = await self.client.post("/api/portal/bind", json={
            "user_id": user_id,
            "pairing_code": pin_code,
            "bot_name": "Mạch Phòng Làm Việc",
            "agent_id": default_agent_id
        })
        bind_data = await bind_resp.json()
        self.assertTrue(bind_data["success"])

        # 5. Get devices and verify pairing
        dev_resp = await self.client.get(f"/api/portal/devices?user_id={user_id}")
        dev_data = await dev_resp.json()
        self.assertTrue(dev_data["success"])
        self.assertEqual(len(dev_data["devices"]), 1)
        device = dev_data["devices"][0]
        self.assertEqual(device["pairing_code"], pin_code)
        self.assertEqual(device["agent_id"], default_agent_id)

        # 6. Assign the device to the new Agent
        assign_resp = await self.client.post("/api/portal/assign-agent", json={
            "user_id": user_id,
            "device_id": device["device_id"],
            "agent_id": new_agent["id"]
        })
        self.assertTrue((await assign_resp.json())["success"])

        # Check updated device info
        dev_resp2 = await self.client.get(f"/api/portal/devices?user_id={user_id}")
        dev_data2 = await dev_resp2.json()
        self.assertEqual(dev_data2["devices"][0]["agent_id"], new_agent["id"])
        self.assertEqual(dev_data2["devices"][0]["agent_name"], "Trợ Lý Ngôn Ngữ")

    async def test_04_ota_endpoint(self):
        resp = await self.client.get("/xiaozhi/ota/")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("firmware", data)
        self.assertIn("websocket", data)
        self.assertTrue(data["websocket"]["url"].endswith("/xiaozhi/v1/"))


if __name__ == "__main__":
    unittest.main()
