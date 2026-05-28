# MCP 集成 - Phase 1 完成报告

## 实现内容

### 1. 核心模块 (mcp_integration/)
- ✅ `config.py` - 配置加载,支持 ~/.paicli/mcp.json
- ✅ `manager.py` - 后台 event loop + 同步接口适配
- ✅ `sanitizer.py` - inputSchema 清洗
- ✅ `wrapper.py` - MCP 工具包装成 Tool 接口

### 2. CLI 集成
- ✅ 修改 `cli_app/runner.py`,启动时加载 MCP servers
- ✅ 自动注册 MCP 工具到 ToolRegistry
- ✅ 退出时清理 MCP 资源

### 3. 测试验证
- ✅ 成功启动 filesystem MCP server
- ✅ 加载 14 个 MCP 工具
- ✅ 成功调用 MCP 工具:
  - `list_directory` - 列出目录
  - `read_text_file` - 读取文件
  - `search_files` - 搜索文件

## 功能特性

### 已实现
- ✅ stdio transport (子进程通信)
- ✅ 同步 Tool 接口适配 (不影响现有代码)
- ✅ 后台 event loop (不阻塞主线程)
- ✅ 工具命名规范 (`mcp__{server}__{tool}`)
- ✅ HITL 集成 (MCP 工具默认需要审批)
- ✅ Schema 清洗 (处理 $ref/anyOf/超长 description)
- ✅ 优雅关闭 (清理资源)

### 未实现 (Phase 2+)
- ❌ HTTP SSE transport
- ❌ MCP resources 支持
- ❌ MCP prompts 支持
- ❌ 图片内容处理
- ❌ Notifications 处理
- ❌ 多个 server 并行启动优化

## 使用方法

### 1. 配置 MCP server

编辑 `~/.paicli/mcp.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed"],
      "disabled": false,
      "env": {}
    }
  }
}
```

### 2. 启动 CLI

```bash
python -m cli_app
```

### 3. 查看工具

```
> /tools
```

会看到 `mcp__filesystem__*` 工具。

### 4. 使用 MCP 工具

Agent 可以自动调用 MCP 工具,例如:

```
> 列出当前目录的文件
```

Agent 会调用 `mcp__filesystem__list_directory`。

## 代码统计

| 文件 | 行数 | 说明 |
|------|------|------|
| config.py | 58 | 配置加载 |
| manager.py | 175 | 核心管理器 |
| sanitizer.py | 50 | Schema 清洗 |
| wrapper.py | 68 | Tool 适配 |
| runner.py (修改) | +30 | CLI 集成 |
| **总计** | **~380 行** | **纯增量代码** |

## 已知问题

1. **shutdown 生命周期验证**: 已修复 `AsyncExitStack` 跨 task 关闭问题
   - 每个 MCP server 现在由一个长期 task 持有 enter/exit 生命周期
   - 已用本地 FastMCP server 和 `@modelcontextprotocol/server-filesystem` 实测通过

2. **dotenv 解析警告**: .env 文件有注释导致解析警告
   - 不影响功能
   - 可以清理 .env 文件的注释

## 下一步 (Phase 2)

1. **多 server 支持**
   - 并行启动多个 server
   - 启动超时处理
   - 失败重试机制

2. **Resources 支持**
   - 实现 `list_resources` / `read_resource`
   - 自动注册虚拟工具

3. **Chrome DevTools 集成**
   - 默认配置 chrome-devtools-mcp
   - 浏览器工具集成

## 总结

Phase 1 **完全成功**,用 ~380 行代码实现了:
- ✅ MCP 协议接入
- ✅ stdio transport
- ✅ 工具注册和调用
- ✅ 与现有架构无缝集成

**没有破坏性改动**,所有现有功能正常工作。
