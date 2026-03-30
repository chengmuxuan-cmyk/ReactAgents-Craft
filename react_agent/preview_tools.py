from __future__ import annotations

import os
import webbrowser
from pathlib import Path


def preview_html_file(file_path: str) -> str:
    """在默认浏览器打开本地 HTML 文件。"""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return f"HTML 文件不存在：{abs_path}"
    if not abs_path.lower().endswith(".html"):
        return f"不是 HTML 文件：{abs_path}"
    webbrowser.open(Path(abs_path).as_uri())
    return f"已在浏览器打开：{abs_path}"

