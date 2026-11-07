import asyncio
import os
import sys
import unittest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from server.desktop_app import create_application


class TestNiOhDualServer(AioHTTPTestCase):

    async def get_application(self):
        return create_application(port=8001)

    @unittest_run_loop
    async def test_01_routing_separation(self):
        # 1. Localhost gets Desktop App Server
        resp_local = await self.client.get("/")
        self.assertEqual(resp_local.status, 200)
        text_local = await resp_local.text()
        self.assertIn("Ni-Oh App Server", text_local)
        self.assertIn("CỔNG ĐIỀU KHIỂN MÁY CHỦ", text_local)

        # 2. Remote Cloudflare host gets Web Portal (xiaozhi.me clone)
        resp_cf = await self.client.get("/", headers={"Host": "super-tunnel.trycloudflare.com"})
        self.assertEqual(resp_cf.status, 200)
        text_cf = await resp_cf.text()
        self.assertIn("Ni-Oh Web Server", text_cf)
        self.assertIn("Quản Lý Agent & Thiết Bị", text_cf)

        # 3. /portal path always returns Web Portal
        resp_portal = await self.client.get("/portal")
        self.assertEqual(resp_portal.status, 200)
        text_p = await resp_portal.text()
        self.assertIn("Ni-Oh Web Server", text_p)

    @unittest_run_loop
    async def test_02_app_server_apis(self):
        # GET /api/gateway/status
        resp = await self.client.get("/api/gateway/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("server_running", data)
        self.assertIn("server_setup", data)
        self.assertIn("device_stats", data)

        # POST /api/gateway/save-setup
        save_resp = await self.client.post("/api/gateway/save-setup", json={
            "default_model": "google/gemini-2.0-flash:free",
            "server_api_key": "test-key-123",
            "enable_weather": "1",
            "enable_search": "1",
            "enable_pc_control": "0",
            "enable_music": "1"
        })
        self.assertEqual(save_resp.status, 200)
        save_data = await save_resp.json()
        self.assertTrue(save_data["success"])

        # Check that status reflects updated setup
        resp2 = await self.client.get("/api/gateway/status")
        data2 = await resp2.json()
        self.assertEqual(data2["server_setup"]["default_model"], "google/gemini-2.0-flash:free")

    @unittest_run_loop
    async def test_03_web_server_agent_and_device_flow(self):
        import uuid
        import random
        u_suffix = uuid.uuid4().hex[:6]
        email = f"tester_{u_suffix}@test.local"

        # 1. Register test user
        reg_resp = await self.client.post("/api/portal/register", json={
            "email": email,
            "password": "password123",
            "name": f"Tester {u_suffix}"
        })
        reg_data = await reg_resp.json()
        self.assertTrue(reg_data["success"])
        user_id = reg_data["user"]["user_id"]

        # 2. Get default agent
        ag_resp = await self.client.get(f"/api/portal/agents?user_id={user_id}")
        ag_data = await ag_resp.json()
        self.assertTrue(ag_data["success"])
        self.assertGreaterEqual(len(ag_data["agents"]), 1)
        default_agent_id = ag_data["agents"][0]["id"]

        # 3. Create a custom new Agent (e.g. English Tutor)
        custom_ag_resp = await self.client.post("/api/portal/agents", json={
            "user_id": user_id,
            "name": "Gia Sư Tiếng Anh",
            "avatar": "🎓",
            "model": "deepseek/deepseek-chat",
            "voice": "vi-VN-NamMinhNeural",
            "prompt": "Bạn là giáo viên tiếng Anh bản ngữ vui vẻ."
        })
        self.assertTrue((await custom_ag_resp.json())["success"])

        # Check agents list has 2 agents now
        ag_resp2 = await self.client.get(f"/api/portal/agents?user_id={user_id}")
        ag_data2 = await ag_resp2.json()
        self.assertEqual(len(ag_data2["agents"]), 2)
        new_agent = [a for a in ag_data2["agents"] if a["name"] == "Gia Sư Tiếng Anh"][0]

        # 4. Pair device via 6-digit PIN
        pin_code = str(random.randint(100000, 999999))
        bind_resp = await self.client.post("/api/portal/bind", json={
            "user_id": user_id,
            "pairing_code": pin_code,
            "bot_name": "Robot Bàn Học",
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

        # 6. Assign the device to the new "Gia Sư Tiếng Anh" Agent
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
        self.assertEqual(dev_data2["devices"][0]["agent_name"], "Gia Sư Tiếng Anh")

    @unittest_run_loop
    async def test_04_ota_endpoint(self):
        resp = await self.client.get("/xiaozhi/ota/")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("firmware", data)
        self.assertIn("websocket", data)
        self.assertTrue(data["websocket"]["url"].endswith("/xiaozhi/v1/"))


if __name__ == "__main__":
    unittest.main()
