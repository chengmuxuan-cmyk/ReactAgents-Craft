"""工具函数模块 - ReAct Agent 的能力实现

提供智能体可调用的各种工具函数。
每个工具都是一个独立的能力，智能体通过调用这些工具来完成用户的任务。

核心工具：
1. read_file: 读取文件内容
2. write_to_file: 写入文件（支持版本管理）
3. run_terminal_command: 执行终端命令（带安全检查）
4. preview_html_file: 在浏览器中预览 HTML 文件

作者：CMD
创建时间：2026-03-30
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import webbrowser
import html
import ipaddress
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from . import policy, runtime


# ==================== 索引管理辅助函数 ====================

def _load_index(index_path: str) -> dict:
    """
    加载文件索引数据
    
    索引文件记录了所有被修改过的文件的历史信息，包括：
    - 每次写入的时间戳
    - 使用的冲突策略
    - 备份文件路径
    - 文件大小等
    
    Args:
        index_path (str): 索引文件的绝对路径
        
    Returns:
        dict: 索引数据字典，格式为：
            {
                "files": {
                    "/absolute/path/to/file.txt": {
                        "writes": [...],  # 写入历史列表
                        "latest_write_at": "2026-03-30T12:00:00",
                        "latest_strategy": "versioned",
                        "latest_action": "created"
                    }
                }
            }
            
    Note:
        - 如果索引文件不存在或损坏，返回空结构
        - 总是确保返回的字典包含 "files" 键
    """
    # 索引文件不存在时，返回空结构
    if not os.path.exists(index_path):
        return {"files": {}}
    
    # 尝试读取并解析 JSON 索引文件
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 验证数据结构
        if not isinstance(data, dict):
            return {"files": {}}
        if "files" not in data or not isinstance(data["files"], dict):
            data["files"] = {}
        return data
    except Exception:
        # 任何异常（如 JSON 解析错误）都返回空结构
        return {"files": {}}


def _save_index(index_path: str, data: dict) -> None:
    """
    保存文件索引数据到磁盘
    
    Args:
        index_path (str): 索引文件的保存路径
        data (dict): 要保存的索引数据字典
        
    Note:
        - 使用 UTF-8 编码，支持中文路径和文件名
        - 格式化输出（indent=2），便于人工阅读和调试
    """
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _append_index_entry(file_path: str, entry: dict) -> None:
    """
    向文件索引中添加一条新的写入记录
    
    每次调用 write_to_file 成功后，都会调用此函数记录操作历史。
    这些信息对于版本追踪、审计、恢复等非常有用。
    
    Args:
        file_path (str): 被写入的文件绝对路径
        entry (dict): 写入记录的详细信息，包括：
            - timestamp (str): ISO 格式的时间戳
            - strategy (str): 使用的冲突策略（versioned/overwrite/skip）
            - action (str): 操作类型（created/updated_with_backup/updated_overwrite/skipped）
            - backup_path (str): 备份文件路径（如果有）
            - size_bytes (int): 写入内容的字节大小
            
    Side Effects:
        - 修改全局索引文件（.agent_index.json）
        - 如果索引文件不存在会自动创建
        
    Example Entry:
        {
            "timestamp": "2026-03-30T14:30:45",
            "strategy": "versioned",
            "action": "updated_with_backup",
            "backup_path": "/path/.history/file.txt.20260330-143045.bak",
            "size_bytes": 1024
        }
    """
    # 获取当前上下文的目录（通常是项目根目录）
    context_dir = runtime.get_context_dir()
    
    # 确保上下文目录存在
    os.makedirs(context_dir, exist_ok=True)
    
    # 构建索引文件的完整路径
    index_path = os.path.join(context_dir, runtime.INDEX_FILE_NAME)
    
    # 加载现有的索引数据
    data = _load_index(index_path)

    # 获取文件的绝对路径（确保一致性）
    abs_path = os.path.abspath(file_path)
    
    # 为该文件创建或获取条目
    file_bucket = data["files"].setdefault(abs_path, {"writes": []})
    
    # 更新最新写入时间
    file_bucket["latest_write_at"] = entry["timestamp"]
    
    # 更新最新使用的策略
    file_bucket["latest_strategy"] = entry["strategy"]
    
    # 更新最新的操作类型
    file_bucket["latest_action"] = entry["action"]
    
    # 将新记录添加到写入历史列表
    file_bucket.setdefault("writes", []).append(entry)
    
    # 保存更新后的索引到磁盘
    _save_index(index_path, data)


def _build_backup_path(abs_path: str) -> str:
    """
    为给定文件生成备份路径
    
    当使用 versioned 模式写入已存在的文件时，
    旧版本会被备份到此路径。
    
    Args:
        abs_path (str): 要备份的文件的绝对路径
        
    Returns:
        str: 备份文件的完整路径，格式为：
            {context_dir}/.history/{relative_path}.{timestamp}.bak
            
    Backup Path Examples:
        # 项目在上下文目录内的文件
        /project/test.py -> /project/.history/test.py.20260330-143045.bak
        
        # 项目外的文件（只保留文件名）
        C:/Users/test.py -> /project/.history/test.py.20260330-143045.bak
        
    Note:
        - 使用时间戳确保备份文件名唯一
        - 自动创建 .history 目录（如果不存在）
        - 处理 Windows 路径中的冒号等特殊字符
    """
    # 获取上下文目录
    context_dir = runtime.get_context_dir()
    
    # 构建历史备份目录
    history_root = os.path.join(context_dir, runtime.HISTORY_DIR_NAME)
    
    # 确保备份目录存在
    os.makedirs(history_root, exist_ok=True)

    # 生成时间戳后缀
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    # 判断文件是否在上下文目录内
    try:
        in_context = os.path.commonpath([context_dir, abs_path]) == context_dir
    except ValueError:
        # Windows 下不同驱动器的路径比较会抛出异常
        in_context = False

    # 如果在目录内，使用相对路径；否则只用文件名
    rel = os.path.relpath(abs_path, context_dir) if in_context else os.path.basename(abs_path)
    
    # 替换 Windows 路径中的冒号（避免文件系统不支持）
    rel = rel.replace(":", "_")
    
    # 构建完整的备份路径
    return os.path.join(history_root, f"{rel}.{ts}.bak")


def _is_command_safe(command: str) -> Tuple[bool, str]:
    """
    检查终端命令是否安全
    
    通过白名单和黑名单机制双重验证命令的安全性。
    这是防止危险操作的关键安全检查点。
    
    Args:
        command (str): 要检查的完整命令字符串
        
    Returns:
        Tuple[bool, str]: (是否安全，原因描述)
            - (True, "ok"): 命令安全，可以执行
            - (False, reason): 命令危险，禁止执行及原因
            
    Security Checks:
        1. 黑名单检查：命令中是否包含危险模式（如 rm, del, format 等）
        2. 白名单检查：命令的可执行文件是否在允许列表中
        3. 参数解析：确保命令可以正确解析为参数列表
        
    Example:
        >>> _is_command_safe("python test.py")
        (True, "ok")
        
        >>> _is_command_safe("rm -rf /")
        (False, "命中高危模式：rm ")
        
        >>> _is_command_safe("unknown_cmd")
        (False, "命令不在白名单：unknown_cmd")
    """
    # 将命令转为小写并添加空格，便于模式匹配
    normalized = f" {command.strip().lower()} "
    
    # 检查 1：黑名单模式匹配
    for pattern in policy.DANGEROUS_COMMAND_PATTERNS:
        if pattern in normalized:
            # 发现危险模式，立即拒绝
            return False, f"命中高危模式：{pattern.strip()}"

    # 检查 2：解析命令参数
    try:
        args = shlex.split(command, posix=False)
    except ValueError:
        # 命令语法错误，无法解析
        return False, "命令解析失败"

    # 空命令检查
    if not args:
        return False, "空命令"

    # 通过检查（仅保留危险模式拦截）
    return True, "ok"


# ==================== 公开的工具函数 ====================

def _resolve_in_context(file_path: str) -> str:
    """将路径解析到工作区内，禁止越界访问。"""
    context_dir = os.path.abspath(runtime.get_context_dir())
    candidate = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(context_dir, file_path)
    )
    if os.path.commonpath([context_dir, candidate]) != context_dir:
        raise ValueError(f"路径超出工作区：{candidate}")
    return candidate


def read_file(file_path: str, *_: str) -> str:
    """读取文件内容。"""
    abs_path = _resolve_in_context(file_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def write_to_file(file_path: str, content: str, *extra_parts: str) -> str:
    """将内容写入文件。"""
    abs_path = _resolve_in_context(file_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    # 兼容模型把同一段内容拆成多个参数的情况
    full_content = "".join([str(content), *[str(p) for p in extra_parts]])
    rendered_content = full_content.replace("\\n", "\n")

    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(rendered_content)
    return f"写入成功：{abs_path}"


def run_terminal_command(command: str) -> str:
    """执行终端命令（受运行时开关与策略约束）。

    Args:
        command: 要执行的命令。

    Returns:
        标准输出或错误信息。
    """
    # 检查 1：全局开关
    if not runtime.COMMAND_EXECUTION_ENABLED:
        return "安全策略：终端命令执行已禁用（使用 --allow-command 可开启）。"

    # 检查 2：安全性验证
    safe, reason = _is_command_safe(command)
    if not safe:
        # 命令不安全，拒绝执行
        return f"安全策略：已拒绝执行命令。原因：{reason}"

    # 解析命令为参数列表（避免 shell 注入）
    try:
        args = shlex.split(command, posix=False)
    except ValueError as e:
        return f"命令解析失败：{str(e)}"

    # 执行命令（不使用 shell，更安全）
    try:
        if os.name == "nt":
            run_result = subprocess.run(
                command,
                shell=True,
                capture_output=True,  # 捕获标准输出和标准错误
                text=True,  # 返回字符串而非字节
                cwd=runtime.get_context_dir(),  # 在项目目录下执行
                timeout=20,  # 20 秒超时保护
            )
        else:
            run_result = subprocess.run(
                args,
                shell=False,  # 重要：禁用 shell，防止注入攻击
                capture_output=True,  # 捕获标准输出和标准错误
                text=True,  # 返回字符串而非字节
                cwd=runtime.get_context_dir(),  # 在项目目录下执行
                timeout=20,  # 20 秒超时保护
            )
    except subprocess.TimeoutExpired:
        return "命令执行超时（20s），已终止。"
    except Exception as e:
        return f"命令执行失败：{str(e)}"

    # 检查命令执行结果
    if run_result.returncode == 0:
        # 成功：返回标准输出（如果有）
        return run_result.stdout if run_result.stdout.strip() else "执行成功（无输出）"
    # 失败：返回标准错误
    return run_result.stderr if run_result.stderr.strip() else "命令执行失败（无错误输出）"


def preview_html_file(file_path: str) -> str:
    """在默认浏览器打开本地 HTML 文件。

    Args:
        file_path: HTML 文件路径。

    Returns:
        执行结果描述。
    """
    # 获取文件的绝对路径
    abs_path = os.path.abspath(file_path)
    
    # 检查 1：文件是否存在
    if not os.path.exists(abs_path):
        return f"HTML 文件不存在：{abs_path}"
    
    # 检查 2：是否是 HTML 文件
    if not abs_path.lower().endswith(".html"):
        return f"不是 HTML 文件：{abs_path}"

    # 使用系统默认浏览器打开 HTML 文件
    # Path.as_uri() 将本地路径转为 file:// URL 格式
    webbrowser.open(Path(abs_path).as_uri())
    
    return f"已在浏览器打开：{abs_path}"


def _is_public_http_url(url: str) -> Tuple[bool, str]:
    """检查 URL 是否可用于公网抓取，拒绝本地与内网地址。"""
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
        # DNS 失败时不提前拒绝，由请求阶段返回错误信息更直观
        pass

    return True, "ok"


def _html_to_text(raw_html: str) -> str:
    """将 HTML 转成可读纯文本。"""
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
    """使用 DuckDuckGo 搜索网页内容（非 Google）。

    Args:
        query: 搜索关键词。
        max_results: 返回条数（1-10）。

    Returns:
        格式化搜索结果。
    """
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
    """抓取 URL 页面并返回正文摘要。

    Args:
        url: 目标地址（http/https）。
        max_chars: 摘要最大长度。
        include_links: 是否附带页面链接。

    Returns:
        抓取结果文本。
    """
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


def get_default_project_directory() -> str:
    """
    获取默认的项目工作目录
    
    当用户未指定项目目录时，使用此函数返回一个固定的 temp 目录。
    这样可以确保即使用户不指定目录，程序也能正常运行。
    
    Returns:
        str: 默认项目目录的绝对路径（{repo_root}/temp）
        
    Side Effects:
        - 如果 temp 目录不存在，会自动创建
        
    Usage:
        >>> get_default_project_directory()
        'E:\\my_project\\temp'
        
    Note:
        - 该目录固定为仓库根目录下的 temp 文件夹
        - 适合用于临时测试和快速原型开发
    """
    # 获取本文件所在项目的根目录（向上两级）
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 构建 temp 目录路径
    temp_dir = os.path.join(root_dir, "temp")
    
    # 确保目录存在
    os.makedirs(temp_dir, exist_ok=True)
    
    return temp_dir

