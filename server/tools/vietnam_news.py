"""
Công Cụ Tin Tức Việt Nam (Vietnam News RSS Aggregator)
-----------------------------------------------------
Thu thập tin tức mới nhất từ các tòa soạn hàng đầu Việt Nam (VnExpress, Tuổi Trẻ)
Phục vụ nhu cầu đọc báo, cập nhật tin nóng trong ngày của người dùng qua loa thông minh.
"""

import aiohttp
import xml.etree.ElementTree as ET
import logging
import re
import html

logger = logging.getLogger("xiaozhivn.tools.vietnam_news")

NEWS_SOURCES = {
    "tin-nong": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "thoi-su": "https://vnexpress.net/rss/thoi-su.rss",
    "kinh-doanh": "https://vnexpress.net/rss/kinh-doanh.rss",
    "cong-nghe": "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss",
    "the-thao": "https://vnexpress.net/rss/the-thao.rss",
    "tuoi-tre": "https://tuoitre.vn/rss/tin-moi-nhat.rss"
}


def _clean_html_text(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<.*?>", "", text)
    clean = html.unescape(clean)
    return clean.strip()


async def get_vietnam_news(category: str = "tin-nong", max_items: int = 3) -> dict:
    """Lấy danh sách tin tức Việt Nam mới nhất từ RSS."""
    rss_url = NEWS_SOURCES.get(category, NEWS_SOURCES["tin-nong"])

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(rss_url, headers=headers, timeout=8) as resp:
                if resp.status != 200:
                    return {"success": False, "summary": "Không thể tải tin tức từ máy chủ báo chí lúc này."}
                xml_data = await resp.text()

        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return {"success": False, "summary": "Dữ liệu tin tức không đúng định dạng."}

        items = []
        for item in channel.findall("item")[:max_items]:
            title = _clean_html_text(item.findtext("title", ""))
            desc = _clean_html_text(item.findtext("description", ""))
            if title:
                items.append({
                    "title": title,
                    "description": desc[:150] + ("..." if len(desc) > 150 else "")
                })

        if not items:
            return {"success": False, "summary": "Hiện chưa có tin tức mới được cập nhật."}

        summary_lines = ["Dưới đây là các tin tức nổi bật mới nhất tại Việt Nam:"]
        for idx, it in enumerate(items, 1):
            summary_lines.append(f"{idx}. {it['title']}.")

        summary = " ".join(summary_lines)
        return {
            "success": True,
            "category": category,
            "items": items,
            "summary": summary
        }

    except Exception as e:
        logger.error(f"Lỗi tải tin tức RSS ({rss_url}): {e}")
        return {"success": False, "summary": f"Không thể lấy tin tức: {str(e)}"}

