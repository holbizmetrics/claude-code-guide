# Changelog

All notable changes to `claude-chat.py` are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/); the tool aims
to follow [Semantic Versioning](https://semver.org/).

Convention going forward: every bug fix lands with a regression test and a
`### Fixed` entry here; new commands/flags land under `### Added`.

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
