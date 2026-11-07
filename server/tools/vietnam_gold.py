"""
Vietnam Gold Price Tool (Giá Vàng Việt Nam Thời Gian Thực)
-----------------------------------------------------------
Cập nhật giá vàng miếng SJC, Doji, PNJ, Bảo Tín Minh Châu và vàng nhẫn 9999
theo thời gian thực phục vụ người dùng Việt Nam.
"""

import re
import urllib.request
import asyncio
import logging

logger = logging.getLogger("xiaozhivn.tools.gold")


async def get_vietnam_gold_price(gold_type: str = "") -> dict:
    """
    Lấy thông tin giá vàng trong nước (SJC, DOJI, Vàng nhẫn 9999, BTMC).
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _fetch_gold_sync, gold_type)
    except Exception as e:
        logger.error(f"Lỗi lấy giá vàng: {e}")
        return {
            "success": False,
            "message": f"Không thể lấy dữ liệu giá vàng trực tiếp: {str(e)}"
        }


def _fetch_gold_sync(gold_type: str = "") -> dict:
    url = "https://chogia.vn/gia-vang"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
    prices = []

    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) >= 3:
            cleaned = [' '.join(re.sub(r'<[^>]+>', ' ', td).split()) for td in tds]
            name = cleaned[0]
            buy = cleaned[1]
            sell = cleaned[2]

            if not buy or not sell or not any(c.isdigit() for c in buy):
                continue

            # Chuẩn hóa tên thương hiệu
            if any(k in name.lower() for k in ["sjc", "doji", "bảo tín minh châu", "nhẫn", "phú quý"]):
                prices.append({
                    "brand": name,
                    "buy": buy,
                    "sell": sell
                })

    if not prices:
        return {
            "success": False,
            "message": "Chưa trích xuất được bảng giá vàng từ nguồn cung cấp."
        }

    # Lọc theo yêu cầu người dùng nếu có chỉ định loại vàng
    filtered = prices
    gt_lower = gold_type.lower()
    if "nhẫn" in gt_lower:
        filtered = [p for p in prices if "nhẫn" in p["brand"].lower()] or prices
    elif "doji" in gt_lower:
        filtered = [p for p in prices if "doji" in p["brand"].lower()] or prices
    elif "sjc" in gt_lower:
        filtered = [p for p in prices if "sjc" in p["brand"].lower()] or prices

    summary_lines = ["Giá vàng trong nước cập nhật mới nhất:"]
    # Chọn tối đa 5 bảng giá tiêu biểu nhất
    seen = set()
    count = 0
    for p in filtered:
        b_name = p["brand"]
        if b_name in seen:
            continue
        seen.add(b_name)
        summary_lines.append(f"- {b_name}: Mua vào {p['buy']} đ/chỉ — Bán ra {p['sell']} đ/chỉ")
        count += 1
        if count >= 4:
            break

    summary = "\n".join(summary_lines)
    return {
        "success": True,
        "summary": summary,
        "data": prices[:8]
    }
