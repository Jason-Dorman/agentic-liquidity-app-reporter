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

# The finding surfaces in catalogue order (Q7, T-41). These names match pull.CATALOGUE.
FINDING_SURFACES = (
    "flow_chains",
    "bridge_across",
    "bridge_cctp",
    "bridge_stargate",
    "confidence",
    *(f"liquidity_{asset}" for asset in ("USDT", "USDC", "DAI", "PYUSD", "USDe")),
)
ROW_FINDINGS = {"flow_chains": "chains", "confidence": "corridors"}  # a finding on each row
COMPARED_FIELDS = ("kind", "severity")
TIERS_NOT_READ = (
    "No tier comparison: the confidence call failed, or its body does not give every "
    "corridor with its id."
)


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
    "TierChange",
    {"corridor": str, "from": str | None, "to": str | None, "observedAt": str | None},
)


class Tier(TypedDict):
    recommendation: str | None
    observedAt: str | None


class Findings(TypedDict):
    surfaces: list[str]
    surfacesMissing: list[str]
    new: list[FindingRef]
    gone: list[FindingRef]
    stillOpen: list[FindingRef]
    changed: list[FindingChange]
    open: dict[str, list[FindingRef]]  # by surface; a key means that surface's set is known
    note: str | None
    missing: str | None


class CorridorTierChanges(TypedDict):
    changes: list[TierChange]
    tiers: dict[str, Tier] | None  # null while no tier map is known (T-40)
    note: str | None
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


# Finding comparison (R-DRV-1, T-40 to T-42). Each surface is compared with its own set in the
# previous run's `open`, by id equality (Q7). A surface not read today carries its previous set.


def findings(pack: Pack, previous: Derived | None) -> Findings:
    """new, gone, stillOpen and changed against the previous run's open set (T-40, T-41)."""
    today = _read_surfaces(pack)
    base = _previous_open(previous)
    before = base or {}
    rows: dict[str, list] = {"new": [], "gone": [], "stillOpen": [], "changed": []}
    for name in FINDING_SURFACES:
        if name in today and name in before:
            for key, part in _compare(before[name], today[name]).items():
                rows[key] += part
    unseen = [name for name in today if name not in before]
    return {
        "surfaces": list(today),
        "surfacesMissing": [name for name in FINDING_SURFACES if name not in today],
        **rows,
        "open": {
            name: today[name] if name in today else before[name]
            for name in FINDING_SURFACES
            if name in today or name in before
        },
        "note": _findings_note(previous, base, unseen),
        "missing": None,
    }


def _read_surfaces(pack: Pack) -> dict[str, list[FindingRef]]:
    """Each readable surface's findings, sorted by id, in catalogue order. A repeated id keeps
    its first entry (T-42). A surface left out is missing (T-41)."""
    failed = _failed_names(pack)
    seen: set[str] = set()
    read: dict[str, list[FindingRef]] = {}
    for name in FINDING_SURFACES:
        refs = _surface_refs(name, _body(pack, name, failed))
        if refs is not None:
            read[name] = sorted(_first_of_each(refs, seen), key=lambda ref: ref["id"])
    return read


def _first_of_each(refs: list[FindingRef], seen: set[str]) -> list[FindingRef]:
    """The refs whose id is not in `seen`, each id once; adds them to `seen`."""
    first: list[FindingRef] = []
    for ref in refs:
        if ref["id"] not in seen:
            seen.add(ref["id"])
            first.append(ref)
    return first


def _surface_refs(name: str, body: Mapping | None) -> list[FindingRef] | None:
    """The surface's findings, or None unless the body gives every one with a string id."""
    objects = _finding_objects(name, body) if body is not None else None
    if objects is None or not all(_has_id(found, "id") for found in objects):
        return None
    return [
        {
            "id": found["id"],
            "surface": name,
            "kind": found.get("kind"),
            "severity": found.get("severity"),
        }
        for found in objects
    ]


def _finding_objects(name: str, body: Mapping) -> list | None:
    """Where each surface holds its findings (T-41). Liquidity: `findings[]`, one per band,
    since `finding` copies the widest one."""
    if name in ROW_FINDINGS:
        rows = body.get(ROW_FINDINGS[name])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return None
        return [row.get("finding") for row in rows]
    if name.startswith("liquidity_"):
        found = body.get("findings")
        return found if isinstance(found, list) else None
    return [body.get("finding")]


def _compare(before: list[FindingRef], after: list[FindingRef]) -> dict[str, list]:
    """One surface's new, gone, stillOpen and changed, each sorted by id."""
    earlier = {ref["id"]: ref for ref in before}
    now = {ref["id"] for ref in after}
    still = [ref for ref in after if ref["id"] in earlier]
    return {
        "new": [ref for ref in after if ref["id"] not in earlier],
        "gone": sorted((ref for ref in before if ref["id"] not in now), key=lambda r: r["id"]),
        "stillOpen": still,
        "changed": [
            {"id": ref["id"], "field": field, "from": earlier[ref["id"]].get(field),
             "to": ref[field]}
            for ref in still
            for field in COMPARED_FIELDS
            if earlier[ref["id"]].get(field) != ref[field]
        ],
    }


def _previous_open(previous: Derived | None) -> dict[str, list[FindingRef]] | None:
    """The previous run's open set by surface, or None when it holds none, as a file from
    before pass 2b does (T-40)."""
    found = _section(previous, "findings").get("open")
    if not isinstance(found, dict):
        return None
    usable = all(
        isinstance(refs, list) and all(_has_id(ref, "id") for ref in refs)
        for refs in found.values()
    )
    return found if usable else None


def _findings_note(previous: Derived | None, base: dict | None, unseen: list[str]) -> str | None:
    if previous is None:
        return FIRST_RUN_NOTE
    if base is None:
        return f"The previous run ({previous['runDate']}) holds no findings to compare with."
    if unseen:
        return f"No earlier reading to compare with: {', '.join(unseen)}."
    return None


# Corridor tier changes (R-DRV-2, T-43): each corridor's `recommendation` against the previous
# run's tiers. A corridor that appears has `from` null; one that leaves has `to` null.


def corridor_tier_changes(pack: Pack, previous: Derived | None) -> CorridorTierChanges:
    base = _previous_tiers(previous)
    read = _read_tiers(pack)
    note = _tiers_note(previous, base)
    if read is None:
        return {"changes": [], "tiers": base, "note": note, "missing": TIERS_NOT_READ}
    tiers, observed_at = read
    changes = _tier_changes(base, tiers, observed_at) if base is not None else []
    return {"changes": changes, "tiers": tiers, "note": note, "missing": None}


def _read_tiers(pack: Pack) -> tuple[dict[str, Tier], str | None] | None:
    """Each corridor's tier and the body's `updatedAt`, or None unless the body gives every
    corridor with a string `corridorId`. A repeated corridor keeps its first row."""
    body = _body(pack, "confidence", _failed_names(pack))
    rows = body.get("corridors") if body is not None else None
    if not isinstance(rows, list) or not all(_has_id(row, "corridorId") for row in rows):
        return None
    updated_at = body.get("updatedAt")
    observed_at = updated_at if isinstance(updated_at, str) else None
    tiers: dict[str, Tier] = {}
    for row in rows:
        tiers.setdefault(
            row["corridorId"],
            {"recommendation": row.get("recommendation"), "observedAt": observed_at},
        )
    return tiers, observed_at


def _tier_changes(
    before: dict[str, Tier], after: dict[str, Tier], observed_at: str | None
) -> list[TierChange]:
    changes: list[TierChange] = []
    for corridor in sorted(before.keys() | after.keys()):
        old = before.get(corridor, {}).get("recommendation")
        new = after.get(corridor, {}).get("recommendation")
        if old != new:
            change = {"corridor": corridor, "from": old, "to": new, "observedAt": observed_at}
            changes.append(change)
    return changes


def _previous_tiers(previous: Derived | None) -> dict[str, Tier] | None:
    """The previous run's tiers, or None when it holds none (T-40)."""
    found = _section(previous, "corridorTierChanges").get("tiers")
    if not isinstance(found, dict) or not all(isinstance(t, dict) for t in found.values()):
        return None
    return found


def _tiers_note(previous: Derived | None, base: dict | None) -> str | None:
    if previous is None:
        return FIRST_RUN_NOTE
    if base is None:
        return f"The previous run ({previous['runDate']}) holds no corridor tiers to compare with."
    return None


# Reading bodies for the comparisons.


def _failed_names(pack: Pack) -> set[str]:
    return {row["name"] for row in failed_calls(pack)}


def _body(pack: Pack, name: str, failed: set[str]) -> dict | None:
    """The parsed body of a call that did not fail, or None."""
    if name in failed or name not in pack.raw:
        return None
    return _json_object(pack.raw[name])


def _section(previous: Derived | None, key: str) -> Mapping:
    found = previous.get(key) if previous is not None else None
    return found if isinstance(found, dict) else {}


def _has_id(value: object, key: str) -> bool:
    return isinstance(value, dict) and isinstance(value.get(key), str)


# Stubs: each returns its empty shape until its pass lands (T-35).


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
    if name in pack.raw and _json_object(pack.raw[name]) is None:
        error = f"answered {call['status']}, but the body is not a JSON object; {NOT_READ}"
        return {**base, "error": error}
    return None


def _json_object(body: bytes) -> dict | None:
    """The body if it parses to a JSON object, the same test pull.read_flags makes, else None."""
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):  # RecursionError: a body nested too deep to parse
        return None
    return parsed if isinstance(parsed, dict) else None


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
