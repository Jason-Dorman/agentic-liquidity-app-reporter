"""The endpoint catalogue and the pull: call each endpoint, keep raw bodies, build the manifest."""

import json
from dataclasses import dataclass

from daily_review.client import Failure, Getter, Response

HEALTH_PATH = "/health"
HEALTH_FIELDS = ("status", "corridorsMonitored", "updatedAt")  # T-19: which deployment answered
_MISSING = object()


@dataclass(frozen=True)
class Healthy:
    """/health answered with a JSON object. `summary` is the log line of the T-19 fields."""

    summary: str


@dataclass(frozen=True)
class NotJson:
    """/health answered 200 with a body that is not a JSON object (T-27). The run stops."""

    message: str


HealthResult = Healthy | NotJson | Failure


def check_health(client: Getter) -> HealthResult:
    """Step 1 of a run: GET /health. A failed call is returned as it came from the client."""
    result = client.get(HEALTH_PATH)
    if not isinstance(result, Response):
        return result
    return _read_health(result.body)


def _read_health(body: bytes) -> Healthy | NotJson:
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):  # RecursionError: a body nested too deep to parse
        parsed = None
    if not isinstance(parsed, dict):
        return NotJson(
            "health body is not a JSON object; check the port in BLOCKFORD_API_BASE_URL"
        )
    shown = " ".join(f"{name}={_show(parsed.get(name, _MISSING))}" for name in HEALTH_FIELDS)
    return Healthy(f"health: {shown}")


def _show(value: object) -> str:
    """A field for the log. Absent is `missing` and null is `null`: neither is a zero."""
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    return str(value)
