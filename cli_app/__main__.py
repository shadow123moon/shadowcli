import argparse
import sys

from .runner import repl, run_tui_mode


def main() -> int:
    parser = argparse.ArgumentParser(description="PaiCLI - Python Agent CLI")
    parser.add_argument("--tui", action="store_true", help="启动 Textual TUI 界面")
    parser.add_argument("--repl", action="store_true", help="启动标准 REPL 界面（默认）")
    args = parser.parse_args()

    if args.tui:
        return run_tui_mode()
    return repl()


if __name__ == "__main__":
    sys.exit(main())
