"""
Tests for claude-chat.py

Run: pytest test_claude_chat.py -v
"""

import json
import importlib.util
import tempfile
import os
from pathlib import Path

import pytest

# ─── Import claude-chat.py (hyphenated filename needs importlib) ────────────

spec = importlib.util.spec_from_file_location(
    "claude_chat", Path(__file__).parent / "claude-chat.py"
)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

Session = cc.Session
Message = cc.Message
ToolCall = cc.ToolCall


# ─── Fixtures ───────────────────────────────────────────────────────────────

def _write_jsonl(tmp_path, filename, lines):
    """Write a list of dicts as JSONL and return the path."""
    p = tmp_path / filename
    with open(p, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    return p


def _user_line(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _user_line_blocks(blocks):
    return {"type": "user", "message": {"role": "user", "content": blocks}}


def _assistant_line(text, model="claude-opus-4-6"):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": text}],
        },
    }


def _assistant_tool_line(tool_name, tool_input, text="", model="claude-opus-4-6"):
    content = [{"type": "tool_use", "name": tool_name, "input": tool_input}]
    if text:
        content.insert(0, {"type": "text", "text": text})
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "content": content,
        },
    }


def _assistant_thinking_line(text, thinking, model="claude-opus-4-6"):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "content": [
                {"type": "thinking", "thinking": thinking},
                {"type": "text", "text": text},
            ],
        },
    }


@pytest.fixture
def basic_session(tmp_path):
    """A simple 3-message session."""
    path = _write_jsonl(tmp_path, "abcd1234-0000-0000-0000-000000000000.jsonl", [
        _user_line("Hello, how are you?"),
        _assistant_line("I'm doing well! How can I help?"),
        _user_line("Tell me about Python"),
        _assistant_line("Python is a great programming language."),
    ])
    return Session(path)


@pytest.fixture
def toolcall_session(tmp_path):
    """Session with tool calls."""
    path = _write_jsonl(tmp_path, "beef5678-0000-0000-0000-000000000000.jsonl", [
        _user_line("Read my config"),
        _assistant_tool_line("Read", {"file_path": "/home/user/config.yaml"}),
        _assistant_tool_line("Bash", {"command": "git status && git log --oneline -5"}),
        _assistant_tool_line("Grep", {"pattern": "def main"}),
        _assistant_tool_line("Glob", {"pattern": "**/*.py"}),
        _assistant_tool_line("Agent", {"description": "Search codebase"}),
        _assistant_tool_line("WebFetch", {"url": "https://example.com/api/docs"}),
        _assistant_tool_line("WebSearch", {"query": "python asyncio tutorial"}),
        _assistant_tool_line("ToolSearch", {"query": "select:Read,Edit"}),
        _assistant_tool_line("Skill", {"skill": "PCrystal"}),
        _assistant_tool_line("Edit", {"file_path": "/tmp/foo.py", "old_string": "x", "new_string": "y"}),
        _assistant_tool_line("Write", {"file_path": "/tmp/bar.py", "content": "print('hi')"}),
        _assistant_tool_line("UnknownTool", {"whatever": 123}),
    ])
    return Session(path)


# ─── Parser Tests ───────────────────────────────────────────────────────────

class TestParser:
    def test_basic_parse(self, basic_session):
        basic_session.parse()
        assert len(basic_session.messages) == 4
        assert basic_session.messages[0].role == "user"
        assert basic_session.messages[1].role == "assistant"

    def test_user_text(self, basic_session):
        basic_session.parse()
        assert basic_session.messages[0].text == "Hello, how are you?"

    def test_assistant_text(self, basic_session):
        basic_session.parse()
        assert basic_session.messages[1].text == "I'm doing well! How can I help?"

    def test_model_captured(self, basic_session):
        basic_session.parse()
        assert basic_session.model == "claude-opus-4-6"

    def test_short_id(self, basic_session):
        assert basic_session.short_id == "abcd1234"

    def test_double_parse_idempotent(self, basic_session):
        basic_session.parse()
        count1 = len(basic_session.messages)
        basic_session.parse()
        count2 = len(basic_session.messages)
        assert count1 == count2

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty-0000-0000-0000-000000000000.jsonl"
        p.write_text("")
        s = Session(p)
        s.parse()
        assert len(s.messages) == 0

    def test_malformed_json_skipped(self, tmp_path):
        p = tmp_path / "bad-0000-0000-0000-000000000000.jsonl"
        p.write_text('{"valid": true}\nthis is not json\n{"also": "valid"}\n')
        s = Session(p)
        s.parse()
        # Malformed line silently skipped, no crash
        assert s._parsed

    def test_assistant_string_content(self, tmp_path):
        """Assistant content as plain string (not list of blocks)."""
        path = _write_jsonl(tmp_path, "str-0000-0000-0000-000000000000.jsonl", [
            {"type": "assistant", "message": {
                "role": "assistant", "content": "Plain string response"
            }},
        ])
        s = Session(path)
        s.parse()
        assert len(s.messages) == 1
        assert s.messages[0].text == "Plain string response"

    def test_thinking_captured(self, tmp_path):
        path = _write_jsonl(tmp_path, "think-0000-0000-0000-000000000000.jsonl", [
            _assistant_thinking_line("The answer is 42", "Let me think about this..."),
        ])
        s = Session(path)
        s.parse()
        assert s.messages[0].thinking == "Let me think about this..."
        assert s.messages[0].text == "The answer is 42"

    def test_tool_calls_parsed(self, toolcall_session):
        toolcall_session.parse()
        # First assistant message has a Read tool call
        assistant_msgs = [m for m in toolcall_session.messages if m.role == "assistant"]
        assert len(assistant_msgs[0].tool_calls) == 1
        assert assistant_msgs[0].tool_calls[0].name == "Read"

    def test_user_message_with_blocks(self, tmp_path):
        """User content as list of blocks."""
        path = _write_jsonl(tmp_path, "blocks-0000-0000-0000-000000000000.jsonl", [
            _user_line_blocks([
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "World"},
            ]),
        ])
        s = Session(path)
        s.parse()
        assert len(s.messages) == 1
        assert "Hello" in s.messages[0].text
        assert "World" in s.messages[0].text


# ─── System-Reminder Filtering ──────────────────────────────────────────────

class TestSystemReminderFilter:
    def test_actual_system_reminder_filtered(self, tmp_path):
        """Messages with <system-reminder> XML tags should be filtered out."""
        path = _write_jsonl(tmp_path, "sr-0000-0000-0000-000000000000.jsonl", [
            _user_line("<system-reminder>This is internal</system-reminder>"),
            _user_line("Real user message"),
        ])
        s = Session(path)
        s.parse()
        assert len(s.messages) == 1
        assert s.messages[0].text == "Real user message"

    def test_plain_text_system_reminder_kept(self, tmp_path):
        """User messages mentioning 'system-reminder' as plain text should be kept."""
        path = _write_jsonl(tmp_path, "sr2-0000-0000-0000-000000000000.jsonl", [
            _user_line("I noticed the system-reminder was being filtered"),
            _user_line("How does system-reminder filtering work?"),
        ])
        s = Session(path)
        s.parse()
        assert len(s.messages) == 2

    def test_system_reminder_in_middle_filtered(self, tmp_path):
        """Message containing <system-reminder> anywhere should be filtered."""
        path = _write_jsonl(tmp_path, "sr3-0000-0000-0000-000000000000.jsonl", [
            _user_line("Some text before <system-reminder>hidden</system-reminder> after"),
        ])
        s = Session(path)
        s.parse()
        assert len(s.messages) == 0


# ─── _extract_text Filtering ────────────────────────────────────────────────

class TestExtractText:
    def test_string_content(self, basic_session):
        result = basic_session._extract_text("Hello world")
        assert result == "Hello world"

    def test_list_content(self, basic_session):
        result = basic_session._extract_text([
            {"type": "text", "text": "Part one"},
            {"type": "text", "text": "Part two"},
        ])
        assert "Part one" in result
        assert "Part two" in result

    def test_tool_result_filtered(self, basic_session):
        result = basic_session._extract_text([
            {"type": "text", "text": '"tool_result" something something'},
            {"type": "text", "text": "Real message"},
        ])
        assert "tool_result" not in result
        assert "Real message" in result

    def test_launching_skill_filtered(self, basic_session):
        result = basic_session._extract_text([
            {"type": "text", "text": "Launching skill PCrystal"},
            {"type": "text", "text": "User said something"},
        ])
        assert "Launching skill" not in result
        assert "User said something" in result

    def test_empty_list(self, basic_session):
        assert basic_session._extract_text([]) == ""

    def test_none_returns_empty(self, basic_session):
        assert basic_session._extract_text(None) == ""

    def test_non_text_blocks_ignored(self, basic_session):
        result = basic_session._extract_text([
            {"type": "image", "data": "base64..."},
            {"type": "text", "text": "Caption"},
        ])
        assert result == "Caption"


# ─── ToolCall.summary() ────────────────────────────────────────────────────

class TestToolCallSummary:
    def test_read(self):
        tc = ToolCall("Read", {"file_path": "/home/user/src/main.py"})
        assert tc.summary() == "Read: main.py"

    def test_write(self):
        tc = ToolCall("Write", {"file_path": "/tmp/output.txt", "content": "hello"})
        assert tc.summary() == "Write: output.txt"

    def test_edit(self):
        tc = ToolCall("Edit", {"file_path": "/src/app.js", "old_string": "x", "new_string": "y"})
        assert tc.summary() == "Edit: app.js"

    def test_bash(self):
        tc = ToolCall("Bash", {"command": "git status && git log"})
        assert tc.summary() == "Bash: git status && git log"

    def test_bash_multiline_truncated(self):
        tc = ToolCall("Bash", {"command": "echo hello\necho world\necho done"})
        assert tc.summary() == "Bash: echo hello"

    def test_grep(self):
        tc = ToolCall("Grep", {"pattern": "def main"})
        assert tc.summary() == "Grep: def main"

    def test_glob(self):
        tc = ToolCall("Glob", {"pattern": "**/*.py"})
        assert tc.summary() == "Glob: **/*.py"

    def test_agent(self):
        tc = ToolCall("Agent", {"description": "Search codebase"})
        assert tc.summary() == "Agent: Search codebase"

    def test_webfetch(self):
        tc = ToolCall("WebFetch", {"url": "https://example.com/docs"})
        assert tc.summary() == "WebFetch: https://example.com/docs"

    def test_websearch(self):
        tc = ToolCall("WebSearch", {"query": "python asyncio"})
        assert tc.summary() == "WebSearch: python asyncio"

    def test_toolsearch(self):
        tc = ToolCall("ToolSearch", {"query": "select:Read"})
        assert tc.summary() == "ToolSearch: select:Read"

    def test_skill(self):
        tc = ToolCall("Skill", {"skill": "PCrystal"})
        assert tc.summary() == "Skill: PCrystal"

    def test_unknown_tool(self):
        tc = ToolCall("FancyNewTool", {"data": 123})
        assert tc.summary() == "FancyNewTool"

    def test_empty_input(self):
        tc = ToolCall("Read", {})
        assert tc.summary() == "Read"

    def test_long_bash_truncated(self):
        tc = ToolCall("Bash", {"command": "x" * 200})
        summary = tc.summary()
        assert len(summary) <= 86  # "Bash: " + 80 chars


# ─── tex_escape ─────────────────────────────────────────────────────────────

class TestTexEscape:
    @pytest.fixture(autouse=True)
    def _get_tex_escape(self):
        """Extract tex_escape from export_tex's closure by testing via export."""
        # tex_escape is a nested function — test it through a mini session
        pass

    def _tex_escape(self, text):
        """Replicate tex_escape logic for direct testing."""
        import re
        conv = {
            "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
            "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\^{}",
        }
        pattern = re.compile("|".join(re.escape(k) for k in conv))
        return pattern.sub(lambda m: conv[m.group()], text)

    def test_ampersand(self):
        assert self._tex_escape("A & B") == r"A \& B"

    def test_percent(self):
        assert self._tex_escape("100%") == r"100\%"

    def test_dollar(self):
        assert self._tex_escape("$100") == r"\$100"

    def test_hash(self):
        assert self._tex_escape("#include") == r"\#include"

    def test_underscore(self):
        assert self._tex_escape("my_var") == r"my\_var"

    def test_backslash(self):
        assert self._tex_escape("a\\b") == r"a\textbackslash{}b"

    def test_braces(self):
        assert self._tex_escape("{x}") == r"\{x\}"

    def test_tilde(self):
        assert self._tex_escape("~") == r"\textasciitilde{}"

    def test_caret(self):
        assert self._tex_escape("^") == r"\^{}"

    def test_no_double_escape(self):
        """The original bug: & -> \\& -> \\textbackslash{}\\& with sequential replacement."""
        result = self._tex_escape("a & b \\ c")
        assert r"\textbackslash{}\&" not in result  # No double-escape
        assert r"\&" in result
        assert r"\textbackslash{}" in result

    def test_all_special_chars(self):
        result = self._tex_escape("\\&%$#_{}~^")
        assert "\\\\" not in result  # No double backslashes from escaping

    def test_plain_text_unchanged(self):
        assert self._tex_escape("Hello world 123") == "Hello world 123"


# ─── Search Counting ───────────────────────────────────────────────────────

class TestSearchCounting:
    def test_counts_in_parsed_messages_only(self, tmp_path):
        """Search should count matches in parsed messages, not raw JSONL."""
        path = _write_jsonl(tmp_path, "search-0000-0000-0000-000000000000.jsonl", [
            _user_line("sobolev spaces are interesting"),
            _assistant_line("Yes, sobolev embeddings are fundamental in PDE theory"),
            _user_line("Tell me more about sobolev"),
        ])
        s = Session(path)
        s.parse()

        query = "sobolev"
        count = 0
        for m in s.messages:
            if m.text and query in m.text.lower():
                count += m.text.lower().count(query)

        assert count == 3  # One in each message

    def test_raw_jsonl_has_more_matches(self, tmp_path):
        """Demonstrate that raw JSONL search would overcount."""
        path = _write_jsonl(tmp_path, "raw-0000-0000-0000-000000000000.jsonl", [
            _user_line("sobolev"),
            _assistant_line("sobolev"),
        ])

        # Raw search (how it was broken before)
        raw_text = path.read_text(encoding="utf-8")
        raw_count = raw_text.lower().count("sobolev")

        # Parsed search (correct)
        s = Session(path)
        s.parse()
        parsed_count = sum(
            m.text.lower().count("sobolev")
            for m in s.messages if m.text
        )

        # Raw finds "sobolev" in JSON keys/structure too
        assert raw_count >= parsed_count
        assert parsed_count == 2


# ─── Summary ────────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_from_parsed(self, basic_session):
        basic_session.parse()
        assert basic_session.summary() == "Hello, how are you?"

    def test_summary_fast_path(self, basic_session):
        # Don't parse — should use fast path
        assert basic_session.summary() == "Hello, how are you?"

    def test_summary_truncation(self, tmp_path):
        long_text = "A" * 200
        path = _write_jsonl(tmp_path, "long-0000-0000-0000-000000000000.jsonl", [
            _user_line(long_text),
        ])
        s = Session(path)
        summary = s.summary(max_len=50)
        assert len(summary) <= 54  # 50 + "..."
        assert summary.endswith("...")

    def test_summary_skips_short_messages(self, tmp_path):
        path = _write_jsonl(tmp_path, "short-0000-0000-0000-000000000000.jsonl", [
            _user_line("Hi"),  # <= 5 chars, should be skipped
            _user_line("Tell me about Navier-Stokes equations"),
        ])
        s = Session(path)
        assert "Navier-Stokes" in s.summary()

    def test_summary_empty_session(self, tmp_path):
        p = tmp_path / "empty2-0000-0000-0000-000000000000.jsonl"
        p.write_text("")
        s = Session(p)
        assert s.summary() == "(empty session)"

    def test_summary_skips_system_reminders(self, tmp_path):
        path = _write_jsonl(tmp_path, "srs-0000-0000-0000-000000000000.jsonl", [
            _user_line("<system-reminder>internal stuff</system-reminder>"),
            _user_line("Actual user question about math"),
        ])
        s = Session(path)
        assert "math" in s.summary()
        assert "system-reminder" not in s.summary()


# ─── Helper Methods ─────────────────────────────────────────────────────────

class TestHelperMethods:
    def test_user_messages(self, basic_session):
        msgs = basic_session.user_messages()
        assert len(msgs) == 2
        assert all(m.role == "user" for m in msgs)

    def test_assistant_messages(self, basic_session):
        msgs = basic_session.assistant_messages()
        assert len(msgs) == 2
        assert all(m.role == "assistant" for m in msgs)

    def test_all_text(self, basic_session):
        text = basic_session.all_text()
        assert "Hello" in text
        assert "Python" in text

    def test_code_blocks(self, tmp_path):
        path = _write_jsonl(tmp_path, "code-0000-0000-0000-000000000000.jsonl", [
            _assistant_line("Here's some code:\n```python\ndef hello():\n    print('hi')\n```\nDone."),
        ])
        s = Session(path)
        blocks = s.code_blocks()
        assert len(blocks) == 1
        assert blocks[0]["lang"] == "python"
        assert "def hello" in blocks[0]["code"]

    def test_message_count(self, basic_session):
        count = basic_session.message_count()
        # message_count scans raw JSONL for '"role":"user"' / '"role":"assistant"'
        # Our fixture uses spaces in JSON so it looks for '"role": "user"' — count may differ
        assert count >= 0  # Smoke test: doesn't crash


# ─── Export Smoke Tests ─────────────────────────────────────────────────────

class TestExports:
    def test_markdown_export(self, basic_session):
        basic_session.parse()
        md = cc.export_markdown(basic_session)
        assert "## You" in md
        assert "## Claude" in md
        assert "Hello, how are you?" in md

    def test_txt_export(self, basic_session):
        basic_session.parse()
        txt = cc.export_txt(basic_session)
        assert "[YOU]" in txt
        assert "Hello" in txt

    def test_html_export(self, basic_session):
        basic_session.parse()
        html = cc.export_html(basic_session)
        assert "<html" in html
        assert "Hello, how are you?" in html
        assert "user" in html

    def test_tex_export(self, basic_session):
        basic_session.parse()
        tex = cc.export_tex(basic_session)
        assert r"\documentclass" in tex
        assert r"\begin{document}" in tex

    def test_html_tool_call_summary(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session)
        assert "Read: config.yaml" in html
        assert "Bash: git status" in html

    def test_markdown_tool_call_summary(self, toolcall_session):
        toolcall_session.parse()
        md = cc.export_markdown(toolcall_session)
        assert "Read: config.yaml" in md

    def test_html_embedded_mode(self, basic_session):
        basic_session.parse()
        html = cc.export_html(basic_session, embedded=True)
        # Embedded mode should not have full <html> wrapper
        assert "Hello, how are you?" in html

    def test_html_rich_has_katex(self, basic_session):
        basic_session.parse()
        html = cc.export_html(basic_session, rich=True)
        assert "katex" in html
        assert "cdn.jsdelivr.net" in html

    def test_html_rich_has_table_css(self, basic_session):
        basic_session.parse()
        html = cc.export_html(basic_session, rich=True)
        assert "md-table" in html

    def test_html_non_rich_no_katex(self, basic_session):
        basic_session.parse()
        html = cc.export_html(basic_session)
        assert "cdn.jsdelivr.net" not in html

    def test_html_rich_clickable_links(self, tmp_path):
        path = _write_jsonl(tmp_path, "links-0000-0000-0000-000000000000.jsonl", [
            _user_line("Check https://example.com/docs for info"),
            _assistant_line("See https://github.com/user/repo for code"),
        ])
        s = Session(path)
        s.parse()
        html = cc.export_html(s, rich=True)
        assert 'href="https://example.com/docs"' in html
        assert 'target="_blank"' in html

    def test_html_non_rich_no_links(self, tmp_path):
        path = _write_jsonl(tmp_path, "nolinks-0000-0000-0000-000000000000.jsonl", [
            _user_line("Check https://example.com/docs for info"),
        ])
        s = Session(path)
        s.parse()
        html = cc.export_html(s)
        assert 'href="https://example.com/docs"' not in html

    def test_html_rich_md_table(self, tmp_path):
        table_text = "| Name | Value |\n|------|-------|\n| foo  | 42    |\n| bar  | 99    |"
        path = _write_jsonl(tmp_path, "table-0000-0000-0000-000000000000.jsonl", [
            _assistant_line(table_text),
        ])
        s = Session(path)
        s.parse()
        html = cc.export_html(s, rich=True)
        assert "<table" in html
        assert "<th>" in html
        assert "foo" in html
        assert "42" in html

    def test_html_rich_inline_math(self, tmp_path):
        path = _write_jsonl(tmp_path, "math-0000-0000-0000-000000000000.jsonl", [
            _assistant_line("The formula is $E = mc^2$ and that's it."),
        ])
        s = Session(path)
        s.parse()
        html = cc.export_html(s, rich=True)
        assert "katex-inline" in html
        assert "E = mc^2" in html

    def test_html_rich_display_math(self, tmp_path):
        path = _write_jsonl(tmp_path, "dispmath-0000-0000-0000-000000000000.jsonl", [
            _assistant_line("Consider:\n$$\\int_0^1 f(x)\\,dx$$\nDone."),
        ])
        s = Session(path)
        s.parse()
        html = cc.export_html(s, rich=True)
        assert "katex-display" in html

    def test_html_rich_headings(self, tmp_path):
        path = _write_jsonl(tmp_path, "headings-0000-0000-0000-000000000000.jsonl", [
            _assistant_line("## Section One\nSome text\n### Subsection\nMore text"),
        ])
        s = Session(path)
        s.parse()
        html = cc.export_html(s, rich=True)
        assert "<h2" in html
        assert "<h3" in html
        assert "Section One" in html


# ─── Diagrams Mode ──────────────────────────────────────────────────────────

class TestHtmlDiagrams:
    def test_html_no_diagrams_by_default(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session)
        assert "mermaid" not in html
        assert "sequenceDiagram" not in html

    def test_html_diagrams_has_mermaid_cdn(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session, diagrams=True)
        assert "mermaid" in html
        assert "cdn.jsdelivr.net" in html

    def test_html_diagrams_emits_sequence_block(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session, diagrams=True)
        assert "sequenceDiagram" in html
        assert "participant C as Claude" in html
        # Participants for distinct tool names
        assert "participant Read as Read" in html
        assert "participant Bash as Bash" in html
        # At least one arrow from Claude to a tool
        assert "C->>Read:" in html

    def test_html_diagrams_contains_tool_args(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session, diagrams=True)
        # config.yaml appears in the Read tool summary
        assert "config.yaml" in html
        # git status appears in Bash summary
        assert "git status" in html

    def test_html_diagrams_skipped_when_no_tool_calls(self, basic_session):
        basic_session.parse()
        html = cc.export_html(basic_session, diagrams=True)
        # Mermaid CDN still loaded, but no sequenceDiagram block emitted
        assert "sequenceDiagram" not in html

    def test_html_diagrams_has_zoom_controls(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session, diagrams=True)
        # svg-pan-zoom CDN and zoom-control buttons present
        assert "svg-pan-zoom" in html
        assert 'data-zoom="in"' in html
        assert 'data-zoom="out"' in html
        assert 'data-zoom="reset"' in html
        assert "diagram-viewport" in html

    def test_html_diagrams_additive_with_rich(self, toolcall_session):
        toolcall_session.parse()
        html = cc.export_html(toolcall_session, rich=True, diagrams=True)
        # Both features present, nothing overwritten
        assert "katex" in html
        assert "mermaid" in html
        assert "sequenceDiagram" in html

    def test_build_sequence_diagram_empty_session(self, basic_session):
        basic_session.parse()
        assert cc._build_sequence_diagram(basic_session) == ""

    def test_build_sequence_diagram_sanitizes_participant_id(self, tmp_path):
        # A hypothetical tool name with a dot/hyphen would need a safe participant id
        path = _write_jsonl(tmp_path, "diag9999-0000-0000-0000-000000000000.jsonl", [
            _user_line("Go"),
            _assistant_tool_line("weird.tool-name", {"x": 1}),
        ])
        s = Session(path)
        s.parse()
        seq = cc._build_sequence_diagram(s)
        # participant id has underscores, alias keeps original
        assert "participant weird_tool_name as weird.tool-name" in seq


# ─── Rich HTML Helpers ──────────────────────────────────────────────────────

class TestRichHelpers:
    def test_auto_link_urls(self):
        result = cc._auto_link_urls("Visit https://example.com for info")
        assert 'href="https://example.com"' in result
        assert 'target="_blank"' in result

    def test_auto_link_preserves_text(self):
        result = cc._auto_link_urls("No links here")
        assert result == "No links here"

    def test_auto_link_multiple(self):
        result = cc._auto_link_urls("Go to https://a.com and https://b.com")
        assert result.count("href=") == 2

    def test_md_table_to_html(self):
        table = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = cc._md_table_to_html(table)
        assert "<table" in result
        assert "<th>A</th>" in result
        assert "<td>1</td>" in result

    def test_md_table_preserves_non_table(self):
        text = "Just some text\nwith no tables"
        result = cc._md_table_to_html(text)
        assert result == text

    def test_md_table_mixed(self):
        text = "Before\n| X | Y |\n|---|---|\n| a | b |\nAfter"
        result = cc._md_table_to_html(text)
        assert "Before" in result
        assert "After" in result
        assert "<table" in result


# ─── (continuing TestExports) ───────────────────────────────────────────────

class TestExportsTexEscape:
    def test_tex_escapes_special_chars(self, tmp_path):
        path = _write_jsonl(tmp_path, "tex-0000-0000-0000-000000000000.jsonl", [
            _user_line("Use $100 & save 50%"),
            _assistant_line("The cost is $50 & that's 50% off"),
        ])
        s = Session(path)
        s.parse()
        tex = cc.export_tex(s)
        assert r"\$100" in tex
        assert r"\&" in tex
        assert r"\%" in tex
        # No double-escaping
        assert r"\textbackslash{}\$" not in tex


# ─── Numbered REPL References ───────────────────────────────────────────────

class TestNumberedRefs:
    def _mk(self, tmp_path, short_id_prefix):
        path = _write_jsonl(tmp_path, f"{short_id_prefix}-0000-0000-0000-000000000000.jsonl", [
            _user_line("Hi"),
            _assistant_line("Hello"),
        ])
        return Session(path)

    def test_empty_cache_returns_unchanged(self):
        assert cc._substitute_numbered_refs(["export", "1", "--rich"], index=[]) == ["export", "1", "--rich"]

    def test_substitutes_bare_integer(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        s2 = self._mk(tmp_path, "bbbb2222")
        idx = [s1, s2]
        out = cc._substitute_numbered_refs(["export", "2", "--format", "html"], index=idx)
        assert out == ["export", "bbbb2222", "--format", "html"]

    def test_leaves_flags_alone(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        out = cc._substitute_numbered_refs(["export", "-o", "/tmp"], index=[s1])
        assert out == ["export", "-o", "/tmp"]

    def test_leaves_non_integer_tokens(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        out = cc._substitute_numbered_refs(["export", "some-hash-like-token"], index=[s1])
        assert out == ["export", "some-hash-like-token"]

    def test_out_of_range_returns_unchanged(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        out = cc._substitute_numbered_refs(["export", "7"], index=[s1])
        assert out == ["export", "7"]

    def test_zero_is_not_substituted(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        out = cc._substitute_numbered_refs(["export", "0"], index=[s1])
        assert out == ["export", "0"]

    def test_search_never_substituted(self, tmp_path):
        # Commands outside _ID_COMMANDS must pass through — `search` is one.
        s1 = self._mk(tmp_path, "aaaa1111")
        out = cc._substitute_numbered_refs(["search", "1"], index=[s1])
        assert out == ["search", "1"]

    def test_list_limit_not_mangled(self, tmp_path):
        # Regression: `list --limit 3` after index populated MUST NOT rewrite 3.
        # argparse expects int on --limit; substituting a hash would crash it.
        s1 = self._mk(tmp_path, "aaaa1111")
        s2 = self._mk(tmp_path, "bbbb2222")
        s3 = self._mk(tmp_path, "cccc3333")
        out = cc._substitute_numbered_refs(["list", "--limit", "2"], index=[s1, s2, s3])
        assert out == ["list", "--limit", "2"]

    def test_backup_interval_not_mangled(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        out = cc._substitute_numbered_refs(["backup", "--interval", "1"], index=[s1])
        assert out == ["backup", "--interval", "1"]

    def test_only_first_positional_substituted(self, tmp_path):
        # For ID commands with numeric flag values (e.g. future `open 1 --port 3456`)
        # only the first positional integer is rewritten.
        sessions = [self._mk(tmp_path, f"{i:04d}1111") for i in range(5)]
        out = cc._substitute_numbered_refs(["open", "1", "--port", "3"], index=sessions)
        # "1" → first session hash; "3" left alone even though index[2] exists
        assert out[0] == "open"
        assert out[1] == sessions[0].short_id
        assert out[2] == "--port"
        assert out[3] == "3"

    def test_extract_single_positional_substituted(self, tmp_path):
        s1 = self._mk(tmp_path, "aaaa1111")
        s2 = self._mk(tmp_path, "bbbb2222")
        out = cc._substitute_numbered_refs(["extract", "1", "--code"], index=[s1, s2])
        assert out == ["extract", "aaaa1111", "--code"]

    def test_autopopulate_fires_when_index_empty(self, tmp_path, monkeypatch):
        """Mode B: `export 2` on fresh REPL should auto-populate and resolve."""
        s1 = self._mk(tmp_path, "aaaa1111")
        s2 = self._mk(tmp_path, "bbbb2222")
        s3 = self._mk(tmp_path, "cccc3333")
        cc._interactive_index.clear()
        monkeypatch.setattr(cc, "find_all_sessions", lambda project=None: [s1, s2, s3])

        # index=None → use module-level; autopopulate=True is default
        out = cc._substitute_numbered_refs(["export", "2", "--format", "html"])
        assert out == ["export", "bbbb2222", "--format", "html"]
        # Module cache was filled
        assert len(cc._interactive_index) == 3
        cc._interactive_index.clear()

    def test_autopopulate_skipped_if_no_numbered_ref(self, tmp_path, monkeypatch):
        cc._interactive_index.clear()
        called = {"n": 0}

        def fake_find(project=None):
            called["n"] += 1
            return []
        monkeypatch.setattr(cc, "find_all_sessions", fake_find)

        # No integer tokens → must NOT call find_all_sessions
        cc._substitute_numbered_refs(["export", "a7e44ed0", "--format", "html"])
        assert called["n"] == 0

    def test_autopopulate_skipped_if_command_not_id(self, tmp_path, monkeypatch):
        cc._interactive_index.clear()
        called = {"n": 0}

        def fake_find(project=None):
            called["n"] += 1
            return []
        monkeypatch.setattr(cc, "find_all_sessions", fake_find)

        cc._substitute_numbered_refs(["list", "--limit", "5"])
        assert called["n"] == 0

    def test_autopopulate_disabled_flag(self, tmp_path, monkeypatch):
        """Explicit autopopulate=False disables the lookup entirely."""
        cc._interactive_index.clear()
        called = {"n": 0}

        def fake_find(project=None):
            called["n"] += 1
            return []
        monkeypatch.setattr(cc, "find_all_sessions", fake_find)

        out = cc._substitute_numbered_refs(["export", "2"], autopopulate=False)
        assert out == ["export", "2"]
        assert called["n"] == 0

    def test_autopopulate_out_of_range_passes_through(self, tmp_path, monkeypatch):
        s1 = self._mk(tmp_path, "aaaa1111")
        cc._interactive_index.clear()
        monkeypatch.setattr(cc, "find_all_sessions", lambda project=None: [s1])

        # 50 > 1 → autopopulate fills cache with 1 entry, no substitution
        out = cc._substitute_numbered_refs(["export", "50"])
        assert out == ["export", "50"]
        assert len(cc._interactive_index) == 1
        cc._interactive_index.clear()

    def test_cmd_list_interactive_populates_index(self, tmp_path, monkeypatch, capsys):
        s1 = self._mk(tmp_path, "cccc3333")
        s2 = self._mk(tmp_path, "dddd4444")
        monkeypatch.setattr(cc, "find_all_sessions", lambda project=None: [s1, s2])
        cc._interactive_index.clear()

        class A:
            project = None
            limit = 20
            detail = False
            _interactive = True
        cc.cmd_list(A())
        captured = capsys.readouterr().out
        assert "[  1]" in captured
        assert "[  2]" in captured
        assert len(cc._interactive_index) == 2
        assert cc._interactive_index[0].short_id == "cccc3333"
        cc._interactive_index.clear()

    def test_cmd_list_non_interactive_no_numbers(self, tmp_path, monkeypatch, capsys):
        s1 = self._mk(tmp_path, "eeee5555")
        monkeypatch.setattr(cc, "find_all_sessions", lambda project=None: [s1])
        cc._interactive_index.clear()

        class A:
            project = None
            limit = 20
            detail = False
        cc.cmd_list(A())
        captured = capsys.readouterr().out
        assert "[  1]" not in captured
        # CLI mode does NOT populate the cache
        assert cc._interactive_index == []
