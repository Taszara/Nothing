# -*- coding: utf-8 -*-
"""视频/图文提取下载站 —— Flask 入口。"""
import threading
import uuid
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from utils import UA, extract_url, detect_platform, platform_name, fetch_safe
from urllib.parse import urlparse
from engines import douyin as dy_engine
from engines import ytdlp as ytdlp_engine
import downloader as dl

BASE = Path(__file__).resolve().parent
DOWNLOADS = BASE / "downloads"

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # cookies 上传上限 2MB

# cookie_id -> cookies 文本（仅存内存）
_cookie_store: dict[str, str] = {}
_cookie_lock = threading.Lock()


# ---------- 页面 ----------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------- 解析 ----------

@app.post("/api/parse")
def api_parse():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    cookie_id = data.get("cookie_id") or ""
    if not text:
        return jsonify(ok=False, error="请粘贴分享链接")

    url = extract_url(text)
    if not url:
        return jsonify(ok=False, error="未识别到链接，请检查分享内容")

    cookies = _cookie_store.get(cookie_id) if cookie_id else None
    platform = detect_platform(url)

    try:
        if platform == "douyin":
            info = dy_engine.parse(url, cookies=cookies)
        else:
            info = ytdlp_engine.parse(url, cookies=cookies)
    except Exception as e:  # noqa: BLE001
        # 抖音专用解析失败 -> 降级 yt-dlp；其余平台直接报错
        if platform != "douyin":
            return jsonify(ok=False, error=str(e))
        try:
            info = ytdlp_engine.parse(url, cookies=cookies)
        except Exception as e2:  # noqa: BLE001
            return jsonify(ok=False, error=f"{e}；兜底引擎也失败：{e2}")

    info["platform"] = platform
    info["platform_name"] = platform_name(platform)
    info["source_url"] = url
    return jsonify(ok=True, data=info)


# ---------- 下载 ----------

@app.post("/api/download")
def api_download():
    data = request.get_json(silent=True) or {}
    if not (data.get("urls") or data.get("source_url")):
        return jsonify(ok=False, error="缺少下载信息，请先重新解析")

    task_id = uuid.uuid4().hex[:12]
    cookie_id = data.get("cookie_id") or ""
    args = dict(data)
    args["cookies"] = _cookie_store.get(cookie_id) if cookie_id else None
    dl.start(task_id, args)
    return jsonify(ok=True, task_id=task_id)


@app.get("/api/task/<task_id>")
def api_task(task_id):
    return jsonify(dl.get_status(task_id))


@app.get("/api/files/<path:name>")
def api_files(name):
    """把已下载文件以附件形式发送给浏览器。"""
    return send_from_directory(DOWNLOADS, name, as_attachment=True)


# ---------- Cookie ----------

@app.post("/api/cookies")
def api_cookies():
    try:
        f = request.files.get("file")
    except RequestEntityTooLarge:
        return jsonify(ok=False, error="文件过大（上限 2MB）")
    if not f:
        return jsonify(ok=False, error="未收到文件")
    text = f.read().decode("utf-8", errors="ignore")
    if "Netscape" not in text and not any(
        k in text for k in ("douyin.com", "ttwid", "sessionid")
    ):
        return jsonify(ok=False, error="文件格式不正确，请使用 Netscape 格式的 cookies.txt")

    cookie_id = uuid.uuid4().hex[:12]
    with _cookie_lock:
        _cookie_store[cookie_id] = text
    return jsonify(ok=True, cookie_id=cookie_id)


# ---------- 封面 / 图片代理（抖音防盗链） ----------

def _is_local_source(headers) -> bool:
    """Origin / Referer 若存在，必须来自本机地址，阻止恶意网页跨站触发。"""
    for key in ("Origin", "Referer"):
        val = headers.get(key)
        if not val:
            continue
        try:
            host = (urlparse(val).hostname or "").lower()
        except ValueError:
            return False
        if host not in ("127.0.0.1", "localhost", "::1"):
            return False
    return True


@app.get("/api/proxy")
def api_proxy():
    if not _is_local_source(request.headers):
        return jsonify(ok=False, error="来源不允许"), 403
    url = request.args.get("url", "")
    if not url.startswith(("http://", "https://")):
        return jsonify(ok=False, error="非法地址"), 400
    try:
        r = fetch_safe(url, headers={"User-Agent": UA,
                                     "Referer": "https://www.douyin.com/"})
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "image/jpeg")
        data = r.raw.read(5 * 1024 * 1024)
        r.close()
        return data, 200, {"Content-Type": ctype}
    except (requests.RequestException, ValueError):
        return jsonify(ok=False, error="图片获取失败"), 502


if __name__ == "__main__":
    print("  视频提取站已启动：http://127.0.0.1:5000")
    print("  下载文件保存目录：", DOWNLOADS)
    app.run(host="127.0.0.1", port=5000, threaded=True)
