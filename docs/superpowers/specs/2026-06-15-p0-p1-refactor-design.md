# P0+P1 架构重构设计

**日期：** 2026-06-15  
**范围：** 全部 P0（4个问题）+ P1（2个问题）  
**策略：** 分层重构（方案 B）

---

## 背景

经过三轮架构审查，识别出 6 个阻碍插件系统扩展的问题：

**P0（阻碍阶段 7）：**
1. ReplRouter 接收 5 个函数参数，破坏了 AppRuntime 的运行时收拢
2. MCP 工具加载在 cli_app/runner.py，插件无法贡献 MCP server
3. cli_app/factories.py 职责错位，且 build_registry 命名混乱
4. PluginManifest 只支持 skills，没有为阶段 7 预留扩展点

**P1（可维护性）：**
5. tooling/__init__.py 导出了内部机制（FileTracker, ReadStateCache）
6. HookManager 只支持 tool hooks，缺少 LLM/skill 层 hooks 的设计

---

## 目标

**核心目标：** AppRuntime 从"数据容器"变成"运行时入口"

**具体目标：**
1. cli_app 不再直接依赖 agent/tooling/llm/sessions
2. 插件可以通过 PluginManifest 声明 MCP server / hooks / tools
3. 为阶段 7（插件贡献运行时扩展）扫清障碍

---

## 架构调整

### 依赖方向变化

**原来：**
```
cli_app/runner.py → cli_app/factories → agent, tooling, llm, sessions
                  ↘ mcp_integration
ReplRouter ← 5 个函数参数（build_agent, chat_fn, ...）
```

**现在：**
```
cli_app/runner.py → app_runtime → agent, tooling, llm, sessions, mcp_integration
ReplRouter ← app_runtime（只接收一个参数）
```

### 模块职责划分

| 模块 | 职责 |
|------|------|
| app_runtime | 运行时资源组装 + 能力暴露（build_agent, chat, MCP 加载） |
| cli_app | 命令解析 + REPL 循环 + 调用 app_runtime |
| ReplRouter | 命令路由 + 从 app_runtime 拿能力 |

---

## 分层重构方案

### 第一轮：AppRuntime 层改造

**目标：** AppRuntime 成为真正的运行时入口

#### 1.1 新建 `app_runtime/builders.py`

从 `cli_app/factories.py` 迁移并改进：

**函数清单：**
- `build_default_tool_runtime() -> ToolRuntime` 
  - 原 `build_registry()`，修正命名
  - 注册默认工具：ReadTool, WriteTool, EditTool, BashTool, LsTool, GrepTool, FindTool, WebSearchTool, WebFetchTool
  
- `build_default_mcp_manager(mcp_config: dict) -> McpServerManager`
  - 封装原 `runner.py` 的 `_load_mcp_tools()` 逻辑
  - 启动 MCP servers，返回已配置的 manager
  
- `list_tools(runtime: ToolRuntime) -> str`
  - 原 `cli_app/factories.list_tools()`，不变
  
- `build_long_term_memory(path) -> TextLongTermMemory`
  - 原 `cli_app/factories.build_long_term_memory()`，不变

**实现细节：**
```python
# 伪代码示例
def build_default_mcp_manager(mcp_config: dict) -> McpServerManager:
    manager = McpServerManager()
    for name, config in mcp_config.items():
        if config.disabled:
            continue
        try:
            manager.start_server_sync(name, config)
        except Exception:
            log.exception(f"MCP server '{name}' failed")
    return manager
```

#### 1.2 修改 `app_runtime/runtime.py`

**AppRuntime 新增字段：**
```python
@dataclass
class AppRuntime:
    # ... 原有字段 ...
    mcp_manager: McpServerManager | None = None
```

**AppRuntime.create() 新增参数：**
```python
@classmethod
def create(
    cls,
    cwd: Path | str,
    *,
    tool_runtime: Any = None,
    mcp_config: dict | None = None,  # 新增
    session_store: SessionStore | None = None,
    long_term_memory: Any | None = None,
    long_term_builder: LongTermBuilder | None = None,
    event_bus: EventBus | None = None,
) -> "AppRuntime":
```

**AppRuntime.create() 逻辑变化：**
1. 如果 `tool_runtime` 是 None，调用 `build_default_tool_runtime()`
2. 如果 `mcp_config` 不是 None：
   - 调用 `build_default_mcp_manager(mcp_config)` 创建 manager
   - 遍历 manager 加载的工具，注册到 `tool_runtime.registry`
   - 将 manager 存入 `self.mcp_manager`
3. 其他逻辑不变

**AppRuntime 新增方法：**

| 方法 | 职责 | 实现方式 |
|------|------|---------|
| `build_agent(messages=None, on_message_appended=None)` | 构建 ReactAgent | 调用 `ReactAgent(self.tool_runtime.registry, ...)` |
| `chat(messages, **kwargs)` | LLM 对话 | 委托给 `llm.chat(messages, **kwargs)` |
| `list_tools()` | 列出已注册工具 | 委托给 `builders.list_tools(self.tool_runtime)` |
| `build_branch_summary(plan)` | 生成分支摘要 | 委托给 `sessions.summarizer.generate_branch_summary(plan)` |

#### 1.3 修改 `app_runtime/__init__.py`

**新增导出：**
```python
from .builders import (
    build_default_tool_runtime,
    build_default_mcp_manager,
    list_tools,
    build_long_term_memory,
)

__all__ = [
    # ... 原有导出 ...
    "build_default_tool_runtime",
    "build_default_mcp_manager",
    "list_tools",
    "build_long_term_memory",
]
```

#### 1.4 向后兼容处理

`cli_app/factories.py` 暂时保留，内部改为重导出：
```python
# DEPRECATED: 请使用 app_runtime.builders
from app_runtime.builders import (
    build_default_tool_runtime as build_registry,
    list_tools,
    build_long_term_memory,
)

def build_agent(registry, *, conversation_messages=None, on_message_appended=None):
    # DEPRECATED: 请使用 AppRuntime.build_agent()
    from agent import ReactAgent
    return ReactAgent(registry, conversation_messages=conversation_messages, 
                      on_message_appended=on_message_appended)

__all__ = ["build_registry", "list_tools", "build_long_term_memory", "build_agent"]
```

---

### 第二轮：调用方层简化

**目标：** ReplRouter 和 runner.py 不再组装运行时

#### 2.1 修改 `cli_app/runner.py`

**repl() 函数简化：**

**原来：**
```python
def repl():
    app_runtime = AppRuntime.create(cwd, tool_runtime=build_registry(), ...)
    mcp_manager = McpServerManager()
    mcp_loaded, mcp_failed = _load_mcp_tools(app_runtime.tool_runtime, mcp_manager)
    
    router = ReplRouter(
        app_runtime=app_runtime,
        build_agent=build_agent,
        run_agent_once=run_once,
        list_tools=list_tools,
        chat_fn=chat,
        build_branch_summary=generate_branch_summary,
    )
```

**现在：**
```python
def repl():
    mcp_config = load_mcp_config()
    app_runtime = AppRuntime.create(cwd, mcp_config=mcp_config)
    
    router = ReplRouter(
        app_runtime=app_runtime,
        renderer=renderer,
    )
```

**删除函数：**
- `_load_mcp_tools()` - 已移到 `app_runtime/builders.py`
- `_render_mcp_status()` - 改为在 `AppRuntime.create()` 里通过 EventBus 发布事件

**MCP 状态通知改为事件：**
```python
# app_runtime/builders.py 里
def build_default_mcp_manager(mcp_config, event_bus=None):
    manager = McpServerManager()
    loaded, failed = 0, 0
    for name, config in mcp_config.items():
        ...
        if success:
            loaded += 1
        else:
            failed += 1
    
    if event_bus:
        event_bus.publish("mcp.loaded", loaded=loaded, failed=failed)
    
    return manager
```

```python
# cli_app/runner.py 里订阅事件
app_runtime.event_bus.subscribe("mcp.loaded", 
    lambda **kw: renderer.message(f"✓ 已加载 {kw['loaded']} 个 MCP server"))
```

#### 2.2 修改 `cli_app/router.py`

**ReplRouter.__init__() 简化：**

**原来：**
```python
def __init__(
    self,
    *,
    app_runtime: AppRuntime,
    renderer: Renderer,
    build_agent: Callable[..., ReactAgent],  # 删除
    run_agent_once: Callable[..., None],     # 删除
    list_tools: Callable[[Any], str] = default_list_tools,  # 删除
    chat_fn: Callable[..., Any] = default_chat,  # 删除
    build_branch_summary: Callable[[NavigationPlan], str] | None = None,  # 删除
    ...
):
```

**现在：**
```python
def __init__(
    self,
    *,
    app_runtime: AppRuntime,
    renderer: Renderer,
    run_agent_once: Callable[..., None] | None = None,  # 可选，默认用内置实现
    confirm_memory: Callable[[MemoryProposal], bool] = ask_memory_confirmation,
    run_interactive_in_worker: bool = False,
):
    self.app_runtime = app_runtime
    self.renderer = renderer
    self.run_agent_once = run_agent_once or _default_run_agent_once
    # ... 其他字段从 app_runtime 拿 ...
```

**内部调用改为从 app_runtime 拿：**

| 原来 | 现在 |
|------|------|
| `self.build_agent(...)` | `self.app_runtime.build_agent(...)` |
| `self.list_tools(self.runtime)` | `self.app_runtime.list_tools()` |
| `self.chat_fn(...)` | `self.app_runtime.chat(...)` |
| `self.build_branch_summary(...)` | `self.app_runtime.build_branch_summary(...)` |

**skill_selector 逻辑：**
- 原来从构造参数传入，现在改为 `None`，在 `_select_auto_skill()` 里动态创建：
  ```python
  def _select_auto_skill(self, line: str) -> SkillSelection | None:
      return self.app_runtime.skill_manager.select_auto_skill(
          line,
          selector=None,  # 让 SkillManager 内部创建
          chat_fn=self.app_runtime.chat,
      )
  ```

---

### 第三轮：清理层

**目标：** 清理公开 API，为阶段 7 预留扩展点

#### 3.1 修改 `tooling/__init__.py`

**清理导出：**

**原来：**
```python
__all__ = [
    "Tool",
    "ToolRegistry",
    "ToolRuntime",
    "ToolExecutionBlocked",
    "BeforeExecuteHook",
    "ReadTool", "WriteTool", "EditTool", "BashTool", ...  # 具体工具
    "FileTracker",  # 删除：内部机制
    "ReadStateCache",  # 删除：内部机制
    "get_file_tracker",  # 删除：内部机制
    "get_read_state_cache",  # 删除：内部机制
    "register_freshness_guard",  # 删除：内部机制
]
```

**现在：**
```python
__all__ = [
    # 插件作者需要的 API
    "Tool",
    "ToolRegistry",
    "ToolRuntime",
    "ToolExecutionBlocked",
    "BeforeExecuteHook",
    
    # 具体工具实现（可选，插件可能需要）
    "ReadTool", "WriteTool", "EditTool", "BashTool", 
    "LsTool", "GrepTool", "FindTool", 
    "WebSearchTool", "WebFetchTool",
]
```

**注释说明：**
```python
# 内部机制（freshness guard）不导出
# 如需使用，请直接导入 tooling.file_tracker 或 tooling.file_cache
# from tooling.file_tracker import FileTracker  # OK
# from tooling import FileTracker  # 不再支持
```

#### 3.2 修改 `plugin_runtime/manifest.py`

**PluginManifest 新增字段：**

```python
@dataclass(frozen=True)
class PluginToolContribution:
    """插件贡献的工具（阶段 7 实现）"""
    module: str  # 例如 "tools.my_tool"
    class_name: str  # 例如 "MyTool"

@dataclass(frozen=True)
class PluginHookContribution:
    """插件贡献的 hook（阶段 7 实现）"""
    event: str  # 例如 "llm.before_chat"
    handler: str  # 例如 "hooks/llm_hook.py"

@dataclass(frozen=True)
class PluginMcpContribution:
    """插件贡献的 MCP server（阶段 7 实现）"""
    name: str
    command: str
    args: list[str] | None = None
    env: dict[str, str] | None = None

@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    skills: list[PluginSkillContribution]
    
    # 阶段 7 扩展点（现在加字段，但不实现加载逻辑）
    tools: list[PluginToolContribution] | None = None
    hooks: list[PluginHookContribution] | None = None
    mcp_servers: list[PluginMcpContribution] | None = None
```

**read_plugin_manifest() 更新：**
- 解析 `tools` / `hooks` / `mcp_servers` 字段（如果存在）
- 如果字段格式错误，加 diagnostic，但不阻止插件加载
- 阶段 7 实现时，PluginManager 会读取这些字段并加载

**manifest 示例：**
```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "skills": ["skills/"],
  "mcp_servers": [
    {
      "name": "my-server",
      "command": "python",
      "args": ["-m", "my_plugin.mcp_server"]
    }
  ],
  "hooks": [
    {
      "event": "llm.before_chat",
      "handler": "hooks/llm_hook.py"
    }
  ],
  "tools": [
    {
      "module": "tools.custom",
      "class_name": "CustomTool"
    }
  ]
}
```

#### 3.3 HookManager 设计补充（不改代码，只文档化）

**当前状态：**
- HookManager 只支持 `on_before_execute(hook)` - tool 层 hooks
- EventBus 已存在，可以用来实现全局 hooks

**阶段 7 路径：**
1. AppRuntime 在关键点发布事件：
   - `llm.before_chat` - LLM 调用前
   - `llm.after_chat` - LLM 调用后
   - `skill.before_select` - skill 选择前
   - `skill.after_load` - skill 加载后
   - `tool.before_execute` - 工具执行前（已有，通过 ToolRuntime）
   - `tool.after_execute` - 工具执行后

2. 插件通过 manifest 声明 hooks：
   ```json
   {
     "hooks": [
       {"event": "llm.before_chat", "handler": "hooks/token_logger.py"}
     ]
   }
   ```

3. PluginManager 加载插件时：
   - 读取 manifest.hooks
   - 动态导入 handler 模块
   - 调用 `app_runtime.event_bus.subscribe(event, handler_fn)`

**不需要修改 HookManager**，因为：
- tool hooks 已经通过 `HookManager.on_before_execute()` 实现
- 其他层的 hooks 通过 EventBus 实现（更灵活）

---

## 测试策略

### 单元测试

| 测试文件 | 覆盖范围 |
|---------|---------|
| `tests/app_runtime/test_builders.py` | `build_default_tool_runtime()`, `build_default_mcp_manager()` |
| `tests/app_runtime/test_runtime.py` | `AppRuntime.create()` 加载 MCP 工具 |
| `tests/app_runtime/test_runtime_methods.py` | `build_agent()`, `chat()`, `list_tools()`, `build_branch_summary()` |
| `tests/plugin_runtime/test_manifest.py` | PluginManifest 解析新字段 |

### 集成测试

| 场景 | 验证点 |
|------|--------|
| repl 启动 | AppRuntime 加载默认工具 + MCP 工具，ReplRouter 正常路由 |
| skill 调用 | ReplRouter 从 app_runtime 拿 build_agent，skill 正常加载 |
| MCP 工具调用 | MCP server 正常启动，工具可被 agent 调用 |

### 回归测试

| 兼容性检查 | 预期结果 |
|-----------|---------|
| `from cli_app.factories import build_registry` | DeprecationWarning，但仍可用 |
| `from tooling import FileTracker` | ImportError（不再导出） |
| 原有 REPL 命令（/tools, /skill, /plugin） | 功能不变 |

---

## 迁移路径

### 第一轮：AppRuntime 层（约 2 小时）

1. 创建 `app_runtime/builders.py`，迁移 factories 代码
2. 修改 `AppRuntime.create()` 和新增方法
3. 修改 `cli_app/factories.py` 为兼容层
4. 跑单元测试，确保 AppRuntime 正常工作

**完成标志：** `AppRuntime.create(mcp_config=...)` 能加载 MCP 工具

### 第二轮：调用方层（约 1.5 小时）

1. 修改 `cli_app/runner.py`，简化 repl()
2. 修改 `cli_app/router.py`，简化 ReplRouter.__init__()
3. 删除 runner.py 的 `_load_mcp_tools()` 等辅助函数
4. 跑集成测试，确保 REPL 正常启动

**完成标志：** `ReplRouter(app_runtime, renderer)` 可正常工作

### 第三轮：清理层（约 30 分钟）

1. 修改 `tooling/__init__.py`，清理导出
2. 修改 `plugin_runtime/manifest.py`，加新字段
3. 更新 PluginManifest 解析逻辑
4. 跑回归测试，确保向后兼容

**完成标志：** PluginManifest 可解析 tools/hooks/mcp_servers 字段

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 第一轮改动较大，测试覆盖不足 | 引入 bug | 每个 builder 函数单独测试，先跑单元测试再跑集成测试 |
| cli_app/factories 兼容层被忽略 | 其他代码调用失败 | 加 DeprecationWarning，文档明确标注 |
| ReplRouter 简化后，run_agent_once 参数丢失 | 单元测试失败 | 保留 run_agent_once 为可选参数，默认用内置实现 |
| PluginManifest 新字段解析错误 | 插件加载失败 | 新字段都是 Optional，解析失败只加 diagnostic 不阻止加载 |

---

## 验收标准

### 功能验收

- [ ] `AppRuntime.create(mcp_config=...)` 能加载 MCP 工具
- [ ] `app_runtime.build_agent()` 能构建 ReactAgent
- [ ] `ReplRouter(app_runtime, renderer)` 可正常启动
- [ ] `/tools` 命令显示默认工具 + MCP 工具
- [ ] `/skill <name>` 命令正常工作
- [ ] `/plugin enable|disable` 命令正常工作

### 架构验收

- [ ] cli_app 不再直接 import agent / tooling / llm / sessions
- [ ] tooling/__init__.py 不再导出 FileTracker / ReadStateCache
- [ ] PluginManifest 可解析 tools / hooks / mcp_servers 字段
- [ ] 所有单元测试通过
- [ ] 所有集成测试通过

### 文档验收

- [ ] CLAUDE.md 更新"运行期收拢"章节
- [ ] app_runtime/builders.py 有清晰的 docstring
- [ ] cli_app/factories.py 有 DEPRECATED 注释
- [ ] plugin_runtime/manifest.py 有阶段 7 字段的说明注释

---

## 后续工作（阶段 7）

完成这次重构后，阶段 7 可以直接实现：

1. **插件贡献 MCP server**
   - PluginManager 读取 manifest.mcp_servers
   - 调用 `app_runtime.mcp_manager.start_server_sync(...)`

2. **插件贡献 hooks**
   - PluginManager 读取 manifest.hooks
   - 调用 `app_runtime.event_bus.subscribe(event, handler)`

3. **插件贡献工具**
   - PluginManager 读取 manifest.tools
   - 动态导入并调用 `app_runtime.tool_runtime.registry.register(tool)`

4. **全局事件发布**
   - 在 `AppRuntime.chat()` 里发布 `llm.before_chat` / `llm.after_chat`
   - 在 `SkillManager.select_auto_skill()` 里发布 `skill.before_select`

---

## 总结

这次重构通过分三轮改造，将 AppRuntime 从"数据容器"升级为"运行时入口"，解决了全部 P0 + P1 问题：

- **P0.1** ReplRouter 简化为只接收 app_runtime ✓
- **P0.2** MCP 工具加载移入 AppRuntime ✓
- **P0.3** factories 移到 app_runtime/builders.py ✓
- **P0.4** PluginManifest 加扩展字段 ✓
- **P1.5** tooling 清理内部导出 ✓
- **P1.6** HookManager 文档化扩展路径 ✓

核心改进：
1. 依赖方向理顺：cli_app → app_runtime → 底层模块
2. 扩展点明确：PluginManifest 预留阶段 7 字段
3. 测试友好：每层独立测试，向后兼容

预计总工作量：**4 小时**（单人完成）
