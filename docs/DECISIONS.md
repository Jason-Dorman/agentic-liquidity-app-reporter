# Decision Log — Blockford Daily Review

Every decision that shapes the build, with its status. Accepted decisions come from the spec or from Jason. Proposed decisions were made while drafting the documents and need Jason's ruling before they are coded. A proposal is never silently promoted.

Statuses: `accepted`, `proposed`, `rejected`, `superseded`.

## Accepted, from the spec (section 2)

| ID | Decision | Status | Date |
|---|---|---|---|
| D-01 | Own repo. Not built into the app repo. | accepted | 2026-10-07 |
| D-02 | Reads the app's API. Does not query the database in v1. | accepted | 2026-10-07 |
| D-03 | Read-only. GET requests only. Never calls a POST route. | accepted | 2026-10-07 |
| D-04 | Runs locally first. API calls go through the SSM port-forward. No infrastructure change. | accepted | 2026-10-07 |
| D-05 | The agent writes its own findings from the data. It does not repeat the API's `finding` text. | accepted | 2026-10-07 |
| D-06 | Internal use only. No publication gating in v1. | accepted | 2026-10-07 |
| D-07 | Claude never touches the network. The script makes every API call. | accepted | 2026-10-07 |
| D-08 | Model-written code runs in Anthropic's sandbox, never on Jason's machine. | accepted | 2026-10-07 |
| D-09 | Output is a markdown file plus a JSON file, saved by date. | accepted | 2026-10-07 |
| D-10 | The agent describes what readings mean. It never recommends trades, positions, or yield. | accepted | 2026-10-07 |

## Proposed, technical

Made while drafting and ruled on one by one on 2026-10-07 (question 6 in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)). New proposals are appended here with status `proposed` and go to Jason before they are coded. T-23 to T-25 were made inside pass 0a, where the build plan's tasks needed them; they are coded and wait on question 13.

| ID | Decision | Why | Status |
|---|---|---|---|
| T-01 | Language: Python 3.11 or later, with the Anthropic Python SDK. | The spec defaults to it; the Python SDK documents every feature used here (Files, code execution, structured outputs). Ruled by Q1. | accepted 2026-10-07 |
| T-02 | Packaging: `uv` with `pyproject.toml`. Python 3.11 or later; 3.12 is what this machine has. | `uv` is already installed here. The spec says 3.11; nothing here needs 3.11 exactly. | accepted 2026-10-07 |
| T-03 | Code execution tool type `code_execution_20260521`, declared as one constant in `tools.py`. | The current type at drafting time. Satisfies the spec's "20250825 or later". No beta header. | accepted 2026-10-07 |
| T-04 | The `run` section is written by code, not by the agent. The agent schema holds sections 1 to 7; the report schema adds `run`. | Only code knows token usage, step count, and duration. | accepted 2026-10-07 |
| T-05 | Three modules beyond the spec layout: `client.py` (one GET function), `store.py` (paths and files), `uploads.py` (Files API). | `pull.py` and `tools.py` both need GET; one place for it. Filesystem and Files API are each one reason to change and belong out of `cli.py` and `agent.py`. | accepted 2026-10-07 |
| T-06 | `api_get` input is `path` plus a `query` string, both required, `strict: true`. | Strict schemas need `additionalProperties: false`; a free-form parameter map cannot satisfy that. | accepted 2026-10-07 |
| T-07 | The allowlist is a static list in `tools.py`, and a test parses `vendor/API-SPEC.md` to assert it holds every GET route, neither POST route, and no route the spec marks removed. | Explicit in code, verified against the source. No runtime parsing of markdown. | accepted 2026-10-07 |
| T-08 | No automatic model fallback on `refusal`. A refusal is a failed Claude call: keep the pack, exit 3, no report. | Spec section 11 says fail loudly. A fallback would write the report with a model other than the one `run.model` names. Can be revisited. | accepted 2026-10-07 |
| T-09 | Exit codes: 0 report written; 1 bad setting; 2 API unreachable; 3 Claude failure or invalid JSON. | Distinct causes, distinct next actions in the runbook. | accepted 2026-10-07 |
| T-10 | Evidence `value` is always a string in the report schema; `"null"` stands for a null source value. | Avoids union types, which the structured output limits cap at 16. | accepted 2026-10-07 |
| T-11 | Non-streaming requests. `MAX_OUTPUT_TOKENS` default 16000. | A report fits well inside that. Non-streaming keeps the loop simple. Streaming becomes necessary only above about 16000. | accepted 2026-10-07 |
| T-12 | Prompt cache: one `cache_control` breakpoint on the API spec system block, 5-minute TTL. | Tools and system are cached together. Steps within a run are seconds apart. | accepted 2026-10-07 |
| T-13 | Thinking is left at the model default (adaptive, on). No `thinking` parameter is sent. | Both candidate models reject `disabled`. Depth can be tuned later with `output_config.effort` as a setting, if Jason wants one. | accepted 2026-10-07 |
| T-14 | The message list is append-only. Thinking blocks are passed back unchanged. | Required by the models' preserved-thinking check. Also the simplest loop. | accepted 2026-10-07 |
| T-15 | Ids: findings `F-<date>-<nn>`, watch items `W-<date>-<nn>`. Never reissued. | Follow-ups need stable ids across days. | accepted 2026-10-07 |
| T-16 | All times UTC. "Today" ends at the run's start time. | The spec stores everything in UTC. Ruled by Q4. | accepted 2026-10-07 |
| T-17 | The SDK's tool runner is not used. `agent.py` owns a manual loop. | The Python runner does not resume `pause_turn`, which the spec requires. | accepted 2026-10-07 |
| T-18 | A connection-refused or connection-reset error from the API is classified as "tunnel down" everywhere it can occur: the health check (exit 2), a failure record in the pack, and an `api_get` error result. It is never conflated with an HTTP error or an empty response. | From Jason's Q2 ruling: the tunnel closes on inactivity and the agent must not read that as "no data". | accepted 2026-10-07 |
| T-19 | The health check logs the `/health` body's `status`, `corridorsMonitored`, and `updatedAt` at the start of every run. | `/health` carries no environment field, so this is the only trace in the log that prod, not the local dev stack on port 3000, answered. From Jason's Q2 note. | accepted 2026-10-07 |
| T-20 | A `--date YYYY-MM-DD` option on `run` reuses that date's saved data pack instead of pulling again. | After an exit 3 the pack is already on disk; re-pulling changes the window and wastes a read of prod. Not in the spec. | accepted 2026-10-07 |
| T-21 | Tests never touch the network and never call the Claude API. Every I/O module has a fake. | Tests must run anywhere, cost nothing, and never read prod. Stated in CLAUDE.md and TESTING.md; needs Jason's ruling to be a rule. | accepted 2026-10-07 |
| T-22 | A small `Makefile` is the front door for commands: `setup`, `test`, `lint`, `check` (lint then test; the gate before every commit), `run`, `pull`, `render DATE=YYYY-MM-DD`, `help`. Each target is one line over `uv`. No tunnel target; that lives in the app repo. | One command for the pre-commit gate so it is never skipped; the daily routine becomes `make run`; `make help` lists everything. | accepted 2026-10-07 |
| T-23 | The CLI is built on the standard library's `argparse`; no CLI package is added. A usage error (unknown command, missing argument, a `--date` that is not a real `YYYY-MM-DD` date) exits **1**, not argparse's default 2. `--date` exists on `run` only. | T-09 gives exit 2 one meaning, "API unreachable", and the runbook sends Jason to the tunnel on a 2. argparse would also exit 2 on a typo. A usage error is bad input, like a bad setting. The spec's dependency list has no CLI package. Made in pass 0a. | proposed |
| T-24 | Tooling: build backend `uv_build`; `uv.lock` committed; dependencies carry lower bounds only, as `uv add` writes them; ruff rules E, W, F, I, B, UP and C90 with `max-complexity = 10`; line length 100. | The lock file gives every machine the same versions. C90 makes lint enforce the complexity rule in ENGINEERING-PRINCIPLES. `uv_build` is uv's own backend, so no second build tool. Made in pass 0a. | proposed |
| T-25 | Settings rules in `config.py`: the real environment wins over `.env`; a blank value counts as not set (the blank key in `.env.example` reads as missing, a blank optional setting takes its default); `MAX_TOOL_CALLS`, `MAX_OUTPUT_TOKENS` and `HISTORY_DAYS` are whole numbers of 1 or more; `BLOCKFORD_API_BASE_URL` starts with `http://` or `https://`; one error names every bad setting and never echoes a value; the key is held as a secret value that prints as asterisks; `.env` is read without writing into the process environment; `Settings` is frozen. | R-CFG-2 says a malformed setting stops the run and names it, but not what malformed means. Zero tool calls or zero history days would make a run that cannot do its job. Not echoing values keeps the key out of every message. Made in pass 0a. | proposed |

## Rulings from Jason

Appended as they arrive, newest last. Each entry names the question or proposal it settles.

| Date | Settles | Ruling |
|---|---|---|
| 2026-10-07 | Q1, T-01 | Python 3.11 or later with the Anthropic Python SDK. |
| 2026-10-07 | Q6 | The proposed technical decisions are ruled one by one, not as a set. Each T row carries its own ruling. |
| 2026-10-07 | Q10 | Keep the repo name `liquidity_read_agent`. Package `daily_review`, command `daily-review`. |
| 2026-10-07 | Q11 | Do not initialize git yet. Jason decides when. |
| 2026-10-07 | Q2 | Base URL `http://localhost:3300/corridor-scout/api` while the tunnel runs. Port 3300, not 3000. Keep the `/corridor-scout` prefix. The tunnel closes on inactivity and gives connection refused, which the script reports as "tunnel down", never as "no data". Only localhost can reach it. It is prod; tools stay GET-only. |
| 2026-10-07 | Q9 | Jason added the Blockford scouts API spec to the repo himself. |
| 2026-10-07 | Q8 | `/impact/estimate`: check the vendored API spec at step 4 and confirm with Jason before it enters the allowlist. |
| 2026-10-07 | Q3 | `/flow/history` accepts `hours` as an integer 1 to 720 (default 168), `limit` as an integer 1 to 5000 (default 500), and an optional `chain` from `CHAIN_IDS`. Anything else, including non-integers, returns 400 with the range in the message. Carry-in rows (`position: 'carry_in'`, one per chain, from at or before the window start) do not count against `limit`, so the response can hold more than `limit` rows. If `truncated` is true the row cap was hit: check the flag and re-call with a larger `limit`, up to 5000. |
| 2026-10-07 | Q4, T-16 | "Today" ends at the run's own start time. The window is always the 24 hours before the run. UTC. |
| 2026-10-07 | Q5 | Default model `claude-sonnet-5-5`. Compare with `claude-opus-5-5` in step 7. |
| 2026-10-07 | Q9 (location) | The API spec lives at `vendor/API-SPEC.md` with a copy header (copied 2026-10-07, version 1.0, latest entry 2026-09-28). One copy only. |
| 2026-10-07 | T-02, T-03, T-04 | Accepted as proposed. |
| 2026-10-07 | T-05, T-06, T-07, T-08 | Accepted as proposed. |
| 2026-10-07 | T-09, T-10, T-11, T-12 | Accepted as proposed. T-09 also settles PRD R-CFG-2: a bad setting stops the run before any call, exit 1. |
| 2026-10-07 | T-13, T-14, T-15, T-17 | Accepted as proposed. No `EFFORT` setting in v1. |
| 2026-10-07 | T-19, T-20, T-21 | Accepted as proposed. Every proposal is now ruled; nothing in this log is open. |
| 2026-10-07 | Q12 | Yes: `derive.py` computes a tenth statistic over `/flow/history` in pass 2c. Per chain: the spec's `chains[]` state, the count of transitions inside the window, the current status, and when it was set, with carry-in rows as window-head state and never as transitions. Magnitudes are never step-held or interpolated. |
| 2026-10-07 | T-22 | Yes to a small Makefile with the eight targets. Added in pass 0a. |
| 2026-10-07 | Build plan | The spec's seven steps stay as milestones with their exit checks unchanged. Each is split into passes on module boundaries (0a; 1a, 1b; 2a to 2e; 3a to 3c; 4a, 4b; 5a, 5b; 6a; 7), each pass ending with green tests and a commit. |
| 2026-10-07 | Q7 | The four finding surfaces are Capital Flow (`/flow/chains`), Bridge Health (`/bridges/:bridge/health`), Corridor Confidence (`/corridors/confidence`), Stablecoin Liquidity (`/stablecoins/:asset/liquidity`). `finding.id` is content-addressed and stable for the same condition. Compare ids across runs by equality: a new id is a new condition, a missing id is a condition that no longer holds. |
| 2026-10-07 | Q11 | Jason initialized the repository and pushed the documents himself (commit `ba02ce2`, branch `main`). Pass 0a task 1 is done by that. |
| 2026-10-07 | Git | Claude never commits and never pushes. Jason handles both. Claude leaves each finished pass in the working tree with `make check` green and suggests a commit message. |
| 2026-10-07 | Build plan | Mark progress in the build plan as work moves: a pass goes to `in progress` when it starts and to `done` with its date in the same change that finishes it. This is part of keeping the docs in lockstep. |
| 2026-10-07 | CI | GitHub Actions runs the rules written so far on every push. It does not fit pass 0a, so it is added to the build plan as pass 0b, before pass 1a. Its choices are questions 15 to 18. |
| 2026-10-07 | Q15 | CI runs on Python 3.11 only, the floor that `requires-python` promises. |
| 2026-10-07 | Q16 | Tests are kept off the network by an autouse fixture in `tests/conftest.py` that makes every socket connection raise. No `pytest-socket` dependency. |
| 2026-10-07 | Q17 | The repository rules run as pytest tests in `tests/test_repo_rules.py`, so `make check` catches a breach before the commit, locally and in CI. `make check` stays the one gate. |
| 2026-10-07 | Q18 | GitHub actions are pinned by major version tag (`actions/checkout@v7`, `astral-sh/setup-uv@v7`). The workflow is read-only and holds no secrets. |
