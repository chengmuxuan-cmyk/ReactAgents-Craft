"""ReAct Agent 核心实现

实现 ReAct (Reasoning + Acting) 模式的核心逻辑。
这是整个智能体的"大脑"，负责：
1. 与 LLM API 交互（流式输出）
2. 解析模型的 Thought/Action/Final Answer
3. 执行工具并收集 Observation
4. 管理会话历史和上下文

ReAct 循环流程：
Thought（思考）→ Action（行动）→ Observation（观察）→ 循环直到 Final Answer

作者：CMD
创建时间：2026-03-30
"""

from __future__ import annotations

import ast
import inspect
import os
import platform
import re
import shlex
from string import Template
from typing import Any, Callable, List, Tuple

from dotenv import load_dotenv
from openai import OpenAI

from prompt_template import react_system_prompt_template
from react_agent import policy, runtime


class ReActAgent:
    """
    ReAct 智能体类
    
    核心工作机制：
    1. 接收用户输入
    2. 构建系统提示（包含工具列表、项目信息等）
    3. 请求模型生成响应（流式输出）
    4. 解析响应中的 XML 标签（<thought>, <action>, <final_answer>）
    5. 执行 Action 指定的工具
    6. 将 Observation 反馈给模型
    7. 循环直到模型输出 Final Answer
    
    Attributes:
        tools (dict): 可用工具字典 {工具名：函数}
        model (str): 使用的模型名称
        project_directory (str): 项目工作目录
        use_deepseek (bool): 是否使用 DeepSeek API
        debug (bool): 是否开启调试模式
        allow_command_execution (bool): 是否允许执行终端命令
        session_messages (List[dict] | None): 当前会话的消息历史
        client (OpenAI): OpenAI 兼容的 API 客户端
    """

    def __init__(
        self,
        tools: List[Callable],
        model: str,
        project_directory: str,
        use_deepseek: bool = False,
        debug: bool = False,
        allow_command_execution: bool = False,
    ):
        """
        初始化 ReAct 智能体
        
        Args:
            tools (List[Callable]): 工具函数列表，每个函数代表一个可被调用的能力
            model (str): 模型标识符，如 "openai/gpt-4o" 或 "deepseek-chat"
            project_directory (str): 项目工作目录的绝对路径
            use_deepseek (bool): 是否使用 DeepSeek API（默认 False 使用 OpenRouter）
            debug (bool): 是否开启调试模式（打印详细日志）
            allow_command_execution (bool): 是否允许执行终端命令（安全考虑，默认 False）
            
        Example:
            >>> # 使用 OpenRouter (GPT-4o)
            >>> agent = ReActAgent(tools=[...], model="openai/gpt-4o", project_directory="/path")
            >>> 
            >>> # 使用 DeepSeek
            >>> agent = ReActAgent(tools=[...], model="deepseek-chat", project_directory="/path", use_deepseek=True)
        """
        # 将工具列表转换为字典，方便通过函数名快速查找
        self.tools = {func.__name__: func for func in tools}
        
        # 保存配置参数
        self.model = model
        self.project_directory = project_directory
        self.use_deepseek = use_deepseek
        self.debug = debug
        self.allow_command_execution = allow_command_execution
        
        # 控制终端命令执行的会话级标志
        # 用户可以选择"本次会话始终允许"来避免重复确认
        self.always_allow_terminal_command = False
        
        # 会话消息历史，用于多轮对话
        # None 表示新会话，有值时表示保留的上下文
        self.session_messages: List[dict] | None = None

        # 根据配置初始化不同的 API 客户端
        if use_deepseek:
            # 使用 DeepSeek API
            print("🔵 正在使用 DeepSeek API...")
            self.client = OpenAI(
                base_url="https://api.deepseek.com",  # DeepSeek API 端点
                api_key=ReActAgent.get_deepseek_api_key(),  # 从环境变量获取密钥
            )
        else:
            # 使用 OpenRouter API（默认）
            print("🟢 正在使用 OpenRouter API...")
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",  # OpenRouter API 端点
                api_key=ReActAgent.get_api_key(),  # 从环境变量获取密钥
            )

    def _debug(self, message: str) -> None:
        """
        打印调试信息（仅在 debug=True 时输出）
        
        Args:
            message (str): 要打印的调试消息
            
        Note:
            这是一个内部辅助方法，避免在生产环境暴露敏感信息
        """
        if self.debug:
            print(f"\n[DEBUG] {message}")

    def reset_session(self) -> None:
        """
        重置会话历史
        
        调用后会清空 session_messages，下次 run() 时会开始全新的对话
        用于用户选择"开始新任务"时清除之前的上下文
        """
        self.session_messages = None

    def _add_command_to_whitelist(self, command: str) -> str:
        """将当前命令对应的可执行程序加入白名单。"""
        try:
            parts = shlex.split(command, posix=False)
        except ValueError as e:
            return f"白名单更新失败：命令解析错误（{str(e)}）"

        if not parts:
            return "白名单更新失败：命令为空"

        executable = os.path.basename(parts[0]).lower()
        policy.SAFE_COMMAND_WHITELIST.add(executable)
        self._debug(f"whitelist add executable={executable}")
        return f"已将可执行程序加入白名单：{executable}"

    def run(self, user_input: str, continue_session: bool = False) -> str:
        """
        运行智能体处理用户任务
        
        这是 ReAct 模式的核心循环，会持续执行以下步骤：
        1. 发送消息到 LLM API（流式输出）
        2. 解析模型的 Thought（思考过程）
        3. 检查是否有 Final Answer（最终答案）
        4. 解析并执行 Action（调用工具）
        5. 收集 Observation（执行结果）
        6. 将 Observation 反馈给模型
        7. 循环直到获得 Final Answer 或达到最大步数
        
        Args:
            user_input (str): 用户的任务描述或问题
            continue_session (bool): 是否继续之前的会话
                - True: 保留 session_messages 中的历史消息
                - False: 清空历史，开始新对话
                
        Returns:
            str: 智能体给出的最终答案
            
        Raises:
            RuntimeError: 当达到最大循环次数（30 步）仍未完成任务时抛出
            
        Security:
            - 终端命令执行前会询问用户（除非 always_allow_terminal_command=True）
            - 提供三种选择：仅本次允许/本次会话始终允许/取消
            
        Example:
            >>> agent = ReActAgent(...)
            >>> result = agent.run("帮我创建一个贪吃蛇游戏", continue_session=False)
        """
        # 构建消息历史
        if continue_session and self.session_messages:
            # 继续之前的会话：复用历史消息
            messages = self.session_messages
            # 添加新的用户消息
            messages.append({"role": "user", "content": f"<question>{user_input}</question>"})
        else:
            # 开始新会话：重新构建系统提示和初始消息
            messages = [
                {"role": "system", "content": self.render_system_prompt(react_system_prompt_template)},
                {"role": "user", "content": f"<question>{user_input}</question>"},
            ]

        # 设置最大循环次数，防止无限循环
        max_steps = 30
        step = 0

        # ReAct 主循环
        while True:
            step += 1
            # 安全检查：超过最大步数则终止
            if step > max_steps:
                raise RuntimeError(f"Reached max ReAct steps ({max_steps}).")

            # 调试信息：打印当前步数和消息数量
            self._debug(f"react_step={step}, message_count={len(messages)}")
            
            # 调用 LLM API 获取模型响应（流式输出）
            content = self.call_model(messages)

            # 解析 Thought（思考过程）
            # Thought 是模型的推理过程，帮助理解其决策逻辑
            thought_match = re.search(r"<thought>(.*?)</thought>", content, re.DOTALL)
            if thought_match:
                print(f"\n\n💭 Thought: {thought_match.group(1)}")

            # 检查 Final Answer（最终答案）
            # 如果模型输出了 Final Answer，表示任务完成
            final_match = re.search(r"<final_answer>(.*?)</final_answer>", content, re.DOTALL)
            if final_match:
                # 保存当前会话历史，供后续 continue_session 使用
                self.session_messages = messages
                return final_match.group(1)

            # 解析 Action（行动）
            # Action 指定了要调用的工具及其参数
            action_match = re.search(r"<action>(.*?)</action>", content, re.DOTALL)
            if not action_match:
                # 如果没有 Action 且没有 Final Answer，说明模型输出格式错误
                raise RuntimeError("模型未输出 <action>")

            raw_action = action_match.group(1)
            self._debug(f"raw_action={raw_action}")
            
            # 解析 Action 字符串为工具名和参数
            tool_name, args = self.parse_action(raw_action)
            self._debug(f"parsed_action tool={tool_name}, args={args}")
            print(f"\n\n🔧 Action: {tool_name}({', '.join(map(str, args))})")

            # 特殊处理：终端命令需要用户确认
            if tool_name == "run_terminal_command":
                # 检查是否允许执行终端命令
                if not self.allow_command_execution:
                    print("\n\n检测到当前未开启终端命令执行（--allow-command）。请选择：")
                    print("1) 仅本次任务临时开启")
                    print("2) 本次会话始终开启")
                    print("3) 继续保持禁用（本次不执行）")
                    policy_choice = input("请输入选项（1/2/3）：").strip()

                    if policy_choice in ("1", "2"):
                        self.allow_command_execution = True
                        runtime.COMMAND_EXECUTION_ENABLED = True
                        if policy_choice == "2":
                            self.always_allow_terminal_command = True
                        self._debug("terminal command policy enabled interactively")
                    else:
                        observation = "安全策略：终端命令执行已禁用。若确需执行，请使用 --allow-command 启动。"
                        self._debug("terminal command blocked by policy (allow_command_execution=False)")
                        print(f"\n\n🔍 Observation: {observation}")
                        messages.append({"role": "user", "content": f"<observation>{observation}</observation>"})
                        continue  # 跳过执行，直接进入下一轮循环

                # 询问用户如何处理（除非之前选择了"本次会话始终允许"）
                if not self.always_allow_terminal_command:
                    print("\n\n即将执行终端命令，请选择：")
                    print("1) 仅本次允许")
                    print("2) 本次会话始终允许")
                    print("3) 取消本次操作")
                    choice = input("请输入选项（1/2/3）：").strip()
                    
                    if choice == "2":
                        # 选项 2：设置会话级标志，后续命令不再询问
                        self.always_allow_terminal_command = True
                    if choice not in ("1", "2"):
                        # 选项 3：取消操作
                        print("\n\n操作已取消。")
                        self.session_messages = messages
                        return "操作被用户取消"

            # 检查工具是否存在
            if tool_name not in self.tools:
                observation = f"Tool not found: {tool_name}"
            else:
                # 执行工具函数并捕获结果
                try:
                    observation = self.tools[tool_name](*args)
                except Exception as e:
                    # 工具执行出错时，将错误信息作为 Observation
                    observation = f"Tool execution error: {str(e)}"

            # 调试信息：打印 Observation 预览（前 300 字符）
            self._debug(f"observation_preview={str(observation)[:300]}")
            print(f"\n\n🔍 Observation: {observation}")
            
            # 将 Observation 添加到消息历史，供模型下一轮参考
            messages.append({"role": "user", "content": f"<observation>{observation}</observation>"})

    def get_tool_list(self) -> str:
        """
        生成工具列表字符串
        
        遍历所有注册的工具，生成包含函数签名和文档字符串的描述文本。
        这些信息会提供给模型，让其了解可用的工具。
        
        Returns:
            str: 格式化的工具列表字符串，每行一个工具的描述
            
        Example Output:
            - read_file(file_path): 读取文件内容（UTF-8）。
            - write_to_file(file_path, content): 写入文件内容，支持冲突策略。
        """
        lines = []
        for func in self.tools.values():
            # 获取函数名、签名和文档字符串
            lines.append(f"- {func.__name__}{inspect.signature(func)}: {inspect.getdoc(func) or ''}")
        return "\n".join(lines)

    def render_system_prompt(self, system_prompt_template: str) -> str:
        """
        渲染系统提示模板
        
        系统提示是指导模型行为的关键指令。该方法将模板中的占位符
        替换为实际值，包括操作系统类型、工具列表、项目文件等。
        
        Args:
            system_prompt_template (str): 包含 ${variable} 占位符的模板字符串
            
        Returns:
            str: 渲染后的完整系统提示
            
        Template Variables:
            - operating_system: 当前操作系统名称（如 Windows, macOS, Linux）
            - tool_list: 可用工具的详细描述列表
            - file_list: 项目目录下所有文件的绝对路径列表
            
        Example:
            假设模板为："你在${operating_system}上，工具有：${tool_list}"
            渲染后："你在 Windows 上，工具有：- read_file..."
        """
        # 获取工具列表字符串
        tool_list = self.get_tool_list()
        
        # 构建项目文件列表，将所有文件路径拼接为逗号分隔的字符串
        file_list = ", ".join(
            os.path.abspath(os.path.join(self.project_directory, f))
            for f in os.listdir(self.project_directory)
        )
        
        # 使用 Python Template 引擎替换变量
        return Template(system_prompt_template).substitute(
            operating_system=self.get_operating_system_name(),
            tool_list=tool_list,
            file_list=file_list,
        )

    @staticmethod
    def get_api_key() -> str:
        """
        从环境变量中获取 OpenRouter API 密钥
        
        安全地加载 OpenRouter API 密钥，优先从 .env 文件读取。
        这是一种安全实践，避免将敏感信息硬编码到代码中。
        
        Returns:
            str: OpenRouter API 密钥
            
        Raises:
            ValueError: 如果未找到 OPENROUTER_API_KEY 环境变量
            
        Security Note:
            API 密钥应存储在 .env 文件中，格式为：
            OPENROUTER_API_KEY=your_api_key_here
            
        How to get:
            1. 访问 https://openrouter.ai/keys
            2. 注册并登录账号
            3. 创建 API Key
            4. 复制到 .env 文件
        """
        load_dotenv()  # 从 .env 文件加载环境变量
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("未找到 OPENROUTER_API_KEY 环境变量，请在 .env 文件中设置。")
        return api_key

    @staticmethod
    def get_deepseek_api_key() -> str:
        """
        从环境变量中获取 DeepSeek API 密钥
        
        安全地加载 DeepSeek API 密钥，优先从 .env 文件读取。
        
        Returns:
            str: DeepSeek API 密钥
            
        Raises:
            ValueError: 如果未找到 DEEPSEEK_API_KEY 环境变量
            
        Security Note:
            API 密钥应存储在 .env 文件中，格式为：
            DEEPSEEK_API_KEY=your_deepseek_api_key_here
            
        How to get:
            1. 访问 https://platform.deepseek.com/
            2. 注册并登录账号
            3. 在控制台创建 API Key
            4. 复制到 .env 文件
        """
        load_dotenv()  # 从 .env 文件加载环境变量
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("未找到 DEEPSEEK_API_KEY 环境变量，请在 .env 文件中设置。\n获取地址：https://platform.deepseek.com/")
        return api_key

    def call_model(self, messages: List[dict]) -> str:
        """
        调用 LLM API 获取模型响应（流式输出）
        
        封装与 OpenAI 兼容 API 的交互逻辑，发送对话历史并接收模型回复。
        使用流式输出（stream=True）可以实时显示模型的生成过程。
        
        Args:
            messages (List[dict]): 对话消息列表，每条消息包含 role 和 content
            
        Returns:
            str: 模型响应的完整文本内容
            
        Request Format:
            {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "..."},
                    {"role": "user", "content": "..."},
                    ...
                ],
                "stream": true
            }
            
        Streaming:
            流式输出通过逐个打印 chunks 实现，可以提供更好的用户体验
        """
        # 调试信息：打印请求详情
        self._debug(
            f"request model={self.model}, stream=True, "
            f"last_role={messages[-1]['role'] if messages else 'none'}"
        )
        if self.debug and messages:
            self._debug(f"last_message_preview={messages[-1]['content'][:300]}")

        print("\n\n正在请求模型（流式输出）...\n")
        
        # 发起流式请求
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,  # 启用流式输出
        )

        # 收集所有流式片段
        chunks: List[str] = []
        for event in stream:
            if not event.choices:
                continue
            # 提取当前片段的文本内容
            piece = event.choices[0].delta.content or ""
            if piece:
                # 实时打印片段（无换行，保持连续输出）
                print(piece, end="", flush=True)
                chunks.append(piece)

        # 打印换行符，美化输出
        print()
        
        # 将所有片段拼接成完整的响应
        content = "".join(chunks)
        self._debug(f"response_chars={len(content)}")
        
        # 将模型响应添加到消息历史
        messages.append({"role": "assistant", "content": content})
        return content

    def parse_action(self, code_str: str) -> Tuple[str, List[Any]]:
        """
        解析模型输出的行动字符串
        
        将形如 function_name(arg1, arg2, ...) 的字符串解析为
        函数名和参数列表。支持复杂的参数类型，包括多行字符串。
        
        Args:
            code_str (str): 行动字符串，例如 'write_to_file("test.py", "content")'
            
        Returns:
            Tuple[str, List[Any]]: (函数名，参数列表)
            
        Raises:
            ValueError: 如果字符串不符合函数调用语法
            
        Parsing Features:
            - 支持字符串参数（单引号/双引号）
            - 支持多行字符串
            - 正确处理转义字符
            - 支持嵌套括号
            - 自动推断参数类型（字符串、数字、布尔值等）
            
        Example:
            >>> parse_action('read_file("hello.txt")')
            ('read_file', ['hello.txt'])
            >>> parse_action('write_to_file("test.py", "print(123)")')
            ('write_to_file', ['test.py', 'print(123)'])
        """
        # 使用正则表达式匹配函数名和参数字符串
        match = re.match(r"(\w+)\((.*)\)", code_str, re.DOTALL)
        if not match:
            raise ValueError("Invalid function call syntax")

        func_name = match.group(1)
        args_str = match.group(2).strip()

        # 手动解析参数列表，特别处理包含多行内容的字符串
        args: List[Any] = []
        current_arg = ""
        in_string = False  # 标记是否在字符串内部
        string_char = None  # 记录字符串的引号类型（' 或 "）
        paren_depth = 0  # 括号嵌套深度
        i = 0

        # 逐字符扫描参数字符串
        while i < len(args_str):
            char = args_str[i]
            if not in_string:
                # 不在字符串内的情况
                if char in ['"', "'"]:
                    # 遇到引号，进入字符串模式
                    in_string = True
                    string_char = char
                    current_arg += char
                elif char == "(":
                    # 左括号，增加嵌套深度
                    paren_depth += 1
                    current_arg += char
                elif char == ")":
                    # 右括号，减少嵌套深度
                    paren_depth -= 1
                    current_arg += char
                elif char == "," and paren_depth == 0:
                    # 遇到顶层逗号（不在嵌套括号内），表示一个参数结束
                    args.append(self._parse_single_arg(current_arg.strip()))
                    current_arg = ""
                else:
                    current_arg += char
            else:
                # 在字符串内的情况
                current_arg += char
                # 检查是否遇到匹配的结束引号（且不是转义的）
                if char == string_char and (i == 0 or args_str[i - 1] != "\\"):
                    in_string = False
                    string_char = None
            i += 1

        # 添加最后一个参数（如果有）
        if current_arg.strip():
            args.append(self._parse_single_arg(current_arg.strip()))

        return func_name, args

    def _parse_single_arg(self, arg_str: str) -> Any:
        """
        解析单个参数值
        
        尝试将参数解析为合适的 Python 类型：
        - 字符串字面量 -> 去除引号并处理转义
        - 数字/布尔值/None -> 使用 ast.literal_eval
        - 其他 -> 返回原始字符串
        
        Args:
            arg_str (str): 参数的字符串表示
            
        Returns:
            Any: 解析后的参数值（可能是 str, int, float, bool, None 等）
            
        Examples:
            >>> _parse_single_arg('"hello"')
            'hello'
            >>> _parse_single_arg('42')
            42
            >>> _parse_single_arg('True')
            True
            >>> _parse_single_arg('some_text')
            'some_text'
        """
        arg_str = arg_str.strip()
        
        # 如果是字符串字面量（被引号包围）
        if (arg_str.startswith('"') and arg_str.endswith('"')) or (
            arg_str.startswith("'") and arg_str.endswith("'")
        ):
            # 移除外层引号并处理转义字符
            inner_str = arg_str[1:-1]
            # 仅处理引号与反斜杠本身，避免把 Windows 路径中的 \t/\n 等误转义
            inner_str = inner_str.replace('\\"', '"').replace("\\'", "'")
            inner_str = inner_str.replace("\\\\", "\\")
            return inner_str
        
        # 尝试使用 ast.literal_eval 解析其他类型（数字、布尔值、None、列表、字典等）
        try:
            return ast.literal_eval(arg_str)
        except (SyntaxError, ValueError):
            # 如果解析失败，返回原始字符串
            return arg_str

    def get_operating_system_name(self) -> str:
        """
        获取当前操作系统的友好名称
        
        将 Python 的 platform.system() 返回值映射为更常用的名称。
        
        Returns:
            str: 操作系统名称（macOS, Windows, Linux 或 Unknown）
            
        Mapping:
            Darwin -> macOS
            Windows -> Windows
            Linux -> Linux
        """
        os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
        return os_map.get(platform.system(), "Unknown")
