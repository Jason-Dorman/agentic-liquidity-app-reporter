"""store.py: pack paths by date; one pull saved as raw bodies, failure records and a manifest.

R-PULL-2 (raw bytes never altered), T-28 (root as an argument), T-30 (a re-pull replaces the pull).
"""

import json
from datetime import date

import pytest

from daily_review.store import pack_paths, save_pack

RUN_DATE = date(2026, 10, 7)
MANIFEST = {"runDate": "2026-10-07", "calls": []}
FAILURE = {
    "name": "flow_history",
    "endpoint": "/flow/history",
    "params": {"hours": 168, "limit": 500},
    "at": "2026-10-07T06:00:03Z",
    "status": 400,
    "error": "hours must be between 1 and 720",
}


def test_pack_paths_follow_data_contracts_section_1(tmp_path):
    paths = pack_paths(tmp_path, RUN_DATE)
    assert paths.root == tmp_path / "data" / "2026-10-07"
    assert paths.raw == paths.root / "raw"
    assert paths.failures == paths.root / "failures"
    assert paths.manifest == paths.root / "manifest.json"
    assert paths.derived == paths.root / "derived.json"
    assert paths.raw_file("flow_history.retry") == paths.raw / "flow_history.retry.json"
    assert paths.failure_file("bsh") == paths.failures / "bsh.json"


def test_save_pack_round_trips_bytes_exactly(tmp_path):
    """R-PULL-2: never altered. Whitespace, key order, non-ASCII and a missing newline survive."""
    bodies = {
        "health": b'{ "status":"operational",\r\n  "corridorsMonitored" : 47 }',
        "liquidity_USDT": '{"note":"café — ok"}\n\n'.encode(),
        "flow_history.retry": b"not even json",
        "empty": b"",
    }
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, bodies, {}, MANIFEST)
    for name, body in bodies.items():
        assert paths.raw_file(name).read_bytes() == body
    assert sorted(p.name for p in paths.raw.iterdir()) == sorted(f"{n}.json" for n in bodies)


def test_failures_and_manifest_are_json_with_sorted_keys_and_two_space_indent(tmp_path):
    """DATA-CONTRACTS conventions; a null stays null (rule 7)."""
    paths = pack_paths(tmp_path, RUN_DATE)
    manifest = {"runDate": "2026-10-07", "calls": [{"name": "x", "truncated": None, "bytes": 0}]}
    save_pack(paths, {}, {"flow_history": FAILURE}, manifest)
    for path, value in [(paths.failure_file("flow_history"), FAILURE), (paths.manifest, manifest)]:
        text = path.read_text("utf-8")
        assert text == json.dumps(value, sort_keys=True, indent=2) + "\n"
    assert '"truncated": null' in paths.manifest.read_text("utf-8")


def test_no_failures_writes_no_failures_directory(tmp_path):
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, {"health": b"{}"}, {}, MANIFEST)
    assert not paths.failures.exists()
    assert paths.manifest.exists()


def test_a_re_pull_leaves_nothing_from_the_earlier_pull(tmp_path):
    """T-30: a name that succeeded first and failed second has only its failure record."""
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, {"health": b"first, and longer", "bsh": b"{}"}, {"spread": FAILURE}, MANIFEST)
    second = {"runDate": "2026-10-07", "calls": [{"name": "bsh"}]}
    save_pack(paths, {"health": b"second"}, {"bsh": FAILURE}, second)
    assert paths.raw_file("health").read_bytes() == b"second"
    assert not paths.raw_file("bsh").exists()
    assert not paths.failure_file("spread").exists()
    assert paths.failure_file("bsh").exists()
    assert json.loads(paths.manifest.read_text("utf-8")) == second


def test_a_re_pull_keeps_derived_json(tmp_path):
    """T-30: derived.json is rebuilt by pass 2a, not removed by the store."""
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, {"health": b"{}"}, {}, MANIFEST)
    paths.derived.write_text("{}")
    save_pack(paths, {"health": b"{}"}, {}, MANIFEST)
    assert paths.derived.read_text() == "{}"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", ".", "..", "with space"])
@pytest.mark.parametrize("where", ["raw", "failures"])
def test_a_name_that_is_not_a_plain_file_name_is_refused(tmp_path, bad, where):
    raw, failures = ({bad: b"{}"}, {}) if where == "raw" else ({}, {bad: FAILURE})
    with pytest.raises(ValueError, match="name"):
        save_pack(pack_paths(tmp_path, RUN_DATE), raw, failures, MANIFEST)
    assert not (tmp_path / "data").exists()


def test_a_refused_name_leaves_an_earlier_pull_untouched(tmp_path):
    """The name check runs before the clear, so a bad call to save_pack deletes nothing."""
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, {"health": b"kept"}, {}, MANIFEST)
    with pytest.raises(ValueError):
        save_pack(paths, {"../escape": b"{}"}, {}, MANIFEST)
    assert paths.raw_file("health").read_bytes() == b"kept"
