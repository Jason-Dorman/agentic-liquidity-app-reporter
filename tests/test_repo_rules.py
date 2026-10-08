"""Repository rules: files never tracked (hard constraint 13); diagrams are Mermaid only."""

import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

REPO = Path(__file__).resolve().parents[1]
RUN_OUTPUT_DIRS = ("data", "reports", "state")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"}


def breaches(tracked):
    """Return one line per tracked path that breaks a repository rule, naming the rule."""
    found = []
    for path in tracked:
        rule = _rule_broken(PurePosixPath(path))
        if rule:
            found.append(f"{path}: {rule}")
    return found


def _rule_broken(path):
    if _is_env_file(path.name):
        return "env files are never committed; only .env.example is"
    if path.parts[0] in RUN_OUTPUT_DIRS:
        return f"{path.parts[0]}/ holds run output and is never committed"
    if path.parts[0] == "docs" and path.suffix.lower() in IMAGE_SUFFIXES:
        return "diagrams are Mermaid; no image files in docs/"
    return None


def _is_env_file(name):
    return name != ".env.example" and (name == ".env" or name.startswith(".env."))


def _tracked_files():
    if shutil.which("git") is None:
        pytest.skip("git is not installed, so the tracked files cannot be listed")
    listing = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True
    )
    if listing.returncode != 0:
        pytest.skip(f"not a git checkout: {listing.stderr.strip()}")
    return [path for path in listing.stdout.split("\0") if path]


def test_a_clean_file_list_has_no_breaches():
    clean = [
        ".env.example",
        "README.md",
        "docs/ARCHITECTURE.md",
        "src/daily_review/cli.py",
        "tests/fixtures/README.md",
        "vendor/API-SPEC.md",
    ]
    assert breaches(clean) == []


def test_env_example_is_allowed():
    assert breaches([".env.example"]) == []


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "src/daily_review/.env",
        "data/2026-10-07/raw/health.json",
        "reports/2026-10-07.json",
        "reports/2026-10-07.md",
        "state/watchlist.json",
        "docs/diagram.png",
        "docs/images/flow.SVG",
    ],
)
def test_each_forbidden_path_is_reported_with_its_rule(path):
    found = breaches(["README.md", path])
    assert len(found) == 1
    assert found[0].startswith(f"{path}: ")


def test_a_run_output_name_below_the_top_level_is_not_a_breach():
    """Hard constraint 13 names the top-level data/, reports/ and state/ directories."""
    assert breaches(["tests/fixtures/reports/sample.json", "src/daily_review/state.py"]) == []


def test_this_checkout_tracks_nothing_it_should_not():
    assert breaches(_tracked_files()) == []
