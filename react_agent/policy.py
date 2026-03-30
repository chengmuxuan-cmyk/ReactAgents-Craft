"""安全策略模块 - 终端命令执行控制

提供终端命令执行的安全检查机制，防止危险操作。
包括白名单（允许的命令）和黑名单（禁止的模式）。

核心功能：
1. 白名单机制：只允许执行指定的安全命令
2. 黑名单机制：禁止包含危险模式的命令
3. 动态策略加载：支持从 JSON 文件自定义策略

作者：CMD
创建时间：2026-03-30
"""

from __future__ import annotations

import json
import os
from typing import Tuple

# ==================== 默认安全策略 ====================

# 白名单：允许执行的命令（只包含这些命令的可执行文件）
# 这些命令通常被认为是相对安全的开发工具
SAFE_COMMAND_WHITELIST = {
    "python",      # Python 解释器
    "python3",     # Python 3 解释器
    "py",          # Python 启动器（Windows）
    "uv",          # UV 包管理器
    "pytest",      # Python 测试框架
    "pip",         # Python 包安装器
    "pip3",        # Python 3 包安装器
    "node",        # Node.js 运行时
    "npm",         # Node.js 包管理器
}

# 黑名单：危险命令模式（只要命令中包含这些字符串就会被禁止）
# 这些模式通常与系统破坏、数据删除等危险操作相关
DANGEROUS_COMMAND_PATTERNS = [
    " rm ",         # Linux/Mac 删除命令
    "del ",         # Windows 删除命令
    "rmdir ",       # 删除目录
    "format ",      # 格式化磁盘
    "mkfs",         # 创建文件系统
    "shutdown",     # 关机
    "reboot",       # 重启
    "powershell -enc",  # PowerShell 编码执行（常用于绕过安全限制）
    "curl ",        # 下载文件（可能下载恶意内容）
    "wget ",        # 下载文件
    "invoke-webrequest",  # PowerShell 下载
]


def load_policy_from_json(policy_path: str) -> Tuple[bool, str]:
    """
    从 JSON 文件加载自定义安全策略
    
    当策略文件存在时，会覆盖默认的白名单和黑名单。
    这允许用户根据实际需求灵活调整安全策略。
    
    Args:
        policy_path (str): 策略 JSON 文件的路径
        
    Returns:
        Tuple[bool, str]: (是否加载成功，消息描述)
            - (True, "policy loaded"): 成功加载策略
            - (False, error_message): 加载失败及原因
            
    JSON Format:
        {
          "whitelist": ["python", "uv", "custom_command"],
          "dangerous_patterns": [" rm ", "del ", "custom_pattern"]
        }
        
    Example JSON:
        {
          "whitelist": ["python", "uv", "node", "npm"],
          "dangerous_patterns": [" rm ", "del ", "sudo "]
        }
        
    Security Note:
        - 修改白名单需谨慎，确保添加的命令是安全的
        - 黑名单可以添加自定义模式来增强安全性
        - 策略文件应该放在项目根目录，避免被随意修改
        
    Usage:
        >>> loaded, msg = load_policy_from_json("./command_policy.json")
        >>> if loaded:
        ...     print(f"策略已加载：{msg}")
        ... else:
        ...     print(f"策略加载失败：{msg}")
    """
    # 检查策略文件是否存在
    if not os.path.exists(policy_path):
        return False, f"policy file not found: {policy_path}"

    # 尝试读取并解析 JSON 文件
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # JSON 解析失败（可能是格式错误、编码问题等）
        return False, f"failed to parse policy JSON: {e}"

    # 更新白名单（如果 JSON 中提供了 whitelist 字段）
    if isinstance(data.get("whitelist"), list):
        # 清空默认白名单
        SAFE_COMMAND_WHITELIST.clear()
        # 添加自定义白名单（全部转为小写，忽略大小写差异）
        SAFE_COMMAND_WHITELIST.update(str(x).lower() for x in data["whitelist"])

    # 更新黑名单（如果 JSON 中提供了 dangerous_patterns 字段）
    if isinstance(data.get("dangerous_patterns"), list):
        # 清空默认黑名单
        DANGEROUS_COMMAND_PATTERNS.clear()
        # 添加自定义黑名单（全部转为小写）
        DANGEROUS_COMMAND_PATTERNS.extend(str(x).lower() for x in data["dangerous_patterns"])

    # 策略加载成功
    return True, "policy loaded"

