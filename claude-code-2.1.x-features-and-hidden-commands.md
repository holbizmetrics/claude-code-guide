# Claude Code — hidden inputs & newer features (v2.1.x, Opus 4.x era)

*Provenance: extracted from the installed binary `~/.local/bin/claude.exe` **v2.1.162**
(2026-06-04) by string-inspection, plus first-party confirmation from the live tool
surface of an Opus 4.8 Claude Code session. Confidence is marked per item:
**[binary]** = string present in your install · **[first-party]** = confirmed from the
running tool definitions · **[folklore]** = widely repeated but unverified, flagged as such.*

---

## The key distinction (why "ultrathink" feels hidden)

There are **three** kinds of input, and only the first shows up when you press `/`:

1. **Slash commands** — `/clear`, `/config`, … — appear in the `/` autocomplete menu.
2. **Slash commands crowded out of the menu** — still typeable, just not *listed* once
   enough skills/plugins are installed (the menu truncates to save space).
3. **Recognized keywords that are NOT slash commands at all** — typed as ordinary prompt
   text, never `/`-prefixed, so they **never appear in the `/` menu** — yet Claude Code
   recognizes them and acts on them.

**`ultrathink` is category 3, and it's the flagship.** It is *not* a slash command, so
pressing `/` will never show it — but type it anywhere in a prompt and Claude Code
**auto-renders it in animated rainbow text, always.** That rainbow render is the visual
tell that the keyword was recognized. This is the cleanest example of "100% valid but
not announced in the menu."

---

## 1. The keyword-trigger family (category 3 — the must-memorize set)

These are typed as ordinary prompt text — never `/`-prefixed, so they **never appear in the
`/` menu**, yet Claude Code pattern-matches them on input and acts. This is the set you have
to *know*, because nothing in the UI lists them.

### The two real keyword triggers (binary-confirmed in v2.1.162)

| Keyword | What it does | The "tell" | Evidence |
|---|---|---|---|
| **`ultrathink`** | Maximum reasoning budget **for that turn** | **Auto-renders in animated rainbow text, always** — the recognition signal | **[binary]** — `/\bultrathink\b/` regex + `tengu_ultrathink` event in the binary |
| **`ultracode`** | Typed as a **keyword**, opts **that turn** into the **Workflow tool** (auto-orchestration / fan-out to subagents). *Session-wide* xhigh+workflow is the separate `/effort ultracode` path, **not** the keyword. | Emits a system-reminder confirming it was recognized | **[binary]** — `Enable the "ultracode" keyword trigger: including the keyword in a prompt opts that turn into the Workflow tool` |

Both are siblings: identical "type-it-in-a-prompt, not-a-command, not-in-the-menu,
**turn-scoped**" behavior. They differ only in *what* they do — `ultrathink` maxes the
turn's reasoning; `ultracode` opts the turn into Workflow orchestration.

**Toggle:** the ultracode trigger can be disabled via the user setting
`workflowKeywordTriggerEnabled` ("Ultracode keyword trigger", boolean). **[binary]**

### How to invoke (no parameters — they're switches, not functions)

Neither keyword takes arguments. You just make the word appear in an ordinary prompt:

- **`ultrathink`** — type it anywhere in a message (start, middle, or end); matched on a
  word boundary, so *presence* is all that matters. No tunable budget — it's max-or-nothing
  for that turn. Lowercase is the safe form. Confirmation: the rainbow render.
- **`ultracode`** — two ways: (1) the **keyword** in a prompt → opts *that turn* into the
  Workflow tool; (2) **`/effort ultracode`** → sets it for the whole **session** (persistent).
  Confirmation: a system-reminder when recognized.
- **The parameterized path is the slash command, not the keyword:** `/effort <tier>` takes
  `low | medium | high | xhigh | max | ultracode`. The keywords themselves are presence flags.
- The two are **orthogonal** — usable together in one prompt (`ultrathink` = max reasoning,
  `ultracode` = workflow orchestration) — and both are Claude Code (terminal) only.

### These two ARE the whole family — the rest is folklore (binary-verified)

A v2.1.162 string count settles it: `ultrathink` (19 occurrences) and `ultracode` (101) are
the **only** keyword triggers present. **Every other circulating phrase returned 0
occurrences:** `megathink`, `think hard`, `think harder`, `think really hard`, `think super
hard`, `think very hard`, `think intensely`, `think longer`, `keep thinking`, `think
deeply`, `think a lot`, `think more`, `think step by step`, `ultra think` — **all absent.**
So `megathink` and the whole `think …` tier ladder are **NOT recognized triggers in this
version** — they are folklore from older builds / community lists. The exact token-budget
numbers quoted for them online are community reverse-engineering; Claude 4.x uses *adaptive*
thinking that sets depth automatically.

- **Live test:** only a recognized trigger rainbow-renders. If a phrase does not go rainbow
  when you type it, it is not a trigger.
- Keyword triggers are Claude Code (terminal) only — they do nothing in the claude.ai web UI.

### Prompt-prefix modes (recognized, but semi-hinted — not fully hidden)

Typed at the **start** of a message; the input box usually flashes a hint, so these are
semi-discoverable rather than memorize-or-lose:

- **`#` → memory mode** — adds the line to memory (CLAUDE.md). **[binary]** (`memory mode`).
- **`!` → bash mode** — runs the rest of the line as a shell command inline. **[first-party]**

### Unconfirmed — do NOT rely on as "100% valid"

- The **`+500k`-style token-budget directive** is referenced in the agent/workflow tooling
  (first-party), but the literal `+500k` syntax was **not found** as a string in the binary,
  so its status as a typed UI directive is unconfirmed here. **[unconfirmed]**

---

## 2. Newer features (Opus 4.x era) — confirmed present in v2.1.162

All strings below are **[binary]**-confirmed in the install (occurrence counts in parens),
with behavior from **[first-party]** tooling. These are the items most likely *missing*
from older guides.

- **`/effort low|medium|high|xhigh|max|ultracode`** (effort ×771) — set reasoning effort.
  `ultracode` (×117) is the top tier: `xhigh` reasoning **plus automatic workflow
  orchestration** (it fans work out to subagents on substantive tasks). Also settable via
  `effortLevel` in settings.json and exposed to skills as `${CLAUDE_EFFORT}`. **Note:**
  `ultracode` is *also* a typed keyword trigger (just type it in a prompt) — see §1.
- **Dynamic workflows** (dynamic workflow ×93) — the fan-out system: author a script that
  spawns many subagents (parallel/pipeline stages), runs in the background, watch/pause/
  resume via `/workflows`. The engine behind `ultracode`'s auto-orchestration.
- **`/ultraplan <prompt>`** (ultraplan ×273) — cloud distributed planning: draft a plan in
  a remote session, review in the browser, then execute or hand back to the terminal.
- **`/code-review ultra`** (ultrareview ×139) — deep multi-agent review in a cloud sandbox.
  `/ultrareview` is a **deprecated alias** for the same thing. (User-triggered & billed.)
- **`/rewind`** (rewind ×166) — restore the conversation/checkpoint to an earlier state.
- **`/fast`** (fast mode ×154) — toggle Fast mode (faster Opus output, not a smaller model;
  available on Opus 4.6/4.7/4.8).
- **Background tasks** (×47) — long-running commands/agents detached from the turn, with
  completion notifications (the `run_in_background` mechanism + the monitor system).
- **`interleaved-thinking`** (×7) — beta: `claude --betas interleaved-thinking` interleaves
  thinking between tool calls.

---

## 3. Built-in `/` commands (category 1 — these DO appear in the menu)

The clean, cross-checked built-in set (the contrast class to the hidden keywords). Your
own `/help` on a *clean* profile is the authoritative per-install list — a profile with
many skills installed will hide some of these from the dropdown (category 2).

Descriptions below are the **binary's own wording (v2.1.162)** where it exposes one; the
rest are concise accurate summaries.

**Conversation & context**
- `/clear` — clear the conversation and start fresh
- `/compact` — "Free up context by summarizing the conversation so far"
- `/export` — "Export the current conversation to a file or clipboard"
- `/copy` — "Copy Claude's last response to clipboard (or `/copy N` for the Nth-latest)"
- `/rewind` — "Restore the code and/or conversation to a previous point" (checkpoint restore)
- `/resume` — "Resume a previous conversation"
- `/rename` — "Rename the current conversation"
- `/memory` — "Edit Claude memory files" (your CLAUDE.md)

**Inspect & configure**
- `/help` — list commands and help
- `/status` — session / account status
- `/cost` — "Cost of the Claude Code session"
- `/config` — settings (e.g. "Configure the auto-compact window size", break reminders)
- `/model` — view / switch the current model
- `/effort` — set reasoning effort (low = "Fast and efficient for simple tasks", medium =
  "Balanced performance — best for most agents", … up to `ultracode`)
- `/doctor` — "Diagnose and verify your Claude Code installation and settings"
- `/permissions` — "Manage allow & deny tool permission rules"
- `/hooks` — configure hooks · `/mcp` — "Manage MCP servers" · `/agents` — "Manage agent
  configurations" · `/skills` — "List available skills" · `/ide` — "Manage IDE integrations
  and show status"
- `/vim` — vim editing mode · `/terminal-setup` — configure terminal key bindings

**Automation & workflows**
- `/workflows` — "Browse dynamic workflow history (running and completed)"
- `/loop` — "List, create, and delete recurring loops and stop-hooks"
- `/schedule` — "Create and manage scheduled remote Claude Code agents"
- `/ultraplan` — "Claude Code on the web drafts a plan you can edit and approve"
- `/code-review` — review the current diff (`/code-review ultra` = cloud multi-agent)
- `/security-review` — "Complete a security review of the pending changes on the current branch"
- `/fast` — toggle Fast mode (faster Opus output)
- `/btw` — "Ask a quick side question without interrupting the main conversation" *(handy + obscure)*

**Account & setup**
- `/login` · `/logout` — authentication
- `/init` — initialize a project `CLAUDE.md`
- `/install-github-app` — install the GitHub app · `/bug` / `/feedback` — report a bug / feedback
- `/release-notes` — show what changed in recent versions

> **Caveat on "all `/` strings":** the binary bundles the AWS Bedrock SDK and skill/example
> text, so a raw grep for `"/word"` also returns API routes (`/model-invocation-jobs`,
> `/foundation-models`, `/inference-profiles`) and example/skill names (`/babysit-prs`,
> `/claims`, `/morning-checkin`) that are **not** built-in commands. The list above is the
> filtered, real built-in set — not the raw grep.

---

## 4. Verify it yourself (the only true 100%-valid source)

- `/help` — the authoritative built-in command list for *your* install/version.
- Grep your own binary: `grep -aoiE '(ultracode|dynamic workflow|ultraplan|rewind)' ~/.local/bin/claude.exe`
- Official docs (lag behind the binary, but ground-truth for documented items):
  `code.claude.com/docs/en/cli-reference`, `…/commands`, `…/model-config`.

*Compiled 2026-06-04 against Claude Code v2.1.162. The thinking keywords and the `ultracode`/
dynamic-workflow block are the parts most likely absent from pre-4.x guides.*
