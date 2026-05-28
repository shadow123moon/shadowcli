from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime
from pathlib import Path


def project_key_for(cwd: Path) -> str:
    abs_path = Path(cwd).expanduser().resolve()
    name = _safe_name(abs_path.name or "root")
    hash_source = os.path.normcase(str(abs_path))
    digest = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def new_session_id(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return f"{current.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-")
    return (safe or "root")[:48]
