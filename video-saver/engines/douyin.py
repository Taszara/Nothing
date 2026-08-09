# -*- coding: utf-8 -*-
"""抖音专用解析器（纯 HTTP）。

流程：任意抖音链接（含 v.douyin.com 短链）规整为数值作品 ID ->
抓取移动端分享页 www.iesdouyin.com/share/video/{id}（页面仍内嵌
window._ROUTER_DATA）-> 提取 aweme_detail ->
得到无水印视频直链（playwm 替换为 play）或图文图片列表。

注意：桌面端作品页已是 JS 空壳，不再内嵌数据；抖音反爬规则多变，
若分享页结构变化导致解析失败，上层会降级到 yt-dlp。
"""
import json
import re
import urllib.parse

import requests

from utils import UA

BASE_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.douyin.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class DouyinError(Exception):
    pass


# ---------- 页面 JSON 提取 ----------

_JSON_PATTERNS = [
    # 现代版：<script id="RENDER_DATA" type="application/json">...</script>（内容为 url 编码）
    (r'<script\s+id="RENDER_DATA"[^>]*>(.*?)</script>', "quote"),
    # SSR 版：window._ROUTER_DATA = {...}
    (r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", "json"),
    (r"window\._ROUTER_DATA\s*=\s*(\{.*?)\};?\s*</script>", "json"),
    # 初始化数据：window.__INIT_PROPS__
    (r"window\.__INIT_PROPS__\s*=\s*(\{.*?\})\s*</script>", "json"),
]


def _extract_json(html: str) -> dict | None:
    for pattern, mode in _JSON_PATTERNS:
        m = re.search(pattern, html, re.S)
        if not m:
            continue
        raw = m.group(1)
        try:
            if mode == "quote":
                raw = urllib.parse.unquote(raw)
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _find_aweme(obj) -> dict | None:
    """递归查找形如 aweme_detail 的字典（含 aweme_id + 视频/图文/描述）。"""
    if isinstance(obj, dict):
        if "aweme_id" in obj and "desc" in obj and (
            "video" in obj or "images" in obj
        ):
            return obj
        for v in obj.values():
            found = _find_aweme(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_aweme(v)
            if found:
                return found
    return None


# ---------- 链接处理 ----------

MOBILE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                   "Mobile/15E148 Safari/604.1"),
    "Referer": "https://www.douyin.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_ID_RE = re.compile(r"/(?:video|note|share/(?:video|note))/(\d{10,})/?")


def _extract_aweme_id(url: str) -> str | None:
    m = _ID_RE.search(url)
    return m.group(1) if m else None


def _normalize(url: str, session: requests.Session) -> str:
    """把任意抖音链接规整为数值作品 ID。"""
    aweme_id = _extract_aweme_id(url)
    if aweme_id:
        return aweme_id
    # v.douyin.com 短链：跟随重定向拿到最终作品页再取 ID
    resp = session.get(url, headers=BASE_HEADERS, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    aweme_id = _extract_aweme_id(resp.url)
    if not aweme_id:
        raise DouyinError("无法识别抖音作品 ID，请检查链接是否完整")
    return aweme_id


def _fetch_share_page(aweme_id: str, session: requests.Session) -> str:
    """移动端分享页仍内嵌 _ROUTER_DATA，是当前最稳的纯 HTTP 数据源。"""
    resp = session.get(
        f"https://www.iesdouyin.com/share/video/{aweme_id}/",
        headers=MOBILE_HEADERS, timeout=20,
    )
    resp.raise_for_status()
    return resp.text


def _build_session(cookies: str | None = None) -> requests.Session:
    s = requests.Session()
    if cookies:
        s.headers["Cookie"] = cookies
    return s


def _pick_video_url(aweme: dict) -> str | None:
    """从 aweme.video 中挑选最高质量的直链，并去除水印（playwm->play）。"""
    video = aweme.get("video") or {}
    candidates = []

    # 按码率从高到低收集 play_addr
    for br in sorted(video.get("bit_rate") or [], key=lambda b: -b.get("bit_rate", 0)):
        for u in (br.get("play_addr") or {}).get("url_list") or []:
            candidates.append(u)
    for u in (video.get("play_addr") or {}).get("url_list") or []:
        candidates.append(u)
    for u in (video.get("download_addr") or {}).get("url_list") or []:
        candidates.append(u)
    if not candidates:
        return None

    # 优先无水印的 play 地址；playwm 视为水印版，替换成 play
    url = candidates[0]
    for c in candidates:
        if "playwm" not in c:
            url = c
            break
    return url.replace("playwm", "play")


def _pick_image_urls(aweme: dict) -> list[str]:
    """图文：提取每张图的直链。"""
    urls = []
    for img in aweme.get("images") or []:
        lst = (img or {}).get("url_list") or []
        if lst:
            urls.append(lst[0])
    return urls


# ---------- 对外接口 ----------

def parse(url: str, cookies: str | None = None) -> dict:
    """解析抖音分享链接，返回统一元信息结构。"""
    session = _build_session(cookies)
    try:
        aweme_id = _normalize(url, session)
        html = _fetch_share_page(aweme_id, session)
    except requests.RequestException as e:
        raise DouyinError(f"无法访问链接：{e}") from e

    data = _extract_json(html)
    aweme = _find_aweme(data) if data else None
    if not aweme:
        raise DouyinError(
            "未能在页面中找到作品数据（抖音反爬或作品已删除）。"
            "可尝试上传 Cookie 后重试。"
        )

    desc = aweme.get("desc") or "抖音作品"
    author = (aweme.get("author") or {}).get("nickname") or ""

    images = _pick_image_urls(aweme)
    if images:
        return {
            "type": "images",
            "title": desc,
            "author": author,
            "cover": images[0],
            "count": len(images),
            "urls": images,
            "engine": "douyin",
        }

    video_url = _pick_video_url(aweme)
    if not video_url:
        raise DouyinError("未能获取到视频直链（可能需要 Cookie）。")

    cover = ""
    cover_obj = (aweme.get("video") or {}).get("cover")
    if isinstance(cover_obj, dict):
        cover = (cover_obj.get("url_list") or [""])[0]
    elif isinstance(cover_obj, list) and cover_obj:
        first = cover_obj[0]
        if isinstance(first, dict):
            cover = (first.get("url_list") or [""])[0]
        else:
            cover = first

    return {
        "type": "video",
        "title": desc,
        "author": author,
        "cover": cover,
        "count": 1,
        "urls": [video_url],
        "engine": "douyin",
    }
