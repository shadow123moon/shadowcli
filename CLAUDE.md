# pythonProject4

`D:\paicli-main\paicli-main`(Java/Maven 项目 **PaiCLI**)的 **Python 重写版**。这不是从零设计的项目——所有模块都有 Java 原版可对照。

## 项目上下文

**原项目 PaiCLI**:一个对标 Claude Code 的 Java Agent CLI,作者沉默王二,按"期"演进(第一期 ReAct,第二期 Plan-and-Execute + DAG,第三期 Memory,第四期 RAG,第五期 Multi-Agent...截至第 21 期已实现 LSP 诊断注入、Git 快照、异步后台任务、图片输入等)。

**重写目的**:用户**逐模块学习**,工作流是:
1. Claude(我)读 Java 原版对应模块,理解其设计
2. Claude 用 Python 习惯重写一份,**不是逐行翻译**——要重构成 Pythonic 风格
3. 用户阅读 Python 版本来学习这套架构

**对协作者(Claude)的核心要求**:重构能力。Java 的 `Builder` / 接口 / 静态工厂 / 复杂继承,在 Python 里要换成 dataclass / Protocol / `@classmethod`、组合等更地道的写法,而不是机械搬运。

## 原项目位置

```
D:\paicli-main\paicli-main\           ← Java 源码
├── src/main/java/com/paicli/         ← 按子包对应"期"的功能
│   ├── agent/ plan/ memory/ rag/ runtime/ tool/ llm/
│   ├── tui/  mcp/  lsp/  snapshot/  hitl/  skill/  ...
├── pom.xml
├── AGENTS.md  README.md  ROADMAP.md  ← 权威设计文档,看模块设计时优先读
```

## Python 重写状态(2026-05-23)

| 期 | Java 包 | Python 模块 | 状态 |
|---|---|---|---|
| 1+2 | `agent/` `plan/` `tool/` `llm/` | `cli_app/` `agent/` `planning/` `tooling/` `llm/` | 骨架完成,有测试 |
| 2(细化) | `plan/` | `planning/` (`plan.py` `task.py` `planner.py`) | 已作为唯一 Plan/DAG 实现 |
| 3 | `memory/` | `memory_pythonic/` (短期/长期/压缩/budget/tokenizer 等) | 骨架完成 |
| 4 | `rag/` | — | 已放弃；本地项目检索改用 read/grep/find/ls |
| 5 | `agent/` 子代理部分 | `multi_agent/` (orchestrator/sub_agent/roles/messages/budget) | 骨架完成 |
| 6+ | tui / mcp / lsp / snapshot / hitl / runtime / skill | 未开始 | — |

## 运行 / 测试

```bash
python -m cli_app                       # 入口,交互式 CLI
python -m unittest discover -s tests -v # 当前测试入口
```

LLM 走 OpenAI 兼容 API,配置走环境变量(`OPENAI_API_KEY` / `API_URL` / `MODEL`)或 `.env`。

## 重构原则(重要)

写 Python 模块时:
- **不要逐行翻译 Java**——先看懂 Java 那一期的"意图",再用 Python 重新组织
- 优先 `dataclass` / `Enum` / `Protocol`,不要造 Java 风格的接口 + 实现类
- 异常处理:Python 让它抛出,不要 Java 风格层层 `try/catch` 包一层 RuntimeException
- 并发:`concurrent.futures` / `asyncio`,不要照搬 Java 的 ExecutorService 抽象
- 命名:Java 的 `xxxManager` / `xxxService` 在 Python 里常常一个模块函数就够,不要无脑加类

## 已知问题(当前快照)

- LLM 客户端已拆到 `llm/client.py`，消息/响应模型放在 `llm/types.py`。
- `memory_pythonic/tokenizer.py` 依赖 `jieba`,未安装时会 `possibly unbound`。可选装:`pip install jieba`,或在使用处加软降级。
- 根目录旧入口/兼容文件已删除；Plan / Task / Planner 统一放在 `planning/`。

## LSP / 类型检查

- 项目装了 `pyright-lsp` plugin,Claude 编辑 Python 文件时会自动收到 `<new-diagnostics>` 推送
- 想拿全项目错误清单:`pyright` CLI 直接跑
- 没装 `mypy`(不要建议改用 mypy,统一用 pyright)
