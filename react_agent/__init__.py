"""ReAct Agent 包

基于 ReAct (Reasoning + Acting) 模式的 AI 智能体实现。
支持调用多种 LLM API（OpenRouter、DeepSeek）完成复杂任务。

核心特性：
- ReAct 循环：Thought → Action → Observation
- 多 API 支持：OpenRouter (GPT-4o/Claude)、DeepSeek
- 安全策略：终端命令白名单/黑名单机制
- 版本控制：文件写入冲突时的版本管理
- 会话管理：支持多轮对话和上下文保持

作者：CMD
创建时间：2026-03-30
"""
