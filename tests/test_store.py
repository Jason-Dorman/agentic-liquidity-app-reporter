"""store.py: pack paths by date, and raw bodies saved byte for byte (R-PULL-2, T-28)."""

from datetime import date

import pytest

from daily_review.store import pack_paths, save_pack

RUN_DATE = date(2026, 10, 7)


def test_pack_paths_follow_data_contracts_section_1(tmp_path):
    paths = pack_paths(tmp_path, RUN_DATE)
    assert paths.root == tmp_path / "data" / "2026-10-07"
    assert paths.raw == paths.root / "raw"
    assert paths.failures == paths.root / "failures"
    assert paths.manifest == paths.root / "manifest.json"
    assert paths.derived == paths.root / "derived.json"
    assert paths.raw_file("flow_history.retry") == paths.raw / "flow_history.retry.json"


def test_save_pack_round_trips_bytes_exactly(tmp_path):
    """R-PULL-2: never altered. Whitespace, key order, non-ASCII and a missing newline survive."""
    bodies = {
        "health": b'{ "status":"operational",\r\n  "corridorsMonitored" : 47 }',
        "liquidity_USDT": '{"note":"café — ok"}\n\n'.encode(),
        "flow_history.retry": b"not even json",
        "empty": b"",
    }
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, bodies)
    for name, body in bodies.items():
        assert paths.raw_file(name).read_bytes() == body
    assert sorted(p.name for p in paths.raw.iterdir()) == sorted(f"{n}.json" for n in bodies)


def test_saving_twice_on_one_date_overwrites(tmp_path):
    """RUNBOOK section 4: a second run on the same date overwrites that date's files."""
    paths = pack_paths(tmp_path, RUN_DATE)
    save_pack(paths, {"health": b"first, and longer"})
    save_pack(paths, {"health": b"second"})
    assert paths.raw_file("health").read_bytes() == b"second"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", ".", "..", "with space"])
def test_a_name_that_is_not_a_plain_file_name_is_refused(tmp_path, bad):
    with pytest.raises(ValueError, match="name"):
        save_pack(pack_paths(tmp_path, RUN_DATE), {bad: b"{}"})
    assert not (tmp_path / "data").exists()
