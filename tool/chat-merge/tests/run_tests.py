#!/usr/bin/env python3
"""run_tests.py -- the ChatMerge regression suite (properties in tests/README.md).

    python3 tests/run_tests.py            builds ChatMerge, then runs every check
    python3 tests/run_tests.py --no-build uses the existing bin/Debug/net10.0 binary

Checks:
  FIXTURE  each tests/cases/<dir>: run on a copy of its inputs; the produced *_merged.txt set must equal the
           expected set, file names and content (line endings normalised -- the fixtures were made on Windows).
  DETERM   the same case run twice gives byte-identical outputs.
  LOSSLESS every non-blank line of every input appears in some output of the run (the property the tool exists
           for). Checked on every fixture AND on the two cases below.
  NAMES    one output file per detected stream: no two streams may write the same path.
  RED      the two data-loss cases found 2026-11-24, which FAILED on the code before that fix:
             collide  two conversations named chat-export-1/2 and chat-export-3/4 -> both wrote chat-export_merged.txt
             diverge  two exports sharing 220 opening lines, each with its own ending -> one ending dropped
Prints `RECORD: chat-merge-tests passed=N failed=M` and exits non-zero on any failure.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CASES = os.path.join(HERE, "cases")
BIN = os.path.join(PROJ, "bin", "Debug", "net10.0", "ChatMerge" + (".exe" if os.name == "nt" else ""))
P = F = 0


def check(name, ok, why=""):
    global P, F
    if ok:
        P += 1; print(f"  PASS {name}")
    else:
        F += 1; print(f"  FAIL {name}  {why}"[:400])


def text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return f.read().replace("\r\n", "\n")


def run(inputs_dir):
    """Run ChatMerge on a fresh copy of the inputs. Returns (outputs {name: text}, stdout, input texts)."""
    work = tempfile.mkdtemp(prefix="chatmerge-")
    ins = {}
    for n in sorted(os.listdir(inputs_dir)):
        if n.endswith(".txt") and not n[:-4].endswith("_merged"):
            shutil.copy(os.path.join(inputs_dir, n), work)
            ins[n] = text(os.path.join(work, n))
    p = subprocess.run([BIN, work], capture_output=True, text=True, encoding="utf-8", errors="replace")
    outs = {n: text(os.path.join(work, n)) for n in sorted(os.listdir(work)) if n.endswith("_merged.txt")}
    shutil.rmtree(work, ignore_errors=True)
    return outs, p.stdout + p.stderr, ins


def streams_reported(stdout):
    return len(re.findall(r'^Stream "', stdout, re.M))


def lost_lines(ins, outs):
    """[(input, line)] for each non-blank input line found in no output (whitespace-normalised, as the tool does)."""
    norm = lambda s: " ".join(s.split())
    have = {norm(l) for o in outs.values() for l in o.split("\n")}
    return [(n, l) for n, t in ins.items() for l in t.split("\n") if norm(l) and norm(l) not in have]


def properties(label, outs, stdout, ins):
    lost = lost_lines(ins, outs)
    check(f"LOSSLESS {label}: every input line is in some output", not lost,
          f"{len(lost)} line(s) lost, e.g. {lost[0] if lost else ''}")
    n = streams_reported(stdout)
    check(f"NAMES {label}: {n} stream(s) -> {len(outs)} output file(s), none overwritten", n == len(outs),
          f"stdout reports {n} streams, {len(outs)} files exist: {sorted(outs)}")


def build_red_cases(root):
    w = lambda p, ls: (os.makedirs(os.path.dirname(p), exist_ok=True), open(p, "w").write("\n".join(ls) + "\n"))
    A = [f"> session ALPHA turn {i}: the user asks about apples number {i}" for i in range(60)]
    B = [f"> session BRAVO turn {i}: the user asks about boats number {i}" for i in range(60)]
    w(f"{root}/collide/chat-export-1.txt", A[:40]); w(f"{root}/collide/chat-export-2.txt", A)
    w(f"{root}/collide/chat-export-3.txt", B[:40]); w(f"{root}/collide/chat-export-4.txt", B)
    C = [f"> shared boot line {i}: identical opening of both exports here" for i in range(220)]
    w(f"{root}/diverge/run-a.txt", C + [f"> ONLY-IN-A ending line {i} that exists nowhere else" for i in range(30)])
    w(f"{root}/diverge/run-b.txt", C + [f"> ONLY-IN-B ending line {i} that exists nowhere else" for i in range(50)])


def main():
    if "--no-build" not in sys.argv:
        b = subprocess.run(["dotnet", "build", "-v", "q", PROJ], capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout[-2000:], b.stderr[-2000:]); sys.exit(2)
    if not os.path.isfile(BIN):
        print(f"no binary at {BIN}"); sys.exit(2)

    for case in sorted(os.listdir(CASES)):
        d = os.path.join(CASES, case)
        want = {n: text(os.path.join(d, n)) for n in sorted(os.listdir(d)) if n.endswith("_merged.txt")}
        outs, stdout, ins = run(d)
        check(f"FIXTURE {case}: outputs {sorted(want)}", sorted(outs) == sorted(want),
              f"got {sorted(outs)}")
        diff = [n for n in want if n in outs and outs[n] != want[n]]
        check(f"FIXTURE {case}: content matches expected", not diff and sorted(outs) == sorted(want), f"differs: {diff}")
        check(f"DETERM {case}: second run identical", run(d)[0] == outs)
        properties(case, outs, stdout, ins)

    red = tempfile.mkdtemp(prefix="chatmerge-red-")
    build_red_cases(red)
    for case in ("collide", "diverge"):
        outs, stdout, ins = run(os.path.join(red, case))
        properties(f"RED {case}", outs, stdout, ins)
    outs, stdout, _ = run(os.path.join(red, "diverge"))
    check("RED diverge: the run says it kept extra content (never silent)", "WARNING" in stdout, stdout[-300:])
    shutil.rmtree(red, ignore_errors=True)

    print(f"\nRECORD: chat-merge-tests passed={P} failed={F}")
    sys.exit(0 if F == 0 else 1)


if __name__ == "__main__":
    main()
