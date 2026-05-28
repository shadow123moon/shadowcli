"""Measure streaming first-chunk vs first-content latency.

This script sends a tiny generic prompt and prints only the timings that matter
for diagnosing API/model first-content delay:

- first_chunk: first SSE chunk received from the server
- first_content: first non-empty content token received
- gap: first_content - first_chunk

It does not use repository prompts, tools, or project context.
"""
from __future__ import annotations

import argparse
import os
import time

from dotenv import load_dotenv
from openai import OpenAI


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--prompt", default="只回复 OK")
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

    client = OpenAI(api_key=api_key, base_url=api_url)
    print(f"model={model}")
    print("run\tfirst_chunk\tfirst_content\tgap\tchunks_before_content\tpreview")

    for index in range(1, args.runs + 1):
        started = time.perf_counter()
        first_chunk = None
        first_content = None
        chunks_before_content = 0
        preview = ""

        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": args.prompt}],
            stream=True,
        )
        for chunk in stream:
            now = time.perf_counter()
            if first_chunk is None:
                first_chunk = now - started

            if first_content is None:
                chunks_before_content += 1

            if chunk.choices:
                content = chunk.choices[0].delta.content or ""
                if content and first_content is None:
                    first_content = now - started
                    preview = content[:30].replace("\n", "\\n")
                    break

        if first_chunk is None or first_content is None:
            print(f"{index}\tNA\tNA\tNA\t{chunks_before_content}\t")
            continue

        gap = first_content - first_chunk
        print(
            f"{index}\t{first_chunk:.3f}s\t{first_content:.3f}s\t"
            f"{gap:.3f}s\t{chunks_before_content}\t{preview}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
