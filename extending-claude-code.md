# Extending Claude Code — field notes from a running installation

*July 2026, Claude Code 2.1.x era. Companion to
[claude-code-2.1.x-features-and-hidden-commands.md](claude-code-2.1.x-features-and-hidden-commands.md).
Everything in Part 1 runs daily on a real four-box fleet (two Windows machines, a Linux box, an
Android phone under Termux) driving a research lab. Part 2 is the extension surface NOT yet
attached, mapped honestly. Part 3 is the adoption order picked, Part 4 the scar tissue.
Versions drift — treat specifics as observations, not contracts.*

---

## Part 1 — Surfaces in production here

### Hooks — the biggest lever

Claude Code's hook events are where an installation stops being a chat tool and becomes
infrastructure. What's wired here, by event:

| Event | What's attached |
|---|---|
| `SessionStart` (startup) | Boot scans: decayed-resource report, hypothesis⇌result registry join, mode-config sanity check. All **silent when clean**, all fail-open. |
| `SessionStart` (compact) | Re-injects project state after context compaction — the session picks up where the compacted one stood. |
| `PreToolUse` on Write/Edit — **blocking** | Contract gates: a dispatch document missing its required `decidable-check:` line is *denied*; a results-ledger row that names no resolvable verifier is *denied*. The write physically cannot happen wrong. |
| `PreToolUse` on Bash — **blocking** | Refuses any state-changing git command with silenced stderr (`git add … 2>/dev/null`). A failed add makes no commit, so no later gate can see it — this is the one failure only a pre-hook can catch. |
| `PreToolUse` on Write — reminders | Non-blocking nudges: first write into a sibling repo → "run the reuse scan first"; first write into heavyweight-process territory → "is this finding big enough for ceremony?" |
| `PostToolUse` | Structural-drift noticer on source files (flags a file crossing size/shape thresholds; suggests one slice, never a rewrite). |
| `Stop` — **blocking** | Push-verify: the session claims "all pushed / nothing stranded" while `git rev-list @{u}..HEAD` says otherwise → the stop is blocked until reality matches the claim. Output-budget: last message hit `max_tokens` → block, force chunked redelivery. Closeout enforcement: a done-declaration without the closing procedure's artifact → block. |
| Speech | A hook pipes assistant output to a local TTS engine (Kokoro, CPU-only, 54 voices) — long runs are audible across the room, and a message bus monitor can *speak* incoming results. |

**Hook lessons, all paid for:**

- **Write hooks as `.sh` files, not inline commands.** On Windows the inline form goes through
  `cmd /c` and gets MSYS-mangled. A two-line shell wrapper is immune.
- **Gate on `CLAUDE_CODE_ENTRYPOINT=cli`.** A user-scoped output hook otherwise contaminates
  every headless `claude -p` call on the machine, corrupting programmatic output.
- **Check the executable bit AND the git index mode (`100755`).** Six hooks sat registered,
  correct, and dead for days across machines because they were committed `100644` — they existed,
  they just couldn't *run*. Verification that only asks "does the file exist?" misses this class.
- **Every blocking gate ships with a test corpus plus a planted-positive control.** A gate that
  has only ever said "pass" has been shown to run, not to work. One gate here fail-opened for 31
  days because it read a field the harness never sends — its corpus stayed green the whole time,
  because the corpus fed the same wrong field.
- **Heuristics warn; only authoritative signals block.** A phrase-scanning axis ("sounds like a
  closeout") false-positives; it may warn. Git state and `stop_reason` are authoritative; they may
  block. A gate that wrongly wedges the user gets waived, and a waived gate is worse than none.

### Slash commands / skills

Project skills live in `.claude/commands/` and `.claude/skills/`. Two conventions that earned
their keep: **prefix-namespace your commands** (everything here is `pcla-*` after the native
`/checkpoint` rewind command shadowed a same-named project command), and treat a skill as a
*procedure* — the session-close skill here runs a six-gate checklist (retrospective, silence
detection, log write, state persist + push, memory hygiene, insight capture) so "we're done" is a
verified state, not a mood.

### CLAUDE.md as a boot loader

Not just style rules: an ordered read-list of architecture files, then a compressed
*trigger → action* table so rules buried deep in prose have a scannable surface. House rule worth
stealing: any rule stated in two places must name its authoritative copy inline — unowned
duplicates drift apart silently.

### Auto-memory

One fact per file, an index file as the always-loaded surface, and a standing discipline:
memory can be stale — verify against the artifact before acting on a remembered "fact." A
six-month-old local clone presented as ground truth is this failure class; it happened while
writing this document's sibling analysis.

### Headless `claude -p`

Works on a subscription, no API key. Used here for benchmark harnesses and cross-session tooling.
See the entrypoint-gating lesson above before adding any user-scoped hook.

### Monitor + background tasks

The `Monitor` tool holds a persistent watch on an external process — here, a message-bus watcher
that raises notifications when peer sessions write. Background Bash keeps servers and beats alive
across turns.

### The transcript as a flight recorder

Every session is a JSONL file under `~/.claude/projects/<project-slug>/`. That surface is
attachable: a post-hoc scanner here reads the session transcript at close and counts verdict-class
statements that never named their evidence source — a per-session quality metric no live hook
could produce. (This repo's `claude-chat.py` exists because of this surface: search, export,
protect.)

### Beyond the harness: an inter-session bus

Not a Claude Code feature — but attached *through* Claude Code surfaces. A git-backed JSONL
message bus lets concurrent sessions on different machines message each other without the human
relaying: boot-time pending-check (summary first, bodies on request), mid-session `Monitor` watch,
identity per session. Presence lesson that transfers to any agent fleet: **a fresh heartbeat is a
process, not a listener.** Distinguish offline / online-but-idle / online-and-attending before
reading silence as deliberation.

---

## Part 2 — The unattached surface (catalog as of July 2026)

### Orchestration

- **Custom subagents** (`.claude/agents/*.md`) — named agents with their own system prompt, tool
  allowlist, and model. Recurring review roles (blind-verifier lenses, a persona reviewer) that
  today are prose prompts re-typed per use become versioned, greppable, invocable by name.
- **Workflow tool + saved workflows** (`.claude/workflows/`) — deterministic multi-agent scripts:
  fan-out, adversarial verify votes, null-control arms, resumable mid-run. A "3-vote diverse-lens
  panel, pass = ≥2/3 and zero reject" verification discipline is literally a ten-line workflow
  script — cognitive discipline turned mechanical.
- **Worktree isolation** (`isolation: worktree` on agents, or `EnterWorktree`) — each concurrent
  session works an isolated copy of the repo. Removes the whole concurrent-write collision class
  (two sessions editing one state file nearly collided here; the Edit tool's staleness check was
  the last line of defense).

### Time — nothing fires without a human or a session

- **CronCreate** — locally scheduled headless runs. A nightly "what can be cleared right now"
  sweep gives an agent stack the clock it structurally lacks. Governance note: run scheduled
  sessions report-only unless your autonomy rules explicitly cover unattended work.
- **/schedule** — cloud-hosted scheduled routines; **/loop** — self-paced recurrence in-session.

### Reach & presence

- **Notification hook + PushNotification** — the hook fires when a session *blocks* (permission
  wait, idle prompt); PushNotification reaches the phone. A wedged session stops being silent.
- **Statusline** — a persistent terminal readout (state, queue depth, bus-pending) instead of
  status commands you have to remember to run.
- **Artifacts** — publish HTML to claude.ai, private by default, stable URL across redeploys; a
  dashboard your phone can open, republished at every session close.
- **Claude in Chrome** — drives a real browser session; UI-bound workflows become scriptable.
  Check policy before pointing it at corporate systems.

### Plumbing

- **MCP servers** — wrap in-house CLIs as typed first-class tools with schemas instead of shell
  strings. *Deliberately not adopted in this installation* (2026-07-28): the main pain it would
  absorb — shell-quoting fragility — is already handled by `json.dumps`/`-F`-file conventions.
  Revisit if the tools ever need to reach Desktop or claude.ai surfaces.
- **Plugins** — bundle hooks + skills + agents + config into one installable unit. Multi-machine
  drift (hooks present but dead on one box, per-machine settings) is exactly what plugin
  packaging versions away.
- **OpenTelemetry export** (`CLAUDE_CODE_ENABLE_TELEMETRY=1`) — wall-clock, token, and
  tool-latency metrics to a collector. If you've ever hand-built a work timer because an agent has
  no clock between its own turns, this is that dataset for one env var.

### Unused hook events (here)

`UserPromptSubmit` (per-turn context injection/validation), `SessionEnd` (cleanup logging),
`SubagentStop`, `PreCompact` (only the post side is covered here). Flagged verify-first: the
GitHub app / `@claude` on PRs — check the billing model against a no-API-key setup before
touching it.

---

## Part 3 — Adoption order picked here (2026-07-28)

1. **Statusline + Notification→PushNotification** — completes a presence system whose hard half
   (voice, bus, heartbeats) already exists.
2. **Verification panel as a saved workflow** + the lens roles as agent definitions — moves a
   mandatory review discipline from prose to mechanism.
3. **OTel export** — one env var, retires a measurement problem.

Behind those: cron report-only sweeps, plugins for multi-box packaging, worktree isolation.
MCP: scratched by decision (see Part 2).

---

## Part 4 — Scar tissue (Windows-heavy, all real)

- **cp1252 stdout kills processes.** One `→` or emoji in a Python `print` under default Windows
  encoding raises `UnicodeEncodeError` mid-run. `PYTHONIOENCODING=utf-8`, or reconfigure stdout at
  startup, or stay ASCII.
- **The PowerShell tool wraps calls as `-EncodedCommand`** — some AV products block that wholesale
  regardless of payload. Git Bash is the reliable lane for long payloads.
- **MSYS `timeout` cannot kill native Windows exes.** Wall budgets must live in-process; verify
  "stopped" with a `tasklist` re-scan, not with the absence of output. Orphaned `git.exe`
  processes from a timed-out fetch were reaped by hand while writing this.
- **Windows PowerShell 5.1 `>` writes UTF-16LE.** Convert *before* truncating:
  `iconv -f UTF-16LE -t UTF-8 file | head -40`, never `head | iconv` — `head` cuts the byte
  stream mid-character and a byte-swapped decode turns every `##` banner into `⌣⌣` (0x23 0x23
  read big-endian is U+2323: the report literally smiles at you). Or let PowerShell read its own
  dialect: `Get-Content file -TotalCount 40`.
- **The shell eats structured payloads.** Backticks and `<...>` vanish into command substitution;
  heredocs collapse `\\`. Generate JSON with `json.dumps`, pass long text via `-F` files or stdin,
  and validate the *whole* target file after writing, not just your lines.
- **`2>/dev/null` converts diagnosable failures into confident wrong output.** It cost this
  installation a silently-failed `git add` class (now hook-blocked) and, twice while producing
  this very document, an error message that would have explained everything instantly.

---

*Written July 2026 from a live installation; the analyses behind Parts 1–3 were produced in
session with Claude Code itself. The blocking-gate philosophy in Part 1 compresses to one line:
make the wiring refuse what the discipline used to merely discourage.*
