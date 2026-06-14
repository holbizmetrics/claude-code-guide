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
    python claude-chat.py search "lemma" --in a7e44ed0 -C 80   Within one session, wide context
    python claude-chat.py search "lemma" --after 2026-05-01    Date-range filter
    python claude-chat.py export a7e44ed0 --stdout | grep foo  Export to stdout for piping
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
    __slots__ = ("role", "text", "tool_calls", "thinking", "timestamp", "model", "has_thinking")

    def __init__(self, role, text="", tool_calls=None, thinking="", timestamp=None, model=None, has_thinking=False):
        self.role = role
        self.text = text
        self.tool_calls = tool_calls or []
        self.thinking = thinking
        self.timestamp = timestamp
        self.model = model
        # True when a thinking/redacted_thinking block was present, even if its
        # content is empty (encrypted transcripts carry the block but no text) —
        # so "reasoning present" is measurable without confusing it with "no thinking".
        self.has_thinking = has_thinking

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


class Turn:
    """One user prompt + the assistant's full (possibly multi-event) response.

    Claude Code emits a single assistant response as SEVERAL transcript events
    (a thinking event, then a text event, then a tool_use event, ...). A Turn
    aggregates those events back into one unit so behavioral metrics are measured
    per response ("how it opens a task"), not per raw event.
    """

    __slots__ = ("model", "n_tools", "first_tool", "narration_chars",
                 "thinking_chars", "has_reasoning", "think_before_action")

    def __init__(self, model, n_tools, first_tool, narration_chars,
                 thinking_chars, has_reasoning, think_before_action):
        self.model = model
        self.n_tools = n_tools
        self.first_tool = first_tool                # name of the first tool used in the turn, or None
        self.narration_chars = narration_chars
        self.thinking_chars = thinking_chars
        self.has_reasoning = has_reasoning          # any thinking event present in the turn
        self.think_before_action = think_before_action  # True/False for tool-turns, None if no tool


def _finalize_turn(aevents):
    """Aggregate a turn's ordered assistant events into a Turn.

    aevents: list of ("A", model, has_thinking, think_idx, tool_idx, tool_names, text_len, think_len).
    think_before_action is resolved at the FIRST tool event: True if any earlier
    event reasoned, or the action event itself reasoned before its first tool.
    """
    if not aevents:
        return None
    model = aevents[0][1]
    n_tools = narration = thinking_chars = 0
    first_tool = None
    has_reasoning = False
    think_before_action = None
    thinking_seen_before_first_tool = False
    for (_, _mdl, has_think, think_idx, tool_idx, tool_names, text_len, think_len) in aevents:
        narration += text_len
        thinking_chars += think_len
        if has_think:
            has_reasoning = True
        if tool_names and first_tool is None:
            first_tool = tool_names[0]
            if thinking_seen_before_first_tool:
                think_before_action = True
            elif has_think and think_idx is not None and tool_idx is not None and think_idx < tool_idx:
                think_before_action = True
            else:
                think_before_action = False
        if tool_names:
            n_tools += len(tool_names)
        if has_think and first_tool is None:
            thinking_seen_before_first_tool = True
    return Turn(model, n_tools, first_tool, narration, thinking_chars,
                has_reasoning, think_before_action)


def _build_turns(events):
    """Segment an ordered event log into Turn objects.

    events: ("U",) boundaries (text-bearing user messages) and
            ("A", ...) assistant events. Assistant events accumulate into the
            current turn; each ("U",) closes the previous turn and opens a new one.
    """
    turns = []
    current = None
    for ev in events:
        if ev[0] == "U":
            if current is not None:
                t = _finalize_turn(current)
                if t:
                    turns.append(t)
            current = []
        else:  # ("A", ...)
            if current is None:
                current = []   # assistant events before the first user message
            current.append(ev)
    if current:
        t = _finalize_turn(current)
        if t:
            turns.append(t)
    return turns


class Session:
    """A parsed Claude Code session.

    Also handles subagent transcripts nested at
    <project>/<session_id>/subagents/agent-<agent_id>.jsonl. Subagent
    sessions expose `is_subagent`, `agent_id`, and `parent_session_id`;
    their `short_id` is the first 8 chars of the agent_id (without the
    "agent-" prefix), so users can refer to subagents by bare agent_id.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.session_id = self.path.stem
        # Detect subagent: lives at <project>/<session_id>/subagents/agent-<id>.jsonl
        self.is_subagent = (
            self.path.parent.name == "subagents"
            and self.session_id.startswith("agent-")
        )
        if self.is_subagent:
            self.agent_id = self.session_id[len("agent-"):]
            self.parent_session_id = self.path.parent.parent.name
            self.short_id = self.agent_id[:8]
            self.project = self.path.parent.parent.parent.name
        else:
            self.agent_id = None
            self.parent_session_id = None
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

        self.turns = []
        events = []  # ordered raw event log for turn segmentation (see _build_turns)
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
                    ts = obj.get("timestamp")

                    if role == "user":
                        text = self._extract_text(msg_data.get("content", ""))
                        if text and "<system-reminder>" not in text:
                            self.messages.append(Message("user", text, timestamp=ts))
                            # A text-bearing user message starts a new turn. tool_result-only
                            # user messages (text == "") are mid-turn and do NOT segment.
                            events.append(("U",))

                    elif role == "assistant":
                        content = msg_data.get("content", [])
                        # Per-turn model: a single session can span >1 model (e.g. a
                        # mid-session model swap), so each assistant turn carries its
                        # OWN model. self.model stays = the first one (session headline).
                        msg_model = msg_data.get("model", None)
                        if not self.model:
                            self.model = msg_model

                        text_parts = []
                        tool_calls = []
                        thinking = ""
                        has_thinking = False
                        think_idx = None   # content-index of first thinking block (within-event order)
                        tool_idx = None    # content-index of first tool_use block
                        thinking_len = 0

                        if isinstance(content, str):
                            text_parts.append(content)
                        elif isinstance(content, list):
                            for i, block in enumerate(content):
                                if not isinstance(block, dict):
                                    continue
                                btype = block.get("type", "")
                                if btype == "text":
                                    text_parts.append(block.get("text", ""))
                                elif btype == "tool_use":
                                    tool_calls.append(ToolCall(
                                        block.get("name", "unknown"),
                                        block.get("input", {})
                                    ))
                                    if tool_idx is None:
                                        tool_idx = i
                                elif btype in ("thinking", "redacted_thinking"):
                                    has_thinking = True
                                    if think_idx is None:
                                        think_idx = i
                                    tcontent = block.get("thinking", "")
                                    if tcontent:
                                        thinking = tcontent
                                        thinking_len += len(tcontent)

                        text = "\n".join(text_parts).strip()
                        # Record EVERY assistant event (incl. thinking-ONLY events, which are
                        # NOT added to self.messages but ARE load-bearing for the turn-level
                        # reasoning% and think-before-action metrics — the point of this pass).
                        events.append(("A", msg_model or self.model, has_thinking,
                                       think_idx, tool_idx,
                                       [tc.name for tc in tool_calls],
                                       len(text), thinking_len))
                        if text or tool_calls:
                            m = Message("assistant", text, tool_calls, thinking,
                                        timestamp=ts, model=msg_model or self.model,
                                        has_thinking=has_thinking)
                            self.messages.append(m)

            self.turns = _build_turns(events)
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
                if m.role == "user" and len(m.text) > 5 and not m.text.lower().startswith("this session is being continued from a previous conversation"):
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
                        if text and len(text) > 5 and "<system-reminder>" not in text and not text.lower().startswith("this session is being continued from a previous conversation"):
                            clean = text.replace("\n", " ").replace("\r", " ")
                            clean = re.sub(r"\s+", " ", clean).strip()
                            return clean[:max_len] + "..." if len(clean) > max_len else clean
        except (IOError, OSError):
            pass
        return "(empty session)"

    def smart_headline(self, max_len=100):
        """No-AI heuristic headline (first real ask / commit subject / edited files /
        keywords) instead of the first message. Cached by file mtime+size."""
        return _truncate(_smart_headline_cached(self), max_len)

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

    def turn_models(self):
        """Counter of per-turn models across assistant messages.

        A session can be multi-model (e.g. a mid-session model swap), so this
        counts every assistant turn's own model — unlike `self.model`, which is
        just the first (headline) model seen.
        """
        from collections import Counter
        self.parse()
        c = Counter()
        for m in self.messages:
            if m.role == "assistant" and m.model:
                c[m.model] += 1
        return c

    def is_mixed(self):
        """True if the session has assistant turns from more than one model."""
        return len(self.turn_models()) > 1

    def has_model(self, needle):
        """True if any per-turn model name contains `needle` (case-insensitive substring)."""
        nl = needle.lower()
        return any(nl in mdl.lower() for mdl in self.turn_models())


# ─── Smart Headlines (heuristic, no AI) ──────────────────────────────────────
#
# The default headline is the first user message, which for boot-style sessions
# is always "Boot up X from:.". Build a meaningful one instead via a cascade:
#   first real ask  ->  git commit subject  ->  edited files  ->  keywords.
# Cached by file mtime+size in ~/.claude/.headline-cache.json so list/serve stay
# fast across runs. Opt-in via --smart; default behavior (summary) is unchanged.

HEADLINE_CACHE_FILE = CLAUDE_DIR / ".headline-cache.json"
_HEADLINE_CACHE = None
_HEADLINE_CACHE_DIRTY = False
_HEADLINE_ALGO = 4  # bump when the cascade changes so cached headlines auto-invalidate

_H_TAG_BLOCK = re.compile(
    r"<(local-command-caveat|bash-input|bash-stdout|bash-stderr|command-name|"
    r"command-message|command-args|local-command-stdout|system-reminder)[^>]*>.*?</\1>",
    re.DOTALL)
_H_LONE_TAG = re.compile(r"</?[a-z][a-z-]*>")
_H_INTERRUPT = re.compile(r"\[Request interrupted[^\]]*\]")
_H_ACK = re.compile(
    r"^(ok(ay)?|yes+|yeah|yep|yup|no+|nope|sure|thx|thanks?|thank you|ty|continue|"
    r"go on|go ahead|proceed|good|nice|cool|great|perfect|done|k|hmm+|sounds good|"
    r"exactly|right|the word)\b", re.IGNORECASE)
_H_ACK_START = re.compile(
    r"^(yeah|yes+|yep|yup|no+|nope|sure|ok(ay)?|right|exactly|good|nice|cool|thanks?)\b",
    re.IGNORECASE)
_H_COMMIT_M = re.compile(r"git\s+commit\b[^\n]*?-m\s+(['\"])(.+?)\1", re.DOTALL)
_H_HEREDOC = re.compile(r"<<\s*['\"]?(\w+)['\"]?\s*\n(.*?)\n", re.DOTALL)
_H_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")
_H_STOP = set((
    "the a an and or but if then else to of in on for with at by from this that these "
    "those is are was were be been being it its as we you i he she they them our your my me "
    "do does did doing have has had not no yes can will would could should may might just like "
    "get got make made use used using let lets ok now here there what how why when which who "
    "about into out up down over under again more most some any all one two would want need see "
    "file files code session please thanks run").split())
_H_TAGWORDS = set((
    "local-command-caveat bash-input bash-stdout bash-stderr command-name command-message "
    "command-args local-command-stdout system-reminder caveat request interrupted boot").split())


def _truncate(s, n, max_loss=0.30):
    """Truncate to n chars at a word boundary, but if backing up to the last
    space would drop more than max_loss of the budget (e.g. a long spaceless
    path), hard-cut instead so the distinguishing tail stays visible."""
    if not s or len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    if sp >= n * (1 - max_loss):
        return cut[:sp].rstrip() + "…"
    return cut.rstrip() + "…"


def _h_strip_noise(text):
    t = _H_TAG_BLOCK.sub(" ", text)
    t = _H_INTERRUPT.sub(" ", t)
    t = _H_LONE_TAG.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _h_meaningful_ask(t):
    if len(t) < 12:
        return False
    low = t.lower()
    if low.startswith("this session is being continued from a previous conversation"):
        return False  # compaction-continuation summary is not a real ask
    if low.startswith("boot ") or ("boot up" in low and "from" in low):
        return False
    if low.startswith("base directory for this skill"):
        return False
    if "accidentally pressed" in low:
        return False
    if _H_ACK.match(t) and len(t) < 45:
        return False
    return True


def _h_first_ask(session):
    for m in session.messages:
        if m.role != "user":
            continue
        t = _h_strip_noise(m.text)
        if _h_meaningful_ask(t):
            return t
    return None


def _h_pathy(t):
    if t.startswith("\\\\") or re.match(r"^[A-Za-z]:\\", t) or "\\\\wsl" in t.lower():
        return True
    return ("\\" in t or "/" in t) and t.count(" ") < 6 and (t.count("\\") + t.count("/")) >= 3


def _h_ask_strong(t):
    if not t or len(t) < 18:
        return False
    low = t.lower()
    if _H_ACK_START.match(t):
        return False
    if "accidentally" in low or low.startswith("i meant") or "by from" in low or "i wanna know if there" in low:
        return False
    return True


def _h_first_nonempty(s):
    for ln in s.splitlines():
        if ln.strip():
            return ln.strip()
    return None


def _h_artifacts(session):
    commits, edits = [], []
    for m in session.messages:
        if m.role != "assistant":
            continue
        for tc in m.tool_calls:
            d = tc.input_data or {}
            if tc.name == "Bash":
                cmd = d.get("command", "")
                if "git commit" in cmd:
                    subj = None
                    if "<<" in cmd:
                        hh = _H_HEREDOC.search(cmd)
                        if hh:
                            subj = _h_first_nonempty(hh.group(2))
                    if not subj:
                        mm = _H_COMMIT_M.search(cmd)
                        if mm:
                            subj = _h_first_nonempty(mm.group(2))
                    if subj and len(subj) > 3 and not subj.lower().startswith("co-authored"):
                        commits.append(subj)
            elif tc.name in ("Edit", "Write", "NotebookEdit"):
                fp = d.get("file_path") or d.get("notebook_path") or ""
                if fp:
                    edits.append(Path(fp).name)
    seen, uedits = set(), []
    for e in edits:
        if e not in seen:
            seen.add(e)
            uedits.append(e)
    return commits, uedits


def _h_edits_str(uedits, n=3):
    if not uedits:
        return None
    head = ", ".join(uedits[:n])
    extra = len(uedits) - n
    return head + (f" (+{extra})" if extra > 0 else "")


def _h_keywords(session, k=4):
    from collections import Counter
    c = Counter()
    for m in session.messages:
        if not m.text:
            continue
        for w in _H_WORD.findall(_h_strip_noise(m.text)):
            lw = w.lower()
            if lw in _H_STOP or lw in _H_TAGWORDS:
                continue
            c[lw] += 1
    common = [w for w, _ in c.most_common(k)]
    return ", ".join(common) if common else None


# A genuine filesystem path only: a Windows drive path, or a Unix absolute path
# with >=2 segments, and only at a token boundary — so prose like "Kafka/RabbitMQ"
# or "cli/chat.py" mid-sentence is NOT mistaken for a path to front-load.
_H_PATH = re.compile(r"(?<![^\s(\"'`])[`'\"]?([A-Za-z]:\\[^`'\"\n]+|/[^\s/`'\"]+(?:/[^\s/`'\"]+)+)[`'\"]?")
_H_VERB = re.compile(
    r"^\s*(survey|scan|read|audit|review|analy[sz]e|inspect|explore|investigate|check)\b",
    re.IGNORECASE)


def _h_path_leaf(path):
    p = path.strip().strip("`'\"").rstrip("\\/").replace("/", "\\")
    return p.split("\\")[-1] or path


def _h_subagent_headline(session):
    """Front-load the target path for subagent task prompts so each row is
    distinct (e.g. 'Survey Prometheus-Field: ...') and survives truncation."""
    msg = next((m.text for m in session.messages if m.role == "user" and len(m.text) > 5), "")
    if not msg:
        return None
    one = re.sub(r"\s+", " ", msg).strip()
    pm = _H_PATH.search(one)
    if not pm:
        return None  # no path to front-load; let the normal cascade handle it
    target = _h_path_leaf(pm.group(1))
    vm = _H_VERB.match(one)
    verb = vm.group(1).capitalize() if vm else None
    tail = re.sub(r"^\s*(and|then|,|;|\.|&)?\s*", "", one[pm.end():], flags=re.IGNORECASE).strip()
    tail = _H_PATH.sub(lambda m: _h_path_leaf(m.group(1)), tail)  # collapse paths in tail to leaves
    tail = re.sub(r"\s+", " ", tail).strip()
    head = f"{verb + ' ' if verb else ''}{target}"
    return head + (": " + tail if tail else "")


def _compute_headline(session):
    """The cascade. Returns an untruncated headline string (never empty)."""
    session.parse()
    if session.is_subagent:
        sub = _h_subagent_headline(session)
        if sub:
            return sub
    ask = _h_first_ask(session)
    commits, uedits = _h_artifacts(session)
    commit = max(commits, key=len) if commits else None
    edits = _h_edits_str(uedits)
    strong = _h_ask_strong(ask)
    if strong and ask and _h_pathy(ask) and (commit or edits):
        strong = False  # path-heavy ask is a poor headline; prefer artifacts
    if strong and commit:
        return _truncate(ask, 60) + "  ·  " + _truncate(commit, 60)
    if strong:
        return ask
    if commit:
        return commit
    if edits:
        return "edits: " + edits
    if ask:
        return ask
    kw = _h_keywords(session)
    if kw:
        return "topics: " + kw
    return session.summary(160)


def _load_headline_cache():
    global _HEADLINE_CACHE
    if _HEADLINE_CACHE is None:
        try:
            _HEADLINE_CACHE = json.loads(HEADLINE_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _HEADLINE_CACHE = {}
    return _HEADLINE_CACHE


def save_headline_cache():
    """Persist the headline cache if it changed. No-op when --smart wasn't used."""
    global _HEADLINE_CACHE_DIRTY
    if _HEADLINE_CACHE is None or not _HEADLINE_CACHE_DIRTY:
        return
    try:
        HEADLINE_CACHE_FILE.write_text(json.dumps(_HEADLINE_CACHE), encoding="utf-8")
        _HEADLINE_CACHE_DIRTY = False
    except Exception:
        pass


def _smart_headline_cached(session):
    global _HEADLINE_CACHE_DIRTY
    cache = _load_headline_cache()
    key = str(session.path)
    try:
        mtime, size = session._stat.st_mtime, session.size
    except Exception:
        mtime, size = None, None
    ent = cache.get(key)
    if ent and ent.get("v") == _HEADLINE_ALGO and ent.get("mtime") == mtime and ent.get("size") == size:
        return ent.get("headline") or ""
    full = _compute_headline(session) or ""
    cache[key] = {"v": _HEADLINE_ALGO, "mtime": mtime, "size": size, "headline": full}
    _HEADLINE_CACHE_DIRTY = True
    return full


# ─── Session Discovery ───────────────────────────────────────────────────────
#
# find_all_sessions / find_session are pure lookups with no per-call state and
# no invariants beyond what Session already enforces — they stay as functions.
# (Bundling them into a "SessionFinder" class with only static-method behavior
# would be the exact "surface compliance without semantic compliance" the
# OOP guide warns against.)

def _parse_date_filter(value, end_of_day=False):
    """Parse a YYYY-MM-DD filter string into a datetime, or None if value is falsy.

    end_of_day=True snaps to 23:59:59 so --before DATE is inclusive of that whole day.
    Raises ValueError with a user-facing message on a malformed date.
    """
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f'Invalid date "{value}" — expected YYYY-MM-DD (e.g. 2026-05-01).')
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


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
        # Subagent transcripts: <project>/<session_id>/subagents/agent-<id>.jsonl
        for sub_jsonl in project_dir.glob("*/subagents/agent-*.jsonl"):
            try:
                if sub_jsonl.stat().st_size > 100:
                    sessions.append(Session(sub_jsonl))
            except (FileNotFoundError, OSError):
                continue
    sessions.sort(key=lambda s: s.modified, reverse=True)
    return sessions


def find_session(session_id):
    """Find a specific session by ID (full or short).

    Subagents can also be looked up by bare agent_id (without the `agent-`
    prefix), since that's what users see in TaskCreate output.
    """
    for s in find_all_sessions():
        if s.session_id == session_id or s.short_id == session_id:
            return s
        if s.is_subagent and s.agent_id == session_id:
            return s
    return None


# ─── Tool-call iteration ─────────────────────────────────────────────────────
#
# _iter_tool_call_strings stays a module-level function (not absorbed into
# SessionScanner) because both SessionScanner and WikiCommand call it.
# It's a pure projection of ToolCall.input_data into searchable (key, string)
# pairs — there's no scanner state involved, so making it a SessionScanner
# static method would be misleading about ownership. Multiple call sites +
# pure data shape → module helper is the right fit.

def _iter_tool_call_strings(tc):
    """Yield (key, str_value) pairs from a ToolCall.input_data, flattening nested values."""
    for key, val in tc.input_data.items():
        if isinstance(val, str):
            yield key, val
        elif isinstance(val, (list, tuple)):
            for i, v in enumerate(val):
                if isinstance(v, str):
                    yield f"{key}[{i}]", v
        elif isinstance(val, dict):
            for k2, v in val.items():
                if isinstance(v, str):
                    yield f"{key}.{k2}", v


# ─── Session preview helper ──────────────────────────────────────────────────
#
# _session_preview is a tiny formatting helper used only by ListCommand. It's
# stateless (input → output, no invariants) — keeping it module-level avoids
# inflating ListCommand with helpers that don't share its state.

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


# ─── Interactive Session Index ──────────────────────────────────────────────
#
# When `list` runs inside the REPL, we remember the displayed sessions in
# order. Subsequent commands like `export 1`, `open 3`, `extract 2 --code`
# can then use the number instead of the hash. CLI (non-REPL) behavior is
# unchanged.

_interactive_index = []  # type: list  # Session objects in display order

# Commands where a bare integer is a session reference (positional session_id).
# Commands not in this set (list, search, backup, stats, serve, protect) can have
# numeric flag values like `--limit 5`, `--interval 3` — those must never be
# rewritten, so we gate substitution by command.
_ID_COMMANDS = frozenset({"export", "extract", "open"})


def _substitute_numbered_refs(tokens, index=None, autopopulate=True):
    """Replace the first positional integer after an ID command with a session short_id.

    Only acts on commands in _ID_COMMANDS (those that take session_id as a positional).
    Only the FIRST non-flag integer token is rewritten — so `open 1 --port 3456`
    correctly leaves `3456` alone even when the index has ≥3456 entries.

    If `autopopulate=True` (default) and the index is empty but tokens suggest
    a numbered ref (small int 1..99), the module-level `_interactive_index` is
    filled from `find_all_sessions()[:20]` — matching what `list` does by
    default. This lets `export 1` work without requiring a prior `list`.

    Tests pass `index=[...]` directly, bypassing autopopulation.

    Returns the (possibly rewritten) token list. REPL inspects before/after
    to print a resolution trace.
    """
    use_module_index = index is None
    if use_module_index:
        index = _interactive_index
    if not tokens or tokens[0] not in _ID_COMMANDS:
        return list(tokens)

    if not index and autopopulate and use_module_index:
        needs_pop = any(
            t and t[0] != "-" and t.isdigit() and 1 <= int(t) <= 99
            for t in tokens[1:]
        )
        if needs_pop:
            sessions = find_all_sessions()[:20]
            _interactive_index.clear()
            _interactive_index.extend(sessions)
            index = _interactive_index

    if not index:
        return list(tokens)

    out = [tokens[0]]
    substituted = False
    for t in tokens[1:]:
        if not substituted and t and t[0] != "-" and t.isdigit():
            n = int(t)
            if 1 <= n <= len(index):
                out.append(index[n - 1].short_id)
                substituted = True
                continue
        out.append(t)
    return out


# ─── SessionScanner ──────────────────────────────────────────────────────────

class SessionScanner:
    """Scans a Session for a query string, returning match count + snippets.

    Earns its existence: holds the normalized query + scan options (tools_only,
    context width) as state, and enforces the invariant that the query is
    always pre-lowercased once at construction (callers shouldn't re-normalize
    on every scan). `scan()` is the behavior over that state.
    """

    def __init__(self, query, *, context=40, tools_only=False, no_truncate=False):
        # Invariant: stored query is always lower-cased (matches are case-insensitive).
        self.query = query.lower()
        self.context = max(0, context)
        self.tools_only = tools_only
        self.no_truncate = no_truncate

    def _snippet(self, text, idx):
        if self.no_truncate:
            # Return the full text containing the match, preserving newlines.
            # Caller is responsible for output formatting (multi-line indentation, etc.).
            return text.strip()
        start = max(0, idx - self.context)
        end = min(len(text), idx + len(self.query) + self.context)
        out = text[start:end].replace("\n", " ")
        if start > 0:
            out = "..." + out
        if end < len(text):
            out = out + "..."
        return out

    def scan(self, session):
        """Return (count, contexts) for one session. contexts is list of (role, snippet)."""
        count = 0
        contexts = []
        for m in session.messages:
            if self.tools_only:
                for tc in m.tool_calls:
                    for field, val in _iter_tool_call_strings(tc):
                        lv = val.lower()
                        if self.query in lv:
                            count += lv.count(self.query)
                            idx = lv.index(self.query)
                            contexts.append((m.role, f"[{tc.name}.{field}] {self._snippet(val, idx)}"))
            else:
                if m.text:
                    lt = m.text.lower()
                    if self.query in lt:
                        count += lt.count(self.query)
                        idx = lt.index(self.query)
                        contexts.append((m.role, self._snippet(m.text, idx)))
        return count, contexts


# Back-compat module-level shim: existing call sites (and the pytest suite)
# may still reach for _scan_session. Delegates to SessionScanner.
def _scan_session(s, query, context, tools_only):
    """Return (count, contexts) for one session. Thin wrapper over SessionScanner."""
    return SessionScanner(query, context=context, tools_only=tools_only).scan(s)


# ─── Exporters ───────────────────────────────────────────────────────────────

class Exporter:
    """Base class for session exporters.

    Subclasses earn their existence by carrying the session + format options
    as state and producing a format-specific string via format(). The base
    class enforces the contract (format() must be overridden, extension is
    declared).
    """

    extension = ""  # override in subclasses

    def __init__(self, session, *, no_truncate=False, embedded=False, rich=False, diagrams=False):
        self.session = session
        self.no_truncate = no_truncate
        self.embedded = embedded
        self.rich = rich
        self.diagrams = diagrams

    def format(self):
        """Return the formatted session string. Subclasses must override."""
        raise NotImplementedError


class MarkdownExporter(Exporter):
    """Markdown export.

    Tool-call inputs are truncated to 500 chars for readability by default;
    pass no_truncate=True for full content (needed for byte-perfect recovery
    of files edited via the Edit/Write tools).
    """

    extension = ".md"

    def format(self):
        session = self.session
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
                    input_str = json.dumps(tc.input_data, indent=2)
                    if not self.no_truncate:
                        input_str = input_str[:500]
                    lines.append(f"\n<details><summary>Tool: {tc.summary()}</summary>\n")
                    lines.append(f"```json\n{input_str}\n```")
                    lines.append(f"</details>\n")
                lines.append("")

        lines.append(f"\n---\n*Exported with claude-chat v{__version__}*\n")
        return "\n".join(lines)


class TextExporter(Exporter):
    """Plain text export."""

    extension = ".txt"

    def format(self):
        session = self.session
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


class TeXExporter(Exporter):
    """LaTeX export."""

    extension = ".tex"

    @staticmethod
    def _tex_escape(text):
        # Single-pass replacement to avoid double-escaping (backslash must not
        # be replaced sequentially after other replacements introduce backslashes)
        conv = {
            "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
            "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\^{}",
        }
        pattern = re.compile("|".join(re.escape(k) for k in conv))
        return pattern.sub(lambda m: conv[m.group()], text)

    def format(self):
        session = self.session
        tex_escape = self._tex_escape

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


class HTMLExporter(Exporter):
    """HTML export with dark theme, optional rich rendering + diagrams.

    The rich-text helpers (_md_table_to_html, _render_table, _auto_link_urls,
    _build_sequence_diagram) live here as static methods because HTML is the
    only consumer that benefits from markdown→HTML or mermaid translation.
    """

    extension = ".html"

    # ─── Rich-text helpers (HTML-only) ──────────────────────────────────────

    @staticmethod
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
                    result.append(HTMLExporter._render_table(table_lines))
                    table_lines = []
                    in_table = False
                result.append(line)

        if table_lines:
            result.append(HTMLExporter._render_table(table_lines))

        return "\n".join(result)

    @staticmethod
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

    @staticmethod
    def _auto_link_urls(text):
        """Convert plain URLs to clickable links (skip already-linked ones)."""
        return re.sub(
            r'(?<!href=")(?<!src=")(https?://[^\s<>")\]]+)',
            r'<a href="\1" target="_blank" rel="noopener">\1</a>',
            text
        )

    @staticmethod
    def _build_sequence_diagram(session):
        """Build a mermaid sequenceDiagram from session tool calls.

        Participants: Claude + one per distinct tool name (in first-seen order).
        Events: one arrow per tool call in conversation order.
        Returns "" if the session has no tool calls.
        """
        tool_names = []
        seen = set()
        events = []
        for m in session.messages:
            if m.role != "assistant" or not m.tool_calls:
                continue
            for tc in m.tool_calls:
                name = (tc.name or "Tool").strip()
                if name not in seen:
                    seen.add(name)
                    tool_names.append(name)
                summary = tc.summary() or name
                s = summary
                if s.startswith(name + ":"):
                    s = s[len(name) + 1:].strip()
                elif s.startswith(name):
                    s = s[len(name):].lstrip(" :-")
                s = s.replace("\r", " ").replace("\n", " ")
                if len(s) > 60:
                    s = s[:57] + "..."
                s = s.replace(";", ",").replace("#", "&#35;")
                s = s.replace("<", "&lt;").replace(">", "&gt;")
                if not s:
                    s = name
                events.append((name, s))
        if not events:
            return ""

        def pid(n):
            safe = re.sub(r"\W+", "_", n).strip("_")
            return safe or "T"

        lines = ["sequenceDiagram", "    participant C as Claude"]
        for n in tool_names:
            lines.append(f'    participant {pid(n)} as {n}')
        for name, s in events:
            lines.append(f"    C->>{pid(name)}: {s}")
        return "\n".join(lines)

    # ─── format() ───────────────────────────────────────────────────────────

    def format(self):
        session = self.session
        embedded = self.embedded
        rich = self.rich
        diagrams = self.diagrams
        no_truncate = self.no_truncate

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
                    text = self._md_table_to_html(text)
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
                    text = self._auto_link_urls(text)
            else:
                text = ""

            # Tool calls
            tools_html = ""
            if m.tool_calls:
                for tc in m.tool_calls:
                    input_preview = json.dumps(tc.input_data, indent=2)
                    if not no_truncate:
                        input_preview = input_preview[:400]
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

        diagrams_head = ""
        diagrams_foot = ""
        diagram_block = ""
        if diagrams:
            seq = self._build_sequence_diagram(session)
            if seq:
                diagram_block = (
                    '<details class="diagram-block" open>'
                    '<summary>Tool-call sequence</summary>'
                    '<div class="diagram-stage">'
                    '<div class="diagram-controls">'
                    '<button type="button" data-zoom="in" title="Zoom in">+</button>'
                    '<button type="button" data-zoom="out" title="Zoom out">−</button>'
                    '<button type="button" data-zoom="reset" title="Reset view">Reset</button>'
                    '<button type="button" data-zoom="full" title="Toggle fullscreen (Esc to exit)">⛶ Full</button>'
                    '<span class="diagram-hint">drag to pan &middot; scroll / pinch to zoom</span>'
                    '</div>'
                    '<div class="diagram-viewport">'
                    '<pre class="mermaid">\n' + seq + '\n</pre>'
                    '</div>'
                    '</div>'
                    '</details>'
                )
            diagrams_head = """
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
<style>
.diagram-block {
    margin: 15px 0 20px 0; padding: 12px 15px; background: var(--surface);
    border-radius: 8px; border-left: 3px solid var(--yellow);
}
.diagram-block > summary {
    cursor: pointer; color: var(--yellow); font-weight: bold;
    font-size: 0.9em; letter-spacing: 0.3px;
}
.diagram-controls {
    display: flex; gap: 6px; align-items: center; margin: 10px 0 6px 0;
}
.diagram-controls button {
    background: var(--surface2); color: var(--text); border: 1px solid var(--border);
    border-radius: 4px; padding: 3px 10px; font: inherit; font-size: 0.85em;
    cursor: pointer; min-width: 32px;
}
.diagram-controls button:hover { background: var(--border); }
.diagram-hint {
    color: var(--text-dim); font-size: 0.75em; margin-left: 6px;
}
.diagram-stage {
    display: flex; flex-direction: column;
}
.diagram-stage:fullscreen {
    background: var(--bg); width: 100vw; height: 100vh; padding: 10px;
}
.diagram-stage:fullscreen .diagram-viewport {
    flex: 1; height: auto;
}
.diagram-viewport {
    background: transparent; border: 1px solid var(--border); border-radius: 4px;
    height: 70vh; overflow: hidden; touch-action: none;
}
.diagram-viewport .mermaid {
    background: transparent; border: none; padding: 0; margin: 0;
    width: 100%; height: 100%; font-family: inherit;
}
.diagram-viewport .mermaid svg {
    width: 100% !important; height: 100% !important; max-width: none !important;
    display: block;
}
</style>"""
            diagrams_foot = """
<script>
document.addEventListener("DOMContentLoaded", function() {
    if (!window.mermaid) return;
    try {
        mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });
    } catch(e) { return; }
    mermaid.run().then(function() {
        document.querySelectorAll(".diagram-block").forEach(function(block) {
            var svg = block.querySelector(".diagram-viewport svg");
            if (!svg || !window.svgPanZoom) return;
            svg.removeAttribute("style");
            svg.setAttribute("width", "100%");
            svg.setAttribute("height", "100%");
            var pz = svgPanZoom(svg, {
                zoomEnabled: true, controlIconsEnabled: false, fit: true, center: true,
                minZoom: 0.2, maxZoom: 20, zoomScaleSensitivity: 0.4
            });
            var stage = block.querySelector(".diagram-stage");
            block.querySelectorAll(".diagram-controls button").forEach(function(btn) {
                btn.addEventListener("click", function() {
                    var k = btn.getAttribute("data-zoom");
                    if (k === "in") pz.zoomIn();
                    else if (k === "out") pz.zoomOut();
                    else if (k === "reset") { pz.resetZoom(); pz.center(); pz.fit(); }
                    else if (k === "full") {
                        if (document.fullscreenElement) document.exitFullscreen();
                        else if (stage && stage.requestFullscreen) stage.requestFullscreen();
                    }
                });
            });
            document.addEventListener("fullscreenchange", function() {
                setTimeout(function() {
                    try { pz.resize(); pz.fit(); pz.center(); } catch(e) {}
                }, 50);
            });
        });
    }).catch(function() {});
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
            .replace("{{RICH_FOOT}}", rich_foot) \
            .replace("{{DIAGRAMS_HEAD}}", diagrams_head) \
            .replace("{{DIAGRAM_BLOCK}}", diagram_block) \
            .replace("{{DIAGRAMS_FOOT}}", diagrams_foot)
        return result


EXPORTER_REGISTRY = {
    "md": MarkdownExporter,
    "html": HTMLExporter,
    "txt": TextExporter,
    "tex": TeXExporter,
}


# Back-compat module-level shims for the existing pytest suite and any
# downstream callers that import these names directly. Each is a thin wrapper
# over the corresponding Exporter or HTMLExporter static method.

def export_markdown(session, no_truncate=False):
    """Export session as Markdown. Thin wrapper over MarkdownExporter."""
    return MarkdownExporter(session, no_truncate=no_truncate).format()


def export_txt(session):
    """Export session as plain text. Thin wrapper over TextExporter."""
    return TextExporter(session).format()


def export_tex(session):
    """Export session as LaTeX. Thin wrapper over TeXExporter."""
    return TeXExporter(session).format()


def export_html(session, embedded=False, rich=False, diagrams=False, no_truncate=False):
    """Export session as HTML. Thin wrapper over HTMLExporter."""
    return HTMLExporter(
        session,
        embedded=embedded,
        rich=rich,
        diagrams=diagrams,
        no_truncate=no_truncate,
    ).format()


def _md_table_to_html(text):
    return HTMLExporter._md_table_to_html(text)


def _render_table(lines):
    return HTMLExporter._render_table(lines)


def _auto_link_urls(text):
    return HTMLExporter._auto_link_urls(text)


def _build_sequence_diagram(session):
    return HTMLExporter._build_sequence_diagram(session)


# ─── Behavioral profiling ─────────────────────────────────────────────────────
#
# A per-model "how it works" fingerprint over Turns (one user prompt + the
# assistant's full multi-event response): reasoning presence, think-before-action,
# first-tool distribution, tool intensity, narration length. Powers `profile` and
# `compare`. Operates on Turn objects (Session.turns), NOT raw events — so
# "how it opens a task" and "does it think before acting" are measured per
# response, with thinking-only events preserved by the parser.

def behavioral_profile(turns):
    """Compute behavioral metrics over a list of Turn objects (already model-filtered)."""
    from collections import Counter
    n = len(turns)
    reasoning = sum(1 for t in turns if t.has_reasoning)
    tool_turns = [t for t in turns if t.first_tool is not None]
    nt = len(tool_turns)
    tba = sum(1 for t in tool_turns if t.think_before_action)
    return {
        "turns": n,
        "reasoning_pct": (100.0 * reasoning / n) if n else 0.0,
        "tool_turns": nt,
        "think_before_action_pct": (100.0 * tba / nt) if nt else 0.0,
        "tool_calls_per_turn": (sum(t.n_tools for t in turns) / n) if n else 0.0,
        "avg_text_chars": (sum(t.narration_chars for t in turns) / n) if n else 0.0,
        "avg_think_chars": (sum(t.thinking_chars for t in turns) / n) if n else 0.0,
        "first_tools": Counter(t.first_tool for t in tool_turns),
    }


def collect_turns(sessions, model_filter=None):
    """Return dict model -> list[Turn] across sessions.

    A turn's model is its first assistant event's model. model_filter
    (case-insensitive substring) restricts which models are kept.
    """
    from collections import defaultdict
    nl = model_filter.lower() if model_filter else None
    groups = defaultdict(list)
    for s in sessions:
        s.parse()
        for t in s.turns:
            if not t.model:
                continue
            if nl and nl not in t.model.lower():
                continue
            groups[t.model].append(t)
    return groups


def collect_assistant_messages(sessions, model_filter=None):
    """Return dict model -> list[Message] of assistant turns across sessions.

    model_filter (case-insensitive substring) restricts which models are kept.
    Retained for callers that want per-message (not per-turn) granularity.
    """
    from collections import defaultdict
    nl = model_filter.lower() if model_filter else None
    groups = defaultdict(list)
    for s in sessions:
        s.parse()
        for m in s.messages:
            if m.role != "assistant" or not m.model:
                continue
            if nl and nl not in m.model.lower():
                continue
            groups[m.model].append(m)
    return groups


def format_profile(label, p):
    """Render one behavioral_profile() dict as an indented block."""
    tools = ", ".join(f"{n}:{c}" for n, c in p["first_tools"].most_common(5)) or "(none)"
    return "\n".join([
        f"  {label}",
        f"    turns (responses):    {p['turns']}",
        f"    reasoning present:    {p['reasoning_pct']:.0f}%",
        f"    think before action:  {p['think_before_action_pct']:.0f}%  (of {p['tool_turns']} tool-turns)",
        f"    tool calls/turn:      {p['tool_calls_per_turn']:.2f}",
        f"    avg narration chars:  {p['avg_text_chars']:.0f}",
        f"    avg thinking chars:   {p['avg_think_chars']:.0f}  (0 = encrypted/absent in transcript)",
        f"    top first-tools:      {tools}",
    ])


# ─── Commands ────────────────────────────────────────────────────────────────

class Command:
    """Base class for CLI commands.

    Earns existence: holds the parsed argparse Namespace as state, and
    declares a contract (execute() must be implemented, name+aliases declared
    for registry dispatch). The argparse Namespace IS the per-invocation
    state that execute() reads to do its work — class invariant: args is
    always set at construction time.
    """

    name = ""              # override: matches argparse subcommand
    aliases = ()           # override: list of alternate names

    def __init__(self, args):
        self.args = args

    def execute(self):
        """Run the command. Subclasses must override."""
        raise NotImplementedError


class ListCommand(Command):
    """List all sessions with summaries."""

    name = "list"
    aliases = ("ls",)

    def execute(self):
        args = self.args
        sessions = find_all_sessions(args.project)
        if not sessions:
            print("No sessions found.")
            return

        # --model: keep only sessions with assistant turns from a matching model.
        # Opt-in, so the default fast path (no full parse) is unchanged.
        model_filter = getattr(args, "model", None)
        if model_filter:
            sessions = [s for s in sessions if s.has_model(model_filter)]
            if not sessions:
                print(f'No sessions with a model matching "{model_filter}".')
                return

        limit = args.limit or 20
        detail = getattr(args, "detail", False)
        interactive = getattr(args, "_interactive", False)
        current_project = None

        shown = sessions[:limit]
        if interactive:
            _interactive_index.clear()
            _interactive_index.extend(shown)

        for i, s in enumerate(shown, start=1):
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
            summary = s.smart_headline(80) if getattr(args, "smart", False) else s.summary(80)
            num = f"[{i:>3}] " if interactive else ""
            tag = "  >sub " if s.is_subagent else "       "
            print(f"  {num}{s.short_id}{tag}{s.modified.strftime('%Y-%m-%d %H:%M')}  {size_kb:6.0f}KB  {age_str:>8}  {summary}")

            if detail:
                previews = _session_preview(s)
                for p in previews:
                    print(f"              > {p}")
                if previews:
                    print()

        save_headline_cache()
        total = len(sessions)
        if total > limit:
            print(f"\n  ... and {total - limit} more. Use --limit {total} to see all.")
        print(f"\n  Total: {total} sessions across {len(set(s.project for s in sessions))} project(s)")
        if interactive:
            print(f"  Tip: use the number, e.g. `export 1 --format html` or `open 2`")


class SearchCommand(Command):
    """Search across all conversations (or within a single session via --in)."""

    name = "search"
    aliases = ("grep", "find")

    def execute(self):
        args = self.args
        query = args.query.lower()
        context = max(0, getattr(args, "context", 40))
        in_session_id = getattr(args, "in_session", None)
        tools_only = getattr(args, "tools", False)
        no_truncate = getattr(args, "no_truncate", False)

        scanner = SessionScanner(query, context=context, tools_only=tools_only, no_truncate=no_truncate)

        # Date-range filter (by session mtime). YYYY-MM-DD; --before is inclusive of that day.
        try:
            after_dt = _parse_date_filter(getattr(args, "after", None), end_of_day=False)
            before_dt = _parse_date_filter(getattr(args, "before", None), end_of_day=True)
        except ValueError as e:
            print(e)
            return

        # Source of sessions
        if in_session_id:
            target = find_session(in_session_id)
            if not target:
                print(f"Session not found: {in_session_id}")
                print("Use 'claude-chat.py list' to see available sessions.")
                return
            sessions = [target]
        else:
            sessions = find_all_sessions(args.project)

        if after_dt:
            sessions = [s for s in sessions if s.modified >= after_dt]
        if before_dt:
            sessions = [s for s in sessions if s.modified <= before_dt]

        # --model: restrict to sessions containing turns from a matching model
        # (session-level scope; the snippet itself isn't model-tagged yet).
        model_filter = getattr(args, "model", None)
        if model_filter:
            sessions = [s for s in sessions if s.has_model(model_filter)]

        results = []
        for s in sessions:
            try:
                s.parse()
                count, contexts = scanner.scan(s)
                if count > 0:
                    results.append((s, count, contexts))
            except (IOError, OSError):
                continue

        if not results:
            field_tag = " in tool calls" if tools_only else ""
            print(f'No results for "{args.query}"{field_tag}')
            # Project-miss suggestion: filter was set, no hits in that project — check elsewhere.
            if args.project and not in_session_id:
                other_projects = {}
                for s in find_all_sessions(None):
                    if args.project.lower() in s.project.lower():
                        continue  # already searched
                    try:
                        s.parse()
                        c, _ = scanner.scan(s)
                        if c > 0:
                            other_projects[s.project] = other_projects.get(s.project, 0) + c
                    except (IOError, OSError):
                        continue
                if other_projects:
                    print(f"\nDid you mean a different project? Matches outside '--project {args.project}':")
                    for p, n in sorted(other_projects.items(), key=lambda x: -x[1])[:5]:
                        print(f"  --project {p}  ({n} match(es))")
            return

        results.sort(key=lambda r: r[1], reverse=True)
        field_tag = " (tool-call inputs)" if tools_only else ""
        if in_session_id:
            s = results[0][0]
            print(f'Found "{args.query}" in session {s.short_id}{field_tag} — {results[0][1]} match(es):\n')
        else:
            print(f'Found "{args.query}" in {len(results)} session(s){field_tag}:\n')

        # When scoped to one session, show all matches; otherwise summarize per-session.
        preview_limit = 50 if in_session_id else 3

        for s, count, contexts in results[:args.limit or 20]:
            if not in_session_id:
                print(f"  {s.short_id}  {s.modified.strftime('%Y-%m-%d %H:%M')}  {count} matches  [{s.project}]")
            for role, snippet in contexts[:preview_limit]:
                role_tag = "YOU" if role == "user" else "AI "
                if no_truncate and "\n" in snippet:
                    # Multi-line snippet (full message): prefix first line with role tag, indent rest.
                    lines = snippet.splitlines()
                    print(f"    {role_tag}: {lines[0]}")
                    for cont_line in lines[1:]:
                        print(f"         {cont_line}")
                    print(f"    {'-' * 40}")  # visual separator between full-message snippets
                else:
                    print(f"    {role_tag}: {snippet}")
            if len(contexts) > preview_limit:
                print(f"    ... and {len(contexts) - preview_limit} more matches")
            print()

        print("Tip: `export <id> --format md` for human-reading (tool inputs truncated at 500 chars).")
        print("     `export <id> --format md --no-truncate` for byte-perfect file/edit recovery.")
        print("     `search ... --no-truncate` shows full message containing each match (vs. ±context snippet).")


class ExportCommand(Command):
    """Export a session to various formats."""

    name = "export"
    aliases = ()

    def execute(self):
        args = self.args

        session = self._resolve_session()
        if session is None:
            return

        session.parse()
        fmt = args.format or "md"
        out_dir = Path(args.output) if args.output else Path(".")
        no_truncate = getattr(args, "no_truncate", False)

        exporter_cls = EXPORTER_REGISTRY.get(fmt)
        if exporter_cls is None:
            print(f"Unknown format: {fmt}. Use: md, html, txt, tex")
            return

        exporter = exporter_cls(
            session,
            no_truncate=no_truncate,
            rich=getattr(args, "rich", False),
            diagrams=getattr(args, "diagrams", False),
        )
        content = exporter.format()
        ext = exporter_cls.extension

        # --stdout: emit to stdout for piping (grep, redirect) instead of writing a file.
        if getattr(args, "stdout", False):
            sys.stdout.write(content)
            if not content.endswith("\n"):
                sys.stdout.write("\n")
            return

        filename = f"claude-chat_{session.short_id}_{session.modified.strftime('%Y%m%d')}{ext}"
        out_path = out_dir / filename

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Exported to: {out_path}")

        if args.open:
            webbrowser.open(str(out_path.resolve()))

    def _resolve_session(self):
        """Resolve session from --file or session_id arg. Returns Session or None on error (prints message)."""
        args = self.args
        if getattr(args, "file", None):
            if args.session_id:
                print("Pass either session_id OR --file, not both.")
                return None
            file_path = Path(args.file)
            if not file_path.is_file():
                print(f"File not found: {file_path}")
                return None
            return Session(file_path)

        if not args.session_id:
            print("Provide a session_id or use --file <path>.")
            return None
        session = find_session(args.session_id)
        if not session:
            print(f"Session not found: {args.session_id}")
            print("Use 'claude-chat.py list' to see available sessions.")
            return None
        return session


class BackupCommand(Command):
    """Backup sessions with optional watch mode."""

    name = "backup"
    aliases = ()

    def execute(self):
        args = self.args
        backup_dir = Path(args.output) if args.output else BACKUP_DIR
        sessions = find_all_sessions(args.project)

        if args.watch:
            print(f"=== Claude Chat Backup Watcher ===")
            print(f"Backup dir:    {backup_dir}")
            print(f"Poll interval: {args.interval}s")
            print(f"Projects:      {len(set(s.project for s in sessions))}")
            print(f"\nInitial backup...")

        # State carried across watch loop iterations.
        self._file_states = {}
        self._backed_up = 0
        self._backup_dir = backup_dir

        self._do_backup()
        print(f"  {self._backed_up} session(s) backed up to {backup_dir}")

        if args.watch:
            print(f"\nWatching for changes (Ctrl+C to stop)...\n")
            try:
                while True:
                    time.sleep(args.interval)
                    n = self._do_backup()
                    if n:
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {n} file(s) updated")
            except KeyboardInterrupt:
                print(f"\nStopped. Total backed up: {self._backed_up}")

    def _do_backup(self):
        """One pass: copy changed sessions, prune old per-session backups."""
        count = 0
        for s in find_all_sessions(self.args.project):
            key = str(s.path)
            current = (s.size, s._stat.st_mtime)
            if key not in self._file_states or self._file_states[key] != current:
                self._file_states[key] = current
                project_backup = self._backup_dir / s.project
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
                self._backed_up += 1
        return count


class StatsCommand(Command):
    """Show usage statistics."""

    name = "stats"
    aliases = ()

    def execute(self):
        args = self.args
        sessions = find_all_sessions(args.project)
        if not sessions:
            print("No sessions found.")
            return

        model_filter = getattr(args, "model", None)
        if model_filter:
            sessions = [s for s in sessions if s.has_model(model_filter)]
            if not sessions:
                print(f'No sessions with a model matching "{model_filter}".')
                return

        total_size = sum(s.size for s in sessions)
        projects = set(s.project for s in sessions)

        # Parse a sample for deeper stats
        total_user_msgs = 0
        total_asst_msgs = 0
        total_tool_calls = 0
        total_code_blocks = 0
        models_turns = {}     # per-TURN model counts (a session can be multi-model)
        mixed_sessions = 0
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
                    if m.model:
                        models_turns[m.model] = models_turns.get(m.model, 0) + 1
            total_code_blocks += len(s.code_blocks())
            if s.is_mixed():
                mixed_sessions += 1

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

        if models_turns:
            print(f"\n  Models (by turn):")
            for model, count in sorted(models_turns.items(), key=lambda x: -x[1]):
                print(f"    {model}: {count} turn(s)")
            print(f"    (mixed-model sessions: {mixed_sessions})")

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


class ExtractCommand(Command):
    """Extract specific content from a session."""

    name = "extract"
    aliases = ()

    def execute(self):
        args = self.args
        session = find_session(args.session_id)
        if not session:
            print(f"Session not found: {args.session_id}")
            return

        session.parse()

        no_truncate = getattr(args, "no_truncate", False)
        limit = getattr(args, "limit", None)

        if getattr(args, "turns", False):
            self._extract_turns(session)
        elif args.code:
            self._extract_code(session)
        elif args.ideas:
            self._extract_ideas(session, no_truncate=no_truncate, limit=limit)
        elif args.decisions:
            self._extract_decisions(session, no_truncate=no_truncate, limit=limit)
        else:
            print("Specify what to extract: --turns, --code, --ideas, or --decisions")

    @staticmethod
    def _extract_turns(session):
        """Emit one compact JSON object per turn (ts, role, model, tools, text).

        Pipe-friendly and low-bloat — the per-turn substrate for downstream
        analysis/priming, without ramming raw JSONL (with all its metadata) into
        context. Mirrors the strip-to-essentials move.
        """
        for m in session.messages:
            rec = {"ts": m.timestamp, "role": m.role}
            if m.role == "assistant":
                rec["model"] = m.model
                if m.tool_calls:
                    rec["tools"] = [tc.name for tc in m.tool_calls]
            rec["text"] = m.text
            print(json.dumps(rec, ensure_ascii=False))

    @staticmethod
    def _extract_code(session):
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

    @staticmethod
    def _extract_ideas(session, no_truncate=False, limit=None):
        print(f"Your messages in session {session.short_id}:\n")
        cap = None if no_truncate else (limit if limit else 300)
        for m in session.user_messages():
            clean = m.text.strip()
            if len(clean) > 10:
                if cap is None or len(clean) <= cap:
                    print(f"  > {clean}")
                else:
                    print(f"  > {clean[:cap]}")
                    print(f"    [...{len(clean)} chars]")
                print()

    @staticmethod
    def _extract_decisions(session, no_truncate=False, limit=None):
        # Search for decision-like patterns
        patterns = [
            r"(?i)(let'?s? go with|decided|decision|chose|picking|option \d|we('ll| will) use)",
            r"(?i)(the plan is|approach:|strategy:|going with|settled on)",
        ]
        # Snippet window: default 30 before / 100 after match. --limit N splits N as 1/4 before, 3/4 after.
        # --no-truncate shows the full message containing the match.
        pre, post = 30, 100
        if limit:
            pre = max(0, limit // 4)
            post = max(0, limit - pre)
        print(f"Decisions in session {session.short_id}:\n")
        found = 0
        for m in session.messages:
            if not m.text:
                continue
            for pat in patterns:
                for match in re.finditer(pat, m.text):
                    if no_truncate:
                        snippet = m.text.replace("\n", " ").strip()
                        who = "You" if m.role == "user" else "AI"
                        print(f"  [{who}] {snippet}")
                    else:
                        start = max(0, match.start() - pre)
                        end = min(len(m.text), match.end() + post)
                        snippet = m.text[start:end].replace("\n", " ")
                        who = "You" if m.role == "user" else "AI"
                        print(f"  [{who}] ...{snippet}...")
                    found += 1
                    break
        if not found:
            print("  No explicit decisions found.")


class ProfileCommand(Command):
    """Behavioral fingerprint of each model across sessions (how it works, not what)."""

    name = "profile"
    aliases = ()

    def execute(self):
        args = self.args
        in_session_id = getattr(args, "in_session", None)
        if in_session_id:
            s = find_session(in_session_id)
            if not s:
                print(f"Session not found: {in_session_id}")
                return
            sessions = [s]
        else:
            sessions = find_all_sessions(args.project)
        if not sessions:
            print("No sessions found.")
            return

        groups = collect_turns(sessions, getattr(args, "model", None))
        if not groups:
            print("No assistant turns matched.")
            return

        scope = f"session {sessions[0].short_id}" if in_session_id else f"{len(sessions)} session(s)"
        print(f"Behavioral profile over {scope}:\n")
        for model in sorted(groups, key=lambda k: -len(groups[k])):
            print(format_profile(model, behavioral_profile(groups[model])))
            print()


class CompareCommand(Command):
    """Compare the behavioral profiles of two models, side by side (delta table)."""

    name = "compare"
    aliases = ("diff",)

    def execute(self):
        args = self.args
        in_session_id = getattr(args, "in_session", None)
        if in_session_id:
            s = find_session(in_session_id)
            if not s:
                print(f"Session not found: {in_session_id}")
                return
            sessions = [s]
        else:
            sessions = find_all_sessions(args.project)
        if not sessions:
            print("No sessions found.")
            return

        a_flat = [t for ts in collect_turns(sessions, args.model_a).values() for t in ts]
        b_flat = [t for ts in collect_turns(sessions, args.model_b).values() for t in ts]
        if not a_flat:
            print(f'No turns matched model "{args.model_a}".')
            return
        if not b_flat:
            print(f'No turns matched model "{args.model_b}".')
            return

        pa, pb = behavioral_profile(a_flat), behavioral_profile(b_flat)
        scope = f"session {sessions[0].short_id}" if in_session_id else f"{len(sessions)} session(s)"
        print(f'Compare "{args.model_a}" vs "{args.model_b}" over {scope}:\n')

        rows = [
            ("turns (responses)", str(pa["turns"]), str(pb["turns"])),
            ("reasoning present %", f"{pa['reasoning_pct']:.0f}%", f"{pb['reasoning_pct']:.0f}%"),
            ("think before action %", f"{pa['think_before_action_pct']:.0f}%", f"{pb['think_before_action_pct']:.0f}%"),
            ("tool calls/turn", f"{pa['tool_calls_per_turn']:.2f}", f"{pb['tool_calls_per_turn']:.2f}"),
            ("avg narration chars", f"{pa['avg_text_chars']:.0f}", f"{pb['avg_text_chars']:.0f}"),
            ("avg thinking chars", f"{pa['avg_think_chars']:.0f}", f"{pb['avg_think_chars']:.0f}"),
        ]
        wlabel = max(len(r[0]) for r in rows)
        ca, cb = args.model_a[:18], args.model_b[:18]
        print(f"  {'metric'.ljust(wlabel)}   {ca.rjust(18)}   {cb.rjust(18)}")
        for name, a, b in rows:
            print(f"  {name.ljust(wlabel)}   {a.rjust(18)}   {b.rjust(18)}")

        print(f"\n  first-tool mix (A | B, % of that model's tool-turns):")
        for t in sorted(set(pa["first_tools"]) | set(pb["first_tools"])):
            ta = 100.0 * pa["first_tools"].get(t, 0) / pa["tool_turns"] if pa["tool_turns"] else 0
            tb = 100.0 * pb["first_tools"].get(t, 0) / pb["tool_turns"] if pb["tool_turns"] else 0
            print(f"    {t.ljust(12)} {ta:5.0f}% | {tb:5.0f}%")


class ServeCommand(Command):
    """Start a local web server to browse conversations."""

    name = "serve"
    aliases = ("web", "browse")

    def execute(self):
        args = self.args
        port = args.port or 3456
        smart = getattr(args, "smart", False)

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
                model_filter = query.get("model", [None])[0]
                sessions = find_all_sessions(project_filter)
                if model_filter:
                    sessions = [s for s in sessions if s.has_model(model_filter)]

                rows = []
                for s in sessions:
                    summary_text = html_mod.escape(s.smart_headline(120) if smart else s.summary(120))
                    size_kb = s.size / 1024
                    rows.append(f"""
                    <tr onclick="window.location='/session/{s.short_id}'" style="cursor:pointer">
                        <td class="mono">{s.short_id}</td>
                        <td>{s.modified.strftime('%Y-%m-%d %H:%M')}</td>
                        <td>{size_kb:.0f} KB</td>
                        <td class="project">{html_mod.escape(s.project[:40])}</td>
                        <td>{summary_text}</td>
                    </tr>""")

                save_headline_cache()
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
                html_content = HTMLExporter(session, embedded=True).format()
                self._send_html(html_content)

            def _serve_search(self, query):
                q = query.get("q", [""])[0]
                model_filter = query.get("model", [None])[0]
                if not q:
                    self._send_html("<html><body>No query</body></html>")
                    return

                sessions = find_all_sessions()
                if model_filter:
                    sessions = [s for s in sessions if s.has_model(model_filter)]
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
                    summary_text = html_mod.escape(s.smart_headline(100) if smart else s.summary(100))
                    rows.append(f"""
                    <tr onclick="window.location='/session/{s.short_id}'" style="cursor:pointer">
                        <td class="mono">{s.short_id}</td>
                        <td>{count} hits</td>
                        <td>{s.modified.strftime('%Y-%m-%d %H:%M')}</td>
                        <td>{summary_text}</td>
                    </tr>""")

                save_headline_cache()
                page = WEB_TEMPLATE_SEARCH.replace("{{ROWS}}", "\n".join(rows))
                page = page.replace("{{QUERY}}", html_mod.escape(q))
                page = page.replace("{{COUNT}}", str(len(results)))
                page = page.replace("{{MODEL_NOTE}}",
                                    f" · model: {html_mod.escape(model_filter)}" if model_filter else "")
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


class WikiCommand(Command):
    """Build a static cross-linked HTML archive of all sessions.

    Output tree:
      <out>/index.html             — all sessions, live client-side search
      <out>/search-index.json      — index data (also inlined into index.html)
      <out>/sessions/<short>.html  — one page per session, with backlinks
    """

    name = "wiki"
    aliases = ("archive",)

    BODY_CAP = 30000  # chars per session in the search index
    SHORT_ID_RE = re.compile(r"\b([0-9a-f]{8})\b", re.IGNORECASE)

    def execute(self):
        args = self.args
        out_dir = Path(args.output) if args.output else (Path.home() / "claude-chat-wiki")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "sessions").mkdir(exist_ok=True)

        sessions = find_all_sessions(args.project)
        if not sessions:
            print("No sessions found.")
            return

        print(f"Building wiki for {len(sessions)} session(s) -> {out_dir}")

        parsed = self._parse_sessions(sessions)
        short_ids = {s.short_id for s in parsed}
        references = self._build_backlinks(parsed, short_ids)
        search_idx, index_json_str = self._build_search_index(parsed, out_dir)
        self._write_session_pages(parsed, short_ids, references, out_dir)
        self._write_index_html(parsed, index_json_str, out_dir)

        print(f"Wiki built: {out_dir}")
        print(f"Open: {(out_dir / 'index.html').resolve()}")

        if getattr(args, "open", False):
            webbrowser.open(str((out_dir / "index.html").resolve()))

    @staticmethod
    def _parse_sessions(sessions):
        parsed = []
        for s in sessions:
            try:
                s.parse()
                parsed.append(s)
            except (IOError, OSError):
                continue
        return parsed

    def _build_backlinks(self, parsed, short_ids):
        """short_id -> set of session short_ids that mention it."""
        references = {sid: set() for sid in short_ids}
        for s in parsed:
            mentioned = set()
            for m in s.messages:
                if not m.text:
                    continue
                for match in self.SHORT_ID_RE.findall(m.text):
                    ml = match.lower()
                    if ml in short_ids and ml != s.short_id:
                        mentioned.add(ml)
            for sid in mentioned:
                references[sid].add(s.short_id)
        return references

    def _build_search_index(self, parsed, out_dir):
        """Build the JSON search index (capped per session) and write search-index.json."""
        search_idx = []
        for s in parsed:
            body_chunks = []
            running = 0
            for m in s.messages:
                if m.text:
                    body_chunks.append(m.text)
                    running += len(m.text)
                    if running > self.BODY_CAP:
                        break
                # Also surface tool-call inputs as searchable text.
                for tc in m.tool_calls:
                    for _, val in _iter_tool_call_strings(tc):
                        body_chunks.append(val)
                        running += len(val)
                        if running > self.BODY_CAP:
                            break
                    if running > self.BODY_CAP:
                        break
            body = " ".join(body_chunks)
            if len(body) > self.BODY_CAP:
                body = body[:self.BODY_CAP]
            search_idx.append({
                "short_id": s.short_id,
                "project": s.project,
                "date": s.modified.strftime("%Y-%m-%d %H:%M"),
                "size_kb": int(s.size / 1024),
                "summary": s.summary(140),
                "body": body,
            })

        # Write the separate JSON too (handy for programmatic use).
        with open(out_dir / "search-index.json", "w", encoding="utf-8") as f:
            json.dump(search_idx, f, separators=(",", ":"))
        index_json_str = json.dumps(search_idx, separators=(",", ":"))
        # Escape "</" so a literal "</script>" inside session data cannot terminate
        # the surrounding <script> tag. JSON parsers accept "<\/". U+2028 / U+2029
        # are already escaped by json.dumps (ensure_ascii=True by default).
        index_json_str = index_json_str.replace("</", "<\\/")
        total_mb = len(index_json_str) / (1024 * 1024)
        print(f"  search index: {total_mb:.1f} MB")
        return search_idx, index_json_str

    def _write_session_pages(self, parsed, short_ids, references, out_dir):
        """Write one HTML page per session with cross-links and backlinks footer."""
        rich = getattr(self.args, "rich", False)
        for s in parsed:
            html = HTMLExporter(s, embedded=True, rich=rich).format()
            # Re-target the embedded back-link.
            html = html.replace('href="/"', 'href="../index.html"')
            # Cross-link 8-char hex short_ids -> sibling session pages.
            def linkify(match, current=s.short_id):
                sid = match.group(1).lower()
                if sid in short_ids and sid != current:
                    return f'<a class="xref" href="{sid}.html">{match.group(1)}</a>'
                return match.group(1)
            html = self.SHORT_ID_RE.sub(linkify, html)
            # Backlinks footer.
            refs = sorted(references.get(s.short_id, set()))
            if refs:
                backlinks = (
                    '<div style="margin:24px 16px;padding:12px;border-top:1px solid #3e3e3e;'
                    'color:#888;font-size:13px"><strong>Referenced by:</strong> '
                    + " · ".join(f'<a href="{r}.html" style="color:#569cd6">{r}</a>' for r in refs)
                    + "</div>"
                )
                html = html.replace("</body>", backlinks + "</body>")
            with open(out_dir / "sessions" / f"{s.short_id}.html", "w", encoding="utf-8") as f:
                f.write(html)

    @staticmethod
    def _write_index_html(parsed, index_json_str, out_dir):
        index_html = WIKI_INDEX_TEMPLATE.replace("{{COUNT}}", str(len(parsed)))
        index_html = index_html.replace("{{PROJECT_COUNT}}", str(len({s.project for s in parsed})))
        index_html = index_html.replace("{{INDEX_JSON}}", index_json_str)
        with open(out_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)


class ProtectCommand(Command):
    """Prevent Claude Code from auto-deleting old sessions."""

    name = "protect"
    aliases = ()

    def execute(self):
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


# ─── Command Registry ────────────────────────────────────────────────────────

def _build_command_registry():
    """Map every command name + alias to its Command class."""
    classes = [
        ListCommand, SearchCommand, ExportCommand, BackupCommand,
        StatsCommand, ExtractCommand, ProfileCommand, CompareCommand,
        ServeCommand, WikiCommand, ProtectCommand,
    ]
    registry = {}
    for cls in classes:
        registry[cls.name] = cls
        for alias in cls.aliases:
            registry[alias] = cls
    return registry


COMMAND_REGISTRY = _build_command_registry()


# Back-compat module-level shims for callers that still want cmd_* functions
# (the existing pytest suite uses these). Each is a thin wrapper that builds
# the right Command and calls execute().

def cmd_list(args):
    ListCommand(args).execute()


def cmd_search(args):
    SearchCommand(args).execute()


def cmd_export(args):
    ExportCommand(args).execute()


def cmd_backup(args):
    BackupCommand(args).execute()


def cmd_stats(args):
    StatsCommand(args).execute()


def cmd_extract(args):
    ExtractCommand(args).execute()


def cmd_serve(args):
    ServeCommand(args).execute()


def cmd_wiki(args):
    WikiCommand(args).execute()


def cmd_protect(args):
    ProtectCommand(args).execute()


# ─── HTML Templates ──────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Chat: {{SESSION_ID}}</title>
{{RICH_HEAD}}
{{DIAGRAMS_HEAD}}
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
{{DIAGRAM_BLOCK}}
{{MESSAGES}}
<div class="footer">Exported with claude-chat v""" + __version__ + """</div>
{{RICH_FOOT}}
{{DIAGRAMS_FOOT}}
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
    this.querySelector('button').textContent='Searching…';
    this.querySelector('button').style.opacity='0.6';
    this.querySelector('input').style.opacity='0.6';
">
    <input type="text" name="q" placeholder="Search across all conversations..." autofocus>
    <input type="text" name="model" placeholder="model (e.g. fable)" style="max-width:180px">
    <button type="submit">Search</button>
</form>
<table>
<tr><th>Session</th><th>Date</th><th>Size</th><th>Project</th><th>Summary</th></tr>
{{ROWS}}
</table>
</body>
</html>"""

WIKI_INDEX_TEMPLATE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Claude Chat Archive</title>
<style>
:root { --bg:#1e1e1e; --fg:#d4d4d4; --accent:#569cd6; --border:#3e3e3e; --muted:#888; }
* { box-sizing: border-box; }
body { background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; margin:0; padding:20px; }
h1 { color:var(--accent); margin:0 0 4px 0; }
.meta { color:var(--muted); font-size:13px; margin-bottom:16px; }
.controls { display:flex; gap:10px; margin-bottom:14px; flex-wrap:wrap; }
input, select { background:#2d2d2d; color:var(--fg); border:1px solid var(--border); padding:8px 12px; border-radius:4px; font-size:14px; font-family:inherit; }
input { flex:1; min-width:260px; }
table { width:100%; border-collapse:collapse; }
th, td { padding:7px 10px; text-align:left; border-bottom:1px solid var(--border); vertical-align:top; }
th { font-weight:600; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:0.5px; }
tbody tr { cursor:pointer; }
tbody tr:hover { background:#2a2a2a; }
.mono { font-family:'SF Mono','Cascadia Code',Menlo,Consolas,monospace; color:var(--accent); }
.snippet { color:#aaa; font-size:12.5px; max-width:640px; }
.project-tag { font-size:11px; color:#999; }
mark { background:#664400; color:#fff; padding:0 2px; border-radius:2px; }
.count { color:var(--muted); align-self:center; font-size:13px; }
</style>
</head><body>
<h1>Claude Chat Archive</h1>
<div class="meta">{{COUNT}} sessions across {{PROJECT_COUNT}} project(s). Click a row to open. Search matches narrative + tool-call inputs.</div>
<div class="controls">
  <input id="q" placeholder="Search..." autofocus />
  <select id="project"><option value="">All projects</option></select>
  <span id="count" class="count"></span>
</div>
<table id="results">
  <thead><tr><th>ID</th><th>Date</th><th>Project</th><th>Summary / Match</th></tr></thead>
  <tbody></tbody>
</table>
<script>
const INDEX = {{INDEX_JSON}};
const projSet = new Set(INDEX.map(s => s.project));
const projSelect = document.getElementById('project');
[...projSet].sort().forEach(p => {
  const opt = document.createElement('option');
  opt.value = p; opt.textContent = p;
  projSelect.appendChild(opt);
});
function esc(s) { return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function reEscape(s) { return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'); }
function highlight(text, q) {
  if (!q) return esc(text);
  return esc(text).replace(new RegExp('(' + reEscape(q) + ')', 'gi'), '<mark>$1</mark>');
}
function snippet(body, q, width) {
  width = width || 80;
  const i = body.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return '';
  const start = Math.max(0, i - width);
  const end = Math.min(body.length, i + q.length + width);
  let snip = body.substring(start, end).replace(/\\s+/g, ' ');
  if (start > 0) snip = '...' + snip;
  if (end < body.length) snip += '...';
  return snip;
}
function render() {
  const q = document.getElementById('q').value.trim();
  const project = projSelect.value;
  const tbody = document.querySelector('#results tbody');
  tbody.innerHTML = '';
  let shown = 0;
  const ql = q.toLowerCase();
  for (const s of INDEX) {
    if (project && s.project !== project) continue;
    let snip = '';
    if (q) {
      const inSummary = s.summary.toLowerCase().includes(ql);
      const inBody = s.body.toLowerCase().includes(ql);
      if (!inSummary && !inBody) continue;
      snip = inBody ? snippet(s.body, q) : '';
    }
    const display = q ? (snip || s.summary) : s.summary;
    const row = document.createElement('tr');
    row.innerHTML =
      '<td class="mono">' + s.short_id + '</td>' +
      '<td>' + s.date + '</td>' +
      '<td class="project-tag">' + esc(s.project) + '</td>' +
      '<td class="snippet">' + highlight(display, q) + '</td>';
    row.addEventListener('click', () => { window.location = 'sessions/' + s.short_id + '.html'; });
    tbody.appendChild(row);
    shown++;
    if (shown >= 500) break;
  }
  document.getElementById('count').textContent = q ? (shown + ' match(es)') : (shown + ' of ' + INDEX.length + ' sessions');
}
document.getElementById('q').addEventListener('input', render);
projSelect.addEventListener('change', render);
render();
</script>
</body></html>"""


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
<div class="stats">{{COUNT}} session(s) found{{MODEL_NOTE}}</div>
<table>
<tr><th>Session</th><th>Matches</th><th>Date</th><th>Summary</th></tr>
{{ROWS}}
</table>
</body>
</html>"""


# ─── Main ────────────────────────────────────────────────────────────────────

_INTERACTIVE_HELP = (
    "  list                          Show recent sessions (numbered)\n"
    "  list --detail                 Show with topic previews\n"
    "  list --smart                  Smarter headlines (real ask / commit / edits)\n"
    "  list --project crystal        Filter by project\n"
    "  search \"react hooks\"          Search across all chats\n"
    "  export SESSION --format html  Export session (md/html/txt/tex)\n"
    "  export SESSION --format html --rich   Rich HTML (math, tables, links)\n"
    "  export SESSION --format html --diagrams   Add mermaid tool-call diagram\n"
    "  stats                         Usage statistics\n"
    "  extract SESSION --code        Extract code blocks\n"
    "  extract SESSION --ideas       Extract your messages\n"
    "  serve                         Open browser UI\n"
    "  backup --watch                Continuous backup\n"
    "  protect                       Prevent auto-deletion\n"
    "  help                          Show this help\n"
    "  quit                          Exit\n"
    "\n"
    "  SESSION can be a hash (a7e44ed0) OR a number from the last `list` —\n"
    "  e.g. after `list`, type `export 1` or `extract 2 --ideas`.\n"
    "\n"
    "  !command                      Run a shell command (e.g. !start file.html)\n"
    "\n"
    "  Tip: run 'protect' to stop auto-deletion (sets cleanupPeriodDays=99999)"
)

_VALID_COMMANDS = {
    "list", "ls", "search", "grep", "find", "export", "backup",
    "stats", "extract", "profile", "compare", "diff",
    "serve", "web", "browse", "wiki", "archive", "protect",
}


class Repl:
    """Interactive REPL.

    Earns existence: holds the shared argparse parser as state, manages the
    REPL input/parse/dispatch loop, and enforces the invariants around
    interactive mode (auto-marking args._interactive, substituting numbered
    refs, validating tokens before handing to argparse). The methods break
    up run() per concern (one method = one responsibility).
    """

    def __init__(self, parser):
        self.parser = parser

    def run(self):
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
                self._run_shell(line[1:].strip())
                continue

            tokens = self._tokenize(line)
            if tokens is None:
                continue

            args = self._parse_tokens(tokens)
            if args is None:
                continue

            self._dispatch(args)
            print()

    @staticmethod
    def _run_shell(shell_cmd):
        if shell_cmd:
            import subprocess
            try:
                subprocess.run(shell_cmd, shell=True)
            except Exception as e:
                print(f"  Shell error: {e}")
        else:
            print("  Usage: !command (e.g. !start file.html)")
        print()

    @staticmethod
    def _tokenize(line):
        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print(f"Parse error: {e}")
            return None

        # "command help" → "command --help"
        if len(tokens) == 2 and tokens[1] == "help":
            tokens[1] = "--help"

        # Check first token before handing to argparse (avoids ugly error dump)
        if tokens[0] not in _VALID_COMMANDS and not tokens[0].startswith("-"):
            print(f"  Unknown command: '{tokens[0]}'")
            print(f"  Try: list, search, export, stats, serve, help")
            print()
            return None

        # Substitute numbered refs (e.g. `export 1` → `export a7e44ed0`).
        orig_tokens = list(tokens)
        tokens = _substitute_numbered_refs(tokens)
        if tokens != orig_tokens:
            for o, n in zip(orig_tokens, tokens):
                if o != n and o.isdigit():
                    sess = next((s for s in _interactive_index if s.short_id == n), None)
                    if sess:
                        print(f"  [resolved {o} → {n}  \"{sess.summary(60)}\"]")
        return tokens

    def _parse_tokens(self, tokens):
        try:
            args = self.parser.parse_args(tokens)
        except SystemExit:
            # argparse calls sys.exit on --help or errors; catch it
            return None

        # Mark args so cmd_list knows to print numbers + populate the index
        if args.command in ("list", "ls"):
            args._interactive = True

        if not args.command:
            print("  Type a command or 'help' to see options.")
            return None

        return args

    @staticmethod
    def _dispatch(args):
        cmd_cls = COMMAND_REGISTRY.get(args.command)
        if cmd_cls is None:
            print(f"Unknown command: {args.command}")
            return
        try:
            cmd_cls(args).execute()
        except Exception as e:
            print(f"Error: {e}")


# Back-compat shim
def cmd_interactive(parser):
    """Interactive REPL mode. Thin wrapper over Repl."""
    Repl(parser).run()


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="claude-chat",
        description="One tool for all your Claude Code conversations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                          List recent sessions
  %(prog)s list --limit 100              Show more sessions
  %(prog)s list --smart                  Smarter headlines when first lines are useless
  %(prog)s search "react hooks"          Search across all chats
  %(prog)s search "auth" --in a7e44ed0   Search within ONE session (all matches)
  %(prog)s search "auth" -C 80           Wider context around each match (default 40)
  %(prog)s search "auth" --no-truncate   Show the full message containing each match
  %(prog)s search "auth" --after 2026-05-01 --before 2026-05-20   Date-range filter
  %(prog)s export a7e44ed0 --format html Export as HTML
  %(prog)s export a7e44ed0 --stdout | grep foo   Export to stdout for piping
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
    p.add_argument("--smart", "-s", action="store_true", help="Smarter headlines: first real ask / commit subject / edited files instead of the first message")
    p.add_argument("--model", "-m", help="Only sessions with turns from this model (substring, e.g. fable)")

    # search
    p = sub.add_parser("search", aliases=["grep", "find"], help="Search across all conversations")
    p.add_argument("query", help="Search query")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--limit", "-n", type=int, default=20, help="Max results")
    p.add_argument("--in", dest="in_session", metavar="SESSION_ID",
                   help="Limit search to a single session (full or short ID); shows all matches within that session")
    p.add_argument("--context", "-C", type=int, default=40,
                   help="Snippet context chars on each side of match (default 40)")
    p.add_argument("--tools", action="store_true",
                   help="Search tool-call inputs (Bash commands, file paths, etc.) instead of narrative text")
    p.add_argument("--no-truncate", action="store_true",
                   help="Show full message containing each match (preserves newlines, indents continuation lines). Overrides --context.")
    p.add_argument("--after", metavar="YYYY-MM-DD",
                   help="Only sessions modified on or after this date")
    p.add_argument("--before", metavar="YYYY-MM-DD",
                   help="Only sessions modified on or before this date (inclusive of the whole day)")
    p.add_argument("--model", "-m", help="Only sessions with turns from this model (substring, e.g. fable)")

    # export
    p = sub.add_parser("export", help="Export session to file")
    p.add_argument("session_id", nargs="?", help="Session ID (full or first 8 chars). Omit when using --file.")
    p.add_argument("--file", help="Path to a JSONL transcript file (e.g. a pre-compact export). Bypasses session lookup.")
    p.add_argument("--format", "-f", choices=["md", "html", "txt", "tex"], default="md", help="Output format")
    p.add_argument("--output", "-o", help="Output directory")
    p.add_argument("--stdout", action="store_true", help="Write export to stdout instead of a file (for piping/grep/redirect)")
    p.add_argument("--open", action="store_true", help="Open in browser/editor after export")
    p.add_argument("--rich", action="store_true", help="Rich HTML: clickable links, KaTeX math, tables")
    p.add_argument("--diagrams", action="store_true", help="HTML: include a mermaid sequenceDiagram of tool calls")
    p.add_argument("--no-truncate", action="store_true", help="Render full tool-call inputs (md/html). Default truncates at 500/400 chars for human reading; use this for byte-perfect file recovery.")

    # backup
    p = sub.add_parser("backup", help="Backup session files")
    p.add_argument("--watch", "-w", action="store_true", help="Watch continuously")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--output", "-o", help="Backup directory")
    p.add_argument("--interval", "-i", type=int, default=10, help="Poll interval (seconds)")

    # stats
    p = sub.add_parser("stats", help="Show usage statistics")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--model", "-m", help="Only sessions with turns from this model (substring, e.g. fable)")

    # extract
    p = sub.add_parser("extract", help="Extract content from session")
    p.add_argument("session_id", help="Session ID (full or first 8 chars)")
    p.add_argument("--turns", action="store_true", help="Compact per-turn JSONL dump (ts, role, model, tools, text) for analysis/piping")
    p.add_argument("--code", action="store_true", help="Extract code blocks")
    p.add_argument("--ideas", action="store_true", help="Extract your messages")
    p.add_argument("--decisions", action="store_true", help="Extract decision points")
    p.add_argument("--no-truncate", action="store_true", help="Show full content without character cap (applies to --ideas and --decisions)")
    p.add_argument("--limit", type=int, help="Per-item character cap (default: 300 for --ideas, ~130 for --decisions snippet window)")

    # profile — per-model behavioral fingerprint
    p = sub.add_parser("profile", help="Per-model behavioral fingerprint (reasoning %, first-tools, tool intensity)")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--in", dest="in_session", metavar="SESSION_ID", help="Scope to a single session (the within-session control)")
    p.add_argument("--model", "-m", help="Restrict to models matching this substring")

    # compare — two-model delta table
    p = sub.add_parser("compare", aliases=["diff"], help="Compare two models' behavioral profiles (delta table)")
    p.add_argument("model_a", help="First model (substring, e.g. fable)")
    p.add_argument("model_b", help="Second model (substring, e.g. opus)")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--in", dest="in_session", metavar="SESSION_ID", help="Scope to a single session (the within-session control)")

    # serve
    p = sub.add_parser("serve", aliases=["web", "browse"], help="Browse in your browser")
    p.add_argument("--port", type=int, default=3456, help="Port number")
    p.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    p.add_argument("--smart", "-s", action="store_true", help="Smarter session headlines (first real ask / commit subject / edited files)")

    # wiki
    p = sub.add_parser("wiki", aliases=["archive"], help="Build a static cross-linked HTML archive of all sessions")
    p.add_argument("--output", "-o", help="Output directory (default: ~/claude-chat-wiki)")
    p.add_argument("--project", "-p", help="Filter by project name")
    p.add_argument("--rich", action="store_true", help="Rich HTML rendering: KaTeX math, tables, auto-links")
    p.add_argument("--open", action="store_true", help="Open the wiki in a browser after building")

    # protect
    sub.add_parser("protect", help="Prevent auto-deletion of old sessions")

    return parser


def main():
    if sys.version_info < (3, 7):
        print("claude-chat requires Python 3.7 or later.")
        sys.exit(1)

    _fix_windows_encoding()

    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        Repl(parser).run()
        return

    cmd_cls = COMMAND_REGISTRY.get(args.command)
    if cmd_cls is None:
        print(f"Unknown command: {args.command}")
        return
    cmd_cls(args).execute()


if __name__ == "__main__":
    main()
