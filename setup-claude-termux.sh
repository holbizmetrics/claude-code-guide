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
#
# What this does:
#   1. Updates all Termux packages
#   2. Installs Node.js, Python, proot, git (if missing)
#   3. Installs Claude Code (or fixes broken install)
#   4. Sets up Android storage access
#   5. Configures .bashrc (proot alias, TMPDIR)
#   6. Optional: math, science, LaTeX, GitHub CLI
#   7. Launches Claude Code
#
# Source: https://skool.com/early-ai-adopters
# ══════════════════════════════════════════════════

# ── Parse flags (scan all args, not just $1) ────
MODE="interactive"
for arg in "$@"; do
    case "$arg" in
        --help|-h)   MODE="help" ;;
        --status)    MODE="status" ;;
        --all)       MODE="all" ;;
    esac
done

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

# ── Status report ───────────────────────────────
show_status() {
    echo ""
    echo -e "${BOLD}🔍 Current Termux Environment${NC}"
    echo "================================"
    echo ""

    echo "📦 Core:"
    check_pkg nodejs  && ok "Node.js $(node --version 2>/dev/null)"       || warn "Node.js not installed"
    check_pkg python  && ok "Python $(python --version 2>/dev/null | cut -d' ' -f2)" || warn "Python not installed"
    check_pkg proot   && ok "proot installed"                              || warn "proot not installed"
    check_pkg git     && ok "git $(git --version 2>/dev/null | cut -d' ' -f3)" || warn "git not installed"
    check_cmd claude  && ok "Claude Code $(claude --version 2>/dev/null)"  || warn "Claude Code not installed"
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
    echo "⚙️  Shell Config:"
    check_bashrc "proot -b /data/data/com.termux/files/usr/tmp:/tmp claude" && ok "Claude proot alias in .bashrc" || warn "Claude proot alias missing"
    check_bashrc "export TMPDIR"  && ok "TMPDIR configured"                || warn "TMPDIR not configured"
    [ -d "$HOME/storage/downloads" ] && ok "Storage access enabled"        || warn "Storage not set up (run termux-setup-storage)"

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
echo -e "${BOLD}🛠️  Claude Code — Termux Setup${NC}"
echo "================================"
echo ""

# Step 1: Update packages
echo "📦 [1/6] Updating packages..."
if pkg update -y && pkg upgrade -y; then
    ok "Packages updated"
else
    fail "Package update failed. Check your network connection."
    exit 1
fi

# Step 2: Install core dependencies
echo ""
echo "📦 [2/6] Installing core dependencies..."

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

# Step 3: Check Claude Code
echo ""
echo "📦 [3/6] Checking Claude Code..."
if check_cmd claude; then
    # Timeout prevents hanging on broken installs
    if timeout 15 claude --version &>/dev/null 2>&1; then
        ok "Claude Code working ($(timeout 10 claude --version 2>/dev/null))"
    else
        warn "Claude Code binary found but broken (Node.js version change?)"
        echo "   📦 Reinstalling..."
        npm install -g @anthropic-ai/claude-code && ok "Claude Code reinstalled" || { fail "Reinstall failed"; exit 1; }
    fi
else
    echo "   📦 Installing Claude Code..."
    npm install -g @anthropic-ai/claude-code && ok "Claude Code installed" || { fail "Installation failed"; exit 1; }
fi

# Step 4: Storage access
echo ""
echo "📂 [4/6] Setting up storage access..."
if [ -d "$HOME/storage/downloads" ]; then
    ok "Storage already configured"
else
    if [ "$MODE" = "all" ]; then
        # --all mode: attempt silently, don't block on dialog
        termux-setup-storage 2>/dev/null || true
        sleep 2
        [ -d "$HOME/storage/downloads" ] && ok "Storage access granted" || warn "Storage needs manual setup: run termux-setup-storage"
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

# Step 5: Create tmp directory
echo ""
echo "📁 [5/6] Creating tmp directory..."
mkdir -p "$HOME/tmp"
ok "$HOME/tmp ready"

# Step 6: Configure .bashrc
echo ""
echo "⚙️  [6/6] Configuring shell..."
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

# Export TMPDIR for this session (alias won't expand in a script, but TMPDIR does)
export TMPDIR="$HOME/tmp"

# ── Optional packages ───────────────────────────
echo ""
echo "================================"
echo ""

if [ "$MODE" = "all" ]; then
    SELECTIONS="1 2 3 4 5 6 7 8 9 10"
else
    echo "📐 Optional packages:"
    echo ""
    check_pkg pari              && echo "    1) PARI/GP          ✅ installed" || echo "    1) PARI/GP          — number theory & algebra"
    check_pkg maxima            && echo "    2) Maxima           ✅ installed" || echo "    2) Maxima           — computer algebra system"
    check_pkg python-numpy      && echo "    3) NumPy            ✅ installed" || echo "    3) NumPy            — numerical computing"
    check_pkg python-scipy      && echo "    4) SciPy            ✅ installed" || echo "    4) SciPy            — scientific computing"
    check_pip sympy             && echo "    5) SymPy            ✅ installed" || echo "    5) SymPy            — symbolic mathematics"
    check_pkg matplotlib        && echo "    6) Matplotlib       ✅ installed" || echo "    6) Matplotlib       — plotting & charts"
    check_pkg texlive-installer && echo "    7) TexLive          ✅ installed" || echo "    7) TexLive          — LaTeX typesetting"
    check_pkg tectonic          && echo "    8) Tectonic         ✅ installed" || echo "    8) Tectonic         — modern LaTeX compiler"
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

    # Case numbers match menu numbers exactly:
    #  1=PARI/GP  2=Maxima     3=NumPy   4=SciPy   5=SymPy
    #  6=Matplotlib  7=TexLive  8=Tectonic  9=GitHub CLI  10=Poppler
    for sel in $SELECTIONS; do
        case $sel in
            1)  install_pkg pari "PARI/GP" ;;
            2)  install_pkg maxima "Maxima" ;;
            3)  install_pkg python-numpy "NumPy" ;;
            4)  install_pkg python-scipy "SciPy" ;;
            5)  install_pip sympy "SymPy (+ mpmath)" ;;
            6)  install_pkg matplotlib "Matplotlib" ;;
            7)  install_pkg texlive-installer "TexLive" ;;
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
echo "🔍 Run ./setup-claude-termux.sh --status anytime."
echo ""
echo "🚀 Launching Claude Code..."
echo ""

# Launch with proot — if Claude exits or crashes,
# the user stays in their shell and can debug
proot -b /data/data/com.termux/files/usr/tmp:/tmp claude

# Claude exited
echo ""
echo "👋 Claude Code exited. Your Termux session is still active."
echo "   Next time just type: claude"
echo ""
