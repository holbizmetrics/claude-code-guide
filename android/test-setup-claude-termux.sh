#!/data/data/com.termux/files/usr/bin/bash
# Minimal smoke test for setup-claude-termux.sh
# Runs anywhere bash exists (Termux, Linux, Git Bash on Windows).
# Catches the dumb regressions: syntax errors, broken --version, broken --help.

set -u
SCRIPT="$(dirname "$0")/setup-claude-termux.sh"
PASS=0
FAIL=0

run() {
    local name="$1"; shift
    if "$@"; then
        echo "  ok   $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL $name"
        FAIL=$((FAIL + 1))
    fi
}

[ -f "$SCRIPT" ] || { echo "FATAL: $SCRIPT not found"; exit 2; }

EXPECTED_VERSION=$(grep '^SCRIPT_VERSION=' "$SCRIPT" | head -1 | cut -d'"' -f2)
[ -n "$EXPECTED_VERSION" ] || { echo "FATAL: could not parse SCRIPT_VERSION"; exit 2; }

echo "Testing $SCRIPT (expected version: $EXPECTED_VERSION)"

# 1. Syntax: bash -n must pass.
run "bash -n parses cleanly" bash -n "$SCRIPT"

# 2. --version prints the version string and exits 0.
run "--version prints v$EXPECTED_VERSION" \
    bash -c "bash '$SCRIPT' --version | grep -q 'v$EXPECTED_VERSION'"

# 3. --help exits 0 and mentions --dry-run.
run "--help mentions --dry-run" \
    bash -c "bash '$SCRIPT' --help | grep -q -- '--dry-run'"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
