# Test fixtures

Every response fixture here is cut from an example in [`vendor/API-SPEC.md`](../../vendor/API-SPEC.md). No fixture is copied from a live response. The `derived/` files are golden outputs: each is what `derive` gives for a pack built in code in `tests/test_derive.py`. Fixtures hold no real depth figures beyond what the API spec itself shows.

## Rules

1. **Source.** A response fixture is an example body from the vendored API spec, copied as it appears there. Where the spec gives no example body, a fixture is built from the interface it gives, using only the spec's own ids, figures and sentences, and its row says so (Q50).
2. **Provenance.** Each file names the spec section it came from. JSON has no comments, so the name goes in the table below, one row per file, added in the same change as the file.
3. **Variants.** A case the spec example does not show (truncated, a null field, a coverage leg not `ok`, `total` above the rows) is a copy of the spec example with the smallest change that makes the case. The table says what was changed. A test may instead make the change in code, on a deep copy of the loaded fixture, when the change is one edit visible in the test (Q50, pass 2b).
4. **Re-copy.** When `vendor/API-SPEC.md` is re-copied from the app repo, check each fixture against its section and update both together.

## Layout

From [docs/TESTING.md](../../docs/TESTING.md) section 5:

```
tests/fixtures/
  README.md                              # this file
  responses/<name>.json                  # one per endpoint name, from API-SPEC.md examples
  responses/<name>.variant.<case>.json   # truncated, null, coverage cases
  reports/sample.json                    # a full report that validates
  reports/sample.md                      # its golden rendering
  derived/first-run.json
  derived/day-two.json
```

`<name>` is the endpoint name used in the data pack (`data/YYYY-MM-DD/raw/<name>.json`).

## Index

| File | Spec section | Change from the spec example |
|---|---|---|
| `derived/first-run.json` | none: golden output, not an API example | `derive(golden_pack(), None)` in `tests/test_derive.py`, written with `store.write_json`. Regenerate it only when the `Derived` shape changes, and read the diff by hand (pass 2a; regenerated in pass 2b for `findings` and `corridorTierChanges`). |
| `responses/flow_chains.json` | `GET /api/flow/chains`, Example (lines 411 to 577 of the vendored spec) | none: verbatim (pass 2b) |
| `responses/bridge_across.json` | `GET /api/bridges/:bridge/health`, Example (lines 832 to 960) | none: verbatim (pass 2b) |
| `responses/confidence.json` | `GET /api/corridors/confidence`, Example (lines 1284 to 1382) | none: verbatim (pass 2b) |
| `responses/liquidity_DAI.json` | `GET /api/stablecoins/:asset/liquidity`, sections `finding` and `findings[]` | **Built, not copied** (Q50): the spec has no example body for this endpoint. Holds only `asset`, `finding` and `findings[]`. The 50 bps entry uses the spec's own id (`dai-dap50-below-range`), figures and sentences; the 10 and 25 bps entries are `not_concluded` with the spec's unavailable headline; `finding` copies the 50 bps entry; prose the spec does not give is `…`. Pass 2e adds the `depth` part. |
