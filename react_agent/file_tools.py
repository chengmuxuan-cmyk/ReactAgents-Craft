from __future__ import annotations

import os

from . import runtime


def _resolve_in_context(file_path: str) -> str:
    """Resolve path inside current runtime context directory."""
    context_dir = os.path.abspath(runtime.get_context_dir())
    candidate = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(context_dir, file_path)
    )
    if os.path.commonpath([context_dir, candidate]) != context_dir:
        raise ValueError(f"路径超出工作区：{candidate}")
    return candidate


def read_file(file_path: str, *_: str) -> str:
    """读取工作目录内文本文件。"""
    abs_path = _resolve_in_context(file_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def write_to_file(file_path: str, content: str, *extra_parts: str) -> str:
    """覆盖写入工作目录内文本文件。"""
    abs_path = _resolve_in_context(file_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    full_content = "".join([str(content), *[str(p) for p in extra_parts]])
    rendered_content = full_content.replace("\\n", "\n")

    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(rendered_content)
    return f"写入成功：{abs_path}"

