"""向后兼容的 CLI 入口点

为了保持与旧版本的兼容性而存在。
该文件本身不包含实际逻辑，只是从 react_agent.cli 模块导入并运行 main() 函数。

设计目的：
1. 保持旧的调用方式仍然有效（uv run agent.py）
2. 实际的代码已经重构到 react_agent/ 包中
3. 这是一个包装层（wrapper），确保平滑过渡

使用方法:
    uv run agent.py [OPTIONS] [PROJECT_DIRECTORY]

完整参数说明请运行：
    uv run agent.py --help

作者：CMD
创建时间：2026-03-30
"""

# 从 react_agent 包中导入 CLI 主函数
# 这样做的目的是将核心代码组织得更加模块化
from react_agent.cli import main


if __name__ == "__main__":
    # 当直接运行此脚本时（如：uv run agent.py），调用 main() 函数
    # main() 函数会处理所有命令行参数并启动交互式会话
    main()
