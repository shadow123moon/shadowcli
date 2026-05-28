"""Inspect early streaming delta fields for a planner-shaped request.

This is a diagnostic script: it prints timing, delta field names, and tiny
previews for early SSE chunks so we can see whether the provider streams
reasoning before normal content.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SANITIZED_PLANNER_PROMPT = """Return only JSON:
{"summary":"...","steps":[{"id":"step_1","description":"...","type":"ANALYSIS","dependencies":[]}]}
Use dependencies only when a step needs another step's output."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="查看当前项目入口文件是什么，只做只读分析")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--prompt-mode",
        choices=("sanitized", "planner"),
        default="sanitized",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    api_url = os.getenv("API_URL")
    model = os.getenv("MODEL")
    if not api_key or not api_url or not model:
        missing = [
            name
            for name, value in {
                "OPENAI_API_KEY": api_key,
                "API_URL": api_url,
                "MODEL": model,
            }.items()
            if not value
        ]
        raise SystemExit(f"Missing env: {', '.join(missing)}")

    system_prompt = SANITIZED_PLANNER_PROMPT
    if args.prompt_mode == "planner":
        from multi_agent.sub_agent import PLANNER_PROMPT

        system_prompt = PLANNER_PROMPT

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请为以下任务制定执行计划：\n{args.task}"},
    ]

    client = OpenAI(api_key=api_key, base_url=api_url)
    started = time.perf_counter()
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
    )

    first_content = None
    first_reasoning = None
    print(f"model={model}")
    print("idx\ttime\tfields\tcontent\treasoning")
    for idx, chunk in enumerate(stream, 1):
        elapsed = time.perf_counter() - started
        if not chunk.choices:
            print(f"{idx}\t{elapsed:.3f}s\tno_choices\t\t")
            continue

        delta = chunk.choices[0].delta
        data = delta.model_dump(exclude_none=True)
        content = str(data.get("content") or "")
        reasoning = _first_present(
            data,
            "reasoning_content",
            "reasoning",
            "reasoning_text",
            "thinking",
        )
        if content and first_content is None:
            first_content = elapsed
        if reasoning and first_reasoning is None:
            first_reasoning = elapsed

        fields = ",".join(data.keys())
        print(
            f"{idx}\t{elapsed:.3f}s\t{fields}\t{_preview(content)}\t{_preview(reasoning)}",
            flush=True,
        )
        if idx >= args.limit or first_content is not None:
            break

    print(
        "summary\t"
        f"first_reasoning={_format_time(first_reasoning)}\t"
        f"first_content={_format_time(first_content)}"
    )
    return 0


def _first_present(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def _preview(text: str, limit: int = 24) -> str:
    return text[:limit].replace("\n", "\\n").replace("\t", "\\t")


def _format_time(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.3f}s"


if __name__ == "__main__":
    raise SystemExit(main())
