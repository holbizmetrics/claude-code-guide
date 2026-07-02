# Changelog

All notable changes to `claude-chat.py` are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/); the tool aims
to follow [Semantic Versioning](https://semver.org/).

Convention going forward: every bug fix lands with a regression test and a
`### Fixed` entry here; new commands/flags land under `### Added`.

## 1.1.3 — 2026-07-02

Round 2 (second feature): **thinking surfacing** — `Message.thinking` was parsed
but rendered nowhere; half the parse work was write-only.

### Added
- **`export --thinking` / `open --thinking`.** Assistant reasoning blocks now
  render as collapsible `<details>` sections in the markdown and HTML exporters
  (before the response text — reasoning precedes answer). **Off by default**:
  thinking is verbose and frequently encrypted-empty in real transcripts, so
  it stays opt-in. Capped at 2000 chars unless `--no-truncate`. Wired through the
  `export_markdown` / `export_html` wrappers too. 2 new tests. Suite: 155 passed.

## 1.1.2 — 2026-07-02

Round 2 (first feature): **tool-result linking** — the blind audit's biggest
export omission.

### Added
- **Tool-result linking.** Each tool's OUTPUT — a `tool_result` block that
  arrives in a later user message, keyed by `tool_use_id` — is now linked back
  onto the `ToolCall` that produced it (`ToolCall.id` + `ToolCall.result`).
  Exports previously showed tool INPUTS but never OUTPUTS, so re-reading an
  exported session showed what was *asked* and never what came *back*. The
  markdown and HTML exporters now render a **Result:** block under each tool call
  (capped at 1000 chars unless `--no-truncate`). `tool_result` content given as a
  list of text/image blocks is flattened (images → `[image]`). 3 new tests
  (link-by-id, list-content flatten, unmatched-id stays None). Suite: 153 passed.

## 1.1.1 — 2026-07-02

Follow-up to 1.1.0: reconcile a test the 1.1.0 reminder-block fix intentionally
broke — and which 1.1.0 shipped without noticing, because it was verified
manually + by profile-diff but the existing pytest suite was **not run** (the
"lint/test before done" miss, owned).

### Fixed
- `test_system_reminder_in_middle_filtered` asserted the OLD (buggy) behavior —
  drop the whole message if a reminder appears anywhere. The 1.1.0 fix
  deliberately changed this: strip the reminder span, KEEP the surrounding real
  prompt. Test renamed → `test_system_reminder_in_middle_stripped_text_kept`
  and now asserts the corrected behavior (reminder gone, real text on both sides
  kept). Suite green: 150 passed.

### Correction
- The 1.1.0 notes implied a test harness would be *built* in round 2. It already
  existed (`test_claude_chat.py`, since v1.0.1) — round 2 EXTENDS it, not builds it.

## 1.1.0 — 2026-07-02

Round 1 of a blind adversarial review (14 findings; the structural rest is a
named round 2: sidechain filtering, serve/wiki memory, mtime→timestamp dates,
short-id collisions, TeX language whitelist, tool-result linking, thinking
surfacing — all EXTENDING the existing `test_claude_chat.py` suite, not building it).

### Fixed
- **User messages carrying `<system-reminder>` blocks were dropped whole** —
  Claude Code appends reminder blocks (hook context, file-change notices) to
  the same content array as the real prompt, so real prompts vanished from
  `export`/`search`/`extract` AND the turn boundary was swallowed, merging
  adjacent assistant turns and skewing `profile`/`compare` metrics. Reminder
  spans are now stripped per block; pure-reminder messages still skip.
- `protect` read/wrote `settings.json` with the platform-default encoding
  (cp1252 mojibake risk on the file that configures Claude Code itself) and
  crashed on malformed JSON; now UTF-8 + refuses to write after a dirty read.
- `export --output <newdir>` died with a raw traceback (missing mkdir).
- `--limit 0` silently became 20 (`or 20` on list/search).
- `search` printed only the first N result sessions with no indication more
  existed; now prints an "…and N more session(s)" trailer.

### Added
- **`usage` (alias `tokens`)** — per-month token table (input/output/
  cache-write/cache-read/TOTAL) summed from transcript `message.usage` fields;
  `--by-model` splits per model; `--project` filters. Raw line scan, no parse.
- **`open SESSION_ID`** — renders to HTML in a temp dir and opens the browser
  (the interactive tip after `list` had advertised `open N` for a command that
  didn't exist).
- `search` raw-substring prefilter: skips full JSON parsing for files that
  can't contain the query (ASCII, quote-free queries only — JSON-escaping-safe;
  falls back to full parse otherwise). Full-corpus search on ~770 files now
  ~2 s. The "did you mean a different project?" second scan uses it too.

## 1.0.2 — 2026-06-14

### Fixed
- Top-level help (`-h` / `--help` / `help`) Examples block was stale: it omitted
  `profile`, `compare`, `activity`, and `wiki`, and had no `--model` example
  despite model filtering being a flagship feature. Added examples for all,
  including `list --model fable`. Same class of omission as the 1.0.1
  interactive-help fix — both help surfaces are now complete.

### Docs
- README `list` section: added a `--model` filter example.

## 1.0.1 — 2026-06-14

### Fixed
- `claude-chat.py -h` / `--help` no longer crashes. A literal `%` in the
  `profile` subcommand's help string ("reasoning %, ...") was parsed by
  argparse as a format specifier, raising
  `ValueError: unsupported format character ',' at index 45`. The top-level
  help had been broken since the `profile` command was added. Escaped to `%%`.
- The interactive (REPL) help now lists `profile`, `compare`, `activity`, and
  `wiki` — four shipped commands that were absent from `help`, making them
  undiscoverable to anyone not reading the source or the README.

### Added
- `claude-chat.py help` and `claude-chat.py ?` now print top-level help instead
  of an "invalid choice" argparse error, mirroring the REPL's `help` command.
  `claude-chat.py help <command>` forwards to `<command> --help`.

### Tests
- New `TestHelpSurface` suite (7 tests): full-help renders without raising,
  every subparser help string is interpolation-safe (guards the whole surface
  against future stray `%`), interactive help lists all primary commands, and
  the CLI `help` / `?` / `help <command>` shims behave.

### Docs
- README: corrected the stale interactive-mode banner and added the missing
  `profile`, `compare`, and `activity` command sections plus a shell-help note.

## 1.0.0

Initial release: `list`, `search`, `export` (md/html/txt/tex), `backup`,
`stats`, `extract`, `profile`, `compare`, `activity`, `serve`, `wiki`,
`protect`; interactive REPL; static cross-linked HTML archive; per-model
behavioral profiling.
