"""
ESP-NOW Command Handler for Ni-Oh Server
-----------------------------------------
Vì server máy tính không có chip phát sóng ESP-NOW trực tiếp,
server đóng vai trò phân tích câu lệnh của người dùng từ LLM,
sau đó đóng gói thành Frame JSON gửi ngược lại ESP32 để ESP32 phát sóng vô tuyến.
"""

import json
import logging

logger = logging.getLogger("nioh.tools.esp_now")


def build_esp_now_packet(action: str, target_device: str, value: str = "") -> dict:
    """
    Đóng gói gói tin ESP-NOW chuẩn bị bắn về mạch ESP32.
    :param action: 'turn_on', 'turn_off', 'toggle', 'set_value', 'broadcast'
    :param target_device: Tên hoặc mã định danh của mạch slave (ví dụ: 'den_ngu', 'cong_tac_1')
    :param value: Giá trị phụ (ví dụ độ sáng, mức quạt 1-3)
    """
    logger.info(f"Đóng gói lệnh ESP-NOW: action={action}, device={target_device}, value={value}")

    payload = {
        "protocol": "esp_now",
        "action": action,
        "device": target_device,
        "value": value,
    }

    return {
        "success": True,
        "forward_to_device": True,  # Báo cho WebSocket server biết cần forward frame này xuống ESP32
        "payload": payload,
        "response_text": f"Đã gửi lệnh {action} tới thiết bị {target_device} qua ESP-NOW.",
    }
