from memory import DEFAULT_LONG_TERM_PATH

BANNER = (
    "ShadowCLI\n"
    "ctrl+c 中断 · ctrl+d 退出 · / 命令 · /new 新对话 · /resume 历史对话\n"
    "首条消息会创建新对话"
)

HELP = (
    "/help       显示帮助\n"
    "/tools      列出工具\n"
    "/plugins    列出插件\n"
    "/plugin     启用或禁用插件\n"
    "/skills     列出 skills\n"
    "/skill      使用指定 skill 执行任务，任务可省略\n"
    "/plan       计划执行任务\n"
    "/memory     显示长期记忆\n"
    "/remember   写入长期记忆\n"
    "/new        开启新对话\n"
    "/resume     恢复历史对话\n"
    "/tree       选择会话节点\n"
    "/jump       跳转到消息节点\n"
    "/compact    压缩当前分支\n"
    "/cancel     取消当前正在运行的任务\n"
    "/quit       退出"
)

PLAN_COMMAND = "/plan"
PLUGIN_COMMAND = "/plugin"
PLUGINS_COMMAND = "/plugins"
SKILL_COMMAND = "/skill"
SKILLS_COMMAND = "/skills"
REMEMBER_COMMAND = "/remember"
MEMORY_COMMAND = "/memory"
NEW_COMMAND = "/new"
RESUME_COMMAND = "/resume"
TREE_COMMAND = "/tree"
JUMP_COMMAND = "/jump"
COMPACT_COMMAND = "/compact"
