# pythonProject4

当前项目是一个已经独立运行的 Python Agent CLI。`D:\paicli-main\paicli-main`(Java/Maven 项目 **PaiCLI**)仍然是重要参考，但本项目不再以“逐期重写 Java 原版”为目标。

## 项目上下文

**原项目 PaiCLI**:一个对标 Claude Code 的 Java Agent CLI,作者沉默王二,按"期"演进(第一期 ReAct,第二期 Plan-and-Execute + DAG,第三期 Memory,第四期 RAG,第五期 Multi-Agent...截至第 21 期已实现 LSP 诊断注入、Git 快照、异步后台任务、图片输入等)。

**当前目标**:以现有 Python 项目为主线，持续维护、收敛边界、补齐测试和文档。Java 原版用于理解设计意图和借鉴思路，不作为必须对齐的实现蓝本。

**对协作者(Claude)的核心要求**:维护判断和边界意识。优先尊重当前 Python 模块结构；需要借鉴 Java 设计时，先理解意图，再用 Python 习惯落到现有代码里，避免机械搬运和推倒重来。

## 原项目位置

```
D:\paicli-main\paicli-main\           ← Java 源码
├── src/main/java/com/paicli/         ← 按子包对应"期"的功能
│   ├── agent/ plan/ memory/ rag/ runtime/ tool/ llm/
│   ├── tui/  mcp/  lsp/  snapshot/  hitl/  skill/  ...
├── pom.xml
├── AGENTS.md  README.md  ROADMAP.md  ← 权威设计文档,看模块设计时优先读
```

## Python 项目状态(2026-06-09)

| 参考期 | Java 包 | Python 模块 | 状态 |
|---|---|---|---|
| 1+2 | `agent/` `plan/` `tool/` `llm/` | `cli_app/` `agent/` `tooling/` `llm/` | 主路径已接入,持续维护 |
| 3 | `memory/` | `sessions/long_term.py` (`long_term.md` 文本事实清单) | 已瘦身为项目级 markdown 记忆 |
| 4 | `rag/` | — | 已放弃；本地项目检索改用 read/grep/find/ls |
| 6+ | hitl / runtime / skill | `extensions/tool_runtime.py` `plugin_runtime/` `skills/` `cli_app/` | HITL 与工具运行时已接入；skill 命令化和插件 manifest 入口已接入 |
| 6+ | tui / mcp / lsp / snapshot | — | 未接入主路径 |

## 近期演进顺序

当前 plugin/runtime 方向按小阶段推进：

```text
阶段 3: plugin manifest -> skill contributions，已完成并接入主入口
阶段 4: 插件启用/禁用/状态管理，下一步
阶段 5: hooks / MCP server / runtime extension contributions
阶段 6: 从命令化 skill 升级到可解释的隐式 skill 选择
```

阶段 4 的边界：先做 `/plugins`、`/plugin enable <id>`、`/plugin disable <id>` 和项目级启用状态存储；不在这一阶段实现 hooks、MCP server、runtime extension 或自动 skill 匹配。

## 运行 / 测试

```bash
python -m cli_app                       # 入口,交互式 CLI
python -m unittest discover -s tests -v # 当前测试入口
```

LLM 走 OpenAI 兼容 API,配置走环境变量(`OPENAI_API_KEY` / `API_URL` / `MODEL`)或 `.env`。

## 测试文件位置

- `tests/test_*.py`: 自动化单元/集成测试，必须能被 `python -m unittest discover -s tests` 稳定发现和运行。
- `debug/artifacts/`: 测试输出、截图、临时压缩包等产物。
- 根目录不放散落测试文件；新增测试按上面三类归位。

## 演进原则(重要)

写 Python 模块时:
- **不要为了对齐 Java 推倒现有 Python 实现**——先看懂需求和现有边界，再小步整理
- 优先 `dataclass` / `Enum` / `Protocol`,不要造 Java 风格的接口 + 实现类
- 异常处理:Python 让它抛出,不要 Java 风格层层 `try/catch` 包一层 RuntimeException
- 并发:`concurrent.futures` / `asyncio`,不要照搬 Java 的 ExecutorService 抽象
- 命名:Java 的 `xxxManager` / `xxxService` 在 Python 里常常一个模块函数就够,不要无脑加类

## 已知问题(当前快照)

- LLM 客户端已拆到 `llm/client.py`，消息/响应模型放在 `llm/types.py`。
- 短期 memory / JSON 长期记忆已退出主路径；会话事实在 session 树里，长期事实在 `long_term.md`，压缩 token 估算优先使用 `tiktoken`。
- 根目录旧入口/兼容文件已删除；旧 Plan / Task / Planner 包已退出主路径。

## LSP / 类型检查

- 项目装了 `pyright-lsp` plugin,Claude 编辑 Python 文件时会自动收到 `<new-diagnostics>` 推送
- 想拿全项目错误清单:`pyright` CLI 直接跑
- 没装 `mypy`(不要建议改用 mypy,统一用 pyright)
