"""MCP 服务器配置加载"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class McpServerConfig:
    """MCP 服务器配置"""
    command: str
    args: list[str]
    env: dict[str, str]
    disabled: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> McpServerConfig:
        return cls(
            command=data["command"],
            args=data.get("args", []),
            env=data.get("env", {}),
            disabled=data.get("disabled", False),
        )


def load_mcp_config() -> dict[str, McpServerConfig]:
    """从 ~/.paicli/mcp.json 加载配置

    如果配置文件不存在,创建默认配置(filesystem server 默认禁用)
    """
    config_path = Path.home() / ".paicli" / "mcp.json"

    if not config_path.exists():
        # 创建默认配置
        default_config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        str(Path.cwd())
                    ],
                    "disabled": True,  # 默认禁用,让用户手动启用
                    "env": {}
                }
            }
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(default_config, indent=2, ensure_ascii=False))
        return {}

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return {
            name: McpServerConfig.from_dict(cfg)
            for name, cfg in data.get("mcpServers", {}).items()
        }
    except Exception as e:
        raise RuntimeError(f"Failed to load MCP config from {config_path}: {e}")
