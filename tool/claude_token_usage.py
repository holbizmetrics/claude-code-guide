"""How many tokens do I use per month? — sums Claude Code usage from local transcripts.

Claude Code stores every session as JSONL under ~/.claude/projects, and each
assistant message carries its token usage. This just adds them up per month.

Usage:  python claude_token_usage.py
Notes:  counts THIS machine only; cache reads are why agentic totals look huge
        (the session re-reads its context every turn). No dependencies, stdlib only.

This is the deliberately-standalone single-file version, made for sharing.
If you already use claude-chat.py (same repo), the identical feature is built
in — `python claude-chat.py usage` (add --by-model to split per model).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
root = Path.home() / ".claude" / "projects"
months = defaultdict(lambda: defaultdict(int))
files = 0

for p in root.rglob("*.jsonl"):
    files += 1
    if files % 20 == 0:  # progress heartbeat - big corpora take a minute, don't look hung
        print(f"\r  scanning... {files} files", end="", flush=True, file=sys.stderr)
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = (o.get("message") or {}).get("usage")
                ts = o.get("timestamp", "")
                if not u or not ts:
                    continue
                m = ts[:7]  # YYYY-MM
                months[m]["in"] += u.get("input_tokens", 0) or 0
                months[m]["out"] += u.get("output_tokens", 0) or 0
                months[m]["cache_w"] += u.get("cache_creation_input_tokens", 0) or 0
                months[m]["cache_r"] += u.get("cache_read_input_tokens", 0) or 0
                months[m]["msgs"] += 1
    except OSError:
        continue

print("\r" + " " * 40 + "\r", end="", file=sys.stderr)  # clear the progress line
print(f"scanned {files} transcript files under {root}\n")
print(f"{'month':8} {'msgs':>7} {'input':>12} {'output':>12} {'cache-write':>13} {'cache-read':>14} {'TOTAL':>14}")
for m in sorted(months):
    d = months[m]
    total = d["in"] + d["out"] + d["cache_w"] + d["cache_r"]
    print(f"{m:8} {d['msgs']:>7,} {d['in']:>12,} {d['out']:>12,} {d['cache_w']:>13,} {d['cache_r']:>14,} {total:>14,}")
print("\nfresh = input+output (the /usage-style number); TOTAL = what the GPUs actually processed")
