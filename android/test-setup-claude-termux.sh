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

# 4. The expired npm pin is gone: v1.x pinned @^1 (Claude Code 1.x).
run "no npm pin to Claude Code 1.x" \
    bash -c "! grep -q 'claude-code@\\^1' '$SCRIPT'"

# 5-8. Route classifier: four inputs, four different answers (a classifier that
#      always says one word fails three of these).
T="$(mktemp -d)"
mkdir -p "$T/lib/node_modules/@anthropic-ai/claude-code"
echo '#!/usr/bin/env node' > "$T/lib/node_modules/@anthropic-ai/claude-code/cli.js"
ln -s "$T/lib/node_modules/@anthropic-ai/claude-code/cli.js" "$T/claude-npm"
printf 'VERSIONS_DIR="x"\nGLIBC_LD="$PREFIX/glibc/lib/ld-linux-aarch64.so.1"\n' > "$T/claude-native"
printf '#!/bin/sh\necho hi\n' > "$T/claude-other"
run "route: npm symlink -> npm"        bash -c "[ \"\$(CLAUDE_BIN='$T/claude-npm' bash '$SCRIPT' --claude-route | tail -1)\" = npm ]"
run "route: launcher file -> native"   bash -c "[ \"\$(CLAUDE_BIN='$T/claude-native' bash '$SCRIPT' --claude-route | tail -1)\" = native ]"
run "route: other file -> unknown"     bash -c "[ \"\$(CLAUDE_BIN='$T/claude-other' bash '$SCRIPT' --claude-route | tail -1)\" = unknown ]"
run "route: absent -> missing"         bash -c "[ \"\$(CLAUDE_BIN='$T/nope' bash '$SCRIPT' --claude-route | tail -1)\" = missing ]"

# 9. The .bashrc rewrite comments out an active proot alias and leaves a
#    commented one alone (exact sed line taken from the script).
SEDLINE="$(grep -F '(native Claude Code needs no proot)' "$SCRIPT" | head -1 | sed 's/^ *//')"
printf "alias claude='proot -b /x:/tmp claude'\n#alias claude='proot -b /y:/tmp claude'\n" > "$T/bashrc"
BASHRC="$T/bashrc" bash -c "BASHRC='$T/bashrc'; $SEDLINE"
run "proot alias commented out, commented line untouched" \
    bash -c "! grep -Eq '^[[:space:]]*alias claude=.proot ' '$T/bashrc' && grep -q '^#alias claude=.proot -b /y' '$T/bashrc'"

# 10-12. Pinned download + sha256 (Termux + network only; skipped elsewhere).
if [ -d /data/data/com.termux ] && curl -fsS --max-time 10 -o /dev/null https://raw.githubusercontent.com/ 2>/dev/null; then
    run "dry-run: missing -> verified install.sh" \
        bash -c "CLAUDE_BIN='$T/nope' bash '$SCRIPT' --dry-run 2>&1 | grep -q 'install.sh verified'"
    run "dry-run: npm -> verified migrate.sh" \
        bash -c "CLAUDE_BIN='$T/claude-npm' bash '$SCRIPT' --dry-run 2>&1 | grep -q 'migrate.sh verified'"
    run "planted wrong sha256 is refused (exit 1, never run)" \
        bash -c "out=\$(CLAUDE_BIN='$T/nope' CCA_EXPECT_INSTALL=$(printf '0%.0s' $(seq 64)) bash '$SCRIPT' --dry-run 2>&1); rc=\$?; [ \$rc -eq 1 ] && echo \"\$out\" | grep -q MISMATCH && ! echo \"\$out\" | grep -q 'would run: bash install.sh'"
else
    echo "  skip pinned-download checks (not Termux, or no network)"
fi
rm -rf "$T"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
