import logging
import os


def configure_logging() -> None:
    level_name = os.getenv("PAICLI_LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            continue
        handler.setLevel(console_level)
        handler.setFormatter(formatter)
