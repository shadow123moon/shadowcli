"""Debug planner API latency without running workers or tools.

Usage:
    python debug/debug_planner_latency.py
    python debug/debug_planner_latency.py --prompt-mode planner
    python debug/debug_planner_latency.py --raw
    python debug/debug_planner_latency.py --task "plan a tiny read-only analysis"

The script prints timing checkpoints for the planner request:
- dotenv/env setup
- message/body construction
- OpenAI client creation
- stream creation
- first chunk
- first content chunk
- stream completion

It never executes tools and never writes project files.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.client import _message_to_dict
from llm.types import Message


DEFAULT_TASK = "Create a two-step read-only plan for finding the project entrypoint and test command."
SANITIZED_PLANNER_PROMPT = """Return only JSON:
{"summary":"...","steps":[{"id":"step_1","description":"...","type":"ANALYSIS","dependencies":[]}]}
Use dependencies only when a step needs another step's output."""


@dataclass
class Stopwatch:
    started: float
    last: float

    @classmethod
    def start(cls) -> "Stopwatch":
        now = time.perf_counter()
        return cls(started=now, last=now)

    def mark(self, label: str, **extra: Any) -> None:
        now = time.perf_counter()
        delta = now - self.last
        total = now - self.started
        self.last = now
        suffix = ""
        if extra:
            fields = " ".join(f"{key}={value}" for key, value in extra.items())
            suffix = f" {fields}"
        print(f"{label:<24} +{delta:7.3f}s total={total:7.3f}s{suffix}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument(
        "--prompt-mode",
        choices=("sanitized", "planner"),
        default="sanitized",
        help="sanitized avoids sending repository prompt text; planner uses the real PLANNER_PROMPT.",
    )
    parser.add_argument("--raw", action="store_true", help="Also test raw requests streaming.")
    parser.add_argument("--max-print", type=int, default=200)
    args = parser.parse_args()

    watch = Stopwatch.start()
    load_dotenv()
    watch.mark("dotenv")

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
    watch.mark(
        "env",
        api_url=_masked_url(api_url),
        model=model,
    )

    planner_prompt = SANITIZED_PLANNER_PROMPT
    if args.prompt_mode == "planner":
        from multi_agent.sub_agent import PLANNER_PROMPT

        planner_prompt = PLANNER_PROMPT
    messages = [
        Message(role="system", content=planner_prompt),
        Message(role="user", content=f"Please create an execution plan for this task:\n{args.task}"),
    ]
    body = {
        "model": model,
        "messages": [_message_to_dict(message) for message in messages],
        "stream": True,
    }
    prompt_chars = sum(len(message.content or "") for message in messages)
    body_bytes = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    watch.mark("build_body", prompt_chars=prompt_chars, body_bytes=body_bytes)

    _run_openai_stream(api_key, api_url, model, messages, watch, args.max_print)
    if args.raw:
        print("\nraw requests stream")
        _run_raw_stream(api_key, api_url, body, args.max_print)
    return 0


def _run_openai_stream(
    api_key: str,
    api_url: str,
    model: str,
    messages: list[Message],
    watch: Stopwatch,
    max_print: int,
) -> None:
    client = OpenAI(api_key=api_key, base_url=api_url)
    watch.mark("openai_client")

    stream = client.chat.completions.create(
        model=model,
        messages=[_message_to_dict(message) for message in messages],
        stream=True,
    )
    watch.mark("create_stream_return")

    first_chunk_seen = False
    first_content_seen = False
    chunks = 0
    content_parts: list[str] = []
    finish_reason = None

    for chunk in stream:
        chunks += 1
        if not first_chunk_seen:
            first_chunk_seen = True
            watch.mark("first_chunk", chunk_type=type(chunk).__name__)
        if chunk.choices:
            choice = chunk.choices[0]
            finish_reason = choice.finish_reason or finish_reason
            content = choice.delta.content or ""
            if content:
                if not first_content_seen:
                    first_content_seen = True
                    watch.mark("first_content", content_preview=repr(content[:30]))
                content_parts.append(content)

    text = "".join(content_parts)
    watch.mark(
        "stream_done",
        chunks=chunks,
        chars=len(text),
        finish=finish_reason,
        preview=repr(text[:max_print].replace("\n", " ")),
    )


def _run_raw_stream(api_key: str, api_url: str, body: dict[str, Any], max_print: int) -> None:
    url = _chat_completions_url(api_url)
    watch = Stopwatch.start()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=body, stream=True, timeout=(10, 120))
    watch.mark("post_return", status=response.status_code)
    response.raise_for_status()

    first_line_seen = False
    first_content_seen = False
    lines = 0
    content_parts: list[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        lines += 1
        if not first_line_seen:
            first_line_seen = True
            watch.mark("first_sse_line", preview=repr(raw_line[:80]))
        if raw_line.startswith("data: "):
            payload = raw_line[6:]
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = data.get("choices") or []
            if not choices:
                continue
            content = choices[0].get("delta", {}).get("content", "")
            if content:
                if not first_content_seen:
                    first_content_seen = True
                    watch.mark("first_content", content_preview=repr(content[:30]))
                content_parts.append(content)

    text = "".join(content_parts)
    watch.mark(
        "raw_done",
        lines=lines,
        chars=len(text),
        preview=repr(text[:max_print].replace("\n", " ")),
    )


def _chat_completions_url(api_url: str) -> str:
    if api_url.endswith("/chat/completions"):
        return api_url
    return api_url.rstrip("/") + "/chat/completions"


def _masked_url(url: str) -> str:
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/..."


if __name__ == "__main__":
    raise SystemExit(main())
