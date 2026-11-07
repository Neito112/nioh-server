"""
Smart Alarm & Proactive Notification System (Hẹn Giờ Báo Thức & Chủ Động Wakeup)
---------------------------------------------------------------------------------
Theo dõi lịch hẹn giờ, báo thức và chủ động gửi thông báo thoại (Proactive TTS)
xuống mạch ESP32 qua WebSocket thời gian thực theo đúng kế hoạch phát triển.
"""

import os
import time
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("xiaozhivn.tools.alarm")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")


def init_alarm_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS alarms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT,
        trigger_timestamp REAL,
        time_str TEXT,
        label TEXT,
        repeat_daily INTEGER DEFAULT 0,
        is_triggered INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()


init_alarm_db()


def set_countdown_timer(device_id: str, minutes: float, label: str = "Hẹn giờ") -> dict:
    """
    Đặt hẹn giờ đếm ngược sau N phút.
    """
    if minutes <= 0:
        minutes = 1.0

    trigger_ts = time.time() + (minutes * 60)
    trigger_dt = datetime.fromtimestamp(trigger_ts)
    time_display = trigger_dt.strftime("%H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT INTO alarms (device_id, trigger_timestamp, time_str, label, repeat_daily, is_triggered)
    VALUES (?, ?, ?, ?, 0, 0)
    """, (device_id, trigger_ts, time_display, label))
    conn.commit()
    conn.close()

    summary = f"Đã đặt hẹn giờ '{label}' sau {int(minutes) if minutes.is_integer() else minutes} phút nữa (lúc {time_display}). Khi đến giờ tôi sẽ chủ động nhắc bạn."
    return {
        "success": True,
        "trigger_time": time_display,
        "minutes": minutes,
        "label": label,
        "summary": summary
    }


def set_alarm_clock(device_id: str, time_str: str, label: str = "Báo thức", repeat_daily: bool = False) -> dict:
    """
    Đặt báo thức theo mốc giờ (Ví dụ: '06:30', '7:00', '18:45').
    """
    now = datetime.now()
    parts = time_str.replace("h", ":").replace("g", ":").split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return {"success": False, "message": f"Định dạng giờ '{time_str}' không hợp lệ. Vui lòng nói ví dụ: 6 giờ 30 hoặc 07:00."}

    target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target_dt <= now:
        target_dt += timedelta(days=1)  # Nếu giờ đã qua trong ngày thì hẹn vào ngày mai

    trigger_ts = target_dt.timestamp()
    formatted_time = target_dt.strftime("%H:%M")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT INTO alarms (device_id, trigger_timestamp, time_str, label, repeat_daily, is_triggered)
    VALUES (?, ?, ?, ?, ?, 0)
    """, (device_id, trigger_ts, formatted_time, label, 1 if repeat_daily else 0))
    conn.commit()
    conn.close()

    day_label = "mỗi ngày" if repeat_daily else "ngày mai" if target_dt.day != now.day else "hôm nay"
    summary = f"Đã đặt báo thức '{label}' lúc {formatted_time} {day_label}. Tôi sẽ chủ động đánh thức bạn đúng giờ."
    return {
        "success": True,
        "trigger_time": formatted_time,
        "label": label,
        "summary": summary
    }


def get_pending_alarms(device_id: str = "") -> dict:
    """Lấy danh sách các báo thức / hẹn giờ đang chờ."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now_ts = time.time()
    if device_id:
        c.execute("SELECT id, time_str, label, repeat_daily FROM alarms WHERE device_id = ? AND is_triggered = 0 AND trigger_timestamp >= ? ORDER BY trigger_timestamp ASC", (device_id, now_ts))
    else:
        c.execute("SELECT id, time_str, label, repeat_daily FROM alarms WHERE is_triggered = 0 AND trigger_timestamp >= ? ORDER BY trigger_timestamp ASC", (now_ts,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return {"success": True, "count": 0, "summary": "Hiện bạn không có báo thức hay hẹn giờ nào đang chờ."}

    items = [f"- {r[2]} lúc {r[1]} {'(lặp lại hàng ngày)' if r[3] else ''}" for r in rows]
    summary = "Danh sách hẹn giờ đang hoạt động:\n" + "\n".join(items)
    return {"success": True, "count": len(rows), "summary": summary}


async def run_alarm_monitor_loop(get_active_connections_func):
    """
    Vòng lặp nền giám sát hẹn giờ & chủ động gửi thông báo giọng nói (Proactive Wakeup).
    """
    logger.info("Bộ giám sát hẹn giờ & báo thức thông minh (Proactive Alarm) đã khởi chạy.")
    while True:
        try:
            await asyncio.sleep(5)
            now_ts = time.time()

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
            SELECT id, device_id, label, time_str, repeat_daily
            FROM alarms
            WHERE is_triggered = 0 AND trigger_timestamp <= ?
            """, (now_ts,))
            due_alarms = c.fetchall()

            for alarm_id, dev_id, label, time_str, repeat in due_alarms:
                if repeat:
                    # Tăng thêm 24 giờ cho chu kỳ tiếp theo
                    c.execute("UPDATE alarms SET trigger_timestamp = trigger_timestamp + 86400 WHERE id = ?", (alarm_id,))
                else:
                    c.execute("UPDATE alarms SET is_triggered = 1 WHERE id = ?", (alarm_id,))
                conn.commit()

                # Gửi thông báo chủ động xuống mạch ESP32 qua WebSocket
                active_conns = get_active_connections_func()
                target_ws = None
                if dev_id and dev_id in active_conns:
                    target_ws = active_conns[dev_id].get("ws")
                elif active_conns:
                    target_ws = next(iter(active_conns.values())).get("ws")

                if target_ws and not target_ws.closed:
                    alert_text = f"Báo thức! Đã đến giờ: {label} ({time_str})!"
                    logger.info(f"Kích hoạt báo thức tới mạch {dev_id}: {alert_text}")
                    msg = {
                        "type": "tts",
                        "state": "start",
                        "text": alert_text
                    }
                    try:
                        await target_ws.send_json(msg)
                    except Exception as e:
                        logger.warning(f"Lỗi gửi thông báo báo thức tới {dev_id}: {e}")

            conn.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Lỗi vòng lặp báo thức: {e}")
            await asyncio.sleep(5)
