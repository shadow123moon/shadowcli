from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from llm import ChatResponse, Message, chat

from .registry import SkillDefinition, SkillRegistry


AUTO_SKILLS_ENV = "SHADOWCLI_AUTO_SKILLS"
_ENABLED_VALUES = {"1", "true", "yes", "on"}
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillSelection:
    skill: SkillDefinition | None
    reason: str = ""


class SkillSelector:
    """Pick at most one skill using only lightweight skill metadata."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        chat_fn: Callable[..., ChatResponse] = chat,
    ) -> None:
        self.registry = registry
        self.chat_fn = chat_fn

    def select(self, user_input: str) -> SkillSelection:
        query = user_input.strip()
        if not query:
            return SkillSelection(None)

        candidates = auto_skill_candidates(self.registry.list())
        if not candidates:
            return SkillSelection(None)

        by_reference = {skill_reference(skill): skill for skill in candidates}
        try:
            response = self.chat_fn(
                [
                    Message(role="system", content=_SYSTEM_PROMPT),
                    Message(role="user", content=_build_selection_payload(query, candidates)),
                ],
                tools=None,
            )
        except Exception:
            log.exception("[skills] 自动 skill 选择失败")
            return SkillSelection(None)

        data = _parse_json_object(response.content or "")
        reason = _string_value(data.get("reason"))
        selected_name = _string_value(data.get("skill"))
        if not selected_name:
            return SkillSelection(None, reason)

        selected = by_reference.get(selected_name)
        if selected is None:
            log.warning("[skills] selector returned unknown skill: %s", selected_name)
            return SkillSelection(None, reason)
        return SkillSelection(selected, reason)


def auto_skills_enabled(environ: Mapping[str, str] | None = None) -> bool:
    value = (environ or os.environ).get(AUTO_SKILLS_ENV, "")
    return value.strip().lower() in _ENABLED_VALUES


def auto_skill_candidates(skills: Sequence[SkillDefinition]) -> list[SkillDefinition]:
    best_by_reference: dict[str, tuple[int, int, SkillDefinition]] = {}
    for index, skill in enumerate(skills):
        priority = _auto_skill_source_priority(skill.source)
        if priority is None:
            continue

        reference = skill_reference(skill)
        current = best_by_reference.get(reference)
        candidate = (priority, index, skill)
        if current is None or candidate[:2] < current[:2]:
            best_by_reference[reference] = candidate

    return [
        skill
        for _, _, skill in sorted(best_by_reference.values(), key=lambda item: (item[0], item[1]))
    ]


def _auto_skill_source_priority(source: str) -> int | None:
    if source == "project":
        return 0
    if source.startswith("plugin:"):
        return 1
    if source.startswith("external:"):
        return 2
    if source == "global":
        return 3
    return None


def skill_reference(skill: SkillDefinition) -> str:
    if skill.source.startswith("plugin:"):
        plugin_name = skill.source.removeprefix("plugin:")
        return f"{plugin_name}:{skill.name}"
    return skill.name


_SYSTEM_PROMPT = "\n".join([
    "你是 ShadowCLI 的自动 skill selector。",
    "只根据用户输入和候选 skill metadata 判断是否应自动加载一个 skill。",
    "只有明确匹配时才选择；不确定时返回 null。",
    "最多选择一个 skill。不要调用工具，不要读取 skill body。",
    '只输出 JSON：{"skill": "<name>", "reason": "..."} 或 {"skill": null, "reason": "..."}。',
])


def _build_selection_payload(user_input: str, skills: Sequence[SkillDefinition]) -> str:
    payload = {
        "user_input": user_input,
        "skills": [
            {
                "skill": skill_reference(skill),
                "source": skill.source,
                "description": skill.description,
                "when_to_use": skill.when_to_use,
                "argument_hint": skill.argument_hint,
            }
            for skill in skills
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_json_fence(text.strip())
    parsed = _loads_object(stripped)
    if parsed is not None:
        return parsed

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match is None:
        return {}
    return _loads_object(match.group(0)) or {}


def _strip_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()


def _loads_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
