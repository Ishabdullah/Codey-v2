#!/usr/bin/env bash
#
# Codey-v2 — Full Installation Script
#
# Installs everything needed to run Codey-v2 on Termux (Android) or Linux:
#   • System packages (pkg / apt / dnf / pacman)
#   • Python dependencies
#   • llama.cpp (built from source)
#   • All three models:
#       7B  — Qwen2.5-Coder-7B-Instruct Q4_K_M  (official Qwen HF)
#       0.5B — planner-codey  (Ishabdullah HF, falls back to Qwen official)
#       Embed — nomic-embed-text-v1.5 Q4_K_M    (nomic-ai HF)
#   • PATH, executable bits, daemon directory
#
# Usage:
#   ./install.sh           — interactive
#   ./install.sh --yes     — non-interactive (CI / automation)
#

set -e

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Paths ─────────────────────────────────────────────────────────────────────
CODEY_V2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_CPP_DIR="$HOME/llama.cpp"
MODELS_DIR="$HOME/models"
PRIMARY_MODEL_DIR="$MODELS_DIR/qwen2.5-coder-7b"
SECONDARY_MODEL_DIR="$MODELS_DIR/qwen2.5-0.5b"
EMBED_MODEL_DIR="$MODELS_DIR/nomic-embed"

# Filenames — must match utils/config.py exactly
PRIMARY_MODEL_FILE="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
SECONDARY_MODEL_FILE="planner-codey.gguf"          # ← matches PLANNER_MODEL_PATH in config.py
EMBED_MODEL_FILE="nomic-embed-text-v1.5.Q4_K_M.gguf"

# ── Model URLs ────────────────────────────────────────────────────────────────
# 7B coder — official Qwen HF
PRIMARY_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"

# 0.5B planner — Ishymoto/qwen2.5-0.5b-codey-planner-gguf (custom fine-tune)
# Fallback to official Qwen if HF is unreachable.
SECONDARY_MODEL_URL="https://huggingface.co/Ishymoto/qwen2.5-0.5b-codey-planner-gguf/resolve/main/qwen2.5-0.5b-instruct.Q4_K_M.gguf"
SECONDARY_MODEL_FALLBACK_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q8_0.gguf"

# Embedding model — nomic-ai HF
EMBED_MODEL_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf"

# ── Helpers ───────────────────────────────────────────────────────────────────
print_status()  { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC}   $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERR]${NC}  $1"; }
print_step()    { echo; echo -e "${CYAN}${BOLD}── $1 ──${NC}"; }

is_termux() { [ -d "/data/data/com.termux" ]; }

# ── 1. Environment check ──────────────────────────────────────────────────────
check_termux() {
    print_step "Environment"
    if is_termux; then
        print_success "Termux detected"
    else
        print_warning "Not Termux — continuing (some paths may need adjustment)"
    fi
}

# ── 2. System packages ────────────────────────────────────────────────────────
install_system_deps() {
    print_step "System packages"

    if is_termux; then
        pkg update -y
        pkg install -y python cmake ninja clang wget curl git
        # pyarrow & pandas must come from pkg on Termux (pip wheels fail on aarch64)
        pkg install -y python-pyarrow python-pandas 2>/dev/null \
            || print_warning "python-pyarrow/pandas pkg install failed — pipeline features may not work"
        print_success "Termux packages installed"
    elif command -v apt &>/dev/null; then
        sudo apt update -y
        sudo apt install -y python3 python3-pip cmake ninja-build clang wget curl git
        print_success "apt packages installed"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip cmake ninja clang wget curl git
        print_success "dnf packages installed"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm python python-pip cmake ninja clang wget curl git
        print_success "pacman packages installed"
    else
        print_warning "Package manager not detected — install manually: python3 pip cmake ninja clang wget curl git"
    fi
}

# ── 3. Python dependencies ────────────────────────────────────────────────────
install_python_deps() {
    print_step "Python dependencies"

    # Upgrade pip first on non-Termux
    if ! is_termux; then
        pip3 install --upgrade pip
    fi

    cd "$CODEY_V2_DIR"

    # Install only what's needed for the core agent + GUI
    # (pipeline/training deps are optional — see requirements.txt for full list)
    pip3 install \
        "rich>=14.0.0" \
        "numpy>=1.24.0" \
        "watchdog>=3.0.0" \
        "aiohttp>=3.9.0" \
        "requests>=2.31.0" \
        "httpx>=0.27.0" \
        "pyyaml>=6.0" \
        "filelock>=3.13.0" \
        "tqdm>=4.65.0" \
        "hnswlib>=0.7.0" \
        || print_warning "Some pip packages failed — Codey-v2 may still work"

    print_success "Core Python packages installed"

    # Offer to install full pipeline deps
    if [ "$SKIP_CONFIRM" = false ]; then
        echo
        read -p "  Install pipeline/training extras? (large download, optional) [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            pip3 install -r "$CODEY_V2_DIR/requirements.txt" \
                || print_warning "Some pipeline packages may have failed (normal on Termux)"
        fi
    fi
}

# ── 4. llama.cpp ──────────────────────────────────────────────────────────────
install_llama_cpp() {
    print_step "llama.cpp"

    if [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        print_success "llama-server already built — skipping"
        return 0
    fi

    if [ -d "$LLAMA_CPP_DIR" ]; then
        print_status "Updating existing llama.cpp clone..."
        cd "$LLAMA_CPP_DIR"
        git pull || print_warning "git pull failed — building from existing source"
    else
        print_status "Cloning llama.cpp (shallow)..."
        git clone --depth 1 https://github.com/ggerganov/llama.cpp "$LLAMA_CPP_DIR" || {
            print_error "Failed to clone llama.cpp"
            return 1
        }
    fi

    cd "$LLAMA_CPP_DIR"
    print_status "Building llama.cpp — this takes 5–15 min on mobile..."

    cmake -B build -DLLAMA_CURL=ON -DBUILD_SHARED_LIBS=OFF || {
        print_error "cmake config failed"; return 1
    }
    cmake --build build --config Release -j"$(nproc)" || {
        print_error "Build failed — try closing other apps and re-running"
        return 1
    }

    if [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        print_success "llama.cpp built successfully"
    else
        print_error "llama-server binary not found after build"
        return 1
    fi
}

# ── 5. Models ─────────────────────────────────────────────────────────────────

check_disk_space() {
    local required_mb="$1" path="$2"
    local available_kb available_mb
    available_kb=$(df -k "$path" 2>/dev/null | tail -1 | awk '{print $4}')
    available_mb=$((available_kb / 1024))
    if [ "$available_mb" -lt "$required_mb" ]; then
        print_warning "Low disk space: need ~${required_mb}MB, have ${available_mb}MB"
        return 1
    fi
    print_success "Disk space OK (${available_mb}MB free)"
}

# download_file <url> <dest> <label>  — returns 0 on success
download_file() {
    local url="$1" output="$2" label="$3"
    print_status "Downloading $label..."
    if command -v wget &>/dev/null; then
        wget --show-progress -c -O "$output" "$url" 2>&1 && return 0
    elif command -v curl &>/dev/null; then
        curl -L -C - -o "$output" "$url" && return 0
    fi
    print_error "Download failed: $label"
    return 1
}

# file_ok <path> <min_bytes>  — returns 0 if file exists and is big enough
file_ok() {
    local path="$1" min="$2"
    [ -f "$path" ] || return 1
    local size
    size=$(stat -c%s "$path" 2>/dev/null || stat -f%z "$path" 2>/dev/null || echo 0)
    [ "$size" -gt "$min" ]
}

download_models() {
    print_step "Models"
    mkdir -p "$PRIMARY_MODEL_DIR" "$SECONDARY_MODEL_DIR" "$EMBED_MODEL_DIR"
    check_disk_space 8000 "$HOME" || true

    local PRIMARY_PATH="$PRIMARY_MODEL_DIR/$PRIMARY_MODEL_FILE"
    local SECONDARY_PATH="$SECONDARY_MODEL_DIR/$SECONDARY_MODEL_FILE"
    local EMBED_PATH="$EMBED_MODEL_DIR/$EMBED_MODEL_FILE"
    local all_present=true

    # ── 7B agent model ──────────────────────────────────────────────────────
    if file_ok "$PRIMARY_PATH" 4000000000; then
        print_success "7B agent model already present — skipping"
    else
        [ -f "$PRIMARY_PATH" ] && rm -f "$PRIMARY_PATH"
        all_present=false
        print_status "7B agent model (~4.7 GB) — official Qwen HF"
        if ! download_file "$PRIMARY_MODEL_URL" "$PRIMARY_PATH" "Qwen2.5-Coder-7B Q4_K_M"; then
            print_warning "Manual: wget -c '$PRIMARY_MODEL_URL' -O '$PRIMARY_PATH'"
        fi
    fi

    # ── 0.5B planner model ──────────────────────────────────────────────────
    if file_ok "$SECONDARY_PATH" 200000000; then
        print_success "0.5B planner model already present — skipping"
    else
        [ -f "$SECONDARY_PATH" ] && rm -f "$SECONDARY_PATH"
        all_present=false
        print_status "0.5B planner model — Ishymoto/qwen2.5-0.5b-codey-planner-gguf (~398 MB)"

        if ! download_file "$SECONDARY_MODEL_URL" "$SECONDARY_PATH" "qwen2.5-0.5b-codey-planner Q4_K_M"; then
            print_warning "HF unreachable — falling back to official Qwen2.5-0.5B"
            rm -f "$SECONDARY_PATH"
            download_file "$SECONDARY_MODEL_FALLBACK_URL" "$SECONDARY_PATH" "Qwen2.5-0.5B (fallback)" \
                || print_warning "Manual: wget -c '$SECONDARY_MODEL_FALLBACK_URL' -O '$SECONDARY_PATH'"
        fi
    fi

    # ── Embedding model ─────────────────────────────────────────────────────
    if file_ok "$EMBED_PATH" 50000000; then
        print_success "Embedding model already present — skipping"
    else
        [ -f "$EMBED_PATH" ] && rm -f "$EMBED_PATH"
        all_present=false
        print_status "Embedding model (~81 MB) — nomic-ai HF"
        download_file "$EMBED_MODEL_URL" "$EMBED_PATH" "nomic-embed-text-v1.5 Q4_K_M" \
            || print_warning "Manual: wget -c '$EMBED_MODEL_URL' -O '$EMBED_PATH'"
    fi

    $all_present && print_success "All models present" || true
}

# ── 6. Executables & PATH ─────────────────────────────────────────────────────
make_executable() {
    print_step "Permissions"
    chmod +x "$CODEY_V2_DIR/codey2"
    chmod +x "$CODEY_V2_DIR/codeyd2"
    chmod +x "$CODEY_V2_DIR/install.sh"
    [ -f "$CODEY_V2_DIR/gui/start.sh" ] && chmod +x "$CODEY_V2_DIR/gui/start.sh"
    print_success "Executable bits set"
}

setup_daemon_dir() {
    mkdir -p "$HOME/.codey-v2"
    print_success "Daemon directory: $HOME/.codey-v2"
}

setup_path() {
    print_step "PATH"

    if [ -n "$ZSH_VERSION" ]; then
        SHELL_CONFIG="$HOME/.zshrc"
    else
        SHELL_CONFIG="$HOME/.bashrc"
    fi

    if grep -q "codey-v2" "$SHELL_CONFIG" 2>/dev/null; then
        print_status "PATH already configured in $SHELL_CONFIG"
    else
        {
            echo ""
            echo "# Codey-v2"
            echo "export PATH=\"$CODEY_V2_DIR:\$PATH\""
        } >> "$SHELL_CONFIG"
        print_success "Added $CODEY_V2_DIR to PATH in $SHELL_CONFIG"
    fi

    export PATH="$CODEY_V2_DIR:$PATH"
    # shellcheck source=/dev/null
    source "$SHELL_CONFIG" 2>/dev/null || true
}

# ── 7. Verify ─────────────────────────────────────────────────────────────────
verify_installation() {
    print_step "Verification"

    command -v python3 &>/dev/null \
        && print_success "python3: $(python3 --version)" \
        || print_error "python3 not found"

    [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ] \
        && print_success "llama-server: built" \
        || print_warning "llama-server: not found"

    file_ok "$PRIMARY_MODEL_DIR/$PRIMARY_MODEL_FILE" 4000000000 \
        && print_success "7B agent model: ready" \
        || print_warning "7B agent model: missing"

    file_ok "$SECONDARY_MODEL_DIR/$SECONDARY_MODEL_FILE" 200000000 \
        && print_success "0.5B planner model: ready" \
        || print_warning "0.5B planner model: missing"

    file_ok "$EMBED_MODEL_DIR/$EMBED_MODEL_FILE" 50000000 \
        && print_success "Embedding model: ready" \
        || print_warning "Embedding model: missing"

    command -v codey2  &>/dev/null && print_success "codey2:  in PATH"  || print_warning "codey2:  not in PATH yet (restart terminal)"
    command -v codeyd2 &>/dev/null && print_success "codeyd2: in PATH"  || print_warning "codeyd2: not in PATH yet (restart terminal)"
}

# ── 8. Completion message ─────────────────────────────────────────────────────
print_completion() {
    echo
    echo -e "${GREEN}${BOLD}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║            CODEY-V2 — Installation Complete                  ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo -e "${CYAN}${BOLD}QUICK START${NC}"
    echo
    echo -e "  Reload shell:   ${BLUE}source $SHELL_CONFIG${NC}"
    echo -e "  Start daemon:   ${BLUE}codeyd2 start${NC}"
    echo -e "  Run Codey:      ${BLUE}codey2${NC}"
    echo -e "    → opens the interactive TUI ${BOLD}and${NC} the browser GUI automatically"
    echo -e "    → browser:    ${BLUE}http://localhost:8888${NC}"
    echo
    echo -e "  Stop daemon:    ${BLUE}codeyd2 stop${NC}"
    echo -e "  Daemon status:  ${BLUE}codeyd2 status${NC}"
    echo

    echo -e "${CYAN}${BOLD}BACKEND SWITCHING  (local models are the default — no key needed)${NC}"
    echo
    echo -e "  Two independent backends:"
    echo -e "    ${BOLD}CODEY_BACKEND${NC}   — 7B coding agent  (ports 8080)"
    echo -e "    ${BOLD}CODEY_BACKEND_P${NC} — 0.5B planner     (port 8081, defaults to CODEY_BACKEND)"
    echo -e "  Each can be: ${BOLD}local${NC} | ${BOLD}openrouter${NC} | ${BOLD}unlimitedclaude${NC}"
    echo
    echo -e "  ── ${BOLD}OpenRouter${NC} ─────────────────────────────────────────────────"
    echo -e "    Key:    ${BLUE}https://openrouter.ai/keys${NC}"
    echo -e "    ${BLUE}export OPENROUTER_API_KEY=\"sk-or-...\"${NC}"
    echo
    echo -e "    # Route both agent and planner to OpenRouter:"
    echo -e "    ${BLUE}export CODEY_BACKEND=\"openrouter\"${NC}"
    echo
    echo -e "    # Override the 7B coding model (default: qwen/qwen-2.5-coder-7b-instruct):"
    echo -e "    ${BLUE}export OPENROUTER_MODEL=\"anthropic/claude-sonnet-4-5\"${NC}"
    echo
    echo -e "    # Override the 0.5B planner model independently (default: same as OPENROUTER_MODEL):"
    echo -e "    ${BLUE}export OPENROUTER_PLANNER_MODEL=\"meta-llama/llama-3.2-1b-instruct:free\"${NC}"
    echo
    echo -e "  ── ${BOLD}UnlimitedClaude${NC} ──────────────────────────────────────────────"
    echo -e "    ${BLUE}export UNLIMITEDCLAUDE_API_KEY=\"your-key\"${NC}"
    echo
    echo -e "    # Route both agent and planner:"
    echo -e "    ${BLUE}export CODEY_BACKEND=\"unlimitedclaude\"${NC}"
    echo
    echo -e "    # Override the 7B coding model (default: qwen3-coder-next):"
    echo -e "    ${BLUE}export UNLIMITEDCLAUDE_MODEL=\"claude-sonnet-4-5\"${NC}"
    echo
    echo -e "    # Override the 0.5B planner model independently (default: claude-haiku-4.5):"
    echo -e "    ${BLUE}export UNLIMITEDCLAUDE_PLANNER_MODEL=\"claude-haiku-4-5\"${NC}"
    echo
    echo -e "  ── ${BOLD}Mix backends${NC} (most flexible) ───────────────────────────────"
    echo -e "    # e.g. 7B runs locally, planner goes to OpenRouter:"
    echo -e "    ${BLUE}export CODEY_BACKEND=\"local\"${NC}"
    echo -e "    ${BLUE}export CODEY_BACKEND_P=\"openrouter\"${NC}"
    echo -e "    ${BLUE}export OPENROUTER_PLANNER_MODEL=\"meta-llama/llama-3.2-1b-instruct:free\"${NC}"
    echo
    echo -e "  ── ${BOLD}Back to local${NC} ────────────────────────────────────────────────"
    echo -e "    ${BLUE}unset CODEY_BACKEND CODEY_BACKEND_P${NC}   # local is always the default"
    echo
    echo -e "  ${YELLOW}Permanent: add exports to ${BLUE}~/.bashrc${YELLOW} then run ${BLUE}source ~/.bashrc${NC}"
    echo

    echo -e "${CYAN}${BOLD}MODEL LOCATIONS${NC}"
    echo -e "  7B  agent:   ${BLUE}$PRIMARY_MODEL_DIR/$PRIMARY_MODEL_FILE${NC}"
    echo -e "  0.5B planner: ${BLUE}$SECONDARY_MODEL_DIR/$SECONDARY_MODEL_FILE${NC}"
    echo -e "  Embed:       ${BLUE}$EMBED_MODEL_DIR/$EMBED_MODEL_FILE${NC}"
    echo
    echo -e "  If any model is missing, resume with:"
    echo -e "  ${BLUE}wget -c '$PRIMARY_MODEL_URL' -O '$PRIMARY_MODEL_DIR/$PRIMARY_MODEL_FILE'${NC}"
    echo -e "  ${BLUE}wget -c '$SECONDARY_MODEL_FALLBACK_URL' -O '$SECONDARY_MODEL_DIR/$SECONDARY_MODEL_FILE'${NC}"
    echo -e "  ${BLUE}wget -c '$EMBED_MODEL_URL' -O '$EMBED_MODEL_DIR/$EMBED_MODEL_FILE'${NC}"
    echo
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    SKIP_CONFIRM=false
    for arg in "$@"; do
        [ "$arg" = "--yes" ] || [ "$arg" = "-y" ] && SKIP_CONFIRM=true && break
    done

    echo -e "${BLUE}${BOLD}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║           Codey-v2 Installation Script                       ║"
    echo "║   Persistent local AI coding agent for Termux / Android      ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo "  Download: ~5.5 GB (models) + ~500 MB (llama.cpp build)"
    echo "  Build time: 5–15 min on mobile"
    echo

    if [ "$SKIP_CONFIRM" = false ]; then
        read -p "  Continue? [Y/n] " -n 1 -r; echo
        [[ $REPLY =~ ^[Nn]$ ]] && { echo "Cancelled."; exit 0; }
    else
        echo "  Non-interactive mode."
    fi

    check_termux
    install_system_deps
    install_python_deps

    if ! install_llama_cpp; then
        print_error "llama.cpp build failed — fix the error above and re-run"
        print_warning "Manual build:"
        print_warning "  git clone --depth 1 https://github.com/ggerganov/llama.cpp ~/llama.cpp"
        print_warning "  cd ~/llama.cpp && cmake -B build -DLLAMA_CURL=ON && cmake --build build -j\$(nproc)"
        exit 1
    fi

    download_models || print_warning "Some models failed — re-run to resume (wget -c is used)"

    make_executable
    setup_daemon_dir
    setup_path
    verify_installation
    print_completion
}

main "$@"
