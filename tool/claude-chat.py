#!/usr/bin/env python3
"""
claude-chat — One tool for all your Claude Code conversations.

Zero dependencies. One file. Works everywhere Python 3.7+ runs.

Commands:
    list                List all sessions with summaries
    search QUERY        Search across all conversations
    export SESSION_ID   Export a session (--format md/html/txt/tex)
    backup              Backup sessions (--watch for continuous)
    stats               Show usage statistics
    extract SESSION_ID  Extract code blocks, user ideas, or decisions
    serve               Open conversations in your browser
    protect             Prevent Claude Code from deleting old sessions

Examples:
    python claude-chat.py list
    python claude-chat.py list --project crystal
    python claude-chat.py search "sobolev spaces"
    python claude-chat.py export a7e44ed0 --format html --open
    python claude-chat.py backup --watch
    python claude-chat.py serve
    python claude-chat.py stats --project crystal
    python claude-chat.py extract a7e44ed0 --code
    python claude-chat.py protect

Author: Holger Morlok (holbizmetrics)
License: MIT
"""

import argparse
import json
import sys
import re
import time
import shutil
import html as html_mod
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import webbrowser
import shlex

__version__ = "1.0.0"

def _fix_windows_encoding():
    """Fix Windows console encoding (cp1252 can't handle Unicode)."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ─── Configuration ───────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
BACKUP_DIR = Path.home() / "claude-chat-backups"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"

# ─── JSONL Parser ────────────────────────────────────────────────────────────

class Message:
    """A single message in a conversation."""
    __slots__ = ("role", "text", "tool_calls", "thinking", "timestamp", "model")

    def __init__(self, role, text="", tool_calls=None, thinking="", timestamp=None, model=None):
        self.role = role
        self.text = text
        self.tool_calls = tool_calls or []
        self.thinking = thinking
        self.timestamp = timestamp
        self.model = model

    def __repr__(self):
        return f"<Message {self.role}: {self.text[:60]}...>"


class ToolCall:
    """A tool invocation within an assistant message."""
    __slots__ = ("name", "input_data", "result")

    def __init__(self, name, input_data=None, result=None):
        self.name = name
        self.input_data = input_data or {}
        self.result = result

    def summary(self):
        """One-line summary: tool name + key parameter."""
        d = self.input_data
        if self.name in ("Read", "Write", "Edit"):
            fp = d.get("file_path", "")
            if fp:
                return f"{self.name}: {Path(fp).name}"
        elif self.name in ("Bash",):
            cmd = d.get("command", "")
            if cmd:
                short = cmd.split("\n")[0][:80]
                return f"Bash: {short}"
        elif self.name in ("Grep", "Grep_search"):
            pat = d.get("pattern", "")
            if pat:
                return f"Grep: {pat[:60]}"
        elif self.name in ("Glob", "Glob_search"):
            pat = d.get("pattern", "")
            if pat:
                return f"Glob: {pat[:60]}"
        elif self.name in ("Agent",):
            desc = d.get("description", "")
            if desc:
                return f"Agent: {desc[:60]}"
        elif self.name in ("WebFetch",):
            url = d.get("url", "")
            if url:
                return f"WebFetch: {url[:70]}"
        elif self.name in ("WebSearch",):
            q = d.get("query", "")
            if q:
                return f"WebSearch: {q[:60]}"
        elif self.name in ("ToolSearch",):
            q = d.get("query", "")
            if q:
                return f"ToolSearch: {q[:60]}"
        elif self.name in ("Skill",):
            s = d.get("skill", "")
            if s:
                return f"Skill: {s}"
        return self.name


class Session:
    """A parsed Claude Code session."""

    def __init__(self, path):
        self.path = Path(path)
        self.session_id = self.path.stem
        self.short_id = self.session_id[:8]
        self.project = self.path.parent.name
        self.messages = []
        self.model = None
        self._stat = self.path.stat()
        self.modified = datetime.fromtimestamp(self._stat.st_mtime)
        self.size = self._stat.st_size
        self._parsed = False

    def parse(self):
        """Parse the JSONL file into messages."""
        if self._parsed:
            return
        self._parsed = True

        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_data = obj.get("message", obj)
                    role = msg_data.get("role", obj.get("type", ""))

                    if role == "user":
                        text = self._extract_text(msg_data.get("content", ""))
                        if text and "<system-reminder>" not in text:
                            self.messages.append(Message("user", text))

                    elif role == "assistant":
                        content = msg_data.get("content", [])
                        if not self.model:
                            self.model = msg_data.get("model", None)

                        text_parts = []
                        tool_calls = []
                        thinking = ""

                        if isinstance(content, str):
                            text_parts.append(content)
                        elif isinstance(content, list):
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                btype = block.get("type", "")
                                if btype == "text":
                                    text_parts.append(block.get("text", ""))
                                elif btype == "tool_use":
                                    tc = ToolCall(
                                        block.get("name", "unknown"),
                                        block.get("input", {})
                                    )
                                    tool_calls.append(tc)
                                elif btype == "thinking":
                                    thinking = block.get("thinking", "")

                        text = "\n".join(text_parts).strip()
                        if text or tool_calls:
                            m = Message("assistant", text, tool_calls, thinking, model=self.model)
                            self.messages.append(m)

        except (IOError, OSError):
            pass

    def _extract_text(self, content):
        """Extract text from user message content (string or list)."""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text":
                        t = c.get("text", "")
                        if '"tool_result"' not in t[:50] and t.strip()[:15] != "Launching skill":
                            parts.append(t)
            return "\n".join(parts).strip()
        return ""

    def summary(self, max_len=100):
        """Get a one-line summary (first meaningful user message). Fast: reads first ~50 lines only."""
        if self._parsed:
            for m in self.messages:
                if m.role == "user" and len(m.text) > 5:
                    clean = m.text.replace("\n", " ").replace("\r", " ")
                    clean = re.sub(r"\s+", " ", clean).strip()
                    return clean[:max_len] + "..." if len(clean) > max_len else clean
            return "(empty session)"

        # Fast path: scan first ~50 lines without full parse
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i > 50:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg_data = obj.get("message", obj)
                    role = msg_data.get("role", obj.get("type", ""))
                    if role == "user":
                        text = self._extract_text(msg_data.get("content", ""))
                        if text and len(text) > 5 and "<system-reminder>" not in text:
                            clean = text.replace("\n", " ").replace("\r", " ")
                            clean = re.sub(r"\s+", " ", clean).strip()
                            return clean[:max_len] + "..." if len(clean) > max_len else clean
        except (IOError, OSError):
            pass
        return "(empty session)"

    def user_messages(self):
        """Get only user messages."""
        self.parse()
        return [m for m in self.messages if m.role == "user" and len(m.text) > 5]

    def assistant_messages(self):
        """Get only assistant messages."""
        self.parse()
        return [m for m in self.messages if m.role == "assistant" and len(m.text) > 5]

    def all_text(self):
        """Get all text content concatenated (for search)."""
        self.parse()
        return "\n".join(m.text for m in self.messages if m.text)

    def code_blocks(self):
        """Extract all code blocks from the conversation."""
        self.parse()
        blocks = []
        for m in self.messages:
            if not m.text:
                continue
            for match in re.finditer(r"```(\w*)\n(.*?)```", m.text, re.DOTALL):
                lang = match.group(1) or "text"
                code = match.group(2).strip()
                blocks.append({"lang": lang, "code": code, "role": m.role})
        return blocks

    def message_count(self):
        """Quick message count without full parse."""
        count = 0
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"role":"user"' in line or '"role":"assistant"' in line:
                        count += 1
        except (IOError, OSError):
            pass
        return count


# ─── Session Discovery ───────────────────────────────────────────────────────

def find_all_sessions(project_filter=None):
    """Find all JSONL session files across all projects."""
    sessions = []
    if not PROJECTS_DIR.exists():
        return sessions
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        if project_filter and project_filter.lower() not in project_dir.name.lower():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
            try:
                if jsonl.stat().st_size > 100:  # skip tiny/empty files
                    sessions.append(Session(jsonl))
            except (FileNotFoundError, OSError):
                continue  # file deleted between glob and stat
    sessions.sort(key=lambda s: s.modified, reverse=True)
    return sessions


def find_session(session_id):
    """Find a specific session by ID (full or short)."""
    for s in find_all_sessions():
        if s.session_id == session_id or s.short_id == session_id:
            return s
    return None


# ─── Commands ────────────────────────────────────────────────────────────────

def _session_preview(session, max_msgs=4):
    """Get a list of preview lines showing what the session was about."""
    session.parse()
    previews = []
    seen_first = False
    for m in session.messages:
        if m.role != "user" or len(m.text) <= 5:
            continue
        text = m.text.replace("\n", " ").replace("\r", " ")
        text = re.sub(r"\s+", " ", text).strip()
        # Skip the boot/first message (already shown as summary)
        if not seen_first:
            seen_first = True
            continue
        # Skip boot skill invocations
        if text.startswith("Boot Prometheus") or text.startswith("Base directory for this skill"):
            continue
        if len(text) > 90:
            text = text[:90] + "..."
        previews.append(text)
        if len(previews) >= max_msgs:
            break
    return previews


def cmd_list(args):
    """List all sessions with summaries."""
    sessions = find_all_sessions(args.project)
    if not sessions:
        print("No sessions found.")
        return

    limit = args.limit or 20
    detail = getattr(args, "detail", False)
    current_project = None

    for s in sessions[:limit]:
        if s.project != current_project:
            current_project = s.project
            print(f"\n  {current_project}")
            print(f"  {'─' * min(60, len(current_project))}")

        age = datetime.now() - s.modified
        if age.days > 0:
            age_str = f"{age.days}d ago"
        elif age.seconds > 3600:
            age_str = f"{age.seconds // 3600}h ago"
        else:
            age_str = f"{age.seconds // 60}m ago"

        size_kb = s.size / 1024
        summary = s.summary(80)
        print(f"  {s.short_id}  {s.modified.strftime('%Y-%m-%d %H:%M')}  {size_kb:6.0f}KB  {age_str:>8}  {summary}")

        if detail:
            previews = _session_preview(s)
            for p in previews:
                print(f"              > {p}")
            if previews:
                print()

    total = len(sessions)
    if total > limit:
        print(f"\n  ... and {total - limit} more. Use --limit {total} to see all.")
    print(f"\n  Total: {total} sessions across {len(set(s.project for s in sessions))} project(s)")


def cmd_search(args):
    """Search across all conversations."""
    query = args.query.lower()
    sessions = find_all_sessions(args.project)
    results = []

    for s in sessions:
        try:
            s.parse()
            contexts = []
            count = 0
            for m in s.messages:
                if m.text and query in m.text.lower():
                    count += m.text.lower().count(query)
                    idx = m.text.lower().index(query)
                    start = max(0, idx - 40)
                    end = min(len(m.text), idx + len(query) + 40)
                    snippet = m.text[start:end].replace("\n", " ")
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(m.text):
                        snippet = snippet + "..."
                    contexts.append((m.role, snippet))
            if count > 0:
                results.append((s, count, contexts))
        except (IOError, OSError):
            continue

    if not results:
        print(f'No results for "{args.query}"')
        return

    results.sort(key=lambda r: r[1], reverse=True)
    print(f'Found "{args.query}" in {len(results)} session(s):\n')

    for s, count, contexts in results[:args.limit or 20]:
        print(f"  {s.short_id}  {s.modified.strftime('%Y-%m-%d %H:%M')}  {count} matches  [{s.project}]")
        for role, snippet in contexts[:3]:
            role_tag = "YOU" if role == "user" else "AI "
            print(f"    {role_tag}: {snippet}")
        if len(contexts) > 3:
            print(f"    ... and {len(contexts) - 3} more matches")
        print()


def cmd_export(args):
    """Export a session to various formats."""
    session = find_session(args.session_id)
    if not session:
        print(f"Session not found: {args.session_id}")
        print("Use 'claude-chat.py list' to see available sessions.")
        return

    session.parse()
    fmt = args.format or "md"
    out_dir = Path(args.output) if args.output else Path(".")

    if fmt == "md":
        content = export_markdown(session)
        ext = ".md"
    elif fmt == "html":
        content = export_html(session, rich=getattr(args, "rich", False))
        ext = ".html"
    elif fmt == "txt":
        content = export_txt(session)
        ext = ".txt"
    elif fmt == "tex":
        content = export_tex(session)
        ext = ".tex"
    else:
        print(f"Unknown format: {fmt}. Use: md, html, txt, tex")
        return

    filename = f"claude-chat_{session.short_id}_{session.modified.strftime('%Y%m%d')}{ext}"
    out_path = out_dir / filename

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Exported to: {out_path}")

    if args.open:
        webbrowser.open(str(out_path.resolve()))


def cmd_backup(args):
    """Backup sessions with optional watch mode."""
    backup_dir = Path(args.output) if args.output else BACKUP_DIR
    sessions = find_all_sessions(args.project)

    if args.watch:
        print(f"=== Claude Chat Backup Watcher ===")
        print(f"Backup dir:    {backup_dir}")
        print(f"Poll interval: {args.interval}s")
        print(f"Projects:      {len(set(s.project for s in sessions))}")
        print(f"\nInitial backup...")

    file_states = {}
    backed_up = 0

    def do_backup():
        nonlocal backed_up
        count = 0
        for s in find_all_sessions(args.project):
            key = str(s.path)
            current = (s.size, s._stat.st_mtime)
            if key not in file_states or file_states[key] != current:
                file_states[key] = current
                project_backup = backup_dir / s.project
                project_backup.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = project_backup / f"{s.short_id}_{ts}.jsonl"
                shutil.copy2(s.path, dest)
                size_kb = dest.stat().st_size / 1024
                print(f"  [BACKUP] {s.short_id} -> {dest.name} ({size_kb:.0f} KB)")

                # Prune old backups
                old = sorted(project_backup.glob(f"{s.short_id}_*.jsonl"),
                             key=lambda f: f.stat().st_mtime, reverse=True)
                for f in old[5:]:
                    f.unlink()
                count += 1
                backed_up += 1
        return count

    do_backup()
    print(f"  {backed_up} session(s) backed up to {backup_dir}")

    if args.watch:
        print(f"\nWatching for changes (Ctrl+C to stop)...\n")
        try:
            while True:
                time.sleep(args.interval)
                n = do_backup()
                if n:
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {n} file(s) updated")
        except KeyboardInterrupt:
            print(f"\nStopped. Total backed up: {backed_up}")


def cmd_stats(args):
    """Show usage statistics."""
    sessions = find_all_sessions(args.project)
    if not sessions:
        print("No sessions found.")
        return

    total_size = sum(s.size for s in sessions)
    projects = set(s.project for s in sessions)

    # Parse a sample for deeper stats
    total_user_msgs = 0
    total_asst_msgs = 0
    total_tool_calls = 0
    total_code_blocks = 0
    models_used = {}
    oldest = min(s.modified for s in sessions)
    newest = max(s.modified for s in sessions)

    print(f"Analyzing {len(sessions)} sessions...")
    for s in sessions:
        s.parse()
        for m in s.messages:
            if m.role == "user":
                total_user_msgs += 1
            elif m.role == "assistant":
                total_asst_msgs += 1
                total_tool_calls += len(m.tool_calls)
        total_code_blocks += len(s.code_blocks())
        if s.model:
            models_used[s.model] = models_used.get(s.model, 0) + 1

    days_span = max(1, (newest - oldest).days)

    print(f"\n{'=' * 50}")
    print(f"  Claude Code Chat Statistics")
    print(f"{'=' * 50}")
    print(f"  Sessions:        {len(sessions)}")
    print(f"  Projects:        {len(projects)}")
    print(f"  Date range:      {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')} ({days_span} days)")
    print(f"  Total size:      {total_size / (1024*1024):.1f} MB")
    print(f"  Avg session:     {total_size / (1024 * len(sessions)):.0f} KB")
    print(f"")
    print(f"  Your messages:   {total_user_msgs}")
    print(f"  AI responses:    {total_asst_msgs}")
    print(f"  Tool calls:      {total_tool_calls}")
    print(f"  Code blocks:     {total_code_blocks}")
    print(f"  Msgs/day:        {(total_user_msgs + total_asst_msgs) / days_span:.1f}")
    print(f"  Sessions/day:    {len(sessions) / days_span:.1f}")

    if models_used:
        print(f"\n  Models:")
        for model, count in sorted(models_used.items(), key=lambda x: -x[1]):
            print(f"    {model}: {count} session(s)")

    # Top sessions by size
    print(f"\n  Largest sessions:")
    for s in sorted(sessions, key=lambda s: s.size, reverse=True)[:5]:
        print(f"    {s.short_id}  {s.size/1024:.0f}KB  {s.modified.strftime('%Y-%m-%d')}  {s.summary(50)}")

    # Project breakdown
    print(f"\n  Projects:")
    for p in sorted(projects):
        p_sessions = [s for s in sessions if s.project == p]
        p_size = sum(s.size for s in p_sessions)
        print(f"    {p[:50]}  {len(p_sessions)} sessions  {p_size/(1024*1024):.1f}MB")


def cmd_extract(args):
    """Extract specific content from a session."""
    session = find_session(args.session_id)
    if not session:
        print(f"Session not found: {args.session_id}")
        return

    session.parse()

    if args.code:
        blocks = session.code_blocks()
        if not blocks:
            print("No code blocks found.")
            return
        print(f"Found {len(blocks)} code block(s):\n")
        for i, b in enumerate(blocks, 1):
            who = "You" if b["role"] == "user" else "AI"
            print(f"--- Block {i} ({b['lang']}, {who}) ---")
            print(b["code"])
            print()

    elif args.ideas:
        print(f"Your messages in session {session.short_id}:\n")
        for m in session.user_messages():
            clean = m.text.strip()
            if len(clean) > 10:
                print(f"  > {clean[:300]}")
                if len(clean) > 300:
                    print(f"    [...{len(clean)} chars]")
                print()

    elif args.decisions:
        # Search for decision-like patterns
        patterns = [
            r"(?i)(let'?s? go with|decided|decision|chose|picking|option \d|we('ll| will) use)",
            r"(?i)(the plan is|approach:|strategy:|going with|settled on)",
        ]
        print(f"Decisions in session {session.short_id}:\n")
        found = 0
        for m in session.messages:
            if not m.text:
                continue
            for pat in patterns:
                for match in re.finditer(pat, m.text):
                    start = max(0, match.start() - 30)
                    end = min(len(m.text), match.end() + 100)
                    snippet = m.text[start:end].replace("\n", " ")
                    who = "You" if m.role == "user" else "AI"
                    print(f"  [{who}] ...{snippet}...")
                    found += 1
                    break
        if not found:
            print("  No explicit decisions found.")

    else:
        print("Specify what to extract: --code, --ideas, or --decisions")


def cmd_serve(args):
    """Start a local web server to browse conversations."""
    port = args.port or 3456

    class ChatHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *a):
            pass  # suppress request logs

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/" or path == "":
                self._serve_index(query)
            elif path.startswith("/session/"):
                session_id = path.split("/session/")[1].strip("/")
                self._serve_session(session_id)
            elif path == "/search":
                self._serve_search(query)
            else:
                self.send_error(404)

        def _send_html(self, html_content):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))

        def _serve_index(self, query):
            project_filter = query.get("project", [None])[0]
            sessions = find_all_sessions(project_filter)

            rows = []
            for s in sessions:
                summary_text = html_mod.escape(s.summary(120))
                size_kb = s.size / 1024
                rows.append(f"""
                <tr onclick="window.location='/session/{s.short_id}'" style="cursor:pointer">
                    <td class="mono">{s.short_id}</td>
                    <td>{s.modified.strftime('%Y-%m-%d %H:%M')}</td>
                    <td>{size_kb:.0f} KB</td>
                    <td class="project">{html_mod.escape(s.project[:40])}</td>
                    <td>{summary_text}</td>
                </tr>""")

            page = WEB_TEMPLATE_INDEX.replace("{{ROWS}}", "\n".join(rows))
            page = page.replace("{{COUNT}}", str(len(sessions)))
            page = page.replace("{{PROJECTS}}", str(len(set(s.project for s in sessions))))
            self._send_html(page)

        def _serve_session(self, session_id):
            session = find_session(session_id)
            if not session:
                self.send_error(404, f"Session not found: {session_id}")
                return
            session.parse()
            html_content = export_html(session, embedded=True)
            self._send_html(html_content)

        def _serve_search(self, query):
            q = query.get("q", [""])[0]
            if not q:
                self._send_html("<html><body>No query</body></html>")
                return

            sessions = find_all_sessions()
            results = []
            for s in sessions:
                try:
                    with open(s.path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if q.lower() in content.lower():
                        count = content.lower().count(q.lower())
                        results.append((s, count))
                except (IOError, OSError):
                    continue

            results.sort(key=lambda r: r[1], reverse=True)
            rows = []
            for s, count in results[:50]:
                summary_text = html_mod.escape(s.summary(100))
                rows.append(f"""
                <tr onclick="window.location='/session/{s.short_id}'" style="cursor:pointer">
                    <td class="mono">{s.short_id}</td>
                    <td>{count} hits</td>
                    <td>{s.modified.strftime('%Y-%m-%d %H:%M')}</td>
                    <td>{summary_text}</td>
                </tr>""")

            page = WEB_TEMPLATE_SEARCH.replace("{{ROWS}}", "\n".join(rows))
            page = page.replace("{{QUERY}}", html_mod.escape(q))
            page = page.replace("{{COUNT}}", str(len(results)))
            self._send_html(page)

    try:
        server = HTTPServer(("127.0.0.1", port), ChatHandler)
    except OSError as e:
        if "address already in use" in str(e).lower() or getattr(e, "errno", 0) == 10048:
            print(f"Port {port} is already in use. Try: claude-chat serve --port {port + 1}")
            return
        raise

    url = f"http://127.0.0.1:{port}"
    print(f"Claude Chat Browser running at {url}")
    print("Note: No authentication. Do not expose this port on a network.")
    print("Press Ctrl+C to stop.\n")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


def cmd_protect(args):
    """Prevent Claude Code from auto-deleting old sessions."""
    if not SETTINGS_FILE.exists():
        settings = {}
    else:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)

    current = settings.get("cleanupPeriodDays")
    if current and current >= 99999:
        print(f"Already protected (cleanupPeriodDays = {current}).")
        return

    if current:
        print(f"WARNING: Current cleanupPeriodDays = {current}")
        print(f"Sessions older than {current} days will be DELETED by Claude Code.")

    settings["cleanupPeriodDays"] = 99999

    # Atomic write: write to temp file, then rename (prevents corruption on crash)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    tmp.replace(SETTINGS_FILE)

    print(f"Protected. Set cleanupPeriodDays = 99999 in {SETTINGS_FILE}")
    print("Your sessions will no longer be auto-deleted.")


# ─── Export Formatters ───────────────────────────────────────────────────────

def export_markdown(session):
    """Export session as Markdown."""
    lines = [
        f"# Claude Code Session: {session.short_id}",
        f"",
        f"**Date:** {session.modified.strftime('%Y-%m-%d %H:%M')}  ",
        f"**Project:** {session.project}  ",
        f"**Model:** {session.model or 'unknown'}  ",
        f"**Size:** {session.size / 1024:.0f} KB  ",
        f"",
        f"---",
        f"",
    ]

    for m in session.messages:
        if not m.text and not m.tool_calls:
            continue

        if m.role == "user":
            lines.append(f"## You\n")
            lines.append(m.text)
            lines.append("")
        elif m.role == "assistant":
            lines.append(f"## Claude\n")
            if m.text:
                lines.append(m.text)
            for tc in m.tool_calls:
                input_str = json.dumps(tc.input_data, indent=2)[:500]
                lines.append(f"\n<details><summary>Tool: {tc.summary()}</summary>\n")
                lines.append(f"```json\n{input_str}\n```")
                lines.append(f"</details>\n")
            lines.append("")

    lines.append(f"\n---\n*Exported with claude-chat v{__version__}*\n")
    return "\n".join(lines)


def export_txt(session):
    """Export session as plain text."""
    lines = [
        f"Claude Code Session: {session.short_id}",
        f"Date: {session.modified.strftime('%Y-%m-%d %H:%M')}",
        f"Project: {session.project}",
        f"Model: {session.model or 'unknown'}",
        f"{'=' * 60}",
        "",
    ]

    for m in session.messages:
        if not m.text:
            continue
        tag = "YOU" if m.role == "user" else "CLAUDE"
        lines.append(f"[{tag}]")
        lines.append(m.text)
        lines.append("")
        lines.append("-" * 40)
        lines.append("")

    return "\n".join(lines)


def export_tex(session):
    """Export session as LaTeX."""
    def tex_escape(text):
        # Single-pass replacement to avoid double-escaping (backslash must not
        # be replaced sequentially after other replacements introduce backslashes)
        conv = {
            "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
            "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\^{}",
        }
        pattern = re.compile("|".join(re.escape(k) for k in conv))
        return pattern.sub(lambda m: conv[m.group()], text)

    lines = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{listings}",
        r"\usepackage[margin=2.5cm]{geometry}",
        r"\usepackage{xcolor}",
        r"\definecolor{usercolor}{RGB}{0,100,200}",
        r"\definecolor{aicolor}{RGB}{100,100,100}",
        r"\lstset{basicstyle=\ttfamily\small,breaklines=true,frame=single,backgroundcolor=\color{gray!10}}",
        r"",
        r"\title{Claude Code Session: " + tex_escape(session.short_id) + r"}",
        r"\date{" + session.modified.strftime('%Y-%m-%d %H:%M') + r"}",
        r"\author{Project: " + tex_escape(session.project[:40]) + r"}",
        r"",
        r"\begin{document}",
        r"\maketitle",
        r"",
    ]

    for m in session.messages:
        if not m.text:
            continue

        if m.role == "user":
            lines.append(r"\subsection*{\textcolor{usercolor}{You}}")
        else:
            lines.append(r"\subsection*{\textcolor{aicolor}{Claude}}")

        # Handle code blocks specially
        parts = re.split(r"(```\w*\n.*?```)", m.text, flags=re.DOTALL)
        for part in parts:
            code_match = re.match(r"```(\w*)\n(.*?)```", part, re.DOTALL)
            if code_match:
                lang = code_match.group(1) or "text"
                code = code_match.group(2)
                lines.append(r"\begin{lstlisting}[language=" + lang + "]")
                lines.append(code)
                lines.append(r"\end{lstlisting}")
            else:
                if part.strip():
                    lines.append(tex_escape(part.strip()))
                    lines.append("")

    lines.append(r"\end{document}")
    return "\n".join(lines)


def _md_table_to_html(text):
    """Convert markdown tables to HTML tables."""
    lines = text.split("\n")
    result = []
    table_lines = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        # Detect table row: starts/ends with | and has content
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
            table_lines.append(stripped)
            in_table = True
        else:
            if in_table and table_lines:
                result.append(_render_table(table_lines))
                table_lines = []
                in_table = False
            result.append(line)

    if table_lines:
        result.append(_render_table(table_lines))

    return "\n".join(result)


def _render_table(lines):
    """Render collected markdown table lines as HTML."""
    if len(lines) < 2:
        return "\n".join(lines)

    rows = []
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Skip separator row (---|---|---)
        if all(re.match(r"^:?-+:?$", c.strip()) for c in cells if c.strip()):
            continue
        rows.append(cells)

    if not rows:
        return "\n".join(lines)

    html = '<table class="md-table">'
    # First row is header
    html += "<thead><tr>"
    for cell in rows[0]:
        html += f"<th>{cell}</th>"
    html += "</tr></thead><tbody>"
    for row in rows[1:]:
        html += "<tr>"
        for cell in row:
            html += f"<td>{cell}</td>"
        html += "</tr>"
    html += "</tbody></table>"
    return html


def _auto_link_urls(text):
    """Convert plain URLs to clickable links (skip already-linked ones)."""
    return re.sub(
        r'(?<!href=")(?<!src=")(https?://[^\s<>")\]]+)',
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        text
    )


def export_html(session, embedded=False, rich=False):
    """Export session as HTML with dark theme."""
    messages_html = []

    for m in session.messages:
        if not m.text and not m.tool_calls:
            continue

        role_class = "user" if m.role == "user" else "assistant"
        role_label = "You" if m.role == "user" else "Claude"

        # Process text: escape HTML, then restore code blocks
        if m.text:
            text = html_mod.escape(m.text)
            # Restore code blocks with syntax highlighting
            def code_replacer(match):
                lang = match.group(1)
                code = match.group(2)
                return f'<pre><code class="language-{lang}">{code}</code></pre>'
            text = re.sub(
                r"```(\w*)\n(.*?)```",
                code_replacer,
                text,
                flags=re.DOTALL
            )

            if rich:
                # Markdown tables → HTML tables (before <br> conversion)
                text = _md_table_to_html(text)
                # Markdown headings
                text = re.sub(r"^(#{1,6})\s+(.+)$", lambda m: f'<h{len(m.group(1))} class="md-heading">{m.group(2)}</h{len(m.group(1))}>', text, flags=re.MULTILINE)
                # Math: $$...$$ display math (before inline to avoid conflicts)
                text = re.sub(r"\$\$(.+?)\$\$", r'<span class="katex-display">\1</span>', text, flags=re.DOTALL)
                # Math: $...$ inline math (not preceded/followed by space+digit pattern that looks like prices)
                text = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", r'<span class="katex-inline">\1</span>', text)

            # Convert markdown bold/italic
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            # Convert newlines to <br> (outside of pre blocks)
            text = re.sub(r"\n(?!<)", "<br>\n", text)

            if rich:
                # Auto-link URLs (after all other processing)
                text = _auto_link_urls(text)
        else:
            text = ""

        # Tool calls
        tools_html = ""
        if m.tool_calls:
            for tc in m.tool_calls:
                input_preview = json.dumps(tc.input_data, indent=2)[:400]
                tools_html += f"""
                <details class="tool-call">
                    <summary>{html_mod.escape(tc.summary())}</summary>
                    <pre>{html_mod.escape(input_preview)}</pre>
                </details>"""

        messages_html.append(f"""
        <div class="message {role_class}">
            <div class="role-label">{role_label}</div>
            <div class="content">{text}{tools_html}</div>
        </div>""")

    nav = ""
    if embedded:
        nav = '<div class="nav"><a href="/">Back to all sessions</a></div>'

    rich_head = ""
    rich_foot = ""
    if rich:
        rich_head = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<style>
.md-table { border-collapse: collapse; margin: 10px 0; width: auto; }
.md-table th, .md-table td {
    border: 1px solid var(--border); padding: 6px 12px; text-align: left;
}
.md-table th { background: var(--code-bg); color: var(--accent); font-size: 0.85em; }
.md-table td { font-size: 0.9em; }
.md-table tr:hover { background: var(--surface2); }
.md-heading { color: var(--accent); margin: 12px 0 6px 0; }
h2.md-heading { font-size: 1.2em; }
h3.md-heading { font-size: 1.1em; }
h4.md-heading { font-size: 1.0em; }
.content a { color: var(--accent); text-decoration: underline; }
.content a:hover { color: var(--green); }
.katex-display { display: block; text-align: center; margin: 12px 0; }
</style>"""
        rich_foot = """
<script>
document.addEventListener("DOMContentLoaded", function() {
    document.querySelectorAll(".katex-display").forEach(function(el) {
        try { katex.render(el.textContent, el, {displayMode: true, throwOnError: false}); } catch(e) {}
    });
    document.querySelectorAll(".katex-inline").forEach(function(el) {
        try { katex.render(el.textContent, el, {displayMode: false, throwOnError: false}); } catch(e) {}
    });
});
</script>"""

    result = HTML_TEMPLATE.replace("{{MESSAGES}}", "\n".join(messages_html)) \
        .replace("{{SESSION_ID}}", session.short_id) \
        .replace("{{DATE}}", session.modified.strftime("%Y-%m-%d %H:%M")) \
        .replace("{{PROJECT}}", html_mod.escape(session.project)) \
        .replace("{{MODEL}}", html_mod.escape(session.model or "unknown")) \
        .replace("{{SIZE}}", f"{session.size / 1024:.0f} KB") \
        .replace("{{MSG_COUNT}}", str(len(session.messages))) \
        .replace("{{NAV}}", nav) \
        .replace("{{RICH_HEAD}}", rich_head) \
        .replace("{{RICH_FOOT}}", rich_foot)
    return result


# ─── HTML Templates ──────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Chat: {{SESSION_ID}}</title>
{{RICH_HEAD}}
<style>
:root {
    --bg: #1a1b26; --surface: #24283b; --surface2: #414868;
    --text: #c0caf5; --text-dim: #565f89; --accent: #7aa2f7;
    --user-bg: #1e3a5f; --ai-bg: #1a1b26;
    --green: #9ece6a; --red: #f7768e; --yellow: #e0af68;
    --border: #3b4261; --code-bg: #1f2335;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: var(--bg); color: var(--text);
    line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px;
}
.header {
    border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 20px;
}
.header h1 { color: var(--accent); font-size: 1.4em; }
.header .meta { color: var(--text-dim); font-size: 0.85em; margin-top: 5px; }
.header .meta span { margin-right: 15px; }
.nav { margin-bottom: 15px; }
.nav a { color: var(--accent); text-decoration: none; }
.nav a:hover { text-decoration: underline; }
.message { padding: 15px; margin-bottom: 10px; border-radius: 8px; border-left: 3px solid transparent; }
.message.user { background: var(--user-bg); border-left-color: var(--accent); }
.message.assistant { background: var(--surface); border-left-color: var(--green); }
.role-label {
    font-size: 0.75em; font-weight: bold; text-transform: uppercase;
    color: var(--text-dim); margin-bottom: 8px; letter-spacing: 0.5px;
}
.message.user .role-label { color: var(--accent); }
.message.assistant .role-label { color: var(--green); }
.content { font-size: 0.95em; word-wrap: break-word; }
pre {
    background: var(--code-bg); padding: 12px; border-radius: 6px;
    overflow-x: auto; margin: 10px 0; border: 1px solid var(--border);
    font-size: 0.85em;
}
code { font-family: 'Fira Code', 'Consolas', monospace; }
.tool-call { margin: 8px 0; }
.tool-call summary {
    cursor: pointer; color: var(--yellow); font-family: monospace;
    font-size: 0.85em; padding: 4px 8px; background: var(--code-bg);
    border-radius: 4px; display: inline-block;
}
.tool-call pre { font-size: 0.8em; margin-top: 5px; }
strong { color: var(--accent); }
.footer {
    margin-top: 30px; padding-top: 15px; border-top: 1px solid var(--border);
    color: var(--text-dim); font-size: 0.8em; text-align: center;
}
@media print {
    body { background: white; color: black; }
    .message.user { background: #f0f4ff; border-left-color: #0066cc; }
    .message.assistant { background: #f8f8f8; border-left-color: #00aa44; }
    pre { background: #f5f5f5; border-color: #ddd; }
}
</style>
</head>
<body>
{{NAV}}
<div class="header">
    <h1>Session {{SESSION_ID}}</h1>
    <div class="meta">
        <span>{{DATE}}</span>
        <span>{{PROJECT}}</span>
        <span>{{MODEL}}</span>
        <span>{{SIZE}}</span>
        <span>{{MSG_COUNT}} messages</span>
    </div>
</div>
{{MESSAGES}}
<div class="footer">Exported with claude-chat v""" + __version__ + """</div>
{{RICH_FOOT}}
</body>
</html>"""

WEB_TEMPLATE_INDEX = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Chat Browser</title>
<style>
:root {
    --bg: #1a1b26; --surface: #24283b; --text: #c0caf5;
    --text-dim: #565f89; --accent: #7aa2f7; --border: #3b4261;
    --green: #9ece6a; --hover: #2a2e4a;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: var(--bg); color: var(--text); padding: 20px;
}
.header { text-align: center; margin-bottom: 25px; }
.header h1 { color: var(--accent); font-size: 1.6em; }
.header .stats { color: var(--text-dim); margin-top: 5px; }
.search-bar {
    max-width: 600px; margin: 0 auto 25px auto; display: flex; gap: 8px;
}
.search-bar input {
    flex: 1; padding: 10px 15px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); font-size: 1em; outline: none;
}
.search-bar input:focus { border-color: var(--accent); }
.search-bar button {
    padding: 10px 20px; background: var(--accent); color: var(--bg);
    border: none; border-radius: 6px; cursor: pointer; font-weight: bold;
}
table { width: 100%; border-collapse: collapse; max-width: 1200px; margin: 0 auto; }
th { text-align: left; padding: 8px 12px; color: var(--text-dim); font-size: 0.8em;
     text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 0.9em; }
tr:hover { background: var(--hover); }
.mono { font-family: 'Fira Code', monospace; color: var(--accent); font-size: 0.85em; }
.project { color: var(--text-dim); font-size: 0.8em; max-width: 200px;
           overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
</head>
<body>
<div class="header">
    <h1>Claude Chat Browser</h1>
    <div class="stats">{{COUNT}} sessions across {{PROJECTS}} projects</div>
</div>
<form class="search-bar" action="/search" method="get" onsubmit="
    this.querySelector('button').textContent='Searching\u2026';
    this.querySelector('button').style.opacity='0.6';
    this.querySelector('input').style.opacity='0.6';
">
    <input type="text" name="q" placeholder="Search across all conversations..." autofocus>
    <button type="submit">Search</button>
</form>
<table>
<tr><th>Session</th><th>Date</th><th>Size</th><th>Project</th><th>Summary</th></tr>
{{ROWS}}
</table>
</body>
</html>"""

WEB_TEMPLATE_SEARCH = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Search: {{QUERY}}</title>
<style>
:root {
    --bg: #1a1b26; --surface: #24283b; --text: #c0caf5;
    --text-dim: #565f89; --accent: #7aa2f7; --border: #3b4261;
    --hover: #2a2e4a;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: var(--bg); color: var(--text); padding: 20px;
}
h1 { color: var(--accent); font-size: 1.3em; margin-bottom: 5px; }
.back { color: var(--accent); text-decoration: none; display: inline-block; margin-bottom: 15px; }
.stats { color: var(--text-dim); margin-bottom: 20px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 8px; color: var(--text-dim); font-size: 0.8em;
     border-bottom: 1px solid var(--border); }
td { padding: 10px 8px; border-bottom: 1px solid var(--border); }
tr:hover { background: var(--hover); }
.mono { font-family: monospace; color: var(--accent); }
</style>
</head>
<body>
<a class="back" href="/">&#8592; Back</a>
<h1>Search: "{{QUERY}}"</h1>
<div class="stats">{{COUNT}} session(s) found</div>
<table>
<tr><th>Session</th><th>Matches</th><th>Date</th><th>Summary</th></tr>
{{ROWS}}
</table>
</body>
</html>"""


# ─── Main ────────────────────────────────────────────────────────────────────

_INTERACTIVE_HELP = (
    "  list                          Show recent sessions\n"
    "  list --detail                 Show with topic previews\n"
    "  list --project crystal        Filter by project\n"
    "  search \"react hooks\"          Search across all chats\n"
    "  export SESSION --format html  Export session (md/html/txt/tex)\n"
    "  export SESSION --format html --rich   Rich HTML (math, tables, links)\n"
    "  stats                         Usage statistics\n"
    "  extract SESSION --code        Extract code blocks\n"
    "  extract SESSION --ideas       Extract your messages\n"
    "  serve                         Open browser UI\n"
    "  backup --watch                Continuous backup\n"
    "  protect                       Prevent auto-deletion\n"
    "  help                          Show this help\n"
    "  quit                          Exit\n"
    "\n"
    "  !command                      Run a shell command (e.g. !start file.html)\n"
    "\n"
    "  Tip: run 'protect' to stop auto-deletion (sets cleanupPeriodDays=99999)"
)

_VALID_COMMANDS = {
    "list", "ls", "search", "grep", "find", "export", "backup",
    "stats", "extract", "serve", "web", "browse", "protect",
}


def cmd_interactive(parser):
    """Interactive REPL mode."""
    try:
        import readline  # noqa: F401 — enables arrow keys / history on Unix
    except ImportError:
        pass  # Windows: pyreadline3 optional, basic input still works

    print(f"claude-chat v{__version__} — interactive mode\n")
    print(_INTERACTIVE_HELP)
    print()

    while True:
        try:
            line = input("claude-chat> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not line:
            continue

        if line in ("quit", "exit", "q"):
            print("Bye.")
            break

        if line in ("help", "?", "h"):
            print(_INTERACTIVE_HELP)
            print()
            continue

        # Shell escape: !command runs in OS shell
        if line.startswith("!"):
            shell_cmd = line[1:].strip()
            if shell_cmd:
                import subprocess
                try:
                    subprocess.run(shell_cmd, shell=True)
                except Exception as e:
                    print(f"  Shell error: {e}")
            else:
                print("  Usage: !command (e.g. !start file.html)")
            print()
            continue

        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print(f"Parse error: {e}")
            continue

        # "command help" → "command --help"
        if len(tokens) == 2 and tokens[1] == "help":
            tokens[1] = "--help"

        # Check first token before handing to argparse (avoids ugly error dump)
        if tokens[0] not in _VALID_COMMANDS and not tokens[0].startswith("-"):
            print(f"  Unknown command: '{tokens[0]}'")
            print(f"  Try: list, search, export, stats, serve, help")
            print()
            continue

        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            # argparse calls sys.exit on --help or errors; catch it
            continue

        if not args.command:
            print("  Type a command or 'help' to see options.")
            continue

        try:
            cmd = args.command
            if cmd in ("list", "ls"):
                cmd_list(args)
            elif cmd in ("search", "grep", "find"):
                cmd_search(args)
            elif cmd == "export":
                cmd_export(args)
            elif cmd == "backup":
                cmd_backup(args)
            elif cmd == "stats":
                cmd_stats(args)
            elif cmd == "extract":
                cmd_extract(args)
            elif cmd in ("serve", "web", "browse"):
                cmd_serve(args)
            elif cmd == "protect":
                cmd_protect(args)
            else:
                print(f"Unknown command: {cmd}")
        except Exception as e:
            print(f"Error: {e}")

        print()


def main():
    if sys.version_info < (3, 7):
        print("claude-chat requires Python 3.7 or later.")
        sys.exit(1)

    _fix_windows_encoding()

    parser = argparse.ArgumentParser(
        prog="claude-chat",
        description="One tool for all your Claude Code conversations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                          List recent sessions
  %(prog)s list --limit 100              Show more sessions
  %(prog)s search "react hooks"          Search across all chats
  %(prog)s export a7e44ed0 --format html Export as HTML
  %(prog)s export a7e44ed0 --format html --open   Export and open in browser
  %(prog)s backup --watch                Watch and backup continuously
  %(prog)s stats                         Show statistics
  %(prog)s extract a7e44ed0 --code       Extract code blocks
  %(prog)s extract a7e44ed0 --ideas      Extract your messages
  %(prog)s serve                         Browse in your browser
  %(prog)s protect                       Prevent auto-deletion
        """,
    )
    parser.add_argument("--version", action="version", version=f"claude-chat v{__version__}")

    sub = parser.add_subparsers(dest="command")

    # list
    p = sub.add_parser("list", aliases=["ls"], help="List sessions with summaries")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--limit", "-n", type=int, help="Max sessions to show")
    p.add_argument("--detail", "-d", action="store_true", help="Show preview of each session's topics")

    # search
    p = sub.add_parser("search", aliases=["grep", "find"], help="Search across all conversations")
    p.add_argument("query", help="Search query")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--limit", "-n", type=int, default=20, help="Max results")

    # export
    p = sub.add_parser("export", help="Export session to file")
    p.add_argument("session_id", help="Session ID (full or first 8 chars)")
    p.add_argument("--format", "-f", choices=["md", "html", "txt", "tex"], default="md", help="Output format")
    p.add_argument("--output", "-o", help="Output directory")
    p.add_argument("--open", action="store_true", help="Open in browser/editor after export")
    p.add_argument("--rich", action="store_true", help="Rich HTML: clickable links, KaTeX math, tables")

    # backup
    p = sub.add_parser("backup", help="Backup session files")
    p.add_argument("--watch", "-w", action="store_true", help="Watch continuously")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--output", "-o", help="Backup directory")
    p.add_argument("--interval", "-i", type=int, default=10, help="Poll interval (seconds)")

    # stats
    p = sub.add_parser("stats", help="Show usage statistics")
    p.add_argument("--project", "-p", help="Filter by project name")

    # extract
    p = sub.add_parser("extract", help="Extract content from session")
    p.add_argument("session_id", help="Session ID (full or first 8 chars)")
    p.add_argument("--code", action="store_true", help="Extract code blocks")
    p.add_argument("--ideas", action="store_true", help="Extract your messages")
    p.add_argument("--decisions", action="store_true", help="Extract decision points")

    # serve
    p = sub.add_parser("serve", aliases=["web", "browse"], help="Browse in your browser")
    p.add_argument("--port", type=int, default=3456, help="Port number")
    p.add_argument("--no-open", action="store_true", help="Don't auto-open browser")

    # protect
    sub.add_parser("protect", help="Prevent auto-deletion of old sessions")

    args = parser.parse_args()

    if not args.command:
        cmd_interactive(parser)
        return

    cmd = args.command
    if cmd in ("list", "ls"):
        cmd_list(args)
    elif cmd in ("search", "grep", "find"):
        cmd_search(args)
    elif cmd == "export":
        cmd_export(args)
    elif cmd == "backup":
        cmd_backup(args)
    elif cmd == "stats":
        cmd_stats(args)
    elif cmd == "extract":
        cmd_extract(args)
    elif cmd in ("serve", "web", "browse"):
        cmd_serve(args)
    elif cmd == "protect":
        cmd_protect(args)


if __name__ == "__main__":
    main()
