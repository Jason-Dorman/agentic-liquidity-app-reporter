"""Compute the day's statistics from a data pack and the previous run. Pure: no I/O."""

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Protocol, TypedDict

# History is the 168 hours the catalogue pulls, not HISTORY_DAYS (T-34).
HISTORY = timedelta(hours=168)
STAMP = "%Y-%m-%dT%H:%M:%SZ"  # ISO 8601 in UTC, to the second (DATA-CONTRACTS conventions)
FIRST_RUN_NOTE = "First run: no previous run to compare with."
ANOMALIES_WINDOW = "24h, filtered in code by detectedAt and resolvedAt"
DEPTH_NOTE = "Bands are nested. Each band is its own figure. Never summed."
FLOW_HISTORY_NOTE = (
    "Write-on-change source. A gap is a held status. carry_in rows are window-head state, "
    "never transitions. No magnitudes."
)
ISSUER_FLOWS_NOTE = "Totals by asset, event type, and flow class. No gross sum."
NO_RECORD = "no failure record in the pack"  # a failed manifest row without its record (T-39)
NOT_READ = "nothing in it can be read"


class Pack(Protocol):
    """What derive reads from one pull (DATA-CONTRACTS section 1). pull.DataPack fits (T-33)."""

    @property
    def raw(self) -> Mapping[str, bytes]: ...

    @property
    def failures(self) -> Mapping[str, Mapping]: ...

    @property
    def manifest(self) -> Mapping: ...


# The Derived shape (DATA-CONTRACTS section 3). Plain JSON values with TypedDict types (T-33).
# Each statistic not yet built holds its empty shape and a `missing` naming its pass (T-35).


class FindingRef(TypedDict):
    id: str
    surface: str
    kind: str | None
    severity: str | None


# `from` is a Python keyword, so these two need the functional form.
FindingChange = TypedDict(
    "FindingChange", {"id": str, "field": str, "from": str | None, "to": str | None}
)
TierChange = TypedDict(
    "TierChange", {"corridor": str, "from": str | None, "to": str | None, "observedAt": str}
)


class Findings(TypedDict):
    surfaces: list[str]
    new: list[FindingRef]
    gone: list[FindingRef]
    stillOpen: list[FindingRef]
    changed: list[FindingChange]
    note: str | None
    missing: str | None


class CorridorTierChanges(TypedDict):
    changes: list[TierChange]
    missing: str | None


class Anomalies(TypedDict):
    window: str
    openCount: int | None
    opened: list[dict]
    resolved: list[dict]
    missing: str | None


class Exceedances(TypedDict):
    bySeries: dict[str, dict]
    missing: str | None


class SettlementHealth(TypedDict):
    byBridge: dict[str, dict]
    byChain: dict[str, dict]
    byAsset: dict[str, dict]
    missing: str | None


class Depth(TypedDict):
    note: str
    byAsset: dict[str, dict]
    missing: str | None


class Peg(TypedDict):
    byAsset: dict[str, dict]
    missing: str | None


class FlowHistory(TypedDict):
    note: str
    byChain: dict[str, dict]
    missing: str | None


class IssuerFlows(TypedDict):
    note: str
    byAsset: dict[str, dict]
    missing: str | None


class FailedCall(TypedDict):
    name: str
    endpoint: str
    status: int | None
    error: str


class Truncation(TypedDict):
    name: str
    note: str


class CoverageFailure(TypedDict):
    name: str
    leg: str
    state: str | None  # an absent leg stays null (rule 7)


class PartialTotal(TypedDict):
    name: str
    total: int
    rows: int


class DataQuality(TypedDict):
    failedCalls: list[FailedCall]
    truncations: list[Truncation]
    coverageFailures: list[CoverageFailure]
    partialTotals: list[PartialTotal]


class Derived(TypedDict):
    runDate: str
    windowStart: str
    windowEnd: str
    historyStart: str
    previousRunDate: str | None
    firstRun: bool
    findings: Findings
    corridorTierChanges: CorridorTierChanges
    anomalies: Anomalies
    exceedances: Exceedances
    settlementHealth: SettlementHealth
    depth: Depth
    peg: Peg
    flowHistory: FlowHistory
    issuerFlows: IssuerFlows
    dataQuality: DataQuality


def derive(pack: Pack, previous: Derived | None) -> Derived:
    """derived.json from one pull and the previous run's derived.json, or None on a first run."""
    manifest = pack.manifest
    return {
        "runDate": manifest["runDate"],
        "windowStart": manifest["windowStart"],
        "windowEnd": manifest["windowEnd"],
        "historyStart": history_start(manifest["windowEnd"]),
        "previousRunDate": previous["runDate"] if previous is not None else None,
        "firstRun": previous is None,
        "findings": findings(pack, previous),
        "corridorTierChanges": corridor_tier_changes(pack, previous),
        "anomalies": anomalies(pack),
        "exceedances": exceedances(pack),
        "settlementHealth": settlement_health(pack),
        "depth": depth(pack),
        "peg": peg(pack),
        "flowHistory": flow_history(pack),
        "issuerFlows": issuer_flows(pack),
        "dataQuality": data_quality(pack),
    }


def history_start(window_end: str) -> str:
    """The start of the 168 hours before the run (T-34)."""
    return (datetime.strptime(window_end, STAMP) - HISTORY).strftime(STAMP)


def _not_computed(next_pass: str) -> str:
    return f"Not computed yet: pass {next_pass}."


# Stubs: each returns its empty shape until its pass lands (T-35).


def findings(pack: Pack, previous: Derived | None) -> Findings:
    """Pass 2b. On a first run nothing is new: the lists stay empty with a note (R-DRV-10)."""
    return {
        "surfaces": [],
        "new": [],
        "gone": [],
        "stillOpen": [],
        "changed": [],
        "note": FIRST_RUN_NOTE if previous is None else None,
        "missing": _not_computed("2b"),
    }


def corridor_tier_changes(pack: Pack, previous: Derived | None) -> CorridorTierChanges:
    """Pass 2b."""
    return {"changes": [], "missing": _not_computed("2b")}


def anomalies(pack: Pack) -> Anomalies:
    """Pass 2c."""
    return {
        "window": ANOMALIES_WINDOW,
        "openCount": None,
        "opened": [],
        "resolved": [],
        "missing": _not_computed("2c"),
    }


def exceedances(pack: Pack) -> Exceedances:
    """Pass 2c."""
    return {"bySeries": {}, "missing": _not_computed("2c")}


def flow_history(pack: Pack) -> FlowHistory:
    """Pass 2c."""
    return {"note": FLOW_HISTORY_NOTE, "byChain": {}, "missing": _not_computed("2c")}


def settlement_health(pack: Pack) -> SettlementHealth:
    """Pass 2d."""
    return {"byBridge": {}, "byChain": {}, "byAsset": {}, "missing": _not_computed("2d")}


def peg(pack: Pack) -> Peg:
    """Pass 2d."""
    return {"byAsset": {}, "missing": _not_computed("2d")}


def depth(pack: Pack) -> Depth:
    """Pass 2e."""
    return {"note": DEPTH_NOTE, "byAsset": {}, "missing": _not_computed("2e")}


def issuer_flows(pack: Pack) -> IssuerFlows:
    """Pass 2e."""
    return {"note": ISSUER_FLOWS_NOTE, "byAsset": {}, "missing": _not_computed("2e")}


# Data quality (R-DRV-9): the manifest and failure records as rows, in manifest order (T-36).


def data_quality(pack: Pack) -> DataQuality:
    calls = pack.manifest["calls"]
    return {
        "failedCalls": failed_calls(pack),
        "truncations": [row for call in calls for row in _truncations(call)],
        "coverageFailures": [
            {"name": call["name"], "leg": leg["leg"], "state": leg["value"]}
            for call in calls
            for leg in call.get("coverageNotOk") or []
        ],
        "partialTotals": [
            {"name": call["name"], **call["totalExceedsRows"]}
            for call in calls
            if isinstance(call.get("totalExceedsRows"), dict)
        ],
    }


def failed_calls(pack: Pack) -> list[FailedCall]:
    """Every failure record, every failed manifest row, and every 2xx body that is not a JSON
    object, in manifest order; records with no manifest row follow, by name (T-39)."""
    calls = pack.manifest["calls"]
    rows = [row for call in calls if (row := _failed_row(pack, call)) is not None]
    listed = {call["name"] for call in calls}
    rows += [_failed_call(pack.failures[name]) for name in sorted(set(pack.failures) - listed)]
    return rows


def _failed_row(pack: Pack, call: Mapping) -> FailedCall | None:
    name = call["name"]
    if name in pack.failures:
        return _failed_call(pack.failures[name])
    base = {"name": name, "endpoint": call["endpoint"], "status": call["status"]}
    if not call["ok"]:
        return {**base, "error": NO_RECORD}
    if name in pack.raw and not _is_json_object(pack.raw[name]):
        error = f"answered {call['status']}, but the body is not a JSON object; {NOT_READ}"
        return {**base, "error": error}
    return None


def _is_json_object(body: bytes) -> bool:
    """Whether the body parses to a JSON object, the same test pull.read_flags makes."""
    try:
        return isinstance(json.loads(body), dict)
    except (ValueError, RecursionError):  # RecursionError: a body nested too deep to parse
        return False


def _failed_call(record: Mapping) -> FailedCall:
    """The failure record's own fields, the whole error kept (DATA-CONTRACTS section 1.1)."""
    return {
        "name": record["name"],
        "endpoint": record["endpoint"],
        "status": record["status"],
        "error": record["error"],
    }


def _truncations(call: Mapping) -> list[Truncation]:
    """One row per cause: flags the API set true, and a page that reached its limit (T-36)."""
    rows: list[Truncation] = []
    if call.get("truncated") is True:
        paths = call["truncatedAt"]
        verb = "is" if len(paths) == 1 else "are"
        note = f"The response says it was cut: {', '.join(paths)} {verb} true."
        rows.append({"name": call["name"], "note": note})
    at_limit = call.get("rowsAtLimit")
    if isinstance(at_limit, dict):
        note = (
            f"Rows served ({at_limit['rows']}) reached the limit ({at_limit['limit']}); "
            "the page may be cut."
        )
        rows.append({"name": call["name"], "note": note})
    return rows
