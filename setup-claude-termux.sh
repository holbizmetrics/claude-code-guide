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
#   ./setup-claude-termux.sh --help   # Show this help
#   ./setup-claude-termux.sh --version # Show version
#
# What this does:
#   1. Updates all Termux packages
#   2. Installs Node.js, Python, proot, git (if missing)
#   3. Validates Node.js version (≥18 required)
#   4. Installs Claude Code (or fixes broken install)
#   5. Sets up Android storage access
#   6. Configures .bashrc (proot alias, TMPDIR)
#   7. Optional: math, science, LaTeX, GitHub CLI
#
# After setup, Claude Code launches automatically.
#
# Source: https://skool.com/early-ai-adopters
# ══════════════════════════════════════════════════

SCRIPT_VERSION="1.1.1"
MIN_NODE_MAJOR=18

# ── Parse flags (scan all args, not just $1) ────
MODE="interactive"
for arg in "$@"; do
    case "$arg" in
        --help|-h)    MODE="help" ;;
        --status)     MODE="status" ;;
        --all)        MODE="all" ;;
        --version|-v) MODE="version" ;;
    esac
done

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
    df -m "$HOME" 2>/dev/null | awk 'NR==2 {print $4}'
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
    info "Lean 4 / Coq — no ARM64/Termux builds. Proof work uses natural-language mode."
    info "For formal verification, use Lean 4 on x86_64 Linux or Windows."

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
if pkg update -y && pkg upgrade -y; then
    ok "Packages updated"
else
    fail "Package update failed. Check your network connection."
    exit 1
fi

# Step 2: Install core dependencies
echo ""
echo "📦 [2/7] Installing core dependencies..."

for dep in nodejs python git proot; do
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
if check_node_version; then
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
if check_cmd claude; then
    if check_claude_health; then
        ok "Claude Code working ($(get_claude_version))"
    else
        warn "Claude Code binary found but not responding (Node.js version change?)"
        echo "   📦 Reinstalling..."
        npm install -g @anthropic-ai/claude-code && ok "Claude Code reinstalled" || { fail "Reinstall failed"; exit 1; }
    fi
else
    echo "   📦 Installing Claude Code..."
    npm install -g @anthropic-ai/claude-code && ok "Claude Code installed" || { fail "Installation failed"; exit 1; }
fi

# Step 5: Storage access
echo ""
echo "📂 [5/7] Setting up storage access..."
if [ -d "$HOME/storage/downloads" ]; then
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
mkdir -p "$HOME/tmp"
ok "$HOME/tmp ready"

# Step 7: Configure .bashrc
echo ""
echo "⚙️  [7/7] Configuring shell..."
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
    if [ -n "$AVAILABLE_MB" ] && [ "$AVAILABLE_MB" -lt 2000 ]; then
        warn "Less than 2GB free — skipping TexLive to avoid filling disk."
        info "Consider Tectonic (lighter alternative) once space is freed."
        SELECTIONS="1 2 3 4 5 6 8 9 10"
    else
        SELECTIONS="1 2 3 4 5 6 7 8 9 10"
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
    echo "   Enter numbers (e.g. 1 3 9), 'all', or Enter to skip:"
    read -p "   > " SELECTIONS
fi

if [ -n "$SELECTIONS" ]; then
    echo ""

    install_pkg() {
        local pkg_name="$1"
        local display_name="$2"
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
        if check_pip "$module"; then
            ok "$display_name already installed"
        else
            echo "   📦 Installing $display_name..."
            pip install --break-system-packages "$module" && ok "$display_name installed" || warn "$display_name installation failed (continuing)"
        fi
    }

    [[ "$SELECTIONS" == *"all"* ]] && SELECTIONS="1 2 3 4 5 6 7 8 9 10"

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
        esac
    done
fi

# ── Launch ──────────────────────────────────────
echo ""
echo "================================"
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
