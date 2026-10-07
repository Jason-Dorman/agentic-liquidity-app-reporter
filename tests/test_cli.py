"""cli.py: the three commands and --date parse and, in pass 0a, exit 0 doing nothing."""

import pytest

from daily_review.cli import main


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["run", "--date", "2026-10-07"],
        ["pull-only"],
        ["render", "reports/2026-10-07.json"],
    ],
)
def test_commands_parse_and_exit_zero(argv):
    """R-RUN-6, R-RUN-7: run, run --date, pull-only, render."""
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
