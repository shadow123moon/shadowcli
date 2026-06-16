# 过时的 Debug 脚本

这些脚本依赖已删除的模块，已不再可用：

## debug_planner_latency.py
- **问题**: 依赖 `multi_agent.sub_agent.PLANNER_PROMPT`（模块已删除）
- **用途**: 测试 planner API 延迟
- **状态**: 需要重构以使用新架构

## debug_plan_batches.py
- **问题**: 依赖 `cli_app.factories.build_registry`（已删除的兼容层）和 `multi_agent` 模块
- **用途**: 检查 planner 生成的步骤批次调度
- **状态**: 需要重构以使用 `AppRuntime`

## 迁移指南

如需恢复这些脚本，需要：
1. 替换 `cli_app.factories` → 使用 `AppRuntime.create()`
2. 替换 `multi_agent` 模块 → 使用当前的 agent/skill 架构
3. 更新 prompt 常量引用 → 从 `agent/prompts.py` 导入

相关 commit: 删除旧 plan/task/planner 包，运行期收拢到 AppRuntime
