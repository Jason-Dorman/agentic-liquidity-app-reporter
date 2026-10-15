"""Parse the command, wire the modules, run the steps in order, and map outcomes to exit codes."""

import argparse
import logging
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from daily_review.client import Client, Getter, TunnelDown
from daily_review.config import Settings, SettingsError, settings_from_environment
from daily_review.pull import DataPack, Healthy, check_health, pull
from daily_review.store import pack_paths, save_pack

# Exit codes (T-09).
OK = 0
BAD_SETTING = 1
USAGE_ERROR = 1  # T-09 keeps exit 2 for "API unreachable", so usage errors share exit 1 (T-23).
API_UNREACHABLE = 2

TUNNEL_HINT = "Open the SSM port-forward (RUNBOOK section 1.1) and run again."
_SNIPPET = 300  # characters of a failure's error kept in its log line

log = logging.getLogger("daily_review")


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


def _client_for(settings: Settings) -> Getter:
    return Client(settings.blockford_api_base_url)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Wiring:
    """What main builds from the outside world. Tests pass fakes in its place."""

    load_settings: Callable[[], Settings] = settings_from_environment
    make_client: Callable[[Settings], Getter] = _client_for
    now: Callable[[], datetime] = _utc_now  # UTC (T-16)
    root: Callable[[], Path] = Path.cwd  # the directory that holds data/ (T-28)


def _configure_logging() -> None:
    """Log to stderr with UTC times (T-16). A no-op when the root logger already has a handler."""
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO line holds the full URL


def _health(client: Getter) -> int:
    """Run the health check, log what it found, and give the exit code (T-19, T-27)."""
    health = check_health(client)
    if isinstance(health, Healthy):
        log.info(health.summary)
        return OK
    log.error("health check failed: %s", health.message)
    if isinstance(health, TunnelDown):
        log.error(TUNNEL_HINT)
    return API_UNREACHABLE


def _report_pull(pack: DataPack) -> int:
    """Log each failed call and the summary line; give the exit code (T-31)."""
    for name, record in pack.failures.items():
        log.warning("pull: %s failed: %s", name, " ".join(record["error"].split())[:_SNIPPET])
    log.info(pack.summary)
    if pack.tunnel_down:
        log.error("tunnel down during the pull; the pack is saved with its failure records.")
        log.error(TUNNEL_HINT)
        return API_UNREACHABLE
    return OK


def _pull_only(wiring: Wiring) -> int:
    """Health, pull, save (pass 1b). The derive step lands in pass 2a."""
    started = wiring.now()  # "today" ends here (T-16)
    try:
        settings = wiring.load_settings()
    except SettingsError as error:
        log.error("%s", error)
        return BAD_SETTING
    client = wiring.make_client(settings)
    health = _health(client)
    if health != OK:
        return health
    host = urlsplit(settings.blockford_api_base_url).hostname or ""
    pack = pull(client, started, host, wiring.now)
    paths = pack_paths(wiring.root(), date.fromisoformat(pack.manifest["runDate"]))
    save_pack(paths, pack.raw, pack.failures, pack.manifest)
    log.info("pack saved: %s", paths.root)
    return _report_pull(pack)


def main(argv: Sequence[str] | None = None, wiring: Wiring | None = None) -> int:
    """Entry point for the daily-review command. Returns the exit code."""
    args = build_parser().parse_args(argv)
    _configure_logging()
    if args.command == "pull-only":
        return _pull_only(wiring or Wiring())
    return OK  # run lands in pass 3b, render in 3a and 3b.
