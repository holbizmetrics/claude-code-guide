"""test_list_json.py — `list --json` is a machine contract, so it gets asserted like one.

Added 2026-09-05 alongside the flag. The consumer (PCLA's session-restore) acts on
these rows: it runs `claude --resume <session_id>` in `cwd`. Three fields are
therefore load-bearing rather than cosmetic, and each has an arm below:

  session_id   the FULL id, not short_id -- resume needs the whole thing
  cwd          the REAL directory, because `project` is the mangled dir name
               (-home-user-Foo) and cannot be decoded back: a directory whose own
               name contains a dash is indistinguishable from a separator
  is_subagent  a subagent transcript is not a terminal anyone can resume, and a
               listing that hides the distinction invites exactly that mistake

The controls matter as much as the cases: --json must stay silent on the human
output (a consumer parses stdout), and must not change what `list` selects.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).resolve().parents[1] / "claude-chat.py"
FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def write_session(projects, project, sid, cwd, text, subagent=False):
    if subagent:
        d = projects / project / "parent-session" / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"agent-{sid}.jsonl"
    else:
        d = projects / project
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{sid}.jsonl"
    recs = [
        {"type": "system", "cwd": cwd, "timestamp": "2026-09-05T01:00:00.000Z"},
        {"type": "user", "cwd": cwd, "timestamp": "2026-09-05T01:00:01.000Z",
         "message": {"role": "user", "content": text}},
    ]
    f.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return f


def run(home, *args):
    # HOME must be the HOME dir, not the .claude dir: claude-chat computes
    # PROJECTS_DIR as Path.home()/".claude"/"projects" at import time. (Written
    # first as projects.parent, which pointed at .claude and made the tool look
    # in .claude/.claude/projects -- every arm failed and the tool was fine.)
    env = {"HOME": str(home), "USERPROFILE": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, str(TOOL), "list", *args],
                          capture_output=True, text=True, env=env, timeout=120)


def main():
    print("test_list_json")
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "home"
        projects = home / ".claude" / "projects"
        projects.mkdir(parents=True)
        write_session(projects, "-d-work-repo",
                      "11111111-2222-4333-8444-555555555555",
                      "/d/work/repo", "prove Lemma F2 for the Gram matrix")
        write_session(projects, "-d-work-repo", "aaaabbbbccccdddd",
                      "/d/work/repo", "blind authoring arm", subagent=True)

        # The operator-set name, found by the Windows session 2026-09-05: it lives
        # BESIDE the transcript, not inside it, which is why every headline
        # heuristic in the tool had been guessing while the answer sat one
        # directory away. A name a human chose beats any heuristic.
        sd = projects / "-d-work-repo" / "11111111-2222-4333-8444-555555555555"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "custom-title.json").write_text(
            json.dumps({"customTitle": "wide-belt chrome extension"}))

        r = run(home, "--json")
        check("CONTROL: --json exits 0", r.returncode == 0)
        try:
            data = json.loads(r.stdout)
            parsed = True
        except (json.JSONDecodeError, ValueError) as e:
            data, parsed = {}, False
            print(f"    (stdout was not JSON: {e}; stdout[:200]={r.stdout[:200]!r})")
        check("THE CASE: stdout is pure JSON, nothing else on the stream", parsed)

        rows = data.get("sessions", [])
        check("both sessions are listed", len(rows) == 2)
        real = next((s for s in rows if not s["is_subagent"]), None)
        sub = next((s for s in rows if s["is_subagent"]), None)

        check("THE CASE: session_id is the FULL id, not the short one",
              real is not None
              and real["session_id"] == "11111111-2222-4333-8444-555555555555")
        check("THE CASE: cwd is the REAL directory, not the mangled project name",
              real is not None and real["cwd"] == "/d/work/repo"
              and real["project"] != "/d/work/repo")
        check("THE CASE: is_subagent distinguishes an arm from a terminal",
              sub is not None and real is not None
              and sub["is_subagent"] is True and real["is_subagent"] is False)
        check("a subagent carries its parent so a consumer can explain itself",
              sub is not None and sub["parent_session_id"] == "parent-session")
        check("THE CASE: the operator's /rename title is carried",
              real is not None and real["custom_title"] == "wide-belt chrome extension")
        check("CONTROL: a session never renamed reports None, not an empty string "
              "(not-renamed is not a title)",
              sub is not None and sub["custom_title"] is None)
        check("counts are reported (total and shown), not left to be inferred",
              data.get("total") == 2 and data.get("shown") == 2)

        r2 = run(home, "--json", "--limit", "1")
        d2 = json.loads(r2.stdout)
        check("CONTROL: --limit still applies, and total != shown says so",
              d2["shown"] == 1 and d2["total"] == 2)

        r3 = run(home)
        check("CONTROL: without --json the human output is unchanged (no JSON)",
              r3.returncode == 0 and not r3.stdout.lstrip().startswith("{"))
        check("CONTROL: ... and it still prints the session", "11111111" in r3.stdout)

    # A project directory that exists but holds nothing must say zero, not crash.
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        r = run(home, "--json")
        ok = False
        try:
            ok = json.loads(r.stdout)["total"] == 0
        except Exception:  # noqa: BLE001
            pass
        check("CONTROL: no sessions yields valid JSON with total 0, not a crash "
              "and not empty stdout", ok)

    if FAILS:
        print(f"BATTERY: {len(FAILS)} FAILURE(S) -> {FAILS}")
        sys.exit(1)
    print("BATTERY: ALL GREEN. `list --json` carries the three fields a consumer "
          "acts on, and leaves the human output alone.")


if __name__ == "__main__":
    main()
