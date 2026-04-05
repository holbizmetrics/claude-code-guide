# claude-chat

**One tool for all your Claude Code conversations.**

Zero dependencies. One file. Works everywhere Python 3.7+ runs.

```
python claude-chat.py list                      # See all your sessions
python claude-chat.py search "react hooks"      # Search across everything
python claude-chat.py export a7e44ed0 --html    # Export with dark theme
python claude-chat.py serve                     # Browse in your browser
python claude-chat.py backup --watch            # Continuous backup
python claude-chat.py protect                   # Stop auto-deletion
```

## Why

Claude Code stores your conversations as JSONL files in `~/.claude/projects/`. Most people don't know this. Worse: **Claude Code silently deletes sessions after 30 days** by default (the `cleanupPeriodDays` setting has [known bugs](https://simonwillison.net/2025/Jun/14/claude-code-cleanup/) where upgrades reset it).

Your conversations contain ideas, decisions, and code you can't reconstruct. This tool makes them searchable, exportable, and safe.

## Install

```bash
# Just download one file. That's it.
curl -O https://raw.githubusercontent.com/holbizmetrics/claude-code-guide/master/claude-chat.py

# Or clone the whole repo
git clone https://github.com/holbizmetrics/claude-code-guide.git
```

Requirements: Python 3.7+. No pip install. No dependencies.

## Commands

### `list` — See all your sessions

```
python claude-chat.py list
python claude-chat.py list --project crystal    # Filter by project
python claude-chat.py list --limit 100          # Show more
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
python claude-chat.py search "sobolev spaces"
python claude-chat.py search "database migration" --project myapp
```

Searches all sessions, shows matching snippets with context. Your personal knowledge base you didn't know you had.

### `export` — Save to Markdown, HTML, plain text, or LaTeX

```
python claude-chat.py export a7e44ed0                    # Markdown (default)
python claude-chat.py export a7e44ed0 --format html      # Dark-themed HTML
python claude-chat.py export a7e44ed0 --format html --open  # Export and open
python claude-chat.py export a7e44ed0 --format tex       # LaTeX
python claude-chat.py export a7e44ed0 --format txt       # Plain text
```

HTML export uses a Tokyo Night dark theme with syntax-highlighted code, collapsible tool calls, and print-friendly CSS.

### `backup` — Protect your conversations

```
python claude-chat.py backup                    # One-time backup
python claude-chat.py backup --watch            # Continuous watcher
python claude-chat.py backup --watch --interval 5  # Poll every 5s
```

The `--watch` mode runs as a separate process, polling for changes. Zero token cost. Survives Claude Code crashes. Keeps the last 5 versions per session.

Backups go to `~/claude-chat-backups/`.

### `stats` — Usage statistics

```
python claude-chat.py stats
python claude-chat.py stats --project myapp
```

Shows: session count, message counts, tool call frequency, code blocks, models used, largest sessions, project breakdown.

### `extract` — Pull out specific content

```
python claude-chat.py extract a7e44ed0 --code       # All code blocks
python claude-chat.py extract a7e44ed0 --ideas      # Your messages only
python claude-chat.py extract a7e44ed0 --decisions  # Decision points
```

### `serve` — Browse in your browser

```
python claude-chat.py serve                     # Opens http://127.0.0.1:3456
python claude-chat.py serve --port 8080         # Custom port
python claude-chat.py serve --no-open           # Don't auto-open browser
```

Dark-themed web UI with search, clickable sessions, and full conversation view.

### `protect` — Stop Claude Code from deleting your sessions

```
python claude-chat.py protect
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

## The Complete Claude Code Guide

This repo also hosts [The Complete Claude Code Guide](https://holbizmetrics.github.io/claude-code-guide/) — 50+ sections covering installation, hooks, memory, subagents, skills, MCP, YOLO mode, Android/Termux, and more.

## License

MIT
