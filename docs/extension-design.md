# PaiCLI 扩展系统设计文档

## 一、设计思想

### 核心思想：控制反转

传统方式：**核心调用功能**

```
核心代码 → 直接调 HITL
核心代码 → 直接调 Reviewer
核心代码 → 直接调语法检查
```

pi 的方式：**核心发事件，谁注册了谁响应**

```
核心代码 → emit("before_execute") → 谁注册了谁来处理
                                      ├── 可能是 HITL
                                      ├── 可能是 Reviewer
                                      ├── 可能是什么都没有
                                      └── 核心不关心
```

核心不知道有谁在监听，也不依赖任何具体的扩展。

---

## 二、四层架构

```
第 1 层：钩子定义（核心代码预埋触发点）
    ↓
第 2 层：扩展加载器（扫描目录，加载扩展文件）
    ↓
第 3 层：扩展 API（扩展通过 API 注册钩子/工具/命令）
    ↓
第 4 层：调度器（事件触发时，遍历所有注册的 handler 依次调用）
```

### 第 1 层：钩子定义

核心代码在**不可避免要经过的路径**上预埋触发点。关键是选对位置：

```
工具执行流程：
    → [before_execute]  在这里可以拦截、修改参数、拒绝
    → 执行工具
    → [after_execute]   在这里可以检查结果、注入诊断
    → 返回结果
```

原则：钩子放在"决策点"上，不是每行代码都放。

### 第 2 层：扩展加载器

```
启动时：
    1. 扫描 extensions/ 目录
    2. 逐个导入模块
    3. 调用模块的 register(api) 函数
    4. 扩展通过 api 注册自己的钩子/工具/命令

运行时：
    核心代码不知道哪些扩展被加载了
    只知道"有一些 handler 注册在某些事件上"
```

### 第 3 层：扩展 API

API 是扩展和核心之间的契约。扩展只能通过 API 和核心交互，不能直接访问核心内部。

```
扩展能做的：
    api.on(event, handler)          → 注册事件钩子
    api.register_tool(tool)         → 注册工具
    api.register_command(cmd)       → 注册命令
    api.events.emit(channel, data)  → 发布自定义事件（扩展间通信）
    api.events.on(channel, handler) → 监听自定义事件（扩展间通信）

扩展不能做的：
    直接修改核心代码
    直接访问其他扩展的内部
    绕过 API 操作
```

### 第 4 层：调度器（Runner）

```
事件触发时：
    1. 遍历所有扩展
    2. 找到注册了该事件的 handler
    3. 依次调用
    4. 如果某个 handler 返回 {"block": True}，停止后续调用
    5. 把结果返回给核心
```

关键设计决策：handler 的返回值能影响核心行为（拦截、修改、放行）。

---

## 三、两种通信机制

### 1. 系统事件（扩展 ↔ 核心）

```python
# 核心预埋触发点
await hooks.emit("before_execute", tool_name, args)

# 扩展注册 handler
api.on("before_execute", my_handler)
```

用途：扩展拦截/修改核心行为。

### 2. EventBus（扩展 ↔ 扩展）

```python
# 扩展 A 发布
api.events.emit("file_changed", {"path": "config.py"})

# 扩展 B 监听
api.events.on("file_changed", lambda data: check_syntax(data["path"]))
```

用途：扩展之间协作，核心代码不参与。

### 区别

| | 系统事件（api.on） | 扩展间事件（api.events） |
|---|---|---|
| 谁触发 | 核心代码（Runner） | 扩展自己 |
| 事件类型 | 固定的（before_execute 等） | 自定义的（随便起名） |
| 用途 | 扩展拦截/修改核心行为 | 扩展之间通信 |

---

## 四、互斥扩展的处理

HITL 和 Reviewer 是同级选择（二选一），通过配置级互斥实现：

```
用户配置文件里选择用哪个扩展
加载时只加载选中的那个
另一个不加载
```

---

## 五、实现计划

### 第 1 步：创建扩展框架（3 个新文件）

#### `extensions/event_bus.py` — 发布/订阅系统

需要实现：
- `on(event, handler)` — 注册
- `emit(event, *args)` — 触发，返回 handler 的结果
- 支持 handler 返回 `{"block": True}` 来拦截

#### `extensions/api.py` — 扩展 API

需要实现：
- `on(event, handler)` — 注册事件钩子
- `register_tool(tool)` — 注册工具
- `events` — 扩展间通信的 EventBus

#### `extensions/loader.py` — 扩展加载器

需要实现：
- 扫描 `extensions/` 目录
- 导入模块
- 调用 `register(api)`

### 第 2 步：在 ToolRegistry 预埋钩子（改 1 个文件）

#### `extensions/tool_runtime.py`

在 `execute()` 方法里加两个触发点：
- `before_execute` — 工具执行前
- `after_execute` — 工具执行后

`before_execute` 的 handler 如果返回拒绝，就不执行工具。

### 第 3 步：把 HITL 改成扩展（1 个新文件）

#### `extensions/hitl.py`

- 注册 `before_execute` 钩子
- 判断工具是否需要审查（复用 `extensions/approval_policy.py` 的逻辑）
- 需要审查时弹出终端交互
- 用户拒绝则返回 `{"block": True, "reason": "用户拒绝"}`

### 第 4 步：把 Reviewer 做成扩展（1 个新文件）

#### `extensions/reviewer.py`

- 注册 `before_execute` 钩子
- 判断工具是否需要审查
- 需要审查时调 LLM 判断
- LLM 拒绝则返回 `{"block": True, "reason": "AI 审查未通过"}`

### 第 5 步：配置选择（改 1 个文件）

#### `cli_app/factories.py`

- 读取配置（环境变量或配置文件）
- 决定加载哪个扩展（HITL 或 Reviewer）
- 调用加载器

---

## 六、文件清单

```
新增：
  extensions/
    __init__.py
    event_bus.py      ← 发布/订阅
    api.py            ← 扩展 API
    loader.py         ← 扫描加载
    hitl.py           ← HITL 扩展
    reviewer.py       ← Reviewer 扩展

修改：
  extensions/tool_runtime.py ← 预埋钩子
  cli_app/factories.py       ← 加载扩展

暂不动：
  extensions/approval_policy.py ← 工具风险判断
```

---

## 七、整体流程图

### 启动时

```
cli_app
  → 读取配置（用 HITL 还是 Reviewer）
  → loader.py 加载对应的扩展
  → 扩展调 api.on("before_execute", handler) 注册钩子
  → ToolRegistry 内部持有这些 handler
```

### 运行时

```
Worker 要调工具
  → ToolRegistry.execute("write", args)
  → 触发 before_execute 钩子
  → handler 执行（HITL 弹终端 / Reviewer 调 LLM）
  → 返回 block 或放行
  → 放行则执行工具
  → 触发 after_execute 钩子（未来加确定性检查）
  → 返回结果
```

---

## 八、未来可扩展的方向

基于同样的框架，以后可以加：

| 扩展 | 钩子位置 | 作用 |
|------|---------|------|
| 确定性检查（语法） | after_execute | 写文件后自动检查语法 |
| 审计日志 | after_execute | 记录所有工具调用 |
| 计划审查（SUPPLEMENT） | before_plan_execute（需要在 Orchestrator 预埋） | 用户补充要求 |
| Step 结果审查 | step_complete（需要在 Orchestrator 预埋） | 审查 Step 完成质量 |
| 网络搜索工具 | register_tool | 加 search 工具 |
| Git 快照 | after_execute | 写文件后自动 git commit |

框架建好后，加这些功能 = 写一个扩展文件丢到 `extensions/` 目录，核心代码不动。
