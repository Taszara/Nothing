# -*- coding: utf-8 -*-
"""通用工具：分享文案链接提取、平台识别、文件名清洗、SSRF 防护。"""
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import requests

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


# ---------- SSRF 防护 ----------


def _is_private_ip(ip: str) -> bool:
    """判断 IP 是否属于不可对外访问的保留/私网段。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_loopback or addr.is_private or addr.is_link_local \
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return True
    if isinstance(addr, ipaddress.IPv4Address):
        # CGNAT / IETF 保留 / 基准测试段 / 保留段（240/4）
        for net in ("100.64.0.0/10", "192.0.0.0/24",
                    "198.18.0.0/15", "240.0.0.0/4"):
            if addr in ipaddress.ip_network(net):
                return True
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:  # ::ffff:x.x.x.x 形式的 IPv4 地址
            return _is_private_ip(str(addr.ipv4_mapped))
        # 文档示例段 / NAT64 前缀
        for net in ("2001:db8::/32", "64:ff9b::/96"):
            if addr in ipaddress.ip_network(net):
                return True
    return False


def is_safe_proxy_url(url: str) -> bool:
    """仅允许解析到公网 IP 的 http(s) 地址（SSRF 防护）。

    逐条校验：协议必须为 http/https，主机名不得为本机，
    解析出的所有 IP 都不能落在私网/回环/链路本地/云元数据等保留段。
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower()
    if hostname in ("localhost", "localhost.localdomain"):
        return False
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        if _is_private_ip(info[4][0]):
            return False
    return True


def fetch_safe(url: str, headers: dict, timeout: int = 15,
               max_redirects: int = 5):
    """带 SSRF 防护的 GET 请求：每一跳重定向都会重新校验目标地址。

    禁止把 requests 的 allow_redirects 重新打开，否则会绕过上面的 IP 校验。
    """
    current = url
    for _ in range(max_redirects + 1):
        if not is_safe_proxy_url(current):
            raise ValueError("目标地址不在允许范围")
        r = requests.get(current, headers=headers, timeout=timeout,
                         stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            r.close()
            if not loc:
                break
            current = urljoin(current, loc)
            continue
        return r
    raise ValueError("重定向次数过多")
