"""Boundary tests for claude-chat.py (stdlib unittest, no pytest).

Run from the tool/ directory:
    python -m unittest discover tests
    python tests/test_claude_chat.py

These are intentionally narrow boundary tests — substrate memory that prevents
regenerating bugs across future AI refactors. They cover:

  1. Session JSONL parsing (Session)
  2. SessionScanner match counting + snippets
  3. MarkdownExporter format() output
  4. COMMAND_REGISTRY name + alias resolution
  5. EXPORTER_REGISTRY name resolution

They do NOT test internals (those have their own pytest suite next to the
script). They DO test the OOP boundary surface — class contracts, registry
shape, exporter polymorphism.
"""

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


# ─── Import the hyphenated module ───────────────────────────────────────────

_TOOL_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _TOOL_DIR / "claude-chat.py"

_spec = importlib.util.spec_from_file_location("claude_chat", _SCRIPT)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def _write_jsonl(tmp_path: Path, filename: str, lines):
    """Write a list of dicts as JSONL and return the path."""
    p = tmp_path / filename
    with open(p, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    return p


def _user_line(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant_line(text, model="claude-opus-4-7"):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": text}],
        },
    }


class TestSessionParsing(unittest.TestCase):
    """Boundary 1: Session reads JSONL and exposes messages + first user text."""

    def test_parse_basic_session(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = _write_jsonl(tmp, "abcd1234-0000-0000-0000-000000000000.jsonl", [
                _user_line("First user message about sobolev spaces"),
                _assistant_line("Sobolev spaces are function spaces."),
                _user_line("Follow-up question"),
            ])
            s = cc.Session(path)
            s.parse()
            self.assertEqual(len(s.messages), 3)
            self.assertEqual(s.messages[0].role, "user")
            self.assertEqual(
                s.messages[0].text,
                "First user message about sobolev spaces",
            )
            self.assertEqual(s.short_id, "abcd1234")


class TestSessionScanner(unittest.TestCase):
    """Boundary 2: SessionScanner finds the query, returns count + snippets."""

    def test_scan_returns_count_and_context(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = _write_jsonl(tmp, "scan0001-0000-0000-0000-000000000000.jsonl", [
                _user_line("Tell me about sobolev embeddings"),
                _assistant_line("Sobolev embeddings are central in PDE theory"),
            ])
            s = cc.Session(path)
            s.parse()
            scanner = cc.SessionScanner("sobolev", context=20)
            count, contexts = scanner.scan(s)
            # Two occurrences (case-insensitive match), one per message
            self.assertEqual(count, 2)
            self.assertEqual(len(contexts), 2)
            roles = [r for r, _ in contexts]
            self.assertIn("user", roles)
            self.assertIn("assistant", roles)
            # Snippets include the matched substring
            for _, snippet in contexts:
                self.assertIn("sobolev", snippet.lower())


class TestMarkdownExporter(unittest.TestCase):
    """Boundary 3: MarkdownExporter output contains the user message text."""

    def test_export_contains_user_text(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = _write_jsonl(tmp, "md001234-0000-0000-0000-000000000000.jsonl", [
                _user_line("Please refactor this code"),
                _assistant_line("Sure, here's the plan."),
            ])
            s = cc.Session(path)
            s.parse()
            md = cc.MarkdownExporter(s).format()
            self.assertIn("Please refactor this code", md)
            self.assertIn("## You", md)
            self.assertIn("## Claude", md)
            self.assertEqual(cc.MarkdownExporter.extension, ".md")


class TestCommandRegistry(unittest.TestCase):
    """Boundary 4: COMMAND_REGISTRY has expected commands + aliases resolve."""

    def test_registry_has_all_commands(self):
        expected = {
            "list", "search", "export", "backup", "stats",
            "extract", "serve", "wiki", "protect",
        }
        for name in expected:
            self.assertIn(name, cc.COMMAND_REGISTRY, f"missing command {name!r}")

    def test_aliases_resolve_to_same_class(self):
        # list/ls
        self.assertIs(cc.COMMAND_REGISTRY["list"], cc.COMMAND_REGISTRY["ls"])
        self.assertIs(cc.COMMAND_REGISTRY["list"], cc.ListCommand)
        # search/grep/find
        self.assertIs(cc.COMMAND_REGISTRY["search"], cc.COMMAND_REGISTRY["grep"])
        self.assertIs(cc.COMMAND_REGISTRY["search"], cc.COMMAND_REGISTRY["find"])
        self.assertIs(cc.COMMAND_REGISTRY["search"], cc.SearchCommand)
        # serve/web/browse
        self.assertIs(cc.COMMAND_REGISTRY["serve"], cc.COMMAND_REGISTRY["web"])
        self.assertIs(cc.COMMAND_REGISTRY["serve"], cc.COMMAND_REGISTRY["browse"])
        # wiki/archive
        self.assertIs(cc.COMMAND_REGISTRY["wiki"], cc.COMMAND_REGISTRY["archive"])

    def test_command_subclasses_have_execute(self):
        # Every registered class must be a Command subclass with execute() overridden
        for name, cls in cc.COMMAND_REGISTRY.items():
            self.assertTrue(issubclass(cls, cc.Command),
                            f"{name} → {cls.__name__} is not a Command subclass")
            self.assertIsNot(cls.execute, cc.Command.execute,
                             f"{cls.__name__} must override Command.execute")


class TestExporterRegistry(unittest.TestCase):
    """Boundary 5: EXPORTER_REGISTRY maps formats to Exporter subclasses."""

    def test_registry_has_all_formats(self):
        self.assertEqual(
            set(cc.EXPORTER_REGISTRY.keys()),
            {"md", "html", "txt", "tex"},
        )

    def test_exporter_subclasses_have_extension_and_format(self):
        for fmt, cls in cc.EXPORTER_REGISTRY.items():
            self.assertTrue(issubclass(cls, cc.Exporter),
                            f"{fmt} → {cls.__name__} is not an Exporter subclass")
            self.assertTrue(cls.extension.startswith("."),
                            f"{cls.__name__}.extension must start with '.': got {cls.extension!r}")
            self.assertIsNot(cls.format, cc.Exporter.format,
                             f"{cls.__name__} must override Exporter.format")


if __name__ == "__main__":
    unittest.main()
