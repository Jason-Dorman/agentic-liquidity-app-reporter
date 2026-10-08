"""cli.py: the commands parse; pull-only runs the health check and maps it to an exit code."""

import json
import logging
import re
import time

import httpx
import pytest
from fakes import FakeClient

from daily_review.cli import Wiring, main
from daily_review.client import Client, HttpError, Response, Timeout, TunnelDown, Unreachable
from daily_review.config import Settings, load_settings
from daily_review.pull import HEALTH_PATH

# vendor/API-SPEC.md, section "GET /api/health", Example (the three T-19 fields).
HEALTH_BODY = json.dumps(
    {"status": "operational", "corridorsMonitored": 47, "updatedAt": "2026-02-21T14:35:00Z"}
).encode()


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


# pull-only, pass 1a: the health check only (BUILD-PLAN pass 1a task 3).


def wiring(result, environ=None) -> tuple[Wiring, FakeClient]:
    client = FakeClient({(HEALTH_PATH, None): result})
    built = Wiring(
        load_settings=lambda: load_settings(environ or {}),
        make_client=lambda settings: client,
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
    assert [path for path, _, _ in client.calls] == ["/health"]


def test_pull_only_needs_no_api_key(empty_cwd):
    """Q14: only run needs ANTHROPIC_API_KEY."""
    built, _ = wiring(Response(status=200, headers={}, body=HEALTH_BODY), environ={})
    assert main(["pull-only"], built) == 0


def test_pull_only_builds_its_client_from_the_base_url_setting(empty_cwd):
    seen = []
    client = FakeClient({(HEALTH_PATH, None): Response(status=200, headers={}, body=HEALTH_BODY)})
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
    built = Wiring(load_settings=lambda: load_settings({}), make_client=lambda settings: real)
    assert main(["pull-only"], built) == 0
    assert [record.name for record in caplog.records] == ["daily_review"]
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
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO health: status=operational "
        r"corridorsMonitored=47 updatedAt=2026-02-21T14:35:00Z\n",
        captured.err,
    )
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
