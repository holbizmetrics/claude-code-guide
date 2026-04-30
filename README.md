# claude-chat

**One tool for all your Claude Code conversations.**

Zero dependencies. One file. Works everywhere Python 3.7+ runs.

```
python3 claude-chat.py                               # Interactive mode
python3 claude-chat.py list                          # See all your sessions
python3 claude-chat.py search "react hooks"          # Search across everything
python3 claude-chat.py export a7e44ed0 --format html # Export with dark theme
python3 claude-chat.py serve                         # Browse in your browser
python3 claude-chat.py backup --watch                # Continuous backup
python3 claude-chat.py protect                       # Stop auto-deletion
```

## Why

Claude Code stores your conversations as JSONL files in `~/.claude/projects/`. Most people don't know this. Worse: **Claude Code silently deletes sessions after 30 days** by default (the `cleanupPeriodDays` setting has [known bugs](https://simonwillison.net/2025/Jun/14/claude-code-cleanup/) where upgrades reset it).

Your conversations contain ideas, decisions, and code you can't reconstruct. This tool makes them searchable, exportable, and safe.

## Install

```bash
# Just download one file. That's it.
curl -O https://raw.githubusercontent.com/holbizmetrics/claude-code-guide/master/tool/claude-chat.py

# Or clone the whole repo
git clone https://github.com/holbizmetrics/claude-code-guide.git
```

Requirements: Python 3.7+. No pip install. No dependencies.

> **Note:** On Windows, use `python` instead of `python3`.

## Quickstart — 10 things worth knowing

Recipe book. Each tip = what to type, what you get, why it matters.

**1. First run: stop the 30-day auto-delete.**
```
python3 claude-chat.py protect
```
Sets `cleanupPeriodDays: 99999`. One-shot. Do this before anything else.

**2. See what you've been working on.**
```
python3 claude-chat.py
list
```
Enters the REPL, lists recent sessions with `[N]` numbered refs. Every session gets a short-hash and a summary line.

**3. Open any session in your browser — dark theme.**
```
export 1 --format html --open
```
In the REPL, after `list`. `1` is the index from the list; you don't have to copy a hash. Works on a fresh REPL too (auto-populates).

**4. Turn on math, tables, and links.**
```
export 1 --format html --rich --open
```
`--rich` pulls in KaTeX for `$...$` math, renders markdown tables as real HTML tables, and makes URLs clickable. Great for research-heavy sessions.

**5. See what a session *actually did*.**
```
export 1 --format html --rich --diagrams --open
```
`--diagrams` embeds a mermaid sequence diagram of every tool call (Claude → Read → Bash → Edit …). Zoom, pan, and fullscreen buttons for long sessions. This is the single biggest "oh wow" feature.

**6. Find something across *all* your chats.**
```
python3 claude-chat.py search "sobolev spaces"
python3 claude-chat.py search "auth bug" --project myapp
```
Full-text search, shows matching snippets with context. Your personal knowledge base you didn't know you had.

**7. Pull out just the code.**
```
extract 1 --code
```
Every code block from the session. Good when you lost a snippet and don't want to re-read 200 messages to find it.

**8. Pull out just your own messages.**
```
extract 1 --ideas
```
Every user message, chronologically. Works like a journal of what you were thinking.

**9. Browse visually when you don't know which session you want.**
```
python3 claude-chat.py serve
```
Opens a local web UI at `http://127.0.0.1:3456`. Click around sessions, search, read. Localhost only — don't expose it.

**10. Continuous backup in the background.**
```
python3 claude-chat.py backup --watch
```
Runs as a separate process, polls for changes, keeps the last 5 versions of each session. Zero token cost. Survives Claude Code crashes.

**Bonus — in the REPL:** prefix any line with `!` to run a shell command without leaving. `!start file.html` on Windows, `!open file.html` on macOS, `!xdg-open file.html` on Linux.

## Commands

### Interactive mode

Run with no arguments to enter interactive mode:

```
python3 claude-chat.py
```

```
claude-chat v1.0.0 — interactive mode
Type a command (list, search, export, stats, ...) or 'help'. Ctrl+C to exit.

claude-chat> list --limit 5
claude-chat> search "react hooks"
claude-chat> export a7e44ed0 --format html --rich --open
claude-chat> quit
```

No need to retype `python3 claude-chat.py` for every command.

### `list` — See all your sessions

```
python3 claude-chat.py list
python3 claude-chat.py list --project crystal    # Filter by project
python3 claude-chat.py list --limit 100          # Show more
```

Output:
```
  D--MyProject
  ────────────
  a7e44ed0  2026-04-05 23:08  1166KB   0m ago  Let's refactor the auth module
  c6618ffd  2026-04-05 08:38   819KB  14h ago  Fix the deployment pipeline
```

### `search` — Find anything across all conversations

```
python3 claude-chat.py search "sobolev spaces"
python3 claude-chat.py search "database migration" --project myapp
```

Searches all sessions, shows matching snippets with context. Your personal knowledge base you didn't know you had.

### `export` — Save to Markdown, HTML, plain text, or LaTeX

```
python3 claude-chat.py export a7e44ed0                    # Markdown (default)
python3 claude-chat.py export a7e44ed0 --format html      # Dark-themed HTML
python3 claude-chat.py export a7e44ed0 --format html --open  # Export and open
python3 claude-chat.py export a7e44ed0 --format html --rich  # Rich: math, tables, links
python3 claude-chat.py export a7e44ed0 --format tex       # LaTeX
python3 claude-chat.py export a7e44ed0 --format txt       # Plain text
```

HTML export uses a Tokyo Night dark theme with syntax-highlighted code, collapsible tool calls, and print-friendly CSS.

The `--rich` flag adds KaTeX math rendering (`$...$` and `$$...$$`), markdown tables as proper HTML tables, clickable links, and markdown headings.

### `backup` — Protect your conversations

```
python3 claude-chat.py backup                    # One-time backup
python3 claude-chat.py backup --watch            # Continuous watcher
python3 claude-chat.py backup --watch --interval 5  # Poll every 5s
```

The `--watch` mode runs as a separate process, polling for changes. Zero token cost. Survives Claude Code crashes. Keeps the last 5 versions per session.

Backups go to `~/claude-chat-backups/`.

### `stats` — Usage statistics

```
python3 claude-chat.py stats
python3 claude-chat.py stats --project myapp
```

Shows: session count, message counts, tool call frequency, code blocks, models used, largest sessions, project breakdown.

### `extract` — Pull out specific content

```
python3 claude-chat.py extract a7e44ed0 --code       # All code blocks
python3 claude-chat.py extract a7e44ed0 --ideas      # Your messages only
python3 claude-chat.py extract a7e44ed0 --decisions  # Decision points
```

### `serve` — Browse in your browser

```
python3 claude-chat.py serve                     # Opens http://127.0.0.1:3456
python3 claude-chat.py serve --port 8080         # Custom port
python3 claude-chat.py serve --no-open           # Don't auto-open browser
```

Dark-themed web UI with search, clickable sessions, and full conversation view.

> **Security note:** The server has no authentication and binds to localhost only. Do not forward the port or expose it on a network — your conversations may contain sensitive code and credentials.

### `protect` — Stop Claude Code from deleting your sessions

```
python3 claude-chat.py protect
```

Sets `cleanupPeriodDays: 99999` in your Claude Code settings. **Run this first** if you haven't already.

## Use as a library

The `Session`, `Message`, and `ToolCall` classes are importable for building your own tools or GUIs:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("claude_chat", "claude-chat.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sessions = mod.find_all_sessions()
for s in sessions[:5]:
    s.parse()
    print(f"{s.short_id}: {len(s.messages)} messages — {s.summary()}")
    for m in s.user_messages():
        print(f"  You: {m.text[:80]}")
```

## How Claude Code stores conversations

Sessions are JSONL files (one JSON object per line) in:

```
~/.claude/projects/<project-name>/<session-uuid>.jsonl
```

Each line contains a message with role, content, tool calls, and model info. The files grow as you talk — a long session can be 20MB+.

**Subagents** spawned via the `Task` tool get their own transcripts, nested one level deeper:

```
~/.claude/projects/<project-name>/<session-uuid>/subagents/agent-<agent-id>.jsonl
```

`list`, `search`, `extract`, and `export` all reach these too. You can refer to a subagent by its bare `<agent-id>` (the same ID printed by `Task` in the parent session).

## Cookbook

For non-obvious patterns — recovering an overwritten file, diagnosing a subagent that errored early, post-compaction session-self-search, anti-fabrication discipline — see [`tool/COOKBOOK.md`](tool/COOKBOOK.md).

## The Complete Claude Code Guide

This repo also hosts [The Complete Claude Code Guide](https://holbizmetrics.github.io/claude-code-guide/) — 50+ sections covering installation, hooks, memory, subagents, skills, MCP, YOLO mode, Android/Termux, and more.

## License

MIT
