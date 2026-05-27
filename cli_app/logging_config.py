import logging
import os
from pathlib import Path


_CONSOLE_HANDLER_ATTR = "_shadowcli_console_handler"
_DEBUG_HANDLER_ATTR = "_shadowcli_debug_handler"
DEFAULT_DEBUG_LOG_PATH = Path("logs/debug/debug.log")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def configure_logging(debug_log_path: str | Path | None = None) -> None:
    level_name = os.getenv("PAICLI_LOG_LEVEL", "WARNING").upper()
    console_level = getattr(logging, level_name, logging.WARNING)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    console_handler = _find_handler(root_logger, _CONSOLE_HANDLER_ATTR)
    if console_handler is None:
        console_handler = logging.StreamHandler()
        setattr(console_handler, _CONSOLE_HANDLER_ATTR, True)
        root_logger.addHandler(console_handler)

    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) or getattr(handler, _DEBUG_HANDLER_ATTR, False):
            continue
        handler.setLevel(console_level)
        handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))

    debug_target = _resolve_debug_log_path(debug_log_path)
    if debug_target is not None:
        _install_debug_file_handler(root_logger, debug_target)


def _find_handler(logger: logging.Logger, attr_name: str) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, attr_name, False):
            return handler
    return None


def _resolve_debug_log_path(debug_log_path: str | Path | None) -> Path | None:
    if debug_log_path is not None:
        return Path(debug_log_path)

    env_value = os.getenv("PAICLI_DEBUG_LOG")
    if not env_value:
        return None
    if env_value.lower() in {"1", "true", "yes", "on"}:
        return DEFAULT_DEBUG_LOG_PATH
    return Path(env_value)


def _install_debug_file_handler(root_logger: logging.Logger, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _find_handler(root_logger, _DEBUG_HANDLER_ATTR)
    if existing is not None:
        root_logger.removeHandler(existing)
        existing.close()

    handler = logging.FileHandler(path, encoding="utf-8")
    setattr(handler, _DEBUG_HANDLER_ATTR, True)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(handler)
