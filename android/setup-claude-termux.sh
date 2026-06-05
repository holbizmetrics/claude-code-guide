#!/data/data/com.termux/files/usr/bin/bash

# ══════════════════════════════════════════════════
# Claude Code — Termux Setup Script
# ══════════════════════════════════════════════════
# One command to go from fresh Termux to working Claude Code.
# Safe to re-run — detects what's already installed.
#
# Usage:
#   ./setup-claude-termux.sh          # Interactive setup + menu
#   ./setup-claude-termux.sh --all    # Install everything, no questions
#   ./setup-claude-termux.sh --status # Show what's installed
#   ./setup-claude-termux.sh --dry-run # Simulate install (no side effects)
#   ./setup-claude-termux.sh --log    # Tee output to ~/setup-claude-termux.log
#   ./setup-claude-termux.sh --log=PATH # Tee output to PATH
#   ./setup-claude-termux.sh --help   # Show this help
#   ./setup-claude-termux.sh --version # Show version
#
# Dry-run env overrides:
#   DRY_NESTED=1        # Simulate nested-proot environment
#   DRY_AVAIL_MB=1500   # Simulate available disk space (MB)
#
# What this does:
#   1. Updates all Termux packages
#   2. Installs Node.js, Python, proot, git (if missing)
#   3. Validates Node.js version (≥18 required)
#   4. Installs Claude Code (or fixes broken install)
#   5. Sets up Android storage access
#   6. Configures .bashrc (proot alias, TMPDIR)
#   7. Optional: math, science, LaTeX, GitHub CLI, formal-proof checkers
#
# After setup, Claude Code launches automatically.
#
# Source: https://skool.com/early-ai-adopters
# Proof verification paths from: https://github.com/holbizmetrics/proof-anywhere
# ══════════════════════════════════════════════════

SCRIPT_VERSION="1.2.3"
MIN_NODE_MAJOR=18
NANODA_DIR="$HOME/nanoda_lib"

# Pin Claude Code to the 1.x line. 2.x requires a platform-native binary
# whose npm postinstall refuses to download on android-arm64, leaving the
# CLI unable to start. Until 2.x has an Android path, 1.x is the only
# version that actually runs in Termux.
CLAUDE_PIN="@anthropic-ai/claude-code@^1"

# ── Parse flags (scan all args, not just $1) ────
MODE="interactive"
DRY_RUN=0
LOG_FILE=""
for arg in "$@"; do
    case "$arg" in
        --help|-h)    MODE="help" ;;
        --status)     MODE="status" ;;
        --all)        MODE="all" ;;
        --dry-run)    DRY_RUN=1 ;;
        --version|-v) MODE="version" ;;
        --log)        LOG_FILE="$HOME/setup-claude-termux.log" ;;
        --log=*)      LOG_FILE="${arg#--log=}" ;;
    esac
done

# --dry-run without an explicit mode → imply --all (non-interactive, full flow)
if [ "$DRY_RUN" = "1" ] && [ "$MODE" = "interactive" ]; then
    MODE="all"
fi

# ── Log re-exec (must come before any output we want captured) ───
# Skip for --version/--help/--status (one-shot output, no side effects).
if [ -n "$LOG_FILE" ] && [ -z "${SETUP_LOG_REENTRY:-}" ] \
   && [ "$MODE" != "version" ] && [ "$MODE" != "help" ]; then
    export SETUP_LOG_REENTRY=1
    echo "📝 Logging to $LOG_FILE"
    exec bash "$0" "$@" 2>&1 | tee "$LOG_FILE"
fi

# Track would-install actions for dry-run summary
WOULD_INSTALL=()

# ── Version ─────────────────────────────────────
if [ "$MODE" = "version" ]; then
    echo "setup-claude-termux.sh v${SCRIPT_VERSION}"
    exit 0
fi

# ── Help ────────────────────────────────────────
if [ "$MODE" = "help" ]; then
    sed -n '/^# Usage:/,/^# ═/p' "$0" | head -n -1 | sed 's/^# //'
    exit 0
fi

# ── Colors ──────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "   ${GREEN}✅ $1${NC}"; }
warn() { echo -e "   ${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "   ${RED}❌ $1${NC}"; }
info() { echo -e "   ${CYAN}ℹ️  $1${NC}"; }

# ── Detection helpers ───────────────────────────
check_pkg()    { dpkg -s "$1" &>/dev/null 2>&1; }
check_cmd()    { command -v "$1" &>/dev/null 2>&1; }
check_pip()    { check_cmd python && python -c "import $1" &>/dev/null 2>&1; }
check_bashrc() { grep -q "$1" "$HOME/.bashrc" 2>/dev/null; }

# ── Node.js version helper ─────────────────────
# Returns 0 if node is installed and major version >= MIN_NODE_MAJOR
check_node_version() {
    if ! check_cmd node; then
        return 1
    fi
    local node_major
    node_major=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
    if [ -z "$node_major" ]; then
        return 1
    fi
    [ "$node_major" -ge "$MIN_NODE_MAJOR" ] 2>/dev/null
}

# ── Claude Code health check (timeout-safe) ────
# Uses timeout if available, falls back to background+wait
check_claude_health() {
    if check_cmd timeout; then
        timeout 15 claude --version &>/dev/null 2>&1
    else
        local tmpout
        tmpout=$(mktemp "${TMPDIR:-/tmp}/claude-health.XXXXXX" 2>/dev/null || echo "$HOME/tmp/.claude-health-$$")
        claude --version >"$tmpout" 2>&1 &
        local pid=$!
        local count=0
        while kill -0 "$pid" 2>/dev/null && [ "$count" -lt 15 ]; do
            sleep 1
            count=$((count + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            rm -f "$tmpout"
            return 1
        fi
        wait "$pid" 2>/dev/null
        local rc=$?
        rm -f "$tmpout"
        return $rc
    fi
}

# ── Get Claude version string (timeout-safe) ───
get_claude_version() {
    if check_cmd timeout; then
        timeout 10 claude --version 2>/dev/null
    else
        local tmpout
        tmpout=$(mktemp "${TMPDIR:-/tmp}/claude-ver.XXXXXX" 2>/dev/null || echo "$HOME/tmp/.claude-ver-$$")
        claude --version >"$tmpout" 2>/dev/null &
        local pid=$!
        local count=0
        while kill -0 "$pid" 2>/dev/null && [ "$count" -lt 10 ]; do
            sleep 1
            count=$((count + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            rm -f "$tmpout"
            echo "unknown"
            return
        fi
        wait "$pid" 2>/dev/null
        cat "$tmpout" 2>/dev/null || echo "unknown"
        rm -f "$tmpout"
    fi
}

# ── Disk space helper (returns available MB) ────
get_available_mb() {
    [ -n "${DRY_AVAIL_MB:-}" ] && { echo "$DRY_AVAIL_MB"; return; }
    df -m "$HOME" 2>/dev/null | awk 'NR==2 {print $4}'
}

# ── Nested-proot probe ─────────────────────────
# Tier 0 (Lean via proot-distro) fails if Termux is already under proot —
# "Error: proot-distro should not be executed under PRoot." We detect by
# checking for PROOT_TMP_DIR / PROOT_L2S_DIR env markers, or probing
# proot-distro's refusal. Returns 0 if we ARE nested (Tier 0 will fail).
check_nested_proot() {
    [ "${DRY_NESTED:-0}" = "1" ] && return 0
    [ "$DRY_RUN" = "1" ] && return 1
    [ -n "${PROOT_TMP_DIR:-}${PROOT_L2S_DIR:-}" ] && return 0
    if check_cmd proot-distro; then
        proot-distro install ubuntu 2>&1 | grep -q "should not be executed under PRoot" && return 0
    fi
    return 1
}

# ── Tier 1 (nanoda_lib) detection ──────────────
check_nanoda() {
    [ -x "$NANODA_DIR/target/release/nanoda_bin" ]
}

# ── Tier 0 (Lean in proot-distro ubuntu) detection ─
check_lean_in_proot() {
    check_cmd proot-distro || return 1
    proot-distro login ubuntu -- bash -c 'source ~/.elan/env 2>/dev/null; command -v lean >/dev/null' &>/dev/null
}

# ── Status report ───────────────────────────────
show_status() {
    echo ""
    echo -e "${BOLD}🔍 Current Termux Environment${NC}"
    echo "================================"
    echo -e "   Script version: ${BOLD}v${SCRIPT_VERSION}${NC}"
    echo ""

    echo "📦 Core:"
    if check_pkg nodejs; then
        if check_node_version; then
            ok "Node.js $(node --version 2>/dev/null)"
        else
            warn "Node.js $(node --version 2>/dev/null) — version ${MIN_NODE_MAJOR}+ required for Claude Code"
        fi
    else
        warn "Node.js not installed"
    fi
    check_pkg python  && ok "Python $(python --version 2>/dev/null | cut -d' ' -f2)" || warn "Python not installed"
    check_pkg proot   && ok "proot installed"                              || warn "proot not installed"
    check_pkg git     && ok "git $(git --version 2>/dev/null | cut -d' ' -f3)" || warn "git not installed"
    check_cmd claude  && ok "Claude Code $(get_claude_version)"            || warn "Claude Code not installed"
    check_pkg gh      && ok "GitHub CLI $(gh --version 2>/dev/null | head -1 | cut -d' ' -f3)" || info "GitHub CLI not installed"

    echo ""
    echo "📐 Math & Science:"
    check_pkg pari            && ok "PARI/GP"    || info "PARI/GP not installed"
    check_pkg maxima          && ok "Maxima"     || info "Maxima not installed"
    check_pkg python-numpy    && ok "NumPy"      || { check_pip numpy      && ok "NumPy (pip)"      || info "NumPy not installed"; }
    check_pkg python-scipy    && ok "SciPy"      || { check_pip scipy      && ok "SciPy (pip)"      || info "SciPy not installed"; }
    check_pip sympy           && ok "SymPy"      || info "SymPy not installed"
    check_pkg matplotlib      && ok "Matplotlib" || { check_pip matplotlib && ok "Matplotlib (pip)" || info "Matplotlib not installed"; }

    echo ""
    echo "📄 Documents & Typesetting:"
    check_pkg texlive-installer && ok "TexLive"             || info "TexLive not installed"
    check_pkg tectonic          && ok "Tectonic"            || info "Tectonic not installed"
    check_pkg poppler           && ok "Poppler (PDF tools)" || info "Poppler not installed"

    echo ""
    echo "🔬 Formal Verification:"
    if check_nanoda; then
        ok "nanoda_lib (Tier 1, check-only) installed at $NANODA_DIR"
    else
        info "nanoda_lib (Tier 1) not installed — native ARM64 Lean proof checker"
    fi
    if check_lean_in_proot; then
        local lean_ver
        lean_ver=$(proot-distro login ubuntu -- bash -c 'source ~/.elan/env 2>/dev/null; lean --version 2>/dev/null' 2>/dev/null | head -1)
        ok "Lean 4 via proot-distro (Tier 0, full authoring) — ${lean_ver:-installed}"
    elif check_nested_proot; then
        info "Lean 4 via proot-distro (Tier 0) blocked — Termux appears nested in proot. Use Tier 1."
    else
        info "Lean 4 via proot-distro (Tier 0) not installed — full authoring + checking"
    fi

    echo ""
    echo "⚙️  Shell Config:"
    check_bashrc "proot -b /data/data/com.termux/files/usr/tmp:/tmp claude" && ok "Claude proot alias in .bashrc" || warn "Claude proot alias missing"
    check_bashrc "export TMPDIR"  && ok "TMPDIR configured"                || warn "TMPDIR not configured"
    [ -d "$HOME/storage/downloads" ] && ok "Storage access enabled"        || warn "Storage not set up (run termux-setup-storage)"

    echo ""
    echo "🧰 Local Execution Coverage:"
    info "These tools let Claude run computations and compile locally."
    info "Without them, Claude still reasons — just can't execute."
    echo ""
    check_cmd python                                           && ok "Python runtime available"                     || info "Python not installed — no local computation"
    (check_pkg pari || check_pkg maxima)                       && ok "CAS available ($(check_pkg pari && echo 'PARI/GP')$(check_pkg pari && check_pkg maxima && echo ', ')$(check_pkg maxima && echo 'Maxima'))" || info "No CAS — symbolic math runs in-context only"
    check_pip numpy                                            && ok "NumPy available (numerical/scientific)"       || info "NumPy not installed — no numerical execution"
    check_pip scipy                                            && ok "SciPy available (stochastic/optimization)"    || info "SciPy not installed"
    check_pip sympy                                            && ok "SymPy available (symbolic computation)"       || info "SymPy not installed"
    (check_pkg texlive-installer || check_pkg tectonic)        && ok "LaTeX available (paper compilation)"          || info "No LaTeX — papers need external compilation"
    check_cmd git                                              && ok "Git available"                                || info "Git not installed"
    check_pkg gh                                               && ok "GitHub CLI available"                         || info "GitHub CLI not installed"
    (check_nanoda || check_lean_in_proot)                      && ok "Formal proof checker available"               || info "No proof checker — formal verification in-context only"

    echo ""
    echo "🐍 Python Modules (pip):"
    if check_cmd pip; then
        pip list --format=columns 2>/dev/null | tail -n +3
    else
        warn "pip not available"
    fi

    echo ""
}

if [ "$MODE" = "status" ]; then
    show_status
    exit 0
fi

# ── Main setup ──────────────────────────────────
echo ""
echo -e "${BOLD}🛠️  Claude Code — Termux Setup v${SCRIPT_VERSION}${NC}"
echo "================================"
echo ""

# Step 1: Update packages
echo "📦 [1/7] Updating packages..."
if [ "$DRY_RUN" = "1" ]; then
    echo "   [DRY] would run: pkg update -y && pkg upgrade -y"
    WOULD_INSTALL+=("run: pkg update + pkg upgrade")
    ok "Packages updated (dry-run)"
elif pkg update -y && pkg upgrade -y; then
    ok "Packages updated"
else
    fail "Package update failed. Check your network connection."
    exit 1
fi

# Step 2: Install core dependencies
echo ""
echo "📦 [2/7] Installing core dependencies..."

for dep in nodejs python git proot; do
    if [ "$DRY_RUN" = "1" ]; then
        echo "   [DRY] would install $dep"
        WOULD_INSTALL+=("pkg: $dep (core)")
        ok "$dep installed (dry-run)"
        continue
    fi
    if check_pkg "$dep"; then
        ok "$dep already installed"
    else
        echo "   📦 Installing $dep..."
        if pkg install "$dep" -y; then
            ok "$dep installed"
        else
            fail "$dep installation failed"
            if [ "$dep" = "nodejs" ] || [ "$dep" = "proot" ]; then
                fail "Cannot continue without $dep."
                exit 1
            fi
        fi
    fi
done

# Step 3: Validate Node.js version
echo ""
echo "📦 [3/7] Validating Node.js version..."
if [ "$DRY_RUN" = "1" ]; then
    ok "Node.js version check (dry-run — assuming ≥v${MIN_NODE_MAJOR})"
elif check_node_version; then
    ok "Node.js $(node --version 2>/dev/null) meets minimum (v${MIN_NODE_MAJOR}+)"
else
    NODE_CURRENT=$(node --version 2>/dev/null || echo "unknown")
    fail "Node.js ${NODE_CURRENT} is below the required v${MIN_NODE_MAJOR}+"
    info "Claude Code requires Node.js ${MIN_NODE_MAJOR} or newer."
    info "Try: pkg upgrade nodejs"
    echo ""
    fail "Cannot continue with outdated Node.js."
    exit 1
fi

# Step 4: Check Claude Code
echo ""
echo "📦 [4/7] Checking Claude Code..."
if [ "$DRY_RUN" = "1" ]; then
    echo "   [DRY] would run: npm install -g $CLAUDE_PIN"
    WOULD_INSTALL+=("npm: $CLAUDE_PIN")
    ok "Claude Code installed (dry-run)"
elif check_cmd claude; then
    if check_claude_health; then
        ok "Claude Code working ($(get_claude_version))"
    else
        warn "Claude Code binary found but not responding (likely 2.x without android-arm64 native binary)"
        echo "   📦 Reinstalling pinned to 1.x ($CLAUDE_PIN)..."
        npm install -g "$CLAUDE_PIN" && ok "Claude Code reinstalled" || { fail "Reinstall failed"; exit 1; }
    fi
else
    echo "   📦 Installing Claude Code ($CLAUDE_PIN)..."
    npm install -g "$CLAUDE_PIN" && ok "Claude Code installed" || { fail "Installation failed"; exit 1; }
fi

# Step 5: Storage access
echo ""
echo "📂 [5/7] Setting up storage access..."
if [ "$DRY_RUN" = "1" ]; then
    echo "   [DRY] would run: termux-setup-storage (unless already configured)"
    WOULD_INSTALL+=("run: termux-setup-storage")
    ok "Storage access (dry-run)"
elif [ -d "$HOME/storage/downloads" ]; then
    ok "Storage already configured"
else
    if [ "$MODE" = "all" ]; then
        echo ""
        warn "Storage access requires an Android permission dialog."
        warn "Skipped in --all mode. Run manually after setup:"
        echo ""
        echo -e "      ${BOLD}termux-setup-storage${NC}"
        echo ""
    else
        echo ""
        warn "Android will show a permission dialog."
        echo "   👆 Tap ALLOW when it appears."
        echo ""
        read -p "   Press Enter to continue..." _
        termux-setup-storage
        sleep 2
        if [ -d "$HOME/storage/downloads" ]; then
            ok "Storage access granted"
        else
            warn "Storage may not be set up."
            info "Re-run termux-setup-storage or: Android Settings → Apps → Termux → Permissions → Storage"
        fi
    fi
fi

# Step 6: Create tmp directory
echo ""
echo "📁 [6/7] Creating tmp directory..."
if [ "$DRY_RUN" = "1" ]; then
    echo "   [DRY] would create: $HOME/tmp"
    WOULD_INSTALL+=("mkdir: \$HOME/tmp")
    ok "$HOME/tmp ready (dry-run)"
else
    mkdir -p "$HOME/tmp"
    ok "$HOME/tmp ready"
fi

# Step 7: Configure .bashrc
echo ""
echo "⚙️  [7/7] Configuring shell..."
if [ "$DRY_RUN" = "1" ]; then
    echo "   [DRY] would append Claude proot alias + TMPDIR export to \$HOME/.bashrc"
    WOULD_INSTALL+=("edit: ~/.bashrc (proot alias, TMPDIR)")
    ok ".bashrc would be configured (dry-run)"
else
    BASHRC="$HOME/.bashrc"
    touch "$BASHRC"
    CHANGED=false

    if ! check_bashrc "proot -b /data/data/com.termux/files/usr/tmp:/tmp claude"; then
        echo "" >> "$BASHRC"
        echo "# Claude Code setup" >> "$BASHRC"
        echo "alias claude='proot -b /data/data/com.termux/files/usr/tmp:/tmp claude'" >> "$BASHRC"
        CHANGED=true
    fi

    if ! check_bashrc "export TMPDIR"; then
        echo "export TMPDIR=\$HOME/tmp" >> "$BASHRC"
        echo "mkdir -p \$TMPDIR 2>/dev/null" >> "$BASHRC"
        CHANGED=true
    fi

    [ "$CHANGED" = true ] && ok "Added Claude Code config to .bashrc" || ok ".bashrc already configured"
fi

export TMPDIR="$HOME/tmp"

# ── Optional packages ───────────────────────────
echo ""
echo "================================"
echo ""

# ── Disk space check ───────────────────────────
AVAILABLE_MB=$(get_available_mb)
if [ -n "$AVAILABLE_MB" ]; then
    if [ "$AVAILABLE_MB" -lt 500 ]; then
        warn "Low disk space: ~${AVAILABLE_MB}MB available."
        warn "Consider freeing space before installing large packages."
        echo ""
    else
        info "Disk space: ~${AVAILABLE_MB}MB available."
        echo ""
    fi
fi

if [ "$MODE" = "all" ]; then
    # Core menu (items 1-10)
    if [ -n "$AVAILABLE_MB" ] && [ "$AVAILABLE_MB" -lt 2000 ]; then
        warn "Less than 2GB free — skipping TexLive to avoid filling disk."
        info "Consider Tectonic (lighter alternative) once space is freed."
        SELECTIONS="1 2 3 4 5 6 8 9 10"
    else
        SELECTIONS="1 2 3 4 5 6 7 8 9 10"
    fi
    # Proof checkers (items 11-12) — Tier 1 always; Tier 0 only if not nested-proot
    SELECTIONS="$SELECTIONS 11"
    if check_nested_proot; then
        warn "Nested-proot detected — skipping Lean 4 (Tier 0). nanoda_lib (Tier 1) will be installed."
    elif [ -n "$AVAILABLE_MB" ] && [ "$AVAILABLE_MB" -lt 3000 ]; then
        warn "Less than 3GB free — skipping Lean 4 (Tier 0, ~3GB needed). Tier 1 still applies."
    else
        SELECTIONS="$SELECTIONS 12"
    fi
else
    echo "📐 Optional packages:"
    echo ""
    check_pkg pari              && echo "    1) PARI/GP          ✅ installed" || echo "    1) PARI/GP          — number theory & algebra"
    check_pkg maxima            && echo "    2) Maxima           ✅ installed" || echo "    2) Maxima           — computer algebra system"
    check_pkg python-numpy      && echo "    3) NumPy            ✅ installed" || echo "    3) NumPy            — numerical computing"
    check_pkg python-scipy      && echo "    4) SciPy            ✅ installed" || echo "    4) SciPy            — scientific computing"
    check_pip sympy             && echo "    5) SymPy            ✅ installed" || echo "    5) SymPy            — symbolic mathematics"
    check_pkg matplotlib        && echo "    6) Matplotlib       ✅ installed" || echo "    6) Matplotlib       — plotting & charts"
    check_pkg texlive-installer && echo "    7) TexLive          ✅ installed" || echo "    7) TexLive          — full LaTeX (~1-2GB)"
    check_pkg tectonic          && echo "    8) Tectonic         ✅ installed" || echo "    8) Tectonic         — lightweight LaTeX"
    check_pkg gh                && echo "    9) GitHub CLI       ✅ installed" || echo "    9) GitHub CLI       — gh auth, PRs, issues"
    check_pkg poppler           && echo "   10) Poppler          ✅ installed" || echo "   10) Poppler          — PDF tools"
    echo ""
    echo "   🔬 Formal proof verification (from proof-anywhere):"
    check_nanoda                && echo "   11) nanoda_lib       ✅ installed" || echo "   11) nanoda_lib       — Lean 4 proof checker, native ARM64 (Tier 1)"
    if check_lean_in_proot; then
        echo "   12) Lean 4 (proot)  ✅ installed"
    elif check_nested_proot; then
        echo "   12) Lean 4 (proot)   ⚠️  nested-proot environment — Tier 0 unavailable, use Tier 1"
    else
        echo "   12) Lean 4 (proot)  — full authoring + checking via Ubuntu proot (~3GB, Tier 0)"
    fi
    echo ""
    echo "   Enter numbers (e.g. 1 3 11), 'all', or Enter to skip:"
    read -p "   > " SELECTIONS
fi

if [ -n "$SELECTIONS" ]; then
    echo ""

    install_pkg() {
        local pkg_name="$1"
        local display_name="$2"
        if [ "$DRY_RUN" = "1" ]; then
            echo "   [DRY] would install $display_name ($pkg_name)"
            WOULD_INSTALL+=("pkg: $display_name ($pkg_name)")
            return 0
        fi
        if check_pkg "$pkg_name"; then
            ok "$display_name already installed"
        else
            echo "   📦 Installing $display_name..."
            pkg install "$pkg_name" -y && ok "$display_name installed" || warn "$display_name installation failed (continuing)"
        fi
    }

    install_pip() {
        local module="$1"
        local display_name="$2"
        if [ "$DRY_RUN" = "1" ]; then
            echo "   [DRY] would pip-install $display_name ($module)"
            WOULD_INSTALL+=("pip: $display_name ($module)")
            return 0
        fi
        if check_pip "$module"; then
            ok "$display_name already installed"
        else
            echo "   📦 Installing $display_name..."
            pip install --break-system-packages "$module" && ok "$display_name installed" || warn "$display_name installation failed (continuing)"
        fi
    }

    # Tier 1: nanoda_lib — native Rust Lean 4 proof checker, ~5K LOC, ARM64-native
    install_nanoda() {
        if [ "$DRY_RUN" = "1" ]; then
            echo "   [DRY] would install Rust toolchain + clone+build nanoda_lib at $NANODA_DIR"
            WOULD_INSTALL+=("nanoda_lib (Tier 1): pkg rust, git clone, cargo build --release")
            return 0
        fi
        if check_nanoda; then
            ok "nanoda_lib already built at $NANODA_DIR"
            return 0
        fi
        install_pkg rust "Rust toolchain"
        if ! check_cmd cargo; then
            warn "cargo unavailable — cannot build nanoda_lib"
            return 1
        fi
        if [ ! -d "$NANODA_DIR/.git" ]; then
            echo "   📦 Cloning nanoda_lib..."
            git clone --depth 1 https://github.com/ammkrn/nanoda_lib.git "$NANODA_DIR" \
                || { warn "nanoda_lib clone failed"; return 1; }
        fi
        echo "   📦 Building nanoda_lib (release) — this takes a few minutes on-device..."
        (cd "$NANODA_DIR" && cargo build --release) \
            && ok "nanoda_lib built — $NANODA_DIR/target/release/nanoda_bin" \
            || { warn "nanoda_lib build failed"; return 1; }
    }

    # Tier 0: Lean 4 via proot-distro + elan. Requires non-nested Termux.
    install_lean_proot() {
        if check_nested_proot; then
            warn "Nested-proot detected — Tier 0 (Lean via proot-distro) is not available."
            info "Use Tier 1 (nanoda_lib, option 11) for proof checking on this device."
            return 1
        fi
        if [ "$DRY_RUN" = "1" ]; then
            echo "   [DRY] would install proot-distro + Ubuntu + elan + Lean 4 (~3GB)"
            WOULD_INSTALL+=("Lean 4 (Tier 0): proot-distro, Ubuntu, elan, lean stable")
            return 0
        fi
        install_pkg proot-distro "proot-distro"
        if ! check_cmd proot-distro; then
            warn "proot-distro missing — aborting Lean install"
            return 1
        fi
        local ubuntu_rootfs="/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu"
        if [ -d "$ubuntu_rootfs" ]; then
            ok "Ubuntu already installed in proot-distro"
        else
            local avail_kb
            avail_kb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')
            if [ -n "${avail_kb:-}" ] && [ "$avail_kb" -lt 3145728 ]; then
                warn "Low space: $((avail_kb/1024)) MB free, ~3GB recommended for Ubuntu + Lean."
                if [ "$MODE" != "all" ]; then
                    read -p "   Continue anyway? (y/n) " yn
                    [ "$yn" = "y" ] || [ "$yn" = "Y" ] || { info "Skipped."; return 1; }
                else
                    warn "Skipping in --all mode."
                    return 1
                fi
            fi
            echo "   📦 Installing Ubuntu in proot-distro (~600MB download)..."
            local install_output install_rc
            install_output=$(proot-distro install ubuntu 2>&1)
            install_rc=$?
            if [ "$install_rc" -eq 0 ]; then
                ok "Ubuntu installed"
            elif echo "$install_output" | grep -qi "already installed"; then
                ok "Ubuntu already installed (detected via install error)"
            else
                warn "Ubuntu install failed"
                echo "$install_output" | sed 's/^/      /'
                return 1
            fi
        fi
        echo "   📦 Installing elan + Lean 4 inside Ubuntu proot..."
        proot-distro login ubuntu -- bash -c '
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -y >/dev/null
            apt-get install -y --no-install-recommends curl ca-certificates git >/dev/null
            if [ ! -d "$HOME/.elan" ]; then
                curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
                    | sh -s -- -y --default-toolchain stable
            fi
            source "$HOME/.elan/env"
            lean --version
        ' && ok "Lean 4 installed in Ubuntu proot (run: proot-distro login ubuntu)" \
          || { warn "Lean install inside proot failed"; return 1; }
    }

    [[ "$SELECTIONS" == *"all"* ]] && SELECTIONS="1 2 3 4 5 6 7 8 9 10 11 12"

    for sel in $SELECTIONS; do
        case $sel in
            1)  install_pkg pari "PARI/GP" ;;
            2)  install_pkg maxima "Maxima" ;;
            3)  install_pkg python-numpy "NumPy" ;;
            4)  install_pkg python-scipy "SciPy" ;;
            5)  install_pip sympy "SymPy (+ mpmath)" ;;
            6)  install_pkg matplotlib "Matplotlib" ;;
            7)
                if [ -n "$AVAILABLE_MB" ] && [ "$AVAILABLE_MB" -lt 2000 ]; then
                    warn "TexLive needs ~1-2GB but only ~${AVAILABLE_MB}MB available."
                    if [ "$MODE" != "all" ]; then
                        read -p "   Install anyway? (y/n) " yn
                        if [ "$yn" != "y" ] && [ "$yn" != "Y" ]; then
                            info "Skipped. Tectonic (option 8) is a lighter alternative."
                            continue
                        fi
                    else
                        warn "Skipping TexLive (insufficient space)."
                        continue
                    fi
                fi
                install_pkg texlive-installer "TexLive"
                ;;
            8)  install_pkg tectonic "Tectonic" ;;
            9)
                install_pkg gh "GitHub CLI"
                if check_cmd gh; then
                    if gh auth status &>/dev/null 2>&1; then
                        ok "Already authenticated with GitHub"
                    elif [ "$MODE" = "all" ]; then
                        info "GitHub CLI installed. Run 'gh auth login' to authenticate."
                    else
                        echo ""
                        echo "   🔑 GitHub authentication needed."
                        read -p "   Authenticate now? (y/n) " yn
                        if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
                            gh auth login
                        else
                            info "Skipped. Run 'gh auth login' later."
                        fi
                    fi
                fi
                ;;
            10) install_pkg poppler "Poppler (PDF tools)" ;;
            11) install_nanoda ;;
            12) install_lean_proot ;;
        esac
    done
fi

# ── Launch ──────────────────────────────────────
echo ""
echo "================================"

if [ "$DRY_RUN" = "1" ]; then
    echo "✅ Dry-run complete — no side effects."
    echo ""
    echo "📋 Would have performed ${#WOULD_INSTALL[@]} action(s):"
    for action in "${WOULD_INSTALL[@]}"; do
        echo "   • $action"
    done
    echo ""
    echo "🔀 Effective flags: MODE=$MODE, DRY_RUN=$DRY_RUN${DRY_NESTED:+, DRY_NESTED=$DRY_NESTED}${DRY_AVAIL_MB:+, DRY_AVAIL_MB=$DRY_AVAIL_MB}"
    echo ""
    exit 0
fi

echo "✅ Setup complete!"
echo ""
echo "📂 Use ~/storage/downloads to share files with Android apps."
[ ! -d "$HOME/storage/downloads" ] && warn "Storage not set up yet — run: termux-setup-storage"
echo "🔍 Run ./setup-claude-termux.sh --status anytime."
echo ""
echo "🚀 Launching Claude Code..."
echo ""

proot -b /data/data/com.termux/files/usr/tmp:/tmp claude

echo ""
echo "👋 Claude Code exited. Your Termux session is still active."
echo "   Next time just type: claude"
echo ""
