import asyncio
import os
import sys
import uuid
import random
import json
import unittest
from aiohttp import web
import aiohttp
from aiohttp.test_utils import AioHTTPTestCase

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from server.desktop_app import create_application


class TestNiOhDualServer(AioHTTPTestCase):

    async def get_application(self):
        return create_application(port=8001)

    async def test_01_routing_separation(self):
        # 1. Localhost gets Server Gateway App
        resp_local = await self.client.get("/")
        self.assertEqual(resp_local.status, 200)
        text_local = await resp_local.text()
        self.assertIn("Ni-Oh Server", text_local)
        self.assertIn("Cổng Máy Chủ & Quản Trị Hệ Thống", text_local)

        # 2. Remote Cloudflare host gets Web Portal
        resp_cf = await self.client.get("/", headers={"Host": "gateway.trycloudflare.com"})
        self.assertEqual(resp_cf.status, 200)
        text_cf = await resp_cf.text()
        self.assertIn("Ni-Oh Voice Portal", text_cf)
        self.assertIn("Bảng Quản Trị Thiết Bị & Trợ Lý AI", text_cf)

    async def test_02_server_gateway_and_oauth_config(self):
        # GET /api/gateway/status
        resp = await self.client.get("/api/gateway/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("server_running", data)
        self.assertIn("local_port", data)
        self.assertIn("live_clients", data)
        self.assertIn("oauth", data)

        # POST /api/admin/oauth-config
        save_oauth = await self.client.post("/api/admin/oauth-config", json={
            "google_client_id": "test-client-id-12345.apps.googleusercontent.com",
            "google_client_secret": "GOCSPX-test-secret"
        })
        self.assertEqual(save_oauth.status, 200)
        save_data = await save_oauth.json()
        self.assertTrue(save_data["success"])

        # Check status reflects saved OAuth
        resp2 = await self.client.get("/api/gateway/status")
        data2 = await resp2.json()
        self.assertEqual(data2["oauth"]["google_client_id"], "test-client-id-12345.apps.googleusercontent.com")

        # GET /api/auth/google/login should redirect to Google OAuth URL
        google_login_resp = await self.client.get("/api/auth/google/login", allow_redirects=False)
        self.assertEqual(google_login_resp.status, 302)
        loc = google_login_resp.headers.get("Location", "")
        self.assertIn("accounts.google.com/o/oauth2/v2/auth", loc)
        self.assertIn("client_id=test-client-id-12345.apps.googleusercontent.com", loc)

    async def test_03_user_management_and_backup(self):
        u_suffix = uuid.uuid4().hex[:6]
        email = f"user_{u_suffix}@example.com"

        # 1. Register test user
        reg_resp = await self.client.post("/api/portal/register", json={
            "email": email,
            "password": "password123456",
            "name": f"Tester {u_suffix}"
        })
        reg_data = await reg_resp.json()
        self.assertTrue(reg_data["success"])
        user_id = reg_data["user"]["user_id"]

        # 2. Check admin user list contains this user
        admin_users_resp = await self.client.get("/api/admin/users")
        self.assertEqual(admin_users_resp.status, 200)
        users_list = (await admin_users_resp.json()).get("users", [])
        matched = [u for u in users_list if u["id"] == user_id]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["agent_count"], 1)  # auto-created default agent

        # 3. Create a custom Agent
        ag_resp = await self.client.post("/api/portal/agents", json={
            "user_id": user_id,
            "name": "Trợ Lý Nghiên Cứu",
            "model": "deepseek-chat",
            "voice": "vi-VN-NamMinhNeural",
            "prompt": "Bạn là chuyên gia nghiên cứu."
        })
        self.assertTrue((await ag_resp.json())["success"])

        # 4. Pair device via 6-digit PIN
        pin_code = str(random.randint(100000, 999999))
        bind_resp = await self.client.post("/api/portal/bind", json={
            "user_id": user_id,
            "pairing_code": pin_code,
            "bot_name": "ESP32 Phòng Lab"
        })
        self.assertTrue((await bind_resp.json())["success"])

        # 5. Backup data
        backup_resp = await self.client.get("/api/admin/backup")
        self.assertEqual(backup_resp.status, 200)
        backup_json = await backup_resp.json()
        self.assertIn("users", backup_json)
        self.assertIn("agents", backup_json)
        self.assertIn("devices", backup_json)

        # 6. Delete user
        del_resp = await self.client.post("/api/admin/delete-user", json={"user_id": user_id})
        self.assertTrue((await del_resp.json())["success"])

        # Check user is deleted
        admin_users_resp2 = await self.client.get("/api/admin/users")
        users_list2 = (await admin_users_resp2.json()).get("users", [])
        self.assertEqual(len([u for u in users_list2 if u["id"] == user_id]), 0)

        # 7. Restore from backup
        restore_resp = await self.client.post("/api/admin/restore", json=backup_json)
        self.assertTrue((await restore_resp.json())["success"])

        # Check restored user exists again
        admin_users_resp3 = await self.client.get("/api/admin/users")
        users_list3 = (await admin_users_resp3.json()).get("users", [])
        self.assertEqual(len([u for u in users_list3 if u["id"] == user_id]), 1)

    async def test_04_ota_and_websocket_routes(self):
        resp = await self.client.get("/xiaozhi/ota/")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("firmware", data)
        self.assertIn("websocket", data)
        self.assertTrue(data["websocket"]["url"].endswith("/xiaozhi/v1/"))

    async def test_05_google_link_modal_and_cf_linking(self):
        # 1. Test in-portal Google account linking without blocking errors
        g_email = f"google_user_{uuid.uuid4().hex[:6]}@gmail.com"
        link_resp = await self.client.post("/api/portal/google-link", json={
            "email": g_email,
            "name": "Nguyen Van Google"
        })
        self.assertEqual(link_resp.status, 200)
        link_data = await link_resp.json()
        self.assertTrue(link_data["success"])
        self.assertEqual(link_data["user"]["provider"], "google")
        self.assertEqual(link_data["user"]["email"], g_email)

        # 2. Check that Desktop App admin user table displays this Google user
        admin_resp = await self.client.get("/api/admin/users")
        users = (await admin_resp.json()).get("users", [])
        g_matched = [u for u in users if u["email"] == g_email]
        self.assertEqual(len(g_matched), 1)
        self.assertEqual(g_matched[0]["provider"], "google")

        # 3. Test Cloudflare quick link and unlink
        cf_quick = await self.client.post("/api/gateway/cf-link-quick")
        self.assertEqual(cf_quick.status, 200)
        self.assertTrue((await cf_quick.json())["success"])

        # Check status shows logged in
        status_resp = await self.client.get("/api/gateway/status")
        status_data = await status_resp.json()
        self.assertTrue(status_data["cf_logged_in"])

        # Unlink Cloudflare
        cf_unlink = await self.client.post("/api/gateway/cf-unlink")
        self.assertEqual(cf_unlink.status, 200)
        self.assertTrue((await cf_unlink.json())["success"])

    async def test_06_vietnamese_localization_and_xiaozhi_protocol(self):
        from server.tools.vietnam_datetime import get_vietnam_time_summary
        from server.voice_engine import process_vietnamese_query

        # 1. Test Vietnamese DateTime (GMT+7 & Lunar Calendar)
        dt = get_vietnam_time_summary()
        self.assertTrue(dt["success"])
        self.assertIn("Dương lịch", dt["summary"])
        self.assertIn("Âm lịch", dt["summary"])

        # 2. Test Vietnamese Wake-word & Exit responses
        wake_res = await process_vietnamese_query("chào ni-oh", {})
        self.assertTrue(len(wake_res) > 0)

        exit_res = await process_vietnamese_query("tạm biệt bạn nhé", {})
        self.assertTrue("tạm biệt" in exit_res.lower() or "hẹn gặp lại" in exit_res.lower() or "tạm dừng" in exit_res.lower())

        # 3. Test OTA endpoint compliance with Xiaozhi protocol
        ota_resp = await self.client.get("/xiaozhi/ota/")
        self.assertEqual(ota_resp.status, 200)
        ota_json = await ota_resp.json()
        self.assertEqual(ota_json["server_time"]["timezone_offset"], 420)  # +7 GMT for Vietnam

        # 4. Test WebSocket Voice Engine Handshake and PIN binding
        test_mac = f"ESP32-VN-{uuid.uuid4().hex[:4].upper()}"
        ws = await self.client.ws_connect("/xiaozhi/v1/", headers={"Device-Id": test_mac})

        # Device is not yet bound: server sends initial pairing PIN display message
        first_msg = await ws.receive_json()
        self.assertEqual(first_msg["type"], "stt")
        self.assertIn("Mã PIN:", first_msg["text"])

        # Send Hello handshake
        await ws.send_json({
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60
            }
        })

        # Read messages until we get 'hello'
        hello_reply = None
        for _ in range(10):
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "hello":
                    hello_reply = data
                    break

        self.assertIsNotNone(hello_reply)
        self.assertEqual(hello_reply["type"], "hello")
        self.assertEqual(hello_reply["version"], 1)
        self.assertEqual(hello_reply["audio_params"]["sample_rate"], 16000)

        # Send Wake-up command
        await ws.send_json({
            "type": "listen",
            "state": "detect",
            "text": "chào ni-oh"
        })

        reply_stt = None
        for _ in range(10):
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "stt":
                    reply_stt = data
                    break

        self.assertIsNotNone(reply_stt)
        self.assertEqual(reply_stt["type"], "stt")
        self.assertTrue(len(reply_stt["text"]) > 0)

        await ws.close()

    async def test_07_mcp_and_tool_integration(self):
        from server.tools.mcp_manager import execute_server_tool, SERVER_TOOLS_SCHEMA

        # 1. Test schema includes all 5 core tools
        tool_names = [t["function"]["name"] for t in SERVER_TOOLS_SCHEMA]
        self.assertIn("get_weather", tool_names)
        self.assertIn("get_vietnam_news", tool_names)
        self.assertIn("get_vietnam_datetime", tool_names)
        self.assertIn("web_search", tool_names)
        self.assertIn("pc_control", tool_names)

        # 2. Test execution of server tools
        res_weather = await execute_server_tool("get_weather", {"location": "Đà Nẵng"})
        self.assertIn("Đà Nẵng", res_weather)

        res_dt = await execute_server_tool("get_vietnam_datetime", {})
        self.assertIn("Bây giờ là", res_dt)

        # 3. Test Vision MCP Endpoint
        vis_resp = await self.client.get("/mcp/vision/explain")
        self.assertEqual(vis_resp.status, 200)
        vis_data = await vis_resp.json()
        self.assertEqual(vis_data["protocol"], "mcp/vision")

        # POST image bytes to Vision MCP
        vis_post = await self.client.post("/mcp/vision/explain", data=b"fake_jpeg_image_data_bytes_1234567890")
        self.assertEqual(vis_post.status, 200)
        vis_post_data = await vis_post.json()
        self.assertEqual(vis_post_data["code"], 0)


if __name__ == "__main__":
    unittest.main()
