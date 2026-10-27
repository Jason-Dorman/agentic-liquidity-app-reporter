"""derive.py: the window fields, the first run, stub statistics, and the data quality part.

DATA-CONTRACTS section 3, R-DRV-9 (data quality), R-DRV-10 (first run), T-33 to T-36.
The finding comparison and tier changes are tested in test_derive_findings.py.
"""

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import FakeClient

import daily_review.derive as derive_module
from daily_review.client import HttpError, Response, Timeout
from daily_review.derive import FIRST_RUN_NOTE, NO_RECORD, derive
from daily_review.pull import NO_FLAGS, DataPack, pull
from daily_review.store import write_json

GOLDEN = Path(__file__).parent / "fixtures" / "derived" / "first-run.json"
WINDOW = {
    "runDate": "2026-10-07",
    "windowStart": "2026-10-06T06:00:00Z",
    "windowEnd": "2026-10-07T06:00:00Z",
    "baseUrlHost": "localhost",
}
NOT_MONITORED = "not_monitored"
COMPUTED = {"findings", "corridorTierChanges"}  # pass 2b
STATISTICS = {  # stubs, by the pass that computes them
    "anomalies": "2c",
    "exceedances": "2c",
    "flowHistory": "2c",
    "settlementHealth": "2d",
    "peg": "2d",
    "depth": "2e",
    "issuerFlows": "2e",
}


def row(name: str, **flags) -> dict:
    """A manifest row for a call that answered 200, with every flag null unless given."""
    base = {"name": name, "endpoint": f"/{name}", "params": {}, "at": "2026-10-07T06:00:01Z"}
    return {**base, "ok": True, "status": 200, "bytes": 2, **NO_FLAGS, **flags}


def failed(name: str, status: int | None, error: str) -> tuple[dict, dict]:
    """A failed call's manifest row and its failure record (DATA-CONTRACTS 1.1 and 1.2)."""
    base = {"name": name, "endpoint": f"/{name}", "params": {}, "at": "2026-10-07T06:00:02Z"}
    manifest_row = {**base, "ok": False, "status": status, "bytes": None, **NO_FLAGS}
    return manifest_row, {**base, "status": status, "error": error}


def make_pack(
    calls: list[dict], failures: dict | None = None, raw: dict | None = None
) -> DataPack:
    manifest = {**WINDOW, "calls": calls}
    return DataPack(raw=raw or {}, failures=failures or {}, manifest=manifest, kinds={})


def golden_pack() -> DataPack:
    """One of each data quality case; the golden first-run derived.json is derived from it."""
    corridors_row, corridors_failure = failed("corridors", 500, '{"error":{"code":"X"}}')
    bsh_row, bsh_failure = failed("bsh", None, "timeout: no answer from /bsh within 30 s")
    calls = [
        row("health"),
        row("bridge_stargate", coverageNotOk=[{"leg": "coverage.fetcher", "value": NOT_MONITORED}]),
        corridors_row,
        row(
            "anomalies_open",
            totalExceedsRows={"total": 5333, "rows": 500},
            rowsAtLimit={"rows": 500, "limit": 500},
        ),
        bsh_row,
        row("liquidity_USDC", truncated=True, truncatedAt=["exceedances.truncated"]),
    ]
    return make_pack(calls, {"corridors": corridors_failure, "bsh": bsh_failure})


# The window fields.


def test_window_fields_come_from_the_manifest_and_history_is_168_hours():
    derived = derive(make_pack([]), None)
    assert derived["runDate"] == "2026-10-07"
    assert derived["windowStart"] == "2026-10-06T06:00:00Z"
    assert derived["windowEnd"] == "2026-10-07T06:00:00Z"
    assert derived["historyStart"] == "2026-09-30T06:00:00Z", "T-34: the 168 hours pulled"


def test_history_start_crosses_a_month_boundary():
    pack = make_pack([])
    pack.manifest["windowEnd"] = "2026-03-03T23:59:59Z"
    assert derive(pack, None)["historyStart"] == "2026-02-24T23:59:59Z"


# The first run and a run with a previous one (R-DRV-10).


def test_first_run_has_no_previous_date_empty_comparison_lists_and_the_note():
    derived = derive(make_pack([]), None)
    assert derived["firstRun"] is True
    assert derived["previousRunDate"] is None
    findings = derived["findings"]
    assert findings["new"] == findings["gone"] == findings["stillOpen"] == findings["changed"] == []
    assert findings["note"] == FIRST_RUN_NOTE
    assert derived["corridorTierChanges"]["changes"] == []
    assert derived["corridorTierChanges"]["note"] == FIRST_RUN_NOTE


def test_a_run_with_a_previous_one_names_its_date_and_drops_the_first_run_note():
    previous = derive(make_pack([]), None)
    previous["runDate"] = "2026-10-05"
    derived = derive(make_pack([]), previous)
    assert derived["firstRun"] is False
    assert derived["previousRunDate"] == "2026-10-05"
    assert derived["findings"]["note"] is None
    assert derived["findings"]["new"] == []


# Stubs until their pass lands (T-35).


def test_every_statistic_is_present_and_says_which_pass_computes_it():
    derived = derive(make_pack([]), None)
    for key, next_pass in STATISTICS.items():
        assert derived[key]["missing"] == f"Not computed yet: pass {next_pass}.", key
    for key in COMPUTED:
        assert derived[key]["missing"] != "Not computed yet: pass 2b.", key


def test_derived_has_exactly_the_contract_keys():
    window = {"runDate", "windowStart", "windowEnd", "historyStart", "previousRunDate", "firstRun"}
    expected = window | COMPUTED | set(STATISTICS) | {"dataQuality"}
    assert set(derive(make_pack([]), None)) == expected


def test_a_stub_never_stands_a_zero_for_a_figure_it_has_not_computed():
    """Rule 7: an absence is null, never 0."""
    assert derive(make_pack([]), None)["anomalies"]["openCount"] is None


def test_the_fixed_notes_from_the_contract_are_set():
    derived = derive(make_pack([]), None)
    assert derived["anomalies"]["window"] == "24h, filtered in code by detectedAt and resolvedAt"
    assert "Never summed" in derived["depth"]["note"]
    assert "carry_in rows are window-head state" in derived["flowHistory"]["note"]
    assert "No gross sum" in derived["issuerFlows"]["note"]


# Data quality (R-DRV-9, T-36).


def test_each_failed_call_is_a_row_with_its_whole_error_in_manifest_order():
    first_row, first = failed("corridors", 500, "<html>\n" + "x" * 2000)
    second_row, second = failed("bsh", None, "timeout: no answer from /bsh within 30 s")
    pack = make_pack([row("health"), first_row, second_row], {"bsh": second, "corridors": first})
    assert derive(pack, None)["dataQuality"]["failedCalls"] == [
        {"name": "corridors", "endpoint": "/corridors", "status": 500, "error": first["error"]},
        {"name": "bsh", "endpoint": "/bsh", "status": None, "error": second["error"]},
    ]


def test_a_flag_the_api_set_true_is_a_truncation_row_naming_its_paths():
    calls = [
        row("bsh", truncated=True, truncatedAt=["truncation.truncated"]),
        row("liquidity_DAI", truncated=True, truncatedAt=["a.truncated", "b.truncated"]),
    ]
    assert derive(make_pack(calls), None)["dataQuality"]["truncations"] == [
        {"name": "bsh", "note": "The response says it was cut: truncation.truncated is true."},
        {
            "name": "liquidity_DAI",
            "note": "The response says it was cut: a.truncated, b.truncated are true.",
        },
    ]


def test_a_page_at_its_limit_is_a_truncation_row():
    calls = [row("exceedances", rowsAtLimit={"rows": 5000, "limit": 5000})]
    assert derive(make_pack(calls), None)["dataQuality"]["truncations"] == [
        {
            "name": "exceedances",
            "note": "Rows served (5000) reached the limit (5000); the page may be cut.",
        }
    ]


def test_a_call_cut_both_ways_gives_one_row_per_cause():
    call = row(
        "bsh",
        truncated=True,
        truncatedAt=["truncation.truncated"],
        rowsAtLimit={"rows": 5000, "limit": 5000},
    )
    rows = derive(make_pack([call]), None)["dataQuality"]["truncations"]
    assert [r["name"] for r in rows] == ["bsh", "bsh"]


@pytest.mark.parametrize(
    "flags",
    [
        {},  # every flag null: the endpoint declares none
        {"truncated": False, "truncatedAt": [], "rowsAtLimit": False},
    ],
)
def test_a_call_not_cut_gives_no_truncation_row(flags):
    assert derive(make_pack([row("corridors", **flags)]), None)["dataQuality"]["truncations"] == []


def test_each_coverage_leg_not_ok_is_a_row_and_an_absent_leg_stays_null():
    legs = [
        {"leg": "coverage.fetcher", "value": "not_monitored"},
        {"leg": "coverage.legs.fits", "value": None},
    ]
    calls = [row("flow_chains", coverageNotOk=[]), row("liquidity_USDe", coverageNotOk=legs)]
    assert derive(make_pack(calls), None)["dataQuality"]["coverageFailures"] == [
        {"name": "liquidity_USDe", "leg": "coverage.fetcher", "state": "not_monitored"},
        {"name": "liquidity_USDe", "leg": "coverage.legs.fits", "state": None},
    ]


def test_a_total_above_the_rows_is_a_partial_total_row():
    calls = [
        row("anomalies_open", totalExceedsRows={"total": 5333, "rows": 500}),
        row("corridors", totalExceedsRows=False),
        row("health"),
    ]
    assert derive(make_pack(calls), None)["dataQuality"]["partialTotals"] == [
        {"name": "anomalies_open", "total": 5333, "rows": 500}
    ]


def test_a_failed_row_without_its_record_is_still_a_failed_call():
    """T-39 (Q41): a loaded pack may lack a record; the failure is never dropped (rule 11)."""
    manifest_row, _ = failed("bsh", None, "unused")
    assert derive(make_pack([manifest_row]), None)["dataQuality"]["failedCalls"] == [
        {"name": "bsh", "endpoint": "/bsh", "status": None, "error": NO_RECORD}
    ]


def test_a_record_without_a_manifest_row_follows_the_manifest_rows_by_name():
    """T-39 (Q41)."""
    first_row, first = failed("corridors", 500, "boom")
    _, orphan_b = failed("spread_latest", 502, "bad gateway")
    _, orphan_a = failed("attestations", None, "timeout: x")
    failures = {"spread_latest": orphan_b, "corridors": first, "attestations": orphan_a}
    rows = derive(make_pack([first_row], failures), None)["dataQuality"]["failedCalls"]
    assert [r["name"] for r in rows] == ["corridors", "attestations", "spread_latest"]
    assert rows[2]["error"] == "bad gateway", "the record's own fields are kept"


@pytest.mark.parametrize(
    "body",
    [b"<html>proxy error</html>", b"[1, 2]", b"", b"\xff\xfe{", b"[" * 100_000, b'"text"'],
)
def test_a_2xx_body_that_is_not_a_json_object_is_a_failed_call(body):
    """T-39 (Q42): a 200 nobody can read is a failure, not a clean answer (rule 11)."""
    raw = {"health": b"{}", "bridge_across": body}
    pack = make_pack([row("health"), row("bridge_across")], raw=raw)
    assert derive(pack, None)["dataQuality"]["failedCalls"] == [
        {
            "name": "bridge_across",
            "endpoint": "/bridge_across",
            "status": 200,
            "error": "answered 200, but the body is not a JSON object; nothing in it can be read",
        }
    ]


def test_failed_calls_keep_manifest_order_across_the_three_kinds():
    recorded_row, recorded = failed("flow_chains", 503, "busy")
    unrecorded_row, _ = failed("corridors", 500, "unused")
    calls = [row("health"), unrecorded_row, row("bsh"), recorded_row]
    pack = make_pack(calls, {"flow_chains": recorded}, raw={"health": b"{}", "bsh": b"oops"})
    rows = derive(pack, None)["dataQuality"]["failedCalls"]
    assert [(r["name"], r["status"]) for r in rows] == [
        ("corridors", 500),
        ("bsh", 200),
        ("flow_chains", 503),
    ]


def test_a_clean_pull_has_empty_data_quality_lists():
    quality = derive(make_pack([row("health"), row("corridors")]), None)["dataQuality"]
    assert quality == {
        "failedCalls": [],
        "truncations": [],
        "coverageFailures": [],
        "partialTotals": [],
    }


def test_data_quality_matches_the_manifest_of_a_real_pull():
    """Pass 2a done-when, through pull() with a fake client: a failure, a cut, a partial total."""
    corridors = {"corridors": [{}], "total": 2, "truncation": {"transfers": {"truncated": True}}}
    client = FakeClient(
        [
            (("/bsh", {"hours": 168, "limit": 5000}), Timeout("timeout: no answer from /bsh")),
            (("/flow/chains", None), HttpError(503, {}, b"busy")),
            (("/corridors", {"limit": 500}), Response(200, {}, json.dumps(corridors).encode())),
        ],
        default=Response(200, {}, b"{}"),
    )
    started = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)
    pack = pull(client, started, "localhost", lambda: started)
    quality = derive(pack, None)["dataQuality"]
    assert [(r["name"], r["status"]) for r in quality["failedCalls"]] == [
        ("flow_chains", 503),
        ("bsh", None),
    ]
    assert quality["truncations"] == [
        {
            "name": "corridors",
            "note": "The response says it was cut: truncation.transfers.truncated is true.",
        }
    ]
    assert quality["partialTotals"] == [{"name": "corridors", "total": 2, "rows": 1}]
    # The empty {} bodies hold none of their declared legs: each absent leg is a row, null.
    legs = [
        (call["name"], leg["leg"], leg["value"])
        for call in pack.manifest["calls"]
        for leg in call["coverageNotOk"] or []
    ]
    assert [(r["name"], r["leg"], r["state"]) for r in quality["coverageFailures"]] == legs
    assert ("bridge_stargate", "coverage.fetcher", None) in legs
    assert ("liquidity_USDT", "coverage.legs.*", None) in legs


# The written file and the module's boundaries.


def test_first_run_derived_json_matches_the_golden_file_with_sorted_keys(tmp_path):
    """TESTING section 5: derived/first-run.json is the expected output for golden_pack()."""
    out = tmp_path / "derived.json"
    write_json(out, derive(golden_pack(), None))
    assert out.read_text("utf-8") == GOLDEN.read_text("utf-8")
    keys = list(json.loads(GOLDEN.read_text("utf-8")))
    assert keys == sorted(keys)


def test_derive_imports_nothing_from_the_package():
    """ARCHITECTURE section 3: derive is pure and depends on no other module (T-33)."""
    tree = ast.parse(Path(derive_module.__file__).read_text("utf-8"))
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
    assert not [name for name in imported if name.startswith("daily_review")]
