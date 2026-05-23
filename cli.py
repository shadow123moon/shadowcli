"""交互式终端入口 —— PaiCLI Python 重写版。

用法::

    python cli.py

启动后进入 `>` 提示符,输入自然语言任务,Agent 规划 + 执行,结果打印回终端,
回到提示符等待下一条。Ctrl+C / Ctrl+D / `/quit` 退出。

—— HITL 接入点 ——
本 CLI **默认不接** HITL 审批。想接的话改 ``build_registry()`` 即可。
但注意:agent.py 内部用 ``registry.get(name).execute(args)``,会绕过
HitlToolRegistry.execute,审批不会弹。要么改 agent 调用风格,要么
让 HitlToolRegistry.get 返回带审批的包装。这是留给你的练习。
"""
from __future__ import annotations

import sys
import traceback

from dotenv import load_dotenv

from agent import PlanExecuteAgent
from planning import Planner
from tool_registry import ToolRegistry
from tools import ExecuteCommandTool, ListDirTool, ReadFileTool, WriteFileTool

BANNER = """
==================================================
  PaiCLI Python 重写版 — 交互终端
==================================================
输入自然语言任务,回车执行。
/help  查看命令    /quit  退出
"""

HELP = """
命令:
  /help    显示本帮助
  /tools   列出已注册的工具
  /quit    退出 (也可 Ctrl+C / Ctrl+D)

示例任务:
  读取 cli.py 文件
  写入文件 hello.txt 内容 'hi'
  列出当前目录
  创建一个 Python 项目叫 demo,包含 main.py 输出 Hello World
"""


def build_registry() -> ToolRegistry:
    """构造工具注册中心。

    想接 HITL? 在 return 前加:

        from hitl_pythonic import with_hitl, TerminalHitlHandler
        registry = with_hitl(registry, TerminalHitlHandler(enabled=True))

    然后看看为什么审批不弹 —— 提示:agent.py 的调用风格。
    """
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(ExecuteCommandTool())
    return registry


def list_tools(registry: ToolRegistry) -> str:
    defs = registry.get_all_definitions()
    if not defs:
        return "(无已注册工具)"
    lines = ["已注册工具:"]
    for d in defs:
        fn = d["function"]
        lines.append(f"  - {fn['name']}: {fn['description']}")
    return "\n".join(lines)


def run_once(agent: PlanExecuteAgent, user_input: str) -> None:
    try:
        result = agent.run(user_input)
    except Exception as e:
        print(f"\n[ERROR] 执行失败: {e}")
        traceback.print_exc()
        return
    print("\n" + "-" * 50)
    print("最终结果:")
    print(result)
    print("-" * 50)


def repl() -> int:
    load_dotenv()
    registry = build_registry()
    planner = Planner()
    agent = PlanExecuteAgent(planner, registry)

    print(BANNER)

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0

        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            print("再见。")
            return 0
        if line == "/help":
            print(HELP)
            continue
        if line == "/tools":
            print(list_tools(registry))
            continue
        if line.startswith("/"):
            print(f"未知命令: {line}  (输入 /help 查看)")
            continue

        run_once(agent, line)


if __name__ == "__main__":
    sys.exit(repl())
