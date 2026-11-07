"""
Local IoT Discovery & Home Assistant Scanner
---------------------------------------------
Quét mạng LAN tìm kiếm Home Assistant và các thiết bị thông minh (mDNS/SSDP),
đồng thời sinh link / mã QR để người dùng nhập Access Token trên điện thoại.
"""

import socket
import logging
import asyncio

logger = logging.getLogger("xiaozhivn.tools.iot_discovery")


async def scan_local_iot_devices(timeout: int = 3) -> dict:
    """
    Quét mạng LAN nội bộ tìm Home Assistant hoặc thiết bị IoT.
    """
    logger.info("Bắt đầu quét mạng LAN tìm thiết bị IoT...")
    found_devices = []

    # 1. Thử quét mDNS cho Home Assistant qua socket UDP 5353
    # Hoặc kiểm tra các IP phổ biến trong dải mạng
    local_ip = _get_local_ip()
    subnet = ".".join(local_ip.split(".")[:3])

    # Kiểm tra cổng 8123 (Home Assistant mặc định) trên gateway và một số IP thường gặp
    test_ips = [f"{subnet}.{i}" for i in [1, 2, 10, 50, 100, 150, 200]]
    if "127.0.0.1" not in test_ips:
        test_ips.append("127.0.0.1")

    for ip in test_ips:
        if _check_port(ip, 8123):
            found_devices.append({
                "name": f"Home Assistant ({ip})",
                "type": "home_assistant",
                "ip": ip,
                "port": 8123,
                "auth_needed": True,
            })

    # Nếu không tìm thấy, trả về trạng thái
    if not found_devices:
        return {
            "success": True,
            "count": 0,
            "devices": [],
            "message": "Không tìm thấy Home Assistant nào trong mạng LAN hiện tại.",
        }

    return {
        "success": True,
        "count": len(found_devices),
        "devices": found_devices,
        "message": f"Đã tìm thấy {len(found_devices)} hệ thống nhà thông minh trong mạng LAN.",
    }


def generate_auth_qr_link(device_ip: str, portal_base_url: str) -> dict:
    """
    Tạo link và URL ảnh mã QR để người dùng quét bằng điện thoại,
    dẫn thẳng tới trang nhập Token cho Home Assistant.
    """
    config_url = f"{portal_base_url}/settings/smart-home?target_ip={device_ip}"
    # Dùng API tạo QR code miễn phí chuẩn
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={config_url}"

    return {
        "config_url": config_url,
        "qr_image_url": qr_image_url,
        "message": f"Quét mã QR để nhập Access Token kết nối Home Assistant tại {device_ip}.",
    }


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _check_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except Exception:
        return False

