"""The endpoint catalogue and the pull: call each endpoint, keep raw bodies, build the manifest."""

import json
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from daily_review.client import (
    Failure,
    Getter,
    HttpError,
    Params,
    Response,
    Timeout,
    TunnelDown,
    Unreachable,
)

HEALTH_PATH = "/health"
HEALTH_FIELDS = ("status", "corridorsMonitored", "updatedAt")  # T-19: which deployment answered
WINDOW = timedelta(hours=24)  # "today" is the 24 hours before the run (T-16)
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
    parsed = _json_object(body)
    if parsed is None:
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


def _json_object(body: bytes) -> dict | None:
    """The body as a JSON object, or None when it is not one."""
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):  # RecursionError: a body nested too deep to parse
        return None
    return parsed if isinstance(parsed, dict) else None


# The catalogue (spec section 5). Paths are declared per endpoint, never found by walking the
# body (T-29, T-32). A path is dot-separated keys; `key[]` steps into every item of a list;
# a final `*` names an object whose every value is a coverage leg.


@dataclass(frozen=True)
class Endpoint:
    """One row of spec section 5, with where its manifest flags live in the response."""

    name: str
    path: str
    params: Params | None = None
    truncation: tuple[str, ...] = ()  # boolean flags; true = the cap was reached
    legs: tuple[str, ...] = ()  # coverage legs: values that are `ok` when the leg was read
    total: str | None = None  # the count of all matching rows, on paged endpoints
    rows: str | None = None  # the list of rows served; counted for `total` and `limit`
    retry_limit: int | None = None  # re-call once with this limit when truncated (Q3)


def _liquidity(asset: str) -> Endpoint:
    return Endpoint(
        f"liquidity_{asset}",
        f"/stablecoins/{asset}/liquidity",
        {"window": "7d"},
        truncation=(
            "depth.history.truncated",
            "depth.venueHistory.truncated",
            "timelines[].truncated",
            "exceedances.truncated",
        ),
        legs=("coverage.legs.*",),
    )


_FLOW_LEGS = ("coverage.flowLeg", "coverage.statusHoldLeg", "coverage.materialityLeg")

CATALOGUE: tuple[Endpoint, ...] = (
    Endpoint("health", HEALTH_PATH),
    Endpoint("flow_chains", "/flow/chains", legs=_FLOW_LEGS),
    # No rows check: carry-in rows do not count against `limit` (Q3, T-32).
    Endpoint(
        "flow_history",
        "/flow/history",
        {"hours": 168, "limit": 500},
        truncation=("truncated",),
        retry_limit=5000,
    ),
    Endpoint("bridge_across", "/bridges/across/health", legs=("coverage.fetcher",)),
    Endpoint("bridge_cctp", "/bridges/cctp/health", legs=("coverage.fetcher",)),
    Endpoint("bridge_stargate", "/bridges/stargate/health", legs=("coverage.fetcher",)),
    Endpoint("confidence", "/corridors/confidence"),
    Endpoint(
        "corridors",
        "/corridors",
        {"limit": 500},
        truncation=("truncation.transfers.truncated", "truncation.poolSnapshots.truncated"),
        total="total",
        rows="corridors",
    ),
    Endpoint(
        "anomalies_open",
        "/anomalies",
        {"active": "true", "limit": 500},
        total="total",
        rows="anomalies",
    ),
    Endpoint(
        "anomalies_all",
        "/anomalies",
        {"active": "false", "limit": 500},
        total="total",
        rows="anomalies",
    ),
    Endpoint("exceedances", "/exceedances", {"hours": 168, "limit": 5000}, rows="exceedances"),
    Endpoint("spread_latest", "/spread", {"latest": "true"}),
    Endpoint("spread_history", "/spread", {"hours": 168, "limit": 5000}, rows="series"),
    Endpoint(
        "bsh",
        "/bsh",
        {"hours": 168, "limit": 5000},
        truncation=("truncation.truncated",),
        rows="series",
    ),
    Endpoint("depth_latest", "/depth", {"latest": "true"}),
    *(_liquidity(asset) for asset in ("USDT", "USDC", "DAI", "PYUSD", "USDe")),
    Endpoint("issuer_flows", "/issuer-flows", {"hours": 168, "limit": 5000}, rows="series"),
    Endpoint("attestations", "/attestations", rows="attestations"),
    Endpoint("structural_facts", "/structural-facts", rows="records"),
)


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _resolve(value: object, path: str, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Each (full path, value) that a declared path names. An absent value is _MISSING."""
    head, _, rest = path.partition(".")
    if head == "*":
        if not isinstance(value, dict):
            yield _join(prefix, path), _MISSING
            return
        for key, item in value.items():
            yield from _step(item, rest, _join(prefix, key))
        return
    key = head.removesuffix("[]")
    found = value.get(key, _MISSING) if isinstance(value, dict) else _MISSING
    if found is _MISSING or (head.endswith("[]") and not isinstance(found, list)):
        yield _join(prefix, path), _MISSING
    elif head.endswith("[]"):
        for index, item in enumerate(found):
            yield from _step(item, rest, _join(prefix, f"{key}[{index}]"))
    else:
        yield from _step(found, rest, _join(prefix, key))


def _step(value: object, rest: str, here: str) -> Iterator[tuple[str, object]]:
    if rest:
        yield from _resolve(value, rest, here)
    else:
        yield here, value


def _found(body: dict, paths: tuple[str, ...]) -> list[tuple[str, object]]:
    return [pair for path in paths for pair in _resolve(body, path)]


def _truncation(body: dict, paths: tuple[str, ...]) -> dict:
    """`truncated` and `truncatedAt` (T-29). An absent flag never reads as false (T-32)."""
    found = _found(body, paths)
    true_at = [path for path, value in found if value is True]
    if true_at:
        return {"truncated": True, "truncatedAt": true_at}
    if found and all(value is False for _, value in found):
        return {"truncated": False, "truncatedAt": []}
    return {"truncated": None, "truncatedAt": None}


def _legs_not_ok(body: dict, legs: tuple[str, ...]) -> list[dict] | None:
    """Each declared coverage leg that is not `ok`, with its value; an absent one is null."""
    if not legs:
        return None
    return [
        {"leg": path, "value": None if value is _MISSING else value}
        for path, value in _found(body, legs)
        if value != "ok"
    ]


def _number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _row_count(body: dict, endpoint: Endpoint) -> int | None:
    rows = body.get(endpoint.rows) if endpoint.rows else None
    return len(rows) if isinstance(rows, list) else None


def _total_exceeds_rows(body: dict, endpoint: Endpoint) -> dict | bool | None:
    total = _number(body.get(endpoint.total)) if endpoint.total else None
    rows = _row_count(body, endpoint)
    if total is None or rows is None:
        return None
    return {"total": total, "rows": rows} if total > rows else False


def _rows_at_limit(body: dict, endpoint: Endpoint, params: Params | None) -> dict | bool | None:
    """Rows served against the sent `limit`, or else the echoed one (T-29, T-32)."""
    rows = _row_count(body, endpoint)
    limit = _number((params or {}).get("limit", body.get("limit")))
    if rows is None or limit is None:
        return None
    return {"rows": rows, "limit": limit} if rows >= limit else False


NO_FLAGS = {
    "truncated": None,
    "truncatedAt": None,
    "coverageNotOk": None,
    "totalExceedsRows": None,
    "rowsAtLimit": None,
}


def read_flags(body: bytes, endpoint: Endpoint, params: Params | None) -> dict:
    """The manifest flags of one response (DATA-CONTRACTS section 1.2). All null if not JSON."""
    parsed = _json_object(body)
    if parsed is None:
        return dict(NO_FLAGS)
    return {
        **_truncation(parsed, endpoint.truncation),
        "coverageNotOk": _legs_not_ok(parsed, endpoint.legs),
        "totalExceedsRows": _total_exceeds_rows(parsed, endpoint),
        "rowsAtLimit": _rows_at_limit(parsed, endpoint, params),
    }


# The pull (spec section 4 step 2). A failed call becomes a failure record and the pull goes on.

_KINDS = {
    HttpError: "HTTP error",
    TunnelDown: "tunnel down",
    Timeout: "timeout",
    Unreachable: "unreachable",
}


@dataclass(frozen=True)
class DataPack:
    """One pull (DATA-CONTRACTS section 1). `kinds` names why each failed call failed."""

    raw: Mapping[str, bytes]
    failures: Mapping[str, dict]
    manifest: dict
    kinds: Mapping[str, str]

    @property
    def tunnel_down(self) -> bool:
        """Any call refused or reset: the API stopped answering mid-pull (T-31)."""
        return "tunnel down" in self.kinds.values()

    @property
    def summary(self) -> str:
        """One log line: calls made, ok, and failed by kind."""
        calls = len(self.manifest["calls"])
        line = f"pull: {calls} calls, {calls - len(self.failures)} ok, {len(self.failures)} failed"
        if not self.kinds:
            return line
        counts = Counter(self.kinds.values())
        return f"{line} ({', '.join(f'{kind} {n}' for kind, n in sorted(counts.items()))})"


Clock = Callable[[], datetime]


@dataclass(frozen=True)
class _Call:
    row: dict
    body: bytes | None = None
    failure: dict | None = None
    kind: str | None = None


def stamp(moment: datetime) -> str:
    """ISO 8601 in UTC, to the second, with a Z (DATA-CONTRACTS conventions)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_text(failure: Failure) -> str:
    """The body as text for an HTTP error, else the failure's message (section 1.1)."""
    if isinstance(failure, HttpError) and failure.body:
        return failure.body.decode("utf-8", "replace")
    return failure.message


def _fetch(
    client: Getter, endpoint: Endpoint, name: str, params: Params | None, now: Clock
) -> _Call:
    at = stamp(now())
    result = client.get(endpoint.path, params)
    base = {"name": name, "endpoint": endpoint.path, "params": dict(params or {}), "at": at}
    if isinstance(result, Response):
        flags = read_flags(result.body, endpoint, params)
        row = {**base, "ok": True, "status": result.status, "bytes": len(result.body), **flags}
        return _Call(row, body=result.body)
    status = result.status if isinstance(result, HttpError) else None
    failure = {**base, "status": status, "error": _error_text(result)}
    row = {**base, "ok": False, "status": status, "bytes": None, **NO_FLAGS}
    return _Call(row, failure=failure, kind=_KINDS[type(result)])


def _calls(client: Getter, endpoint: Endpoint, now: Clock) -> list[tuple[str, _Call]]:
    """The endpoint's call, and its one re-call with a larger limit when truncated (Q3)."""
    first = _fetch(client, endpoint, endpoint.name, endpoint.params, now)
    calls = [(endpoint.name, first)]
    if endpoint.retry_limit is not None and first.row["truncated"] is True:
        params = {**(endpoint.params or {}), "limit": endpoint.retry_limit}
        name = f"{endpoint.name}.retry"
        calls.append((name, _fetch(client, endpoint, name, params, now)))
    return calls


def pull(
    client: Getter,
    started: datetime,
    base_url_host: str,
    now: Clock,
    catalogue: tuple[Endpoint, ...] = CATALOGUE,
) -> DataPack:
    """Call every endpoint in order. Never stops early: every name gets a file or a record."""
    calls = [pair for endpoint in catalogue for pair in _calls(client, endpoint, now)]
    manifest = {
        "runDate": started.astimezone(UTC).date().isoformat(),
        "windowStart": stamp(started - WINDOW),
        "windowEnd": stamp(started),
        "baseUrlHost": base_url_host,
        "calls": [call.row for _, call in calls],
    }
    return DataPack(
        raw={name: call.body for name, call in calls if call.body is not None},
        failures={name: call.failure for name, call in calls if call.failure is not None},
        manifest=manifest,
        kinds={name: call.kind for name, call in calls if call.kind is not None},
    )
