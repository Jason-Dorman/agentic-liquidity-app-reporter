"""derive.py: the finding comparison and corridor tier changes (pass 2b).

R-DRV-1, R-DRV-2, R-DRV-10; T-40 to T-43. Bodies are the spec examples in
tests/fixtures/responses/; each change case is a deep copy with one edit (Q50).
"""

import copy
import json
from pathlib import Path

import pytest

from daily_review.derive import FINDING_SURFACES, FIRST_RUN_NOTE, TIERS_NOT_READ, derive
from daily_review.pull import CATALOGUE, NO_FLAGS, DataPack

FIXTURES = Path(__file__).parent / "fixtures" / "responses"
READ = ("flow_chains", "bridge_across", "confidence", "liquidity_DAI")  # the fixtures held
WINDOW = {
    "runDate": "2026-10-07",
    "windowStart": "2026-10-06T06:00:00Z",
    "windowEnd": "2026-10-07T06:00:00Z",
    "baseUrlHost": "localhost",
}
UPDATED_AT = "2026-08-28T14:35:00Z"  # the confidence example's updatedAt
BASE_ID = "corridor-across_ethereum_base-degraded"


def bodies() -> dict[str, dict]:
    return {name: json.loads((FIXTURES / f"{name}.json").read_text("utf-8")) for name in READ}


def run(found: dict[str, dict | bytes], previous=None, failed=(), run_date="2026-10-07"):
    """derive over the bodies given, with a failure record for each name in `failed`."""
    raw = {n: b if isinstance(b, bytes) else json.dumps(b).encode() for n, b in found.items()}
    calls = [
        {"name": n, "endpoint": f"/{n}", "params": {}, "at": "2026-10-07T06:00:01Z",
         "ok": n not in failed, "status": 200 if n not in failed else 503,
         "bytes": None, **NO_FLAGS}
        for n in [*raw, *failed]
    ]
    failures = {
        n: {"name": n, "endpoint": f"/{n}", "params": {}, "at": "x", "status": 503, "error": "busy"}
        for n in failed
    }
    manifest = {**WINDOW, "runDate": run_date, "calls": calls}
    return derive(DataPack(raw=raw, failures=failures, manifest=manifest, kinds={}), previous)


def first_day() -> dict:
    """A first run over the spec examples, dated the day before."""
    return run(bodies(), run_date="2026-10-06")


def ids(refs: list[dict]) -> list[str]:
    return [ref["id"] for ref in refs]


def corridor(found: dict) -> dict:
    return found["confidence"]["corridors"][0]


# The surfaces and where their findings come from (T-41).


def test_finding_surfaces_are_catalogue_names_in_catalogue_order():
    """derive imports nothing from the package, so this pins its list to pull.CATALOGUE."""
    names = [endpoint.name for endpoint in CATALOGUE]
    assert sorted(FINDING_SURFACES, key=names.index) == list(FINDING_SURFACES)
    assert set(FINDING_SURFACES) <= set(names)
    assert len(FINDING_SURFACES) == 10, "four surfaces: 1 flow, 3 bridges, 1 confidence, 5 assets"


def test_first_run_fills_open_from_every_surface_and_reports_nothing_as_new():
    findings = first_day()["findings"]
    assert findings["new"] == findings["gone"] == findings["stillOpen"] == findings["changed"] == []
    assert findings["note"] == FIRST_RUN_NOTE
    assert findings["missing"] is None
    assert findings["surfaces"] == list(READ)
    assert findings["surfacesMissing"] == [n for n in FINDING_SURFACES if n not in READ]
    assert {name: ids(refs) for name, refs in findings["open"].items()} == {
        "flow_chains": ["flow-base-flight-confirmed", "flow-optimism-not-concluded"],
        "bridge_across": ["bridge-across-constrained"],
        "confidence": [BASE_ID],
        "liquidity_DAI": ["dai-dap10-not-concluded", "dai-dap25-not-concluded",
                          "dai-dap50-below-range"],
    }


def test_a_finding_ref_carries_its_surface_kind_and_severity():
    refs = first_day()["findings"]["open"]["bridge_across"]
    assert refs == [
        {"id": "bridge-across-constrained", "surface": "bridge_across",
         "kind": "settlement_constrained", "severity": "elevated"}
    ]


def test_liquidity_takes_every_band_and_not_the_widest_copy_again():
    """`finding` is byte-identical to the widest `findings[]` entry (T-41)."""
    refs = first_day()["findings"]["open"]["liquidity_DAI"]
    assert [ref["id"] for ref in refs].count("dai-dap50-below-range") == 1


def test_an_absent_kind_or_severity_stays_null():
    """Rule 7: an absence is null, never a guessed value."""
    found = bodies()
    del found["bridge_across"]["finding"]["kind"]
    del found["bridge_across"]["finding"]["severity"]
    ref = run(found)["findings"]["open"]["bridge_across"][0]
    assert ref["kind"] is None and ref["severity"] is None


# The comparison (R-DRV-1, Q7: id equality).


def test_the_same_ids_both_runs_are_still_open():
    findings = run(bodies(), first_day())["findings"]
    assert ids(findings["stillOpen"]) == [ref["id"] for refs in findings["open"].values()
                                          for ref in refs]
    assert findings["new"] == findings["gone"] == findings["changed"] == []
    assert findings["note"] is None


def test_a_new_id_is_new_and_the_old_one_is_gone():
    found = bodies()
    corridor(found)["finding"]["id"] = "corridor-across_ethereum_base-usable"
    findings = run(found, first_day())["findings"]
    assert ids(findings["new"]) == ["corridor-across_ethereum_base-usable"]
    assert ids(findings["gone"]) == [BASE_ID]


def test_a_missing_id_is_gone_with_its_previous_kind_and_severity():
    found = bodies()
    del found["flow_chains"]["chains"][1]
    findings = run(found, first_day())["findings"]
    assert findings["gone"] == [
        {"id": "flow-optimism-not-concluded", "surface": "flow_chains",
         "kind": "not_concluded", "severity": "unknown"}
    ]
    assert findings["new"] == []


def test_a_severity_change_is_in_changed_and_the_id_stays_still_open():
    found = bodies()
    corridor(found)["finding"]["severity"] = "elevated"
    findings = run(found, first_day())["findings"]
    assert findings["changed"] == [
        {"id": BASE_ID, "field": "severity", "from": "notable", "to": "elevated"}
    ]
    assert BASE_ID in ids(findings["stillOpen"])
    assert findings["new"] == findings["gone"] == []


def test_a_kind_change_on_the_same_id_is_in_changed():
    found = bodies()
    found["bridge_across"]["finding"]["kind"] = "settlement_degraded"
    changed = run(found, first_day())["findings"]["changed"]
    assert changed == [
        {"id": "bridge-across-constrained", "field": "kind",
         "from": "settlement_constrained", "to": "settlement_degraded"}
    ]


def test_lists_follow_catalogue_order_then_id():
    """T-42. Every id renamed so each one is new; the list is not sorted by id alone."""
    found = bodies()
    for chain in found["flow_chains"]["chains"]:
        chain["finding"]["id"] = "z-" + chain["finding"]["id"]
    found["liquidity_DAI"]["findings"].reverse()
    for entry in found["liquidity_DAI"]["findings"]:
        entry["id"] = "a-" + entry["id"]
    new = run(found, first_day())["findings"]["new"]
    assert ids(new) == [
        "z-flow-base-flight-confirmed",
        "z-flow-optimism-not-concluded",
        "a-dai-dap10-not-concluded",
        "a-dai-dap25-not-concluded",
        "a-dai-dap50-below-range",
    ]


def test_a_repeated_id_keeps_its_first_entry():
    found = bodies()
    entries = found["liquidity_DAI"]["findings"]
    entries.insert(0, {**copy.deepcopy(entries[2]), "severity": "elevated"})
    refs = run(found)["findings"]["open"]["liquidity_DAI"]
    assert [(r["id"], r["severity"]) for r in refs if r["id"] == "dai-dap50-below-range"] == [
        ("dai-dap50-below-range", "elevated")
    ]


# A surface not read today (T-41): never gone, carried in `open`.


def test_a_failed_surface_gives_no_gone_entries_and_carries_its_previous_findings():
    previous = first_day()
    found = bodies()
    del found["flow_chains"]
    findings = run(found, previous, failed=("flow_chains",))["findings"]
    assert findings["gone"] == []
    assert "flow_chains" in findings["surfacesMissing"]
    assert "flow_chains" not in findings["surfaces"]
    assert findings["open"]["flow_chains"] == previous["findings"]["open"]["flow_chains"]
    assert not [ref for ref in findings["stillOpen"] if ref["surface"] == "flow_chains"]


def test_a_carried_set_is_the_base_on_the_run_after():
    found = bodies()
    del found["flow_chains"]
    second = run(found, first_day(), failed=("flow_chains",))
    third_bodies = bodies()
    del third_bodies["flow_chains"]["chains"][1]
    findings = run(third_bodies, second)["findings"]
    assert ids(findings["gone"]) == ["flow-optimism-not-concluded"]
    assert "flow-base-flight-confirmed" in ids(findings["stillOpen"])


def _no_findings_key(found):
    del found["liquidity_DAI"]["findings"]  # `finding` alone is not every band


def _row_without_finding(found):
    del found["flow_chains"]["chains"][0]["finding"]


def _id_not_a_string(found):
    found["flow_chains"]["chains"][0]["finding"]["id"] = None


def _chains_not_a_list(found):
    found["flow_chains"]["chains"] = {"base": {}}


def _bridge_without_finding(found):
    del found["bridge_across"]["finding"]


def _entry_not_an_object(found):
    found["liquidity_DAI"]["findings"].append("dai-dap100")


def _body_not_json(found):
    found["confidence"] = b"<html>proxy error</html>"


@pytest.mark.parametrize(
    "spoil",
    [
        _no_findings_key,
        _row_without_finding,
        _id_not_a_string,
        _chains_not_a_list,
        _bridge_without_finding,
        _entry_not_an_object,
        _body_not_json,
    ],
)
def test_a_body_that_does_not_give_every_finding_is_a_missing_surface(spoil):
    previous = first_day()
    found = bodies()
    spoil(found)
    findings = run(found, previous)["findings"]
    (name,) = [n for n in READ if n in findings["surfacesMissing"]]
    assert findings["gone"] == [], "a surface we could not read loses nothing"
    assert findings["open"][name] == previous["findings"]["open"][name]


def test_a_surface_read_for_the_first_time_is_open_only_and_named_in_the_note():
    """Q51: no earlier reading means no comparison for that surface, not everything new."""
    found = bodies()
    del found["flow_chains"]
    first = run(found, failed=("flow_chains",), run_date="2026-10-06")
    assert "flow_chains" not in first["findings"]["open"]
    findings = run(bodies(), first)["findings"]
    assert not [ref for ref in findings["new"] if ref["surface"] == "flow_chains"]
    assert ids(findings["open"]["flow_chains"]) == [
        "flow-base-flight-confirmed", "flow-optimism-not-concluded"
    ]
    assert findings["note"] == "No earlier reading to compare with: flow_chains."


# A previous derived.json with no comparison base (T-40, Q44).


def _pass_2a_file() -> dict:
    """A derived.json as pass 2a wrote it: stub statistics, no `open`, no `tiers`."""
    previous = first_day()
    previous["findings"] = {"surfaces": [], "new": [], "gone": [], "stillOpen": [],
                            "changed": [], "note": None, "missing": "Not computed yet: pass 2b."}
    previous["corridorTierChanges"] = {"changes": [], "missing": "Not computed yet: pass 2b."}
    return previous


def test_a_previous_file_from_before_pass_2b_is_no_base_and_the_note_names_its_date():
    derived = run(bodies(), _pass_2a_file())
    findings, tiers = derived["findings"], derived["corridorTierChanges"]
    assert derived["firstRun"] is False
    assert findings["new"] == findings["gone"] == findings["stillOpen"] == []
    assert findings["note"] == "The previous run (2026-10-06) holds no findings to compare with."
    assert set(findings["open"]) == set(READ)
    assert tiers["changes"] == []
    assert tiers["note"] == "The previous run (2026-10-06) holds no corridor tiers to compare with."
    assert tiers["tiers"] is not None


@pytest.mark.parametrize(
    "bad_open",
    [
        [],
        {"flow_chains": "flow-base-flight-confirmed"},
        {"flow_chains": [{"surface": "flow_chains"}]},
    ],
)
def test_an_unusable_previous_open_is_no_base(bad_open):
    previous = first_day()
    previous["findings"]["open"] = bad_open
    findings = run(bodies(), previous)["findings"]
    assert findings["new"] == findings["gone"] == []
    assert findings["note"].startswith("The previous run (2026-10-06) holds no findings")


# Corridor tier changes (R-DRV-2, T-43).


def test_first_run_records_each_tier_with_the_body_updated_at_and_no_changes():
    tiers = first_day()["corridorTierChanges"]
    assert tiers == {
        "changes": [],
        "tiers": {"across_ethereum_base": {"recommendation": "degraded", "observedAt": UPDATED_AT}},
        "note": FIRST_RUN_NOTE,
        "missing": None,
    }


def test_an_unchanged_tier_is_no_change():
    tiers = run(bodies(), first_day())["corridorTierChanges"]
    assert tiers["changes"] == []
    assert tiers["note"] is None and tiers["missing"] is None


def test_a_changed_recommendation_is_a_tier_change():
    found = bodies()
    corridor(found)["recommendation"] = "avoid"
    found["confidence"]["updatedAt"] = "2026-08-29T14:35:00Z"
    assert run(found, first_day())["corridorTierChanges"]["changes"] == [
        {"corridor": "across_ethereum_base", "from": "degraded", "to": "avoid",
         "observedAt": "2026-08-29T14:35:00Z"}
    ]


def test_a_corridor_that_appears_or_leaves_has_a_null_side():
    found = bodies()
    added = copy.deepcopy(corridor(found))
    added.update(corridorId="cctp_ethereum_base", recommendation="preferred")
    found["confidence"]["corridors"] = [added]
    assert run(found, first_day())["corridorTierChanges"]["changes"] == [
        {"corridor": "across_ethereum_base", "from": "degraded", "to": None,
         "observedAt": UPDATED_AT},
        {"corridor": "cctp_ethereum_base", "from": None, "to": "preferred",
         "observedAt": UPDATED_AT},
    ]


def test_an_absent_updated_at_gives_a_null_observed_at():
    found = bodies()
    del found["confidence"]["updatedAt"]
    tiers = run(found)["corridorTierChanges"]["tiers"]
    assert tiers["across_ethereum_base"]["observedAt"] is None


def test_a_failed_confidence_call_says_why_and_carries_the_previous_tiers():
    previous = first_day()
    found = bodies()
    del found["confidence"]
    tiers = run(found, previous, failed=("confidence",))["corridorTierChanges"]
    assert tiers["changes"] == []
    assert tiers["missing"] == TIERS_NOT_READ
    assert tiers["tiers"] == previous["corridorTierChanges"]["tiers"]


def test_carried_tiers_are_the_base_on_the_run_after():
    found = bodies()
    del found["confidence"]
    second = run(found, first_day(), failed=("confidence",))
    third = bodies()
    corridor(third)["recommendation"] = "usable"
    changes = run(third, second)["corridorTierChanges"]["changes"]
    assert [(c["from"], c["to"]) for c in changes] == [("degraded", "usable")]


def test_a_first_run_without_confidence_knows_no_tiers():
    """Q51: null, not {}, so the next run does not report every corridor as appearing."""
    found = bodies()
    del found["confidence"]
    first = run(found, failed=("confidence",), run_date="2026-10-06")
    assert first["corridorTierChanges"]["tiers"] is None
    second = run(bodies(), first)["corridorTierChanges"]
    assert second["changes"] == []
    assert second["note"].startswith("The previous run (2026-10-06) holds no corridor tiers")


@pytest.mark.parametrize(
    "spoil",
    [
        lambda body: body["corridors"][0].pop("corridorId"),
        lambda body: body.update(corridors={"across_ethereum_base": {}}),
        lambda body: body.pop("corridors"),
    ],
)
def test_a_confidence_body_without_every_corridor_id_is_no_comparison(spoil):
    previous = first_day()
    found = bodies()
    spoil(found["confidence"])
    tiers = run(found, previous)["corridorTierChanges"]
    assert tiers["missing"] == TIERS_NOT_READ
    assert tiers["tiers"] == previous["corridorTierChanges"]["tiers"]
