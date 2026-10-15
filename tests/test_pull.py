"""pull.py: the catalogue, the manifest flags, failure records, and the flow_history retry.

R-PULL-1 to R-PULL-6 and R-PULL-8; T-29 to T-32. Bodies are cut down from the vendored spec's
shapes and the first live pull (2026-10-08); each test names the shape it uses.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fakes import FakeClient

from daily_review.client import HttpError, Response, Timeout, TunnelDown, Unreachable
from daily_review.pull import CATALOGUE, Endpoint, pull, read_flags

STARTED = datetime(2026, 10, 7, 6, 0, 0, tzinfo=UTC)
BY_NAME = {endpoint.name: endpoint for endpoint in CATALOGUE}

# DATA-CONTRACTS section 1: the 23 names of spec section 5.
NAMES = [
    "health", "flow_chains", "flow_history", "bridge_across", "bridge_cctp", "bridge_stargate",
    "confidence", "corridors", "anomalies_open", "anomalies_all", "exceedances", "spread_latest",
    "spread_history", "bsh", "depth_latest", "liquidity_USDT", "liquidity_USDC", "liquidity_DAI",
    "liquidity_PYUSD", "liquidity_USDe", "issuer_flows", "attestations", "structural_facts",
]  # fmt: skip


def ok(value) -> Response:
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return Response(status=200, headers={}, body=body)


def ticking_clock():
    """A clock that moves one second per call, so each call's `at` is distinct."""
    moments = (STARTED + timedelta(seconds=n) for n in range(10_000))
    return lambda: next(moments)


def run_pull(results=None, default=None):
    client = FakeClient(
        [((BY_NAME[n].path, BY_NAME[n].params), r) for n, r in (results or {}).items()],
        default=default or ok({}),
    )
    return pull(client, STARTED, "localhost", ticking_clock()), client


def flags(name, body, params="sent"):
    endpoint = BY_NAME[name]
    return read_flags(json.dumps(body).encode(), endpoint, endpoint.params if params else None)


def row(pack, name):
    (found,) = [call for call in pack.manifest["calls"] if call["name"] == name]
    return found


# The catalogue (R-PULL-1).


def test_the_catalogue_has_the_23_names_of_spec_section_5_in_order():
    assert [endpoint.name for endpoint in CATALOGUE] == NAMES


@pytest.mark.parametrize(
    ("name", "path", "params"),
    [
        ("health", "/health", None),
        ("flow_history", "/flow/history", {"hours": 168, "limit": 500}),
        ("bridge_stargate", "/bridges/stargate/health", None),
        ("corridors", "/corridors", {"limit": 500}),
        ("anomalies_open", "/anomalies", {"active": "true", "limit": 500}),
        ("anomalies_all", "/anomalies", {"active": "false", "limit": 500}),
        ("exceedances", "/exceedances", {"hours": 168, "limit": 5000}),
        ("spread_latest", "/spread", {"latest": "true"}),
        ("spread_history", "/spread", {"hours": 168, "limit": 5000}),
        ("bsh", "/bsh", {"hours": 168, "limit": 5000}),
        ("depth_latest", "/depth", {"latest": "true"}),
        ("liquidity_PYUSD", "/stablecoins/PYUSD/liquidity", {"window": "7d"}),
        ("issuer_flows", "/issuer-flows", {"hours": 168, "limit": 5000}),
        ("attestations", "/attestations", None),
        ("structural_facts", "/structural-facts", None),
    ],
)
def test_each_call_uses_the_spec_path_and_params(name, path, params):
    """Spec section 5; flow_history hours and limit from the Q3 ruling (R-PULL-6)."""
    assert (BY_NAME[name].path, BY_NAME[name].params) == (path, params)


def test_impact_estimate_is_not_in_the_pack():
    """R-PULL-5: only the agent's tool may call it."""
    assert not any("impact" in endpoint.path for endpoint in CATALOGUE)


# A pull where every call succeeds.


def test_all_23_succeed_each_called_once_with_its_params():
    pack, client = run_pull()
    assert [(path, params) for path, params, _ in client.calls] == [
        (e.path, e.params) for e in CATALOGUE
    ]
    assert list(pack.raw) == NAMES
    assert pack.failures == {}
    assert [call["name"] for call in pack.manifest["calls"]] == NAMES
    assert all(call["ok"] and call["status"] == 200 for call in pack.manifest["calls"])
    assert not pack.tunnel_down
    assert pack.summary == "pull: 23 calls, 23 ok, 0 failed"


def test_raw_bytes_kept_equal_bytes_received():
    """R-PULL-2: whitespace, key order and odd bytes survive the pull untouched."""
    body = b'{ "z":1,\r\n "a" : [ ] }\n\n'
    pack, _ = run_pull({"bsh": ok(body)})
    assert pack.raw["bsh"] == body
    assert row(pack, "bsh")["bytes"] == len(body)


def test_manifest_window_and_host_follow_data_contracts():
    """T-16: the window is the 24 hours before the run's start. Host only, never the URL."""
    pack, _ = run_pull()
    manifest = pack.manifest
    assert manifest["runDate"] == "2026-10-07"
    assert manifest["windowStart"] == "2026-10-06T06:00:00Z"
    assert manifest["windowEnd"] == "2026-10-07T06:00:00Z"
    assert manifest["baseUrlHost"] == "localhost"
    first, second = manifest["calls"][:2]
    assert (first["at"], second["at"]) == ("2026-10-07T06:00:00Z", "2026-10-07T06:00:01Z")
    assert first["endpoint"] == "/health" and first["params"] == {}


def test_run_date_is_the_utc_date_of_the_start():
    """T-16: all times UTC, even when the clock hands over another zone."""
    late = datetime(2026, 10, 7, 23, 30, tzinfo=UTC).astimezone(timezone(timedelta(hours=-5)))
    pack = pull(FakeClient({}, default=ok({})), late, "localhost", lambda: late)
    assert pack.manifest["runDate"] == "2026-10-07"
    assert pack.manifest["windowEnd"] == "2026-10-07T23:30:00Z"


# Failures (R-PULL-3): a record, and the pull goes on.


def test_one_400_gives_a_failure_record_and_the_others_proceed():
    error = b'{"error":{"code":"VALIDATION_ERROR","message":"hours must be between 1 and 720"}}'
    pack, client = run_pull({"flow_history": HttpError(status=400, headers={}, body=error)})
    assert len(client.calls) == 23
    assert "flow_history" not in pack.raw
    assert pack.failures["flow_history"] == {
        "name": "flow_history",
        "endpoint": "/flow/history",
        "params": {"hours": 168, "limit": 500},
        "at": "2026-10-07T06:00:02Z",
        "status": 400,
        "error": error.decode(),
    }
    assert row(pack, "flow_history") == {
        "name": "flow_history",
        "endpoint": "/flow/history",
        "params": {"hours": 168, "limit": 500},
        "at": "2026-10-07T06:00:02Z",
        "ok": False,
        "status": 400,
        "bytes": None,
        "truncated": None,
        "truncatedAt": None,
        "coverageNotOk": None,
        "totalExceedsRows": None,
        "rowsAtLimit": None,
    }
    assert not pack.tunnel_down
    assert pack.summary == "pull: 23 calls, 22 ok, 1 failed (HTTP error 1)"


def test_a_long_multi_line_http_error_is_kept_whole():
    """DATA-CONTRACTS 1.1: the whole body as text. Not cut, whitespace not collapsed."""
    body = ("<html>\n  <body>\n\t" + "é" * 2000 + "  \r\n  </body>\n</html>\n").encode()
    pack, _ = run_pull({"bsh": HttpError(status=502, headers={}, body=body)})
    assert pack.failures["bsh"]["error"] == body.decode()


def test_an_http_error_with_no_body_records_the_status_line():
    pack, _ = run_pull({"bsh": HttpError(status=502, headers={}, body=b"")})
    assert pack.failures["bsh"]["error"] == "HTTP 502"


def test_a_timeout_has_status_null():
    message = "timeout: no answer from /bsh within 30 s"
    pack, _ = run_pull({"bsh": Timeout(message)})
    assert pack.failures["bsh"]["status"] is None
    assert pack.failures["bsh"]["error"] == message
    assert not pack.tunnel_down


def test_connection_refused_mid_run_is_tunnel_down_and_the_pull_goes_on():
    """T-18: never "no data". Every later name still gets a file or a record."""
    down = TunnelDown("tunnel down: connection refused at localhost:3300")
    names = NAMES[10:]
    pack, client = run_pull({name: down for name in names})
    assert len(client.calls) == 23
    assert all(pack.failures[name]["error"].startswith("tunnel down:") for name in names)
    assert all(pack.failures[name]["status"] is None for name in names)
    assert set(pack.raw) | set(pack.failures) == set(NAMES)
    assert pack.tunnel_down
    assert pack.summary == "pull: 23 calls, 10 ok, 13 failed (tunnel down 13)"


def test_the_summary_counts_failures_by_kind():
    pack, _ = run_pull(
        {
            "bsh": Timeout("timeout: x"),
            "corridors": Unreachable("unreachable: x"),
            "confidence": HttpError(status=500, headers={}, body=b"x"),
            "spread_latest": Timeout("timeout: y"),
        }
    )
    assert pack.summary == (
        "pull: 23 calls, 19 ok, 4 failed (HTTP error 1, timeout 2, unreachable 1)"
    )


# truncated and truncatedAt (R-PULL-4, T-29, T-32).


def test_corridors_truncation_names_the_flag_that_was_true():
    """Live shape 2026-10-08: truncation.transfers hit its cap, poolSnapshots did not."""
    body = {
        "corridors": [],
        "truncation": {
            "transfers": {"truncated": True, "rows": 50000, "cap": 50000, "windowHours": 168},
            "poolSnapshots": {"truncated": False, "rows": 10, "cap": 50000, "windowHours": 168},
        },
    }
    got = flags("corridors", body)
    assert (got["truncated"], got["truncatedAt"]) == (True, ["truncation.transfers.truncated"])


def test_every_flag_false_is_false_with_an_empty_list():
    flag = {"truncated": False}
    body = {"truncation": {"transfers": flag, "poolSnapshots": flag}}
    got = flags("corridors", body)
    assert (got["truncated"], got["truncatedAt"]) == (False, [])


def test_a_null_truncation_block_is_null_not_false():
    """Spec: `truncation: null` = completeness could not be established, NOT truncated:false."""
    got = flags("corridors", {"corridors": [], "truncation": None})
    assert (got["truncated"], got["truncatedAt"]) == (None, None)


def test_one_flag_false_and_one_absent_is_null_not_false():
    """T-32: an absent flag never reads as false."""
    got = flags("corridors", {"truncation": {"transfers": {"truncated": False}}})
    assert (got["truncated"], got["truncatedAt"]) == (None, None)


def test_a_flag_that_is_not_a_boolean_is_not_read_as_false():
    got = flags("flow_history", {"truncated": "false"})
    assert got["truncated"] is None


def test_liquidity_flags_step_through_lists_and_name_each_item():
    """Live shape: depth.history, depth.venueHistory, timelines[], exceedances."""
    body = {
        "coverage": {"legs": {"depth": "ok"}},
        "depth": {"history": {"truncated": False}, "venueHistory": {"truncated": False}},
        "timelines": [{"truncated": False}, {"truncated": True}],
        "exceedances": {"truncated": True},
    }
    got = flags("liquidity_USDC", body)
    assert got["truncated"] is True
    assert got["truncatedAt"] == ["timelines[1].truncated", "exceedances.truncated"]


def test_a_withheld_venue_history_makes_liquidity_truncation_null():
    """Spec: venueHistory is null under a withhold. Absent is not false (T-32)."""
    body = {
        "depth": {"history": {"truncated": False}, "venueHistory": None},
        "timelines": [{"truncated": False}],
        "exceedances": {"truncated": False},
    }
    assert flags("liquidity_USDC", body)["truncated"] is None


def test_an_endpoint_that_declares_no_flag_has_truncated_null():
    """Fields absent from a response give null, not false (R-PULL-4)."""
    got = flags("confidence", {"corridors": [], "updatedAt": "x"})
    assert (got["truncated"], got["truncatedAt"]) == (None, None)


# coverageNotOk.


def test_flow_chains_legs_all_ok_is_an_empty_list():
    """Spec section GET /api/flow/chains: three request-level legs."""
    body = {"coverage": {"flowLeg": "ok", "statusHoldLeg": "ok", "materialityLeg": "ok"}}
    assert flags("flow_chains", body)["coverageNotOk"] == []


def test_a_failed_leg_is_listed_with_its_value():
    body = {"coverage": {"flowLeg": "read_failed", "statusHoldLeg": "ok", "materialityLeg": "ok"}}
    assert flags("flow_chains", body)["coverageNotOk"] == [
        {"leg": "coverage.flowLeg", "value": "read_failed"}
    ]


def test_stargate_not_monitored_is_recorded():
    """Spec section 5: bridge_stargate records that it is not monitored."""
    got = flags("bridge_stargate", {"coverage": {"fetcher": "not_monitored"}})
    assert got["coverageNotOk"] == [{"leg": "coverage.fetcher", "value": "not_monitored"}]


def test_a_declared_leg_absent_from_the_body_is_listed_as_null():
    """T-29: never read as ok."""
    body = {"coverage": {"flowLeg": "ok", "materialityLeg": "ok"}}
    assert flags("flow_chains", body)["coverageNotOk"] == [
        {"leg": "coverage.statusHoldLeg", "value": None}
    ]


def test_every_key_under_liquidity_coverage_legs_is_a_leg():
    """T-32: the live body had six legs, `fits` among them; a new leg needs no code change."""
    legs = {"depth": "ok", "metrics": "ok", "spread": "ok", "profile": "ok", "exceedances": "ok"}
    body = {"coverage": {"legs": {**legs, "fits": "read_failed", "later": "read_failed"}}}
    assert flags("liquidity_DAI", body)["coverageNotOk"] == [
        {"leg": "coverage.legs.fits", "value": "read_failed"},
        {"leg": "coverage.legs.later", "value": "read_failed"},
    ]


@pytest.mark.parametrize("legs", ["absent", None, "ok", ["ok"]])
def test_a_legs_value_that_is_not_an_object_is_listed_as_null(legs):
    """T-29: absent, null, a string or a list is no reading of any leg, so never `[]`."""
    coverage = {} if legs == "absent" else {"legs": legs}
    assert flags("liquidity_DAI", {"coverage": coverage})["coverageNotOk"] == [
        {"leg": "coverage.legs.*", "value": None}
    ]


@pytest.mark.parametrize("name", ["depth_latest", "attestations", "bsh", "confidence"])
def test_coverage_blocks_that_are_not_legs_are_not_read(name):
    """T-29: depth's composition and attestations' per-issuer list are not legs."""
    body = {"coverage": {"version": "v2", "note": "partial"}, "attestations": []}
    assert flags(name, body)["coverageNotOk"] is None


# totalExceedsRows.


def test_open_anomalies_beyond_the_page_record_total_and_rows():
    """Live 2026-10-08: total 5332 against a 500-row page."""
    body = {"anomalies": [{}] * 500, "total": 5332, "limit": 500, "offset": 0}
    assert flags("anomalies_open", body)["totalExceedsRows"] == {"total": 5332, "rows": 500}


def test_total_equal_to_rows_is_false():
    """Spec example, GET /api/corridors: total 15, 15 rows would be complete."""
    assert flags("corridors", {"corridors": [{}] * 15, "total": 15})["totalExceedsRows"] is False


@pytest.mark.parametrize(
    "body", [{"corridors": []}, {"corridors": [], "total": None}, {"total": 3}]
)
def test_no_total_or_no_rows_is_null(body):
    assert flags("corridors", body)["totalExceedsRows"] is None


# rowsAtLimit (R-PULL-8).


@pytest.mark.parametrize(
    ("name", "key"),
    [("spread_history", "series"), ("bsh", "series"), ("issuer_flows", "series"),
     ("exceedances", "exceedances")],
)  # fmt: skip
def test_a_page_whose_rows_equal_the_sent_limit_is_recorded(name, key):
    """Live 2026-10-08: each of these four served exactly 5000 rows."""
    assert flags(name, {key: [{}] * 5000})["rowsAtLimit"] == {"rows": 5000, "limit": 5000}


def test_fewer_rows_than_the_limit_is_false():
    assert flags("spread_history", {"series": [{}] * 10})["rowsAtLimit"] is False


def test_the_echoed_limit_is_used_when_none_was_sent():
    """T-32: attestations and structural_facts use a server default of 100."""
    body = {"records": [{}] * 100, "count": 100, "limit": 100}
    assert flags("structural_facts", body)["rowsAtLimit"] == {"rows": 100, "limit": 100}
    assert flags("attestations", {"attestations": [], "limit": 100})["rowsAtLimit"] is False


def test_flow_history_has_no_rows_check():
    """T-32: carry-in rows do not count against limit (Q3); its own flag says when it is cut."""
    body = {"transitions": [{}] * 506, "limit": 500, "truncated": False}
    assert flags("flow_history", body)["rowsAtLimit"] is None


@pytest.mark.parametrize("name", ["spread_latest", "depth_latest", "health"])
def test_an_endpoint_with_no_limit_has_rows_at_limit_null(name):
    assert flags(name, {"series": [{}] * 3, "count": 3})["rowsAtLimit"] is None


def test_rows_that_are_not_a_list_are_null():
    assert flags("bsh", {"series": None})["rowsAtLimit"] is None


# Bodies that are not a JSON object.


@pytest.mark.parametrize("body", [b"<html>", b"[1]", b"", b"[" * 200_000])
def test_a_200_that_is_not_a_json_object_is_kept_with_null_flags(body):
    """Raw is kept as received; no flag can be read from it, so each is null, never false."""
    pack, _ = run_pull({"corridors": ok(body)})
    assert pack.raw["corridors"] == body
    call = row(pack, "corridors")
    assert call["ok"] is True
    for name in ("truncated", "truncatedAt", "coverageNotOk", "totalExceedsRows", "rowsAtLimit"):
        assert call[name] is None


# The flow_history re-call (R-PULL-6, Q3).

FLOW = BY_NAME["flow_history"]
RETRY = (FLOW.path, {"hours": 168, "limit": 5000})


def flow_pull(first, retry=None):
    results = [((FLOW.path, FLOW.params), first)]
    if retry is not None:
        results.append((RETRY, retry))
    client = FakeClient(results, default=ok({}))
    return pull(client, STARTED, "localhost", ticking_clock()), client


def test_truncated_flow_history_is_re_called_once_with_limit_5000():
    first, second = b'{"truncated": true, "transitions": []}', b'{"truncated": false}'
    pack, client = flow_pull(ok(first), ok(second))
    flow_calls = [(path, params) for path, params, _ in client.calls if path == FLOW.path]
    assert flow_calls == [(FLOW.path, FLOW.params), RETRY]
    assert pack.raw["flow_history"] == first
    assert pack.raw["flow_history.retry"] == second
    names = [call["name"] for call in pack.manifest["calls"]]
    assert len(names) == 24
    assert names[names.index("flow_history") + 1] == "flow_history.retry"
    retry = row(pack, "flow_history.retry")
    assert retry["params"] == {"hours": 168, "limit": 5000}
    assert retry["truncated"] is False


def test_a_retry_that_is_still_truncated_is_not_called_again():
    body = b'{"truncated": true}'
    pack, client = flow_pull(ok(body), ok(body))
    assert sum(1 for path, _, _ in client.calls if path == FLOW.path) == 2
    assert row(pack, "flow_history.retry")["truncated"] is True


@pytest.mark.parametrize("first", [ok({"truncated": False}), ok({}), Timeout("timeout: x")])
def test_no_re_call_unless_the_first_says_truncated_true(first):
    pack, client = flow_pull(first)
    assert sum(1 for path, _, _ in client.calls if path == FLOW.path) == 1
    assert "flow_history.retry" not in pack.raw
    assert len(pack.manifest["calls"]) == 23


def test_a_failed_retry_has_its_own_failure_record():
    pack, _ = flow_pull(ok({"truncated": True}), HttpError(status=400, headers={}, body=b"no"))
    record = pack.failures["flow_history.retry"]
    assert (record["status"], record["params"]) == (400, {"hours": 168, "limit": 5000})
    assert "flow_history" in pack.raw


def test_only_an_endpoint_that_declares_a_retry_limit_is_re_called():
    """Corridors truncated is recorded, never re-called: only flow_history has a retry limit."""
    corridors = {"truncation": {"transfers": {"truncated": True}}}
    pack, client = run_pull({"corridors": ok(corridors)})
    assert len(client.calls) == 23
    assert row(pack, "corridors")["truncated"] is True


def test_a_one_endpoint_catalogue_can_be_pulled():
    """The catalogue is data: pull walks whatever it is given."""
    endpoint = Endpoint("only", "/only", {"limit": 2}, rows="series")
    client = FakeClient([(("/only", {"limit": 2}), ok({"series": [1, 2]}))])
    pack = pull(client, STARTED, "localhost", ticking_clock(), (endpoint,))
    assert row(pack, "only")["rowsAtLimit"] == {"rows": 2, "limit": 2}
