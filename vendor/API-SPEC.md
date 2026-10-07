> **Vendored copy.** Copied into this repo on 2026-10-07 from the Blockford Corridor Scout app repo (spec version 1.0, latest entry dated 2026-09-28). Do not edit here; re-copy from the app repo and update this line.

# API Specification
## Corridor Scout REST API

**Version:** 1.0  
**Base URL:** `https://corridorscout.com/corridor-scout/api`

> **⚠ THE `/corridor-scout` SEGMENT IS THE APP'S MOUNT POINT, NOT AN API VERSION PREFIX**
> (moved 2026-08-30, AUDIT #46 / D36). The whole application is served under a Next
> `basePath`, so the pages live at `/corridor-scout/*` and **`/api/*` moved with them**.
> The bare origin `/` answers **307** to `/corridor-scout` — temporary, deliberately and
> permanently so, because the bare domain is bound for the Blockford main site.
>
> ⚠ **Every worked example below was updated with it.** A curl left on the old path returns
> **404**, not an error envelope — there is no route there to produce one, so the response
> carries none of this spec's typed vocabulary.
>
> ⚠ **A browser client must not hard-code the prefix.** `src/lib/base-path.ts` declares it
> once and `apiFetcher` applies it, which is why in-repo call sites are still written
> `/api/…`. See CLAUDE.md.

---

## Overview

The Corridor Scout API provides programmatic access to cross-chain bridge health data. All endpoints return JSON and support CORS for browser-based access.

### Rate Limits
- **Anonymous (planned, not yet enforced):** 100 requests/minute per IP
- **Authenticated (future):** 1000 requests/minute per API key

### Response Format
All responses follow this structure:

```typescript
// Success — flat top-level payload (no data/meta wrapper)
{
  "status": "operational",
  ...
}
// Some endpoints (health, flow/chains, rpc-health) include a top-level
// `updatedAt` (ISO8601) field. There is no `meta` object or `cached` field.

// Error
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid bridge parameter",
    "details": { "field": "bridge", "value": "unknown" }
  }
}
```

`details` (`{ field, value }`) is present only on `VALIDATION_ERROR`; `NOT_FOUND` and `INTERNAL_ERROR` return only `code` + `message`; the 503s (`POOL_SNAPSHOT_UNAVAILABLE`, `GAS_UNAVAILABLE`) additionally carry a `reason` field instead of `details`.

---

## Endpoints

### GET /api/health

System-wide health overview.

#### Response

```typescript
interface HealthResponse {
  status: "operational" | "degraded" | "down";
  corridorsMonitored: number;
  corridorsHealthy: number;
  corridorsIdle: number;   // no transfers in the window — quiet, not failing (§10.2)
  corridorsDegraded: number;
  corridorsDown: number;
  transfers24h: number;
  successRate24h: number | null;  // 0-100, null when no transfers have resolved
  activeAnomalies: number;
  updatedAt: string;       // ISO8601
}
```

`corridorsMonitored === corridorsHealthy + corridorsIdle + corridorsDegraded + corridorsDown`.
The system-wide `status` down/degraded fractions are taken over ACTIVE corridors
(healthy + degraded + down), excluding `idle` (DATA-MODEL §10.5).

#### Example

```bash
curl https://corridorscout.com/corridor-scout/api/health
```

```json
{
  "status": "operational",
  "corridorsMonitored": 47,
  "corridorsHealthy": 41,
  "corridorsIdle": 3,
  "corridorsDegraded": 2,
  "corridorsDown": 1,
  "transfers24h": 15234,
  "successRate24h": 98.7,
  "activeAnomalies": 2,
  "updatedAt": "2026-02-21T14:35:00Z"
}
```

---

### ~~GET /api/flight~~ — **REMOVED (Phase D2, 2026-08-28)**

**Hard cutover, no compat shim (decision D8)** — there are no external consumers
pre-public, and a shim that nobody exercises is a decoy, not a fallback. The route,
the `FlightVelocity` component and its test suite are deleted, not deprecated.

**Replacement: [`GET /api/flow/chains`](#get-apiflowchains).** It serves the same
flow-ratio LFV leg at full fidelity (now under `flow`) and adds the settlement leg
plus the §9B composite status. Field mapping for a migrating consumer:

| `/api/flight` | `/api/flow/chains` |
|---|---|
| `chains[].flowRatio` | `chains[].flow.flowRatio` (**now nullable** — see below) |
| *(no equivalent)* | `coverage.flowLeg` — **check it**: `"read_failed"` means every flow field is absent because the read failed, not because the chains were quiet |
| `chains[].netFlowUsd` / `inboundUsd` / `outboundUsd` / `totalVolumeUsd` | same names under `chains[].flow` (all nullable) |
| `chains[].status` | `chains[].flow.status` |
| `chains[].windowHours` | `chains[].flow.windowHours` (also top-level `windowHours`) |
| `chains[].alert` | **gone** — read `chains[].compositeStatus === 'flight'` |

⚠ **`flowRatio` IS NULLABLE ON THE NEW ROUTE AND WAS NOT ON THE OLD ONE.** The new
route serves the union of both legs, so a chain observed only by the settlement leg
appears with no flow reading. `null` there means *not measured*; `0` would assert a
perfectly balanced chain. A consumer that reads it as a number will read absence as
balance.

⚠ **`alert` is gone deliberately.** It flagged `flow.status === 'flight'` — the flow
leg alone. Under §9B a published `flight` requires BOTH a flow signal and a
pool-pressure signal, so the old flag would now fire on outflows the composite
declines to escalate.

---

### GET /api/flow/chains

Per-chain flow (§9 LFV) composed with settlement health (§9A BSH) into the §9B
composite status. The Capital Flow surface's read. Replaces `/api/flight`.

Both legs are computed **live** — off the transfers table and the latest pool
snapshots + AcrossConfigStore — so the reading never depends on a capture cron
having run. Cached 60s in Redis.

**No query parameters, deliberately.** LIQUIDITY-METRICS-REFACTOR §7.2 sketches
`?bridge=` and `?window=`; neither ships:

- **`?bridge=`** would narrow the settlement leg to one bridge while the flow leg
  still covered every bridge on the chain — a composite whose two legs are drawn
  from different populations. The per-bridge breakdown is served whole in
  `settlement.readings`, and `/api/bridges/:bridge/health` answers the per-bridge
  question directly.
- **`?window=`** would return differently-calibrated numbers under one field name:
  the LFV noise floor, pure-dollar rule, flight ratio and dwell offsets are all
  calibrated for 24h (DATA-MODEL §9, decision D5).

#### Response

```typescript
interface FlowChainsResponse {
  windowHours: number;          // 24
  coverage: {
    // 'read_failed' = the flow leg could not be read AT ALL this tick, so every
    // chain's flow fields are absent for an infrastructure reason — NOT because the
    // chains were quiet. A degraded payload is never written to the cache.
    flowLeg: "ok" | "read_failed";
    // FF-2. Whether the PERSISTED transition log (lfv_snapshots) could be read this tick —
    // the only source of "how long has this status held". 'read_failed' means every
    // finding's `flowStatusHold` is null for ONE infrastructure reason, not because five
    // chains have never transitioned. A degraded payload is never cached on either leg.
    statusHoldLeg: "ok" | "read_failed";
    // D60. Whether the materiality gate (DATA-MODEL §9B.2a) was FULLY applied on this
    // response. 'volume_read_failed': the 30-day median read failed; 'price_unavailable':
    // at least one spoke asset could not be priced (D60.7). Either way the spokes the gate
    // could not evaluate were INCLUDED — each stamped with the reason the gate reached first
    // (`target_unavailable` / `price_unavailable` / `volume_unavailable`; non-spokes stay
    // `not_a_spoke`) — so a de-minimis spoke MAY be binding a chain composite. Never cached.
    materialityLeg: "ok" | "volume_read_failed" | "price_unavailable";
    // There is deliberately no `settlementLeg` sibling — see the note below.
  };
  chains: ChainRow[];           // EVERY monitored chain, always; ranked worst-flow first
  updatedAt: string;
}

interface ChainRow {
  chain: string;
  // DATA-MODEL §9B.2. `flight` requires BOTH legs; `pressure` is settlement-only.
  compositeStatus: "stable" | "inflow" | "outflow" | "pressure" | "flight" | "insufficient_data";
  compositeReason: string;      // names the leg that decided the label
  flow: {
    status: "stable" | "inflow" | "outflow" | "flight" | "insufficient_data";
    // Why the flow fields are absent, when they are. null whenever the leg was read.
    unavailableReason: "lfv_read_failed" | null;
    flowRatio: number | null;   // null = no LFV reading for this chain — NOT 0
    netFlowUsd: number | null;
    inboundUsd: number | null;
    outboundUsd: number | null;
    totalVolumeUsd: number | null;
    windowHours: number;
  };
  settlement: {
    worstLevel: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
    worstScore: number | null;  // null whenever worstLevel is "unknown"
    bindingBridge: string | null;   // which reading carried worstLevel
    bindingAsset: string | null;
    reason: string;             // "bsh_ranked" | "bsh_unavailable" | "bsh_no_readings"
                                // | "bsh_all_de_minimis" (D60: readings exist, every one
                                //   excluded — UNESTABLISHED, not healthy)
    contributingCount: number;  // ELIGIBLE readings that carried a RANKED level (D60)
    unknownCount: number;       // readings present but uncomputable (an unknown reading is
                                //   never gated, so this is the full unknown count — D60.7)
    readings: Array<{           // EVERY reading, excluded ones included
      bridge: string;
      asset: string;
      level: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
      score: number | null;
      reason: string;
      method: string;
      underlying: Record<string, unknown>;  // bridge-specific raw signal
      materiality:                          // D60 — the gate's verdict on THIS reading
        | "not_ranked"                                                  // level unknown: never gated
        | "not_a_spoke" | "material_by_usd" | "material_by_share"       // eligible
        | "target_unavailable" | "price_unavailable" | "volume_unavailable" // eligible, gate NOT evaluated (loud)
        | "de_minimis";                                                 // EXCLUDED from the composite
    }>;
    excluded: Array<{           // D60 — what the materiality gate removed from the composite
      bridge: string;
      asset: string;
      level: "healthy" | "degraded" | "pressure" | "critical";  // never unknown (D60.7)
      score: number | null;
      target: number;           // dataworker target, TOKEN UNITS (5000 = 5,000 USDT); always > 0
      targetUsd: number;
      medianDailyVolumeUsd: number;   // the chain's 30-day median daily bridge volume
      volumeShare: number | null;     // targetUsd / median; null when the median is 0
      reason: "de_minimis";
    }>;
  };
  finding: FlowFinding;         // FF-2 — the Scout's conclusion for this chain
}
```

#### `finding` — the Scout's conclusion (FF-2 / D44.4, 2026-09-08)

The deterministic conclusion the Capital Flow surface opens with, served as a first-class
object so the same conclusion reaches humans and machines from ONE derivation
(`src/lib/findings/flow.ts`, pure). Composed from the row it sits on and nothing else,
except the status hold below — so it can never cite a figure the response does not carry.

```typescript
interface FlowFinding {
  id: string;                 // content-addressed, e.g. "flow-base-flight-unconfirmed" —
                              // stable for the same condition; NOT a sequence number
  kind: 'flight_confirmed' | 'flight_unconfirmed' | 'settlement_pressure_only'
      | 'net_outflow' | 'net_inflow' | 'no_directional_signal' | 'not_concluded';
  severity: 'notable' | 'elevated' | 'none' | 'unknown';
  chain: string;
  compositeStatus: CompositeChainStatus;  // echoed from the row, never recomputed
  compositeReason: string;                // the machine token, verbatim
  windowHours: number;
  headline: string;           // one deterministic sentence, leading with the MARKET FACT —
                              // "$210,000 net outflow from base over 24h, while settlement on
                              // across/WETH was under pressure." Direction is a WORD, never a
                              // sign; the state word is not in it (D59, 2026-09-11)
  narrative: {                // the three questions, kept apart (D43)
    whatHappened: string;
    comparedWith: string | null;
    whyItMatters: string;
  };
  binding: {                  // the settlement reading that carried the worst RANKED level
    bridge: string | null;
    asset: string | null;
    level: BshLevel;
    score: number | null;
    reason: string;
  };
  flowStatusHold: { status: LfvStatus; seconds: number } | null;
  detail: string[];
  evidence: Array<{ label: string; detail: string }>;
  coverage: {                 // ⚠ EVIDENCE METADATA, NOT "CONFIDENCE" (D9/§6)
    flowLeg: 'measured' | 'quiet' | 'absent';
    flowAbsenceReason: string | null;   // non-null exactly when flowLeg is 'absent'
    settlementRanked: number;
    settlementUnknown: number;
    settlementExcluded: number; // D60 — de-minimis exclusions; each named in `caveats`
    caveats: string[];        // named limits — rendered, never hidden. Always: the
                              // worst-observed-leg rule + "flow is context only"; then, as
                              // applicable: initiations-only, structurally unmeasurable assets,
                              // an unavailable reading, and the settlement-absent consequence
                              // ("…the route tier therefore rests on observed transfer health
                              // alone." / "Neither route signal is currently observable…")
  };
}
```

⚠ **THE PROSE IS A PRESENTATION PROJECTION OF THE STRUCTURED FIELDS (D62, 2026-09-12).** Every
string above is composed from `recommendation`, `recommendationReason`, `settlement`, `observed`
and `destinationChainFlow` on the same row and adds nothing to them; the machine layer —
`kind`, `recommendation`, `recommendationReason`, `corroboration`, `binding.leg`, the
levels, scores, counts, typed absences and reason tokens — is unchanged by the copy pass. A
consumer that needs the token reads the field; the prose no longer carries `bsh_pressure`,
`completionObservableReason` or `lfv_read_failed` as words.

⚠ **`kind` IS NOT `compositeStatus`, AND `flight_unconfirmed` IS WHY.** A chain whose flow
leg classified flight but whose settlement leg did not confirm it is served as
`compositeStatus: "outflow"` with `compositeReason: "flight_unconfirmed_bsh_unavailable"` or
`"flight_not_confirmed_bsh_healthy"`. A consumer keying only on the status word cannot tell
that case from a plain `lfv_outflow_bsh_not_pressured`, and the distinction is the product
(FF spec §8.2). `kind` is therefore derived from the REASON, not the status.

⚠ **`flowStatusHold` IS THE FLOW LEG'S HOLD TIME, NEVER THE COMPOSITE'S — and the field
carries its own `status` so it cannot be read as one.** `lfv_snapshots` is write-on-change
over the `LfvStatus`; the composite is `LfvStatus × BSH` and flips the instant a
densely-captured settlement reading moves. Quoting this duration under the composite would
publish "in flight for 4h 35m" about an escalation that began four minutes ago. A composite
hold time would need a persisted composite transition log, which does not exist (§11
backlog).

⚠ **`null` HERE DOES NOT MEAN "just started".** The route only quotes a duration when the
flow leg was actually READ **and** the persisted status IS the live one — the live reading is computed per request while the log is
written by a 5-minute collector, so any chain that transitioned since the last tick has a
persisted row describing its PREVIOUS status. When no duration can be quoted the reason is
named in `coverage.caveats`, from four:

| Condition | Caveat says (reader copy since D59) |
|---|---|
| `lfv_hold_status_not_yet_captured` | "Flow-state duration is unavailable because the current state has not yet been recorded in the transition history. This does not mean the state is new." (the live reading is per request; the history is written by a 5-minute collector) |
| `lfv_hold_no_history` | "Flow-state duration is unavailable because no transition history has been recorded for this chain. This does not mean the state is new." |
| `lfv_hold_read_failed` | "Flow-state duration could not be retrieved for this request." (`coverage.statusHoldLeg: "read_failed"`) |
| `lfv_hold_no_live_status` | "Flow-state duration is unavailable because there is no current readable flow state for this request." — the FLOW leg was not read this request (D51.4) |

⚠ **NO PROBABILITY, NO CONFIDENCE GRADE, NO CAUSAL PROSE.** Pinned by the shared
forbidden-vocabulary guard (`src/lib/findings/shared.ts`), applied to the whole serialized
object.

⚠ **`narrative.whyItMatters` RENDERS THE COMPOSITE REASON, AND THAT RENDERING DEPENDS ON
WHETHER ANY SETTLEMENT READING RANKED — NOT ON THE REASON TOKEN ALONE (D51.1).** (✎ It was
`detail[0]` too until D52.2; since D59 `detail` carries the most-constrained settlement reading
with its evaluated/unavailable counts and the flow-signal persistence sentence, and the card
renders those two facts as a compact strip rather than printing `detail` as a list.)
`composeChainStatus` branches on `isPressure(level)`, which is false for a **healthy** reading
and equally false for an **unreadable** one, so `lfv_only`, `lfv_insufficient_data` and
`lfv_outflow_bsh_not_pressured` are each emitted in both cases. A consumer keying off the
token alone therefore **cannot** tell "settlement was read and was calm" from "settlement was
never read" — check `settlement.worstLevel !== 'unknown'` (equivalently
`finding.coverage.settlementRanked > 0`) before drawing any conclusion about the settlement
leg from these three. The served prose already does this and says which case it is in.

**Two absences that look alike and are not.** `reason: "bsh_no_readings"` means we
hold nothing for this chain; `"bsh_unavailable"` means every reading we hold said it
could not be computed (stale snapshot, unreadable ConfigStore). An operator triages
those differently, so they are never collapsed.

⚠ **A THIRD, SINCE D60 (2026-09-11): `"bsh_all_de_minimis"`.** Readings exist and computed
fine, but every one is from a DE-MINIMIS spoke (target < $25,000 AND < 2% of the chain's
30-day median daily volume — DATA-MODEL §9B.2a) and none may bind the chain composite. The
settlement leg is **unestablished** — the composite takes `worstLevel: "unknown"` — and the
finding says so in its own words (headline "Settlement is unestablished: no reading on this
chain is material enough to bind it."). Excluded readings are served in full on
`settlement.excluded[]`, stay in `readings[]` stamped `materiality: "de_minimis"`, and each is
named in `finding.coverage.caveats` ("across/USDT excluded from chain composite (de minimis:
target 5,000 USDT ≈ $5,000, below the materiality floor); its own reading is critical."). When
an exclusion exists, the ranked copy says "**material** settlement readings did not show
pressure" and the headline "not under pressure **on any material route**" (D60.7) — the row
still carries the excluded reading's own level. The gate applies to THIS endpoint only —
`/api/corridors/confidence` and `/api/bridges/:bridge/health` still rank that reading. An
`unknown` reading is NEVER gated (`materiality: "not_ranked"`, counted in `unknownCount`), and a
zero target is `target_unavailable`, not a $0 notional (D60.7). A gate that could not be
evaluated (no price, no median, no target) INCLUDES the spoke and says so on `materiality`;
`coverage.materialityLeg` other than `"ok"` means the gate was not fully applied on this
response and the payload was not cached.

**The flow leg has the same split, and it is why `unavailableReason` exists.**
`status: "insufficient_data"` with `unavailableReason: null` means *this chain lacks a
full 24h observation window* — a quiet chain. `unavailableReason: "lfv_read_failed"`
(always with `coverage.flowLeg: "read_failed"`) means *our reader failed*. `LfvStatus`
has no member for the second, so it is carried alongside rather than smuggled into the
first.

⚠ **THE CHAIN SET IS ENUMERATED FROM THE MONITORED-CHAIN REGISTRY, NOT FROM THE DATA.**
Every monitored chain appears in every response, whatever either leg returned. This is
load-bearing and was a real defect until 2026-08-28 (AUDIT #40 / D31.5): the set used
to be the union of the two legs, and because `fetchChainLfv` **rejects** on a DB fault
while `fetchBshReadings` swallows its own failures and resolves `[]`, a DB outage
collapsed the response to `chains: []` and served it **200** — a total outage rendered
as "we monitor no chains". A chain carrying a BSH reading but absent from the registry
is still surfaced, so nothing is dropped in the other direction.

⚠ **NO `coverage.settlementLeg`, AND THE OMISSION IS THE HONEST ANSWER.**
`fetchBshReadings` swallows each bridge's rejection in its own `allSettled` and
resolves `[]`, so this route **cannot** distinguish "both bridge fetchers threw" from
"nothing is captured". Emitting `settlementLeg: "ok"` in that state would be a
fabrication. What is knowable is served per chain, in `settlement.reason`.

**`unknown` never ranks.** A BSH reading of `unknown` is an absence, not a level. It
cannot make `worstLevel` worse (manufacturing pressure from a stale snapshot) and
cannot make it better (manufacturing health from one). It is excluded from the
ordering and counted in `unknownCount`.

#### Example

```bash
curl https://corridorscout.com/corridor-scout/api/flow/chains
```

```json
{
  "windowHours": 24,
  "coverage": { "flowLeg": "ok", "statusHoldLeg": "ok", "materialityLeg": "ok" },
  "chains": [
    {
      "chain": "base",
      "compositeStatus": "flight",
      "compositeReason": "lfv_outflow_with_bsh_pressure",
      "flow": {
        "status": "outflow",
        "unavailableReason": null,
        "flowRatio": -0.42,
        "netFlowUsd": -210000,
        "inboundUsd": 145000,
        "outboundUsd": 355000,
        "totalVolumeUsd": 500000,
        "windowHours": 24
      },
      "settlement": {
        "worstLevel": "pressure",
        "worstScore": 0.31,
        "bindingBridge": "across",
        "bindingAsset": "WETH",
        "reason": "bsh_ranked",
        "contributingCount": 2,
        "unknownCount": 0,
        "readings": [
          {
            "bridge": "across",
            "asset": "WETH",
            "level": "pressure",
            "score": 0.31,
            "reason": "ratio 0.28 below healthy band",
            "method": "target_ratio",
            "underlying": { "currentBalance": 112.4, "target": 400 },
            "materiality": "material_by_usd"
          },
          {
            "bridge": "cctp",
            "asset": "USDC",
            "level": "healthy",
            "score": 0.94,
            "reason": "latency within baseline",
            "method": "latency_baseline",
            "underlying": { "currentMedianSeconds": 812, "baselineMedianSeconds": 795 },
            "materiality": "not_a_spoke"
          }
        ],
        "excluded": []
      },
      "finding": {
        "id": "flow-base-flight-confirmed",
        "kind": "flight_confirmed",
        "severity": "elevated",
        "chain": "base",
        "compositeStatus": "flight",
        "compositeReason": "lfv_outflow_with_bsh_pressure",
        "windowHours": 24,
        "headline": "$210,000 net outflow from base over 24h, while settlement on across/WETH was under pressure.",
        "narrative": {
          "whatHappened": "$210,000 net outflow from base over 24h.",
          "comparedWith": "$145,000 in · $355,000 out over 24h.",
          "whyItMatters": "Capital was leaving the chain while settlement capacity was under pressure. Blockford classifies this combination as flight."
        },
        "binding": {
          "bridge": "across",
          "asset": "WETH",
          "level": "pressure",
          "score": 0.31,
          "reason": "bsh_ranked"
        },
        "flowStatusHold": { "status": "outflow", "seconds": 16500 },
        "detail": [
          "Most constrained settlement reading: across / WETH, under pressure (BSH 0.31). 2 settlement readings evaluated.",
          "The flow signal has remained in net outflow for 4h 35m. This duration applies to flow only; settlement conditions can change independently."
        ],
        "evidence": [
          { "label": "Chain inflows and outflows", "detail": "inbound/outbound over 24h · composite status flight" },
          { "label": "Flow-state history", "detail": "records flow-state changes rather than every observation" },
          { "label": "Settlement readings", "detail": "2 evaluated · 0 unavailable · most constrained across/WETH" }
        ],
        "coverage": {
          "flowLeg": "measured",
          "flowAbsenceReason": null,
          "settlementRanked": 2,
          "settlementUnknown": 0,
          "settlementExcluded": 0,
          "caveats": ["Net flow is measured at the chain level and is not attributed to the bridge named in the settlement signal, or to any single bridge."]
        }
      }
    },
    {
      "chain": "optimism",
      "compositeStatus": "insufficient_data",
      "compositeReason": "lfv_insufficient_data",
      "flow": {
        "status": "insufficient_data",
        "unavailableReason": null,
        "flowRatio": null,
        "netFlowUsd": null,
        "inboundUsd": null,
        "outboundUsd": null,
        "totalVolumeUsd": null,
        "windowHours": 24
      },
      "settlement": {
        "worstLevel": "unknown",
        "worstScore": null,
        "bindingBridge": null,
        "bindingAsset": null,
        "reason": "bsh_unavailable",
        "contributingCount": 0,
        "unknownCount": 1,
        "readings": [
          {
            "bridge": "across",
            "asset": "WETH",
            "level": "unknown",
            "score": null,
            "reason": "spoke_snapshot_unavailable",
            "method": "target_ratio",
            "underlying": { "target": 50 },
            "materiality": "not_ranked"
          }
        ],
        "excluded": []
      },
      "finding": {
        "id": "flow-optimism-not-concluded",
        "kind": "not_concluded",
        "severity": "unknown",
        "chain": "optimism",
        "compositeStatus": "insufficient_data",
        "compositeReason": "lfv_insufficient_data",
        "windowHours": 24,
        "headline": "No flow measurement is available for optimism over this 24h window. Settlement conditions could not be evaluated.",
        "narrative": {
          "whatHappened": "No flow measurement is available for optimism over this 24h window.",
          "comparedWith": null,
          "whyItMatters": "There is not enough readable flow or settlement data to classify the current condition: the flow condition is unclassified, and no settlement reading could be ranked."
        },
        "binding": {
          "bridge": null,
          "asset": null,
          "level": "unknown",
          "score": null,
          "reason": "bsh_unavailable"
        },
        "flowStatusHold": null,
        "detail": ["…"],
        "evidence": [
          { "label": "Chain inflows and outflows", "detail": "inbound/outbound over 24h · composite status insufficient_data" },
          { "label": "Flow-state history", "detail": "records flow-state changes rather than every observation" }
        ],
        "coverage": {
          "flowLeg": "absent",
          "flowAbsenceReason": "lfv_no_reading",
          "settlementRanked": 0,
          "settlementUnknown": 1,
          "settlementExcluded": 0,
          "caveats": ["…", "Flow-state duration is unavailable because no transition history has been recorded for this chain. This does not mean the state is new."]
        }
      }
    }
  ],
  "updatedAt": "2026-08-28T14:35:00Z"
}
```

⚠ **`comparedWith` IS `null` ON THE SECOND ROW AND THAT IS AN ANSWER, NOT A GAP.** With no
flow reading there is no inbound-against-outbound comparison to state; writing one anyway
is how a surface acquires a reference nobody measured.

---

### GET /api/bridges/:bridge/health

One bridge's BSH readings (DATA-MODEL §9A), grouped by chain, with the
worst-across-chains roll-up. The Bridge Health surface's read.

**It serves BSH and nothing else, on purpose.** The Bridge Health *view* also shows
the operational-event feed and settlement quantiles; both are already served —
`/api/anomalies` owns `operational_event`, `/api/corridors` owns the observed
quantiles. Re-serving either here would be a second computation of one fact. The
view composes three reads.

**The bridge-wide HubPool TVL IS here, as of Phase D-RETIRE (2026-08-29)** — served as
`poolAggregate`, stamped `scope: "bridge_wide"`, and landed in the SAME change that removed
`pool.{tvlUsd,utilization,fragility}` from `/api/corridors` and `/api/corridors/:corridorId`
for HubPool/BurnMint. That simultaneity is the point: the global aggregate must never be
served in two places, because the two would eventually disagree and a reader would have no
way to tell which was true.

**Two D32.2/D17 additions.** `coverage.fetcher` says whether THIS bridge's settlement fetcher
came back — `failed` means *we could not look*, which is not *we hold nothing*. And
`chains[].uncomputable[]` names the assets that can never carry a reading on that chain, with
the structural reason (D17). Both are described below.

#### Status codes

| Situation | Response |
|---|---|
| `bridge` is not a known bridge name | **400** `VALIDATION_ERROR` (with `details`) |
| Known bridge, not monitored (Stargate) | **200**, `captured: false`, `rollup.reason: "bridge_not_monitored"` |
| Monitored bridge, no readings | **200**, `rollup.reason: "bsh_no_readings"` |
| Monitored bridge, every reading uncomputable | **200**, `rollup.reason: "bsh_unavailable"` |

There is **no 404** on this route: every value that reaches the handler is either a
bridge we know (resolves 200) or not a bridge at all (400). See "404 IS FOR IDENTITY".

#### Response

```typescript
interface BridgeHealthResponse {
  bridge: string;
  bridgeModel: "HubPool" | "BurnMint" | "DestPool";
  capacityLabel: string;        // what bounds capacity for this model
  captured: boolean;            // false = known bridge, no collector running
  coverage: {
    /**
     * ⚠ D32.2. Whether THIS bridge's settlement fetcher came back this request.
     * `failed` → we could not look; the roll-up reason is `bsh_fetch_failed`, NOT
     * `bsh_no_readings`. `not_monitored` → no fetcher runs for this bridge at all.
     * Attributed PER FETCHER: another bridge failing never marks this one unlooked-at.
     */
    fetcher: "ok" | "failed" | "not_monitored";
  };
  rollup: {
    level: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
    score: number | null;
    reason: string;
    bindingChain: string | null;
    bindingAsset: string | null;
    contributingCount: number;
    unknownCount: number;
  };
  /**
   * ⚠ ONE ROW PER MONITORED CHAIN (`BRIDGE_CHAINS[bridge]`), unioned with any chain a reading
   * arrived for — NOT the set that happens to have readings. Until 2026-08-30 this was
   * enumerated from the readings, which permanently omitted `ethereum` for Across (its hub
   * produces no reading by design) and with it FOUR uncomputable-by-design pairs, so the
   * served `uncomputable` totalled 10 of 14 and a reader concluded Across was unmonitored on
   * Ethereum. Same defect and same fix as `/api/flow/chains` (AUDIT #40 / D31.5).
   * A chain with no readings emits `assets: []` and a `reason` from the same ladder.
   */
  chains: Array<{
    chain: string;
    worstLevel: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
    worstScore: number | null;
    bindingAsset: string | null;   // worst-across-assets, per D-RETIRE's ruling
    reason: string;
    /**
     * ⚠ D17 — a SEPARATE LIST FROM `assets`, not a null reading inside it. These pairs can
     * never carry a reading here: Across publishes no dataworker spoke target for them, so
     * no row is written at all, permanently. Merging them into `assets` would put a
     * permanent structural absence in the array that carries transient `unknown` readings,
     * which is the conflation the split exists to prevent.
     *
     * Reasons: `across_no_published_spoke_target` · `across_hub_chain_has_no_spoke_target`
     * · `chain_not_monitored_for_bridge` · `bridge_not_monitored`.
     * Derived from `ACROSS_BSH_PAIRS` itself (`src/lib/bsh-coverage.ts`), never a second
     * copy of the allow-list.
     */
    uncomputable: Array<{ asset: string; reason: string }>;
    assets: Array<{
      asset: string;
      level: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
      score: number | null;
      reason: string;
      method: string;
      underlying: Record<string, unknown>;
    }>;
  }>;
  /**
   * ⚠ THE BRIDGE-WIDE POOL FIGURE (Phase D-RETIRE). `null` for a bridge with no such
   * concept at all (DestPool: its pools are per chain); an OBJECT carrying
   * `unavailableReason` when the concept exists and this read produced nothing. Different
   * facts — a consumer renders nothing for the first and a typed absence for the second.
   *
   * `unavailableReason`: `pool_not_applicable_burnmint` (a POSITIVE fact — this model holds
   * no pool, permanently) · `pool_snapshot_unavailable` (no usable snapshot right now) ·
   * `pool_read_failed` (the read itself failed) · `pool_composition_incomplete` (a declared
   * STABLECOIN did not contribute, so the USD sum is WITHHELD rather than served short).
   *
   * ⚠ NEVER AN UNMARKED PARTIAL SUM. Until 2026-08-30 this summed the surviving rows and
   * flagged nothing unless ALL were missing, so a partially-observed bridge-wide TVL was
   * byte-identical on the wire to a complete one — a smaller, healthy-looking pool, omitting
   * exactly the asset that had gone silent (the AUDIT #36 shape). `lib/dap-aggregate` states
   * the same invariant for depth.
   *
   * ⚠ COMPLETENESS IS TWO QUESTIONS. `tvlUsd`/`availableLiquidity` are STABLECOIN-scoped;
   * `assets[]` is POOLED_ASSETS-scoped. A missing stablecoin withholds the USD figures; a
   * missing WETH does not (it never entered the sum) but IS reported in `missingAssets`,
   * because the exhaustion picture is then known-incomplete.
   *
   * ⚠ `assets[].utilization` is PER ASSET, never a TVL-weighted composite (D30.2), and null
   * rather than 0 when no reading was established. ⚠ `tvlUsd` is STABLECOIN-scoped while
   * `assets[]` is POOLED_ASSETS-scoped — valuation and the exhaustion picture have different
   * populations on purpose (AUDIT #39).
   */
  poolAggregate: {
    scope: "bridge_wide";
    /** ⚠ NULL when a declared STABLECOIN did not contribute — never a partial sum. */
    tvlUsd: number | null;
    availableLiquidity: number | null;
    assets: Array<{ asset: string; utilization: number | null }>;
    /** The pooled assets this bridge's aggregate declares (POOLED_ASSETS). */
    expectedAssets: string[];
    contributingAssets: string[];
    /** Declared but ABSENT. Non-empty → incomplete, and the surface says so. */
    missingAssets: string[];
    recordedAt: string | null;
    unavailableReason: string | null;
  } | null;
  /**
   * ⚠ THE SCOUT'S CONCLUSION for this bridge (FF-3, decision D53). Derived server-side by
   * `src/lib/findings/bridge.ts` from THE BODY THAT SHIPS and serialized once, so the same
   * conclusion reaches the surface and a machine consumer from one derivation — and so a
   * sentence can never cite a figure this response does not carry.
   *
   * ⚠ IT IS PRESENT ON EVERY 200, INCLUDING `captured: false`. An optional finding would
   * force a consumer to write its own fallback conclusion, which is precisely what serving
   * the conclusion removes.
   *
   * ⚠ RENDER IT, DO NOT REASSEMBLE IT. `level`, `score`, `reason`, `bindingChain` and
   * `bindingAsset` are ECHOES of `rollup` — never recomputed — so the two can never
   * disagree on one screen.
   *
   * ⚠⚠ `nativeCondition.unit` IS LOAD-BEARING. For Across (`target_ratio`) both figures are
   * HUMAN TOKEN UNITS against a per-L1-token dataworker spoke target, and NO price leg is
   * read anywhere on the BSH path. A consumer that renders them with a currency symbol is
   * wrong — invisibly on USDT, by roughly three orders of magnitude on WETH.
   */
  finding: {
    /** Content-addressed and stable for the same condition — NOT a sequence number. */
    id: string;
    kind: "settlement_constrained" | "settlement_degraded" | "settlement_healthy" | "not_concluded";
    severity: "notable" | "elevated" | "none" | "unknown";
    bridge: string;
    bridgeModel: string;
    /** Echoes of `rollup`, above. */
    level: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
    score: number | null;
    reason: string;
    bindingChain: string | null;
    bindingAsset: string | null;
    headline: string;
    /**
     * The three questions kept apart. `comparedWith` is nullable and null is an answer.
     * ⚠ READER-FACING SINCE D61 (2026-09-11): `whyItMatters` is rendered under the label
     * "What it means" (the property name is unchanged to avoid API churn). Every sentence
     * here restates a structured field beside it — a consumer never needs to parse prose.
     */
    narrative: { whatHappened: string; comparedWith: string | null; whyItMatters: string };
    /** The raw signal behind the score, IN THE UNIT IT WAS MEASURED IN. */
    nativeCondition:
      | { kind: "balance_vs_target"; method: "target_ratio"; unit: "token_units";
          asset: string; currentBalance: number; target: number; ratio: number | null; text: string }
      | { kind: "latency_vs_baseline"; method: "latency_baseline"; unit: "seconds";
          currentMedianSeconds: number; baselineMedianSeconds: number; text: string }
      | { kind: "unrenderable"; method: string; reason: string; text: string }
      | null;
    /**
     * ⚠ `not_assessable` IS NOT A HEDGE. With fewer than two ranked readings there is no
     * rest-of-bridge, so calling a constraint "isolated" would assert breadth nobody has.
     */
    breadth: {
      concentration: "isolated" | "broad" | "not_assessable";
      ranked: number; impaired: number; unknown: number; uncomputable: number;
    };
    /** Echoes `poolAggregate`, plus the population split below. `null` when there is none. */
    capacity: {
      scope: "bridge_wide";
      /** False for BurnMint — a POSITIVE structural fact, not a missing card. */
      applicable: boolean;
      /** ⚠ AN UNPRICED MIXED-ASSET SUM OF TOKEN UNITS, NOT DOLLARS. */
      availableLiquidity: number | null;
      tvlUsd: number | null;
      /** Over ALL of POOLED_ASSETS. */
      missingAssets: string[];
      /**
       * ⚠ THE SPLIT IS SERVED SO A SURFACE NEED NOT RE-DERIVE IT. `missingAssets` spans
       * POOLED_ASSETS (incl. WETH) while the sums cover STABLECOINS only, so an
       * "INCOMPLETE" warning keyed off the whole array reports a shortfall in a figure WETH
       * was never part of. `missingValued` non-empty ⇒ the sums ARE short.
       */
      missingValued: string[];
      missingUnvalued: string[];
      unavailableReason: string | null;
      text: string;
    } | null;
    detail: string[];
    evidence: Array<{ label: string; detail: string }>;
    /** ⚠ THE CONFIDENCE STATEMENT, AND THERE IS DELIBERATELY NO GRADE (D9/§6). */
    coverage: {
      fetcher: "ok" | "failed" | "not_monitored";
      captured: boolean;
      ranked: number; unknown: number; uncomputable: number;
      /** Named limits. ⚠ Rendered, never hidden. */
      caveats: string[];
    };
  };
  updatedAt: string;
}
```

⚠ **A missing (chain, asset) pair is not a gap in this response — for Across it is
usually a structural fact, AND IT IS NOW NAMED** in `chains[].uncomputable[]` rather than
merely absent. `ACROSS_BSH_PAIRS` (decision D17) limits Across BSH to
the pairs the ConfigStore publishes a spoke target for: **WETH on all four spokes,
USDT on optimism/base, and nothing for USDC or DAI on any monitored chain.**
Uncomputable-by-design pairs write no row at all, so they simply do not appear.
That is "Across publishes no target for this pair", not "the read failed".

#### Example

```bash
curl https://corridorscout.com/corridor-scout/api/bridges/across/health
```

```json
{
  "bridge": "across",
  "bridgeModel": "HubPool",
  "capacityLabel": "HubPool TVL",
  "captured": true,
  "coverage": { "fetcher": "ok" },
  "rollup": {
    "level": "pressure",
    "score": 0.31,
    "reason": "bsh_ranked",
    "bindingChain": "base",
    "bindingAsset": "USDT",
    "contributingCount": 2,
    "unknownCount": 0
  },
  "chains": [
    {
      "chain": "base",
      "worstLevel": "pressure",
      "worstScore": 0.31,
      "bindingAsset": "USDT",
      "reason": "bsh_ranked",
      "assets": [
        {
          "asset": "USDT",
          "level": "pressure",
          "score": 0.31,
          "reason": "ratio 0.28 below healthy band",
          "method": "target_ratio",
          "underlying": { "currentBalance": 112400, "target": 400000 }
        },
        {
          "asset": "WETH",
          "level": "healthy",
          "score": 0.91,
          "reason": "ratio 0.86",
          "method": "target_ratio",
          "underlying": { "currentBalance": 344.2, "target": 400 }
        }
      ],
      "uncomputable": [
        { "asset": "USDC", "reason": "across_no_published_spoke_target" },
        { "asset": "DAI",  "reason": "across_no_published_spoke_target" }
      ]
    }
  ],
  "poolAggregate": {
    "scope": "bridge_wide",
    "tvlUsd": 12400000,
    "availableLiquidity": 9100000,
    "assets": [
      { "asset": "DAI", "utilization": 3.9 },
      { "asset": "USDC", "utilization": 32.39 },
      { "asset": "USDT", "utilization": 10.5 },
      { "asset": "WETH", "utilization": 55.1 }
    ],
    "expectedAssets": ["DAI", "USDC", "USDT", "WETH"],
    "contributingAssets": ["DAI", "USDC", "USDT", "WETH"],
    "missingAssets": [],
    "recordedAt": "2026-08-28T14:34:00Z",
    "unavailableReason": null
  },
  "finding": {
    "id": "bridge-across-constrained",
    "kind": "settlement_constrained",
    "severity": "elevated",
    "bridge": "across",
    "bridgeModel": "HubPool",
    "level": "pressure",
    "score": 0.31,
    "reason": "bsh_ranked",
    "bindingChain": "base",
    "bindingAsset": "USDT",
    "headline": "across settlement is under pressure on base / USDT.",
    "narrative": {
      "whatHappened": "The most constrained readable settlement leg is base / USDT, currently under pressure (BSH 0.31).",
      "comparedWith": "The base spoke holds 112,400 USDT, or 28.1% of its 400,000 USDT target.",
      "whyItMatters": "The constraint is isolated to one readable settlement leg; the other 1 currently reads healthy."
    },
    "nativeCondition": {
      "kind": "balance_vs_target",
      "method": "target_ratio",
      "unit": "token_units",
      "asset": "USDT",
      "currentBalance": 112400,
      "target": 400000,
      "ratio": 0.281,
      "text": "The base spoke holds 112,400 USDT, or 28.1% of its 400,000 USDT target."
    },
    "breadth": { "concentration": "isolated", "ranked": 2, "impaired": 1, "unknown": 0, "uncomputable": 2 },
    "capacity": {
      "scope": "bridge_wide",
      "applicable": true,
      "availableLiquidity": 9100000,
      "tvlUsd": 12400000,
      "missingAssets": [],
      "missingValued": [],
      "missingUnvalued": [],
      "unavailableReason": null,
      "text": "Bridge-wide pool: 9,100,000 stablecoin units available · $12,400,000 stablecoin TVL. Available liquidity is an unpriced sum of stablecoin token units, not USD; the two figures can diverge when a constituent depegs. Bridge-wide figures are not attributable to a single corridor."
    },
    "detail": [
      "Bridge health reflects the weakest readable settlement leg, not the average condition of the bridge.",
      "The base spoke holds 112,400 USDT, or 28.1% of its 400,000 USDT target.",
      "Balance and target are measured in token units, not USD.",
      "The constraint is isolated: 1 of 2 readable settlement legs is below healthy.",
      "2 evaluated · 0 unavailable this read · 2 structurally unmeasurable",
      "Bridge-wide pool: 9,100,000 stablecoin units available · $12,400,000 stablecoin TVL. Available liquidity is an unpriced sum of stablecoin token units, not USD; the two figures can diverge when a constituent depegs. Bridge-wide figures are not attributable to a single corridor."
    ],
    "evidence": [
      { "label": "Settlement health over time", "detail": "across · base / USDT" },
      { "label": "Settlement health across legs", "detail": "2 evaluated · 0 unavailable this read · 2 structurally unmeasurable" },
      { "label": "Operational events", "detail": "attestation degradation · completions stopped · pause/upgrade" }
    ],
    "coverage": {
      "fetcher": "ok",
      "captured": true,
      "ranked": 2,
      "unknown": 0,
      "uncomputable": 2,
      "caveats": [
        "Bridge health reflects the weakest readable settlement leg, not the average condition of the bridge.",
        "Settlement-health level thresholds are provisional and have not yet been fitted to observed distributions.",
        "2 chain/asset pairs cannot be measured with this bridge's available data. This is structural, not an outage."
      ]
    }
  },
  "updatedAt": "2026-08-28T14:35:00Z"
}
```

⚠ **The ONLY dollar figure in a served `finding` is `tvlUsd`, and that is checked.**
`112,400 USDT` / `400,000 USDT` are token units; the FF spec's own §9.2 example wrote them as
`$112.4k / $400k`, which is invisible on USDT and wrong by three orders of magnitude on WETH.
`availableLiquidity` is likewise an unpriced token-unit sum — during a depeg it can
legitimately print LARGER than the `tvlUsd` beside it. `tvlUsd` itself IS dollars and prints
with a `$`, at FULL precision (`$12,400,000`), **not** the compact form the card uses.
⚠ **This paragraph previously said the block carries no currency symbol at all** — false, and
its test passed only because the fixture had no pool aggregate (AUDIT D54.4). The pin is now
a populated-pool response in which every `$` is asserted to belong to the tvlUsd figure.

⚠ **The prose is READER-FACING since D61 (2026-09-11), and the machine fields are not.**
`level`, `reason`, `method`, `unit`, `bindingChain`/`bindingAsset`, the three coverage counts and
`capacity.unavailableReason` stay terse tokens; the sentences translate them (`ranked` → "evaluated",
`unknown` → "unavailable this read", `uncomputable` → "structurally unmeasurable", the binding pair →
"the most constrained readable settlement leg"). The headline states the observed condition on the
named leg and carries no score; `whatHappened` carries the score; `nativeCondition.text` carries the
figures and nothing else (the unit note is its own `detail` line); an absence's `whatHappened` says
whose absence it is (`Blockford could not retrieve settlement data for across.`) and its
`whyItMatters` is the consequence, never a repeat. `capacity.text` is composed from the same
per-reason map the card renders (`POOL_UNAVAILABLE_COPY`), and the card prints it verbatim. No
machine token appears inside a served sentence. See AUDIT D61.

⚠ **Read the example's `uncomputable` block as the D17 fact it is.** USDC and DAI are not
missing from `assets` because a read failed — Across publishes no dataworker spoke target for
them on any monitored chain, so no row is ever written. And `poolAggregate` is the ONLY place
this bridge-wide figure is served; it is not on any corridor response.

---

### GET /api/corridors/confidence

Per-corridor synthesis of the observed legs, ranked worst-first. The Corridor
Confidence surface's read.

⚠ **THERE IS NO `confidenceScore`, AND THAT IS THE DECISION, NOT AN OMISSION.**
LIQUIDITY-METRICS-REFACTOR §7.3 sketches `confidenceScore: number // 0.0-1.0
composite`; **decision D9 and PHASE-0-SPEC-V2_4 §6 supersede it** — the weighting
math is deferred and Phase 0 ships no composite score, no probability, no confidence
band. What ships is `recommendation`: a documented worst-of ladder over observed
levels (DATA-MODEL §9B.3), reproducible by hand from the two legs beside it.

⚠ **`destinationChainFlow` IS CONTEXT, NOT AN INPUT TO `recommendation`.** LFV is
chain-scoped and bridge-agnostic; the recommendation answers a corridor-scoped
question. Feeding a chain-wide flow ratio into a per-corridor verdict would mix
populations, so it is served beside the verdict, named for the chain it describes,
and excluded from the ladder. A chain in `flight` does not change any corridor's
recommendation.

**Settlement is scoped to (this corridor's bridge, this corridor's DESTINATION
chain)**, then rolled up worst-across-assets. A corridor X→Y settles on Y, through
its own bridge; another bridge's health on the same chain says nothing about whether
this corridor can settle.

#### Response

```typescript
interface CorridorConfidenceResponse {
  corridors: CorridorConfidenceRow[];   // avoid → degraded → usable → preferred → unknown
  updatedAt: string;
}

interface CorridorConfidenceRow {
  corridorId: string;
  bridge: string;
  bridgeModel: "HubPool" | "BurnMint" | "DestPool";
  sourceChain: string;
  destChain: string;
  recommendation: "preferred" | "usable" | "degraded" | "avoid" | "unknown";
  recommendationReason: string;   // names the binding leg, or the absence
  finding: CorridorFinding;       // FF-4 — the Scout's conclusion for this corridor (below)
  settlement: {
    level: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
    score: number | null;
    bindingAsset: string | null;
    /**
     * ⚠ FIVE VALUES, AND THREE OF THEM ARE ABSENCES THAT ARE NOT ALIKE (DATA-MODEL §9B.1):
     *   `bsh_ranked`                 — a reading exists
     *   `bsh_unavailable`            — readings held, all uncomputable THIS TICK
     *   `bsh_no_readings`            — the fetcher ran and we hold nothing
     *   `bsh_fetch_failed`           — D32.2: the fetcher did NOT come back. We could not look
     *   `bsh_uncomputable_by_design` — D17: no reading can EVER exist for this corridor,
     *                                  because Across publishes no dataworker spoke target
     *                                  for ANY asset on its destination chain. PERMANENT.
     *
     * Precedence where the roll-up found nothing: `bsh_uncomputable_by_design` outranks
     * `bsh_fetch_failed`, because it would hold even had we looked. A RANKED roll-up and
     * `bsh_unavailable` are never overridden — both are truthful observations.
     */
    reason: string;
    contributingCount: number;
    unknownCount: number;
    /**
     * ⚠ D17 — assets that can never carry a reading on this DESTINATION chain, with the
     * structural reason. A SEPARATE list from `assets`, because a permanent structural
     * absence and a transient `unknown` are triaged differently. Empty for CCTP (BurnMint
     * has no per-asset spoke target). Derived from `ACROSS_BSH_PAIRS` itself.
     */
    uncomputable: Array<{ asset: string; reason: string }>;
    assets: Array<{ asset: string; level: string; score: number | null; reason: string; method: string }>;
  };
  observed: {
    healthStatus: "healthy" | "degraded" | "down" | "idle" | "unknown";  // ⚠ a ONE-HOUR verdict
    successRate24h: number | null;        // 24h — ⚠ ALREADY A PERCENTAGE (0–100)
    p50DurationSeconds: number | null;    // ONE-HOUR quantile
    p90DurationSeconds: number | null;    // ONE-HOUR quantile
    transferCount24h: number;
    /**
     * ⚠ CAN A COMPLETION ON THIS DESTINATION BE OBSERVED AT ALL? When false,
     * `transferCount24h` is a true count of initiations whose OUTCOMES ARE UNKNOWABLE and
     * `successRate24h` is null by construction — it will never fill in. Same definition
     * as /api/corridors (`lib/observed-destinations`).
     */
    completionObservable: boolean;
    completionObservableReason: string | null;   // non-null EXACTLY when the flag is false
  };
  destinationChainFlow: {
    chain: string;                        // ALWAYS the corridor's destChain
    /**
     * Null EXACTLY when `unavailableReason` is non-null: no flow status is held for this
     * request, and none is claimed.
     */
    status: "stable" | "inflow" | "outflow" | "flight" | "insufficient_data" | null;
    /**
     * ⚠ D57.2 (the D51.4 class, one surface over). `insufficient_data` is a COMPUTED LFV
     * verdict — "this chain lacks a full observation window" — and the route used to stamp
     * it when the flow leg REJECTED, so an outage was byte-identical to a quiet chain and the
     * served finding said every destination "reads insufficient_data". Non-null exactly when
     * the flow leg rejected this request. A chain merely ABSENT from a successful read keeps
     * `insufficient_data` with `unavailableReason: null` — the same reading /api/flow/chains
     * serves for that case.
     */
    unavailableReason: "lfv_read_failed" | null;
    flowRatio: number | null;             // null when unavailableReason is non-null
    netFlowUsd: number | null;            // null when unavailableReason is non-null
    windowHours: number;
  };
}
```

#### `finding` — the Scout's conclusion (FF-4 / D44.4, 2026-09-09)

The deterministic conclusion the Corridor Confidence surface opens with, served on EVERY
row — `unknown` ones included — so the same conclusion reaches humans and machines from ONE
derivation (`src/lib/findings/corridor.ts`, pure). Composed from the row it sits on and
nothing else, so it can never cite a figure the response does not carry.

```typescript
interface CorridorFinding {
  id: string;                 // content-addressed, e.g. "corridor-across_ethereum_base-degraded"
                              // — stable for the same condition; NOT a sequence number
  kind: 'route_avoid' | 'route_degraded' | 'route_usable' | 'route_preferred' | 'not_concluded';
  severity: 'notable' | 'elevated' | 'none' | 'unknown';   // a pure function of kind — an
                                                            // ordering key, NOT a risk grade
  corridorId: string; bridge: string; sourceChain: string; destChain: string;
  recommendation: CorridorRecommendation;   // echoed from the row, never recomputed
  recommendationReason: string;             // the machine token, verbatim
  binding: {                  // the leg that set the tier, as ONE served line — READER-FACING
                              // SINCE D62 (2026-09-12)
    leg: 'settlement' | 'health' | 'none' | 'unrecognised';
    text: string;             // "Settlement pressure · USDT" · "Observed transfer health down" ·
                              // "No route condition could be evaluated · settlement:
                              //  structurally unmeasurable · transfers: none initiated over 24h"
                              //  (D57.6 — each leg's OWN served state in reader words, never
                              //  the ladder's collapsed token; the token rides on
                              //  `recommendationReason`) · an unrecognised token verbatim
  };
  settlementLevel: BshLevel;  settlementScore: number | null;  bindingAsset: string | null;
  headline: string;           // ⚠ LEADS WITH THE OBSERVABLE STORY (D62), never the tier word:
                              //  both legs → their relationship ("Transfers remain healthy on
                              //  {src} → {dest} via {bridge}, but destination settlement is
                              //  under pressure on USDT."); one leg → its fact, then the other
                              //  leg's absence; no leg → "There is not enough observable route
                              //  data to assign a tier for …". An unrecognised reason or tier
                              //  is APPENDED verbatim.
  narrative: {                // the three questions, kept apart (D43)
    whatHappened: string;     // the route condition as a fact, with the BSH score and the
                              //  one-hour window ("Destination settlement is under pressure on
                              //  USDT (BSH 0.31) while observed transfer performance remains
                              //  healthy over the last hour.")
    comparedWith: null;       // ⚠ ALWAYS null here: a worst-of ladder has no fitted reference
    whyItMatters: string;     // the tier's documented meaning in reader language; RENDERED
                              //  under the label "What it means" (D62). The ladder MECHANISM
                              //  is a caveat + methodology, not this cell.
  };
  corroboration:              // how the two INDEPENDENTLY-captured legs relate (§10.3)
    | 'settlement_impaired_transfers_healthy'   // THE sentence an uptime dashboard misses
    | 'both_impaired'
    | 'transfers_impaired_settlement_healthy'
    | 'both_healthy'
    | 'not_assessable';       // one leg is an absence — no comparison is possible
  corroborationText: string | null;   // the sentence ("Transfers are healthy over the last
                                      //  hour, while destination settlement is under pressure
                                      //  on USDT. The two are independent measurements, and
                                      //  they disagree."); ⚠ NULL whenever not_assessable
  observed: {                 // the transfer leg, with the observability qualification
    healthStatus: string; successRate24h: number | null;
    p50DurationSeconds: number | null; p90DurationSeconds: number | null;
    transferCount24h: number; completionObservable: boolean; completionObservableReason: string | null;
    text: string;             // the leg as THREE sentences — one per window, each named
                              //  ("Transfer health is healthy over the last hour. One-hour
                              //  transfer times are p50 120s and p90 300s. Over 24 hours,
                              //  99.5% of 90 observable transfers succeeded."); the absences
                              //  are their own sentences (idle · none resolved · outcomes
                              //  unobservable) and the reason TOKEN is not printed in prose
    summary: string;          // one row line: "Healthy (1h) · p50 120s · p90 300s (1h) ·
                              //  99.5% success · 90 transfers (24h)" · "342 initiated over 24h
                              //  · outcomes unobservable · no success rate" · "Idle · no
                              //  transfer initiated over 24h"
  };
  context: {                  // ⚠ CONTEXT ONLY — the single field carrying destination-chain flow
    chain: string;
    status: string | null;    // null when the flow leg was not read (D57.2)
    unavailableReason: 'lfv_read_failed' | null;
    netFlowUsd: number | null; flowRatio: number | null; windowHours: number;
    text: string;             // BEGINS "Context only: {chain} flow status is {status}, …" — and
                              // when the leg was not read says "could not be retrieved for this
                              // request", printing no status word (the reason is the typed
                              // `unavailableReason` field, not a word in the sentence — D62)
    summary: string;          // BEGINS "context · {chain} {status} · …", or
                              // "context · {chain} flow not retrieved this request"
  };
  detail: string[];           // the binding leg in words ("The route tier is set by
                              // destination settlement, which reads pressure on USDT."). Served
                              // for machine consumers; NOT printed on the card since D62 (it
                              // restates the binding line). ⚠ NOT the settlement-absence copy
                              // (D57.8): the Settlement evidence block renders that as the
                              // reading's own plate, and carrying it here printed it twice
  evidence: Array<{ label: string; detail: string }>;
  coverage: {                 // ⚠ EVIDENCE METADATA, NOT "CONFIDENCE" (D9/§6)
    settlementRanked: number; settlementUnknown: number;
    settlementUncomputable: number;              // D17 — can NEVER carry a reading here
    settlementAbsenceClass: 'structural' | 'transient' | null;   // never `awaiting_fit` on
                                                  // this route — that class belongs to the
                                                  // exceedance series (D57)
    caveats: string[];        // named limits — rendered, never hidden. Always: the
                              // worst-observed-leg rule + "flow is context only"; then, as
                              // applicable: initiations-only, structurally unmeasurable assets,
                              // an unavailable reading, and the settlement-absent consequence
                              // ("…the route tier therefore rests on observed transfer health
                              // alone." / "Neither route signal is currently observable…")
  };
}
```

⚠ **THE PROSE IS A PRESENTATION PROJECTION OF THE STRUCTURED FIELDS (D62, 2026-09-12).** Every
string above is composed from `recommendation`, `recommendationReason`, `settlement`, `observed`
and `destinationChainFlow` on the same row and adds nothing to them; the machine layer —
`kind`, `recommendation`, `recommendationReason`, `corroboration`, `binding.leg`, the
levels, scores, counts, typed absences and reason tokens — is unchanged by the copy pass. A
consumer that needs the token reads the field; the prose no longer carries `bsh_pressure`,
`completionObservableReason` or `lfv_read_failed` as words.

⚠ **`context` IS THE ONLY PLACE THE DESTINATION CHAIN'S FLOW APPEARS, AND IT SAYS SO ITSELF.**
LFV is chain-scoped and bridge-agnostic (§9); the tier is corridor-scoped and excludes it by
design (D31, FF spec §10.2). The derivation keeps the flow out of `headline`, `binding`,
`narrative` and `detail` **by test**, and both `context.text` and `context.summary` open with
the word *context* so a consumer that lifts one line without its neighbours still lifts a
true one. A chain in `flight` changes nothing on the finding except `context`.

⚠ **`corroborationText` IS NULL WHEN ONE LEG IS AN ABSENCE, AND THAT IS NOT A GAP.** The
§10.3 sentence compares two independent measurements; it exists only when both are present.
`settlement.level === 'unknown'`, or an observed health outside `healthy | degraded | down`
(`idle` — a quiet corridor; `unknown` — traffic with nothing resolved), yields
`corroboration: 'not_assessable'` and no sentence. A consumer must not compose one: a
half-sentence reads as agreement. The level in the sentence is **interpolated** — a `degraded`
reading says "is degraded", a `critical` one "is critically constrained", never the spec
example's "under pressure" for anything but `pressure`.

⚠ **`binding` IS A RENDERING OF THE SERVED REASON TOKEN PLUS THE LEG IT NAMES, NOT A SECOND
LADDER.** `bsh_<level>` with a ranked level → `Settlement <level> · <bindingAsset>` (the asset
is read from the settlement roll-up); `health_<status>` with an observed status → `Observed
transfer health <status>`; the no-leg tokens (`bsh_unavailable`, `no_observations_idle_and_bsh_unavailable`;
`health_unobserved` is declared but unreachable from the ladder) → `leg: 'none'` with a line
naming EACH leg's own served state in reader words (`settlement: structurally unmeasurable ·
transfers: none initiated over 24h`) — because the ladder's token says `unavailable` for a
settlement leg whose plate says "structurally unmeasurable, permanently" (D57.6); anything
else → `leg: 'unrecognised'` with the token verbatim.

⚠ **`corroborationText` FOR `both_healthy` NAMES ITS POPULATION (D57.5).** The all-clear says
over how many assets settlement evaluated, how many can never carry a reading on that
destination, and (D62) how many readings were unavailable this read — on base, USDC and DAI
are permanently unmeasurable, so "settlement is healthy" without that clause was an all-clear
over a population that excludes most stablecoins. The headline for this state says "the
readable destination settlement legs are also healthy", never "settlement is healthy".

⚠ **The evidence entry for exceedances/anomalies is NOT labelled "Recent" (D57.4).** The
per-corridor anomaly read (`/api/anomalies?corridorId=&active=false&limit=20`) applies no time
window and orders by severity, so a capped page is the highest-severity rows over the store's
full history; and bridge-level `operational_event` rows carry `corridorId: null`, so that class
can never appear in a corridor-keyed read. The surface's caption and truncation line say both.

⚠ **`observed.summary` AND `observed.text` NAME THEIR WINDOWS.** `healthStatus` is a one-hour
verdict and the quantiles are one-hour; the rate and count are 24h. `text` is three sentences,
one per window; `summary` tags `(1h)` and `(24h)` on the line. A compact line that dropped the
labels would let a reader fuse them — the fusion is reachable in both directions (200 transfers
in 24h and none in the last hour reads `idle`; a last-hour collapse reads `down` beside a
99.9%). When completions are unobservable neither string calls the count successes, failures
or resolutions.

⚠ **NO PROBABILITY, NO CONFIDENCE GRADE, NO CAUSAL PROSE.** Pinned by the shared
forbidden-vocabulary guard (`src/lib/findings/shared.ts`) over the whole serialized object.
The tier is described as a tier ("places the corridor at the Degraded tier"), never as a
rating, and the headline no longer says *because* — the binding leg is its own served line.

**`recommendation: "unknown"` is served when NO leg was observed** — an idle corridor
with no BSH reading. Never `preferred`, which would recommend a corridor nothing is
known about.

⚠ **AN UNCOMPUTABLE SETTLEMENT LEG DOES NOT CHANGE `recommendation`.** The ladder reasons over
observed LEVELS, and `unknown` is `unknown` to it however it arose — a structural absence must
neither manufacture pressure nor manufacture health. The structural fact is served BESIDE the
verdict, in `settlement`, where a reader can see it. `recommendationReason` names the ladder's
binding leg, which is a different question from `settlement.reason`.

#### Example

```bash
curl https://corridorscout.com/corridor-scout/api/corridors/confidence
```

```json
{
  "corridors": [
    {
      "corridorId": "across_ethereum_base",
      "bridge": "across",
      "bridgeModel": "HubPool",
      "sourceChain": "ethereum",
      "destChain": "base",
      "recommendation": "degraded",
      "recommendationReason": "bsh_pressure",
      "settlement": {
        "level": "pressure",
        "score": 0.31,
        "bindingAsset": "USDT",
        "reason": "bsh_ranked",
        "contributingCount": 2,
        "unknownCount": 0,
        "uncomputable": [
          { "asset": "USDC", "reason": "across_no_published_spoke_target" },
          { "asset": "DAI",  "reason": "across_no_published_spoke_target" }
        ],
        "assets": [
          { "asset": "USDT", "level": "pressure", "score": 0.31, "reason": "ratio 0.28 below healthy band", "method": "target_ratio" },
          { "asset": "WETH", "level": "healthy", "score": 0.91, "reason": "ratio 0.86", "method": "target_ratio" }
        ]
      },
      "observed": {
        "healthStatus": "healthy",
        "successRate24h": 99.5,
        "p50DurationSeconds": 120,
        "p90DurationSeconds": 300,
        "transferCount24h": 90,
        "completionObservable": true,
        "completionObservableReason": null
      },
      "destinationChainFlow": {
        "chain": "base",
        "status": "outflow",
        "unavailableReason": null,
        "flowRatio": -0.42,
        "netFlowUsd": -210000,
        "windowHours": 24
      },
      "finding": {
        "id": "corridor-across_ethereum_base-degraded",
        "kind": "route_degraded",
        "severity": "notable",
        "corridorId": "across_ethereum_base",
        "bridge": "across",
        "sourceChain": "ethereum",
        "destChain": "base",
        "recommendation": "degraded",
        "recommendationReason": "bsh_pressure",
        "binding": { "leg": "settlement", "text": "settlement pressure · USDT" },
        "settlementLevel": "pressure",
        "settlementScore": 0.31,
        "bindingAsset": "USDT",
        "headline": "Transfers remain healthy on ethereum → base via across, but destination settlement is under pressure on USDT.",
        "narrative": {
          "whatHappened": "Destination settlement is under pressure on USDT (BSH 0.31) while observed transfer performance remains healthy over the last hour.",
          "comparedWith": null,
          "whyItMatters": "Destination settlement reads pressure on at least one asset, which lowers the corridor to the Degraded tier."
        },
        "corroboration": "settlement_impaired_transfers_healthy",
        "corroborationText": "Transfers are healthy over the last hour, while destination settlement is under pressure on USDT. The two are independent measurements, and they disagree.",
        "observed": {
          "healthStatus": "healthy", "successRate24h": 99.5,
          "p50DurationSeconds": 120, "p90DurationSeconds": 300, "transferCount24h": 90,
          "completionObservable": true, "completionObservableReason": null,
          "text": "Transfer health is healthy over the last hour. One-hour transfer times are p50 120s and p90 300s. Over 24 hours, 99.5% of 90 observable transfers succeeded.",
          "summary": "Healthy (1h) · p50 120s · p90 300s (1h) · 99.5% success · 90 transfers (24h)"
        },
        "context": {
          "chain": "base", "status": "outflow", "unavailableReason": null, "netFlowUsd": -210000, "flowRatio": -0.42, "windowHours": 24,
          "text": "Context only: base flow status is outflow, -$210,000 net over 24h. Chain flow is bridge-agnostic and does not affect this route tier.",
          "summary": "context · base outflow · -$210,000 net over 24h"
        },
        "detail": [
          "The route tier is set by destination settlement, which reads pressure on USDT."
        ],
        "evidence": [
          { "label": "Destination settlement by asset", "detail": "2 evaluated · 0 unavailable this read · 2 structurally unmeasurable · reason bsh_ranked" },
          { "label": "Observed transfer performance", "detail": "90 transfers over 24h · completion outcomes observable" },
          { "label": "Corridor events and exceedances", "detail": "threshold crossings and anomalies recorded for across_ethereum_base (bridge-level operational events carry no corridor key and are not included)" }
        ],
        "coverage": {
          "settlementRanked": 2, "settlementUnknown": 0, "settlementUncomputable": 2,
          "settlementAbsenceClass": null,
          "caveats": [
            "Route tiers use a deterministic worst-observed-leg rule: signals are not averaged, weighted or scored.",
            "Destination-chain flow is context only and does not affect the route tier.",
            "2 destination assets cannot carry a settlement reading with the available bridge data. They are outside the settlement verdict; this is structural, not an outage."
          ]
        }
      }
    }
  ],
  "updatedAt": "2026-08-28T14:35:00Z"
}
```

---

### GET /api/corridors

List all monitored corridors with health metrics.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `bridge` | string | Filter by bridge (across, cctp, stargate) |
| `source` | string | Filter by source chain |
| `dest` | string | Filter by destination chain |
| `status` | string | Filter by health status (healthy, idle, degraded, down) |
| `sort` | string | Sort field (**p50, p90, transfers**). ⚠ `fragility` was REMOVED in Phase D-RETIRE and now **400s** — see the note below. |
| `order` | string | Sort order (asc, desc) |
| `limit` | number | Max results (default 100, max 500) |
| `offset` | number | Pagination offset |

#### Response

```typescript
interface CorridorsResponse {
  corridors: Corridor[];
  total: number;
  limit: number;
  offset: number;
  /**
   * Completeness of the underlying read (added 2026-08-30, AUDIT #47/D37).
   * `null` = completeness could not be established (a cache entry predating the field) —
   * NOT the same as `truncated: false`.
   */
  truncation: {
    transfers:     { truncated: boolean; rows: number; cap: number; windowHours: number };
    poolSnapshots: { truncated: boolean; rows: number; cap: number; windowHours: number };
  } | null;
}

> **⚠ `truncation` — EVERY CORRIDOR FIGURE DEPENDS ON IT (added 2026-08-30).**
> `successRate24h`, the settlement quantiles and `volumeUsd24h` are computed over transfer
> rows loaded under a **row cap** (`MAX_TRANSFER_QUERY_ROWS`, a `t4g.micro` memory guard —
> AUDIT #34). When the cap is reached the 7-day window is **partial**, so those figures are
> computed over an unknown fraction of N — a 7-day quantity that is silently wrong while
> looking exactly like a right one. The cap hit was previously only LOGGED; a log is not the
> payload, and a consumer had no way to know.
>
> ⚠ **`truncated` means "the cap was reached", which is not exactly "rows were dropped".**
> Detection is `rows === cap`, so a window holding exactly the cap reports truncated with
> nothing missing. It over-reports on one boundary case and never under-reports — the
> correct direction for a completeness flag, and why the wording is *may be incomplete*.
>
> ⚠ **This is part (a) of a two-part fix.** Part (b) — pushing the aggregation into
> Postgres (`SUM`/`percentile_disc` over the window, one query) so the cap is unnecessary
> at all — is **scoped and unstarted**; see AUDIT #48/D37 "Scoped, NOT fixed".

> **⚠ `completionObservable` — IT QUALIFIES EVERY OTHER FIGURE ON THE ROW (added
> 2026-08-31, AUDIT #47/#50).** `false` means a completion on this corridor's destination
> **cannot be observed at all** — the bridge has no listener there — so the outcome of its
> transfers is unknowable rather than pending. `completionObservableReason` is
> `destination_not_monitored`, non-null exactly when the flag is false.
>
> ⚠ **DERIVED AT READ TIME, never stored.** Observability is a property of CURRENT
> monitoring: monitor the chain later and replay its fills, and those very transfers become
> resolvable. A stored flag would preserve a yesterday-answer.
>
> ⚠ **WHAT IT DOES TO THE OTHER FIELDS.** `transferCount24h` and `volumeUsd24h` remain TRUE
> — they count observed initiations, and nulling them would erase real data to fix a
> labelling problem. `successRate24h` is `null`, because the resolvable set is empty *by
> construction* and will stay empty. A surface rendering the counts must attach the reason
> to them ("342 initiated · completions not observed") rather than showing a bare number
> with a flag elsewhere in the payload.

> **⚠ `successRate1h` / `successRate24h` ARE `null` WHENEVER NOTHING RESOLVED (changed
> 2026-08-31, AUDIT #42).** `successRate()` previously returned a fabricated **100** for an
> empty resolvable set; the served fields were guarded, the value passed to the health
> classifier was not, and a corridor with traffic and zero successes read `healthy`. The
> null now originates in the function itself, so no caller can reintroduce it.
>
> ⚠ **`null` HAS TWO CAUSES AND THEY ARE DIFFERENT FACTS.** A quiet corridor (nothing
> resolved this window — honest and temporary) versus `completionObservable: false` (the
> resolvable set is empty by construction and will stay empty). Read the two fields
> together. ⚠ **`status` may now be `unknown`** — traffic exists but no verdict is
> supportable. It is NOT a fifth severity and must not be ordered inside
> `healthy → degraded → down`.

interface Corridor {
  corridorId: string;        // e.g., "across_ethereum_arbitrum"
  bridge: string;
  // Liquidity model — drives bridge-aware UI display (docs/archive/bug-fixes.md Step 4/6):
  //   HubPool   → Across (capacity = HubPool TVL)
  //   BurnMint  → CCTP   (no pool — unlimited capacity)
  //   DestPool  → Stargate (capacity = destination chain pool)
  bridgeModel: "HubPool" | "BurnMint" | "DestPool";
  sourceChain: string;
  destChain: string;
  status: "healthy" | "idle" | "degraded" | "down";
  metrics: {
    transferCount1h: number;
    transferCount24h: number;
    successRate1h: number | null;   // 0-100, null when no resolved transfers
    successRate24h: number | null;  // 0-100, null when no resolved transfers
    p50DurationSeconds: number | null;
    p90DurationSeconds: number | null;
    volumeUsd24h: number;
  };
  /**
   * ⚠⚠ NULL FOR HubPool AND BurnMint SINCE PHASE D-RETIRE (2026-08-29) — i.e. for EVERY
   * corridor currently monitored. Retained only for `DestPool`.
   *
   * WHY. For a HubPool bridge the only pool figure that exists is the GLOBAL, bridge-wide
   * HubPool aggregate, and serving it here stamped the IDENTICAL `tvlUsd`, `utilization` and
   * `fragility` on every Across corridor — correct as a bridge-level backstop, meaningless
   * per corridor (finding #5, verified live). BSH (§9A) is the canonical settlement-capacity
   * metric across all bridge models; the bridge-wide figure survives on
   * `GET /api/bridges/:bridge/health` as `poolAggregate`, labelled `scope: "bridge_wide"`.
   *
   * ⚠ NULL, NOT A ZEROED OBJECT. `{ tvlUsd: 0, fragility: "none" }` is byte-identical to a
   * genuinely empty pool with no fragility.
   */
  pool: {
    tvlUsd: number;
    utilization: number | null;  // 0-100 = MAX per-asset; null = not established
    availableLiquidity: number;
    // DestPool only now (docs/DATA-MODEL.md §7).
    fragility: "none" | "low" | "medium" | "high" | "unknown";
    fragilityReason: string;
  } | null;
  /**
   * Why `pool` is null. Non-null EXACTLY when `pool` is null.
   *   `pool_not_applicable_burnmint` — a POSITIVE fact: this bridge model holds no pool.
   *   `pool_scope_bridge_wide`       — a SCOPE refusal: the figure exists, bridge-wide only.
   * The two are kept apart because they are different claims.
   */
  poolUnavailableReason: string | null;
  lastTransferAt: string;    // ISO8601
}
```

⚠ **`?sort=fragility` NOW RETURNS 400 (Phase D-RETIRE).** With `pool` null on every monitored
corridor a fragility sort would have compared `undefined` to `undefined` and returned the input
order, silently, while the API kept advertising the key as valid. The build plan requires the
sort key, its validation entry and the field to be removed in the SAME change; a loud 400 is
the answer. Valid sorts are `p50`, `p90`, `transfers`.

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/corridors?bridge=across&status=healthy&sort=p50&order=asc"
```

```json
{
  "corridors": [
    {
      "corridorId": "across_ethereum_arbitrum",
      "bridge": "across",
      "bridgeModel": "HubPool",
      "sourceChain": "ethereum",
      "destChain": "arbitrum",
      "status": "healthy",
      "metrics": {
        "transferCount1h": 47,
        "transferCount24h": 1124,
        "successRate1h": 100,
        "successRate24h": 99.8,
        "p50DurationSeconds": 210,
        "p90DurationSeconds": 372,
        "volumeUsd24h": 45600000
      },
      "pool": null,
      "poolUnavailableReason": "pool_scope_bridge_wide",
      "lastTransferAt": "2026-02-21T14:34:12Z"
    }
  ],
  "total": 15,
  "limit": 100,
  "offset": 0
}
```

---

### GET /api/corridors/:corridorId

Detailed view of a single corridor.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `corridorId` | string | Corridor identifier (e.g., across_ethereum_arbitrum) |

#### Response

```typescript
interface CorridorDetailResponse {
  /**
   * ⚠ `corridor.pool` IS NULL FOR HubPool AND BurnMint SINCE PHASE D-RETIRE — see the
   * `Corridor` interface under `GET /api/corridors` for the full rationale. This route
   * carried the same defect: the detail page showed the identical bridge-wide TVL,
   * utilization and fragility for every Across corridor. Its DestPool branch additionally
   * carries `pool.unavailableReason` (`abi_defective_excluded`) when rows exist but are
   * withheld as known-wrong (AUDIT #36).
   */
  corridor: Corridor;
  recentTransfers: Transfer[];      // Last 20
  hourlyStats: HourlyStat[];        // Last 24 hours
  dailyStats: DailyStat[];          // Last 7 days
  anomalies: Anomaly[];             // Active anomalies
}

interface Transfer {
  transferId: string;
  amount: string;                   // Decimal string
  amountUsd: number | null;
  asset: string;
  status: "pending" | "completed" | "stuck" | "failed";
  initiatedAt: string;
  completedAt: string | null;
  durationSeconds: number | null;
  txHashSource: string | null;
  txHashDest: string | null;
}

interface HourlyStat {
  hour: string;                     // ISO8601 hour start
  transferCount: number;
  successRate: number | null;       // null when no resolved transfers in bucket
  p50DurationSeconds: number | null;
  p90DurationSeconds: number | null;
  volumeUsd: number;
}

interface DailyStat {
  date: string;                     // YYYY-MM-DD
  transferCount: number;
  successRate: number | null;       // null when no resolved transfers in bucket
  avgDurationSeconds: number | null;
  volumeUsd: number;
  // Daily rollup keys on resolved transfers, not initiations — it never emits
  // 'idle' (a no-resolved-transfers day is reported 'down'). 3-state by design.
  status: "healthy" | "degraded" | "down";
}
```

#### Example

```bash
curl https://corridorscout.com/corridor-scout/api/corridors/across_ethereum_arbitrum
```

```json
{
  "corridor": {
    "corridorId": "across_ethereum_arbitrum",
    "bridge": "across",
    "bridgeModel": "HubPool",
    "sourceChain": "ethereum",
    "destChain": "arbitrum",
    "status": "healthy",
    "metrics": { ... },
    "pool": null,
    "poolUnavailableReason": "pool_scope_bridge_wide",
    "lastTransferAt": "2026-02-21T14:34:12Z"
  },
  "recentTransfers": [
    {
      "transferId": "eth_12345_67890",
      "amount": "10000.000000",
      "amountUsd": 10000,
      "asset": "USDC",
      "status": "completed",
      "initiatedAt": "2026-02-21T14:30:00Z",
      "completedAt": "2026-02-21T14:33:30Z",
      "durationSeconds": 210,
      "txHashSource": "0xabc...",
      "txHashDest": "0xdef..."
    }
  ],
  "hourlyStats": [
    {
      "hour": "2026-02-21T14:00:00Z",
      "transferCount": 47,
      "successRate": 100,
      "p50DurationSeconds": 210,
      "p90DurationSeconds": 372,
      "volumeUsd": 2340000
    }
  ],
  "dailyStats": [
    {
      "date": "2026-02-21",
      "transferCount": 1124,
      "successRate": 99.8,
      "avgDurationSeconds": 245,
      "volumeUsd": 45600000,
      "status": "healthy"
    }
  ],
  "anomalies": []
}
```

---

### GET /api/impact/estimate

Calculate the **total observed/deterministic cost to act** for a potential
transfer (Phase 2a — PHASE-0-SPEC-V2_4 §4, DATA-MODEL §8). **BREAKING vs the
pre-2a slippage-led shape**: the response leads with `totalCostBps`; the
slippage-era fields (`poolSharePct`, `estimatedSlippageBps`, `warning`,
top-level `fastFill`) are gone.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bridge` | string | Yes | Bridge protocol |
| `source` | string | Yes | Source chain |
| `dest` | string | Yes | Destination chain |
| `amountUsd` | number | Yes | Transfer amount in USD |

#### Response

```typescript
interface ImpactEstimateResponse {
  corridorId: string;
  transferAmountUsd: number;
  pool: {
    tvlUsd: number;            // 0 for BurnMint bridges (no pool)
    utilization: number | null;  // 0-100 = MAX per-asset; null = not established (incl. BurnMint)
    availableLiquidity: number; // 0 for BurnMint
  };
  impact: {
    // THE headline. Bps fields are served at FULL PRECISION — NEVER rounded
    // (PO 2026-08-14): rounding produced boundary values that contradicted
    // the band label (4.996 → "5.00" tagged with the sub-5 band) and
    // components that failed to sum to the total. Consumers must not round
    // for display either — strip float noise at most (e.g. 6 significant
    // digits), never at a precision that could cross a band edge.
    totalCostBps: number;      // exact sum of the four components
    components: {
      slippageBps: number;     // pool-share slippage (0 for BurnMint)
      sourceGasBps: number;    // observed source-chain gas / amount (GasSnapshot + native price)
      destGasBps: number;      // observed destination-chain gas / amount
      protocolFeeBps: number;  // per-bridge fee model (Across LP fee; CCTP V1 = 0) — DATA-MODEL §8.5
    };
    // Observed settlement latency (7-day corridor quantiles) — reported
    // ALONGSIDE cost, never summed into it. Typed null when the corridor has
    // no completed transfers in the window (never 0).
    settlement: { p50Seconds: number | null; p90Seconds: number | null };
    impactLevel: "negligible" | "low" | "moderate" | "high" | "severe"; // totalCostBps bands, DATA-MODEL §8.4
    // Across-only supplementary settlement-speed signal. Null for
    // CCTP/Stargate, and for Across when the SpokePool snapshot is missing —
    // supplementary, never load-bearing.
    fastFill: {
      available: boolean;          // True when SpokePool depth ≥ transferAmountUsd
      spokePoolTvlUsd: number;
      coverageRatio: number | null; // transferAmountUsd / spokePoolTvlUsd; null when SpokePool TVL is 0
      note: string;                // "Sufficient SpokePool capital" / "Exceeds SpokePool — rebalance lag possible"
    } | null;
    // Bridge-model caveat — ALWAYS render when present:
    //   BurnMint: "CCTP is burn/mint, no pool slippage applies"
    //   HubPool:  relayer-fee exclusion — Across protocolFeeBps is the LP fee
    //             only; the headline is NOT all-in (PO 2026-08-14)
    //   DestPool: deferred-fee note (Stargate on hold)
    note: string | null;
  };
  /**
   * ⚠ REPLACED THE `fragility` BLOCK IN PHASE D-RETIRE (2026-08-29). `calculateFragility` is
   * DestPool-only now, and every bridge this endpoint quotes is HubPool or BurnMint — so the
   * old block would have refused on every request. This is the DESTINATION chain's worst BSH
   * reading for THIS bridge, scoped exactly as `/api/corridors/confidence` scopes it, from
   * the same `worstBsh`, so the two surfaces cannot disagree.
   *
   * ⚠ THERE IS NO `postTransfer` SIBLING, AND ITS ABSENCE IS THE DECISION. BSH has no
   * hypothetical: its denominator is a published dataworker spoke target, and a reading for
   * a transfer that has not happened would be a MODELLED number on an observed-only surface
   * (§6). The transfer's own pool impact is already `impact.components.slippageBps`.
   *
   * ⚠ `reason` is a typed absence when `level` is `unknown` — never a healthy default. And
   * `unknown` does NOT trigger the stress advice in `recommendation`: escalating on an
   * absence would manufacture a warning out of a stale snapshot.
   */
  bridgeSettlement: {
    level: "healthy" | "degraded" | "pressure" | "critical" | "unknown";
    score: number | null;
    reason: string;             // bsh_ranked | bsh_unavailable | bsh_no_readings | …
    bindingAsset: string | null;
    contributingCount: number;
    unknownCount: number;
  };
  corridorHealth: {
    status: "healthy" | "idle" | "degraded" | "down";
    p50DurationSeconds: number | null;   // 1-hour window; null when no data
    p90DurationSeconds: number | null;
    successRate1h: number | null;    // null when no resolved transfers
  };
  /**
   * Component-aware advice (split only when slippage dominates).
   * ⚠ ITS STRESS BRANCH IS BSH SINCE D-RETIRE: `fragility === 'high'` became
   * `bshLevel === 'pressure' || 'critical'` — the two §9A levels `composite-status.isPressure`
   * defines, so this endpoint and the chain composite cannot disagree about "under stress".
   */
  recommendation: string | null;
  disclaimer: string;              // Always present
}
```

#### Fail-loud responses

Two typed 503 reasons. UIs must render each as an explicit "Data temporarily
unavailable" state, not as a stale or zero value.

**Pool (HubPool bridges — Across).** Global HubPool snapshot missing, older
than 30 minutes, or present but unpriced (Phase 0a fail-loud). SpokePool data
is **never** substituted for HubPool capacity:

```json
{
  "error": {
    "code": "POOL_SNAPSHOT_UNAVAILABLE",
    "message": "Impact cannot be estimated: HubPool liquidity snapshot is missing, stale, or unpriced (price feed unavailable).",
    "reason": "pool_snapshot_unavailable"
  }
}
```

**Gas (all bridges).** Latest `gas_snapshots` row missing/stale (>30 min), a
fee field null, or the native-token USD price unavailable, for either the
source or destination chain. Gas is never guessed (spec §4):

```json
{
  "error": {
    "code": "GAS_UNAVAILABLE",
    "message": "Impact cannot be estimated: gas snapshot or native-token price is missing or stale for a required chain.",
    "reason": "gas_unavailable"
  }
}
```

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/impact/estimate?bridge=across&source=ethereum&dest=arbitrum&amountUsd=5000000"
```

```json
{
  "corridorId": "across_ethereum_arbitrum",
  "transferAmountUsd": 5000000,
  "pool": {
    "tvlUsd": 85000000,
    "utilization": 24,
    "availableLiquidity": 65025000
  },
  "impact": {
    "totalCostBps": 4.87,
    "components": {
      "slippageBps": 2.94,
      "sourceGasBps": 0.01,
      "destGasBps": 0.01,
      "protocolFeeBps": 1.91
    },
    "settlement": { "p50Seconds": 210, "p90Seconds": 372 },
    "impactLevel": "negligible",
    "fastFill": {
      "available": true,
      "spokePoolTvlUsd": 12500000,
      "coverageRatio": 0.4,
      "note": "Sufficient SpokePool capital"
    },
    "note": "Relayer fee not included; varies per quote. Total shown is slippage + gas + LP fee only."
  },
  "bridgeSettlement": {
    "level": "healthy",
    "score": 0.91,
    "reason": "bsh_ranked",
    "bindingAsset": "WETH",
    "contributingCount": 2,
    "unknownCount": 0
  },
  "corridorHealth": {
    "status": "healthy",
    "p50DurationSeconds": 210,
    "p90DurationSeconds": 372,
    "successRate1h": 100
  },
  "recommendation": null,
  "disclaimer": "Directional estimate only. Not an execution guarantee."
}
```

### GET /api/anomalies

> ⚠⚠ **CONSUMER RULE (D54.2, 2026-09-09): THIS ENDPOINT SERVES NO TIME WINDOW, AND ITS PAGE IS
> ORDERED BY SEVERITY.** `orderBy` is `severity desc, lastSeenAt desc, detectedAt desc`, there
> is **no time filter at all**, `limit` defaults to **50** (max 500), and `anomalies` has **no
> retention policy** — so resolved rows accumulate indefinitely and, on an `active=false` read,
> compete with open ones for the page. Three obligations follow for any consumer:
>
> 1. **Read the OPEN set as its own query** (`active=true`) if you intend to count or assert
>    anything about what is currently firing. Deriving "0 open" from a mixed `active=false` page
>    is how a standing episode renders as an all-clear.
> 2. **Never describe the served set as a time window.** "In the last N hours" is a bound this
>    endpoint does not apply.
> 3. **Render the truncation.** `total` / `limit` / `offset` are served precisely so a cut page
>    is distinguishable from a complete one; ignoring them makes them equal.
>
> Bridge Health does all three (`src/components/bridges/BridgeHealth.tsx`,
> `src/lib/operational-timeline.ts`).

List detected anomalies.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `active` | boolean | Only unresolved anomalies (default true) |
| `severity` | string | Filter by severity (low, medium, high) |
| `type` | string | Filter by type (latency_spike, failure_cluster, liquidity_drop, stuck_transfer, operational_event) |
| `bridge` | string | Filter by bridge |
| `corridorId` | string | Filter by corridor |
| `limit` | number | Max results (default 50, max 500) |
| `offset` | number | Pagination offset (default 0) |

#### Response

```typescript
interface AnomaliesResponse {
  anomalies: Anomaly[];
  total: number;
  limit: number;
  offset: number;
}

interface Anomaly {
  id: string;
  anomalyType: "latency_spike" | "failure_cluster" | "liquidity_drop" | "stuck_transfer"
    | "operational_event"; // discrete bridge/venue state change (Phases 2b-1/2b-2, DATA-MODEL §11.5)
  // For operational_event rows this is the subject key, NOT a corridor triple
  // (there is no corridor page): `${bridge}_${chain}` for completions_stopped
  // and attestation_degradation, `${bridge}_${chain}_${deposit|fill}` for
  // contract_pause_upgrade (one subject per watched event signature). Which
  // detector fired is details.detector ('completions_stopped' |
  // 'contract_pause_upgrade' | 'attestation_degradation'), with the full trigger
  // evidence alongside it — for the two silence detectors sinceSeconds,
  // observedSilenceSeconds, thresholdSeconds, signalKind; for
  // attestation_degradation the published 0c BSH reading it promoted (level,
  // score, currentMedianSeconds, baselineMedianSeconds, latencyRatio,
  // latencyMultipleOfBaseline, method, snapshotRecordedAt, snapshotAgeSeconds)
  // — plus `config` (the thresholds in force at fire time) and, if the open row
  // worsened, details.escalation {at, from, to, …} (severity is escalate-only on
  // open rows). NOTE: top-level details are FROZEN at onset, so on an escalated
  // row the current state is in details.escalation — `description` reads the
  // escalated band/multiple in preference to the onset ones for exactly that
  // reason.
  corridorId: string;
  bridge: string;
  sourceChain: string | null;
  destChain: string | null;
  severity: "low" | "medium" | "high";
  detectedAt: string;
  // Last run the condition was observed still firing (anomaly lifecycle,
  // 2026-08-12): one open row per episode; re-detection bumps this instead of
  // creating a sibling. Null on rows created before the lifecycle landed.
  lastSeenAt: string | null;
  resolvedAt: string | null;
  details: {
    // Varies by anomaly type. Lifecycle markers: `last_evaluation:
    // "unobservable"` = the subject could not be evaluated on the most recent
    // run (row deliberately left open — blindness never resolves);
    // `resolution: "subject_descoped_*"` = resolved because the subject was
    // removed from the detector's evaluation basis, not because it recovered.
    [key: string]: any;
  } | null;
  description: string;           // Human-readable summary
}
```

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/anomalies?active=true&severity=high"
```

```json
{
  "anomalies": [
    {
      "id": "anom_123",
      "anomalyType": "latency_spike",
      "corridorId": "stargate_ethereum_avalanche",
      "bridge": "stargate",
      "sourceChain": "ethereum",
      "destChain": "avalanche",
      "severity": "high",
      "detectedAt": "2026-02-21T14:20:00Z",
      "resolvedAt": null,
      "details": {
        "normalP90Seconds": 1800,
        "currentP90Seconds": 12420,
        "multiplier": 6.9,
        "affectedTransfers": 12
      },
      "description": "Latency 6.9x normal on Stargate ETH→AVAX"
    },
    {
      "id": "anom_124",
      "anomalyType": "operational_event",
      "corridorId": "cctp_base",
      "bridge": "cctp",
      "sourceChain": null,
      "destChain": "base",
      "severity": "high",
      "detectedAt": "2026-02-21T14:35:00Z",
      "lastSeenAt": "2026-02-21T15:05:00Z",
      "resolvedAt": null,
      "details": {
        "detector": "attestation_degradation",
        "level": "critical",
        "score": 0.05,
        "currentMedianSeconds": 12000,
        "baselineMedianSeconds": 880,
        "latencyRatio": 0.073,
        "latencyMultipleOfBaseline": 13.7,
        "method": "latency_baseline",
        "snapshotRecordedAt": "2026-02-21T15:03:00Z",
        "snapshotAgeSeconds": 120
      },
      "description": "CCTP attestation latency 13.7x baseline on Cctp →Base (BSH critical)"
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

---

### GET /api/structural-facts

Read structural classifications (the `analyst_classification` data class — see
DATA-MODEL §17). Public read; `dataClass` is served on every record so consumers
know which data class produced a level. **Default returns the latest version per
`(entityType, entityKey, factor)`**; `?history=true` returns every version.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `entityType` | string | Filter by entity type (`issuer` \| `asset_chain`) |
| `entityKey` | string | Filter by entity key (issuer slug, or `asset:chain`) |
| `factor` | string | Filter by factor (see DATA-MODEL §17.1) |
| `history` | boolean | Return all versions instead of latest-per-factor (default false) |
| `limit` | number | Max results (default 100, max 500) |
| `offset` | number | Pagination offset (default 0) |

#### Response

```typescript
interface StructuralFactsResponse {
  records: StructuralFactRecord[];
  count: number;      // records in this page
  history: boolean;   // echo of the ?history flag
  limit: number;
  offset: number;
}

interface StructuralFactRecord {
  id: string;
  entityType: "issuer" | "asset_chain";
  entityKey: string;
  factor: string;               // enum, see DATA-MODEL §17.1
  level: string;                // enum value for that factor — NEVER numeric
  dataClass: "analyst_classification";
  basis: string;                // narrative basis
  citationUrl: string;          // required
  documentHash: string | null;  // set when the citation is a stored document
  asOf: string;                 // ISO 8601
  version: number;              // monotonic per (entityType, entityKey, factor)
  createdAt: string;            // ISO 8601
}
```

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/structural-facts?entityType=issuer&entityKey=circle"
```

```json
{
  "records": [
    {
      "id": "42",
      "entityType": "issuer",
      "entityKey": "circle",
      "factor": "reserve_conformity",
      "level": "conforming",
      "dataClass": "analyst_classification",
      "basis": "Q1 2026 attestation shows 100% cash + short-dated T-bills backing.",
      "citationUrl": "https://www.circle.com/en/transparency",
      "documentHash": null,
      "asOf": "2026-04-01T00:00:00Z",
      "version": 2,
      "createdAt": "2026-07-08T12:00:00Z"
    }
  ],
  "count": 1,
  "history": false,
  "limit": 100,
  "offset": 0
}
```

---

### POST /api/structural-facts

Ingest one structural classification (append-only). **Guarded by the ingestion-auth
pattern** — `Authorization: Bearer <ADMIN_SECRET>` (a second secret, distinct from
`CRON_SECRET`; NOT RBAC). This is a low-frequency, human-operated fact-ingestion
route. Each POST creates a **new row at the next version** for its
`(entityType, entityKey, factor)`; corrections are new versions, never mutations.

#### Request Body

```typescript
interface StructuralFactInput {
  entityType: "issuer" | "asset_chain";
  entityKey: string;            // validated against the known-entity vocabulary (below)
  factor: string;               // must be valid for entityType (DATA-MODEL §17.1)
  level: string;                // must be a permitted enum value for factor — NEVER numeric
  basis: string;                // required narrative basis
  citationUrl: string;          // required, must be a URL
  documentHash?: string;        // optional; set when the citation is a stored document
  asOf: string;                 // ISO 8601
  allowUnregisteredEntity?: boolean; // explicit opt-out of the known-entity guard (not persisted)
}
```

`dataClass`, `version`, `id`, and `createdAt` are **server-controlled** and rejected
if present in the body (strict schema). On success returns **201** with the created
`StructuralFactRecord`.

**Known-entity guard (write-side):** on an append-only table a typo'd `entityKey`
doesn't error — it silently creates a permanent orphan lineage no assessment ever
renders. So the POST validates `entityKey` against the known-entity vocabulary and
rejects unknowns with `400`:

- `issuer` — a lowercase snake_case slug in `KNOWN_ISSUER_SLUGS`
  (`tether, circle, sky, paxos, ethena, first_digital`; `sky` is one slug carrying
  the two-token USDS/DAI slot). Interim set until R2's `ISSUER_REGISTRY` lands.
- `asset_chain` — `asset:chain` where `asset` ∈ `ASSESSED_ASSETS` ∪ `USDS` and
  `chain` is a monitored `CHAIN_IDS` key (e.g. `USDC:arbitrum`, `USDS:ethereum`).

`allowUnregisteredEntity: true` is the explicit escape hatch for authoring a
genuinely new entity; format rules (slug pattern, `asset:chain` shape) still apply
even with the override.

#### Example

```bash
curl -X POST "https://corridorscout.com/corridor-scout/api/structural-facts" \
  -H "Authorization: Bearer $ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "entityType": "issuer",
    "entityKey": "circle",
    "factor": "reserve_conformity",
    "level": "conforming",
    "basis": "Q1 2026 attestation shows 100% cash + short-dated T-bills backing.",
    "citationUrl": "https://www.circle.com/en/transparency",
    "asOf": "2026-04-01T00:00:00Z"
  }'
```

Errors: `400 VALIDATION_ERROR` (bad shape, unknown factor for entityType, level
outside the factor vocabulary, numeric level, unregistered/malformed `entityKey`
without `allowUnregisteredEntity`); `401 Unauthorized` (missing/wrong bearer when
`ADMIN_SECRET` is set); `409 VERSION_CONFLICT` (a concurrent append claimed the
version — retry).

---

### GET /api/spread

Per-asset price/reference **spread** series for charting (the `observed`
non-backfillable series — see DATA-MODEL §16). Read from a direct on-chain DEX spot
(Curve 3pool `get_dy`) with an Alchemy by-address fallback. **Fail-loud is preserved
end to end:** an unavailable observation is `priceUsd`/`spreadBps` = `null` (a visible
gap), never a fabricated `0` or `$1.00` peg. `source` carries provenance (venue +
probe size, or the `alchemy_prices_by_address` fallback tag).

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `asset` | string | Filter to one monitored asset (a `PEG_REFERENCES` key, e.g. `USDC`) |
| `hours` | number | Lookback window for the time series (default 24, max 168 = 7d) |
| `latest` | boolean | `true` → newest row **per asset** (current-state summary; ignores `hours`) |
| `limit` | number | Max rows for the time-series path (default 500, max 5000) |

#### Response

```typescript
interface SpreadResponse {
  series: SpreadPoint[];
  count: number;
  latest: boolean;       // echo of ?latest
  asset?: string;        // echo when filtered
  hours?: number;        // present only on the time-series (non-latest) path
}

interface SpreadPoint {
  id: string;
  asset: string;
  referenceKind: "usd_peg" | "underlying" | "native";
  reference: string;             // 'USD' | 'ETH' | 'BTC'
  priceUsd: number | null;       // null = unavailable (fail-loud, never 0)
  referenceUsd: number | null;
  spreadBps: number | null;      // (price - ref)/ref * 1e4; null if price null
  source: string;                // provenance, e.g. 'curve3pool:get_dy:10k:USDC->USDT:feestripped'
  recordedAt: string;            // ISO 8601
}
```

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/spread?asset=USDC&hours=24"
curl "https://corridorscout.com/corridor-scout/api/spread?latest=true"
```

```json
{
  "series": [
    {
      "id": "1",
      "asset": "USDC",
      "referenceKind": "usd_peg",
      "reference": "USD",
      "priceUsd": 0.9998,
      "referenceUsd": 1.0,
      "spreadBps": -2,
      "source": "curve3pool:get_dy:10k:USDC->USDT:feestripped",
      "recordedAt": "2026-07-08T16:00:00.000Z"
    }
  ],
  "count": 1,
  "latest": false,
  "asset": "USDC",
  "hours": 24
}
```

Errors: `400 VALIDATION_ERROR` (unknown `asset`, bad `latest`); `500 INTERNAL_ERROR`.

---

### GET /api/bsh

Raw **`bsh_snapshots`** capture series (R6.2). One row per `(bridge, chain, asset)` per
5-minute tick, served verbatim: `score` (NULL exactly when `level='unknown'` — a `0.0`
would read as *critical health*), `level`, `reason` (the per-tick typed reason), `method`,
and `underlying` (the raw signal; UI-SPEC asks for the `target_ratio` raw inputs by name
and this is the only place they are served).

> ⚠ **THIS SERIES IS NON-BACKFILLABLE FOR ACROSS, WHICH IS WHY THE ENDPOINT EXISTS.** The
> denominator is the AcrossConfigStore dataworker target and `l1TokenConfig` returns only
> the CURRENT value — the history is not retained on-chain (§9A.3, D3). A score at instant
> T exists only because a tick wrote it down. Until R6.2 there was **no read path** for it:
> `/api/bridges/:bridge/health` computes BSH **live**, so the only external trace of a
> historical reading was a band crossing in `threshold_exceedances`.

**This route serves ROWS; `/api/bridges/:bridge/health` serves an ANSWER.** Different
populations; a figure there and a row here are not two views of one number.

Params: `bridge` · `chain` · `asset` · `hours` (24, max 168) · `latest` · `limit` (500, max
5000). `coverage` is enumerated from `BRIDGES × BRIDGE_CHAINS × bshAssetPopulation()` and
classified by `bsh-coverage.ts` — **never from the rows** — so a monitored pair that
produced nothing is present with `rowsInResponse: 0`, and Stargate still appears as
`captured: false`. `truncation` is `null` on the `latest` path (no cap applied there;
`null` ≠ `truncated:false`).

⚠ **BSH carries no coverage-version stamp and one must not be invented.** §18.7's stamp
exists because `dap_usd` is a Σ over a declared venue set. A BSH row is single-source; its
provenance axis is **`method`**, which is why a methodology change ships as a new method
string rather than silently re-basing. Segment a fit by `(bridge, chain, asset, method)`.

---

### GET /api/flow/history

The **persisted** flow-ratio LFV series — `lfv_snapshots` (R6.3). Sibling of
`/api/flow/chains`, not a sub-resource: that route computes the flow leg live and composes
it with BSH; this serves the capture table alone — no BSH leg, no composite, no score.

> ⚠⚠ **`lfv_snapshots` IS WRITE-ON-CHANGE, NOT DENSE.** A row is persisted only when a
> chain's **status transitions**. A gap means *"the status did not change"* — the chain was
> read on every tick throughout. It does **not** mean no data and does **not** mean zero.
> Three traps the payload is shaped to prevent:
> 1. **Gaps.** Every row carries `statusValidUntil` / `statusValidUntilBasis`
>    (`next_transition` | `open` | `unknown_truncated`) / `statusHeldForSeconds` — a row is
>    an **interval**, not a point. `open` = still in force, never absence.
> 2. **The window head.** The status at `since` was usually set by a row older than the
>    window; each chain's newest such row is served as `position: "carry_in"` — a real
>    persisted row, never synthesised, exempt from `limit`.
> 3. **⚠ The MAGNITUDES do not hold across the interval.** Write-on-change keys on
>    *status*; `flowRatio`/`netFlowUsd` drift continuously within one and are observed only
>    at the transition instant — hence `observation` nested under a row whose interval sits
>    on `status`. **Neither step-hold nor interpolate them.**
>
> No densified view is offered, opt-in or otherwise: synthetic rows would put readings in
> the response that no collector ever wrote.

⚠ Out-of-range `hours`/`limit` **400, they are NOT clamped** — a deliberate divergence from
the dense capture reads. On a dense series a clamp shortens a chart; here it manufactures a
falsehood, because a caller silently given a shorter window sees no transitions in the part
that was cut and, since a gap means "unchanged", concludes the chain was stable through a
period nobody looked at.

`chains[]` is enumerated from `CHAIN_IDS`, never the rows, with five states —
`transitions_observed` · `unchanged_in_window` (the write-on-change state) ·
`unknown_truncated` · `no_history` · `excluded_by_filter` (a `?chain=` filter must not make
other chains report "we hold nothing" when the truth is "we did not look").

---

### GET /api/depth

Depth-at-Peg (DaP) capture series (Phase R1a — see DATA-MODEL §19). Per (asset, venue,
pair, band) two-sided market depth within ±{10,25,50} bps of the $1.00 peg, in USD.
`series[]` is the **raw capture** (RCR and the other §B.6 metrics are R-M1 calculators, not
this endpoint); `aggregates[]` adds the `(asset, bandBps)` Σ-over-venues roll-up with its
quote-class decomposition and coverage stamp.

Fail-loud preserved: a failed venue fetch is a row with `bidDepthUsd`/`askDepthUsd` =
`null` and a typed `unavailableReason` (`rate_limited` | `api_error` | `pair_missing`) —
never a skipped row, never a fabricated 0. A genuine empty band is 0. `venue` is always
exposed, because **coverage is US-accessible venues BY DESIGN** (D18, 2026-08-17):
**v2 = Coinbase + Kraken + Bitstamp** (Bitstamp added by R1a-v2, D19, 2026-08-18). Aggregate
depth therefore measures **US-accessible depth** and does not claim to be global, and
**PYUSD and USDe remain single-venue on Kraken even after v2** — so consumers must aggregate
with the venue set visible. See DATA-MODEL §19 for the per-asset Kraken-share table.

> ⚠ **`coverage.publication` gates EXTERNAL use of these figures** (PO ruling D19,
> 2026-08-18). Capture and internal computation are permitted by every contributing venue;
> **publishing derived figures to third parties is not**, until each venue's redistribution
> posture is resolved by counsel review, licence, or explicit permission. Today the block
> reads `posture: "collect_and_compute"` with `blockingVenues: ["bitstamp","coinbase","kraken"]`.
> Read it before wiring this endpoint into anything third parties can see.

**The aggregate, the decomposition and the stamp** (PO ruling — DATA-MODEL §18.7):

- `dapUsd` is the **heterogeneous sum** over every declared venue/pair in the group (total
  absorbable exit is the question DaP answers; the USDT-quoted USDC book is a real exit
  tunnel and stays in). `subtotals` splits it by **quote class** — `usd_direct` (pair quoted
  in true USD) and `usdt_relative` (quoted in USDT, 1:1 by design) — so the pure USD-direct
  view is served, not merely recomputable. Keys come from `DAP_QUOTE_CLASSES`, so a new class
  cannot appear in the data without appearing here.
- **A figure is withheld rather than understated.** `dapUsd` is non-null only when the
  group's `(venue, pair)` set **exactly equals** the declared composition for that asset
  **and** every member has both sides. A declared member absent (`missingMembers` — e.g. a
  `venue` filter or `limit` truncation), an undeclared member present (`unexpectedMembers`)
  or a failed book (`unavailableMembers`) each null the affected figure and **name the
  member**. Subtotals are scoped per class, so a class whose own members were all observed
  survives the other class's outage.
- **A class with no declared member is `null`, not `0`** — `0` would assert an empty book (a
  market claim) instead of "no such book is in coverage".
- **`coverageVersion` cannot lie**: it is stamped only on an exact composition match, so a
  venue added without a declared version nulls both the stamp and the total instead of
  re-basing the series. Declared versions: **`v1`** (2026-07-09, Coinbase + Kraken, 8 triples)
  and **`v2`** (2026-08-18, + Bitstamp, 10 triples). **Pre-2026-08-18 ticks keep their `v1`
  stamp on the series path** — historical rows are judged against the composition they were
  captured under, never today's registry. Availability is a separate axis — a verified composition with a
  dead book keeps its stamp and loses its total. Fits must **segment** on this value and
  never span it (DATA-MODEL §18.1 FIT-TIME COVERAGE).
- `entityKey` is the `dap_usd` exceedance identity, so an aggregate joins directly to
  `GET /api/exceedances?series=dap_usd&entityKey=…`.
- **Which composition an aggregate is judged against differs by path** (`coverageBasis`).
  `latest=true` asks what depth is *now*, so the live registry is both the right
  completeness basis and the right stamp (`coverageBasis: "venue_registry"`). The **time
  series is judged tick by tick**: each tick resolves its **own** version from its own
  observed `(asset, venue, pair)` triples (`coverageBasis: "observed_tick"`, the same
  matcher `scripts/backfill-exceedances.ts` uses), because a stored tick was summed over
  whatever set was in force *at the time*. Judging history against today's registry would
  blank the entire pre-boundary era the moment a venue is added.
- **Registry drift degrades the `latest` path only.** If the live registry matches **no**
  declared coverage version (a config regression), the raw `series[]` still serves and
  `latest` aggregates degrade to `[]` with `coverage.unresolvedReason: "registry_drift"` —
  the non-backfillable capture read never goes down for an aggregate-side fault. The time
  series is **immune**: it never consults the registry, so stored history whose own
  composition *is* declared keeps rendering, stamped with its own version.
- **A tick whose composition matches no declared version** is withheld and labelled, never
  guessed: `dapUsd` and every subtotal `null`, `coverageVersion`/`coverageBasis` `null`,
  `unresolvedReason: "tick_composition_unrecorded"`, `complete: false`, and
  `missingMembers`/`unexpectedMembers` deliberately **empty** (both are diffs against a
  declared set, and there is none). Because resolution is at **tick granularity**, an
  `asset`- or `venue`-**filtered** time-series read never observes a whole tick and is
  labelled this way rather than stamped from a slice — chart the unfiltered series and
  filter client-side. A `limit`-truncated window does the same to its oldest tick.
- **Coverage aliasing is OBSERVED server-side; nothing in the response changes.** On the
  series path only, a tick whose resolved version differs from the version in force at its
  `recordedAt` bumps `corridor_dap_coverage_alias_observed_total` (`/api/metrics`). Because
  coverage is recomputed **per request**, that counter is **traffic-weighted read exposure** —
  a **tripwire** for "does aliasing exist at all", **never** a count of affected ticks. The
  per-tick **census** is the `npm run exceedance-backfill` run summary. Resolution is
  unaffected: `effectiveFrom` is read here to observe, never to decide. DATA-MODEL §18.6.
- **Age spread (`latest`).** The latest path takes the newest row per tuple with no shared
  time window, so one leg can be far staler than another. The stale leg is **summed, not
  dropped** (dropping understates depth, and `dap_usd` is one-sided *below*, so an
  understated total reads as phantom thin depth); the spread is surfaced instead via
  `oldestRecordedAt` / `recordedAtSpreadSeconds`. On a tick the two timestamps are equal
  and the spread is 0.
- `unclassifiedPairs` is non-empty when a member's quote is outside `DAP_QUOTE_CLASSES`: it
  is in the total but in **no** subtotal, so "subtotals sum to total" holds **only** while
  this array is empty. Empty under v1 and v2 (every declared pair quotes USD or USDT).

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `asset` | string | Filter to one `ASSESSED_ASSETS` symbol (USDT, USDC, DAI, PYUSD, USDe). **BEHAVIOUR CHANGE (D18, 2026-08-17):** the assessed set dropped from six to five — `?asset=FDUSD` now returns **400 `VALIDATION_ERROR`** (unknown asset) instead of a valid-but-empty result. FDUSD is out of scope by design, not an asset awaiting coverage. |
| `venue` | string | Filter to one venue (`coinbase` \| `kraken` \| `bitstamp`). ⚠ A venue filter makes every affected `aggregates[]` total **null with `missingMembers` named** — a filtered set is not the declared composition, and a partial sum would understate depth. |
| `band` | number | Filter to one band (10 \| 25 \| 50) |
| `latest` | boolean | `true` (default) → newest row **per** (asset, venue, pair, band); ignores `hours` |
| `hours` | number | Lookback window when `latest=false` (default 24, max 168 = 7d) |
| `limit` | number | Max rows for the time-series path (default 500, max 5000) |

#### Response

```typescript
interface DepthResponse {
  series: DepthPoint[];
  count: number;            // rows in `series`, not aggregates
  latest: boolean;
  aggregates: DepthAggregate[]; // [] only on the latest path when the registry is drifted;
                                // the time series withholds PER TICK instead (see `coverage`)
  coverage: DepthCoverage;
  asset?: string;   // echoed when filtered
  venue?: string;
  band?: number;
  hours?: number;   // present only on the time-series (latest=false) path
}

interface DepthAggregate {
  asset: string;
  bandBps: number;               // 10 | 25 | 50
  entityKey: string;             // 'USDC:10bps' — the dap_usd exceedance identity
  recordedAt: string;            // ISO 8601; freshest input in the group
  oldestRecordedAt: string;      // ISO 8601; stalest input — bounds how old the Σ's legs are
  recordedAtSpreadSeconds: number; // recordedAt − oldestRecordedAt; 0 on a tick
  dapUsd: number | null;         // heterogeneous Σ(bid+ask); null unless the composition is
                                 // verified AND every member observed (never a partial sum)
  subtotals: {                   // keys iterate DAP_QUOTE_CLASSES
    usd_direct: number | null;   // null = withheld, or no member of this class in coverage
    usdt_relative: number | null;
  };
  coverageVersion: string | null;  // 'v1' | 'v2'; null when the member set ≠ the declared
                                   // composition. A pre-2026-08-18 tick stamps 'v1'.
  coverageBasis: 'venue_registry' | 'observed_tick' | null;  // what the stamp was resolved
                                 // from — registry on `latest`, the tick's own rows on the
                                 // series; null when the basis itself is unresolved
  unresolvedReason: string | null; // 'tick_composition_unrecorded' when this tick matches no
                                 // declared version; null otherwise
  complete: boolean;               // dapUsd !== null
  unavailableMembers: { venue: string; pair: string; reason: string }[];
  missingMembers:     { venue: string; pair: string; quoteClass: string | null }[];
  unexpectedMembers:  { venue: string; pair: string; quoteClass: string | null }[];
  unclassifiedPairs:  string[];    // quote outside DAP_QUOTE_CLASSES → in total, in no subtotal
}

interface DepthCoverage {         // request-level; ALWAYS the LIVE registry's composition,
                                  // even on the series path (where stamps come per tick)
  version: string | null;         // 'v2' since 2026-08-18 ('v1' before it)
  effectiveFrom: string | null;   // 'YYYY-MM-DD' — DOCUMENTATION ONLY, never matched on:
                                  // resolution is set equality over (asset, venue, pair).
                                  // Read server-side for alias OBSERVATION only (a counter,
                                  // nothing served changes) — DATA-MODEL §18.6
  note: string | null;            // the partial-coverage caveat, travelling with the number
  composition: { asset: string; venue: string; pair: string; quoteClass: string | null }[];
  quoteClasses: string[];         // ['usd_direct', 'usdt_relative']
  stampBasis: 'venue_registry' | 'observed_tick';  // which basis produced the per-aggregate
                                  // stamps in THIS response — explains a `version: 'v2'`
                                  // sitting beside aggregates stamped 'v1' on the series path
  unresolvedReason: string | null; // 'registry_drift' when the LIVE registry matches no
                                   // declared version (affects the latest path only)
  publication: DepthPublication | null;  // null only when coverage itself is unresolved —
                                   // there is no composition to judge (D19)
}

interface DepthPublication {      // MAY these figures be published externally? (D19)
  publishCleared: boolean;        // true ONLY when every contributing venue is
                                  // publication_granted. FAIL-CLOSED: an unrecorded venue
                                  // blocks, and 'license_pending' blocks — pending ≠ granted
  posture: 'collect_and_compute' | 'publish_cleared';
  blockingVenues: string[];       // sorted; one blocking member blocks the whole aggregate,
                                  // because dap_usd is a SUM — no partial publication of a sum
  unrecordedVenues: string[];     // in the composition with NO recorded terms check at all
}

interface DepthPoint {
  id: string;
  recordedAt: string;            // ISO 8601
  asset: string;
  venue: string;                 // 'coinbase' | 'kraken' | 'bitstamp'
  venueClass: string;            // 'cex' (dex arrives with R1b)
  pair: string;                  // measured verbatim: 'USDT/USD', 'USDS/USD', 'USDC/USDT'
  bandBps: number;               // 10 | 25 | 50
  bidDepthUsd: number | null;    // Σ price·size, bids in [1−b, 1.00]; null = failed fetch (never 0)
  askDepthUsd: number | null;    // Σ price·size, asks in [1.00, 1+b]
  dapUsd: number | null;         // bid + ask; null if either side is unavailable (never a partial sum)
  levelsObserved: number | null;
  method: string;                // 'orderbook_banded_v1' | 'orderbook_banded_usdt1to1_inverted_v1'
  unavailableReason: string | null; // 'rate_limited' | 'api_error' | 'pair_missing'
}
```

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/depth?asset=USDT&band=25"
curl "https://corridorscout.com/corridor-scout/api/depth?latest=false&venue=kraken&hours=24"
```

Errors: `400 VALIDATION_ERROR` (unknown `asset`, invalid `band`/`latest`); `500 INTERNAL_ERROR`.

---

### GET /api/issuer-flows

Issuer **mint/burn capture** (Phase R2 — see DATA-MODEL §20). One row per on-chain supply
change of an assessed asset, newest first.

**Phase boundary:** this endpoint does **no NIV, RCR or ARC computation** — those are the
**R-M1** deterministic calculators. It serves the raw capture plus a decomposed totals block.

**Scope: Ethereum mainnet only** (decision D20). ⚠ **USDT is Ethereum-scoped**: Tron is its
dominant issuance venue and is uncovered, so a Tron-only redemption wave is invisible here
and USDT gross burns are understated by construction. This ships in the response's
`caveats` block, not only in this doc.

#### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `asset` | string | all | One of the captured tokens (`USDT`, `USDC`, `DAI`, `USDS`, `PYUSD`, `USDe`). 400 otherwise. |
| `issuer` | string | all | An `ISSUER_REGISTRY` slug. Accepts identity-only issuers (e.g. `first_digital`) — identity is wider than scope. 400 otherwise. |
| `eventType` | string | all | `mint` \| `burn`. 400 otherwise. |
| `flowClass` | string | all | `issuer_treasury` \| `bridge` \| `protocol_module` \| `unclassified`. 400 otherwise. |
| `hours` | integer | `24` | Lookback window on `occurredAt` (the BLOCK timestamp). Clamped to `[1, 4320]` (180d, the backfill horizon) — clamped, not rejected. |
| `limit` | integer | `500` | Max rows. Clamped to `[1, 5000]`. |

#### Response `200 OK`

```json
{
  "series": [
    {
      "occurredAt": "2026-08-18T12:00:00.000Z",
      "chain": "ethereum",
      "asset": "USDC",
      "issuer": "circle",
      "eventType": "mint",
      "method": "zero_address_transfer",
      "amountRaw": "5000000",
      "amountUsd": 4.9995,
      "priceUsd": 0.9999,
      "counterparty": "0x55fe002aeff02f77364de339a1292923a15844b8",
      "flowClass": "issuer_treasury",
      "blockNumber": 25781400,
      "txHash": "0xabab…",
      "logIndex": 3
    }
  ],
  "count": 1,
  "hours": 24,
  "totals": [
    {
      "asset": "DAI",
      "eventType": "burn",
      "byFlowClass": [
        { "flowClass": "protocol_module", "count": 1300, "pricedCount": 1300, "amountUsd": 800000000 },
        { "flowClass": "issuer_treasury", "count": 4, "pricedCount": 4, "amountUsd": 5000000 }
      ]
    }
  ],
  "unpricedCount": 0,
  "caveats": {
    "grossIsNotIssuance": "…decompose first.",
    "unclassifiedMeansUnproven": "…NOT \"other\".",
    "usdtIsEthereumScoped": "…Tron … uncovered …",
    "usdValuation": "…never a $1.00 peg by assumption (decision D1).",
    "slotAggregation": "DAI and USDS are recorded verbatim as separate assets of one assessed slot…"
  }
}
```

**`amountRaw` is an exact INTEGER STRING** — never exponential notation. It is a `uint256`
beyond IEEE-754 exact range, so serialising it as a number would silently round the one exact
field on the row, and rendering it as `4.079e+26` (what a naive `String()` on the underlying
decimal produces for any 18-decimal amount ≥ 1,000 tokens) would break `BigInt()` on it. On
unpriced rows it is the **only** usable magnitude.

**`amountUsd` / `priceUsd` are `null` when no observed price was available** — never `$1.00`
by assumption (decision D1 / phase 0a). **Backfilled rows are `null` by construction** (no
historical price source), as are live events older than the pricing freshness window (a
catch-up tick must not value week-old events at today's spot price). That is why
`unpricedCount` is served, and why each `byFlowClass` entry carries **`pricedCount` beside
`count`**: the summed `amountUsd` covers only the priced rows, so beside a full count it would
understate the group while looking complete. `amountRaw` is exact regardless.

**`totals` is ALWAYS decomposed by flow class and carries NO pre-summed gross figure.**
This is deliberate. RCR's v1 denominator is "gross burns 24h", and over a measured 33h window
DAI moved **$1.64B gross on ≈ −$8M net** with the same Sky module on both sides — so a single
"gross" number would let a consumer pick up protocol round-tripping as redemption *without
ever making that choice explicitly*. A caller who wants a gross figure must decide which
classes belong in it, which is exactly the choice R-M1 owns.

**`flowClass: "unclassified"` means NOT PROVEN, never "other".** USDe and PYUSD mint directly
to the depositor, so genuine issuance lands in this class. `counterparty` is served verbatim
on every row so any classification stays auditable and re-derivable.

## ⚠ 404 IS FOR IDENTITY, NEVER FOR DATA AVAILABILITY

**An entity that EXISTS always resolves — with its gaps typed.** A 404 asserts "this
thing is not a thing we have"; it must never be used to mean "we hold no rows for it
right now". Those are different statements and callers act on them differently: the
first is permanent and terminal, the second is a temporary hole in one section.

| situation | response |
|---|---|
| Malformed id / unknown bridge / unknown chain | **400** `VALIDATION_ERROR` |
| Syntactically valid but not a monitored entity | **404** `NOT_FOUND` |
| Monitored entity, some data unavailable | **200**, that section typed as absent |
| Monitored entity, all data unavailable | **200**, every section typed as absent |

Absence is expressed with the system's existing vocabulary — the same family as
`dap_unavailable`, `attestation_missing`, `classification_missing`, `no_gap_baseline`,
`supply_scope_incomplete` — not with a status code and not with zeros. **A zero is a
measurement; `null` plus a reason is an absence.** Rendering an absence as `0` produces
a fabricated reassurance (`tvlUsd: 0` alongside `fragility: 'low'`) that is
indistinguishable from a genuine reading.

**Worked example, and why this became a rule (2026-08-26, AUDIT #36).**
`GET /api/corridors/[id]` used to return 404 when a corridor had no transfers AND no
pool snapshots. The Stage-1 exclusion made "no pool snapshots" a routine, designed state
for every Across corridor — so a monitored corridor would have reported *not found*,
telling a caller the corridor does not exist when what was missing was one section of
its data. It now resolves 200 with `pool.unavailableReason` naming why, while transfers,
stats and anomalies serve normally.

⚠ **The response SHAPE is identical whether the data is present or absent** — the same
keys, with nulls and a reason instead of numbers. That is what lets the Stage-2 replay
repopulate it with no contract change, and it is why the dashboard needed no edit: it
already keyed off `pool.fragility === 'unknown'`.

## Errors

| Status | Code | When |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | Unknown `asset`, `issuer`, `eventType`, `flowClass` or `bridge` |
| 500 | `INTERNAL_ERROR` | Unhandled server error (underlying message never leaked) |

---

### GET /api/attestations

The **reserve attestation registry** (Phase R3 — see DATA-MODEL §21): the structured
composition of published issuer reserve attestations, the `ingested_document` data
class. Public read; `dataClass` is served on every record.

**Default returns the latest version per `(issuer, subject)`**; `?history=true`
returns every version of every as-of date. Every record carries its **age and
staleness** — an attested number is a photograph, not a feed (SPEC §B.6.4) — and the
response always includes a `coverage` block naming **every expected (issuer, subject),
including those with no attestation at all**. Absence of disclosure is itself
assessment content, so it is in the default response, not behind a flag.

This endpoint does **not** compute ARC; that is R-M1's calculator over these rows
(`src/intelligence/arc.ts`, **BUILT 2026-08-24** — DATA-MODEL §26). ~~⚠ **ARC IS NOT SERVED BY
ANY ROUTE YET:** pass 2 freezes it into `metric_snapshots` and adds no read endpoint —
`/api/stablecoins/:asset/liquidity` remains **R-D**.~~ **→ CORRECTED 2026-08-30 (UI pass C):
`GET /api/stablecoins/:asset/liquidity` SHIPPED with UI pass A (2026-08-28) and serves the
frozen `arc` rows.** And while this registry is empty, every frozen `arc` row reads
`attestation_missing`, permanently so for `sky/DAI` and `ethena/USDe`.

**Its read surface is the Attestation Registry tool (`/tools/attestations`, UI pass C).** It
renders the `coverage` block — every expected pair including the missing ones — with
`ageDays`/`status` prominent, provenance linked, and composition by statutory category where
a document exists. ⚠ **It is READ-ONLY, by ruling:** ingestion stays `POST /api/attestations`
behind `ADMIN_SECRET` (the R3 pattern — ingestion-auth, NOT RBAC), which is an operator step
and never a browser form in Phase 0.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `issuer` | string | Filter by issuer slug (`tether`, `circle`, `sky`, `paxos`, `ethena`, …) |
| `subject` | string | Filter by the token the attestation covers (`USDT`, `USDC`, `PYUSD`, …) |
| `history` | boolean | Return all versions instead of latest-per-subject (default false) |
| `limit` | number | Max results (default 100, max 500) |
| `offset` | number | Pagination offset (default 0) |

⚠ `limit`, `offset` and `history` affect the `attestations` page **only**. `coverage`
is computed by its own query, so no paging flag can make a missing subject disappear;
`issuer`/`subject` narrow it, nothing else does.

⚠ **`updatedAt` (added 2026-08-30, UI pass C) is the age of the RESPONSE, never of a
document.** Document age is per record (`ageDays`), measured from each attestation's **own
as-of date**. The two must not be conflated: a freshly-served page must not make a
six-month-old report read as fresh. It matters most in the current state, where **zero
documents are held** and a screen-level timestamp is the only age there is.

#### Response

```typescript
interface AttestationsResponse {
  attestations: ReserveAttestation[];
  count: number;                 // records in this page
  coverage: CoverageEntry[];     // EVERY expected (issuer, subject), missing ones included
  staleAfterDays: number;        // provisional staleness threshold (45)
  staleThresholdBasis: "provisional_v1";
  updatedAt: string;             // when the RESPONSE was produced — NOT any document's age
  dataClass: "ingested_document";
  history: boolean;
  limit: number;
  offset: number;
}

interface ReserveAttestation {
  id: string;
  issuer: string;
  subject: string;               // token covered, verbatim — part of the identity
  asOfDate: string;              // YYYY-MM-DD — the attestation's OWN effective date
  publishedDate: string | null;  // YYYY-MM-DD
  attestor: string;
  sourceUrl: string;             // required
  documentHash: string | null;   // null = weaker but honest provenance
  dataClass: "ingested_document";
  composition: Record<string, number>;     // enum-keyed USD amounts (DATA-MODEL §21.2)
  rawComposition: Record<string, unknown>; // the attestation's own line items, verbatim
  totalAttestedUsd: number | null;         // SERVER-computed from composition; null if it no longer validates
  circulatingUsd: number | null;           // AS STATED in the attestation, if stated
  ageDays: number;               // from asOfDate, NOT from ingestion. Negative if future-dated.
  status: "current" | "attestation_stale";
  staleAfterDays: number;
  ingestedAt: string;            // ISO 8601
  version: number;               // monotonic per (issuer, subject, asOfDate)
  createdAt: string;             // ISO 8601
}

interface CoverageEntry {
  issuer: string;
  subject: string;
  status: "current" | "attestation_stale" | "attestation_missing";
  latestAsOfDate: string | null; // null ⇒ nothing ever ingested
  ageDays: number | null;
  expected: boolean;             // false = held but outside the expected set
}
```

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/attestations?issuer=circle"
```

```json
{
  "attestations": [
    {
      "id": "7",
      "issuer": "circle",
      "subject": "USDC",
      "asOfDate": "2026-07-31",
      "publishedDate": "2026-08-11",
      "attestor": "Deloitte & Touche LLP",
      "sourceUrl": "https://www.circle.com/transparency/reserve-report-2026-07.pdf",
      "documentHash": "sha256:e3b0c44298fc1c149afbf4c8996fb924…",
      "dataClass": "ingested_document",
      "composition": { "cash": 5000000000, "tbills_le93d": 55000000000 },
      "rawComposition": {
        "Cash held at regulated financial institutions": 5000000000,
        "U.S. Treasury securities (<=93 days)": 55000000000
      },
      "totalAttestedUsd": 60000000000,
      "circulatingUsd": 59900000000,
      "ageDays": 18.5,
      "status": "current",
      "staleAfterDays": 45,
      "ingestedAt": "2026-08-18T09:00:00Z",
      "version": 1,
      "createdAt": "2026-08-18T09:00:00Z"
    }
  ],
  "count": 1,
  "coverage": [
    { "issuer": "circle", "subject": "USDC", "status": "current", "latestAsOfDate": "2026-07-31", "ageDays": 18.5, "expected": true }
  ],
  "staleAfterDays": 45,
  "staleThresholdBasis": "provisional_v1",
  "dataClass": "ingested_document",
  "history": false,
  "limit": 100,
  "offset": 0
}
```

⚠ **`attestation_missing` is a normal, permanent state for some issuers.** With no
filter, the coverage block reports `sky/DAI`, `sky/USDS` and `ethena/USDe` as
`attestation_missing` indefinitely — neither issuer publishes a GENIUS-shaped reserve
attestation. There is deliberately no "not applicable" status: the absence is the
assessment content (DATA-MODEL §21.3).

---

### POST /api/attestations

Ingest one reserve attestation (append-only). **Guarded by the ingestion-auth
pattern** — `Authorization: Bearer <ADMIN_SECRET>` (a second secret, distinct from
`CRON_SECRET`; NOT RBAC). This is a low-frequency, human-operated fact-ingestion
route: a published document, transcribed with its provenance. Each POST creates a
**new row at the next version** for its `(issuer, subject, asOfDate)`; corrections are
new versions, never mutations.

#### Request Body

```typescript
interface AttestationInput {
  issuer: string;                 // validated against ISSUER_REGISTRY slugs
  subject: string;                // token covered — validated against that issuer's tokens
  asOfDate: string;               // YYYY-MM-DD (calendar date; a timestamp is rejected)
  publishedDate?: string;         // YYYY-MM-DD
  attestor: string;               // signing firm, verbatim
  sourceUrl: string;              // required, must be a URL
  documentHash?: string;          // hash of the retrieved document
  composition: Record<string, number>;     // enum-keyed USD amounts (DATA-MODEL §21.2)
  rawComposition: Record<string, unknown>; // the attestation's own line items, verbatim
  circulatingUsd?: number;        // AS STATED in the attestation
  allowUnregisteredIssuer?: boolean; // explicit opt-out of the issuer guard (not persisted)
  allowUnregisteredSubject?: boolean; // explicit opt-out of the subject guard (not persisted)
}
```

`dataClass`, `version`, `id` and `ingestedAt` are **server-controlled** and rejected if
present in the body (strict schema). On success returns **201** with the created
`ReserveAttestation`.

**Validation that matters (all fail-loud, nothing is coerced):**

- `composition` keys must be `STATUTORY_RESERVE_CATEGORIES` members; values must be
  finite, non-negative **numbers**. A numeric string (`"1000"`) is **rejected, not
  parsed** — coercion would put an unreviewed transcription into an append-only table.
- `rawComposition` must be a non-empty object. It is the ground truth `composition` is
  checked against, so it cannot be blank.
- `asOfDate` must be a real calendar date. `2026-02-30` is rejected rather than rolled
  forward to March 2, which would silently move the attestation's effective period. It
  also **may not lead the clock by more than 2 days**: an attestation reports a period
  that has ended, and a mistyped year would store cleanly, read `current`, and keep the
  staleness alert silent for a year.
- `circulatingUsd` must be `< 1e24` with at most **6 decimal places** — the bounds of its
  `numeric(30,6)` column. Postgres would round a finer value **silently** and reject an
  oversized one as a bare `500`; both are `400`s here, naming the field.
- **Known-entity guards.** A typo'd `issuer` or `subject` on an append-only table
  creates a permanent orphan lineage no assessment ever renders, so both are a `400`
  unless explicitly overridden. `subject` is checked against the issuer's registered
  tokens — `allowUnregisteredSubject: true` is how another of its tokens is ingested
  (Paxos USDP). A **brand-new issuer needs BOTH overrides**: with no registered
  contracts, its subject cannot be checked either.

#### Example

```bash
curl -X POST "https://corridorscout.com/corridor-scout/api/attestations" \
  -H "Authorization: Bearer $ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "issuer": "circle",
    "subject": "USDC",
    "asOfDate": "2026-07-31",
    "publishedDate": "2026-08-11",
    "attestor": "Deloitte & Touche LLP",
    "sourceUrl": "https://www.circle.com/transparency/reserve-report-2026-07.pdf",
    "documentHash": "sha256:e3b0c44298fc1c149afbf4c8996fb924…",
    "composition": { "cash": 5000000000, "tbills_le93d": 55000000000 },
    "rawComposition": {
      "Cash held at regulated financial institutions": 5000000000,
      "U.S. Treasury securities (<=93 days)": 55000000000
    },
    "circulatingUsd": 59900000000
  }'
```

Errors: `400 VALIDATION_ERROR` (bad shape, non-enum composition key, coerced-looking
value, empty `rawComposition`, impossible or far-future date, out-of-range
`circulatingUsd`, unregistered issuer/subject without the matching override); `401 Unauthorized` (missing/wrong bearer when `ADMIN_SECRET`
is set); `409 VERSION_CONFLICT` (a concurrent append claimed the version — retry).

---

### GET /api/issuers/:issuer/profile

The **§B.5(f) issuer profile parent object** (Phase R4 — see DATA-MODEL §22): the four
§B.5(e) statutory-map factors for one issuer, its R3 attestation lineage, and every
expected per-(asset, chain) child.

**R4 stores nothing, so there is no POST here.** The profile is a read-time composition
over stores that already own every value: the classifications live in
`structural_fact_records` and are authored through `POST /api/structural-facts`
(ingestion-auth pattern); the lineage lives in `reserve_attestations` and is authored
through `POST /api/attestations`. See DATA-MODEL §22 / decision D22.

**No numeric score exists on this surface.** §B.5(a)'s `StructuralScore` and §B.6.5's
composite level are Phase 1, rule-based and server-computed — explicitly not built here.

⚠ **Two states that look alike and mean opposite things.** A factor whose `level` is
`"unknown"` was **classified** — an analyst read the primary document and it does not
establish the fact, and the record carries a basis and citation. A factor with
`status: "classification_missing"` has **never been authored**; `level` is `null` and
every provenance field is `null`. Never collapse the two. Today **every** issuer reads
`profile_missing` on **every** factor — no classification has been authored yet (the
same posture as R3's un-ingested attestations). That is the endpoint working.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `issuer` | string | Registered issuer slug (`tether`, `circle`, `sky`, `paxos`, `ethena`, `first_digital`) |

#### Response

```typescript
interface IssuerProfileResponse {
  profile: IssuerProfile;
  children: AssetChainProfileSummary[];   // every expected (asset, chain), classified or not
  generatedAt: string;                    // ISO 8601
}

interface IssuerProfile {
  entityType: "issuer";
  entityKey: string;                      // issuer slug
  issuer: string;
  issuerName: string;
  slots: string[];                        // ASSESSED_ASSETS slot labels served
  captured: boolean;                      // false = identity-only issuer (scope, not absence — D18)
  status: ProfileStatus;
  profileVersion: string;                 // "factor@version|…", alphabetical, "@none" when unauthored
  asOf: string | null;                    // OLDEST contributing as-of (ISO) — see DATA-MODEL §22.3
  asOfNewest: string | null;
  ageDays: number | null;                 // since asOf (the oldest)
  staleAfterDays: number;                 // provisional (90)
  completeness: {
    expected: number;                     // 4 for an issuer, 3 for a child
    classified: number;
    missingFactors: string[];             // taxonomy order
  };
  factors: ProfileFactor[];               // ALWAYS all 4, missing ones included
  attestationLineage: AttestationLineageEntry[];  // ALWAYS every expected subject
  attestationStaleAfterDays: number;      // R3's threshold (45) — NOT staleAfterDays (90)
}

type ProfileStatus =
  | "current"             // complete and within staleAfterDays
  | "profile_stale"       // complete, oldest factor strictly PAST staleAfterDays
  | "profile_incomplete"  // some but not all classified (MAY also be stale — read ageDays)
  | "profile_missing";    // zero classified

interface ProfileFactor {
  factor: string;                         // G-SFR taxonomy factor (DATA-MODEL §17.1)
  status: "classified" | "classification_missing";
  level: string | null;                   // null ⟺ classification_missing — NEVER coerced to "unknown"
  permittedLevels: string[];              // the full enum scale for this factor
  dataClass: "analyst_classification" | null;
  basis: string | null;
  citationUrl: string | null;
  documentHash: string | null;
  asOf: string | null;                    // the classification's OWN as-of date
  version: number | null;
  ageDays: number | null;
  stale: boolean | null;                  // null when unauthored — "not stale" would assert freshness
  derivedFrom: string | null;             // "reserve_attestations" on reserve_conformity only
}

interface AttestationLineageEntry {
  subject: string;                        // token the report covers, verbatim
  expected: boolean;                      // false = held for a subject the registry
                                          // does not expect — surfaced, never hidden
  status: "current" | "attestation_stale" | "attestation_missing";
  asOfDate: string | null;                // YYYY-MM-DD — the attestation's OWN date
  ageDays: number | null;
  version: number | null;
  attestor: string | null;
  sourceUrl: string | null;
  documentHash: string | null;
}
```

⚠ **Two staleness clocks.** A lineage entry's `status` is computed against
`attestationStaleAfterDays` (R3's 45 days), **not** the profile's `staleAfterDays` (90). Both
are on the response; reading an `attestation_stale` entry against 90 would be wrong. Lineage
`ageDays` is rounded exactly as `GET /api/attestations` rounds it, so one document never
reports two different ages.

`children[]` are `AssetChainProfile` objects **without** the embedded `parent` — the
parent is already this response's top-level object, and a second copy invites a consumer
to read the stale one. Use `GET /api/asset-profiles` when you need the child with its
parent embedded.

#### Example

```bash
curl http://localhost:3000/corridor-scout/api/issuers/circle/profile
```

```json
{
  "profile": {
    "entityType": "issuer",
    "entityKey": "circle",
    "issuer": "circle",
    "issuerName": "Circle",
    "slots": ["USDC"],
    "captured": true,
    "status": "profile_missing",
    "profileVersion": "permitted_issuer_status@none|redemption_policy_disclosure@none|reserve_conformity@none|yield_arrangement_exposure@none",
    "asOf": null,
    "asOfNewest": null,
    "ageDays": null,
    "staleAfterDays": 90,
    "completeness": {
      "expected": 4,
      "classified": 0,
      "missingFactors": [
        "permitted_issuer_status",
        "reserve_conformity",
        "redemption_policy_disclosure",
        "yield_arrangement_exposure"
      ]
    },
    "factors": [
      {
        "factor": "reserve_conformity",
        "status": "classification_missing",
        "level": null,
        "permittedLevels": ["conforming", "partial", "non_conforming", "unassessable", "unknown"],
        "dataClass": null,
        "basis": null,
        "citationUrl": null,
        "documentHash": null,
        "asOf": null,
        "version": null,
        "ageDays": null,
        "stale": null,
        "derivedFrom": "reserve_attestations"
      }
    ],
    "attestationStaleAfterDays": 45,
    "attestationLineage": [
      {
        "subject": "USDC",
        "expected": true,
        "status": "attestation_missing",
        "asOfDate": null,
        "ageDays": null,
        "version": null,
        "attestor": null,
        "sourceUrl": null,
        "documentHash": null
      }
    ]
  },
  "children": [
    {
      "entityType": "asset_chain",
      "entityKey": "USDC:arbitrum",
      "issuer": "circle",
      "asset": "USDC",
      "chain": "arbitrum",
      "chainId": 42161,
      "tokenAddress": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
      "status": "profile_missing",
      "profileVersion": "bridge_dependence@none|redemption_path@none|wrapper_structure@none",
      "asOf": null,
      "asOfNewest": null,
      "ageDays": null,
      "staleAfterDays": 90,
      "completeness": { "expected": 3, "classified": 0, "missingFactors": ["wrapper_structure", "bridge_dependence", "redemption_path"] },
      "factors": []
    }
  ],
  "generatedAt": "2026-08-19T12:00:00.000Z"
}
```

*(`factors` and `children` abridged above — the real response carries all 4 factors, all
3 child factors, and all 6 USDC deployments.)*

Errors: `404 ISSUER_NOT_FOUND` (unknown slug — the message names the known set; **no
`details`**, per the global envelope rule that reserves it for `VALIDATION_ERROR`);
`500 INTERNAL_ERROR`.

---

### GET /api/asset-profiles

The **§B.5(f) per-(asset, chain) child profiles** (Phase R4 — see DATA-MODEL §22): the
three `asset_chain` factors for each monitored deployment, **with the issuer parent
embedded at read time**.

Read-time inheritance is the point: nothing is denormalized into a child, so
re-classifying a parent factor lands in every child of that issuer with **no child write
anywhere**. Like its sibling, this route has **no write path**.

With no parameters it serves every expected child across every registered issuer —
including the ones with zero classifications, which is the coverage statement.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `asset` | string | Token symbol issued by a registered issuer (`USDT`, `USDC`, `DAI`, `USDS`, `PYUSD`, `USDe`) |
| `chain` | string | Monitored chain name (`ethereum`, `arbitrum`, `optimism`, `base`, `polygon`, `avalanche`) |
| `issuer` | string | Registered issuer slug |

⚠ An unknown `asset`/`chain`/`issuer` is a **400, not an empty list**: silently returning
`[]` for a typo'd symbol reads exactly like "this asset has no deployments", which is the
fabricated absence this surface exists to prevent. A **valid** but empty result is a `200`
with `count: 0` and a **discriminated** `unavailableReason` — three genuinely different
empties that must not be conflated:

| `unavailableReason` | Means |
|---|---|
| `no_monitored_deployment` | A real absence — a valid pair we do not monitor (`PYUSD` on `avalanche`). |
| `filter_mismatch` | The filters contradict each other (`asset=USDC&issuer=tether`). Nothing is absent; the combination cannot exist. |
| `issuer_out_of_scope` | An identity-only issuer (`first_digital`). Its empty child set is **scope by design** (D18), never a coverage gap. |

#### Response

```typescript
interface AssetProfilesResponse {
  profiles: AssetChainProfile[];
  count: number;
  filters: { asset: string | null; chain: string | null; issuer: string | null };
  unavailableReason: "no_monitored_deployment" | "filter_mismatch" | "issuer_out_of_scope" | null;
  generatedAt: string;
}

interface AssetChainProfile {
  entityType: "asset_chain";
  entityKey: string;                      // "ASSET:chain", the G-SFR entityKey
  issuer: string;
  asset: string;
  chain: string;
  chainId: number;
  tokenAddress: string;                   // lowercase, from TOKEN_REGISTRY
  status: ProfileStatus;
  profileVersion: string;
  asOf: string | null;
  asOfNewest: string | null;
  ageDays: number | null;
  staleAfterDays: number;
  completeness: { expected: number; classified: number; missingFactors: string[] };
  factors: ProfileFactor[];               // ALWAYS all 3
  parent: IssuerProfile;                  // read-time inheritance, never denormalized
}
```

#### Example

```bash
curl 'http://localhost:3000/corridor-scout/api/asset-profiles?asset=USDC&chain=base'
```

Errors: `400 VALIDATION_ERROR` (unknown `asset`, unmonitored `chain`, unregistered
`issuer` — `details.field` names which); `500 INTERNAL_ERROR`.

---

### GET /api/exceedances

The threshold-exceedance **peaks-over-threshold (POT)** log (Phase 1d — see DATA-MODEL
§18). One row per observation of a continuous series that crossed its configured band,
newest first. `EXCEEDANCE_SERIES` declares **eight**; six can produce rows today
(`spread_bps`, `bsh_score`, `lfv_flow_ratio`, `settlement_seconds`, `pool_utilization`,
`dap_usd`, and `niv_7d` for USDC since 2026-09-01) and **`rcr` cannot**, because its band table is empty until
their dated D5 fits land. All eight are named in `seriesStates` regardless — see below.

**Phase boundary:** this endpoint does **no GPD/EVT fitting**, no ξ/β estimation, no tail
probabilities and no confidence bands (spec §6) — it serves the raw log a Phase 1 fit will
be run over.

There is deliberately **no `latest` mode**: a POT log's value is the sparse *history*, not
a current-state row. Every row carries the full arithmetic (`threshold`, `observed`,
`direction`, `exceedanceMag`) so a consumer can independently verify the magnitude **and**
see which threshold was **in force at capture time** — bands are provisional (decision D5)
and will be recalibrated, so today's constants must never be used to reinterpret an old
row.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `series` | string | Filter to one series (see the six above) |
| `entityKey` | string | Exact match, e.g. `USDC`, `across:arbitrum:USDC`, `across_ethereum_arbitrum` (max 200 chars) |
| `direction` | string | `above` \| `below` |
| `hours` | number | Lookback window (default 24, max 720 = 30d) — clamped, never rejected |
| `limit` | number | Max rows (default 500, max 5000) — clamped, never rejected |

#### Response

```typescript
interface ExceedancesResponse {
  exceedances: ExceedancePoint[];
  count: number;           // counts the SERVED rows (post-gate), never the pre-gate window
  hours: number;
  updatedAt: string;       // when the RESPONSE was produced — not the age of any reading
  seriesStates: ExceedanceSeriesState[];   // one per series in the REGISTRY (see below)
  countScope: 'window' | 'filtered';       // which population the counts describe
  publication: DapPublication & { withheldSeries: string[] };  // the D19 gate (see below)
  series?: string;     // echoed when filtered
  entityKey?: string;
  direction?: string;
}

interface ExceedanceSeriesState {
  series: string;
  sidedness: 'two_sided' | 'low_side_bad' | 'high_side_bad';  // DECLARED, never inferred
  fitted: boolean;
  state: 'logged' | 'awaiting_fit' | 'withheld';
  count: number | null;    // null unless state === 'logged' AND countScope === 'window'
  fitSchedule:             // present only while awaiting — the ONE source for the date
    | { kind: 'dated'; date: string; basis: string }
    | { kind: 'trigger'; trigger: string; basis: string }
    | null;
}

interface ExceedancePoint {
  id: string;
  series: string;          // 'spread_bps' | 'bsh_score' | 'lfv_flow_ratio' |
                           // 'settlement_seconds' | 'pool_utilization' | 'dap_usd'
  entityKey: string;       // permanent series identity — format varies by series (§18.1)
  threshold: number | null;    // the band IN FORCE at capture time
  observed: number | null;     // the raw reading
  exceedanceMag: number | null; // ALWAYS POSITIVE (the POT excess); pair with `direction`
  direction: string;       // 'above' | 'below'
  observationKey: string;  // idempotency identity of the underlying observation
  recordedAt: string;      // ISO 8601
  coverageVersion: string | null; // source-set stamp; 'v1'|'v2' on dap_usd, null on the other five
}
```

**`coverageVersion` — the source-set stamp (DATA-MODEL §18.7).** Only `dap_usd` is an
aggregate over sources, so only it carries one; `null` on the other five means "**this series
has no composition**", never "unknown". It is served **verbatim**, including an id the current
build no longer declares — rows outlive the code that wrote them, and the id a row was stamped
with *is* the segment it belongs to.

> ⚠ **FIT-TIME RULE — a fit, baseline, mean or trend must NOT span two coverage versions.**
> Segment by `(series, entityKey, coverageVersion)`. An aggregate-over-sources series
> **re-bases its level** whenever a venue is added, so a level shift at a boundary is a
> **coverage** change, never a market move — spanning one reads "a new venue came online" as
> "depth tripled overnight". Never re-resolve the stamp against today's constants and never
> default it to the newest version.
>
> ⚠ **INHERIT THIS TOO — the segment can contain post-boundary ticks (subset aliasing).** The
> stamp is resolved by **composition equality alone**, so a tick recorded after a boundary
> whose new-venue rows failed to persist presents the older composition and is stamped with
> the older version. That is **benign for level-consistency** (the sum genuinely *was* over
> that member set) but is **accepted second-order SAMPLE MIXING for fits**: the tick sits in
> the earlier version's sample, so that segment's tail — and its rate `N_u/N` — carries draws
> from a regime where the extra venue existed and went unobserved. It is **observed, not
> corrected**: run `npm run exceedance-backfill -- --dry-run` over the window for the
> authoritative **per-tick census** (its run summary). The server counter
> `corridor_dap_coverage_alias_observed_total` is a **traffic-weighted tripwire** for "does
> aliasing exist at all" and is **not** a tick count. Full record: DATA-MODEL §18.7 and §18.6.

**`seriesStates` — ENUMERATED FROM THE REGISTRY, never from the rows that arrived (added
2026-08-30, UI pass C).** An empty list means two entirely different things and the rows
cannot say which:

| state | what an empty list means |
|---|---|
| `logged` | a band is fitted — **nothing crossed it** in this window. |
| `awaiting_fit` | **no band exists**, so the producer offers zero candidates and *nothing is being evaluated*. An empty log here does **not** mean nothing crossed. Today: **`rcr` only**, D5 fit dated **2026-09-28** — served on `fitSchedule` so a consumer names the date from ONE source rather than holding a second copy of a PO ruling. ⚠ `niv_7d` left this state on **2026-09-01**: it is FITTED for USDC, and its other four assets are **per-asset named absences**, which is a different thing — the series IS evaluated, and those four keys resolve no band. A per-asset absence never shows as `awaiting_fit`. |
| `withheld` | the series is DaP-derived and the D19 gate removed its rows **before serialization** for this audience. `count` is `null`: a count would itself say what crossed. |

Deriving this list from the readings would silently drop every series that produced nothing —
precisely the series a reader needs. (This repo has shipped the enumerate-from-the-readings
defect twice: AUDIT #40 / D31.5 and AUDIT #44 / D34.8.)

**`countScope` — and why a filtered request carries no counts.** `series`/`entityKey`/
`direction` narrow **which rows were fetched**, so a count over the result would report
`logged · 0` for every series the query excluded — "we measured it and nothing crossed",
when in fact we did not look. Under any of those filters `countScope` is `filtered` and
**every `count` is `null`**. `hours`/`limit` bound the window rather than selecting series,
so they leave it at `window`. `seriesStates` still names **every** series either way, so a
filtered view can never read as "these are the only series that exist".

**`publication` — the D19 publication gate (added 2026-08-30, UI pass C).** Identical in
shape to the block on `GET /api/stablecoins/:asset/liquidity`, deliberately, so one consumer
component renders the gate everywhere; it carries one extra field, `withheldSeries`.

> ⚠ **A `dap_usd` row's `observed` IS the Σ-over-venues DaP aggregate in USD, and its
> `threshold` IS the fitted USD depth floor.** Ungated, this endpoint would serve exactly the
> figures `/api/stablecoins/:asset/liquidity` withholds — one surface publishing what another
> withholds, which is the failure D32.3 exists to prevent. The predicate is **shared**
> (`src/lib/exceedance-publication.ts`), never restated.
>
> ⚠ **Withheld means NOT SERIALIZED.** A gated row is **removed**, not redacted: "depth
> crossed below its floor" is itself a statement about the gated quantity, so nulling the
> numbers would still disclose that the crossing happened. `withheldSeries` names WHICH
> series a reader is not seeing, without saying how many rows they held.
>
> ⚠ **Each row is judged against its OWN coverage stamp**, not one response-wide posture:
> this window straddles coverage versions by construction (`v1` before the 2026-08-18 seam,
> `v2` after), so no single stamp could speak for all of them. The SERIES-level state is
> judged against the composition being captured now, which is what lets a gated series
> report `withheld` on a window that returned no rows at all.
>
> ⚠ **The decision is made here and travels in the payload.** A consumer renders
> `publication.display`; re-deriving it from `publishCleared` is the local verdict D32.3
> forbids. Fail-closed on both axes: an unresolvable posture is not clearance, and an
> unrecognised `DAP_AUDIENCE` resolves to `public`.
>
> ⚠ **The stamp check covers `rcr` on a timer.** An `rcr` exceedance row's `observed` is the
> RCR value, whose numerator IS the DaP aggregate, and those rows carry an inherited
> `coverage_version`. A hard-coded series list would begin leaking withheld RCR values the
> day `RCR_EXCEEDANCE_BANDS` is fitted (2026-09-28) — no code change, no failing test.

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/exceedances?series=spread_bps&entityKey=USDC&hours=168"
curl "https://corridorscout.com/corridor-scout/api/exceedances?series=settlement_seconds&direction=above&limit=1000"
```

Errors: `400 VALIDATION_ERROR` (unknown `series`/`direction`, over-long `entityKey`);
`500 INTERNAL_ERROR`.

### GET /api/stablecoins/:asset/liquidity

The **Stablecoin Liquidity** read (Phase R-D) — one per-asset object composing everything
that surface renders. This was the last read endpoint R-D owed and the single code blocker
on the surface (`docs/UI-SPEC.md` "Build readiness").

Everything served is either a **frozen** row (`dap_snapshots`, `metric_snapshots`) or a raw
capture (`venue_depth_snapshots`, `spread_snapshots`, `threshold_exceedances`) plus the R4
read-time profile composition. **No figure is computed here.** The DaP roll-up and its
withholding rule were decided by `src/lib/dap-aggregate.ts` when the tick was frozen; the
ratios were decided by the R-M1 calculators. There is no composite score and none is coming
in Phase 0 (§6, decisions D9/D31).

**Path parameter**

| Param | Values |
|---|---|
| `asset` | one of `ASSESSED_ASSETS` — `USDT`, `USDC`, `DAI`, `PYUSD`, `USDe` |

Anything else is **404 `ASSET_NOT_FOUND`** — an identity error, not a data gap. An assessed
asset with nothing stored resolves **200** with every section typed as absent (see "404 IS
FOR IDENTITY, NEVER FOR DATA AVAILABILITY" above) — including `depth.unavailableReason:
"depth_no_capture"`, which is a DIFFERENT state from `depth_read_failed` (we looked and hold
nothing, versus we could not look) and from an empty band SELECTION (a display choice).

**Query parameters**

| Param | Values | Default | Notes |
|---|---|---|---|
| `window` | `24h` \| `7d` \| `30d` | `24h` | DECLARED, not free-form. Each window carries its own DaP bucket width (15 / 60 / 360 min). An undeclared value is `400 VALIDATION_ERROR` rather than a silent fall back to 24h. |

Cached 60s in Redis, keyed by **asset + window + audience**. A payload with any leg in
`read_failed` is **never** cached — pinning a read failure for a minute keeps serving it long
after the DB recovered.

#### Five legs, independently settled

`depth` · `metrics` · `spread` · `profile` · `exceedances` are awaited under
`Promise.allSettled`. One leg failing never discards another's observation, and
`coverage.legs` says which ones were actually read. Every section carries its own
`unavailableReason`, and **a failed leg is an empty array plus a named reason, never a `0`**.

```json
{
  "coverage": { "legs": { "depth": "ok", "metrics": "ok", "spread": "ok", "profile": "ok", "exceedances": "ok" } }
}
```

Reads are **sequential within a leg and parallel across legs**, which bounds — but does not
minimise — pool usage. The pg pool is `max: 10`; firing all **ten** underlying queries at once
would let a single dashboard request hold the whole pool while the capture crons contend for
connections (the AUDIT #34 shape).

⚠ **PEAK CONCURRENCY IS SEVEN, NOT FIVE, AND THE PROFILE LEG IS WHY.** Four legs issue one
query at a time (depth 3 sequential, metrics 2 sequential, spread 1, exceedances 1), but the
profile leg calls `loadIssuerProfile`, which fires **three** queries under its own
`Promise.all` (`src/lib/issuer-profile-reads.ts`). So the worst case is 4 + 3 = 7 in flight.
Stated as a measured number rather than the intended one: an earlier draft of this section
claimed "nine underlying queries" and "five in flight", and both were wrong.

#### `depth` — the frozen DaP roll-up, ladder and history

```json
{
  "depth": {
    "coverageVersion": "v2",
    "coverageBasis": "observed_tick",
    "declaredVenues": ["bitstamp", "coinbase", "kraken"],
    "bands": [
      { "bandBps": 10, "recordedAt": "2026-08-28T11:55:00.000Z", "dapUsd": 4821330.12,
        "subtotals": { "usd_direct": 3910220.00, "usdt_relative": 911110.12 },
        "coverageVersion": "v2", "coverageBasis": "observed_tick",
        "withheldReason": null, "memberCount": 3 }
    ],
    "ladder": [
      { "venue": "kraken", "venueClass": "cex", "pair": "USDC/USD", "quoteClass": "usd_direct",
        "bandBps": 10, "bidDepthUsd": 811200.5, "askDepthUsd": 902110.0, "dapUsd": 1713310.5,
        "levelsObserved": 64, "method": "orderbook_l2", "unavailableReason": null,
        "recordedAt": "2026-08-28T11:55:00.000Z" }
    ],
    "history": {
      "window": "24h", "bucketMinutes": 15, "tickCount": 864, "truncated": false,
      "buckets": [
        { "bandBps": 10, "bucketStart": "2026-08-28T11:45:00.000Z",
          "minUsd": 4610000.00, "maxUsd": 4930000.00, "lastUsd": 4821330.12,
          "ticks": 3, "withheldTicks": 0, "coverageVersions": ["v2"] }
      ]
    },
    "publication": { "...": "see below" },
    "unavailableReason": null
  }
}
```

⚠ **`history.minUsd` IS FIRST-CLASS AND IS NOT DERIVABLE FROM THE OTHERS.** `dap_usd` is a
low-side-bad series (`EXCEEDANCE_SIDEDNESS`), so the trough is the event. A bucket summarised
by a mean or a last-value would hide it, **and would do so in the flattering direction**. A
withheld tick counts into `withheldTicks` and contributes to nothing else — folding a typed
refusal in as `0` would fabricate the deepest possible thin-depth reading out of "we could not
look". A bucket in which every tick was withheld still emits, with null min/max/last: a
dropped bucket is indistinguishable from a dead producer.

⚠ **`coverageVersions` on a bucket is a list.** More than one entry means the bucket
**straddles a coverage boundary**, and its level shift is composition, not market — the
v1→v2 boundary of 2026-08-18 is exactly this (§18.7).

⚠ **`truncated: true`** means the row ceiling (`MAX_DAP_HISTORY_ROWS` = 40,000) was reached and
the oldest part of the window is not represented. Served rather than logged: a truncated chart
that does not say so reads as a complete one.

⚠ **`declaredVenues` is the venues THIS ASSET'S composition names — not the registry's venue
set.** PYUSD and USDe are single-venue (Kraken) after v2; drawing a venue axis from the full
registry would put an empty Bitstamp column beside them, which a reader parses as a zero
reading rather than as coverage that was never claimed.

`bands[].dapUsd` is `null` exactly when `withheldReason` is set (`coverage_unresolved` |
`composition_mismatch` | `member_unavailable`) — **never a partial sum**. A ladder row's
`dapUsd` is `null` if either side is absent — never a one-sided total. A genuine `0` is a
measurement (an empty market), not an absence.

#### `depth.publication` — the D19 gate, and it binds RCR too

```json
{
  "publication": {
    "publishCleared": false,
    "posture": "collect_and_compute",
    "blockingVenues": ["bitstamp", "coinbase", "kraken"],
    "unrecordedVenues": [],
    "resolved": true,
    "audience": "internal",
    "display": "render",
    "withheldReason": null
  }
}
```

**Posture** is a property of the data and is resolved from the **frozen row's own
`coverage_version`**, never from the live registry — a v1-stamped row must be judged against
the venues that actually contributed to it, and every pre-2026-08-18 production row is that
case. All three v2 venues block: Bitstamp is `license_pending`, and *pending is not granted*.

**Audience** is configuration (`DAP_AUDIENCE`, default `internal`). The two axes meet in
exactly one place, `src/lib/publication-display.ts` (PO ruling D32.3):

| audience | posture | `display` |
|---|---|---|
| `internal` | `collect_and_compute` | `render` — with the posture stated on the panel |
| `internal` | `publish_cleared` | `render` |
| `public` | `collect_and_compute` | **`withhold`** |
| `public` | `publish_cleared` | `render` |

⚠ **A consumer must never re-derive this from `publishCleared`.** That is the local verdict
D32.3 forbids; render `display`.

⚠ **`withhold` MEANS THE FIGURES ARE NOT SERIALIZED.** `bands` and `ladder` become `[]`,
`history` becomes `null`, and `unavailableReason` reads `publication_not_cleared`. A number
withheld in the DOM is a number published.

⚠ **AND THE WITHHOLD REACHES RCR.** D19 gates "any `dap_usd`-derived figure", and **RCR's
numerator IS the DaP aggregate** (§B.6.2) — which is why an `rcr` row carries an inherited
`coverage_version` at all (§18.7 binds RCR one level up). A gated metric serves `value: null`
with `unavailableReason: "publication_not_cleared"`, and its **history points are typed the
same way rather than dropped** — deleting them would make a withheld series byte-identical to
one that was never computed. NIV,
its gross-redemption companion and ARC are token-unit and attested-reserve constructions,
carry no stamp, and are **not** gated. The rule is read off the row, so a future DaP-derived
metric inherits the gate by inheriting the stamp.

**`resolved: false`** means the posture itself could not be established — an unknown stamp, no
stamped rows, or bands disagreeing about their version. That is **not clearance**: it
withholds for a public audience exactly as a blocked posture would.

#### `metrics` — RCR, NIV, its companion, and ARC

```json
{
  "metrics": {
    "latest": [
      { "metric": "rcr", "recordedAt": "2026-08-28T11:10:00.000Z", "value": 4.21,
        "unavailableReason": null, "coverageVersion": "v2",
        "valuationBasis": "spread_snapshot_reprice", "supplyBasis": null,
        "arcNumeratorBasis": null, "unclassifiedShare": 0.03, "unprovenShare": null,
        "attestationAsOf": null },
      { "metric": "arc", "recordedAt": "2026-08-28T11:10:00.000Z", "value": null,
        "unavailableReason": "supply_scope_incomplete",
        "arcNumeratorBasis": "statutory_liquid_v1", "attestationAsOf": null, "...": "..." }
    ],
    "history": [ { "metric": "niv_7d", "recordedAt": "...", "value": -0.0042,
                   "unavailableReason": null, "coverageVersion": null } ],
    "unavailableReason": null
  }
}
```

Metrics are emitted in declared order (`rcr`, `niv_7d`, `gross_redemption_rate_7d`, `arc`).
History is hourly and **not** bucketed — hourly is the producer's cadence.

⚠ **A row with an `unavailableReason` is a RESULT, not a miss, and is served as content.**
Three states this surface will show constantly, all correct:

| state | what it means |
|---|---|
| `supply_scope_incomplete` | **Every `arc` row reads this** (ruling D26). An all-chains attested numerator over Ethereum-only supply inflates the ratio (≈198% for USDT — ≈175B attested ÷ a measured 88.31B Ethereum `totalSupply()`, 2026-08-25) *in the flattering direction*, so the construction is **refused, not caveated**. Render it as a typed refusal with its reason — never blank, never a number, never "coming soon". It clears when per-chain `totalSupply()` reads land, and ARC's history back-computes. |
| `attestation_missing` | Permanent and correct for `sky/DAI` and `ethena/USDe`, who publish nothing of this shape. There is deliberately no `not_applicable`. |
| `issuer_flows_unavailable` | PYUSD/USDe `rcr` — a named absence, not a gap. |

⚠ **RCR's three honesty dimensions are SERVED, not merely stored** (DATA-MODEL §24.1):
`unclassifiedShare` (how much of the denominator is NOT PROVEN), `valuationBasis`
(`event_amount_usd` vs `spread_snapshot_reprice` — one basis per window, never a mix), and the
inherited `coverageVersion`. ARC carries the parallel `unprovenShare` (eligible reserve
excluded from the numerator as not-proven-liquid) and `attestationAsOf` as a **calendar date** —
staleness is measured from the document's own as-of date and is **displayed, never a refusal**.

#### `spread` — three distinct absences

```json
{ "spread": { "polled": false, "note": "ASSESSED_ASSETS coverage; no deep canonical …",
              "latest": null, "unavailableReason": "spread_reference_unpolled" } }
```

| `unavailableReason` | meaning |
|---|---|
| `null` | a reading is present (its `spreadBps` may still be `null`) |
| `spread_no_readings` | polled, nothing captured yet |
| `spread_reference_unpolled` | **the 3-vs-5 seam.** `PEG_REFERENCES` polls USDC/USDT/DAI only; PYUSD and USDe are registered **UNPOLLED placeholders** with a recorded reason (PO decision 2026-07-08), served verbatim in `note`. A deliberate decision, not a capture failure. |
| `spread_read_failed` | the leg itself did not read |

**Never render the gap as `0` or as a peg.**

#### `profile` — the R4 read-time composition

Served whole, including every `classification_missing` slot and every `attestation_missing`
lineage entry. `assetSubjectHeld` says whether a document is held for **this asset's** subject
(rows are keyed `(issuer, subject)` — one issuer publishes a separate report per token, D21).

⚠ **`classification_missing` (nobody has looked) is NOT the taxonomy's `unknown` (an analyst
read the document and it does not establish the fact).** This endpoint keeps them distinct and
a consumer must too (D22). `issuer_unregistered` names an assessed asset that maps to no
registered issuer — a registry gap, not a read failure.

#### `exceedances` — rows plus per-series state

```json
{
  "exceedances": {
    "series": [
      { "series": "dap_usd", "fitted": true, "state": "logged", "count": 2 },
      { "series": "rcr", "fitted": false, "state": "awaiting_fit", "count": 0 },
      { "series": "niv_7d", "fitted": true, "state": "logged", "count": 0 },
      // for DAI/PYUSD/USDe/USDT this same series serves instead:
      // { "series": "niv_7d", "fitted": true, "state": "band_refused", "count": 0,
      //   "refusal": { "reason": "unfittable_degenerate_distribution",
      //                "reopenTrigger": "counterparty_map_verified_for_issuer_treasury_paths" } },
      { "series": "spread_bps", "fitted": true, "state": "logged", "count": 0 }
    ],
    "rows": [ { "id": "9", "series": "dap_usd", "entityKey": "USDC:10bps",
                "threshold": 1000000, "observed": 800000, "exceedanceMag": 200000,
                "direction": "below", "observationKey": "…", "coverageVersion": "v1",
                "recordedAt": "…" } ],
    "unavailableReason": null
  }
}
```

⚠ **`state` is why this section is not just rows.** An empty list means four different things,
and the rows alone cannot tell them apart:

| `state` | an empty list means | `count` |
|---|---|---|
| `logged` | nothing crossed a band that IS fitted and IS captured for this asset | a number |
| `awaiting_fit` | **nothing is being evaluated** — no D5 band exists yet (**`rcr` only**, 2026-09-28; `niv_7d` was fitted 2026-09-01) | a number |
| `band_refused` | **nothing is being evaluated FOR THIS ASSET, and no date will change it** — the series is fitted for other assets and this one's band was refused with a stated reason and a reopen TRIGGER (`niv_7d` for DAI/PYUSD/USDe/USDT since 2026-09-01). Carries `refusal: { reason, reopenTrigger }`. ⚠ Distinct from `awaiting_fit`, which promises a date, and from `logged`, which asserts a measurement nobody made. Added 2026-09-01 when a series first became fitted for SOME of its assets | a number, or `awaiting_fit` |
| `not_captured` | a band exists, but this ASSET produces no observation — `spread_bps` for PYUSD/USDe, whose references are deliberately unpolled | a number |
| `withheld` | **unknown** — the series is DaP-derived and the D19 posture removed its rows | **`null`** |

`fitted` is derived from the band tables (`isExceedanceSeriesFitted`), never hand-kept, so
pasting the first fitted band flips it with no edit here.

⚠ **`dap_usd` ROWS ARE REMOVED UNDER A WITHHOLD, NOT REDACTED.** A `dap_usd` row's `observed`
**is** the Σ-over-venues aggregate in USD and its `threshold` is the fitted USD depth floor —
so serving the row with nulled numbers would still disclose that depth crossed its floor,
which is itself a statement about the gated quantity, and serving `count: 0` would assert that
it did not. Hence `state: "withheld"` with `count: null`. (This was a real leak, found by
adversarial review before commit — AUDIT #43 / D33.4.)

Both entity-key shapes are queried: the bare asset (`rcr`, `niv_7d`, `spread_bps`) and
`${asset}:${band}bps` (`dap_usd`). Rows are capped at 500, newest first.

#### Example

```bash
curl "https://corridorscout.com/corridor-scout/api/stablecoins/USDC/liquidity"
curl "https://corridorscout.com/corridor-scout/api/stablecoins/USDT/liquidity?window=30d"
```

Errors: `400 VALIDATION_ERROR` (undeclared `window`); `404 ASSET_NOT_FOUND` (asset outside
`ASSESSED_ASSETS`); `500 INTERNAL_ERROR`.

---

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Invalid request parameters — includes an unknown `:bridge` on the bridge-health endpoint (a name that is not a bridge is an identity error, not a data gap) |
| `NOT_FOUND` | 404 | Resource not found |
| `RATE_LIMITED` | 429 | Too many requests (planned) |
| `INTERNAL_ERROR` | 500 | Server error |
| `VERSION_CONFLICT` | 409 | Concurrent append to a structural-fact `(entity, factor)` claimed the version — retry (structural-facts POST) |
| `ISSUER_NOT_FOUND` | 404 | Unknown issuer slug (issuer-profile endpoint, Phase R4) — the message names the registered set |
| `ASSET_NOT_FOUND` | 404 | Asset outside `ASSESSED_ASSETS` (stablecoin-liquidity endpoint, Phase R-D) — the message names the assessed set. ⚠ Never returned for an assessed asset with no stored rows, which resolves 200 with typed absences |
| `POOL_SNAPSHOT_UNAVAILABLE` | 503 | HubPool/pool liquidity snapshot missing, stale, or present-but-unpriced (impact endpoint) |
| `GAS_UNAVAILABLE` | 503 | Gas snapshot or native-token USD price missing/stale for a required chain — gas is never guessed (impact endpoint, Phase 2a) |

> Ingestion routes (`POST /api/structural-facts`, future R3 attestations) also return
> a bare `401 { "error": "Unauthorized" }` / `500 { "error": "Endpoint not configured" }`
> from the shared ingestion-auth guard — distinct from the structured error envelope above.

---

## TypeScript SDK (Future)

```typescript
import { CorridorScout } from '@corridorscout/sdk';

const client = new CorridorScout({
  apiKey: 'optional-for-higher-limits'
});

// Get system health
const health = await client.getHealth();

// Get all corridors
const corridors = await client.getCorridors({
  bridge: 'across',
  status: 'healthy'
});

// Calculate impact
const impact = await client.estimateImpact({
  bridge: 'across',
  source: 'ethereum',
  dest: 'arbitrum',
  amountUsd: 5000000
});

// Subscribe to real-time updates
client.subscribe('anomalies', (anomaly) => {
  console.log('New anomaly:', anomaly);
});
```

---

## Webhooks (Future)

```typescript
// POST to your endpoint
{
  "event": "anomaly.created",
  "timestamp": "2026-02-21T14:20:00Z",
  "data": {
    "anomalyId": "anom_123",
    "type": "latency_spike",
    "corridorId": "stargate_ethereum_avalanche",
    "severity": "high"
  }
}
```
---

## Changelog

### 2026-08-28 — Phase R-D: `GET /api/stablecoins/:asset/liquidity`

**ADDED**, no breaking change to any existing endpoint. The last read endpoint R-D owed and
the single code blocker on the Stablecoin Liquidity surface. Serves five independently-settled
legs from frozen rows + the R4 read-time composition; computes nothing.

Five accumulated PO riders land here and are all served, not merely stored:
`valuationBasis`, `unclassifiedShare`, the inherited `coverageVersion` (§24.1), the D19
`publication` posture, and ARC's `supply_scope_incomplete` **as content** (D26).

Two rulings taken while building it:
- **DaP history is bucketed min/max/last**, never a mean or a last-value. `dap_usd` is
  low-side-bad, so a naive downsample hides the trough *in the flattering direction*.
  `minUsd` is first-class and a withheld tick is never folded in as `0`.
- **`display` = audience × posture, decided once** in `src/lib/publication-display.ts`
  (D32.3). `DAP_AUDIENCE` (default `internal`) is the second axis; `withhold` means the
  figures are not serialized, and **the withhold reaches RCR** because RCR's numerator is
  the DaP aggregate.

New error code: `ASSET_NOT_FOUND` (404, identity only — never for absent data).

### 2026-08-28 — Phase D1 + the `/api/flight` cutover

**Removed:** `GET /api/flight` (decision D8 — hard cutover, no compat shim; no
external consumers pre-public). The route, `FlightVelocity.tsx` and the route's test
suite are deleted, not deprecated. Field-by-field migration table under the struck
heading above.

**Added:**
- `GET /api/flow/chains` — flow leg + settlement leg + §9B composite status.
- `GET /api/bridges/:bridge/health` — one bridge's BSH, grouped by chain.
- `GET /api/corridors/confidence` — ranked corridors, worst-first.

**Two shape hazards for a consumer migrating off `/api/flight`:**
1. **`flowRatio` is now nullable.** The new route serves the union of both legs, so
   a chain observed only by BSH has no flow reading. `null` = not measured; `0`
   would assert a balanced chain.
2. **`alert` is gone.** It flagged the flow leg alone. Under §9B a published
   `flight` requires BOTH a flow signal and a pool-pressure signal, so the old flag
   would fire on outflows the composite declines to escalate. Read
   `compositeStatus === "flight"`.

**No `confidenceScore` anywhere**, on this or any endpoint — decision D9 and
PHASE-0-SPEC-V2_4 §6 defer the weighting math and forbid composite scores in Phase
0. `/api/corridors/confidence` serves a rule-based `recommendation` ladder instead.

### 2026-08-27 — ⚠ `pool.utilization` CHANGES MEANING (breaking for readers, not for parsers)

**The field's name is unchanged and its type widens to `number | null`. Its SEMANTICS
change, which no client can detect from the payload — hence this entry.**

Affects `GET /api/corridors`, `GET /api/corridors/:id`, and `GET /api/impact/estimate`.

| | before | after |
|---|---|---|
| meaning | TVL-weighted **MEAN** across the corridor's stablecoin pools | **MAX** across the corridor's pooled assets |
| absence | `0` | `null` |
| asset scope | `STABLECOINS` (USDC, USDT, DAI) | `POOLED_ASSETS` (adds WETH) |

**Why MAX.** `pool.utilization` sits beside `pool.fragility`, and fragility now judges
**exhaustion per asset** (`POOL_EXHAUSTION_UTILIZATION_PCT = 90`, AUDIT #39 / D30.2). A mean
reported next to a max-based verdict lets a reader see `utilization: 40` beside
`fragility: "high"` and conclude the service is broken. The served number is the one the
decision was actually made on, and `null` is reported when no reading was established.

**⚠ It also unifies three routes that had silently diverged.** For one day,
`/api/impact/estimate` served the mean under this name while its two siblings served the
max — one documented field, two meanings, over the same rows. One meaning now, everywhere
it appears.

**`null` is absence, not zero.** A stale HubPool snapshot, a drained/corrupt TVL, or a
non-finite input yields `null`: no reading was established. It previously yielded `0`,
making a drained pool and an unevaluated one byte-identical. **Clients must render absence
(`—`), never `0%`.**

**Migration.** Parsers need `number | null` handling. Anything comparing this field against
a threshold should be re-examined: the retired gradated boundaries (60 = high, 30 = medium)
no longer exist, and applying them to a max produces false amber on ordinary readings —
USDC's median is 32.6, so a `> 30` rule would have fired on the majority of ticks beside a
`low` badge. Fragility level is the correct field to branch on.


---

## R6.1 — the recomputability envelope (`?includeInputs=true`)

`dap_snapshots.inputs` and `metric_snapshots.inputs` are NOT NULL columns whose stated
purpose is that *"every computed row stores the inputs' row-id ranges or hashes so any
figure is recomputable"*. Until R6.1 **no endpoint serialized any of it** — so *"show me
how you got this"*, the regulated buyer's first question (Blockford §B.6), was answerable from
the database and unanswerable over HTTP.

`GET /api/stablecoins/:asset/liquidity?includeInputs=true` attaches the envelope to each
frozen row in `depth.bands[]` and `metrics.latest[]`: the contributing row-id ranges
(`sources`), the concrete summed `values`, the named missing/undeclared/unobserved members,
and the **provisional `params` in force when the row was frozen** — never today's
constants, the same guarantee `threshold_exceedances` gets by storing its own threshold.

Strictly additive and default-off: on a normal request the keys do not appear and the JSONB
is not even read. The Redis key gained an `inputs`/`noinputs` segment. An uncoercible value
is a `400`, never a silent `false`.

⚠ **Only the LATEST frozen rows carry one.** A history bucket summarises many rows (no
single envelope) and a 30-day metric history runs to 720 points per metric.

⚠⚠ **THE D19 GATE REACHES THE ENVELOPE MORE SHARPLY THAN THE HEADLINE FIGURES.**
`inputs.members[].dapUsd` is *every contributing venue's* depth figure, and an `rcr`
envelope's `values.dapUsd` **is** the gated aggregate one division up. Both ride the same
decision: under a withhold the depth envelope is unreachable (bands are `[]`) and a
DaP-derived metric serves `inputsUnavailableReason: "publication_not_cleared"` with **no
`inputs` key at all** — absent, not nulled. `inputs_unparseable` is served rather than a
partial: an envelope exists to be recomputed *from*, which makes a plausible-looking
partial strictly worse than nothing. Lists cap at 50 entries with a `truncated` flag.

---

## ⚠ 2026-09-02 — `GET /api/depth` now APPLIES the publication gate

Previously it **reported** the posture in `coverage.publication` and then served the
figures that posture withholds. It was safe only by accident — `DAP_AUDIENCE` defaults to
`internal` — but the public flip is deliberately a **config change with no code change**
(D32.3), so on the day it happened there would have been no diff to review, and this
endpoint would have published the full aggregate and its per-venue decomposition while
`/api/stablecoins/:asset/liquidity` withheld the same numbers. One surface publishing what
another refuses is the exact failure `exceedance-publication.ts` was extracted to close,
one endpoint over. Found by adversarial review of R6.1.

`coverage.publication` now carries `audience` / `display` / `withheldReason` beside the
posture, in the **same shape the liquidity route serves**, so a consumer reads one decision
from either endpoint and never re-derives it from `publishCleared`. Under a withhold the
per-row depth figures (`dapUsd`, `bidDepthUsd`, `askDepthUsd`, `levelsObserved`) are
**omitted, not nulled** — the row keeps its identity, timestamp and `unavailableReason`, and
loses only what it held — and `aggregates` is `[]`.


## `depth.bands[].vsBaseline` — column 1's regime delta (D40, 2026-09-03)

Each band carries the comparison between its realized crossing rate on the requested window
and the rate its band was fitted to produce.

```typescript
type VsBaseline =
  | { kind: 'compared'; realizedRate: number; targetRate: number;
      state: 'in_regime' | 'below_regime' | 'above_regime';
      crossings: number; evaluated: number;
      baselineWindow: string;   // "2026-08-18 → 2026-09-01" — ALWAYS stated
      threshold: number; label: string }
  | { kind: 'not_comparable';
      reason: 'no_fit_recorded' | 'band_refused'
            | 'fit_predates_regime_comparison' | 'nothing_evaluated_in_window'
            // ⚠ READ FAILURES, and NOT the same as `no_fit_recorded`.
            | 'baseline_read_failed' | 'crossings_read_failed';
      label: string };
```

⚠ **RENDER `label`; NEVER RE-DERIVE THE COMPARISON.** The target rate and the tolerance come
from the STORED fit, so a consumer computing its own would reinterpret an old fit under
today's constants — the thing `band_fits.regime_lower_mult` / `regime_upper_mult` exist to
prevent.

⚠ **`crossings` COMES FROM AN UNCAPPED COUNT, NOT FROM `exceedances[]`.** The exceedance log
served on this response is capped at 500 rows; a consumer computing its own rate from those
rows reproduces the population defect that inverted the verdict on 7d/30d windows (DATA-MODEL
§18.9). This is one more reason `vsBaseline` is rendered, never re-derived.

⚠ **THE COMPARISON IS SCOPED TO ONE COVERAGE VERSION.** `evaluated` counts only ticks stamped
with the fit's own version; a bucket straddling a §18.7 seam is excluded from both legs.

⚠ **`not_comparable` IS CONTENT, NOT AN ERROR.** `band_refused` names the reopen TRIGGER
(never a date); `fit_predates_regime_comparison` marks a fit whose tolerance was never
recorded; `nothing_evaluated_in_window` is NOT a 0% rate — 0/0 means nothing was looked at.

⚠ **`coverage.legs` GAINED A SIXTH MEMBER, `fits`.** The fit record is read as its own
allSettled leg so a failed BASELINE read degrades the DELTA alone — the depth figure it was
going to be compared against must not disappear with it. A consumer pinning the legs object
shape should expect six.

**Why:** AUDIT #53 / D40. It replaces the `exceeded` observation rung, which fired on any
crossing and was therefore true for every asset always.


## `depth.venueHistory` — the per-venue depth series (D40, 2026-09-03)

The raw per-venue books over the requested window, bucketed. This is what the hero chart on
the Stablecoin Liquidity surface plots.

```typescript
interface DapVenueHistory {
  window: '24h' | '7d' | '30d';
  bucketMinutes: number;
  declaredVenues: string[];   // from THIS ASSET'S coverage composition, not the registry
  readingCount: number;
  truncated: boolean;
  buckets: Array<{
    venue: string; pair: string; bandBps: number;
    bucketStart: string;      // ISO
    minUsd: number | null;    // ⚠ THE MINIMUM IS THE SERIES — dap_usd is low-side-bad
    maxUsd: number | null;
    readings: number;
    unavailableReadings: number;   // read, reported nothing usable
  }>;
}
```

⚠ **THESE DO NOT SUM TO `depth.bands[].dapUsd`, AND A CONSUMER MUST NOT STACK THEM.** The
band figure is the FROZEN roll-up, which withholds a total whenever a member is missing;
these are the raw books, which still have rows when the aggregate refused. The two are not
tick-correlated. A stacked total would silently contradict the headline beside it.

⚠ **`venueHistoryUnavailableReason: 'venue_history_read_failed' | null` IS A SEPARATE
ABSENCE.** This is the heaviest query the route issues, so it is caught locally rather than
rejecting the depth leg: `venueHistory` can be `null` while `unavailableReason` is `null` and
every band is present and correct. As a bare `await` its rejection discarded bands, ladder and
history too — a chart outage costing the headline figure it sits above.

⚠ **`null` UNDER A WITHHOLD, AND IT IS SERIALIZED AFTER THE GATE.** A venue's own order book
is the sharpest form of the D19-gated quantity — precisely what Coinbase's and Kraken's
terms bar republishing — so it is unreachable exactly when `bands` is. Pinned by the same
route test that scans the payload for the withheld figures.

⚠ **`truncated` IS NOT DECORATIVE.** USDT/USDC carry 3 venues x 3 bands x 8,640 ticks =
77,760 rows on a 30-day window against a 40,000-row cap, so a 30d venue read is ALWAYS cut.
A consumer that drops the flag renders a window starting ~15 days late while labelling it a
month.

⚠ **A DECLARED VENUE THAT REPORTED NOTHING STAYS IN `declaredVenues` WITH NO BUCKETS.**
Dropping it would read as "not part of this asset's picture" rather than "part of it, and
silent" — the enumerate-from-the-registry rule applied to a venue axis.


## `depth.bands[].operatingRange` — the fit-window reference statistic (pass D, 2026-09-03)

Where the series RUNS on the requested window against where it ran over the window its
floor was cut on:

```typescript
operatingRange: {
  currentMedian: number | null;    // median dap_usd over the DISPLAY window
  baselineMedian: number | null;   // median dap_usd over the FIT window (from band_fits)
  currentN: number;                // ticks under each median — stated, so a thin window
  baselineN: number;               //   cannot masquerade as a full one
} | null;
```

⚠ **BOTH LEGS ARE THE SAME STATISTIC (median) over two NAMED windows.** Comparing the
display window's *minimum* against the fit window's *median* would report a decline on a
window where nothing changed — a trough always sits under its own median — so the headline
would be non-zero by construction. Median vs median is definitionally equal when the
distribution has not moved.

⚠ **NULL when there is no comparable fit or the baseline read failed** — caught locally, so
a slow median query can only cost the enrichment, never the figure it enriches. This is the
served, authoritative form of the "reference depth" framing ("fit-window median $X →
current $Y"); a consumer must render it, never recompute a reference from its own history
slice (a different read is a different population).


## `finding` — the Scout's conclusion (D42/D43, 2026-09-04; AUDIT #55)

The deterministic conclusion the surface opens with, served as a first-class object so the
same conclusion reaches humans and machines from ONE derivation (`src/lib/findings/liquidity.ts`,
pure — the finding-first layer, PHASE-0-SPEC-V2_4 §5A).

```typescript
finding: {
  id: string;                 // content-addressed, e.g. "dai-dap50-below-range" — stable
                              // for the same condition; NOT a sequence number (no
                              // openedAt exists, and none may be inferred)
  kind: 'below_operating_range' | 'crossing_above_fitted_rate'
      | 'below_range_and_crossing' | 'within_operating_range' | 'not_concluded';
  severity: 'notable' | 'elevated' | 'none' | 'unknown';
  asset: string;
  bandBps: number;            // ⚠ the band the conclusion is cut at — headline, finding
                              // and hero chart all render THIS band and can never disagree
  headline: string;           // one deterministic sentence, leading with the dollar figure
  narrative: {                // the three questions, kept apart (D43)
    whatHappened: string;     //   a quantity, in dollars
    comparedWith: string | null;   //   a NAMED window; null when nothing compares
    whyItMatters: string;     //   consequence stated from measurements only
  };
  detail: string[];           // supporting clauses, each traceable to a stored value or
                              // a typed absence
  evidence: Array<{ label: string; detail: string }>;
  coverage: {                 // ⚠ EVIDENCE METADATA, NOT "CONFIDENCE" (D44.1) — counts
    observations: number;     // and names a reader weighs themselves; there is
    declaredVenues: number;   // deliberately NO epistemic grade in Phase 0 (D9/§6)
    coverageVersion: string | null;
    caveats: string[];        // named limits — rendered, never hidden. Always: the
                              // worst-observed-leg rule + "flow is context only"; then, as
                              // applicable: initiations-only, structurally unmeasurable assets,
                              // an unavailable reading, and the settlement-absent consequence
                              // ("…the route tier therefore rests on observed transfer health
                              // alone." / "Neither route signal is currently observable…")
  };
}
```

⚠ **THE PROSE IS A PRESENTATION PROJECTION OF THE STRUCTURED FIELDS (D62, 2026-09-12).** Every
string above is composed from `recommendation`, `recommendationReason`, `settlement`, `observed`
and `destinationChainFlow` on the same row and adds nothing to them; the machine layer —
`kind`, `recommendation`, `recommendationReason`, `corroboration`, `binding.leg`, the
levels, scores, counts, typed absences and reason tokens — is unchanged by the copy pass. A
consumer that needs the token reads the field; the prose no longer carries `bsh_pressure`,
`completionObservableReason` or `lfv_read_failed` as words.

### `findings[]` — the same conclusion at every declared band (FF-1.8 / D44.5, 2026-09-04)

```typescript
findings: FindingWire[];      // one entry per band in DAP_BANDS_BPS (10, 25, 50), each
                              // composed by the SAME derivation and cut at its own band
```

`finding` (singular) remains the **widest** band — the broadest measure of exit capacity we
hold, and the right default for a consumer that does not choose. `findings[]` exists because
D44.5 rules that the band selector drives the finding, the headline and the hero chart
TOGETHER: the client **selects** the entry whose `bandBps` matches the band it is showing,
and never re-cuts a conclusion locally. `finding` is byte-identical to the widest entry.

⚠ **THE BANDS ARE NESTED, NOT DISJOINT.** ±25 bps contains everything inside ±10 bps
(`computeBandDepth` sums every level inside the half-band), so these are three nested
measures of one book. Their figures must never be summed or presented as a decomposition of
a total — the sum double-counts the core, in the flattering direction.

⚠ **EVERY ENTRY RIDES THE D19 GATE.** Each is composed from the already-gated `depth`
section, so under a withhold every band resolves to `not_concluded` with the posture's own
reason and no entry can leak a figure the section above it withheld.

⚠ **A BAND WITH NO READING STILL GETS AN ENTRY**, carrying `not_concluded` and a named
reason. Omitting it would make a client fall back to a DIFFERENT band's conclusion under
this band's label. For the same reason a refusal headline names its band.

⚠ **RENDER IT; DO NOT REASSEMBLE IT.** The sentences pair stored values with named windows;
a consumer composing its own from parts would eventually word one differently — two
surfaces stating one measurement as two claims.

⚠ **THE HEADLINE IS A DISPLAY CONVENIENCE, fully redundant with the structured fields** — a
machine never parses it. `severity` is a deterministic documented ladder over `kind`
(`within_operating_range` → `none`; below-range AND crossing-high → `elevated`; either
alone → `notable`; `not_concluded` → `unknown`) — it grades nothing an observation did not
establish, which is the only basis on which it is admitted (D42).

⚠ **NO CLAUSE RESTS ON A LEG WE DO NOT HOLD.** "Prices remain stable" is unsayable for the
two unpolled spread assets, and even where polled the reading is QUOTED ("Latest peg-spread
reading: −2.0 bps" — the LATEST point reading from `readSpreadLatest`, never a window
statistic; D58.1), never judged against a threshold nobody fitted (D43).

⚠ **THE PROSE IS READER-FACING AND ONE FACT PER LAYER (D58, 2026-09-11).** `headline` leads
with the subject and the dollars ("DAI market depth within ±50 bps of the peg is $113,000 — 56%
below its 2026-08-18 → 2026-09-01 baseline."); `narrative.whatHappened` is the measurement
("$113,000 of quoted market depth within ±50 bps of the peg."); `comparedWith` the comparison
("56% below the … baseline median of $258,000." — MEDIAN, because that is what `levelDrop`
divides the CURRENT reading by; the level is stated here once and never restated in `detail`);
`whyItMatters` the plain-English meaning plus the quoted peg reading ("Less quoted liquidity is
available near the peg than in the reference period. Latest peg-spread reading: −2.0 bps.");
`detail` the persistence evidence ("Depth was below its fitted floor in 100% of 288
observations. The floor was calibrated for a 10% breach rate."), preceded by a NAMED absence
line only when no median could be computed, and on a refused section the machine reason
verbatim (`Reason code: depth_read_failed`); `evidence[].label` is
`Depth vs. fitted floor` · `Floor breaches` · `Depth by venue`. A `not_concluded` headline
leads with the measurement or the unavailability ("… is $113,000. No baseline comparison is
available yet." / "Depth data for USDC within ±50 bps of the peg is currently unavailable."),
never with "No finding for…". Rates print without a trailing `.0` but keep a discriminating
decimal (`10.4%`); `vsBaseline.label` is unchanged. ⚠ **No sentence calls the figure an exit
quantity**: DaP is two-sided (bids within the lower band plus asks within the upper), so "what
an exit would meet" overstated it and was retired (D58.2). Machine consumers must key on
`kind`/`severity`/`coverage`, never on the prose — the prose is the display layer and was
rewritten without a wire change.

⚠ **NO FINDING IS PERSISTED** ("derived now, stored later") — this is a read-time
composition over `threshold_exceedances`, `band_fits` and the frozen `dap_snapshots`, the
same pattern as the R4 profile (D22). The other three Scout surfaces gained their own
`finding` per surface pass (D44.4) — Capital Flow and Bridge Health on 2026-09-08, Corridor
Confidence on 2026-09-09 (FF-4), so **all four surfaces now serve one** — and the shapes share
semantics, not necessarily fields (D44.1 — `FindingProjection` in PHASE-0-SPEC-V2_4 §5A is
the conceptual minimum).
