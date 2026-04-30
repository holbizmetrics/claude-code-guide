# claude-chat cookbook

Patterns that don't fit the README's linear command reference. Each entry: situation → command → why it works.

`--help` tells you what flags exist. This document tells you when to reach for them — and what tricks the tool has accumulated that aren't obvious from the help text.

---

## 1. Recover a file you accidentally overwrote

**Situation:** an `Edit` or `Write` call changed a file, you don't have a backup, but the JSONL has the original content embedded as `old_string`.

```
python3 claude-chat.py export <session> --no-truncate --format md --output <dir>
```

Default export truncates tool inputs at 500 chars (md) / 400 chars (html) so the export stays human-readable. `--no-truncate` preserves them byte-for-byte, so `old_string` round-trips intact. Grep the export for the file path; copy `old_string` straight back to disk.

**Why it works:** tool inputs in the JSONL are byte-perfect. Only the default rendering truncates.

---

## 2. Find what a subagent actually produced

**Situation:** a `Task` subagent ran during a session — you want its output, not the parent's summary of what it returned.

```
python3 claude-chat.py search "<term>"
python3 claude-chat.py extract <agent-id> --code     # or --ideas, --decisions
python3 claude-chat.py export <agent-id> --format md --output <dir>
```

Subagent transcripts live nested one level deeper than primary sessions (see README). `list`/`search`/`extract`/`export` all reach them as if they were primary sessions. The bare `agent-id` (without the `agent-` prefix) works as a short_id — paste it straight from the parent's `Task` output.

**Why it works:** subagents are fully-formed sessions in their own right — same JSONL format, just nested.

---

## 3. Diagnose a subagent that errored before producing output

**Situation:** a subagent returned ambiguous content like "Tool result missing due to internal error". Did it crash early, or get partway through and lose its wrap-up?

```
python3 claude-chat.py search "PRE-REGISTER" --project X       # or any expected protocol marker
python3 claude-chat.py search "<expected-output-token>" --project X
```

Look for **absence**. If the subagent's transcript doesn't contain structural markers your prompt asked for, it errored before the structured-output phase. If it does contain them, the error came later (post-compute, mid-wrap-up).

**Why it works:** search-against-absence is a one-command diagnostic. Hand-pathing into the JSONL would take ten.

**Real example:** in a generator-mode run, three subagents were spawned. Two contained `PRE-REGISTER` (intact). One didn't (errored before producing structured output). One search command, three diagnoses.

---

## 4. Recover prior in-session state after compaction

**Situation:** a long session got auto-compacted. You have a summary but not the full content. You're about to make a decision based on "what we agreed earlier" and you don't fully trust the summary.

```
python3 claude-chat.py export <current-session-id> --format md --output <dir>
grep "<term>" <dir>/claude-chat_<id>_<date>.md
```

The full pre-compaction text is still in the JSONL — compaction only narrows what the *current* model context sees, not what's on disk. Search the source instead of trusting the summary.

**Why it works:** this is the anti-fabrication discipline. When you'd otherwise be tempted to synthesize "what we probably agreed", you have a 30-second alternative: read the source.

---

## 5. Trace a concept across all your work

**Situation:** "where did I first discuss X?" / "every session that touched Y."

```
python3 claude-chat.py search "<concept>"
python3 claude-chat.py search "<concept>" --project <name>
```

Cross-session full-text. Hit counts per session let you find the session where the idea was load-bearing, not just mentioned in passing.

**Why it works:** your conversations are a personal knowledge base. Most people forget they have it.

---

## 6. Audit a session for fabricated tool calls

**Situation:** you (or a model) wrote a result based on a tool call that may not have actually happened.

```
python3 claude-chat.py export <session> --format md --output <dir>
grep "Tool result missing" <dir>/claude-chat_<id>_*.md
grep "<expected-output-string>" <dir>/claude-chat_<id>_*.md
```

Every tool call is in the JSONL with its result (or error). If the claim is "the script returned X", grep the export for the script's actual output. Mismatch = fabrication; absence = the call never ran.

**Why it works:** tool-call results are ground truth. Anything claimed about them can be checked.

---

## 7. Capture a session as a permanent artifact

**Situation:** a session contains work you want preserved beyond Claude Code's 30-day cleanup window.

```
python3 claude-chat.py protect           # one-shot, raises window to 99999d
python3 claude-chat.py backup --watch    # continuous backup process, last 5 versions
python3 claude-chat.py export <session> --format html --rich --diagrams --output <dir>   # archived as a readable doc
```

`protect` raises Claude Code's `cleanupPeriodDays` setting. `backup --watch` is a separate polling process — zero token cost, survives Claude Code crashes. For irreplaceable sessions, also export to HTML — that file lives independent of any tool, viewable in any browser, forever.

**Why it works:** three layers (live session, backup folder, exported HTML) at three independence levels.

---

## Patterns about discipline, not commands

### Search before you synthesize
When you're about to claim something based on "what we agreed earlier" and you're post-compaction, search the export first. Cost: 30 seconds. Avoidance value: the entire fabrication failure mode. Especially relevant for any quoted number, decision, or commitment.

### Subagent absence as signal
A subagent transcript that doesn't contain expected protocol markers diagnoses early-error without reading the JSONL. Make this a routine sanity check when subagents return ambiguous content, before treating their output as "missing" vs "partial".

### Tool inputs are recoverable
Anything ever passed to `Edit`, `Write`, `Bash`, etc. is in the JSONL. File you overwrote? In a JSONL. Command output you lost? In a JSONL. `--no-truncate` is your recovery flag — pre-set it as muscle memory for any file-recovery situation.

### Structural fidelity ≠ numerical fidelity
When verifying claims (yours, a model's, a subagent's), check **values**, not **structure**. A fabricated claim usually has the right shape (same headings, same formatting, same conjecture pattern) because that's all in priors. The numbers won't match the source. So an audit that asks "does this look right?" will pass the fabrication; an audit that asks "do these numbers match the JSONL?" will catch it.

---

## Adding to this cookbook

When you discover a non-obvious pattern that saved you time, add an entry. Each entry is short by design: situation, command, why. If you find yourself writing more than 10 lines of explanation, the underlying tool needs a flag, not a longer recipe.
