# main.py
import os

from dotenv import load_dotenv

from tools import ReadFileTool, WriteFileTool, ListDirTool, ExecuteCommandTool
from tool_registry import ToolRegistry
from planning import Planner
from agent import PlanExecuteAgent

def main():
    # 初始化工具注册中心
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(ExecuteCommandTool())
    load_dotenv()
    # 初始化规划器（使用环境变量配置）
    planner = Planner()

    # 创建 Agent
    agent = PlanExecuteAgent(planner, registry)

    # 示例任务
    print("=== 示例：创建一个项目结构 ===")
    result = agent.run("创建一个 Python 项目叫 demo，包含 main.py 和 README.md，"
                       "其中 main.py 输出 'Hello World'，然后列出项目目录")
    print("最终结果:\n", result)

if __name__ == "__main__":
    main()
