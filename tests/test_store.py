"""store.py: pack paths by date; one pull saved as raw bodies, failure records and a manifest;
derived.json saved, and the previous one found.

R-PULL-2 (raw bytes never altered), T-28 (root as an argument), T-30 (a re-pull replaces the pull),
T-37 (the previous derived.json).
"""

import json
import logging
import os
from datetime import date

import pytest

from daily_review.store import load_previous_derived, pack_paths, save_derived, save_pack

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


# derived.json: today's saved, the previous one found (pass 2a, T-37).


def test_save_derived_writes_sorted_keys_and_keeps_nulls(tmp_path):
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, {}, {}, MANIFEST)
    derived = {"runDate": "2026-10-07", "previousRunDate": None, "anomalies": {"openCount": None}}
    save_derived(paths, derived)
    assert paths.derived.read_text("utf-8") == json.dumps(derived, sort_keys=True, indent=2) + "\n"


def put_derived(root, day: str, value) -> None:
    folder = root / "data" / day
    folder.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value)
    (folder / "derived.json").write_text(text, "utf-8")


def test_no_data_folder_is_a_first_run(tmp_path):
    assert load_previous_derived(tmp_path, RUN_DATE) is None


def test_the_newest_earlier_derived_is_the_previous_one(tmp_path):
    for day in ("2026-10-04", "2026-10-06", "2026-10-05"):
        put_derived(tmp_path, day, {"runDate": day})
    assert load_previous_derived(tmp_path, RUN_DATE) == {"runDate": "2026-10-06"}


def test_today_and_later_dates_are_never_the_previous_run(tmp_path):
    """RUNBOOK section 4: the comparison uses the most recent earlier date, not the same date."""
    for day in ("2026-10-07", "2026-10-08"):
        put_derived(tmp_path, day, {"runDate": day})
    assert load_previous_derived(tmp_path, RUN_DATE) is None


def test_a_pack_without_derived_json_is_passed_over(tmp_path, caplog):
    put_derived(tmp_path, "2026-10-05", {"runDate": "2026-10-05"})
    (tmp_path / "data" / "2026-10-06" / "raw").mkdir(parents=True)
    assert load_previous_derived(tmp_path, RUN_DATE) == {"runDate": "2026-10-05"}
    assert "skipped" not in caplog.text, "a pack without derived.json is not a problem"


@pytest.mark.parametrize("name", ["notes", "2026-10-6", "2026-13-01", "2026-10-06.old"])
def test_a_folder_that_is_not_a_date_is_ignored(tmp_path, name):
    """Ignored, not the end of the search: the older real pack is still found."""
    put_derived(tmp_path, name, {"runDate": name})
    put_derived(tmp_path, "2026-10-04", {"runDate": "2026-10-04"})
    (tmp_path / "data" / "2026-10-05.json").write_text("{}")  # a file, not a folder
    assert load_previous_derived(tmp_path, RUN_DATE) == {"runDate": "2026-10-04"}


@pytest.mark.parametrize(
    "bad",
    [
        "{not json",
        "[1, 2]",
        json.dumps({"firstRun": True}),  # no runDate
        json.dumps({"runDate": "2026-10-05"}),  # not its folder's date
        "\udcff",  # not UTF-8 once written with surrogateescape below
    ],
)
def test_an_unusable_previous_is_skipped_with_a_warning_and_the_next_older_is_used(
    tmp_path, caplog, bad
):
    put_derived(tmp_path, "2026-10-04", {"runDate": "2026-10-04"})
    folder = tmp_path / "data" / "2026-10-06"
    folder.mkdir(parents=True)
    (folder / "derived.json").write_bytes(bad.encode("utf-8", "surrogateescape"))
    with caplog.at_level(logging.WARNING):
        assert load_previous_derived(tmp_path, RUN_DATE) == {"runDate": "2026-10-04"}
    (warning,) = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert "2026-10-06" in warning and "derived.json" in warning


def test_when_no_earlier_derived_is_usable_it_is_a_first_run(tmp_path, caplog):
    put_derived(tmp_path, "2026-10-06", "{not json")
    with caplog.at_level(logging.WARNING):
        assert load_previous_derived(tmp_path, RUN_DATE) is None
    assert "skipped" in caplog.text


def older_and_newer(root):
    """A usable 2026-10-04 and an empty 2026-10-06 folder for the test to spoil."""
    put_derived(root, "2026-10-04", {"runDate": "2026-10-04"})
    newer = root / "data" / "2026-10-06"
    newer.mkdir(parents=True)
    return newer


def assert_skipped_to_the_older_one(root, caplog):
    with caplog.at_level(logging.WARNING):
        assert load_previous_derived(root, RUN_DATE) == {"runDate": "2026-10-04"}
    (warning,) = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert "2026-10-06" in warning


def test_a_derived_json_that_is_a_folder_is_skipped_with_a_warning(tmp_path, caplog):
    """T-37: cannot be read as a file (OSError)."""
    (older_and_newer(tmp_path) / "derived.json").mkdir()
    assert_skipped_to_the_older_one(tmp_path, caplog)


def test_a_derived_json_nested_too_deep_to_parse_is_skipped_with_a_warning(tmp_path, caplog):
    """T-37: json raises RecursionError, not ValueError, on deep nesting."""
    (older_and_newer(tmp_path) / "derived.json").write_text("[" * 100_000)
    assert_skipped_to_the_older_one(tmp_path, caplog)


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root ignores permissions")
def test_a_pack_folder_that_cannot_be_searched_is_skipped_with_a_warning(tmp_path, caplog):
    """T-37: on Python 3.11 Path.exists raises PermissionError here; the read must not."""
    newer = older_and_newer(tmp_path)
    (newer / "derived.json").write_text(json.dumps({"runDate": "2026-10-06"}))
    newer.chmod(0o600)
    try:
        assert_skipped_to_the_older_one(tmp_path, caplog)
    finally:
        newer.chmod(0o700)
