import sys

from .runner import repl


def main() -> int:
    """ShadowCLI 入口：启动终端 REPL"""
    return repl()


if __name__ == "__main__":
    sys.exit(main())
