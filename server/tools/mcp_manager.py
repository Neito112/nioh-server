"""
XiaoZhiVN MCP (Model Context Protocol) & Unified Tool Manager
-------------------------------------------------------------
Triển khai chuẩn giao thức Model Context Protocol (MCP) và Function Calling:
1. Client-side MCP: Tương tác hai chiều qua JSON-RPC 2.0 với phần cứng ESP32:
   - Bắt tay khởi tạo: method 'initialize'
   - Khám phá công cụ phần cứng: method 'tools/list' (Loa, màn hình LCD, camera, cảm biến)
   - Điều khiển thực thi từ xa: method 'tools/call'
2. Server-side Tools: Các công cụ máy chủ thuần Việt:
   - Thời tiết Việt Nam (Open-Meteo)
   - Tin tức báo chí Việt Nam (VnExpress & Tuổi Trẻ RSS)
   - Lịch Âm Dương & Ngày giờ Việt Nam (GMT+7)
   - Tìm kiếm Internet (DuckDuckGo)
   - Điều khiển lệnh máy tính (PC Control)
3. Hợp nhất danh mục công cụ (Unified Tool Registry) theo chuẩn OpenAI tools schema
   để mô hình LLM (DeepSeek, Gemini, GPT-4o, Ollama) tự động ra quyết định gọi công cụ.
"""

import json
import asyncio
import logging
from typing import Dict, Any, List

logger = logging.getLogger("xiaozhivn.mcp_manager")

from server.tools.free_weather import get_weather
from server.tools.free_search import search_web
from server.tools.pc_control import execute_pc_command
from server.tools.vietnam_datetime import get_vietnam_time_summary
from server.tools.vietnam_news import get_vietnam_news


# ── ĐỊNH NGHĨA CÔNG CỤ MÁY CHỦ THUẦN VIỆT (SERVER TOOLS SCHEMA) ─────

SERVER_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Tra cứu thông tin thời tiết thời gian thực tại các tỉnh thành của Việt Nam.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Tên tỉnh hoặc thành phố tại Việt Nam, ví dụ: Hà Nội, TP. Hồ Chí Minh, Đà Nẵng, Cần Thơ, Hải Phòng, Đà Lạt..."
                    }
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vietnam_news",
            "description": "Cập nhật tin tức báo chí mới nhất trong ngày tại Việt Nam từ VnExpress và Tuổi Trẻ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["tin-nong", "thoi-su", "kinh-doanh", "cong-nghe", "the-thao"],
                        "description": "Thể loại tin tức cần tra cứu (mặc định là 'tin-nong')."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vietnam_datetime",
            "description": "Tra cứu ngày giờ hiện tại, thứ trong tuần, năm Can Chi và lịch Âm Dương Việt Nam theo múi giờ GMT+7.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Tìm kiếm thông tin trên Internet khi người dùng hỏi các kiến thức cập nhật hoặc sự kiện xã hội.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Từ khóa tìm kiếm thông tin ngắn gọn."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pc_control",
            "description": "Thực hiện lệnh điều khiển máy tính máy chủ như tắt máy tính, khóa màn hình, chụp ảnh màn hình, chỉnh âm lượng PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Lệnh điều khiển, ví dụ: 'tắt máy tính', 'khóa máy', 'chụp màn hình', 'tăng âm lượng', 'giảm âm lượng'."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_radio",
            "description": "Phát kênh phát thanh Radio VOV Việt Nam trên mạch ESP32. Sử dụng khi người dùng yêu cầu nghe đài, mở VOV, radio thời sự hoặc giao thông.",
            "parameters": {
                "type": "object",
                "properties": {
                    "station_name": {
                        "type": "string",
                        "description": "Mã kênh: VOV1 (Thời sự), VOV2 (Văn hóa), VOV3 (Âm nhạc giải trí), VOV_GT_HN (Giao thông Hà Nội), VOV_GT_HCM (Giao thông TP.HCM), VOV_MEKONG (Mekong FM), VOV5 (Đối ngoại), BBC, NPR."
                    }
                },
                "required": ["station_name"]
            }
        }
    }
]


# ── THỰC THI CÔNG CỤ PHÍA MÁY CHỦ ──────────────────────────────────

async def execute_server_tool(tool_name: str, args: dict) -> str:
    """Thực thi công cụ nội bộ của máy chủ và trả về kết quả dạng văn bản."""
    try:
        if tool_name == "get_weather":
            loc = args.get("location", "Hà Nội")
            res = await get_weather(loc)
            return res.get("summary", f"Không tìm thấy dữ liệu thời tiết tại {loc}.")

        elif tool_name == "get_vietnam_news":
            cat = args.get("category", "tin-nong")
            res = await get_vietnam_news(cat, max_items=3)
            return res.get("summary", "Hiện chưa có tin tức mới.")

        elif tool_name == "get_vietnam_datetime":
            res = get_vietnam_time_summary()
            return res.get("summary", "Đang cập nhật thời gian.")

        elif tool_name == "web_search":
            q = args.get("query", "")
            res = await search_web(q)
            return res.get("summary", f"Không tìm thấy kết quả cho '{q}'.")

        elif tool_name == "pc_control":
            cmd = args.get("command", "")
            res = execute_pc_command(cmd)
            return res.get("message", "Đã gửi lệnh điều khiển máy tính.")

        return f"Công cụ {tool_name} không được hỗ trợ trên máy chủ."
    except Exception as e:
        logger.error(f"Lỗi thực thi công cụ {tool_name}: {e}")
        return f"Lỗi thực thi {tool_name}: {str(e)}"


# ── BỘ QUẢN LÝ MCP CLIENT CHO PHẦN CỨNG ESP32 ──────────────────────

class DeviceMCPClient:
    """
    Quản lý phiên MCP Client cho thiết bị phần cứng ESP32.
    Thực hiện giao thức JSON-RPC 2.0 qua kênh WebSocket.
    """
    def __init__(self, ws, device_id: str, host_url: str = ""):
        self.ws = ws
        self.device_id = device_id
        self.host_url = host_url
        self.device_tools: List[dict] = []
        self._next_id = 1
        self._pending_calls: Dict[int, asyncio.Future] = {}

    def get_next_id(self) -> int:
        req_id = self._next_id
        self._next_id += 1
        return req_id

    async def initialize(self):
        """Gửi thông điệp bắt tay khởi tạo MCP tới ESP32 kèm điểm cuối vision."""
        req_id = self.get_next_id()
        vision_url = f"{self.host_url}/mcp/vision/explain" if self.host_url else "/mcp/vision/explain"
        msg = {
            "type": "mcp",
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {},
                    "vision": {
                        "url": vision_url,
                        "token": ""
                    }
                },
                "clientInfo": {
                    "name": "XiaoZhiVN-Server",
                    "version": "1.0.0"
                }
            }
        }
        await self.ws.send_json(msg)
        logger.info(f"Đã gửi MCP initialize tới mạch {self.device_id}")

    async def request_tools_list(self):
        """Yêu cầu mạch ESP32 liệt kê danh sách công cụ phần cứng mà mạch hỗ trợ."""
        req_id = self.get_next_id()
        msg = {
            "type": "mcp",
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/list",
            "params": {}
        }
        await self.ws.send_json(msg)
        logger.info(f"Đã gửi MCP tools/list tới mạch {self.device_id}")

    def handle_mcp_message(self, data: dict):
        """Xử lý các bản tin phản hồi JSON-RPC 2.0 từ mạch ESP32."""
        req_id = data.get("id")

        # 1. Phản hồi kết quả của tools/list
        result = data.get("result", {})
        if "tools" in result and isinstance(result["tools"], list):
            self.device_tools = result["tools"]
            logger.info(f"Mạch {self.device_id} đã đăng ký {len(self.device_tools)} công cụ MCP: {[t.get('name') for t in self.device_tools]}")
            return

        # 2. Phản hồi kết quả của tools/call
        if req_id in self._pending_calls:
            fut = self._pending_calls.pop(req_id)
            if not fut.done():
                if "error" in data:
                    fut.set_result(f"Lỗi phần cứng: {data['error'].get('message', 'Không rõ')}")
                else:
                    content = result.get("content", [])
                    if content and isinstance(content, list) and "text" in content[0]:
                        fut.set_result(content[0]["text"])
                    else:
                        fut.set_result("Đã thực hiện lệnh phần cứng thành công.")

    async def call_tool(self, tool_name: str, arguments: dict, timeout: float = 8.0) -> str:
        """Gửi lệnh gọi công cụ MCP tới phần cứng ESP32 và chờ kết quả."""
        req_id = self.get_next_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending_calls[req_id] = fut

        msg = {
            "type": "mcp",
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        await self.ws.send_json(msg)
        logger.info(f"Gửi MCP tools/call tới {self.device_id}: {tool_name}({arguments})")

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_calls.pop(req_id, None)
            return f"Thiết bị phần cứng không phản hồi lệnh {tool_name} sau {timeout} giây."
        except Exception as e:
            self._pending_calls.pop(req_id, None)
            return f"Lỗi gọi công cụ phần cứng: {str(e)}"

    def get_unified_tools_schema(self) -> List[dict]:
        """Tổng hợp danh mục công cụ máy chủ và công cụ phần cứng thành định dạng chuẩn OpenAI."""
        unified = list(SERVER_TOOLS_SCHEMA)

        for dt in self.device_tools:
            name = dt.get("name", "")
            desc = dt.get("description", "Công cụ điều khiển phần cứng thiết bị ESP32.")
            input_schema = dt.get("inputSchema") or {"type": "object", "properties": {}}
            unified.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"[Thiết Bị Phần Cứng] {desc}",
                    "parameters": input_schema
                }
            })

        return unified

