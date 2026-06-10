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
/remember <事实>    写入长期记忆
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

`main.py`、`core.py`、`cli.py` 不再作为入口。后续新增能力优先接到 `cli_app/` 的命令路由；工具执行期扩展接 `ToolRuntime`，workflow/skill 类上下文能力接 `skills/`。

## 执行链路

普通对话：

```text
cli_app
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
  -> PluginManager.skill_roots()
  -> SkillRegistry(extra_roots=...)
```

Skill 命令：

```text
cli_app /skill <name> [任务]
  -> SkillRegistry.load(name)
  -> SkillContextBuilder
  -> ReactAgent
```

自动 skill 选择：

```text
普通输入 + PAICLI_AUTO_SKILLS=1
  -> SkillSelector 只看 project/enabled plugin skill metadata
  -> 选择 0/1 个 skill
  -> 命中时 SkillContextBuilder 注入 skill body
  -> ReactAgent 执行原始输入
```

插件 skill 贡献：

```text
plugins/<id>/.codex-plugin/plugin.json
PAICLI_PLUGIN_ROOTS=<external plugin root>
  -> PluginManager 校验 manifest
     - name 必须是 kebab-case
     - skills path 必须相对插件根并以 ./ 开头
  -> .agents/plugins.json 决定 enabled / disabled
  -> SkillRoot(source="plugin:<id>", path=...)
  -> SkillRegistry 读取 SKILL.md / skill.md
```

关键约束：Agent 不直接 `tool.execute(...)`，统一走 `registry.execute(...)`。Agent 只产生事件，`cli_app/runner.py` 把事件路由给 `ui/terminal.py` 渲染，并把消息事实写入 session。

## 模块职责

| 模块 | 职责 |
|---|---|
| `cli_app/` | 交互入口、命令路由、日志初始化、Agent 事件路由 |
| `agent/` | 默认 ReAct 对话入口、共享 AgentLoop、预算和主线 prompt；只产生事件，不直接打印 |
| `ui/` | 用户可见终端输出和输入 |
| `sessions/` | 按项目目录隔离的 append-only 会话树，以及 markdown 长期事实清单 |
| `plugin_runtime/` | 读取项目插件和外部插件 root 的 manifest，管理 `.agents/plugins.json` 启用状态，当前只加载 enabled 插件的 skill contributions |
| `skills/` | 发现、加载并格式化 `SKILL.md` / `skill.md` 上下文 |
| `tooling/` | 工具基类、具体工具、工具注册中心 |
| `extensions/tool_runtime.py` | 工具运行时、before_execute hook、HITL/Reviewer 接入点 |
| `extensions/approval_policy.py` | 工具风险判断 |
| `llm/` | OpenAI 兼容 Chat API 客户端和消息模型 |

## 记忆

Session 和长期记忆分层：

```text
Session        = 完整会话树，可恢复当前 branch，按项目目录隔离
TextLongTermMemory = 用户通过 /remember 主动保存的 markdown bullet 事实清单
RuntimeContextBuilder = 运行时上下文视图，从当前 branch 摘要和 long_term 现算
```

会话存储默认目录：

```text
~/.pai_cli/sessions/<project_key>/
  project.json
  long_term.md
  conversations/<session_id>/
    meta.json
    messages.jsonl
```

当前有三层概念：

```text
messages.jsonl = session_header / message / leaf / branch_summary / compaction 事件流
long_term.md   = 项目级长期事实，/remember 追加 "- 事实"
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
```

普通对话只写入 session，不再维护短期 memory。长期记忆不自动从模型回答里抽取事实，避免把不确定回答、临时日志和推理过程污染成长记忆。

## HITL

HITL 已经接到 `ToolRuntime`，不再有独立的 `HitlToolRegistry` 包装层。

启用方式：

```powershell
$env:PAICLI_HITL="1"
python -m cli_app
```

执行链路：

```text
ToolRuntime.execute(name, args)
  -> 根据工具 metadata 判断是否需要审批
  -> TerminalHitlHandler 询问用户
  -> 通过后执行原始工具
```

工具通过自身属性声明风险：

```python
approval_required = True
approval_level = "🔴 高危"
approval_reason = "将在系统上执行 Shell 命令，可能修改文件、安装软件或影响系统状态"
```

当前默认需要审批的工具：

```text
write
edit
bash
```

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
开发调试信息 -> logging / PAICLI_DEBUG_LOG
会话事实     -> sessions/.../messages.jsonl
```

普通终端日志默认是 WARNING，细节日志按需写 debug 文件。

环境变量：

```text
PAICLI_LOG_LEVEL=WARNING
PAICLI_DEBUG_LOG=1
PAICLI_COMMAND_TIMEOUT_SECONDS=120
PAICLI_AUTO_SKILLS=1
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
| HITL | 已接入，合并到 `ToolRegistry` |
| Session/长期记忆 | 已接入，session 实时记录会话树，长期记忆写入 `long_term.md` |
| Skills | 命令化已接入；默认扫描项目、外部/env、全局 skill roots，插件 skills 必须经 `.codex-plugin/plugin.json` manifest 声明；`PAICLI_AUTO_SKILLS=1` 可开启默认关闭的 0/1 自动 skill 选择 |
| Skill compatibility | 已支持 `SKILL.md` / `skill.md`、UTF-8 BOM、折叠 frontmatter description、坏 skill 诊断跳过，以及无参数 `/skill <name>` |
| Plugin format | 已兼容 Codex 风格 `.codex-plugin/plugin.json`、kebab-case `name`、以 `./` 开头的 manifest path、`skills` 字符串/列表/对象声明，以及 `PAICLI_PLUGIN_ROOTS` 外部插件 root |
| Plugin state | 已接入；插件默认禁用，`/plugins` 可查看，`/plugin enable/disable` 写入 `.agents/plugins.json`，enabled 插件 skills 才会进入 `/skills` 和自动 skill 候选 |
| 项目检索 | 使用 `ls` / `grep` / `find` / `read`，不再维护 RAG 索引 |
| Plan 日志 | 旧 `logs/plans/` 专用日志已移出主路径 |
| 测试 | 主线 import / HITL / session 树测试可单独验证 |

## 待清理

- `agent/execute.py` 看起来像旧执行器残留，后续可以确认是否删除。
- `tooling/file_tools.py` 后续如果继续膨胀，可以再拆成 file/edit/search 三类。
