# ShadowCLI

Python Agent CLI — 基于 ReAct 的交互式代码助手，支持 skill 扩展和插件系统。

## 快速开始

1. **配置环境变量**

```bash
cp .env.example .env
# 编辑 .env，填入你的 API key
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **运行**

```bash
python -m cli_app
```

## 核心功能

- **ReAct Agent** — 工具调用 + 流式输出
- **会话树** — 支持分支、跳转、自动压缩
- **Skill 系统** — 14 个内置 skills（brainstorming、TDD、debugging 等）
- **自动 skill 选择** — 设置 `PAICLI_AUTO_SKILLS=1` 后，根据输入自动加载合适的 skill
- **插件管理** — 兼容 Codex `.codex-plugin` 格式

## 自动 Skill 选择

在 `.env` 中设置 `PAICLI_AUTO_SKILLS=1` 后启用。Agent 会根据你的输入自动选择合适的 skill：

- "我想实现一个新功能" → 自动加载 `brainstorming`
- "测试报错了" → 自动加载 `systematic-debugging`
- "帮我写个登录功能" → 自动加载 `brainstorming`

## 常用命令

```
/skills              查看所有可用 skills
/skill <name>        手动加载指定 skill
/plugins             查看所有插件
/plugin enable <n>   启用插件
/compact             手动压缩会话
/jump <target>       跳转到历史分支
/tree                查看会话树
```

## 项目结构

```
cli_app/        — 命令解析、REPL 路由
app_runtime/    — 运行期资源组装
agent/          — ReAct 循环实现
tooling/        — 工具定义（read、write、bash 等）
memory/         — 长期记忆存储、建议和受控写入工具
skills/         — Skill 注册和选择器
plugin_runtime/ — 插件发现和加载
plugins/        — 插件目录（superpowers 等）
```

## 测试

```bash
python -m unittest discover -s tests -v
```

## 文档

详见 [CLAUDE.md](CLAUDE.md) 查看架构设计和演进原则。
