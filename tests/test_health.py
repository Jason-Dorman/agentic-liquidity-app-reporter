"""pull.check_health: GET /health, read the three T-19 fields, or say why not (T-27)."""

import json

import pytest
from fakes import FakeClient

from daily_review.client import HttpError, Response, Timeout, TunnelDown, Unreachable
from daily_review.pull import HEALTH_PATH, Healthy, NotJson, check_health

# vendor/API-SPEC.md, section "GET /api/health", Example.
SPEC_EXAMPLE = {
    "status": "operational",
    "corridorsMonitored": 47,
    "corridorsHealthy": 41,
    "corridorsIdle": 3,
    "corridorsDegraded": 2,
    "corridorsDown": 1,
    "transfers24h": 15234,
    "successRate24h": 98.7,
    "activeAnomalies": 2,
    "updatedAt": "2026-02-21T14:35:00Z",
}


def answering(result) -> FakeClient:
    return FakeClient({(HEALTH_PATH, None): result})


def ok(body: bytes) -> Response:
    return Response(status=200, headers={}, body=body)


def test_health_is_one_get_of_the_health_path_with_no_params():
    client = answering(ok(json.dumps(SPEC_EXAMPLE).encode()))
    check_health(client)
    assert [(path, params) for path, params, _ in client.calls] == [("/health", None)]


def test_the_spec_example_gives_the_three_fields():
    """T-19, R-RUN-8: status, corridorsMonitored, updatedAt."""
    health = check_health(answering(ok(json.dumps(SPEC_EXAMPLE).encode())))
    assert isinstance(health, Healthy)
    assert health.summary == (
        "health: status=operational corridorsMonitored=47 updatedAt=2026-02-21T14:35:00Z"
    )


@pytest.mark.parametrize("status", ["degraded", "down"])
def test_a_degraded_or_down_status_still_counts_as_reachable(status):
    health = check_health(answering(ok(json.dumps({**SPEC_EXAMPLE, "status": status}).encode())))
    assert isinstance(health, Healthy)
    assert f"status={status}" in health.summary


def test_a_missing_field_is_logged_as_missing_and_a_null_as_null():
    """T-27: a JSON object with a field absent is still reachable. A null is not a zero."""
    body = {"status": "operational", "corridorsMonitored": None}
    health = check_health(answering(ok(json.dumps(body).encode())))
    assert isinstance(health, Healthy)
    assert "corridorsMonitored=null" in health.summary
    assert "updatedAt=missing" in health.summary


@pytest.mark.parametrize(
    "body",
    [b"<html>dev stack</html>", b"[1, 2]", b'"operational"', b"", b"\xff", b"[" * 200_000],
)
def test_a_body_that_is_not_a_json_object_is_not_json(body):
    """T-27: we cannot tell which deployment answered, so the run must not go on."""
    health = check_health(answering(ok(body)))
    assert isinstance(health, NotJson)
    assert "not a JSON object" in health.message
    assert "BLOCKFORD_API_BASE_URL" in health.message


@pytest.mark.parametrize(
    "failure",
    [
        TunnelDown("tunnel down: connection refused at localhost:3300"),
        HttpError(status=500, headers={}, body=b"boom"),
        Timeout("timeout: no answer from /health within 30 s"),
        Unreachable("unreachable: Name or service not known"),
    ],
)
def test_a_failed_call_is_passed_through_unchanged(failure):
    assert check_health(answering(failure)) is failure
