# Changelog

All notable changes to `claude-chat.py` are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/); the tool aims
to follow [Semantic Versioning](https://semver.org/).

Convention going forward: every bug fix lands with a regression test and a
`### Fixed` entry here; new commands/flags land under `### Added`.

## 1.1.0 — 2026-07-02

Round 1 of a blind adversarial review (14 findings; the structural rest is a
named round 2: sidechain filtering, serve/wiki memory, mtime→timestamp dates,
short-id collisions, TeX language whitelist, tool-result linking, thinking
surfacing).

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
