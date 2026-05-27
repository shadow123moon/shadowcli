import logging
import re
from datetime import datetime
from pathlib import Path

from .constants import DEFAULT_PLAN_LOG_DIR, PLAN_LOG_FILENAME_LIMIT
from .logging_config import LOG_FORMAT

log = logging.getLogger(__name__)
NOISY_PLAN_LOGGER_PREFIXES = ("openai", "httpx", "httpcore", "urllib3")


def build_plan_log_path(task: str, log_dir: Path | None = None) -> Path:
    safe_task = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", task.strip(), flags=re.UNICODE)
    safe_task = safe_task.strip("._")[:PLAN_LOG_FILENAME_LIMIT] or "plan"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return (log_dir or DEFAULT_PLAN_LOG_DIR) / f"{timestamp}_{safe_task}.log"


class PlanLogSession:
    def __init__(self, task: str, log_dir: Path | None = None):
        self.task = task
        self.path = build_plan_log_path(task, log_dir)
        self._handler: logging.FileHandler | None = None
        self._root_logger = logging.getLogger()
        self._previous_root_level: int | None = None

    def __enter__(self) -> "PlanLogSession":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._previous_root_level = self._root_logger.level
        self._root_logger.setLevel(logging.DEBUG)

        handler = logging.FileHandler(self.path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.addFilter(_PlanLogFilter())
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        self._root_logger.addHandler(handler)
        self._handler = handler

        log.info("========== PLAN START ==========")
        log.info("[计划日志] 开始记录本次计划，任务：%s", self.task)
        log.info("[计划日志] 日志文件：%s", self.path)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            log.error("[计划日志] 本次计划异常结束：%s", exc)
            log.debug("[计划日志] 异常详情", exc_info=(exc_type, exc, tb))
        else:
            log.info("[计划日志] 本次计划正常结束")
        log.info("========== PLAN END ==========")

        if self._handler is not None:
            self._root_logger.removeHandler(self._handler)
            self._handler.close()
            self._handler = None
        if self._previous_root_level is not None:
            self._root_logger.setLevel(self._previous_root_level)
        return False


class _PlanLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _is_noisy_plan_logger(record.name)


def _is_noisy_plan_logger(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in NOISY_PLAN_LOGGER_PREFIXES
    )
