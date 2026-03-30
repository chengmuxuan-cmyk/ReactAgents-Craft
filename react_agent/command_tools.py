from __future__ import annotations

import os
import shlex
import subprocess
from typing import Tuple

from . import policy, runtime


def _is_command_safe(command: str) -> Tuple[bool, str]:
    """Check command against dangerous patterns."""
    normalized = f" {command.strip().lower()} "
    for pattern in policy.DANGEROUS_COMMAND_PATTERNS:
        if pattern in normalized:
            return False, f"命中高危模式：{pattern.strip()}"

    try:
        args = shlex.split(command, posix=False)
    except ValueError:
        return False, "命令解析失败"
    if not args:
        return False, "空命令"
    return True, "ok"


def run_terminal_command(command: str) -> str:
    """执行终端命令（需先启用 --allow-command）。"""
    if not runtime.COMMAND_EXECUTION_ENABLED:
        return "安全策略：终端命令执行已禁用（使用 --allow-command 可开启）。"

    safe, reason = _is_command_safe(command)
    if not safe:
        return f"安全策略：已拒绝执行命令。原因：{reason}"

    try:
        if os.name == "nt":
            run_result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=runtime.get_context_dir(),
                timeout=20,
            )
        else:
            args = shlex.split(command, posix=False)
            run_result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                cwd=runtime.get_context_dir(),
                timeout=20,
            )
    except subprocess.TimeoutExpired:
        return "命令执行超时（20s），已终止。"
    except Exception as e:
        return f"命令执行失败：{str(e)}"

    if run_result.returncode == 0:
        return run_result.stdout if run_result.stdout.strip() else "执行成功（无输出）"
    return run_result.stderr if run_result.stderr.strip() else "命令执行失败（无错误输出）"

