from __future__ import annotations

import json
from pathlib import Path


PLUGIN_STATE_PATH = Path(".agents") / "plugins.json"


class PluginStateStore:
    def __init__(self, root: Path | str, *, path: Path | None = None):
        self.root = Path(root)
        self.path = path or self.root / PLUGIN_STATE_PATH

    def enabled(self) -> set[str]:
        data = self._read()
        enabled = data.get("enabled", [])
        if not isinstance(enabled, list):
            return set()
        return {name for name in enabled if isinstance(name, str) and name.strip()}

    def enable(self, name: str) -> None:
        enabled = self.enabled()
        enabled.add(name)
        self._write(enabled)

    def disable(self, name: str) -> None:
        enabled = self.enabled()
        enabled.discard(name)
        self._write(enabled)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, enabled: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"enabled": sorted(enabled)}
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
