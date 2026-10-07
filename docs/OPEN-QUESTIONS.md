# Open Questions — Blockford Daily Review

Questions that need Jason's ruling. Nothing that depends on a question is coded before it is answered. Answers are recorded in [DECISIONS.md](DECISIONS.md) and the question is marked closed here, with the date.

**Questions 1 to 12 were closed on 2026-10-07.** Questions 13 and 14 were raised in pass 0a and are open. Questions 15 to 18 shape pass 0b (CI) and are open. New questions are appended to the second table with the next number and status `open`.

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
| Q13 | **Pass 0a choices.** Accept T-23 (argparse; usage errors exit 1, not 2), T-24 (`uv_build`, committed `uv.lock`, ruff with C90 at 10) and T-25 (settings rules: environment over `.env`, blank is unset, integers 1 or more, base URL scheme, key never printed) in [DECISIONS.md](DECISIONS.md)? | They are already in the code from pass 0a, because the pass could not finish without them. Each is a small change to reverse. | Nothing hard. Pass 1a builds on T-25. | accept all three | open |
| Q14 | **Which commands need the key?** `Settings` requires `ANTHROPIC_API_KEY` today. `pull-only` and `render` never call Claude, but from pass 1a they load settings for the base URL. Should they run without a key? | Without a ruling, `make pull` fails with exit 1 on a machine that has no key, though it never uses one. | Pass 1a | The key is required only by `run`. `Settings` holds it as optional; `run` checks it first, before the health check, and exits 1 naming it. `pull-only` and `render` load without it. | open |
| Q15 | **CI Python version.** Run CI on 3.11 only, or on 3.11 and 3.12? | `requires-python` promises 3.11 and later. `.venv` on this machine is 3.11.8, and 3.12.3 is also installed. Two versions cost twice the CI time. | Pass 0b | 3.11 only, the floor that `requires-python` promises. | open |
| Q16 | **How tests are kept off the network.** An autouse fixture in `tests/conftest.py` that makes every socket connection raise, or the `pytest-socket` dev dependency? | T-21 is a rule today but nothing enforces it. | Pass 0b | The fixture: a few lines, no new dependency. | open |
| Q17 | **Where the repository rules run.** As pytest tests, so `make check` runs them locally and in CI, or as a CI-only step? The rules: no tracked `.env`; nothing under `data/`, `reports/`, `state/`; no image files in `docs/`. | A CI-only check catches a breach after the push; a test catches it before the commit. | Pass 0b | As tests. `make check` stays the one gate, unchanged. | open |
| Q18 | **Pinning the GitHub actions.** By major version tag (`actions/checkout@v5`) or by full commit SHA with the version in a comment? | A tag can be moved by the action's owner; a SHA cannot. The workflow holds no secrets and only reads the repo. | Pass 0b | Major version tags. The workflow has read-only permissions and no secrets, so a moved tag has little to reach. | open |

## Closed

| # | Closed on | Ruling | Recorded in |
|---|---|---|---|
| Q1 | 2026-10-07 | Python 3.11 or later. | DECISIONS T-01 |
| Q6 | 2026-10-07 | Ruled on T-02 to T-21 one by one; all accepted. | DECISIONS rulings table |
| Q10 | 2026-10-07 | Keep repo name; package `daily_review`; command `daily-review`. | DECISIONS rulings table |
| Q11 | 2026-10-07 | No git init yet. Jason decides when. Later the same day Jason initialized and pushed the repository himself. | DECISIONS rulings table |
| Q2 | 2026-10-07 | `http://localhost:3300/corridor-scout/api`; tunnel facts recorded in RUNBOOK 1.1; "tunnel down" handling in T-18. | DECISIONS rulings table, T-18, RUNBOOK |
| Q9 | 2026-10-07 | Jason added the API spec to the repo; moved to `vendor/API-SPEC.md` with a copy header on his ruling. | DECISIONS rulings table |
| Q3 | 2026-10-07 | `hours` 1 to 720 integer, default 168; `limit` 1 to 5000, default 500; carry-in rows exempt from `limit`; re-call with a larger `limit` when `truncated` is true. | DECISIONS rulings table, PRD R-PULL-6 |
| Q4 | 2026-10-07 | "Today" ends at the run's start time. | DECISIONS T-16 |
| Q5 | 2026-10-07 | Sonnet 5.5 default; compare Opus 5.5 in step 7. | DECISIONS rulings table |
| Q7 | 2026-10-07 | Four surfaces as the spec names them; ids compared by equality. | DECISIONS rulings table, GLOSSARY |
| Q12 | 2026-10-07 | Yes: a flow-history statistic in pass 2c, with carry-in rows as window-head state. | DECISIONS rulings table, PRD R-DRV-13, DATA-CONTRACTS section 3 |
| Q8 | 2026-10-07 | Check the vendored spec at step 4; confirm with Jason before allowlisting. The spec (section `GET /api/impact/estimate`) shows a GET with four required query parameters: `bridge`, `source`, `dest`, `amountUsd`. | DECISIONS rulings table |
