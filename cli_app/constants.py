from pathlib import Path

BANNER = """
==================================================
  PaiCLI Python 重写版 — 交互终端
==================================================
输入自然语言任务,回车执行。
/help  查看命令    /plan  单 Agent 计划执行    /tree  会话树    /quit  退出
"""

HELP = """
命令:
  /help    显示本帮助
  /tools   列出已注册的工具
  /plan    单 Agent 计划执行,用法: /plan <任务>
  /memory  显示当前长期记忆状态
  /remember <事实>  写入一条长期记忆
  /tree    显示最近会话节点
  /jump <entry_id>  跳转到旧消息
  /quit    退出 (也可 Ctrl+C / Ctrl+D)

示例任务:
  读取 cli_app/runner.py 文件
  写入文件 hello.txt 内容 'hi'
  列出当前目录
  /plan 创建一个 Python 项目叫 demo,包含 main.py 输出 Hello World
  你好
"""

PLAN_COMMAND = "/plan"
REMEMBER_COMMAND = "/remember"
MEMORY_COMMAND = "/memory"
TREE_COMMAND = "/tree"
JUMP_COMMAND = "/jump"
DEFAULT_LONG_TERM_PATH = Path("agent_memory") / "long_term.md"
