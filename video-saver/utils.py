# -*- coding: utf-8 -*-
"""通用工具：分享文案链接提取、平台识别、文件名清洗。"""
import re

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 平台识别：域名 -> 内部标识
PLATFORM_RULES = [
    ("douyin",   ("douyin.com", "iesdouyin.com")),
    ("kuaishou", ("kuaishou.com", "gifshow.com", "chenzhongtech.com")),
    ("bilibili", ("bilibili.com", "b23.tv", "bilibili.tv")),
    ("weibo",    ("weibo.com", "weibo.cn")),
    ("xiaohongshu", ("xiaohongshu.com", "xhslink.com")),
    ("ixigua",   ("ixigua.com")),
    ("youtube",  ("youtube.com", "youtu.be")),
    ("tiktok",   ("tiktok.com", "douyin.com")),
]

PLATFORM_NAMES = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "bilibili": "哔哩哔哩",
    "weibo": "微博",
    "xiaohongshu": "小红书",
    "ixigua": "西瓜视频",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "other": "其他平台",
}

_URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff，。；、！？（）()【】\[\]\"'“”‘’<>]+")
_TRAILING_PUNCT = "，。；、！？）】\"'“”‘’"


def extract_url(text: str):
    """从分享文案中提取第一个链接。"""
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(_TRAILING_PUNCT)
    return url or None


def detect_platform(url: str):
    """按域名判定平台，返回内部标识。"""
    low = url.lower()
    for key, domains in PLATFORM_RULES:
        if any(d in low for d in domains):
            return key
    return "other"


def platform_name(key: str) -> str:
    return PLATFORM_NAMES.get(key, key or "其他平台")


_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t\x00-\x1f]')


def sanitize_filename(name: str, fallback: str = "download", max_len: int = 80) -> str:
    """清洗为安全的文件名（不含扩展名）。"""
    if not name:
        name = fallback
    name = _ILLEGAL.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = fallback
    return name[:max_len]


def ensure_unique(path):
    """若文件已存在，追加 (1)(2) 序号，返回不冲突的新路径。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        cand = path.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1
