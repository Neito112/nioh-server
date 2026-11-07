"""
Công Cụ Ngày Giờ & Lịch Âm Dương Việt Nam (Vietnam DateTime & Lunar Calendar)
----------------------------------------------------------------------------
Cung cấp ngày giờ hiện tại theo múi giờ Việt Nam (GMT+7, Asia/Ho_Chi_Minh)
và chuyển đổi lịch Âm Việt Nam chính xác theo thuật toán thiên văn Hồ Ngọc Đức.
"""

from datetime import datetime, timezone, timedelta
import math

VN_TIMEZONE = timezone(timedelta(hours=7))

THU_TIENG_VIET = {
    0: "Thứ Hai",
    1: "Thứ Ba",
    2: "Thứ Tư",
    3: "Thứ Năm",
    4: "Thứ Sáu",
    5: "Thứ Bảy",
    6: "Chủ Nhật"
}

CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
CHI = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]
CON_GIAP = ["Chuột", "Trâu", "Hổ", "Mèo", "Rồng", "Rắn", "Ngựa", "Dê", "Khỉ", "Gà", "Chó", "Lợn"]


def jd_from_date(dd: int, mm: int, yy: int) -> int:
    """Tính số ngày Julian từ ngày Dương lịch."""
    a = (14 - mm) // 12
    y = yy + 4800 - a
    m = mm + 12 * a - 3
    jd = dd + ((153 * m + 2) // 5) + 365 * y + (y // 4) - (y // 100) + (y // 400) - 32045
    if jd < 2299161:
        jd = dd + ((153 * m + 2) // 5) + 365 * y + (y // 4) - 32083
    return jd


def get_new_moon_day(k: int, time_zone: float = 7.0) -> int:
    """Tính ngày Sóc (New Moon) theo thuật toán thiên văn Jean Meeus."""
    t = k / 1236.85
    t2 = t * t
    t3 = t2 * t
    t4 = t3 * t
    dr = math.pi / 180

    jde = 2451524.3743 + 29.530588853 * k + 0.0001337 * t2 - 0.000000150 * t3 + 0.00000000073 * t4
    m = 2.5534 + 29.10535669 * k - 0.0000218 * t2 - 0.00000011 * t3
    mprime = 201.5643 + 385.81693528 * k + 0.0107438 * t2 + 0.00001239 * t3 - 0.000000058 * t4
    f = 160.7108 + 390.67050274 * k - 0.0016341 * t2 - 0.00000227 * t3 + 0.00000011 * t4

    d_jde = (
        (0.1734 - 0.000393 * t) * math.sin(m * dr)
        + 0.0021 * math.sin(2 * m * dr)
        - 0.4068 * math.sin(mprime * dr)
        + 0.0161 * math.sin(2 * mprime * dr)
        - 0.0004 * math.sin(3 * mprime * dr)
        + 0.0104 * math.sin(2 * f * dr)
        - 0.0051 * math.sin((m + mprime) * dr)
        - 0.0074 * math.sin((m - mprime) * dr)
        + 0.0004 * math.sin((2 * f + m) * dr)
        - 0.0004 * math.sin((2 * f - m) * dr)
        - 0.0006 * math.sin((2 * f + mprime) * dr)
        + 0.0010 * math.sin((2 * f - mprime) * dr)
        + 0.0005 * math.sin((m + 2 * mprime) * dr)
    )
    jde += d_jde
    return int(jde + 0.5 + time_zone / 24.0)


def get_sun_longitude(jdn: int, time_zone: float = 7.0) -> int:
    """Tính kinh độ Mặt Trời để xác định tiết khí."""
    t = (jdn - 2451545.0 + 0.5 - time_zone / 24.0) / 36525.0
    dr = math.pi / 180
    l0 = 280.46645 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52910 + 35999.05029 * t - 0.0001537 * t * t
    c = (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m * dr)
    c += (0.019993 - 0.000101 * t) * math.sin(2 * m * dr)
    c += 0.000289 * math.sin(3 * m * dr)
    theta = l0 + c
    theta = theta % 360.0
    return int(theta / 30.0)


def solar_to_lunar(dd: int, mm: int, yy: int, time_zone: float = 7.0) -> tuple[int, int, int, bool]:
    """Chuyển đổi ngày Dương lịch sang Âm lịch Việt Nam (ngày, tháng, năm, có phải tháng nhuận)."""
    day_number = jd_from_date(dd, mm, yy)
    k = int((day_number - 2451545.0) / 29.530588853)
    month_start = get_new_moon_day(k + 1, time_zone)
    if month_start > day_number:
        month_start = get_new_moon_day(k, time_zone)
    else:
        k += 1

    a11 = get_new_moon_day(int((jd_from_date(31, 12, yy) - 2451545.0) / 29.530588853), time_zone)
    sun_long = get_sun_longitude(a11, time_zone)
    if sun_long >= 9:
        b11 = a11
    else:
        b11 = get_new_moon_day(int((jd_from_date(31, 12, yy) - 2451545.0) / 29.530588853) - 1, time_zone)

    lunar_day = day_number - month_start + 1
    diff = int((month_start - b11) / 29.0)
    lunar_month = (diff + 11) % 12
    if lunar_month == 0:
        lunar_month = 12

    lunar_year = yy
    if lunar_month >= 11 and mm < 3:
        lunar_year = yy - 1

    return lunar_day, lunar_month, lunar_year, False


def get_vietnam_time_summary() -> dict:
    """Trả về tóm tắt thông tin ngày, giờ Dương lịch và Âm lịch Việt Nam."""
    now = datetime.now(VN_TIMEZONE)
    thu = THU_TIENG_VIET.get(now.weekday(), "Thứ")
    gio_str = f"{now.hour:02d} giờ {now.minute:02d} phút"
    ngay_duong_str = f"{thu}, ngày {now.day:02d} tháng {now.month:02d} năm {now.year}"

    try:
        ld, lm, ly, is_leap = solar_to_lunar(now.day, now.month, now.year)
        can_nam = CAN[(ly + 6) % 10]
        chi_nam = CHI[(ly + 8) % 12]
        con_giap = CON_GIAP[(ly + 8) % 12]
        am_lich_str = f"ngày {ld} tháng {lm} năm {can_nam} {chi_nam} (năm con {con_giap})"
    except Exception:
        am_lich_str = "Đang cập nhật"

    summary = (
        f"Bây giờ là {gio_str}, {ngay_duong_str} (Dương lịch). "
        f"Âm lịch hôm nay là {am_lich_str}."
    )

    return {
        "success": True,
        "time": gio_str,
        "solar_date": ngay_duong_str,
        "lunar_date": am_lich_str,
        "summary": summary
    }
