# chat-merge — test fixtures

Fixtures and the ChatMerge regression suite (`run_tests.py`, added 2026-11-24). Promoted
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

## Running
`python3 tests/run_tests.py` (needs the .NET 10 SDK; `--no-build` reuses the built binary). It runs
ChatMerge on a copy of each case dir and asserts, per case: the expected `_merged.txt` set and
content (line endings normalised -- the fixtures were made on Windows), determinism (two runs
identical), property 1 as LOSSLESS (every non-blank input line is in some output), and one output
file per stream. Two generated RED cases pin the 2026-11-24 data-loss bugs and failed on the code
before that fix: `collide` (two conversations named chat-export-1/2 and -3/4 wrote one output file,
the first lost) and `diverge` (two exports sharing a 220-line opening, the smaller one's own ending
dropped). Last run: `RECORD: chat-merge-tests passed=40 failed=0`; switching either fix off turns its
own two checks red (38/40).

Not covered yet: property 4 (input validation -- non-export files are still processed) and `--single`
mode (checked by hand 2026-11-24: both conversations kept).
