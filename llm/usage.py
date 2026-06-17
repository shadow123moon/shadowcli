from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def normalize_usage(usage: dict | None) -> TokenUsage:
    if not usage:
        return TokenUsage()

    input_tokens = _int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("prompt_cache_hit_tokens", 0) + usage.get("prompt_cache_miss_tokens", 0)
    )
    output_tokens = _int(usage.get("completion_tokens") or usage.get("output_tokens"))

    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = _int(
        details.get("cached_tokens")
        or usage.get("cached_input_tokens")
        or usage.get("prompt_cache_hit_tokens")
    )
    if input_tokens <= 0 and cached:
        input_tokens = cached + _int(usage.get("prompt_cache_miss_tokens"))

    return TokenUsage(
        input_tokens=max(0, input_tokens),
        cached_input_tokens=max(0, min(cached, input_tokens) if input_tokens else cached),
        output_tokens=max(0, output_tokens),
    )


def usage_to_metadata(usage: dict | None) -> dict[str, int]:
    normalized = normalize_usage(usage)
    if normalized.total_tokens <= 0 and normalized.cached_input_tokens <= 0:
        return {}
    return {
        "input_tokens": normalized.input_tokens,
        "cached_input_tokens": normalized.cached_input_tokens,
        "output_tokens": normalized.output_tokens,
    }


def usage_from_metadata(metadata: dict[str, Any] | None) -> TokenUsage:
    raw = metadata or {}
    return TokenUsage(
        input_tokens=max(0, _int(raw.get("input_tokens"))),
        cached_input_tokens=max(0, _int(raw.get("cached_input_tokens"))),
        output_tokens=max(0, _int(raw.get("output_tokens"))),
    )


def sum_token_usage(usages) -> TokenUsage:
    total = TokenUsage()
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    for usage in usages:
        normalized = usage if isinstance(usage, TokenUsage) else usage_from_metadata(usage)
        input_tokens += normalized.input_tokens
        cached_input_tokens += normalized.cached_input_tokens
        output_tokens += normalized.output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
    )


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
