from __future__ import annotations

import html
import ipaddress
import re
import socket
from typing import Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests


def _is_public_http_url(url: str) -> Tuple[bool, str]:
    """Allow only public http(s) URLs."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "仅支持 http/https URL"
    if not parsed.hostname:
        return False, "URL 缺少主机名"

    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False, "禁止访问本地地址"

    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                return False, f"禁止访问内网/保留地址：{ip}"
    except Exception:
        pass

    return True, "ok"


def _html_to_text(raw_html: str) -> str:
    """Convert HTML to readable text."""
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?is)<br\\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p\\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</h[1-6]\\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<li\\s*>", "\n- ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \\t\\r\\f\\v]+", " ", cleaned)
    cleaned = re.sub(r"\\n\\s*\\n+", "\n\n", cleaned)
    return cleaned.strip()


def web_search(query: str, max_results: int = 5) -> str:
    """使用 DuckDuckGo 搜索网页内容（非 Google）。"""
    query = query.strip()
    if not query:
        return "搜索词不能为空。"

    limit = max(1, min(int(max_results), 10))
    endpoint = "https://duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ReActAgent/1.0; +https://duckduckgo.com/)",
    }

    try:
        resp = requests.get(endpoint, params={"q": query}, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return f"搜索失败：{str(e)}"

    result_blocks = re.findall(r'(?is)<a[^>]*class="result__a"[^>]*>.*?</a>', resp.text)
    if not result_blocks:
        return "未检索到结果。"

    lines = [f"搜索词：{query}", "搜索引擎：DuckDuckGo", ""]
    count = 0
    for block in result_blocks:
        if count >= limit:
            break
        href_match = re.search(r'href="([^"]+)"', block, re.IGNORECASE)
        title = _html_to_text(block)
        if not href_match or not title:
            continue

        raw_href = html.unescape(href_match.group(1))
        parsed = urlparse(raw_href)
        if parsed.path.startswith("/l/"):
            q = parse_qs(parsed.query)
            if "uddg" in q and q["uddg"]:
                raw_href = unquote(q["uddg"][0])
        if raw_href.startswith("//"):
            raw_href = f"https:{raw_href}"
        if not raw_href.startswith(("http://", "https://")):
            continue

        count += 1
        lines.append(f"{count}. {title}")
        lines.append(f"   {raw_href}")

    if count == 0:
        return "未检索到可用结果。"
    return "\n".join(lines)


def crawl_url(url: str, max_chars: int = 4000, include_links: bool = True) -> str:
    """抓取 URL 页面并返回正文摘要。"""
    url = url.strip()
    ok, reason = _is_public_http_url(url)
    if not ok:
        return f"抓取被拒绝：{reason}"

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ReActAgent/1.0)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return f"抓取失败：{str(e)}"

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        return f"抓取失败：不支持的内容类型 {content_type or 'unknown'}"

    final_url = resp.url
    body_text = _html_to_text(resp.text)
    if not body_text:
        body_text = "(页面正文为空)"

    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", resp.text)
    title = _html_to_text(title_match.group(1)) if title_match else "(无标题)"

    limit = max(200, min(int(max_chars), 20000))
    excerpt = body_text[:limit]
    if len(body_text) > limit:
        excerpt += "\n\n...(已截断)"

    lines = [
        f"URL: {url}",
        f"最终地址: {final_url}",
        f"标题: {title}",
        "",
        "正文摘要：",
        excerpt,
    ]

    if include_links and "text/html" in content_type:
        hrefs = re.findall(r'(?is)<a[^>]+href="([^"]+)"', resp.text)
        unique_links = []
        seen = set()
        for href in hrefs:
            absolute = urljoin(final_url, html.unescape(href).strip())
            if not absolute.startswith(("http://", "https://")):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            unique_links.append(absolute)
            if len(unique_links) >= 10:
                break
        if unique_links:
            lines.extend(["", "页面链接（最多 10 条）："])
            for idx, link in enumerate(unique_links, start=1):
                lines.append(f"{idx}. {link}")

    return "\n".join(lines)

