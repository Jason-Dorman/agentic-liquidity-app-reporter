"""cli.py: the commands parse; pull-only runs health, pull and save, and maps them to exit codes."""

import json
import logging
import re
import time
from datetime import UTC, datetime

import httpx
import pytest
from fakes import FakeClient

from daily_review.cli import Wiring, main
from daily_review.client import Client, HttpError, Response, Timeout, TunnelDown, Unreachable
from daily_review.config import Settings, load_settings
from daily_review.pull import CATALOGUE, HEALTH_PATH
from daily_review.store import pack_paths

# vendor/API-SPEC.md, section "GET /api/health", Example (the three T-19 fields).
HEALTH_BODY = json.dumps(
    {"status": "operational", "corridorsMonitored": 47, "updatedAt": "2026-02-21T14:35:00Z"}
).encode()
STARTED = datetime(2026, 10, 7, 6, 0, 0, tzinfo=UTC)
NAMES = [endpoint.name for endpoint in CATALOGUE]


def ok(body: bytes = b"{}") -> Response:
    return Response(status=200, headers={}, body=body)


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["run", "--date", "2026-10-07"],
        ["render", "reports/2026-10-07.json"],
    ],
)
def test_commands_not_built_yet_parse_and_exit_zero(argv):
    """R-RUN-6, R-RUN-7: run, run --date, render. Their bodies land in passes 3a and 3b."""
    assert main(argv) == 0


def test_help_lists_three_commands_and_the_date_option(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    for word in ["run", "pull-only", "render", "--date"]:
        assert word in out


@pytest.mark.parametrize("bad", ["2026-13-01", "07-10-2026", "20261007", "2026-1-7", "today"])
def test_bad_date_is_a_usage_error_with_exit_one(bad, capsys):
    """T-09 keeps exit 2 for "API unreachable", so usage errors exit 1 (T-23)."""
    with pytest.raises(SystemExit) as caught:
        main(["run", "--date", bad])
    assert caught.value.code == 1
    assert "--date" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [[], ["unknown"], ["render"], ["pull-only", "--date", "2026-10-07"]]
)
def test_other_usage_errors_exit_one(argv):
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 1


# pull-only: the health check (pass 1a), then the pull and the save (pass 1b).


def wiring(result, environ=None, rest=None) -> tuple[Wiring, FakeClient]:
    """The health check answers `result`; every other call answers `rest`, by default {}."""
    client = FakeClient({(HEALTH_PATH, None): result}, default=rest or ok())
    built = Wiring(
        load_settings=lambda: load_settings(environ or {}),
        make_client=lambda settings: client,
        now=lambda: STARTED,
    )
    return built, client


@pytest.fixture
def empty_cwd(tmp_path, monkeypatch):
    """pull-only runs here, so a test can see that nothing was written."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def info_logs(caplog):
    caplog.set_level(logging.INFO)
    return caplog


def test_pull_only_reachable_logs_the_three_health_fields_and_exits_zero(empty_cwd, caplog):
    """R-RUN-8, T-19: the log shows which deployment answered."""
    built, client = wiring(Response(status=200, headers={}, body=HEALTH_BODY))
    assert main(["pull-only"], built) == 0
    assert "status=operational" in caplog.text
    assert "corridorsMonitored=47" in caplog.text
    assert "updatedAt=2026-02-21T14:35:00Z" in caplog.text
    paths = [path for path, _, _ in client.calls]
    assert paths[0] == "/health", "the health check comes before the pull"
    assert paths[1:] == [endpoint.path for endpoint in CATALOGUE]


def test_pull_only_needs_no_api_key(empty_cwd):
    """Q14: only run needs ANTHROPIC_API_KEY."""
    built, _ = wiring(Response(status=200, headers={}, body=HEALTH_BODY), environ={})
    assert main(["pull-only"], built) == 0


def test_pull_only_builds_its_client_from_the_base_url_setting(empty_cwd):
    seen = []
    client = FakeClient({(HEALTH_PATH, None): ok(HEALTH_BODY)}, default=ok())
    url = "http://localhost:3301/corridor-scout/api"
    built = Wiring(
        load_settings=lambda: load_settings({"BLOCKFORD_API_BASE_URL": url}),
        make_client=lambda settings: seen.append(settings.blockford_api_base_url) or client,
    )
    main(["pull-only"], built)
    assert seen == [url]


def test_connection_refused_exits_two_says_tunnel_down_and_writes_nothing(empty_cwd, caplog):
    """R-RUN-4, T-18: never read as "no data"."""
    built, _ = wiring(TunnelDown("tunnel down: connection refused at localhost:3300"))
    assert main(["pull-only"], built) == 2
    assert "tunnel down" in caplog.text
    assert "RUNBOOK section 1.1" in caplog.text
    assert "no data" not in caplog.text
    assert list(empty_cwd.iterdir()) == []


def test_http_500_exits_two_prints_the_status_and_writes_nothing(empty_cwd, caplog):
    body = b'{"error":{"code":"INTERNAL_ERROR"}}'
    built, _ = wiring(HttpError(status=500, headers={}, body=body))
    assert main(["pull-only"], built) == 2
    assert "HTTP 500" in caplog.text
    assert "tunnel down" not in caplog.text
    assert "RUNBOOK section 1.1" not in caplog.text
    assert list(empty_cwd.iterdir()) == []


@pytest.mark.parametrize(
    "failure",
    [
        Timeout("timeout: no answer from /health within 30 s"),
        Unreachable("unreachable: Name or service not known"),
        Response(status=200, headers={}, body=b"<html>not the API</html>"),
    ],
)
def test_other_health_failures_exit_two_and_write_nothing(failure, empty_cwd, caplog):
    """T-26, T-27: timeout, other transport errors, and a 200 that is not a JSON object."""
    built, _ = wiring(failure)
    assert main(["pull-only"], built) == 2
    assert "health check failed" in caplog.text
    assert "RUNBOOK section 1.1" not in caplog.text, "the tunnel hint is for tunnel down only"
    assert list(empty_cwd.iterdir()) == []


def test_a_bad_setting_exits_one_names_it_and_makes_no_call(empty_cwd, caplog):
    """R-CFG-2, T-09: stop before any call."""
    made = []
    built = Wiring(
        load_settings=lambda: load_settings({"MAX_TOOL_CALLS": "0"}),
        make_client=lambda settings: made.append(settings),
    )
    assert main(["pull-only"], built) == 1
    assert "MAX_TOOL_CALLS" in caplog.text
    assert made == []


def test_the_default_wiring_builds_the_real_client(empty_cwd, monkeypatch):
    """The real Client is built (and refused by the network guard, T-21), not a fake."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    built = Wiring()
    client = built.make_client(built.load_settings())
    with pytest.raises(RuntimeError, match="T-21"):
        client.get(HEALTH_PATH)



def test_httpx_request_lines_stay_out_of_the_log(empty_cwd, caplog):
    """RUNBOOK section 9: the health line comes first; httpx's INFO line holds the full URL."""
    real = Client(
        "http://user:pw@localhost:3300/corridor-scout/api",
        transport_factory=lambda: httpx.MockTransport(
            lambda request: httpx.Response(200, content=HEALTH_BODY)
        ),
    )
    built = Wiring(
        load_settings=lambda: load_settings({}),
        make_client=lambda settings: real,
        now=lambda: STARTED,
    )
    assert main(["pull-only"], built) == 0
    assert {record.name for record in caplog.records} == {"daily_review"}
    assert caplog.records[0].getMessage().startswith("health: ")
    assert "pw@" not in caplog.text


@pytest.fixture
def bare_root_logger(monkeypatch):
    """Call it in the test body: pytest adds its own root handlers only once the test runs.

    Leaves the root logger as a real run finds it, with no handlers. Restored afterwards.
    """
    root = logging.getLogger()

    def strip() -> logging.Logger:
        monkeypatch.setattr(root, "handlers", [])
        monkeypatch.setattr(root, "level", root.level)
        return root

    return strip


def test_a_real_run_logs_the_health_line_to_stderr_with_a_utc_time(
    bare_root_logger, empty_cwd, capsys
):
    """T-28, RUNBOOK section 9: `<UTC time> INFO health: ...` on stderr, nothing on stdout."""
    built, _ = wiring(Response(status=200, headers={}, body=HEALTH_BODY))
    root = bare_root_logger()
    assert main(["pull-only"], built) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    first, *rest = captured.err.splitlines()
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO health: status=operational "
        r"corridorsMonitored=47 updatedAt=2026-02-21T14:35:00Z",
        first,
    )
    assert rest and all(re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO ", x) for x in rest)
    (handler,) = root.handlers
    assert handler.formatter.converter is time.gmtime


def test_a_bad_setting_is_one_timestamped_log_line(bare_root_logger, empty_cwd, capsys):
    """RUNBOOK section 9: the line that names the setting carries the time and level."""
    built = Wiring(load_settings=lambda: load_settings({"MAX_TOOL_CALLS": "0"}))
    bare_root_logger()
    assert main(["pull-only"], built) == 1
    (line,) = capsys.readouterr().err.splitlines()
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ERROR Bad settings", line)
    assert "MAX_TOOL_CALLS" in line


# pull-only after the health check (pass 1b): pull, save, summary, exit code (T-31).


def saved(root):
    return pack_paths(root, STARTED.date())


def test_pull_only_saves_the_pack_under_the_run_date_and_exits_zero(empty_cwd, caplog):
    built, _ = wiring(ok(HEALTH_BODY))
    assert main(["pull-only"], built) == 0
    paths = saved(empty_cwd)
    assert sorted(p.stem for p in paths.raw.iterdir()) == sorted(NAMES)
    manifest = json.loads(paths.manifest.read_text("utf-8"))
    assert [call["name"] for call in manifest["calls"]] == NAMES
    assert manifest["windowEnd"] == "2026-10-07T06:00:00Z"
    assert manifest["baseUrlHost"] == "localhost"
    assert not paths.failures.exists()
    assert "pull: 23 calls, 23 ok, 0 failed" in caplog.text
    assert str(paths.root) in caplog.text


def test_the_health_body_in_the_pack_is_the_pulls_own_bytes(empty_cwd):
    """The catalogue's health row is a call of its own; its body is saved as received."""
    built, _ = wiring(ok(HEALTH_BODY))
    main(["pull-only"], built)
    assert saved(empty_cwd).raw_file("health").read_bytes() == HEALTH_BODY


def test_an_http_error_mid_pull_is_recorded_logged_and_exits_zero(empty_cwd, caplog):
    """Spec section 11, T-31: one endpoint failing does not stop the run.

    A long error page with newlines is kept whole in its failure record (DATA-CONTRACTS 1.1)
    and shown in the log as one line cut to 300 characters (RUNBOOK section 9).
    """
    page = "<html>\n  <body>\n    " + "x" * 1000 + "\n  </body>\n</html>\n"
    client = FakeClient(
        [
            ((HEALTH_PATH, None), ok(HEALTH_BODY)),
            (("/bsh", {"hours": 168, "limit": 5000}), HttpError(500, {}, page.encode())),
        ],
        default=ok(),
    )
    built = Wiring(
        load_settings=lambda: load_settings({}),
        make_client=lambda settings: client,
        now=lambda: STARTED,
    )
    assert main(["pull-only"], built) == 0
    record = json.loads(saved(empty_cwd).failure_file("bsh").read_text("utf-8"))
    assert record["status"] == 500
    assert record["error"] == page, "kept whole on disk, newlines and all"
    (warning,) = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warning == "pull: bsh failed: " + ("<html> <body> " + "x" * 1000)[:300]
    assert "\n" not in warning, "one log line per failed call"
    assert "pull: 23 calls, 22 ok, 1 failed (HTTP error 1)" in caplog.text
    assert "RUNBOOK section 1.1" not in caplog.text


def test_a_tunnel_that_closes_mid_pull_saves_the_pack_and_exits_two(empty_cwd, caplog):
    """T-31: the pack is kept, with a failure record per name, and the tunnel hint is shown."""
    down = TunnelDown("tunnel down: connection refused at localhost:3300")
    built, _ = wiring(ok(HEALTH_BODY), rest=down)
    assert main(["pull-only"], built) == 2
    paths = saved(empty_cwd)
    pulled = [name for name in NAMES if name != "health"]  # /health still answers here
    assert sorted(p.stem for p in paths.failures.iterdir()) == sorted(pulled)
    assert [p.stem for p in paths.raw.iterdir()] == ["health"]
    assert paths.manifest.exists()
    assert "tunnel down during the pull" in caplog.text
    assert "RUNBOOK section 1.1" in caplog.text
    assert "pull: 23 calls, 1 ok, 22 failed (tunnel down 22)" in caplog.text


@pytest.mark.parametrize("failure", [Timeout("timeout: x"), Unreachable("unreachable: x")])
def test_timeouts_and_unreachable_mid_pull_exit_zero(failure, empty_cwd):
    """T-31: only tunnel down mid-pull exits 2."""
    built, _ = wiring(ok(HEALTH_BODY), rest=failure)
    assert main(["pull-only"], built) == 0


def test_a_second_pull_on_the_same_date_replaces_the_first(empty_cwd):
    """T-30: nothing from the earlier pull is left beside the new one."""
    built, _ = wiring(ok(HEALTH_BODY))
    main(["pull-only"], built)
    down = TunnelDown("tunnel down: connection refused at localhost:3300")
    built, _ = wiring(ok(HEALTH_BODY), rest=down)
    main(["pull-only"], built)
    assert [p.stem for p in saved(empty_cwd).raw.iterdir()] == ["health"]


def test_the_pack_goes_under_the_root_the_wiring_names(tmp_path, empty_cwd):
    """T-28: the root is passed in, never read from a setting."""
    root = tmp_path / "elsewhere"
    built, _ = wiring(ok(HEALTH_BODY))
    built = Wiring(
        load_settings=built.load_settings,
        make_client=built.make_client,
        now=built.now,
        root=lambda: root,
    )
    assert main(["pull-only"], built) == 0
    assert saved(root).manifest.exists()
    assert not (empty_cwd / "data").exists()
