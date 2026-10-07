# Product Requirements — Blockford Daily Review

**Version:** 0.1 (2026-10-07)
**Source:** [BUILD-SPEC.md](BUILD-SPEC.md) v0.1. Where this document and the spec differ, the spec wins and this document is corrected.
**Owner:** Jason, product owner and lead engineer.

This document restates the spec as numbered requirements so that the build plan, the tests, and code review can point at them. It adds nothing the spec does not say. Where it proposes, it says so.

## 1. Problem

The Blockford app shows the on-chain stablecoin landscape through views: capital flow, bridge health, corridors, anomalies, exceedances, settlement health, depth, peg, issuer flows. Reading those views well takes time every day. The UI shows the current state. It does not say what changed since yesterday, what the readings mean together, or what to watch next. Nobody writes that down.

## 2. Users

| User | Need |
|---|---|
| Jason | A daily review to read each morning: what changed, what to watch, what the data shows that the UI does not. |
| Future agents | A read of the landscape before they move stablecoins. The `preActionRead` section is the seed of that. |

v1 serves Jason. Decision 6: internal use only.

## 3. Goals

| ID | Goal |
|---|---|
| G1 | Each day, one report that says what changed, what to watch, and what the agent found beyond the UI. |
| G2 | Every claim in the report names its source: endpoint, field, timestamp. |
| G3 | The agent writes its own findings from the data. It does not repeat the API's `finding` text. |
| G4 | Safe by construction. Read-only. Claude never touches the network. Model-written code runs only in Anthropic's sandbox. |
| G5 | A first step toward agents that understand the landscape before they act. |

## 4. Non-goals for v1

From spec section 3 and section 12.

- AWS deployment, scheduling, email delivery, S3 archive.
- Database queries. The API is the only data source.
- Publication gating for depth and RCR figures.
- Any action taken by the agent. It reads and writes a report. Nothing else.
- Trade, position, or yield recommendations. Never, in any version.

## 5. Requirements

Each requirement cites its spec section. Status is `spec` (stated in the spec), `accepted (T-nn)` (added here and ruled by Jason, see [DECISIONS.md](DECISIONS.md)), or `proposed` (added here, awaiting a ruling, tracked in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)).

### 5.1 The run

| ID | Requirement | Spec | Status |
|---|---|---|---|
| R-RUN-1 | The script runs once a day, on demand, on Jason's machine. API calls go through the SSM port-forward. | §1, §2.4 | spec |
| R-RUN-2 | "Today" is the 24 hours before the run's start time, in UTC. History is 7 days (`HISTORY_DAYS`). | §5, Q4 ruling | spec |
| R-RUN-3 | A run performs the eight steps of spec section 4 in order: health, pull, derive, upload, agent, validate, render, save. | §4 | spec |
| R-RUN-4 | If `/health` cannot be reached the run stops with a clear error, exits non-zero, and writes no report. | §4.1, §11 | spec |
| R-RUN-5 | A run ends by saving `reports/YYYY-MM-DD.json` and `.md`, updating the watch list, and deleting the uploaded files. | §4.8 | spec |
| R-RUN-6 | The CLI offers `run`, `pull-only`, and `render`. | §9 | spec |
| R-RUN-7 | `run --date YYYY-MM-DD` reuses that date's saved data pack instead of pulling. Derive, agent, render and save proceed from it. | — | accepted (T-20) |
| R-RUN-8 | The health check logs the `/health` body's `status`, `corridorsMonitored` and `updatedAt`, so the log shows which deployment answered. | — | accepted (T-19) |

### 5.2 The data pack

| ID | Requirement | Spec | Status |
|---|---|---|---|
| R-PULL-1 | Every endpoint in the spec section 5 table is called, with the stated parameters. | §5 | spec |
| R-PULL-2 | Each raw response is saved to `data/YYYY-MM-DD/` exactly as received. Raw responses are never altered. | §4.2 | spec |
| R-PULL-3 | A failed call is saved as a failure record holding the status and the error. The run continues. | §5 | spec |
| R-PULL-4 | Every `truncated` flag, every `coverage` leg that is not `ok`, and every case where `total` exceeds the rows returned is recorded. | §5 | spec |
| R-PULL-5 | GET only. `/impact/estimate` is not in the pack; the agent may call it through its tool. | §2.3, §5 | spec |
| R-PULL-6 | `/flow/history` is called with `hours=168` and `limit=500`. The route accepts integer `hours` 1 to 720 and integer `limit` 1 to 5000; anything else returns 400. Carry-in rows are exempt from `limit`. When the response says `truncated: true`, the call is repeated with a larger `limit`, up to 5000, and both responses are kept in the pack. | §5, §13.3, Q3 ruling | spec |
| R-PULL-7 | `anomalies_all` is filtered in code by `detectedAt` and `resolvedAt`, since `/anomalies` has no time window. | §5, §7 rule 9 | spec |

### 5.3 Derived statistics

Code computes these. The agent does not. All from spec section 6.

| ID | Requirement | Status |
|---|---|---|
| R-DRV-1 | Finding comparison: every `finding.id` from the four surfaces (Capital Flow, Bridge Health, Corridor Confidence, Stablecoin Liquidity), compared with the previous run by id equality as new, gone, still open, plus changes in `kind` and `severity`. | spec, Q7 ruling |
| R-DRV-2 | Corridor tier changes: any corridor whose `recommendation` changed. | spec |
| R-DRV-3 | Anomalies: opened and resolved in the last 24 hours, and the count of open ones. | spec |
| R-DRV-4 | Exceedances: count by series for today, against the 7-day daily average. | spec |
| R-DRV-5 | Settlement health: per bridge, chain, and asset, today's minimum and median score against the 7-day values. | spec |
| R-DRV-6 | Depth: per asset and band, today's minimum against the 7-day median, judged against the thresholds the API serves. No hard-coded threshold. | spec |
| R-DRV-7 | Peg: today's minimum and maximum spread per asset. | spec |
| R-DRV-8 | Issuer flows: totals by asset, event type, and flow class. Never one gross sum. | spec |
| R-DRV-9 | Data quality: every failed call, truncation, and failed coverage leg. | spec |
| R-DRV-10 | On the first run the comparison says there is no previous run. It does not report everything as new. | spec |
| R-DRV-11 | A null in the source stays a null in the stats, with a note saying what is missing and why. It is never treated as zero. | spec (§7 rule 5) |
| R-DRV-12 | Depth bands are nested. They are never added together. Venue history is never stacked into a total. | spec (§7 rule 7) |
| R-DRV-13 | Flow history: per chain, the spec's `chains[]` state, the count of status transitions inside the window, the current status and when it was set. Carry-in rows are window-head state, never transitions. A gap is a held status. Magnitudes are never step-held or interpolated. | accepted (Q12) |

### 5.4 The agent

| ID | Requirement | Spec | Status |
|---|---|---|---|
| R-AGT-1 | The model is a setting. Default `claude-sonnet-5-5`. `claude-opus-5-5` is tried and the reports compared. | §7, §10 | spec |
| R-AGT-2 | The system prompt holds the agent's role, the rules of section 7, and the app's `API-SPEC.md` in full. | §7 | spec |
| R-AGT-3 | The message holds `derived.json`, the app's own findings, the last 7 report JSON files, and the current watch list. | §7 | spec |
| R-AGT-4 | The raw data pack is available as files in the code sandbox. Raw series never go in the message. | §7 | spec |
| R-AGT-5 | Tool `api_get`: GET only, path matched against an allowlist built from the API spec, POST routes never allowed, call cap `MAX_TOOL_CALLS` (default 15), result size cap with a plain-words notice when cut. It runs on Jason's machine. | §7 | spec |
| R-AGT-6 | Tool `code_execution`: Anthropic's code execution tool, no internet, reads the uploaded files only. Files attached through the Files API and `container_upload` blocks. | §7 | spec |
| R-AGT-7 | The loop handles a code execution result arriving in a later response, and the `pause_turn` stop reason. | §7 | spec |
| R-AGT-8 | The agent follows the fourteen rules of spec section 7. See [AGENT-DESIGN.md](AGENT-DESIGN.md) for how each is enforced. | §7 | spec |
| R-AGT-9 | Prompt caching is on for the system prompt. | §10 | spec |
| R-AGT-10 | The sandbox keeps data for up to 30 days. Accepted for v1 under decision 6. | §7 | spec |

### 5.5 The report

| ID | Requirement | Spec | Status |
|---|---|---|---|
| R-RPT-1 | The agent's final answer is JSON produced with structured outputs (`output_config.format`, type `json_schema`). | §8 | spec |
| R-RPT-2 | The schema respects the limits: every object has `additionalProperties: false`; no numeric or string-length constraints; at most 24 optional fields; at most 16 union-typed fields; no recursion. | §8 | spec |
| R-RPT-3 | The report has eight sections: headline, changes, findings, followUps, preActionRead, dataQuality, watchList, run. | §8 | spec |
| R-RPT-4 | Each finding has an id, a label (`observed`, `pattern`, `hypothesis`), a statement, evidence (endpoint, field, value, time), and what would confirm it. | §8 | spec |
| R-RPT-5 | Code renders the markdown from the JSON. The markdown adds nothing the JSON does not hold. | §4.7, §8 | spec |
| R-RPT-6 | The `run` section (date, model, tool calls used, token usage) is filled by code after the agent finishes, because only code knows the usage. | §8 | accepted (T-04) |

### 5.6 Failing loudly

| ID | Requirement | Spec | Status |
|---|---|---|---|
| R-FAIL-1 | API unreachable: stop, exit non-zero, no report. | §11 | spec |
| R-FAIL-2 | One endpoint fails: the report is still written. The failure appears in data quality, and in the headline if it hides a whole view. | §11 | spec |
| R-FAIL-3 | Claude call fails, or the JSON does not validate: keep the data pack, exit non-zero, no report. | §11 | spec |
| R-FAIL-4 | Tool-call cap reached: the agent is told. The report records it. | §11 | spec |
| R-FAIL-5 | No view is ever skipped silently. | §11 | spec |
| R-FAIL-6 | A `refusal` stop reason from the model is treated as a failed Claude call (R-FAIL-3). No automatic fallback to another model in v1. | — | accepted (T-08) |

### 5.7 Settings

| ID | Requirement | Spec | Status |
|---|---|---|---|
| R-CFG-1 | Settings: `ANTHROPIC_API_KEY`, `BLOCKFORD_API_BASE_URL`, `MODEL`, `MAX_TOOL_CALLS`, `MAX_OUTPUT_TOKENS`, `HISTORY_DAYS`. The key lives in `.env` and is never committed. | §10 | spec |
| R-CFG-2 | A missing or malformed setting stops the run before any API call, with a message naming the setting. | — | accepted (T-09) |

### 5.8 Non-functional

| ID | Requirement | Status |
|---|---|---|
| R-NF-1 | `data/`, `reports/`, and `state/` are gitignored. They hold depth figures. | spec (§9) |
| R-NF-2 | Code follows [ENGINEERING-PRINCIPLES.md](ENGINEERING-PRINCIPLES.md). One responsibility per module. Complexity under 10. | spec (principles) |
| R-NF-3 | Each build step ends with its check before the next starts. | spec (§12) |
| R-NF-4 | Tests never touch the network and never call the Claude API. Every I/O module has a fake. | accepted (T-21) |
| R-NF-5 | Documents are updated in the same change as the code they describe. | Jason's rule (CLAUDE.md) |

## 6. Success criteria

v1 is done when all of these hold.

1. The six build steps in [BUILD-PLAN.md](BUILD-PLAN.md) have passed their exit checks.
2. Seven consecutive daily reports have been read by hand, and in each one every claim can be traced to an endpoint, a field, and a timestamp.
3. No report contains an invented probability, score, or confidence grade.
4. A quiet day produces a short report.
5. Day two's report refers to day one's findings and watch items.
6. The first run says there was no previous run and reports nothing as new.
7. Logs and tests show zero non-GET requests, ever.
8. Every endpoint failure in that week appears in the report's data quality section.

## 7. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| API traps: nested depth bands, nulls, no window on `/anomalies`, change-only `/flow/history` | Wrong stats or wrong claims | Rules in the system prompt, the API spec in full, and derive tests on fixtures for each trap |
| Report schema hits the structured output limits | API rejects the schema | Schema limit test in `schema.py` tests; evidence values stored as strings |
| Context grows with seven reports plus the API spec | Cost, slower runs | Measure token usage from step 3; prompt caching; shrink past reports if needed, with Jason's ruling |
| Tool cap too low or too high | Shallow report, or runaway cost | `MAX_TOOL_CALLS` is a setting; the report records calls used |
| Code execution result arrives after an `api_get` call in the same turn | Loop mishandles the response | Explicit loop contract in [ARCHITECTURE.md](ARCHITECTURE.md); scripted fake responses in tests |
| Model refuses or hits `max_tokens` | No report | Fail loudly, keep the data pack, exit non-zero |
| `/flow/history` carry-in rows read as in-window transitions | Phantom changes on every run | `derive.py` keeps `position: 'carry_in'` rows as window-head state, never as transitions (R-DRV-13); a test covers it; the system prompt repeats rule 10 for the agent's own reads |

## 8. Open questions

Tracked in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md). Questions 1 to 12 were closed on 2026-10-07. New ones are added there before any code depends on them.

## 9. Traceability

| Spec section | Requirements |
|---|---|
| §2 Decisions | [DECISIONS.md](DECISIONS.md) D-01 to D-10 |
| §4 How one run works | R-RUN-3, R-RUN-4, R-RUN-5 |
| §5 The data pack | R-PULL-1 to R-PULL-7 |
| §6 Stats computed by code | R-DRV-1 to R-DRV-12 |
| §7 The agent | R-AGT-1 to R-AGT-10 |
| §8 The report | R-RPT-1 to R-RPT-6 |
| §9 Files and layout | R-RUN-6, R-NF-1 |
| §10 Settings | R-CFG-1, R-AGT-9 |
| §11 Failing loudly | R-FAIL-1 to R-FAIL-6 |
| §12 Build order | R-NF-3, [BUILD-PLAN.md](BUILD-PLAN.md) |
| §13 Open questions | [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) Q1 to Q5 |
