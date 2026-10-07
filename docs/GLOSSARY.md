# Glossary — Blockford Daily Review

Terms as the documents use them. Where a term belongs to the Blockford API, the vendored `API-SPEC.md` is the authority and the entry here says only what the build spec says. Entries marked *confirm* are to be checked against the API spec in build step 2.

## The product

| Term | Meaning |
|---|---|
| Daily review | The report this script writes once a day: what changed, what to watch, what the agent found that the UI does not show. |
| Run | One execution of the script: the eight steps of spec section 4. |
| Today | The 24 hours before the run's start time, UTC (question 4 ruling). |
| History | The 7 days before the run (`HISTORY_DAYS`). Several endpoints cap at 168 hours. |
| Window | The time span a figure belongs to. Named on every figure: `latest`, `1h`, `24h`, `7d`, or exact start and end. |
| Data pack | The raw responses from every endpoint in spec section 5, saved by date, never altered. |
| Failure record | A file saved in place of a response when a call failed: endpoint, status, error. |
| Manifest | One row per call in the pack: status, bytes, and the quality flags. |
| Derived stats | `derived.json`: the statistics code computes from the pack (spec section 6). |
| Report | `reports/YYYY-MM-DD.json` and its rendered `.md`. Eight sections (spec section 8). |
| Watch list | Items the next run should look at, carried from day to day in `state/watchlist.json`. |
| Follow-up | An earlier finding or watch item, marked in today's report as resolved, still open, or dropped. |
| Pre-action read | What the readings mean for an agent about to move stablecoins, by chain or corridor. Never an instruction to act. |
| Headline | The one thing that matters today. |

## Finding labels

| Label | Meaning |
|---|---|
| Observed | A value or change read directly from a field, with its source. |
| Pattern | Several observations that line up across time, chains, or assets. |
| Hypothesis | A possible cause or meaning. Always says what would confirm it. Causes appear only as hypotheses. |

## The agent

| Term | Meaning |
|---|---|
| Agent | Claude, running in the loop in `agent.py`, with the system prompt and two tools. |
| `api_get` | The tool that lets the agent GET an allowlisted path. Runs on Jason's machine. Capped by `MAX_TOOL_CALLS`. |
| Code execution | Anthropic's server-side tool. Runs model-written code in a sandbox with no internet, on the uploaded files only. |
| Sandbox | The container that code execution runs in. Keeps data for up to 30 days. |
| Files API | Anthropic's upload service. The script uploads the pack, references it with `container_upload` blocks, and deletes it at the end of the run. |
| Structured outputs | The Messages API feature that makes the final answer match a JSON schema (`output_config.format`). |
| Prompt caching | Reusing the unchanged prefix (tools and system prompt) across the requests of a run. |
| `pause_turn` | A stop reason meaning the server-side tool loop hit its limit; the script re-sends to continue. |
| Allowlist | The list of GET routes `api_get` may call, built from the API spec. The two POST routes are never in it. |
| Tool cap | `MAX_TOOL_CALLS`, the number of `api_get` calls allowed per run. |
| App findings | The `finding` objects the API returns on some surfaces. A starting point for the agent, never the answer. |

## The domain, as the build spec names it

| Term | Meaning per the build spec | Confirm |
|---|---|---|
| Blockford | The app whose API this script reads. Its API base path is `/corridor-scout/api`. | |
| Corridor | A route for moving a stablecoin between chains, with transfer counts, success rates, durations, and a confidence tier. | |
| Corridor tier | The confidence level the API assigns a corridor, carried in the `recommendation` field. A change in it is a tier change. | *confirm field* |
| Capital flow | The view served by `/flow/chains`, with its own findings. | |
| Flow history | `/flow/history`: status transitions over time. Write-on-change: a gap means the status held. Each row is an interval with `statusValidUntil`; each chain's newest row from before the window is served as `position: 'carry_in'`. Magnitudes hold only at the transition instant. Accepts integer `hours` 1 to 720 and `limit` 1 to 5000; out of range is 400. | |
| Bridge | A cross-chain transfer system. The spec names Across, CCTP, and Stargate. Stargate is recorded as not monitored. | |
| Bridge health | The view served by `/bridges/<name>/health`. | |
| Settlement health | The series served by `/bsh`, scored per bridge, chain, and asset. | *confirm what BSH stands for* |
| Peg, spread | How far a stablecoin's price sits from its target, served by `/spread`. The spec calls it "the peg". | |
| Depth | Liquidity available by venue and band, served by `/depth` and per asset by `/stablecoins/<asset>/liquidity`. | |
| Depth band | One of a nested set of ranges that depth is reported in. Nested means a wider band contains the narrower ones, so bands are never added together. | *confirm band names* |
| Venue | A place where depth is measured. Venue history is never stacked into a total. | |
| Issuer flows | Mint and burn events, served by `/issuer-flows`, totaled by asset, event type, and flow class. | *confirm field names* |
| Anomaly | An event the app detected, served by `/anomalies` with `detectedAt` and `resolvedAt`. The endpoint has no time window. | |
| Exceedance | A threshold crossing on a series, served by `/exceedances`, with per-series state. | |
| Attestation | A slow-moving record served by `/attestations`, used for staleness and change detection. | |
| Structural fact | A slow-moving record served by `/structural-facts`, used for change detection only. | |
| Finding | The deterministic conclusion a surface opens with: `id` (content-addressed, stable for the same condition), `kind`, `severity`, `headline`, `narrative`, `evidence`, `coverage`. Not persisted by the app; composed at read time. | |
| Surface | A view that carries a `finding`. The API spec names four: Capital Flow (`/flow/chains`), Bridge Health (`/bridges/:bridge/health`), Corridor Confidence (`/corridors/confidence`), Stablecoin Liquidity (`/stablecoins/:asset/liquidity`). | *confirm (question 7)* |
| Coverage leg | A part of a response's coverage report. A leg that is not `ok` is recorded as a data quality item. | |
| Truncated | A response flag meaning rows were cut. Always recorded. | |
| `total` versus rows | When a response says `total` is larger than the rows it returned. Always recorded. | |
| RCR | A figure the spec names as gated for publication later (decision 6). Meaning per the API spec. | *confirm* |
| Assets | The stablecoins pulled per asset: USDT, USDC, DAI, PYUSD, USDe. | |
| Impact estimate | `GET /impact/estimate` with `bridge`, `source`, `dest`, `amountUsd`: the observed cost to act for a potential transfer. Not in the pack; reachable through `api_get` only, once confirmed at step 4. | *confirm at step 4 (question 8)* |

## Words we use, and words we avoid

| Use | Avoid | Why |
|---|---|---|
| watch, measure | monitoring | Spec rule 13 |
| absent, missing | zero, none (for a null) | Spec rule 5 |
| token units | dollars (unless the field says USD) | Spec rule 6 |
| what the reading means | what to do | Decision 10 |
