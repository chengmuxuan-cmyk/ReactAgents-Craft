# ReAct Agent

一个基于 ReAct（Reasoning + Acting）模式实现的命令行 AI Agent。

它会在每一轮中执行：
1. `Thought`：分析当前任务
2. `Action`：调用工具（读文件、写文件、执行终端命令、预览 HTML、联网搜索、URL 抓取）
3. `Observation`：获取工具结果并继续推理
4. 最终输出 `final_answer`

## 功能特性

- 基于 XML 标签约束的 ReAct 推理流程
- 模型响应支持流式打印
- 支持多模型后端（OpenRouter / DeepSeek）
- 会话模式：任务完成后可“继续当前任务”或“开始新任务”
- 调试模式：`--debug`
- 文件读写已简化：仅在当前工作目录（默认 `temp`）内读写，覆盖写入
- 终端命令默认禁用，需 `--allow-command` 显式开启
- 支持联网搜索工具（DuckDuckGo，非 Google）
- 支持按 URL 抓取网页正文摘要（带基础 SSRF 防护）

## 项目结构（已拆分）

- `agent.py`：兼容入口（薄启动器）
- `react_agent/cli.py`：CLI 参数与交互主循环
- `react_agent/core.py`：ReAct 主流程（模型交互、action 解析）
- `react_agent/file_tools.py`：文件读写工具（工作区限制 + 多参数容错）
- `react_agent/command_tools.py`：命令执行工具（高危模式拦截 + 超时）
- `react_agent/web_tools.py`：联网搜索与 URL 抓取工具
- `react_agent/preview_tools.py`：HTML 预览工具
- `react_agent/tools.py`：兼容入口（保留）
- `react_agent/runtime.py`：运行时上下文（目录、策略、开关）
- `react_agent/policy.py`：安全策略加载与维护
- `prompt_template.py`：系统提示词模板
- `command_policy.json`：命令危险模式策略文件
- `.env.example`：环境变量示例
- `temp/`：默认工作目录（自动创建）

## 默认行为

- `project_directory` 参数可选
- 不传时默认使用项目下 `temp` 目录（自动创建）

```bash
uv run agent.py
```

如果要操作其他目录：

```bash
uv run agent.py E:\some_other_project
```

## 安装与配置

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，并填入：

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

## 启动示例

默认（OpenRouter + `./temp`）：

```bash
uv run agent.py
```

DeepSeek：

```bash
uv run agent.py --deepseek --model deepseek-chat
```

DeepSeek + 调试：

```bash
uv run agent.py --debug --deepseek --model deepseek-chat
```

允许终端命令（高风险，默认禁用）：

```bash
uv run agent.py --allow-command
uv run agent.py --debug --allow-command --deepseek --model deepseek-chat
```


## CLI 参数

- `project_directory`：可选，默认 `temp`
- `--deepseek` / `-d`：启用 DeepSeek
- `--model` / `-m`：指定模型
- `--debug`：开启调试打印
- `--allow-command`：允许执行终端命令（默认禁用）

## 文件读写行为

- `read_file(file_path)`：读取工作目录内文本文件
- `write_to_file(file_path, content, ...)`：覆盖写入；兼容模型把内容拆成多个参数
- 路径越界（不在工作目录内）会被拒绝

## 登录页写完后能不能直接看？

可以。让 Agent 调用：

```text
preview_html_file("E:/my_project/temp/login.html")
```

会自动打开默认浏览器。

## 示例任务

简单文件任务：

```text
帮我创建一个 hello.txt 文件，内容是 "Hello, World!"
```

代码任务：

```text
创建一个简单的 Python 计算器程序，支持加减乘除
```

## 复杂示例任务（可直接粘贴）

### 场景 1：完整登录页 + 可运行预览 + 说明文档

```text
在 temp 目录下创建一个可直接打开的登录页面（login.html + style.css + app.js），要求：
1) 响应式布局，移动端和桌面端都可用；
2) 表单包含邮箱、密码、记住我、显示/隐藏密码；
3) 前端校验（邮箱格式、密码长度>=8）；
4) 模拟异步登录请求和 loading 状态；
5) 登录成功和失败都有提示；
6) 写一个 README_login.md 说明交互逻辑；
7) 最后自动打开 login.html 让我预览。
```

### 场景 2：多文件 Python 小项目 + 测试 + 运行脚本

```text
在 temp 目录下创建一个“任务管理 CLI”项目，要求：
1) 使用 Python，按模块拆分（models.py、storage.py、cli.py）；
2) 支持任务增删改查、按状态过滤、导出 JSON；
3) 补充 6 个以上单元测试；
4) 生成 requirements.txt 和项目使用说明；
5) 自动执行测试并把结果总结给我。
```

### 场景 3：现有代码重构 + 回归验证

```text
读取 temp 目录下所有 Python 文件，做一次可运行的重构：
1) 提取重复逻辑；
2) 增加类型注解和必要注释；
3) 不改变对外行为；
4) 运行语法检查和测试；
5) 输出“改动清单 + 风险点 + 后续建议”。
```

### 场景 4：前端页面到可演示版本

```text
在 temp 目录下做一个“数据看板”单页应用：
1) 原生 HTML/CSS/JS；
2) 三个统计卡片 + 一个趋势图（可用纯 SVG/Canvas）；
3) 支持浅色/深色切换并记住用户选择；
4) 模拟接口延迟和失败重试；
5) 页面加载后自动打开给我看。
```

### 场景 5：互联网调研 + 定向爬取汇总

```text
帮我做“RAG 向量数据库选型”快速调研：
1) 先联网搜索 5~8 条近期资料（不要用 Google）；
2) 抓取其中 3 个你认为最有价值的 URL 正文；
3) 输出对比表：功能、部署方式、成本、社区活跃度、适用场景；
4) 最后给出一个“适合小团队 MVP”的推荐结论。
```

## 新增工具

- `web_search(query, max_results=5)`：使用 DuckDuckGo 进行互联网搜索（非 Google）
- `crawl_url(url, max_chars=4000, include_links=True)`：抓取用户提供 URL 的正文摘要与链接列表

说明：
1. `crawl_url` 仅允许 `http/https`
2. 默认拒绝 `localhost` 与内网/保留地址
3. 仅处理 `text/html` 与 `text/plain` 内容类型

## 命令安全策略

默认禁用终端命令执行；只有加 `--allow-command` 才可执行。

即使开启也会受限：
1. 高危关键字拦截（删除/格式化/下载执行等）
2. 默认拦截高危模式（删除/格式化/可疑下载执行等）
3. 执行目录限定在项目上下文目录（默认 `temp`）
4. 命令超时自动终止（20 秒）

你可以通过 `command_policy.json` 自定义：
- `dangerous_patterns`

### command_policy.json 示例

```json
{
  "dangerous_patterns": [
    " rm ",
    "del ",
    "rmdir ",
    "format ",
    "mkfs",
    "shutdown",
    "reboot",
    "powershell -enc",
    "curl ",
    "wget ",
    "invoke-webrequest"
  ]
}
```

调参建议：
1. 只维护 `dangerous_patterns` 即可
2. 改完后重新启动 `agent.py` 生效

## 常见问题

### 1) `uv run agent.py --debug --deepseek --model deepseek-chat` 报错

优先检查：
1. `.env` 是否存在且包含 `DEEPSEEK_API_KEY`
2. 当前终端是否在项目根目录（确保能加载 `.env`）
3. 模型名是否正确（推荐 `deepseek-chat`）

### 2) 缺少 API Key

- DeepSeek：`DEEPSEEK_API_KEY`
- OpenRouter：`OPENROUTER_API_KEY`

### 3) 登录页重复生成如何处理

当前 `write_to_file` 为覆盖写入。若你希望保留历史版本，建议在任务里明确要求“先备份再写入”。

## License

MIT


