"""统一的终端输出层。

所有 Agent / 编排器的用户可见输出都走这里，方便：
- 统一样式
- 未来切换到事件总线 / TUI 库（rich 等）
- 避免业务模块反向依赖 cli_app
"""
from pathlib import Path
from typing import TextIO

COMMAND_OUTPUT_PREVIEW_CHARS = 4000


def _write(message: str, out: TextIO | None = None, *, end: str = "\n", flush: bool = False) -> None:
    if out is not None:
        out.write(message + end)
        return
    print(message, end=end, flush=flush)


def print_message(message: str) -> None:
    print(message)


def print_content_delta(text: str, out: TextIO | None = None) -> None:
    _write(text, out, end="", flush=True)


def print_tool_start(tool_name: str, out: TextIO | None = None) -> None:
    _write(f"\n🛠️ {tool_name}", out, flush=True)


def print_command_result(
    agent_name: str,
    tool_name: str,
    result: str,
    out: TextIO | None = None,
) -> None:
    if tool_name not in {"bash", "execute_command"}:
        return
    text = result or ""
    if len(text) > COMMAND_OUTPUT_PREVIEW_CHARS:
        text = (
            text[:COMMAND_OUTPUT_PREVIEW_CHARS]
            + f"\n...（输出过长，已截断；完整结果见计划日志，共 {len(result)} 字）"
        )
    _write(f"📤 [{agent_name}] {tool_name} 结果:\n{text}", out)


def print_final_result(title: str, result: str, plan_log_path: str | Path | None = None) -> None:
    print("\n" + "-" * 50)
    print(title)
    print(result)
    if plan_log_path is not None:
        print(f"计划日志: {plan_log_path}")
    print("-" * 50)


def print_cancel_requested() -> None:
    print("\n\n⚠️ 检测到 Ctrl+C，正在停止...", flush=True)


def print_cancelled() -> None:
    print("\n\n⚠️ 已取消", flush=True)


def print_plan_start() -> None:
    print("📋 第一阶段：规划")
    print("🧑‍💼 规划者正在分析任务...\n")


def print_plan_steps(summary: str, *, title: str = "📋 执行计划") -> None:
    print(title)
    print(summary + "\n")


def print_replan() -> None:
    print("📝 已收到补充要求，正在重新规划...\n")


def print_execution_phase() -> None:
    print("⚡ 第二阶段：执行")


def print_parallel_batch(batch_index: int, step_count: int, worker_count: int) -> None:
    print(
        f"⚡ 批次 #{batch_index}：{step_count} 个独立步骤并行执行"
        f"（最多 {worker_count} 个并发 Worker）\n"
    )


def print_step_start(
    worker_name: str,
    step_id: str,
    description: str,
    out: TextIO | None = None,
) -> None:
    _write(f"🛠️ {worker_name} 执行步骤 [{step_id}]: {description}", out)


def print_step_done(step_id: str, out: TextIO | None = None) -> None:
    _write(f"✅ 步骤 [{step_id}] 执行完成", out)


def print_step_cancelled(step_id: str, out: TextIO | None = None) -> None:
    _write(f"❌ 步骤 [{step_id}] 被取消", out)


def print_step_failed(step_id: str, reason: str, out: TextIO | None = None) -> None:
    _write(f"❌ 步骤 [{step_id}] 执行失败：{reason}", out)


def print_step_skipped(step_id: str, description: str) -> None:
    print(f"⏭️ 步骤 [{step_id}] 因前置步骤失败被跳过: {description}")


def print_buffer(content: str) -> None:
    print(content, end="")


def print_approval_request(level: str, tool_name: str, risk: str, arguments: dict) -> None:
    print(f"\n⚠️ {level} {tool_name}")
    print(f"   风险: {risk}")
    print(f"   参数: {arguments}")


def ask_approval_choice() -> str:
    return input("允许执行？[y/n/c]: ").strip().lower()


def ask_approval_advice() -> str:
    return input("补充说明: ").strip()
