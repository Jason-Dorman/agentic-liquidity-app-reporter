# Blockford Daily Review — Build Spec

**Version:** 0.1 (2026-10-07)
**Status:** Draft for Jason's rulings. Hand to Claude Code once section 13 is answered.

---

## 1. What this is

A script that runs once a day. It pulls the last day of data from the Blockford app's API. An agent (Claude) studies it and writes a daily review. The review says what changed, what to watch, and what the agent found that the UI does not show.

It is for Jason's own reading. It is also the first step toward agents that understand the on-chain landscape before they act.

## 2. Decisions already made

| # | Decision |
|---|---|
| 1 | Own repo. Not built into the app repo. |
| 2 | Reads the app's API. Does not query the database in v1. |
| 3 | Read-only. GET requests only. Never calls a POST route. |
| 4 | Runs locally first. API calls go through the SSM port-forward (app RUNBOOK §2b). No infrastructure change. |
| 5 | The agent writes its own findings from the data. It does not just repeat the API's `finding` text. |
| 6 | Internal use only. No publication gating in v1. |
| 7 | Claude never touches the network. The script makes every API call. |
| 8 | Model-written code runs in Anthropic's sandbox, never on Jason's machine. |
| 9 | Output is a markdown file plus a JSON file, saved by date. |
| 10 | The agent describes what readings mean. It never recommends trades, positions, or yield. |

## 3. Not in v1

- AWS deployment, scheduling, email delivery, S3 archive (see section 12).
- Database queries.
- Publication gating for depth and RCR figures.
- Any action taken by the agent. It only reads and writes a report.

## 4. How one run works

1. **Check the API.** Call `/health`. If it cannot be reached, stop with a clear error. Write no report.
2. **Pull the data pack.** Call every endpoint in section 5. Save each raw response to `data/YYYY-MM-DD/`. Never alter a raw response.
3. **Compute the stats.** Code builds `derived.json` (section 6). This includes the comparison with the previous run.
4. **Upload files.** Send the data pack files to the Files API so the code sandbox can read them.
5. **Run the agent.** Claude gets the summary, the stats, its past notes, and two tools (section 7).
6. **Get the report as JSON.** The final answer must match the report schema (section 8).
7. **Render markdown from the JSON.** Code does this. The markdown adds nothing the JSON does not hold.
8. **Save.** Write `reports/YYYY-MM-DD.json` and `.md`. Update the watch list. Delete the uploaded files.

## 5. The data pack

All paths are relative to the base URL setting. "Today" means the 24 hours before the run. History means 7 days (168 hours is the cap on several endpoints).

| Name | Call | Why |
|---|---|---|
| health | `/health` | System overview |
| flow_chains | `/flow/chains` | Capital Flow view and its findings |
| flow_history | `/flow/history` (7 days) | Status transitions. Out-of-range `hours` returns 400, so confirm the allowed range first |
| bridge_across | `/bridges/across/health` | Bridge Health view |
| bridge_cctp | `/bridges/cctp/health` | Bridge Health view |
| bridge_stargate | `/bridges/stargate/health` | Records that it is not monitored |
| confidence | `/corridors/confidence` | Corridor tiers and findings |
| corridors | `/corridors?limit=500` | Transfer counts, success rates, durations |
| anomalies_open | `/anomalies?active=true&limit=500` | What is firing now |
| anomalies_all | `/anomalies?active=false&limit=500` | Filter in code by `detectedAt` and `resolvedAt` |
| exceedances | `/exceedances?hours=168&limit=5000` | Threshold crossings and per-series state |
| spread_latest | `/spread?latest=true` | The peg, current |
| spread_history | `/spread?hours=168&limit=5000` | The peg, over the week |
| bsh | `/bsh?hours=168&limit=5000` | Settlement health history |
| depth_latest | `/depth?latest=true` | Depth by venue and band |
| liquidity_{asset} | `/stablecoins/{asset}/liquidity?window=7d` for USDT, USDC, DAI, PYUSD, USDe | Depth history, metrics, findings per asset |
| issuer_flows | `/issuer-flows?hours=168&limit=5000` | Mint and burn |
| attestations | `/attestations` | Slow-moving. Used for staleness and change detection |
| structural_facts | `/structural-facts` | Slow-moving. Change detection only |

Rules for the pull:

- A failed call is saved as a failure record with the status and error. The run continues.
- Record every `truncated` flag, every `coverage` leg that is not `ok`, and every case where `total` is larger than the rows returned.
- `/impact/estimate` is not in the pack. The agent can call it through its tool.

## 6. Stats computed by code

Code computes these. The agent does not.

- **Finding comparison.** Collect every `finding.id` from the four surfaces. Compare with the previous run: new, gone, still open. Also record changes in `kind` and `severity`.
- **Corridor tier changes.** Any corridor whose `recommendation` changed.
- **Anomalies.** Opened and resolved in the last 24 hours. Count of open ones.
- **Exceedances.** Count by series for today, against the 7-day daily average.
- **Settlement health.** Per bridge, chain, and asset: today's minimum and median score against the 7-day values.
- **Depth.** Per asset and band: today's minimum against the 7-day median. Use the thresholds the API serves. Do not hard-code any.
- **Peg.** Today's minimum and maximum spread per asset.
- **Issuer flows.** Totals by asset, event type, and flow class. Never one gross sum.
- **Data quality.** Every failed call, truncation, and failed coverage leg.

On the first run there is no previous run. The comparison says so. It does not report everything as new.

## 7. The agent

**Model.** A setting. Default `claude-sonnet-5-5`. Try `claude-opus-5-5` and compare the reports.

**What it receives.**

- A system prompt with: its role, the rules below, and the app's `API-SPEC.md` in full. The spec documents the traps.
- `derived.json` and the app's own findings, in the message.
- The last 7 report JSON files and the current watch list.
- The raw data pack, as files in the code sandbox. Raw series do not go in the message.

**Tool 1: `api_get`** (runs on Jason's machine)

- Input: a path and query parameters.
- GET only. The path must match an allowlist built from the API spec. The two POST routes are never allowed.
- A cap on calls per run (`MAX_TOOL_CALLS`, default 15).
- A cap on result size. If a result is cut, the result says so in plain words.

**Tool 2: code execution** (runs in Anthropic's sandbox)

- Tool type `code_execution_20250825` or later, name `code_execution`. No beta header needed.
- The sandbox has no internet access. It reads the uploaded files only.
- Attach files with the Files API and `container_upload` blocks.
- When Claude calls `api_get` in the same turn as code execution, the code result arrives in a later response. The loop must handle that, and the `pause_turn` stop reason.
- Sandbox data is kept for up to 30 days. This is accepted for v1 under decision 6.

**Rules for the agent.**

1. Every claim names its source: endpoint, field, and timestamp.
2. Every finding has a label: `observed`, `pattern`, or `hypothesis`.
3. A hypothesis says what would confirm it. Causes appear only as hypotheses.
4. No invented probabilities, scores, or confidence grades.
5. A null is an absence, not a zero. Say what is missing and why.
6. Token units are not dollars. Only fields marked USD get a dollar sign.
7. Depth bands are nested. Never add them together. Never stack venue history into a total.
8. Name the window for every figure. One-hour and 24-hour figures are different things.
9. `/anomalies` has no time window. Never describe its rows as "the last N hours" unless code filtered them.
10. `/flow/history` records changes only. A gap means the status held. Do not interpolate the magnitudes.
11. Use the app's findings as a starting point. Add what they do not say. Put any disagreement in the data quality section.
12. Describe what a reading means for an agent about to move stablecoins. Never recommend a trade, a position, or yield.
13. Use "watch" and "measure." Avoid "monitoring."
14. On a quiet day, write a short report.

## 8. The report

The agent's final answer is JSON that matches a schema. Use structured outputs (`output_config.format`, type `json_schema`). It works alongside tools.

Schema limits to design around: every object needs `additionalProperties: false`, no numeric or string-length constraints, at most 24 optional fields, at most 16 union-typed fields, no recursion.

Sections:

1. **headline** — the one thing that matters today.
2. **changes** — what changed since the last run. References the code's comparison.
3. **findings** — the agent's own. Each has an id, a label, a statement, evidence (endpoint, field, value, time), and what would confirm it.
4. **followUps** — earlier findings and watch items, each marked resolved, still open, or dropped.
5. **preActionRead** — what the readings mean before acting, by chain or corridor.
6. **dataQuality** — failed reads, gaps, truncations, disagreements with the UI.
7. **watchList** — the updated list the next run will receive.
8. **run** — date, model, tool calls used, token usage.

Code renders the markdown from this JSON. One derivation, two formats.

## 9. Files and layout

```
daily-review/
  BUILD-SPEC.md
  README.md
  .env.example
  src/daily_review/
    cli.py          # run, pull-only, render
    config.py
    pull.py         # section 5
    derive.py       # section 6
    agent.py        # section 7 loop
    tools.py        # api_get and its allowlist
    schema.py       # report schema
    render.py       # JSON to markdown
  prompts/system.md
  vendor/API-SPEC.md   # copied from the app repo, with its date
  data/      # gitignored
  reports/   # gitignored
  state/     # gitignored, holds watchlist.json
  tests/
```

`data/`, `reports/`, and `state/` stay out of git. They hold depth figures.

## 10. Settings

| Setting | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | In `.env`. Never committed. |
| `BLOCKFORD_API_BASE_URL` | The port-forward address plus `/corridor-scout/api`. |
| `MODEL` | Default `claude-sonnet-5-5`. |
| `MAX_TOOL_CALLS` | Default 15. |
| `MAX_OUTPUT_TOKENS` | Cap per response. |
| `HISTORY_DAYS` | Default 7. |

Turn on prompt caching for the system prompt. The loop re-sends it on every step.

## 11. Failing loudly

- API unreachable: stop, exit non-zero, no report.
- One endpoint fails: the report is still written. The failure appears in data quality and in the headline if it hides a whole view.
- Claude call fails or the JSON does not validate: keep the data pack, exit non-zero, no report.
- Tool-call cap reached: the agent is told. The report records it.
- No view is ever skipped silently.

## 12. Build order

Each step ends with a check before the next one starts.

1. **Pull.** Save the data pack. Check: every endpoint has a file or a failure record.
2. **Derive.** Build `derived.json`. Check: tests pass on fixtures from the API spec, including null-is-not-zero and first-run cases.
3. **Agent without tools.** Stats in, report JSON out, markdown rendered. Check: schema validates.
4. **Add `api_get`.** Check: allowlist rejects POST and unknown paths. Cap holds.
5. **Add code execution.** Check: the agent reads an uploaded file and computes from it.
6. **Follow-ups.** Feed in past reports and the watch list. Check: day two refers to day one.

Then read a week of reports by hand before changing anything.

**Later, not v1:** run it daily inside the VPC, calling the app's internal address. That needs a security group rule, a route out to the Claude API, the key in Secrets Manager, email through SES, and an S3 archive.

## 13. Open questions for Jason

1. **Language.** Default is Python 3.11 with the Anthropic SDK. The app is TypeScript. Which do you want?
2. **Local address.** What port does the SSM port-forward expose? Confirm the `/corridor-scout` base path applies on the host.
3. **`/flow/history` range.** What `hours` values does it accept?
4. **Run time.** What time of day should "today" end? All times are stored in UTC.
5. **Model.** Start on Sonnet 5.5, or go straight to Opus 5.5?

## References

- Code execution tool: https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
- Structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Tool use: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- Files API: https://platform.claude.com/docs/en/build-with-claude/files
- Prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
