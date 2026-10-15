# Open Questions — Blockford Daily Review

Questions that need Jason's ruling. Nothing that depends on a question is coded before it is answered. Answers are recorded in [DECISIONS.md](DECISIONS.md) and the question is marked closed here, with the date.

**Questions 1 to 12 were closed on 2026-10-07.** Questions 13 and 14 were raised in pass 0a and closed on 2026-10-08. Questions 15 to 18 shaped pass 0b (CI) and were closed on 2026-10-07. Question 19 was found in pass 0b and is open. Questions 20 to 26 shaped pass 1b and were closed on 2026-10-08. Question 27 was found in the first live pull and is open. Question 28 was found in pass 1b and is open. New questions are appended to the second table with the next number and status `open`.

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
| Q13 | **Pass 0a choices.** Accept T-23 (argparse; usage errors exit 1, not 2), T-24 (`uv_build`, committed `uv.lock`, ruff with C90 at 10) and T-25 (settings rules: environment over `.env`, blank is unset, integers 1 or more, base URL scheme, key never printed) in [DECISIONS.md](DECISIONS.md)? | They are already in the code from pass 0a, because the pass could not finish without them. Each is a small change to reverse. | Nothing hard. Pass 1a builds on T-25. | accept all three | closed |
| Q14 | **Which commands need the key?** `Settings` requires `ANTHROPIC_API_KEY` today. `pull-only` and `render` never call Claude, but from pass 1a they load settings for the base URL. Should they run without a key? | Without a ruling, `make pull` fails with exit 1 on a machine that has no key, though it never uses one. | Pass 1a | The key is required only by `run`. `Settings` holds it as optional; `run` checks it first, before the health check, and exits 1 naming it. `pull-only` and `render` load without it. | closed |
| Q15 | **CI Python version.** Run CI on 3.11 only, or on 3.11 and 3.12? | `requires-python` promises 3.11 and later. `.venv` on this machine is 3.11.8, and 3.12.3 is also installed. Two versions cost twice the CI time. | Pass 0b | 3.11 only, the floor that `requires-python` promises. | closed |
| Q16 | **How tests are kept off the network.** An autouse fixture in `tests/conftest.py` that makes every socket connection raise, or the `pytest-socket` dev dependency? | T-21 is a rule today but nothing enforces it. | Pass 0b | The fixture: a few lines, no new dependency. | closed |
| Q17 | **Where the repository rules run.** As pytest tests, so `make check` runs them locally and in CI, or as a CI-only step? The rules: no tracked `.env`; nothing under `data/`, `reports/`, `state/`; no image files in `docs/`. | A CI-only check catches a breach after the push; a test catches it before the commit. | Pass 0b | As tests. `make check` stays the one gate, unchanged. | closed |
| Q18 | **Pinning the GitHub actions.** By major version tag (`actions/checkout@v5`) or by full commit SHA with the version in a comment? | A tag can be moved by the action's owner; a SHA cannot. The workflow holds no secrets and only reads the repo. | Pass 0b | Major version tags. The workflow has read-only permissions and no secrets, so a moved tag has little to reach. | closed |
| Q19 | **Anchor the run-output ignores.** `.gitignore` has `data/`, `reports/` and `state/` without a leading `/`, so git ignores a directory of that name at any depth. `git check-ignore` shows `tests/fixtures/reports/sample.json`, the golden fixture TESTING section 5 plans, is ignored. Change them to `/data/`, `/reports/`, `/state/`? | The golden report fixture and its markdown would never be committed, and CI would fail on a missing file. `tests/test_repo_rules.py` already checks the top level only. | Pass 3a (fixtures under `tests/fixtures/reports/`) | Yes: anchor all three to the repository root. | open |
| Q20 | **Start pass 1b before 1a is closed?** Pass 1a's code is done; its last item is the live `pull-only` check with the tunnel open, and the tunnel was closed on 2026-10-08. | The build order says no pass starts before the one before it is done. | Pass 1b | Start 1b now and close both in one tunnel session. | closed |
| Q21 | **How the manifest finds its flags.** `truncated` flags and coverage legs sit at different depths per endpoint, and some `coverage` blocks are not legs. Declared paths per catalogue row, or a generic walk? Also flag a page whose rows equal its `limit`? | R-PULL-4. Four 5000-row pulls carry no truncation flag. | Pass 1b | Declared paths, plus `rowsAtLimit` (T-29). | closed |
| Q22 | **A re-pull on the same date.** `save_pack` overwrites by name, so an old raw file can stay beside a new failure record. | The pack must be one pull. | Pass 1b | Clear `raw/`, `failures/` and `manifest.json` first (T-30). | closed |
| Q23 | **`pull-only` exit code after calls fail mid-pull.** | A tunnel that closes mid-pull turns every later call into "tunnel down". | Pass 1b | Exit 2 if any call was "tunnel down", else 0 (T-31). | closed |
| Q24 | **Calls whose page does not cover the week.** The first live pull (2026-10-08) with `hours=168`: `bsh` at `limit=5000` covers about 38 hours (its own `truncation.truncated` is true), `exceedances` about 24.5 hours, `issuer_flows` about 11 hours, `spread_history` about 5.8 days. `anomalies_open` has `total` 5332 against a 500-row page, the maximum. Change the catalogue in pass 1b? | Spec section 5's calls cannot return a full week for four endpoints. | Pass 1b | Pull as specced, record the cuts, decide the fix separately (Q27). | closed |
| Q25 | **Liquidity coverage legs.** The live bodies have six legs under `coverage.legs` (`fits` is new); the vendored spec names five. | A fixed list would miss a leg the API adds. | Pass 1b | Every key under `coverage.legs` is a leg (T-32). | closed |
| Q26 | **`rowsAtLimit` without a sent `limit`.** `attestations` and `structural_facts` use a server default of 100 and echo it. `flow_history` carry-in rows do not count against `limit`. | A default-100 page can be cut silently; a carry-in count would be wrong. | Pass 1b | Use the echoed `limit`; exempt `flow_history` (T-32). | closed |
| Q27 | **Cover the full week.** Four 168-hour pulls are cut at 5000 rows (see Q24), and the open anomalies exceed the 500-row page. The week statistics of passes 2c to 2e (exceedances daily average, settlement health week values, peg, issuer flows) would be computed over a part of the window. Options: split calls by asset, bridge or series; shorter windows; ask the app for an offset or a higher cap; or compute only over the hours the page covers and say so. | Every week figure names its window; a partial window must not pass as a full one. | Passes 2c, 2d, 2e | none yet; to be proposed with live row counts per filter | open |
| Q28 | **`run` after a call is "tunnel down" mid-pull.** T-31 rules `pull-only`: save the pack and exit 2. Should `run` do the same and stop before the agent, or go on and write a report whose data quality section names the hidden views? | Spec section 11 says an unreachable API stops the run with no report, and one failed endpoint does not. A tunnel that closes mid-pull is both. | Pass 3b | Stop like `pull-only`: save the pack, exit 2, no report. After reopening the tunnel, `run` pulls again. | open |

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
| Q15 | 2026-10-07 | CI on Python 3.11 only. | DECISIONS rulings table |
| Q16 | 2026-10-07 | Autouse socket guard in `tests/conftest.py`; no new dependency. | DECISIONS rulings table, TESTING section 1 |
| Q17 | 2026-10-07 | Repository rules as pytest tests in `tests/test_repo_rules.py`. | DECISIONS rulings table, TESTING section 4 |
| Q18 | 2026-10-07 | Actions pinned by major version tag. | DECISIONS rulings table |
| Q13 | 2026-10-08 | T-23, T-24 and T-25 accepted as coded. | DECISIONS T-23 to T-25, rulings table |
| Q14 | 2026-10-08 | The key is required by `run` only; `pull-only` and `render` load without it. | DECISIONS rulings table, T-25, RUNBOOK section 2 |
| Q20 | 2026-10-08 | No: wait for the tunnel. Pass 1a's live check is run and 1a marked done before pass 1b starts. | DECISIONS rulings table |
| Q21 | 2026-10-08 | Declared paths per catalogue row, plus `rowsAtLimit` beyond the spec. | DECISIONS T-29 |
| Q22 | 2026-10-08 | A re-pull clears that date's `raw/`, `failures/` and `manifest.json` first. | DECISIONS T-30 |
| Q23 | 2026-10-08 | Exit 2 if any call in the pull was "tunnel down"; else 0 once the pack is saved. | DECISIONS T-31 |
| Q24 | 2026-10-08 | Pull as specced in pass 1b; record the cuts; the fix is question 27. | DECISIONS rulings table |
| Q25 | 2026-10-08 | Every key under `coverage.legs` is a leg. | DECISIONS T-32 |
| Q26 | 2026-10-08 | Sent `limit`, else echoed; `flow_history` exempt. | DECISIONS T-32 |
