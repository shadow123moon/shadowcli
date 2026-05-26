# pythonProject4 项目地图

这份文档只记录当前 Python 项目的运行入口、模块职责和真实执行链路。`CLAUDE.md` 仍然保留为“改写策略和阶段情况”文档。

## 入口

唯一推荐入口：

```bash
python -m cli_app
```

交互命令：

```text
普通输入            默认走 ReactAgent
/plan <任务>        走 AgentOrchestrator，多 Agent 规划执行
/remember <事实>    写入长期记忆
/memory             查看短期/长期记忆状态
/tools              查看已注册工具
/quit               退出
```

`main.py`、`core.py`、`cli.py` 不再作为入口。后续新增能力优先接到 `cli_app/` 的命令路由和 `ToolRuntime`。

## 执行链路

普通对话：

```text
cli_app
  -> ReactAgent
  -> SubAgent(role=REACT)
  -> ToolRuntime.execute(name, args)
  -> ToolRegistry.execute(name, args)
  -> Tool.execute(args)
```

计划模式：

```text
cli_app /plan
  -> AgentOrchestrator
  -> planner 生成计划
  -> worker 执行步骤
  -> ToolRegistry.execute(name, args)
```

关键约束：Agent 不直接 `tool.execute(...)`，统一走 `registry.execute(...)`。日志、HITL 审批和工具扩展都在这个入口收口。

## 模块职责

| 模块 | 职责 |
|---|---|
| `cli_app/` | 交互入口、命令路由、日志初始化、Plan 日志文件 |
| `agent/react_agent.py` | 默认 ReAct 对话入口 |
| `multi_agent/` | Plan-and-Execute、多 Agent 编排、Planner/Worker |
| `planning/` | 旧版 Plan/DAG 数据结构和规划器 |
| `tooling/` | 工具基类、具体工具、工具注册中心 |
| `extensions/tool_runtime.py` | 工具运行时、before_execute hook、HITL/Reviewer 接入点 |
| `extensions/approval_policy.py` | 工具风险判断 |
| `memory_pythonic/` | 短期记忆、长期记忆、上下文构造、压缩 |
| `llm/` | OpenAI 兼容 Chat API 客户端和消息模型 |

## 记忆

当前有三层概念：

```text
history     = 本轮 LLM 调用的消息序列，不负责长期存储
short_term  = 当前会话近期对话，保存在 MemoryManager 内存中
long_term   = 跨会话可靠事实，默认写入 agent_memory/long_term_memory.json
```

普通输入和 `/plan` 都可以通过 `MemoryManager.context_for(user_input)` 读取记忆上下文，但它们不共用同一段 SubAgent history。

长期记忆当前主要来源：

```text
/remember <事实>
```

普通对话会进入短期记忆，长期记忆不自动从模型回答里抽取事实。这样能避免把不确定回答、临时日志和推理过程污染成长记忆。

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
write_file
execute_command
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

为兼容历史 LLM 调用语义，旧工具名仍作为工具 alias 保留：

```text
read_file
write_file
list_dir
execute_command
```

## 日志

普通终端日志默认是 INFO，细节日志写入计划日志文件。

环境变量：

```text
PAICLI_LOG_LEVEL=INFO
PAICLI_COMMAND_TIMEOUT_SECONDS=120
```

`/plan` 每次执行会在 `logs/plans/` 下生成日志，包含更详细的 Agent、工具调用和 debug 信息。

工具日志应回答“做了什么”：

```text
read_file       看了哪个文件
write_file      写了哪个文件
execute_command 执行了什么命令
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

## 当前状态

| 能力 | 状态 |
|---|---|
| CLI 入口 | 已收敛到 `cli_app/` |
| 默认 React 对话 | 已接入 |
| `/plan` 多 Agent | 已接入 |
| 工具调用 | 统一走 `ToolRegistry.execute()` |
| HITL | 已接入，合并到 `ToolRegistry` |
| 短期/长期记忆 | 已接入，长期记忆由 `/remember` 写入 |
| 项目检索 | 使用 `ls` / `grep` / `find` / `read`，不再维护 RAG 索引 |
| Plan 日志 | 已接入 `logs/plans/` |
| 测试 | `unittest discover -s tests -v` 覆盖主要链路 |

## 待清理

- `agent/execute.py` 看起来像旧执行器残留，后续可以确认是否删除。
- `tooling/file_tools.py` 后续如果继续膨胀，可以再拆成 file/edit/search 三类。
- `memory_pythonic/retrieval.py` 和 `memory_pythonic/tokenizer.py` 是否继续保留，取决于后续是否要做更强的记忆检索。
