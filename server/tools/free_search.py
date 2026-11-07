"""
Free Web Search Tool for XiaoZhiVN Server
-----------------------------------------
Sử dụng DuckDuckGo Search: 100% Miễn phí, không cần đăng ký tài khoản hay API Key.
Hỗ trợ tìm kiếm tiếng Việt và trả kết quả tóm tắt cho LLM.
"""

import asyncio
import logging

logger = logging.getLogger("xiaozhivn.tools.free_search")


async def search_web(query: str, max_results: int = 4) -> dict:
    """
    Tìm kiếm thông tin trên Internet qua DuckDuckGo không cần API key.
    """
    logger.info(f"Tìm kiếm web: query='{query}'")
    try:
        # Chạy trong executor vì duckduckgo_search có thể đồng bộ
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, _ddg_search, query, max_results)
        
        if not results:
            return {"success": False, "summary": f"Không tìm thấy kết quả nào cho '{query}'."}

        summary_parts = []
        for i, item in enumerate(results, 1):
            title = item.get("title", "")
            body = item.get("body", "")
            summary_parts.append(f"[{i}] {title}: {body}")

        full_summary = "\n".join(summary_parts)
        return {
            "success": True,
            "query": query,
            "results": results,
            "summary": full_summary,
        }
    except Exception as e:
        logger.error(f"Lỗi tìm kiếm web: {e}", exc_info=True)
        return {"success": False, "summary": f"Lỗi tìm kiếm: {str(e)}"}


def _ddg_search(query: str, max_results: int):
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except ImportError:
        # Fallback qua html scraping đơn giản nếu chưa có gói duckduckgo_search
        import urllib.request
        import urllib.parse
        import json
        url = "https://api.duckduckgo.com/?q=" + urllib.parse.quote(query) + "&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            abstract = data.get("AbstractText", "")
            if abstract:
                return [{"title": data.get("Heading", query), "body": abstract}]
            topics = data.get("RelatedTopics", [])
            items = []
            for t in topics[:max_results]:
                if "Text" in t:
                    items.append({"title": t.get("FirstURL", ""), "body": t.get("Text", "")})
            return items

