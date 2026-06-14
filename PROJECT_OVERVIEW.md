# pythonProject4 项目地图

这份文档只记录当前 Python 项目的运行入口、模块职责和真实执行链路。`CLAUDE.md` 记录项目目标、协作原则和测试落位约定。

## 入口

唯一推荐入口：

```bash
python -m cli_app
```

交互命令：

```text
普通输入            默认走 ReactAgent
/plan <任务>        走 ReactAgent 单 Agent 计划执行
/remember <事实>    写入长期记忆，默认归入 project
/remember <类型> <事实> 写入指定长期记忆类型：user/project/feedback/reference
/memory             查看长期记忆状态
/tree               查看最近会话节点
/jump <entry_id>    跳转到旧消息
/tools              查看已注册工具
/plugins            查看可用插件
/plugin enable <name>
/plugin disable <name>
/skills             列出可用 skills
/skill <name> [任务] 使用指定 skill 执行任务，任务可省略
/quit               退出
```

`main.py`、`core.py`、`cli.py` 不再作为入口。后续新增运行期资源优先接到 `app_runtime/`，交互命令接到 `cli_app/`，工具执行期扩展接 `ToolRuntime`，workflow/skill 类上下文能力接 `skills/`。

## 执行链路

普通对话：

```text
cli_app
  -> AppRuntime 持有 ToolRuntime / HookManager / AppStateStore / SessionStore / LongTermMemory / SessionRuntime / SkillManager / EventBus
  -> HookManager 安装 freshness guard 工具 hook，并桥接到 ToolRuntime
  -> AppStateStore 统一项目级运行期状态入口
  -> SessionRuntime 负责压缩、重载 agent conversation、重建 RuntimeContextBuilder
  -> SkillManager 持有 PluginManager / SkillRegistry
  -> AppRuntime.prepare_agent_run() 自动压缩并重建 RuntimeContextBuilder
  -> ReactAgent
  -> AgentLoop
  -> ToolRuntime.execute(name, args)
  -> ToolRegistry.execute(name, args)
  -> Tool.execute(args)
```

计划模式：

```text
cli_app /plan
  -> ReactAgent
  -> 单个 ReAct 循环生成计划并执行
  -> ToolRuntime.execute(name, args)
  -> ToolRegistry.execute(name, args)
```

Skill 初始化：

```text
cli_app 启动
  -> AppRuntime.create()
  -> SkillManager.create()
  -> PluginManager.skill_roots()
  -> SkillRegistry(extra_roots=...)
```

Skill 命令：

```text
cli_app /skill <name> [任务]
  -> AppRuntime.build_skill_context(name, base_context, arguments)
  -> SkillManager.build_context(...)
  -> SkillRegistry.load(name)
  -> SkillContextBuilder 注入 skill body
  -> ReactAgent
```

运行前上下文准备：

```text
ReplRouter
  -> AppRuntime.prepare_agent_run(session, agent, context_builder)
  -> SessionRuntime.prepare_agent_run(...)
  -> compact_session(force=False)
  -> 如发生压缩，重载 agent conversation messages
  -> 返回新的 RuntimeContextBuilder
```

手动压缩：

```text
cli_app /compact
  -> AppRuntime.compact_agent_session(session, agent)
  -> SessionRuntime.compact_agent_session(...)
  -> compact_session(force=True)
  -> 如发生压缩，重载 agent conversation messages
  -> 返回新的 RuntimeContextBuilder
```

自动 skill 选择：

```text
普通输入 + SHADOWCLI_AUTO_SKILLS=1
  -> AppRuntime.select_auto_skill(...)
  -> SkillSelector 只看 project/enabled plugin/external/global skill metadata
     (name/source/description/when_to_use/argument_hint)
  -> 选择 0/1 个 skill
  -> 命中时 AppRuntime.build_skill_context_for_definition(...)
  -> SkillContextBuilder 注入 skill body
  -> ReactAgent 执行原始输入
```

长期记忆工具：

```text
ReactAgent 执行中
  -> 调用 propose_memory(type, text, reason)
  -> ProposeMemoryTool 校验类型/空文本/重复事实
  -> 终端询问用户是否保存
  -> 用户确认后才调用 TextLongTermMemory.remember(...)
```

插件 skill 贡献：

```text
plugins/<id>/.codex-plugin/plugin.json
SHADOWCLI_PLUGIN_ROOTS=<external plugin root>
  -> PluginManager 校验 manifest
     - name 必须是 kebab-case
     - skills path 必须相对插件根并以 ./ 开头
  -> .agents/plugins.json 决定 enabled / disabled
  -> SkillRoot(source="plugin:<id>", path=...)
  -> SkillRegistry 读取 SKILL.md / skill.md
```

插件启用/禁用：

```text
cli_app /plugin enable|disable <name>
  -> AppRuntime.set_plugin_enabled(name, enabled)
  -> AppStateStore.set_plugin_enabled(...)
  -> PluginStateStore 写入 .agents/plugins.json
  -> AppRuntime.refresh_skills()
  -> ReplRouter 更新当前 skill_registry 引用
```

关键约束：Agent 不直接 `tool.execute(...)`，统一走 `registry.execute(...)`。Agent 只产生事件，`cli_app/runner.py` 把事件路由给 `ui/terminal.py` 渲染，并把消息事实写入 session。

## 模块职责

| 模块 | 职责 |
|---|---|
| `app_runtime/` | 运行期资源组装层，AppRuntime 持有 ToolRuntime、HookManager、AppStateStore、SessionStore、LongTermMemory、SessionRuntime、SkillManager 和 EventBus；HookManager 负责默认工具 hooks 的安装与桥接；AppStateStore 统一项目级运行期状态入口；SessionRuntime 负责运行前/手动上下文压缩、agent conversation 重载和 RuntimeContextBuilder 重建；SkillManager 组合 PluginManager/SkillRegistry，并负责插件启用/禁用后的 skill 刷新、自动 skill 选择和 skill context 组装 |
| `cli_app/` | 交互入口、命令路由、日志初始化、Agent 事件路由 |
| `agent/` | 默认 ReAct 对话入口、共享 AgentLoop、预算和主线 prompt；只产生事件，不直接打印 |
| `ui/` | 用户可见终端输出和输入 |
| `sessions/` | 按项目目录隔离的 append-only 会话树、分支跳转、branch summary 和 compaction |
| `memory/` | 结构化长期记忆存储、`propose_memory` 工具和长期记忆写入规则 |
| `plugin_runtime/` | 读取项目插件和外部插件 root 的 manifest，管理 `.agents/plugins.json` 启用状态，当前只加载 enabled 插件的 skill contributions |
| `skills/` | 发现、加载并格式化 `SKILL.md` / `skill.md` 上下文 |
| `tooling/` | 工具基类、具体工具、工具注册中心、ToolRuntime；默认 hook 安装入口在 AppRuntime/HookManager |
| `llm/` | OpenAI 兼容 Chat API 客户端和消息模型 |

## 记忆

Session 和长期记忆分层：

```text
Session        = 完整会话树，可恢复当前 branch，按项目目录隔离
TextLongTermMemory = 用户确认后保存的结构化 markdown 长期记忆
RuntimeContextBuilder = 运行时上下文视图，从当前 branch 摘要和长期记忆现算
```

代码边界：

```text
sessions/ = messages.jsonl、leaf、branch_summary、compaction
memory/   = MEMORY.md、user/project/feedback/reference、写入工具和去重/search policy
```

会话存储默认目录：

```text
~/.shadowcli/sessions/<project_key>/
  project.json
  memory/
    MEMORY.md
    user.md
    project.md
    feedback.md
    reference.md
  conversations/<session_id>/
    meta.json
    messages.jsonl
```

当前有三层概念：

```text
messages.jsonl = session_header / message / leaf / branch_summary / compaction 事件流
memory/        = 结构化长期记忆目录，MEMORY.md 为索引，分类文件保存 bullet 事实
```

Session 只追加，不改旧 entry。`leaf` 表示当前分支位置；`branch_summary` 是树上的节点，不是 sidecar 文件。System prompt 和 RuntimeContextBuilder 生成的 system context 都是运行时构造的临时视图，不作为普通消息写入 `messages.jsonl`。普通输入和 `/plan` 都通过同一个 `ReactAgent` 执行，`/plan` 只是单 Agent 的计划执行提示。

分支跳转入口保持三层边界：

```text
ui.ask_branch_navigation_choice()  -> 只询问用户 1/2/3
cli_app.navigate_session_branch()  -> 调 plan_navigation，再按选择路由
SessionManager                     -> branch_to 或 branch_to_with_summary
```

`/tree` 显示最近 20 个节点和当前 leaf；`/jump <entry_id>` 使用上面的跳转入口。选择“总结当前分支后跳转”时，由 `sessions.summarizer.generate_branch_summary()` 生成摘要，再追加 `branch_summary` 节点。

长期记忆当前主要来源：

```text
/remember <事实>
/remember user <事实>
/remember project <事实>
/remember feedback <事实>
/remember reference <事实>
propose_memory 工具候选 + 用户确认
```

普通对话只写入 session，不再维护短期 memory。长期记忆不自动从模型回答、branch summary 或 compaction summary 里抽取事实，避免把不确定回答、临时日志和推理过程污染成长记忆。旧 `long_term.md` 格式已放弃，不再读取、导入或写入；新路径必须是结构化 `memory/` 目录。`propose_memory` 工具默认可见，但它只能提出候选，不能绕过确认直接写入。

## 运行时 Hooks

默认工具 hook 只有 freshness guard：`edit` / `write` 修改已存在文件前，必须先通过 `read` 读取过该文件；如果文件在读取后被进程外修改，本次修改会被软拒绝并要求重新读取。

执行链路：

```text
ToolRuntime.execute(name, args)
  -> HookManager bridge
  -> freshness guard 检查 read-before-edit/write
  -> ToolRegistry.execute(name, args)
```

HITL / AI reviewer 审批层已从主路径移除。后续如果重新引入审批，应作为插件/runtime contribution 经 `AppRuntime` 统一安装，而不是恢复独立包装层或散落到 runner。

## 工具

当前核心工具参考 Pi Coding Agent 的极简工具面：

```text
read   读取文件
write  创建或覆盖文件
edit   精准替换文件中的文本
bash   执行 Shell 命令
ls     列目录
grep   搜索文本
find   查找文件
```

旧版 alias（`read_file` / `write_file` / `list_dir` / `execute_command`）已移除，避免向模型暴露重复工具定义。

## 日志

用户可见内容、开发日志和会话事实分开处理：

```text
用户可见内容 -> ui/terminal.py
开发调试信息 -> logging / SHADOWCLI_DEBUG_LOG
会话事实     -> sessions/.../messages.jsonl
```

普通终端日志默认是 WARNING，细节日志按需写 debug 文件。

环境变量：

```text
SHADOWCLI_LOG_LEVEL=WARNING
SHADOWCLI_DEBUG_LOG=1
SHADOWCLI_COMMAND_TIMEOUT_SECONDS=120
SHADOWCLI_AUTO_SKILLS=1
```

`/plan` 当前不再创建旧的 `logs/plans/` 计划日志；它走普通 `ReactAgent` 工具循环和全局 debug 日志。

工具日志应回答“做了什么”：

```text
read  看了哪个文件
write 写了哪个文件
bash  执行了什么命令
```

## 配置和测试

LLM 对话模型：

```text
OPENAI_API_KEY
API_URL
MODEL
```

依赖安装：

```bash
pip install -r requirements.txt
```

本地常用环境：

```bash
conda run -n lc python -m cli_app
conda run -n lc python -m unittest discover -s tests -v
```

测试文件存放约定：

```text
tests/test_*.py        自动化单元/集成测试，参与 unittest discover
debug/artifacts/       测试输出、截图、临时压缩包等产物
```

根目录只保留项目级入口、配置和总览文档；新增测试、报告、截图不要直接放根目录。

## 当前状态

| 能力 | 状态 |
|---|---|
| CLI 入口 | 已收敛到 `cli_app/` |
| 默认 React 对话 | 已接入 |
| `/plan` 单 Agent | 已接入 |
| 工具调用 | 统一走 `ToolRegistry.execute()` |
| 运行时 hooks | 默认只保留 freshness guard；HITL / AI reviewer 审批层已移除 |
| Session | 已接入，实时记录会话树、分支摘要和压缩节点 |
| 长期记忆 | 已接入，代码包为 `memory/`，数据写入项目级 `memory/` 结构化目录 |
| 长期记忆工具 | 已接入，`propose_memory` 允许 Agent 执行中提出候选，经类型/重复校验和用户确认后才写入 |
| Skills | 命令化已接入；默认扫描项目、外部/env、全局 skill roots，插件 skills 必须经 `.codex-plugin/plugin.json` manifest 声明；`SHADOWCLI_AUTO_SKILLS=1` 可开启默认关闭的 0/1 自动 skill 选择，候选含 project / enabled plugin / external / global，并使用 `when_to_use` metadata 辅助判断 |
| Skill compatibility | 已支持 `SKILL.md` / `skill.md`、UTF-8 BOM、折叠 frontmatter description、坏 skill 诊断跳过，以及无参数 `/skill <name>` |
| Plugin format | 已兼容 Codex 风格 `.codex-plugin/plugin.json`、kebab-case `name`、以 `./` 开头的 manifest path、`skills` 字符串/列表/对象声明，以及 `SHADOWCLI_PLUGIN_ROOTS` 外部插件 root |
| Plugin state | 已接入；插件默认禁用，`/plugins` 可查看，`/plugin enable/disable` 经 AppStateStore 写入 `.agents/plugins.json`，enabled 插件 skills 才会进入 `/skills` 和自动 skill 候选 |
| AppRuntime/EventBus | 已接入薄层；runner 通过 AppRuntime 统一组装 tool/hook/state/session/memory/skill/event 资源，默认工具 hooks 经 HookManager 安装，插件状态经 AppStateStore 读写，运行前自动压缩和手动 `/compact` 经 SessionRuntime，插件启用/禁用、自动 skill 选择和显式/自动 skill 的 context 组装经 SkillManager，EventBus 先作为运行期事件入口 |
| 项目检索 | 使用 `ls` / `grep` / `find` / `read`，不再维护 RAG 索引 |
| Plan 日志 | 旧 `logs/plans/` 专用日志已移出主路径 |
| 测试 | 主线 import / ToolRuntime / freshness guard / session 树测试可单独验证 |

## 待清理

- `agent/execute.py` 看起来像旧执行器残留，后续可以确认是否删除。
- `tooling/file_tools.py` 后续如果继续膨胀，可以再拆成 file/edit/search 三类。
