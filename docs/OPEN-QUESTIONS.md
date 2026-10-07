# Open Questions — Blockford Daily Review

Questions that need Jason's ruling. Nothing that depends on a question is coded before it is answered. Answers are recorded in [DECISIONS.md](DECISIONS.md) and the question is marked closed here, with the date.

**Questions 1 to 12 were closed on 2026-10-07.** New questions are appended to the second table with the next number and status `open`.

Statuses: `open`, `closed`.

## From the spec (section 13)

| # | Question | Why it matters | Blocks | Proposed default | Status |
|---|---|---|---|---|---|
| Q1 | **Language.** Python 3.11 with the Anthropic SDK, or TypeScript like the app? | Every code file, the commands in the README and runbook, the test tooling. | Step 0 | Python (T-01). The Python SDK documents every feature used here. | closed |
| Q2 | **Local address.** What port does the SSM port-forward expose? Does the `/corridor-scout` base path apply on the host? | `BLOCKFORD_API_BASE_URL` and the first live exit check. | Step 1 | none; `.env.example` carries a placeholder | closed |
| Q3 | **`/flow/history` range.** What `hours` values does it accept? | Out-of-range returns 400, and the pack would carry a failure record every day. | Step 1 | none; confirm from the API spec or a live call | closed |
| Q4 | **Run time.** What time of day should "today" end? All times are UTC. | The window on every figure, and the daily routine. | Step 2 | The run's own start time (T-16), so the window is always the 24 hours before the run | closed |
| Q5 | **Model.** Start on Sonnet 5.5, or go straight to Opus 5.5? | Cost and report quality. The spec says try both and compare. | Step 3 | Sonnet 5.5 as default, compare with Opus 5.5 in step 7 (spec section 7) | closed |

## Found while drafting the documents

| # | Question | Why it matters | Blocks | Proposed default | Status |
|---|---|---|---|---|---|
| Q6 | **Proposed technical decisions.** Accept T-01 to T-17 in [DECISIONS.md](DECISIONS.md) as a set, or rule on them one by one? | They shape the module layout, the schema, the loop, and the exit codes. | Step 0 | accept as a set | closed |
| Q7 | **Finding surfaces and ids.** The spec says findings come from "the four surfaces". Which four endpoints are they? Are `finding.id` values stable across days, so that new, gone, and still open can be computed? | The finding comparison is the first statistic and the backbone of `changes` and `followUps`. | Step 2 | The API spec's `finding` section names the four: Capital Flow (`/flow/chains`), Bridge Health (`/bridges/:bridge/health`), Corridor Confidence (`/corridors/confidence`), Stablecoin Liquidity (`/stablecoins/:asset/liquidity`). It says `finding.id` is content-addressed and "stable for the same condition; NOT a sequence number". Confirmed by Jason. | closed |
| Q8 | **`/impact/estimate`.** It is reachable only through `api_get`. Is it a GET route, and what parameters does it take? | The allowlist. | Step 4 | from the API spec | closed |
| Q9 | **Where to copy `API-SPEC.md` from.** The app repo was not found under `~/projects` on this machine. A prior session points at `/mnt/c/Users/rjd61/Documents/RebelWealth/scouts/corridor-scouts`. Is that the app repo, and which file is the spec? | `vendor/API-SPEC.md` feeds the system prompt and the allowlist. | Step 0 | that path | closed |
| Q10 | **Names.** The spec's layout is `daily-review/` with package `daily_review`; this repo is `liquidity_read_agent`. Keep the repo name and use `daily_review` as the package and `daily-review` as the command? | File paths in every document. | Step 0 | yes | closed |
| Q11 | **Git.** This directory is not a git repository yet. Initialize it in step 0 and make the documents the first commit? | The principles say commit frequently. | Step 0 | yes | closed |
| Q12 | **Flow-history statistic.** Spec section 6 lists no statistic over `/flow/history`; the file is in the pack for the agent to read in the sandbox under rule 10. Should `derive.py` also compute per-chain status transitions in the window (count, current status, held since), honoring carry-in rows and held status? | Decides whether pass 2c has a third statistic, and whether the carry-in handling is code or prompt. | Pass 2c | No. Keep to the spec's nine statistics; the agent reads the raw file. Add it later only if the week of reading shows the agent misreads carry-in rows. | closed |

## Closed

| # | Closed on | Ruling | Recorded in |
|---|---|---|---|
| Q1 | 2026-10-07 | Python 3.11 or later. | DECISIONS T-01 |
| Q6 | 2026-10-07 | Ruled on T-02 to T-21 one by one; all accepted. | DECISIONS rulings table |
| Q10 | 2026-10-07 | Keep repo name; package `daily_review`; command `daily-review`. | DECISIONS rulings table |
| Q11 | 2026-10-07 | No git init yet. Jason decides when. | DECISIONS rulings table |
| Q2 | 2026-10-07 | `http://localhost:3300/corridor-scout/api`; tunnel facts recorded in RUNBOOK 1.1; "tunnel down" handling in T-18. | DECISIONS rulings table, T-18, RUNBOOK |
| Q9 | 2026-10-07 | Jason added the API spec to the repo; moved to `vendor/API-SPEC.md` with a copy header on his ruling. | DECISIONS rulings table |
| Q3 | 2026-10-07 | `hours` 1 to 720 integer, default 168; `limit` 1 to 5000, default 500; carry-in rows exempt from `limit`; re-call with a larger `limit` when `truncated` is true. | DECISIONS rulings table, PRD R-PULL-6 |
| Q4 | 2026-10-07 | "Today" ends at the run's start time. | DECISIONS T-16 |
| Q5 | 2026-10-07 | Sonnet 5.5 default; compare Opus 5.5 in step 7. | DECISIONS rulings table |
| Q7 | 2026-10-07 | Four surfaces as the spec names them; ids compared by equality. | DECISIONS rulings table, GLOSSARY |
| Q12 | 2026-10-07 | Yes: a flow-history statistic in pass 2c, with carry-in rows as window-head state. | DECISIONS rulings table, PRD R-DRV-13, DATA-CONTRACTS section 3 |
| Q8 | 2026-10-07 | Check the vendored spec at step 4; confirm with Jason before allowlisting. The spec (section `GET /api/impact/estimate`) shows a GET with four required query parameters: `bridge`, `source`, `dest`, `amountUsd`. | DECISIONS rulings table |
