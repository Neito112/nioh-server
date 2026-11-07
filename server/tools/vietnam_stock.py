"""
Vietnam Stock Market Tool (Chứng Khoán Việt Nam Thời Gian Thực)
---------------------------------------------------------------
Truy vấn chỉ số thị trường VN-Index, HNX-Index và giá giao dịch các mã cổ phiếu
theo thời gian thực phục vụ người dùng Việt Nam.
"""

import json
import urllib.request
import asyncio
import logging

logger = logging.getLogger("xiaozhivn.tools.stock")


async def get_vietnam_stock_info(symbol: str = "") -> dict:
    """
    Truy vấn chỉ số VN-Index hoặc mã cổ phiếu cụ thể (FPT, VCB, HPG, SSI, VIC...).
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _fetch_stock_sync, symbol)
    except Exception as e:
        logger.error(f"Lỗi truy vấn chứng khoán: {e}")
        return {
            "success": False,
            "message": f"Không thể lấy dữ liệu chứng khoán: {str(e)}"
        }


def _fetch_stock_sync(symbol: str = "") -> dict:
    clean_sym = symbol.strip().upper()

    # 1. Nếu hỏi tổng quan thị trường hoặc VN-INDEX
    if not clean_sym or clean_sym in ["VNINDEX", "VN-INDEX", "THI_TRUONG", "CHUNG_KHOAN"]:
        try:
            url = "https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VNINDEX"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            closes = data.get("c", [])
            if len(closes) >= 2:
                last_c = closes[-1]
                prev_c = closes[-2]
                diff = round(last_c - prev_c, 2)
                pct = round((diff / prev_c) * 100, 2)
                trend = "tăng" if diff > 0 else "giảm" if diff < 0 else "đứng giá"
                summary = f"Chỉ số VN-Index hiện đạt {last_c:.2f} điểm ({trend} {abs(diff):.2f} điểm, tương đương {pct:+.2f}% so với phiên trước)."
                return {
                    "success": True,
                    "symbol": "VNINDEX",
                    "price": last_c,
                    "change": diff,
                    "percent": pct,
                    "summary": summary
                }
        except Exception as e:
            logger.warning(f"Lỗi lấy VN-Index: {e}")

    # 2. Nếu hỏi mã cổ phiếu cụ thể (hoặc danh sách tiêu biểu)
    target_syms = clean_sym if clean_sym else "FPT,VCB,HPG,SSI,VIC"
    url = f"https://bgapidatafeed.vps.com.vn/getliststockdata/{target_syms}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        stocks = json.loads(resp.read().decode("utf-8"))

    if not stocks or not isinstance(stocks, list):
        return {
            "success": False,
            "message": f"Không tìm thấy dữ liệu giao dịch cho mã '{clean_sym}'."
        }

    lines = []
    for item in stocks:
        sym = item.get("sym", "")
        ref = item.get("r", 0)  # Giá tham chiếu
        last = item.get("lastPrice") or item.get("c", 0)  # Giá khớp gần nhất
        change = item.get("ot", 0)  # Thay đổi
        high = item.get("highPrice", 0)
        low = item.get("lowPrice", 0)
        vol = item.get("lot", 0)

        # Chuyển đổi an toàn giá và biến động
        try:
            last_num = float(last)
            price_vnd = f"{last_num * 1000:,.0f} đ"
        except (ValueError, TypeError):
            price_vnd = f"{last} đ" if last else "Đang cập nhật"

        try:
            chg_num = float(change)
            chg_str = f"{chg_num:+.2f}"
        except (ValueError, TypeError):
            chg_str = str(change)

        try:
            vol_num = int(vol)
            vol_str = f"{vol_num:,}"
        except (ValueError, TypeError):
            vol_str = str(vol)

        lines.append(f"- Cổ phiếu {sym}: Giá {price_vnd} (Biến động: {chg_str}, Cao nhất: {high}, Thấp nhất: {low}, Khối lượng: {vol_str} CP)")

    summary = "Thông tin giao dịch chứng khoán:\n" + "\n".join(lines)
    return {
        "success": True,
        "summary": summary,
        "stocks": stocks
    }
