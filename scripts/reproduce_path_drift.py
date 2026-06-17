from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm import Message
from llm.client import chat_stream


DEFAULT_TARGET_ROOT = (
    r"C:\Users\shadowmoon\Downloads\Compressed\ClaudeCodeRev-master"
    r"\ClaudeCodeRev-master"
)
DEFAULT_DRIFT_FRAGMENT = r"ClaudeCode-master\ClaudeCode-master"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "列出目录内容。path 必须是已经确认的真实路径。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取文件内容。path 必须从之前 ls/read 结果中精确复制，不要猜测相似目录名。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe real-model path drift in tool calls.")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--target-root", default=DEFAULT_TARGET_ROOT)
    parser.add_argument("--drift-fragment", default=DEFAULT_DRIFT_FRAGMENT)
    parser.add_argument("--output", default=".runtime/path_drift_trace.jsonl")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("after_tool_results", _messages_after_tool_results(args.target_root)),
        ("followup_user", _messages_followup_user(args.target_root)),
    ]

    total = 0
    drifted = 0
    with output.open("a", encoding="utf-8") as fp:
        for trial in range(1, args.trials + 1):
            for scenario, messages in scenarios:
                total += 1
                record = _run_probe(
                    trial=trial,
                    scenario=scenario,
                    messages=messages,
                    target_root=args.target_root,
                    drift_fragment=args.drift_fragment,
                )
                drifted += 1 if record["drifted"] else 0
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(_format_record(record))

    print(f"\nsummary: {drifted}/{total} drifted")
    print(f"trace: {output}")
    return 0


def _run_probe(
    *,
    trial: int,
    scenario: str,
    messages: list[Message],
    target_root: str,
    drift_fragment: str,
) -> dict:
    content_parts: list[str] = []
    tool_calls: list[dict] = []
    for event in chat_stream(messages, tools=TOOLS):
        if event.type == "content":
            content_parts.append(event.data)
        elif event.type == "tool_call":
            tool_calls.append(event.data)

    parsed_paths = [_path_from_tool_call(call) for call in tool_calls]
    drift_paths = [
        path for path in parsed_paths
        if path and _is_drift_path(path, target_root=target_root, drift_fragment=drift_fragment)
    ]
    return {
        "trial": trial,
        "scenario": scenario,
        "drifted": bool(drift_paths),
        "drift_paths": drift_paths,
        "tool_calls": tool_calls,
        "content_preview": "".join(content_parts)[:500],
    }


def _messages_after_tool_results(target_root: str) -> list[Message]:
    return _seed_messages(target_root)


def _messages_followup_user(target_root: str) -> list[Message]:
    messages = _seed_messages(target_root)
    messages.append(Message(
        role="user",
        content=(
            "继续审查，重点确认 src/utils/sessionStorage.ts 和 src/memdir/memdir.ts 的关系。"
            "如果需要更多上下文，请调用 read。"
        ),
    ))
    return messages


def _seed_messages(target_root: str) -> list[Message]:
    memdir_path = rf"{target_root}\src\memdir"
    session_storage_path = rf"{target_root}\src\utils\sessionStorage.ts"
    memdir_file_path = rf"{target_root}\src\memdir\memdir.ts"
    return [
        Message(
            role="system",
            content=(
                "你是 ShadowCLI 代码审查 agent。你可以调用 ls/read 工具。"
                "工具 path 必须精确使用用户给定项目根，不能改写、缩短或猜测相似目录名。"
            ),
        ),
        Message(
            role="user",
            content=(
                f"请只审核 {target_root} 的 memory/session 相关设计，不要修改文件。"
                "下面是你刚刚已经完成的工具调用转录。现在请继续审查；"
                "如果需要更多上下文，请调用 read。"
                "\n\n"
                f"📁 ls path={memdir_path}\n"
                f"{_memdir_listing()}\n\n"
                f"📄 read path={session_storage_path}\n"
                f"{_session_storage_excerpt(session_storage_path)}\n\n"
                f"📄 read path={memdir_file_path}\n"
                f"{_memdir_excerpt(memdir_file_path)}\n\n"
                "注意：项目根路径必须保持完全一致，不要把 ClaudeCodeRev-master 改成 ClaudeCode-master。"
            ),
        ),
    ]


def _memdir_listing() -> str:
    return "\n".join([
        "memdir.ts  (12.4 KB)",
        "types.ts  (2.1 KB)",
        "index.ts  (0.4 KB)",
        "README.md  (3.6 KB)",
    ])


def _session_storage_excerpt(path: str) -> str:
    return "\n".join([
        f"共 80 行，显示 1-80: {path}",
        "     1| import { join } from 'path'",
        "     2| export function getSessionStoragePath(projectRoot: string): string {",
        "     3|   return join(projectRoot, '.claude', 'sessions')",
        "     4| }",
        "     5| export function loadSession(projectRoot: string, id: string) {",
        "     6|   const sessionPath = join(getSessionStoragePath(projectRoot), `${id}.json`)",
        "     7|   return readJson(sessionPath)",
        "     8| }",
    ])


def _memdir_excerpt(path: str) -> str:
    return "\n".join([
        f"共 120 行，显示 1-120: {path}",
        "     1| export type MemoryScope = 'private' | 'team'",
        "     2| export async function loadMemoryIndex(root: string) {",
        "     3|   return readMarkdown(join(root, 'MEMORY.md'))",
        "     4| }",
        "     5| export async function writeMemoryFile(root: string, name: string, content: string) {",
        "     6|   return writeFile(join(root, name), content)",
        "     7| }",
    ])


def _path_from_tool_call(call: dict) -> str | None:
    try:
        args = json.loads(call.get("arguments") or "{}")
    except json.JSONDecodeError:
        return None
    path = args.get("path")
    return path if isinstance(path, str) else None


def _is_drift_path(path: str, *, target_root: str, drift_fragment: str) -> bool:
    normalized_path = path.replace("/", "\\").lower()
    normalized_root = target_root.replace("/", "\\").lower()
    normalized_drift = drift_fragment.replace("/", "\\").lower()
    if normalized_drift in normalized_path:
        return True
    if _looks_absolute_windows_path(path) and not normalized_path.startswith(normalized_root):
        return True
    return False


def _looks_absolute_windows_path(path: str) -> bool:
    return len(path) >= 3 and path[1:3] == ":\\"


def _format_record(record: dict) -> str:
    status = "DRIFT" if record["drifted"] else "ok"
    calls = [
        f"{call.get('name')}({_path_from_tool_call(call) or '<no path>'})"
        for call in record["tool_calls"]
    ]
    return f"[{status}] trial={record['trial']} scenario={record['scenario']} calls={calls}"


if __name__ == "__main__":
    raise SystemExit(main())
