"""命令行接口 (CLI) 入口

提供用户与 ReAct Agent 交互的命令行界面。
支持多种启动参数和交互式会话管理。

核心功能：
1. 解析命令行参数（模型选择、调试模式等）
2. 初始化运行时上下文和安全策略
3. 管理用户会话（新任务/继续任务/退出）
4. 显示调试信息（可选）

作者：CMX
创建时间：2026-03-30
"""

from __future__ import annotations

import os

import click

from .core import ReActAgent
from .policy import load_policy_from_json
from .runtime import set_runtime_context
from .command_tools import run_terminal_command
from .file_tools import read_file, write_to_file
from .preview_tools import preview_html_file
from .tools import get_default_project_directory
from .web_tools import crawl_url, web_search


@click.command()
@click.argument("project_directory", required=False, type=click.Path(file_okay=False, dir_okay=True))
@click.option("--deepseek", "-d", is_flag=True, help="使用 DeepSeek API（默认使用 OpenRouter）")
@click.option("--model", "-m", default=None, help="指定模型名称（DeepSeek 默认 deepseek-chat，OpenRouter 默认 openai/gpt-4o）")
@click.option("--debug", is_flag=True, help="开启调试模式，打印模型交互与 action 解析细节")
@click.option("--allow-command", is_flag=True, help="允许执行终端命令（默认禁用，存在风险）")
def main(
    project_directory: str | None,
    deepseek: bool,
    model: str | None,
    debug: bool,
    allow_command: bool,
):
    """
    CLI 入口函数 - 程序的主入口点
    
    该函数负责：
    1. 解析所有命令行参数
    2. 设置运行时环境（项目目录、写入策略、命令执行权限）
    3. 加载安全策略文件
    4. 创建并配置 ReActAgent 实例
    5. 进入交互式会话循环
    
    Args:
        project_directory (str | None): 项目根目录路径。如果未提供，使用默认的 temp 目录
        deepseek (bool): 是否使用 DeepSeek API。True=DeepSeek，False=OpenRouter
        model (str | None): 自定义模型名称。None 时使用默认值
        debug (bool): 是否开启调试模式。开启后会打印详细的交互日志
        allow_command (bool): 是否允许执行终端命令。出于安全考虑，默认禁用
    Usage Examples:
        # 使用默认的 GPT-4o
        uv run agent.py
        
        # 使用 DeepSeek
        uv run agent.py --deepseek
        
        # 指定项目和模型
        uv run agent.py ./my_project -d -m deepseek-coder
        
        # 开启调试模式和命令执行
        uv run agent.py --debug --allow-command
        
    """
    # 获取项目的绝对路径
    # 如果用户未提供，使用默认目录（temp 文件夹）
    project_dir = os.path.abspath(project_directory) if project_directory else get_default_project_directory()
    
    # 确保项目目录存在，不存在则创建
    os.makedirs(project_dir, exist_ok=True)

    # 设置全局运行时上下文
    # 这会影响后续工具函数的行为（如文件写入、命令执行等）
    set_runtime_context(project_dir, "overwrite", allow_command)

    # 从项目根目录加载可选的安全策略文件
    # 策略文件可以自定义白名单和黑名单规则
    policy_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "command_policy.json")
    loaded, msg = load_policy_from_json(policy_path)

    # 定义智能体可用的工具列表
    # 这些工具会被注册到 ReActAgent 中，供 AI 调用
    tools = [
        read_file,
        write_to_file,
        run_terminal_command,
        preview_html_file,
        web_search,
        crawl_url,
    ]
    
    # 如果开启调试模式，打印所有配置信息
    if debug:
        print("🐞 调试模式已开启")
        print(f"📁 project_dir={project_dir}")
        print("🗂️ write_mode=overwrite")
        print(f"🛡️ allow_command={allow_command}")
        print(f"📜 policy={msg if loaded else msg}")

    # 根据命令行参数创建智能体实例
    # 支持 DeepSeek 和 OpenRouter 两种 API 提供商
    if deepseek:
        # 使用 DeepSeek API
        model_name = model or "deepseek-chat"  # 如果未指定模型，使用默认的 deepseek-chat
        print(f"\n🚀 将使用 DeepSeek API - 模型：{model_name}")
        agent = ReActAgent(
            tools=tools,
            model=model_name,
            project_directory=project_dir,
            use_deepseek=True,  # 标记使用 DeepSeek
            debug=debug,  # 传递调试模式标志
            allow_command_execution=allow_command,  # 传递命令执行权限
        )
    else:
        # 使用 OpenRouter API（默认）
        model_name = model or "openai/gpt-4o"  # 如果未指定模型，使用默认的 GPT-4o
        print(f"\n🚀 将使用 OpenRouter API - 模型：{model_name}")
        agent = ReActAgent(
            tools=tools,
            model=model_name,
            project_directory=project_dir,
            use_deepseek=False,  # 标记使用 OpenRouter
            debug=debug,
            allow_command_execution=allow_command,
        )

    # 会话管理变量
    # continue_session 控制是否在下一轮对话中保留上下文
    continue_session = False
    
    # 主交互循环 - 持续响应用户请求直到用户选择退出
    while True:
        if continue_session and agent.session_messages:
            # 继续之前的会话（保留上下文）
            # 用户可以补充需求或修改之前的任务
            task = input("\n请输入继续任务的补充需求（直接回车可取消继续）：").strip()
            if not task:
                print("已取消继续当前任务，返回菜单。")
                continue_session = False
                continue
            # 运行智能体，continue_session=True 表示保留历史消息
            final_answer = agent.run(task, continue_session=True)
        else:
            # 开始新任务或首次运行
            task = input("请输入任务：").strip()
            if not task:
                print("任务不能为空，请重新输入。")
                continue
            # 运行智能体，continue_session=False 表示清空历史
            final_answer = agent.run(task, continue_session=False)

        # 打印智能体的最终回答
        print(f"\n\n✅ Final Answer：{final_answer}")

        # 显示下一步操作菜单
        print("\n下一步请选择：")
        print("1) 开始新任务（清空上下文）")
        print("2) 继续当前任务（保留上下文）")
        print("3) 退出程序")
        choice = input("请输入选项（1/2/3）：").strip()

        # 处理用户选择
        if choice == "1":
            # 选项 1：开始新任务，清空会话历史
            agent.reset_session()
            continue_session = False
            continue
        if choice == "2":
            # 选项 2：继续当前任务，保留会话历史
            if agent.session_messages:
                continue_session = True
                continue
            print("当前没有可继续的上下文，将开始新任务。")
            continue_session = False
            continue
        # 选项 3：退出程序
        print("已退出。")
        break
