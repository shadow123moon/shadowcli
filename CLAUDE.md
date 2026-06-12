# pythonProject4

Python Agent CLI — 基于 ReAct 的交互式代码助手，支持 skill 扩展、插件系统和会话树管理。

## 项目概览

**核心能力：**
- ReAct Agent — 工具调用 + 流式输出
- 会话树结构 — 支持分支、跳转、压缩
- Skill 系统 — 项目 skill + 插件贡献 skill，可选的 LLM 自动选择
- 插件管理 — `.codex-plugin/plugin.json` 格式兼容，启用/禁用状态持久化
- 运行时保护 — Hook 机制（freshness guard）
- MCP 集成 — Model Context Protocol server 支持

## 架构分层

```
cli_app/        — 命令解析、REPL 路由、终端交互
app_runtime/    — 运行期资源组装（AppRuntime、HookManager、SkillManager、SessionRuntime）
agent/          — ReAct 循环实现
tooling/        — 工具定义与工具运行时（read、write、bash、grep、ToolRuntime 等）
skills/         — Skill 注册表和选择器
plugin_runtime/ — 插件发现、manifest 解析、状态管理
sessions/       — 会话树、压缩、长期记忆
llm/            — LLM 客户端封装（OpenAI 兼容 API）
ui/             — 渲染抽象（终端、Markdown）
```

## 运行期收拢

`app_runtime/` 负责创建、持有和刷新运行期资源：

- **AppRuntime** — 总装入口，持有所有运行期组件
- **HookManager** — 工具 hooks 的安装与桥接（freshness guard）
- **AppStateStore** — 项目级运行期状态（插件启用状态）
- **SessionRuntime** — 会话上下文准备、自动压缩、agent 对话重载
- **SkillManager** — 组合 PluginManager + SkillRegistry，承接插件启用/禁用、自动 skill 选择、skill context 组装
- **EventBus** — 运行期生命周期事件发布（为阶段 7 插件贡献 hooks 预留）

调用方通过 `app_runtime.skill_manager.X` / `app_runtime.session_runtime.X` 访问能力，不再通过门面转发。

## 近期演进

当前 plugin/runtime 方向按小阶段推进：

```text
阶段 3: plugin manifest -> skill contributions，已完成
阶段 4: 市面 skill/plugin 格式适配，已完成
阶段 5: 插件启用/禁用/状态管理，已完成
阶段 6: 隐式 skill 选择（PAICLI_AUTO_SKILLS=1），已完成最小版
运行期收拢: AppRuntime + EventBus + HookManager + AppStateStore + SessionRuntime + SkillManager，已完成
阶段 7: 插件贡献 hooks / MCP server / runtime extensions（待实现）
```

**阶段 6 边界：** `PAICLI_AUTO_SKILLS=1` 时，普通输入前用 LLM selector 在 project skills 和 enabled plugin skills 中选择 0/1 个 skill；selector 只看 `name/source/description/argument_hint` metadata，不读取完整 `SKILL.md`；命中时终端打印自动加载的 skill 和原因。默认关闭，不做多 skill 链式加载、向量库、长期偏好学习或自动启用插件。

**运行期收拢边界：** 后续插件贡献的 hooks、MCP server、runtime extension contributions 应优先挂到 `app_runtime` 入口，而不是继续散落在 runner/router 里。

## 运行 / 测试

```bash
python -m cli_app                       # 入口，交互式 CLI
python -m unittest discover -s tests -v # 当前测试入口
```

LLM 走 OpenAI 兼容 API，配置走环境变量（`OPENAI_API_KEY` / `API_URL` / `MODEL`）或 `.env`。

## 测试文件位置

- `tests/test_*.py` — 自动化单元/集成测试，必须能被 `python -m unittest discover -s tests` 稳定发现和运行
- `debug/artifacts/` — 测试输出、截图、临时压缩包等产物
- 根目录不放散落测试文件；新增测试按上面归位

## 演进原则

写 Python 模块时：
- 优先 `dataclass` / `Enum` / `Protocol`，不要造 Java 风格的接口 + 实现类
- 异常处理：Python 让它抛出，不要层层 `try/catch` 包一层 RuntimeException
- 并发：`concurrent.futures` / `asyncio`，不要照搬 Java 的 ExecutorService 抽象
- 命名：`xxxManager` / `xxxService` 在 Python 里常常一个模块函数就够，不要无脑加类
- DRY、YAGNI、小步迭代、测试先行

## 已知问题

- LLM 客户端已拆到 `llm/client.py`，消息/响应模型放在 `llm/types.py`
- 短期 memory / JSON 长期记忆已退出主路径；会话事实在 session 树里，长期事实在 `long_term.md`，压缩 token 估算优先使用 `tiktoken`
- 根目录旧入口/兼容文件已删除；旧 Plan / Task / Planner 包已退出主路径

## LSP / 类型检查

- 项目装了 `pyright-lsp` plugin，Claude 编辑 Python 文件时会自动收到 `<new-diagnostics>` 推送
- 想拿全项目错误清单：`pyright` CLI 直接跑
- 没装 `mypy`（不要建议改用 mypy，统一用 pyright）
