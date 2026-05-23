# chat-merge — test fixtures

Seed fixtures for the ChatMerge regression suite (suite itself: TODO). Promoted
2026-05-23 from ad-hoc mass-use test data, so the tool that *rewrites chat history*
finally gets a safety net.

## Cases (`tests/cases/`)
Each case dir holds input `.txt` exports + the expected `*_merged.txt`:
- `3-edge`, `4-pref-suf`, `4b-suffix`, `5-boilerplate`, `6-identical`, `7-five-singletons`
  — grouping / edge scenarios (prefix & suffix overlap, boilerplate normalization,
  identical inputs, all-singletons).
- `fp-resistance` — distinct sessions that must NOT be merged together (fingerprint specificity).

## Properties the suite must assert (priority order)
1. **Lossless merge** (load-bearing / Grounding-Audit): each produced `_merged.txt` is a
   content-superset of every input in its stream — no dropped turns. "Keep the largest"
   *assumes* superset; an edited/branched export may not be -> silent loss.
2. **Determinism**: same inputs -> byte-identical streams across runs. (The old det-A/det-B
   dirs were two-run *evidence*, ~97 files each — not stored here; the suite regenerates both
   runs and compares. Originals live in the operator's backup if a large/scale fixture is wanted.)
3. **Grouping correctness**: progressive exports of one session -> one stream; distinct
   sessions stay separate (fp-resistance).
4. **Input validation**: non-export / wrong-type inputs rejected, not silently processed
   (gap flagged in `../AUDIT-2026-05-11.md`).

## Running (once the suite exists)
`dotnet test` — a `ChatMerge.Tests` project that runs ChatMerge on each case dir and
asserts the properties above against the expected `_merged.txt`.
