"""
Free Music Stream Tool for XiaoZhiVN Server
-------------------------------------------
Sử dụng yt-dlp để tìm kiếm và trích xuất luồng âm thanh YouTube:
- 100% Miễn phí, không cần tài khoản hay API key
- Hỗ trợ mọi bài hát tiếng Việt, remix, podcast
- Trả về direct audio URL hoặc stream audio data qua WebSocket
"""

import asyncio
import logging

logger = logging.getLogger("xiaozhivn.tools.free_music")


async def search_and_get_audio_stream(song_name: str) -> dict:
    """
    Tìm bài hát trên YouTube và lấy link luồng audio trực tiếp.
    """
    logger.info(f"Yêu cầu phát nhạc: '{song_name}'")
    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(None, _extract_audio_url, song_name)
        if not data:
            return {"success": False, "message": f"Không tìm thấy bài hát '{song_name}'."}
        return {
            "success": True,
            "title": data.get("title"),
            "artist": data.get("uploader", ""),
            "duration": data.get("duration"),
            "audio_url": data.get("url"),
            "thumbnail": data.get("thumbnail"),
            "message": f"Đang phát bài: {data.get('title')}",
        }
    except Exception as e:
        logger.error(f"Lỗi tìm nhạc: {e}")
        return {"success": False, "message": f"Lỗi tìm bài hát: {str(e)}"}


def _extract_audio_url(song_name: str) -> dict:
    import yt_dlp

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch1",
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{song_name}", download=False)
        if "entries" in info and len(info["entries"]) > 0:
            entry = info["entries"][0]
        else:
            entry = info

        return {
            "title": entry.get("title"),
            "uploader": entry.get("uploader"),
            "duration": entry.get("duration"),
            "url": entry.get("url"),
            "thumbnail": entry.get("thumbnail"),
        }

