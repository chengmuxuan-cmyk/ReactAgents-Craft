"""运行时上下文管理

提供全局的运行时配置，供工具函数和其他模块使用。
通过设置全局变量，实现跨模块的状态共享。

核心功能：
1. 项目目录上下文：所有文件操作都基于此目录
2. 写入冲突策略：控制文件覆盖行为
3. 命令执行开关：全局禁用/启用终端命令
作者：CMX
创建时间：2026-03-30
"""

from __future__ import annotations

import os

# ==================== 全局运行时变量 ====================

# 文件写入冲突处理策略
# 可选值："versioned"（版本备份）, "overwrite"（直接覆盖）, "skip"（跳过）
WRITE_CONFLICT_STRATEGY = "versioned"

# 当前会话的项目根目录
# 所有文件读写操作都相对于此目录
TOOL_CONTEXT_PROJECT_DIR: str | None = None

# 索引文件名
# 用于记录文件修改历史、版本信息等元数据
INDEX_FILE_NAME = ".agent_index.json"

# 历史备份目录名
# versioned 模式下，旧版本文件会保存在此目录
HISTORY_DIR_NAME = ".history"

# 终端命令执行总开关
# False=完全禁用，True=允许执行（需配合安全策略检查）
COMMAND_EXECUTION_ENABLED = False


def set_runtime_context(project_dir: str, write_mode: str, allow_command: bool) -> None:
    """
    设置运行时上下文
    
    在 CLI 启动时调用一次，设置整个会话期间的全局状态。
    这些状态会影响后续所有工具函数的行为。
    
    Args:
        project_dir (str): 项目根目录的绝对路径
            - 所有文件操作（读/写）都相对于此目录
            - 历史备份也会保存在此目录下
        write_mode (str): 文件写入冲突处理策略
            - "versioned": 创建版本备份（默认，最安全）
            - "overwrite": 直接覆盖旧文件
            - "skip": 如果文件已存在则跳过
        allow_command (bool): 是否允许执行终端命令
            - True: 允许执行（仍需通过安全策略检查）
            - False: 完全禁用终端命令执行
            
    Global State Modified:
        - TOOL_CONTEXT_PROJECT_DIR: 设置为传入的 project_dir
        - WRITE_CONFLICT_STRATEGY: 设置为传入的 write_mode（转小写）
        - COMMAND_EXECUTION_ENABLED: 设置为传入的 allow_command
        
    Usage Example:
        >>> # CLI 启动时调用
        >>> set_runtime_context("/path/to/project", "versioned", False)
        >>> 
        >>> # 之后工具函数会使用这些全局设置
        >>> write_to_file("test.txt", "content")  # 会自动备份到 .history/
    """
    global TOOL_CONTEXT_PROJECT_DIR, WRITE_CONFLICT_STRATEGY, COMMAND_EXECUTION_ENABLED
    
    # 保存项目目录的绝对路径
    TOOL_CONTEXT_PROJECT_DIR = os.path.abspath(project_dir)
    
    # 保存写入策略（统一转为小写，避免大小写不一致）
    WRITE_CONFLICT_STRATEGY = write_mode.lower()
    
    # 设置命令执行总开关
    COMMAND_EXECUTION_ENABLED = allow_command


def get_context_dir() -> str:
    """
    获取当前上下文的目录路径
    
    这是一个安全的访问器函数，确保总是返回有效的目录路径。
    即使 TOOL_CONTEXT_PROJECT_DIR 未设置，也会返回一个默认值。
    
    Returns:
        str: 当前上下文目录的绝对路径
            - 如果 TOOL_CONTEXT_PROJECT_DIR 已设置，返回它
            - 否则返回本模块所在的目录（作为后备）
            
    Usage:
        >>> # 工具函数中获取工作目录
        >>> context_dir = get_context_dir()
        >>> file_path = os.path.join(context_dir, "myfile.txt")
        
    Note:
        该函数保证了返回值总是有效的目录路径，避免了 None 值检查
    """
    # 如果已经设置了项目目录，返回它
    if TOOL_CONTEXT_PROJECT_DIR:
        return TOOL_CONTEXT_PROJECT_DIR
    
    # 否则返回本模块所在的目录（作为默认值）
    return os.path.dirname(os.path.abspath(__file__))
