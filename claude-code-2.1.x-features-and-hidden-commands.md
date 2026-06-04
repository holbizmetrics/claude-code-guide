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

## 1. Thinking keywords (category 3 — prompt text, never in the `/` menu)

Escalating reasoning budget. Type the phrase anywhere in your message; it applies to that
turn only.

| Keyword | Tier | Notes |
|---|---|---|
| `think` | basic extended thinking | **[binary/first-party]** |
| `think hard` / `think harder` | more | **[folklore on exact budget]** |
| `megathink` | more still | **[folklore]** — community-named, not in official docs |
| **`ultrathink`** | **maximum** | **[binary]** — rainbow-rendered, the flagship hidden keyword |

- The rainbow render of `ultrathink` is the recognition signal. **[first-party]**
- Token-budget numbers circulated online (~4k … ~32k) are **community reverse-engineering,
  not official**, and Claude 4.x uses *adaptive* thinking that sets depth automatically —
  so treat the ordering as real and the exact numbers as folklore. **[folklore]**
- These are Claude Code (terminal) only; typing them in the claude.ai web UI does nothing.

---

## 2. Newer features (Opus 4.x era) — confirmed present in v2.1.162

All strings below are **[binary]**-confirmed in the install (occurrence counts in parens),
with behavior from **[first-party]** tooling. These are the items most likely *missing*
from older guides.

- **`/effort low|medium|high|xhigh|max|ultracode`** (effort ×771) — set reasoning effort.
  `ultracode` (×117) is the top tier: `xhigh` reasoning **plus automatic workflow
  orchestration** (it fans work out to subagents on substantive tasks). Also settable via
  `effortLevel` in settings.json and exposed to skills as `${CLAUDE_EFFORT}`.
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

`/help` · `/clear` · `/compact` · `/config` · `/cost` · `/doctor` · `/status` · `/init` ·
`/memory` · `/model` · `/permissions` · `/hooks` · `/mcp` · `/agents` · `/skills` ·
`/resume` · `/export` · `/login` · `/logout` · `/bug` · `/vim` · `/terminal-setup` ·
`/release-notes` · and the newer **`/effort` · `/fast` · `/rewind` · `/loop` ·
`/install-github-app` · `/code-review`**.

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
