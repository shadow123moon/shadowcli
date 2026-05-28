"""MCP inputSchema 清洗,适配 OpenAI function schema"""
import logging

log = logging.getLogger(__name__)


def sanitize_schema(schema: dict) -> dict:
    """清洗 MCP inputSchema

    问题:
    - MCP 可能有 $ref / anyOf / oneOf
    - description 可能超长(>1000 字符)
    - 可能缺少 type 字段
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    cleaned = schema.copy()

    # 1. 移除不支持的字段
    for key in ["$ref", "$schema", "definitions"]:
        cleaned.pop(key, None)

    # 2. 处理 anyOf / oneOf(简化为第一个)
    if "anyOf" in cleaned:
        log.warning("inputSchema contains 'anyOf', using first option")
        cleaned = cleaned["anyOf"][0] if cleaned["anyOf"] else {}

    if "oneOf" in cleaned:
        log.warning("inputSchema contains 'oneOf', using first option")
        cleaned = cleaned["oneOf"][0] if cleaned["oneOf"] else {}

    # 3. 截断超长 description
    if "description" in cleaned and len(cleaned["description"]) > 500:
        cleaned["description"] = cleaned["description"][:497] + "..."

    # 4. 递归清洗 properties
    if "properties" in cleaned:
        cleaned["properties"] = {
            k: sanitize_schema(v) if isinstance(v, dict) else v
            for k, v in cleaned["properties"].items()
        }

    # 5. 递归清洗 items(数组)
    if "items" in cleaned and isinstance(cleaned["items"], dict):
        cleaned["items"] = sanitize_schema(cleaned["items"])

    return cleaned
