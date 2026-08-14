# -*- coding: utf-8 -*-
"""下载编排：后台线程执行，进度写入任务状态，前端轮询。"""
import shutil
import threading
import tempfile
import zipfile
from pathlib import Path

import requests

from utils import UA, sanitize_filename, ensure_unique
from engines import douyin as dy_engine
from engines import ytdlp as ytdlp_engine

BASE = Path(__file__).resolve().parent
DOWNLOADS = BASE / "downloads"
DOWNLOADS.mkdir(exist_ok=True)

_REFERERS = {"douyin": "https://www.douyin.com/"}

_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def get_status(task_id: str) -> dict:
    with _lock:
        return dict(_tasks.get(task_id, {"status": "notfound"}))


def _update(task_id: str, **kw):
    with _lock:
        task = _tasks.setdefault(task_id, {})
        task.update(kw)
        task["id"] = task_id
        return task


def start(task_id: str, args: dict):
    _update(task_id, status="queued", progress=0)
    threading.Thread(target=_run, args=(task_id, args), daemon=True).start()


# ---------- 执行 ----------

def _run(task_id: str, args: dict):
    platform = args.get("platform") or "other"
    typ = args.get("type") or "video"
    title = args.get("title") or "download"
    urls = args.get("urls") or []
    images = args.get("images") or []
    videos = args.get("videos") or []
    source_url = args.get("source_url")
    cookies = args.get("cookies") or None

    try:
        if platform == "douyin" and typ == "mixed":
            files = _save_mixed(task_id, title, images, videos, cookies)
        elif platform == "douyin" and typ == "images":
            files = [_save_images(task_id, title, urls or images, cookies)]
        elif platform == "douyin" and typ == "video":
            files = [_save_video(task_id, title, (urls or videos)[0], cookies)]
        else:
            files = [_save_ytdlp(task_id, source_url, cookies)]

        file_infos = [{"name": p.name, "size": p.stat().st_size}
                      for p in files if p.exists()]
        _update(task_id, status="done", progress=100, files=file_infos,
                filename=file_infos[0]["name"] if file_infos else "",
                filesize=file_infos[0]["size"] if file_infos else 0)
    except Exception as e:  # noqa: BLE001 —— 异常信息直接呈现给用户
        _update(task_id, status="error", error=str(e) or "下载失败")


def _save_mixed(task_id: str, title: str, images: list[str],
                videos: list[str], cookies: str | None) -> list[Path]:
    """图文+视频混排：视频逐个下载、图片打包 ZIP，返回全部文件路径。"""
    files = []
    for i, vurl in enumerate(videos, 1):
        name = title if len(videos) == 1 else f"{title} 视频{i}"
        files.append(_save_video(task_id, name, vurl, cookies))
    if images:
        files.append(_save_images(task_id, title, images, cookies))
    return files


def _headers(cookies: str | None, referer: str | None = None):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    if cookies:
        h["Cookie"] = cookies
    return h


def _save_video(task_id: str, title: str, url: str, cookies: str | None) -> Path:
    """requests 流式下载单视频，落盘 downloads/。"""
    referer = _REFERERS.get("douyin")
    with requests.get(url, headers=_headers(cookies, referer),
                      stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        ext = ".mp4"
        # 从 URL 推断扩展名（直链常带 .mp4）
        m = url.rsplit("?", 1)[0].rsplit("/", 1)[-1]
        if "." in m and m.rsplit(".", 1)[-1].lower() in {"mp4", "mov", "webm", "flv", "m4a", "mp3"}:
            ext = "." + m.rsplit(".", 1)[-1].lower()

        dest = ensure_unique(DOWNLOADS / f"{sanitize_filename(title)}{ext}")
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if total:
                    _update(task_id, status="running",
                            progress=round(done * 100 / total),
                            downloaded=done, total=total)
        return dest


def _save_images(task_id: str, title: str, urls: list[str],
                 cookies: str | None) -> Path:
    """图文：逐张下载后打包 ZIP。"""
    referer = _REFERERS.get("douyin")
    tmp = Path(tempfile.mkdtemp(prefix="imgs_"))
    total = len(urls)
    try:
        for i, url in enumerate(urls, 1):
            with requests.get(url, headers=_headers(cookies, referer),
                              stream=True, timeout=30) as r:
                r.raise_for_status()
                m = url.rsplit("?", 1)[0].rsplit("/", 1)[-1]
                ext = "." + m.rsplit(".", 1)[-1].lower() if "." in m else ".jpg"
                if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                    ext = ".jpg"
                path = tmp / f"{i:02d}{ext}"
                with open(path, "wb") as f:
                    for chunk in r.iter_content(64 * 1024):
                        if chunk:
                            f.write(chunk)
            _update(task_id, status="running", progress=round(i * 80 / total))

        dest = ensure_unique(DOWNLOADS / f"{sanitize_filename(title)}.zip")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(tmp.iterdir()):
                zf.write(p, p.name)
        _update(task_id, progress=95)
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _save_ytdlp(task_id: str, source_url: str, cookies: str | None) -> Path:
    """交给 yt-dlp 下载（其他平台 / 抖音兜底）。"""
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            recv = d.get("downloaded_bytes") or 0
            if total:
                _update(task_id, status="running",
                        progress=round(recv * 100 / total),
                        downloaded=recv, total=total)

    return ytdlp_engine.download(source_url, cookies=cookies, hook=hook)
