"""
Free Weather Tool for XiaoZhiVN Server
--------------------------------------
Sử dụng Open-Meteo API: 100% Miễn phí, không cần bất kỳ API key nào.
Tự động chuyển đổi tên tỉnh/thành phố Việt Nam sang tọa độ.
"""

import logging
import aiohttp

logger = logging.getLogger("xiaozhivn.tools.free_weather")

# Tọa độ mặc định một số thành phố lớn tại Việt Nam
DEFAULT_CITIES = {
    "hà nội": (21.0285, 105.8542),
    "hồ chí minh": (10.8231, 106.6297),
    "sài gòn": (10.8231, 106.6297),
    "đà nẵng": (16.0544, 108.2022),
    "hải phòng": (20.8449, 106.6881),
    "cần thơ": (10.0452, 105.7469),
    "nha trang": (12.2388, 109.1967),
    "đà lạt": (11.9404, 108.4583),
    "huế": (16.4637, 107.5909),
    "vũng tàu": (10.3460, 107.0843),
    "quy nhơn": (13.7830, 109.2197),
}

WMO_WEATHER_CODES = {
    0: "trời quang đãng, không mây",
    1: "chủ yếu trời quang",
    2: "trời có mây rải rác",
    3: "trời nhiều mây, u ám",
    45: "có sương mù",
    48: "sương mù dày đặc",
    51: "mưa phùn nhẹ",
    53: "mưa phùn vừa",
    55: "mưa phùn dày",
    61: "mưa rào nhẹ",
    63: "mưa vừa",
    65: "mưa to",
    80: "mưa rào bất chợt",
    81: "mưa rào nặng hạt",
    82: "mưa rào dữ dội",
    95: "có dông bão sấm sét",
}


async def get_weather(location: str = "Hà Nội") -> dict:
    """
    Lấy thông tin thời tiết hiện tại qua Open-Meteo (Miễn phí 100%).
    """
    norm_loc = location.lower().strip()
    lat, lon = DEFAULT_CITIES.get(norm_loc, (None, None))

    async with aiohttp.ClientSession() as session:
        # Nếu không có trong danh sách cố định, dùng Geocoding API miễn phí của Open-Meteo
        if lat is None:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=vi&format=json"
            try:
                async with session.get(geo_url, timeout=5) as resp:
                    if resp.status == 200:
                        geo_data = await resp.json()
                        results = geo_data.get("results")
                        if results:
                            lat = results[0]["latitude"]
                            lon = results[0]["longitude"]
                            location = results[0].get("name", location)
            except Exception as e:
                logger.warning(f"Lỗi geocoding cho {location}: {e}")

        # Fallback về Hà Nội nếu không tìm thấy
        if lat is None:
            lat, lon = DEFAULT_CITIES["hà nội"]
            location = "Hà Nội"

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
            f"&timezone=Asia%2FBangkok"
        )

        try:
            async with session.get(weather_url, timeout=6) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    curr = data.get("current", {})
                    temp = curr.get("temperature_2m")
                    feels = curr.get("apparent_temperature")
                    humidity = curr.get("relative_humidity_2m")
                    code = curr.get("weather_code", 0)
                    wind = curr.get("wind_speed_10m")

                    condition = WMO_WEATHER_CODES.get(code, "thời tiết bình thường")
                    text_summary = (
                        f"Thời tiết tại {location} hiện tại: {condition}, nhiệt độ {temp}°C, "
                        f"cảm giác như {feels}°C, độ ẩm {humidity}%, gió thổi {wind} km/h."
                    )
                    return {
                        "success": True,
                        "location": location,
                        "temperature": temp,
                        "feels_like": feels,
                        "humidity": humidity,
                        "condition": condition,
                        "summary": text_summary,
                    }
                else:
                    return {"success": False, "summary": f"Không thể lấy dữ liệu thời tiết (Lỗi {resp.status})."}
        except Exception as e:
            logger.error(f"Lỗi kết nối thời tiết: {e}")
            return {"success": False, "summary": f"Lỗi kết nối dịch vụ thời tiết: {str(e)}"}

