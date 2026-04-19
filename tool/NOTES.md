# Notes

## Known issues

### `--open` sometimes doesn't visibly launch the browser (Windows)

Running `export ... --open` writes the file correctly but the browser tab
doesn't always surface. Happens when a previous tab for the same file is
already open — the browser silently refocuses in the background.

Workarounds:
- `!start <path>` in the REPL (works reliably)
- Manually open the exported path

Likely fix: switch `webbrowser.open()` to `os.startfile()` on Windows for
local file paths, which matches `start <path>` behavior.

---

## Deferred

- Sequence-diagram header row isn't sticky when zoomed/panned — accepted
  for v1 with zoom/pan + Reset as the workaround.
- `open` command (ephemeral browser view, no export artifact) — planned.
- Pre-compact hook section in README (with 3-beat WHY) — planned.
