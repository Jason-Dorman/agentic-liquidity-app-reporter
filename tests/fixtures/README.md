# Test fixtures

Every fixture here is cut from an example in [`vendor/API-SPEC.md`](../../vendor/API-SPEC.md). No fixture is copied from a live response. Fixtures hold no real depth figures beyond what the API spec itself shows.

## Rules

1. **Source.** A response fixture is an example body from the vendored API spec, copied as it appears there.
2. **Provenance.** Each file names the spec section it came from. JSON has no comments, so the name goes in the table below, one row per file, added in the same change as the file.
3. **Variants.** A case the spec example does not show (truncated, a null field, a coverage leg not `ok`, `total` above the rows) is a copy of the spec example with the smallest change that makes the case. The table says what was changed.
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
| *(none yet; milestone 2 passes add them)* | | |
