"""Parse the command, wire the modules, run the steps in order, and map outcomes to exit codes."""

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

USAGE_ERROR = 1  # T-09 keeps exit 2 for "API unreachable", so usage errors share exit 1 (T-23).


class _Parser(argparse.ArgumentParser):
    """argparse with usage errors on exit 1 instead of argparse's default 2."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(USAGE_ERROR, f"{self.prog}: error: {message}\n")


def _run_date(text: str) -> date:
    """A --date value: exactly YYYY-MM-DD and a real calendar date."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date: {error}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="daily-review", description="Blockford Daily Review.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    run = commands.add_parser(
        "run",
        help="full run: health, pull, derive, agent, render, save. "
        "--date YYYY-MM-DD reuses that date's saved pack instead of pulling.",
    )
    run.add_argument(
        "--date",
        type=_run_date,
        metavar="YYYY-MM-DD",
        help="reuse the saved data pack for this date; no pull",
    )
    commands.add_parser("pull-only", help="health, pull, derive, save. No agent.")
    render = commands.add_parser("render", help="re-render a saved report's markdown from its JSON")
    render.add_argument("report", type=Path, help="path to reports/YYYY-MM-DD.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the daily-review command. Returns the exit code."""
    build_parser().parse_args(argv)
    return 0
