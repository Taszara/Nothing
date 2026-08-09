# -*- coding: utf-8 -*-
"""yt-dlp 通用引擎：负责抖音以外的平台（B站/快手/微博/小红书/YouTube 等），
以及抖音解析失败时的兜底。"""
import shutil
import tempfile
from pathlib import Path

from yt_dlp import YoutubeDL

from utils import UA, sanitize_filename, ensure_unique

BASE = Path(__file__).resolve().parent.parent
DOWNLOADS = BASE / "downloads"


class ParseError(Exception):
    pass


def _format_spec() -> str:
    """无 FFmpeg 时避免选择需要音画合并的 DASH 格式：
    优先渐进式 mp4，其次纯视频 mp4；有 FFmpeg 则允许合并取最高画质。"""
    if shutil.which("ffmpeg"):
        return "bv*[ext=mp4]+ba/bv*[ext=mp4]/b"
    return "best[ext=mp4][vcodec!=none][acodec!=none]/bv*[ext=mp4]/b"


def _base_opts(cookies: str | None = None, outtmpl=None, hook=None):
    opts = {
        "format": _format_spec(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "user_agent": UA,
        "outtmpl": outtmpl or "download",
        "retries": 3,
        "socket_timeout": 20,
    }
    if cookies:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write(cookies)
        tmp.close()
        opts["cookiefile"] = tmp.name
    if hook:
        opts["progress_hooks"] = [hook]
    return opts


def _first_entry(info: dict) -> dict:
    entries = info.get("entries")
    if entries:
        for e in entries:
            if e:
                return e
    return info


def parse(url: str, cookies: str | None = None) -> dict:
    """解析链接元信息（不下载）。"""
    try:
        with YoutubeDL(_base_opts(cookies)) as ydl:
            info = _first_entry(ydl.extract_info(url, download=False))
    except Exception as e:
        raise ParseError(f"解析失败：{e}") from e

    if not info:
        raise ParseError("未能获取到内容信息")

    return {
        "type": "video",
        "title": info.get("title") or "untitled",
        "author": (info.get("uploader") or info.get("channel") or "").strip(),
        "cover": info.get("thumbnail"),
        "count": 1,
        "engine": "ytdlp",
    }


def download(url: str, cookies: str | None = None, hook=None) -> Path:
    """下载视频到 downloads/，返回最终文件路径。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="vids_"))
    outtmpl = str(tmp_dir / "%(title).80s [%(id)s].%(ext)s")
    try:
        with YoutubeDL(_base_opts(cookies, outtmpl=outtmpl, hook=hook)) as ydl:
            info = _first_entry(ydl.extract_info(url, download=True))
        files = [p for p in tmp_dir.iterdir() if p.is_file()]
        if not files:
            raise ParseError("未生成文件")
        src = files[0]
        title = sanitize_filename(info.get("title") or src.stem, fallback="download")
        dest = ensure_unique(DOWNLOADS / f"{title}{src.suffix}")
        shutil.move(str(src), dest)
        return dest
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
