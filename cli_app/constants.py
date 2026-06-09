from pathlib import Path

BANNER = (
    "PaiCLI\n"
    "ctrl+c 中断 · ctrl+d 退出 · / 命令 · /new 新对话 · /resume 历史对话\n"
    "首条消息会创建新对话"
)

HELP = (
    "/help       显示帮助\n"
    "/tools      列出工具\n"
    "/skills     列出 skills\n"
    "/plan       计划执行任务\n"
    "/memory     显示长期记忆\n"
    "/remember   写入长期记忆\n"
    "/new        开启新对话\n"
    "/resume     恢复历史对话\n"
    "/tree       选择会话节点\n"
    "/jump       跳转到消息节点\n"
    "/compact    压缩当前分支\n"
    "/quit       退出"
)

PLAN_COMMAND = "/plan"
SKILLS_COMMAND = "/skills"
REMEMBER_COMMAND = "/remember"
MEMORY_COMMAND = "/memory"
NEW_COMMAND = "/new"
RESUME_COMMAND = "/resume"
TREE_COMMAND = "/tree"
JUMP_COMMAND = "/jump"
COMPACT_COMMAND = "/compact"
DEFAULT_LONG_TERM_PATH = Path("agent_memory") / "long_term.md"
