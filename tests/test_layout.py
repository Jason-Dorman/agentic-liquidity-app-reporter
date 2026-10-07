"""The package layout from ARCHITECTURE section 3 and the vendored spec's copy header."""

import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULES = [
    "cli",
    "config",
    "client",
    "pull",
    "derive",
    "store",
    "uploads",
    "tools",
    "agent",
    "schema",
    "render",
]


@pytest.mark.parametrize("name", MODULES)
def test_each_module_states_its_responsibility_in_one_line(name):
    module = importlib.import_module(f"daily_review.{name}")
    docstring = (module.__doc__ or "").strip()
    assert docstring
    assert "\n" not in docstring


def test_vendored_api_spec_keeps_its_copy_header():
    """Milestone 0 exit check: vendor/API-SPEC.md is present with its copy header on line 1."""
    first_line = (REPO / "vendor" / "API-SPEC.md").read_text().splitlines()[0]
    assert first_line.startswith("> **Vendored copy.**")
    assert "Copied into this repo on" in first_line
    assert "spec version" in first_line
