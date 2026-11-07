"""
PC System Control Tool for Ni-Oh Server
---------------------------------------
Cho phép ESP32 điều khiển trực tiếp PC đang chạy server
hoặc gửi gói Wake-on-LAN tới các PC khác trong mạng LAN.
"""

import os
import sys
import socket
import logging
import subprocess

logger = logging.getLogger("xiaozhivn.tools.pc_control")


def execute_pc_command(action: str, target: str = "local", param: str = "") -> dict:
    """
    Thực thi lệnh điều khiển PC.
    :param action: 'shutdown', 'restart', 'sleep', 'lock', 'volume_up', 'volume_down', 'mute', 'open_app', 'wake_on_lan'
    :param target: 'local' hoặc địa chỉ IP / MAC của PC đích
    :param param: tên ứng dụng hoặc thông số phụ
    """
    action = action.lower().strip()
    logger.info(f"Yêu cầu điều khiển PC: action={action}, target={target}, param={param}")

    try:
        # 1. Wake-on-LAN (Bật PC từ xa)
        if action in ("wake_on_lan", "wol", "turn_on"):
            mac_address = target if ":" in target or "-" in target else param
            if not mac_address:
                return {"success": False, "message": "Cần cung cấp địa chỉ MAC của card mạng PC để bật."}
            _send_magic_packet(mac_address)
            return {"success": True, "message": f"Đã gửi tín hiệu khởi động (Wake-on-LAN) tới máy có MAC {mac_address}."}

        # 2. Điều khiển máy cục bộ (Windows)
        if sys.platform == "win32":
            return _handle_windows_actions(action, param)
        elif sys.platform.startswith("linux"):
            return _handle_linux_actions(action, param)
        elif sys.platform == "darwin":
            return _handle_macos_actions(action, param)
        else:
            return {"success": False, "message": f"Hệ điều hành {sys.platform} chưa hỗ trợ lệnh này."}

    except Exception as e:
        logger.error(f"Lỗi khi điều khiển PC: {e}", exc_info=True)
        return {"success": False, "message": f"Lỗi hệ thống: {str(e)}"}


def _send_magic_packet(mac_address: str):
    """Gửi UDP Magic Packet tới broadcast address (Port 9)."""
    clean_mac = mac_address.replace(":", "").replace("-", "")
    if len(clean_mac) != 12:
        raise ValueError("Địa chỉ MAC không hợp lệ!")
    data = bytes.fromhex("FF" * 6 + clean_mac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(data, ("<broadcast>", 9))


def _handle_windows_actions(action: str, param: str) -> dict:
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
        return {"success": True, "message": "Đang tắt máy tính trong 5 giây."}

    elif action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "5"], check=False)
        return {"success": True, "message": "Đang khởi động lại máy tính."}

    elif action in ("sleep", "suspend"):
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)
        return {"success": True, "message": "Đã đưa máy tính vào chế độ ngủ."}

    elif action == "lock":
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
        return {"success": True, "message": "Đã khóa màn hình máy tính."}

    elif action in ("volume_up", "volume_down", "mute"):
        # Điều khiển volume bằng PowerShell WScript.Shell SendKeys
        key_code = "{PGUP}" if action == "volume_up" else ("{PGDN}" if action == "volume_down" else "")
        # Dùng phím ảo đa phương tiện 0xAF (Vol Up), 0xAE (Vol Down), 0xAD (Mute)
        ps_cmd = {
            "volume_up": "(New-Object -ComObject Wscript.Shell).SendKeys([char]175)",
            "volume_down": "(New-Object -ComObject Wscript.Shell).SendKeys([char]174)",
            "mute": "(New-Object -ComObject Wscript.Shell).SendKeys([char]173)",
        }.get(action, "")
        if ps_cmd:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False)
            return {"success": True, "message": f"Đã thực hiện chỉnh âm lượng: {action}."}

    elif action in ("open_app", "open_url", "launch"):
        if not param:
            return {"success": False, "message": "Vui lòng cho biết ứng dụng hoặc đường dẫn cần mở."}
        # Mở ứng dụng hoặc URL bằng start
        os.system(f'start "" "{param}"')
        return {"success": True, "message": f"Đã mở {param}."}

    return {"success": False, "message": f"Lệnh '{action}' không được nhận diện."}


def _handle_linux_actions(action: str, param: str) -> dict:
    if action == "shutdown":
        subprocess.run(["systemctl", "poweroff"], check=False)
        return {"success": True, "message": "Đang tắt máy."}
    elif action == "restart":
        subprocess.run(["systemctl", "reboot"], check=False)
        return {"success": True, "message": "Đang khởi động lại."}
    elif action == "sleep":
        subprocess.run(["systemctl", "suspend"], check=False)
        return {"success": True, "message": "Máy đang ngủ."}
    elif action == "open_app" and param:
        subprocess.Popen([param])
        return {"success": True, "message": f"Đã chạy {param}."}
    return {"success": False, "message": f"Lệnh {action} chưa cấu hình trên Linux."}


def _handle_macos_actions(action: str, param: str) -> dict:
    if action == "sleep":
        subprocess.run(["pmset", "sleepnow"], check=False)
        return {"success": True, "message": "Mac đang ngủ."}
    elif action == "open_app" and param:
        subprocess.run(["open", "-a", param], check=False)
        return {"success": True, "message": f"Đã mở {param}."}
    return {"success": False, "message": f"Lệnh {action} chưa cấu hình trên macOS."}

