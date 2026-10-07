# CLAUDE.md

Working rules for Claude Code in this repository. Read this before touching anything.

## Who you are working with

Jason is the **product owner and the lead engineer**. Treat him as both.

- He makes the product calls and the engineering calls. You propose, he decides.
- **If there is a question, ask him. Do not assume.** This includes small things: a default value, a file name, a library choice, how to interpret a field. Ask before you build on the assumption.
- When you ask, give him the options and your recommendation, then wait.
- Record every answer in [docs/DECISIONS.md](docs/DECISIONS.md) and close the item in [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md).
- Do not start code on a step whose open questions are unanswered. Say what is blocked and why.

## Documents move in lockstep with code

**Every code change that alters behavior, shape, layout, settings, or commands updates the documents in the same change.** Not later. Not in a follow-up. The docs are part of the deliverable.

Use this map to know what to update:

| If you change... | Update |
|---|---|
| A module's responsibility, a dependency between modules, the run sequence, failure handling | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| The data pack layout, `derived.json`, the report schema, the watch list, rendering | [docs/DATA-CONTRACTS.md](docs/DATA-CONTRACTS.md) |
| The system prompt, tool definitions, agent rules, what the agent receives | [docs/AGENT-DESIGN.md](docs/AGENT-DESIGN.md) and `prompts/system.md` |
| A setting, a command, an exit code, a path | [docs/RUNBOOK.md](docs/RUNBOOK.md), `.env.example`, and the README quickstart |
| A step's status, scope, or exit check | [docs/BUILD-PLAN.md](docs/BUILD-PLAN.md) |
| A decision, or you make a technical choice the spec does not cover | [docs/DECISIONS.md](docs/DECISIONS.md) (and ask Jason first) |
| A requirement's meaning or scope | [docs/PRD.md](docs/PRD.md), and tell Jason, because the spec is the source |
| Test strategy, fixtures, required cases | [docs/TESTING.md](docs/TESTING.md) |
| A term's meaning | [docs/GLOSSARY.md](docs/GLOSSARY.md) |

Before you say a change is done, check this table. All diagrams are Mermaid, inside fenced ` ```mermaid ` blocks. No image files.

## Engineering principles

[docs/ENGINEERING-PRINCIPLES.md](docs/ENGINEERING-PRINCIPLES.md) applies to every line. The short version:

- **Maximize cohesion. Minimize coupling. Contain the impact of change.**
- One module, one reason to change. One function, one job.
- Composition over inheritance. Code to interfaces. Make dependencies explicit.
- Cyclomatic complexity under 10, ideally 5. If higher, split, unless the domain truly demands it.
- Tests first when possible. Every behavior change comes with tests. No tests, no merge.
- No shared global state. No control flags that change behavior.
- When in doubt, simplify.

Run the review checklist in that document before every commit.

## Hard constraints from the spec

These come from [docs/BUILD-SPEC.md](docs/BUILD-SPEC.md) and [docs/DECISIONS.md](docs/DECISIONS.md). They are not negotiable in code review.

1. GET only. The `api_get` allowlist is built from the API spec. The two POST routes are never allowed.
2. Claude never touches the network. The script makes every API call.
3. Model-written code runs only in Anthropic's code execution sandbox.
4. Raw API responses are saved verbatim and never altered.
5. Code computes the statistics. The agent does not.
6. Thresholds come from the API. None are hard-coded.
7. A null is an absence, not a zero.
8. Token units are not dollars. Only fields marked USD get a dollar sign.
9. Depth bands are nested; never summed. Venue history is never stacked into a total.
10. The agent never recommends a trade, a position, or yield.
11. No view is ever skipped silently. Every failure appears in the report's data quality section.
12. The markdown is rendered from the JSON and adds nothing the JSON does not hold.
13. `data/`, `reports/` and `state/` are gitignored. `.env` is never committed.

## Build order

Follow [docs/BUILD-PLAN.md](docs/BUILD-PLAN.md). The spec's seven steps are milestones, each split into passes. A pass ends with green tests, updated docs, and a commit. A milestone ends with its exit check against the live API. Do not skip ahead. Do not combine passes.

## Where things live

| Thing | Place |
|---|---|
| Package code | `src/daily_review/` |
| System prompt | `prompts/system.md` |
| Vendored API spec | `vendor/API-SPEC.md` (copy header on line 1; re-copy from the app repo, never edit) |
| Tests and fixtures | `tests/`, `tests/fixtures/` |
| Raw data packs | `data/YYYY-MM-DD/` |
| Reports | `reports/YYYY-MM-DD.json` and `.md` |
| Watch list | `state/watchlist.json` |

## Commands

Python 3.11 or later, ruled 2026-10-07 (question 1). The `Makefile` is the front door (T-22); each target is one line over `uv`:

```bash
make setup      # uv sync
make test       # uv run pytest
make lint       # uv run ruff check src tests
make check      # lint, then test. Run this before every commit. No exceptions.
make run        # uv run daily-review run
make pull       # uv run daily-review pull-only
make render DATE=YYYY-MM-DD   # uv run daily-review render reports/DATE.json
make help       # list the targets
```

To reuse a saved pack after a failed run: `uv run daily-review run --date YYYY-MM-DD`.

Tests never touch the network. Tests never call the Claude API. Every I/O module has a fake (T-21).

## Claude API usage

Use the official `anthropic` SDK. Current shapes are documented in [docs/AGENT-DESIGN.md](docs/AGENT-DESIGN.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Do not write API calls from memory. If a shape is uncertain, check the SDK or ask.

## Git

- The repository is not initialized yet. Jason decides when (question 11). Do not run `git init` on your own.
- Once initialized: commit at the end of every pass at minimum, and after each green `make check` during a pass. Never commit with `make check` failing.
- Commit messages say what changed and why, in plain words.
- Never commit `.env`, `data/`, `reports/`, `state/`.

## Writing style for documents

Plain words. Short sentences. Say what a thing is, not what it is like. "Watch" and "measure", not "monitoring". Name the window for every figure.
