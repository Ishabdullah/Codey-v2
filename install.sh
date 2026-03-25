#!/usr/bin/env bash
#
# Codey-v2 Installation Script
#
# This script installs everything needed for Codey-v2:
# - Python dependencies
# - llama.cpp binary (with CURL support for HTTP API)
# - Primary model (Qwen2.5-Coder-7B-Instruct Q4_K_M)
# - Secondary model (Qwen2.5-1.5B-Instruct Q8_0)
# - Embedding model (nomic-embed-text-v1.5 Q4_K_M)
# - PATH configuration
#
# Usage:
#   ./install.sh           # Interactive installation
#   ./install.sh --yes     # Non-interactive installation
#
# After installation:
#   - codey2 "your prompt"    # Run a task
#   - codey2 --chat           # Interactive chat mode
#   - codeyd2 start           # Start the daemon
#   - codeyd2 stop            # Stop the daemon
#   - codey2 status           # Check daemon status
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CODEY_V2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_CPP_DIR="$HOME/llama.cpp"
MODELS_DIR="$HOME/models"
PRIMARY_MODEL_DIR="$MODELS_DIR/qwen2.5-coder-7b"
SECONDARY_MODEL_DIR="$MODELS_DIR/qwen2.5-1.5b"
EMBED_MODEL_DIR="$MODELS_DIR/nomic-embed"
PRIMARY_MODEL_FILE="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
SECONDARY_MODEL_FILE="qwen2.5-1.5b-instruct-q8_0.gguf"
EMBED_MODEL_FILE="nomic-embed-text-v1.5.Q4_K_M.gguf"

# URLs for model downloads (HuggingFace)
PRIMARY_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
SECONDARY_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q8_0.gguf"
EMBED_MODEL_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           Codey-v2 Installation Script                    ║"
echo "║   Persistent AI Agent for Termux                          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo

# Function to print status
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running in Termux
check_termux() {
    print_status "Checking environment..."
    if [ -d "/data/data/com.termux" ]; then
        print_success "Running in Termux"
    else
        print_warning "Not running in Termux. Some commands may need adjustment."
    fi
}

# Install system dependencies
install_dependencies() {
    print_status "Installing system dependencies..."
    
    if [ -d "/data/data/com.termux" ]; then
        # Termux
        pkg update -y
        pkg install -y python cmake ninja clang wget curl git
        print_success "System dependencies installed"
    else
        # Generic Linux
        if command -v apt &> /dev/null; then
            sudo apt update
            sudo apt install -y python3 python3-pip cmake ninja-build clang wget curl git
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y python3 python3-pip cmake ninja clang wget curl git
        elif command -v pacman &> /dev/null; then
            sudo pacman -S --noconfirm python python-pip cmake ninja clang wget curl git
        else
            print_warning "Package manager not detected. Please install dependencies manually."
            print_warning "Required: python3, pip, cmake, ninja, clang, wget, curl, git"
            return 1
        fi
        print_success "System dependencies installed"
    fi
}

# Install Python dependencies
install_python_deps() {
    print_status "Installing Python dependencies..."
    
    if [ -d "/data/data/com.termux" ]; then
        # Termux - pip is already available with python package
        print_status "Termux detected, using system pip..."
    else
        # Generic Linux - upgrade pip
        pip3 install --upgrade pip
    fi
    
    # Install requirements
    cd "$CODEY_V2_DIR"
    pip3 install -r requirements.txt
    
    print_success "Python dependencies installed"
}

# Install llama.cpp
install_llama_cpp() {
    print_status "Installing llama.cpp..."

    if [ -d "$LLAMA_CPP_DIR" ]; then
        print_status "llama.cpp already exists, updating..."
        cd "$LLAMA_CPP_DIR"
        git pull || {
            print_warning "Failed to update llama.cpp, continuing with existing version"
        }
    else
        print_status "Cloning llama.cpp (shallow clone for faster download)..."
        # Use shallow clone for faster download
        git clone --depth 1 https://github.com/ggerganov/llama.cpp "$LLAMA_CPP_DIR" || {
            print_error "Failed to clone llama.cpp"
            print_warning "You can manually clone: git clone --depth 1 https://github.com/ggerganov/llama.cpp $LLAMA_CPP_DIR"
            return 1
        }
    fi

    # Check if already built
    if [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        print_success "llama.cpp already built"
        return 0
    fi

    # Build llama.cpp
    cd "$LLAMA_CPP_DIR"
    print_status "Building llama.cpp (this may take 5-15 minutes on mobile devices)..."
    
    # Configure with cmake
    cmake -B build -DLLAMA_CURL=ON -DBUILD_SHARED_LIBS=OFF || {
        print_error "cmake configuration failed"
        return 1
    }
    
    # Build with progress display
    cmake --build build --config Release -j$(nproc) || {
        print_error "llama.cpp build failed"
        print_warning "This can happen on low-memory devices. Try closing other apps and running again."
        return 1
    }

    # Verify build
    if [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        print_success "llama.cpp installed successfully"
    else
        print_error "llama.cpp build failed - llama-server not found"
        return 1
    fi
}

# Download a file with progress and resume support
download_file() {
    local url="$1"
    local output="$2"
    local description="$3"

    print_status "Downloading $description..."

    # Use wget with resume support (-c) and progress bar
    if command -v wget &> /dev/null; then
        wget --show-progress -c -O "$output" "$url" 2>&1 || {
            print_error "Download failed for $description"
            return 1
        }
    elif command -v curl &> /dev/null; then
        # curl with resume support (-C -)
        curl -L -C - -o "$output" "$url" || {
            print_error "Download failed for $description"
            return 1
        }
    else
        print_error "Neither wget nor curl found"
        return 1
    fi
}

# Check available disk space
check_disk_space() {
    local required_mb="$1"
    local path="$2"
    
    # Get available space in KB
    local available_kb=$(df -k "$path" 2>/dev/null | tail -1 | awk '{print $4}')
    local available_mb=$((available_kb / 1024))
    
    if [ "$available_mb" -lt "$required_mb" ]; then
        print_error "Insufficient disk space. Need ${required_mb}MB, have ${available_mb}MB"
        return 1
    fi
    
    print_success "Disk space check passed (${available_mb}MB available)"
    return 0
}

# Download models
download_models() {
    print_status "Setting up model directories..."
    mkdir -p "$PRIMARY_MODEL_DIR"
    mkdir -p "$SECONDARY_MODEL_DIR"
    mkdir -p "$EMBED_MODEL_DIR"

    # Check disk space (need ~8GB for all models + llama.cpp)
    print_status "Checking disk space..."
    if ! check_disk_space 8000 "$HOME"; then
        print_warning "Continuing despite low disk space warning"
    fi

    # Track if any models need downloading
    MODELS_NEED_DOWNLOAD=false

    # Check primary model (7B)
    PRIMARY_MODEL_PATH="$PRIMARY_MODEL_DIR/$PRIMARY_MODEL_FILE"
    if [ -f "$PRIMARY_MODEL_PATH" ]; then
        # Check if file is complete (not partial download)
        FILE_SIZE=$(stat -c%s "$PRIMARY_MODEL_PATH" 2>/dev/null || stat -f%z "$PRIMARY_MODEL_PATH" 2>/dev/null || echo 0)
        MIN_SIZE=4000000000  # 4GB minimum for valid model

        if [ "$FILE_SIZE" -gt "$MIN_SIZE" ]; then
            print_success "Primary model (7B) already exists ($(numfmt --to=iec-i --suffix=B $FILE_SIZE 2>/dev/null || echo "${FILE_SIZE}B")), skipping..."
        else
            print_warning "Primary model (7B) exists but appears incomplete, re-downloading..."
            rm -f "$PRIMARY_MODEL_PATH"
            MODELS_NEED_DOWNLOAD=true
        fi
    else
        print_status "Primary model (7B) not found"
        MODELS_NEED_DOWNLOAD=true
    fi

    # Check secondary model (1.5B)
    SECONDARY_MODEL_PATH="$SECONDARY_MODEL_DIR/$SECONDARY_MODEL_FILE"
    if [ -f "$SECONDARY_MODEL_PATH" ]; then
        # Check if file is complete (not partial download)
        FILE_SIZE=$(stat -c%s "$SECONDARY_MODEL_PATH" 2>/dev/null || stat -f%z "$SECONDARY_MODEL_PATH" 2>/dev/null || echo 0)
        MIN_SIZE=1000000000  # 1GB minimum for valid model

        if [ "$FILE_SIZE" -gt "$MIN_SIZE" ]; then
            print_success "Secondary model (1.5B) already exists ($(numfmt --to=iec-i --suffix=B $FILE_SIZE 2>/dev/null || echo "${FILE_SIZE}B")), skipping..."
        else
            print_warning "Secondary model (1.5B) exists but appears incomplete, re-downloading..."
            rm -f "$SECONDARY_MODEL_PATH"
            MODELS_NEED_DOWNLOAD=true
        fi
    else
        print_status "Secondary model (1.5B) not found"
        MODELS_NEED_DOWNLOAD=true
    fi

    # Check embedding model
    EMBED_MODEL_PATH="$EMBED_MODEL_DIR/$EMBED_MODEL_FILE"
    if [ -f "$EMBED_MODEL_PATH" ]; then
        # Check if file is complete (not partial download)
        FILE_SIZE=$(stat -c%s "$EMBED_MODEL_PATH" 2>/dev/null || stat -f%z "$EMBED_MODEL_PATH" 2>/dev/null || echo 0)
        MIN_SIZE=50000000  # 50MB minimum for valid embedding model

        if [ "$FILE_SIZE" -gt "$MIN_SIZE" ]; then
            print_success "Embedding model already exists ($(numfmt --to=iec-i --suffix=B $FILE_SIZE 2>/dev/null || echo "${FILE_SIZE}B")), skipping..."
        else
            print_warning "Embedding model exists but appears incomplete, re-downloading..."
            rm -f "$EMBED_MODEL_PATH"
            MODELS_NEED_DOWNLOAD=true
        fi
    else
        print_status "Embedding model not found"
        MODELS_NEED_DOWNLOAD=true
    fi

    # If no models need downloading, skip entirely
    if [ "$MODELS_NEED_DOWNLOAD" = false ]; then
        print_success "All models already downloaded, skipping model download step"
        return 0
    fi

    echo
    print_warning "Models will be downloaded now (~7GB total)"
    print_warning "This may take 10-30 minutes depending on your connection"
    print_warning "Press Ctrl+C to skip and download models manually later"
    echo

    # Download primary model (7B)
    if [ ! -f "$PRIMARY_MODEL_PATH" ]; then
        print_status "Downloading Primary model (7B) - ~4.7GB..."
        if download_file "$PRIMARY_MODEL_URL" "$PRIMARY_MODEL_PATH" "Primary model (7B)"; then
            # Verify download
            FILE_SIZE=$(stat -c%s "$PRIMARY_MODEL_PATH" 2>/dev/null || stat -f%z "$PRIMARY_MODEL_PATH" 2>/dev/null || echo 0)
            if [ "$FILE_SIZE" -gt 4000000000 ]; then
                print_success "Primary model (7B) downloaded successfully"
            else
                print_error "Primary model download appears incomplete"
                print_warning "You can resume download later: wget -c -P $PRIMARY_MODEL_DIR $PRIMARY_MODEL_URL"
            fi
        else
            print_error "Failed to download primary model"
            print_warning "Manual download: wget -c -P $PRIMARY_MODEL_DIR $PRIMARY_MODEL_URL"
        fi
    fi

    # Download secondary model (1.5B)
    if [ ! -f "$SECONDARY_MODEL_PATH" ]; then
        print_status "Downloading Secondary model (1.5B) - ~2GB..."
        if download_file "$SECONDARY_MODEL_URL" "$SECONDARY_MODEL_PATH" "Secondary model (1.5B)"; then
            # Verify download
            FILE_SIZE=$(stat -c%s "$SECONDARY_MODEL_PATH" 2>/dev/null || stat -f%z "$SECONDARY_MODEL_PATH" 2>/dev/null || echo 0)
            if [ "$FILE_SIZE" -gt 1000000000 ]; then
                print_success "Secondary model (1.5B) downloaded successfully"
            else
                print_error "Secondary model download appears incomplete"
                print_warning "You can resume download later: wget -c -P $SECONDARY_MODEL_DIR $SECONDARY_MODEL_URL"
            fi
        else
            print_error "Failed to download secondary model"
            print_warning "Manual download: wget -c -P $SECONDARY_MODEL_DIR $SECONDARY_MODEL_URL"
        fi
    fi

    # Download embedding model
    if [ ! -f "$EMBED_MODEL_PATH" ]; then
        print_status "Downloading Embedding model - ~81MB..."
        if download_file "$EMBED_MODEL_URL" "$EMBED_MODEL_PATH" "Embedding model"; then
            # Verify download
            FILE_SIZE=$(stat -c%s "$EMBED_MODEL_PATH" 2>/dev/null || stat -f%z "$EMBED_MODEL_PATH" 2>/dev/null || echo 0)
            if [ "$FILE_SIZE" -gt 50000000 ]; then
                print_success "Embedding model downloaded successfully"
            else
                print_error "Embedding model download appears incomplete"
                print_warning "You can resume download later: wget -c -P $EMBED_MODEL_DIR $EMBED_MODEL_URL"
            fi
        else
            print_error "Failed to download embedding model"
            print_warning "Manual download: wget -c -P $EMBED_MODEL_DIR $EMBED_MODEL_URL"
        fi
    fi
}

# Configure PATH
setup_path() {
    print_status "Configuring PATH..."

    # Determine shell config file
    if [ -n "$BASH_VERSION" ]; then
        SHELL_CONFIG="$HOME/.bashrc"
    elif [ -n "$ZSH_VERSION" ]; then
        SHELL_CONFIG="$HOME/.zshrc"
    else
        SHELL_CONFIG="$HOME/.bashrc"
    fi

    # Check if already in PATH
    if grep -q "codey-v2" "$SHELL_CONFIG" 2>/dev/null; then
        print_status "Codey-v2 already in PATH"
    else
        # Add to PATH
        echo "" >> "$SHELL_CONFIG"
        echo "# Codey-v2" >> "$SHELL_CONFIG"
        echo "export PATH=\"$CODEY_V2_DIR:\$PATH\"" >> "$SHELL_CONFIG"
        print_success "Added Codey-v2 to PATH in $SHELL_CONFIG"
    fi

    # Source the config file to make it available immediately
    if [ -f "$SHELL_CONFIG" ]; then
        source "$SHELL_CONFIG"
    fi

    # Also export PATH for current session
    export PATH="$CODEY_V2_DIR:$PATH"
}

# Make scripts executable
make_executable() {
    print_status "Making scripts executable..."
    chmod +x "$CODEY_V2_DIR/codey2"
    chmod +x "$CODEY_V2_DIR/codeyd2"
    print_success "Scripts are now executable"
}

# Create daemon directory
setup_daemon_dir() {
    print_status "Creating daemon directory..."
    mkdir -p "$HOME/.codey-v2"
    print_success "Daemon directory created"
}

# Verify installation
verify_installation() {
    print_status "Verifying installation..."

    # Check Python
    if command -v python3 &> /dev/null; then
        print_success "Python3: $(python3 --version)"
    else
        print_error "Python3 not found"
        return 1
    fi

    # Check llama.cpp
    if [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        print_success "llama.cpp: installed"
    else
        print_warning "llama.cpp: not found"
    fi

    # Check models
    if [ -f "$PRIMARY_MODEL_PATH" ]; then
        print_success "Primary model (7B): installed"
    else
        print_warning "Primary model (7B): not downloaded"
    fi

    if [ -f "$SECONDARY_MODEL_PATH" ]; then
        print_success "Secondary model (1.5B): installed"
    else
        print_warning "Secondary model (1.5B): not downloaded"
    fi

    if [ -f "$EMBED_MODEL_PATH" ]; then
        print_success "Embedding model: installed"
    else
        print_warning "Embedding model: not downloaded"
    fi

    # Check codey2 command
    if command -v codey2 &> /dev/null; then
        print_success "codey2 command: available"
    else
        print_warning "codey2 command: not in PATH (restart terminal or run: source $SHELL_CONFIG)"
    fi

    # Check codeyd2 command
    if command -v codeyd2 &> /dev/null; then
        print_success "codeyd2 command: available"
    else
        print_warning "codeyd2 command: not in PATH (restart terminal or run: source $SHELL_CONFIG)"
    fi
}

# Print completion message
print_completion() {
    echo
    echo -e "${GREEN}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║              Installation Complete!                       ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo
    echo "To start using Codey-v2:"
    echo
    echo "  1. Reload your shell configuration:"
    echo "     ${BLUE}source $SHELL_CONFIG${NC}"
    echo
    echo "  2. Start the daemon:"
    echo "     ${BLUE}codeyd2 start${NC}"
    echo
    echo "  3. Send your first task:"
    echo "     ${BLUE}codey2 \"Hello, create a hello world Python script\"${NC}"
    echo
    echo "  4. Or run interactively:"
    echo "     ${BLUE}codey2 --chat${NC}"
    echo
    echo "  5. Check status anytime:"
    echo "     ${BLUE}codey2 status${NC}"
    echo
    echo "Useful commands:"
    echo "  ${BLUE}codeyd2 start|stop|status|restart|reload|config${NC}"
    echo "  ${BLUE}codey2 \"your prompt\"${NC}"
    echo "  ${BLUE}codey2 --chat${NC} (interactive chat mode)"
    echo "  ${BLUE}codey2 task list${NC}"
    echo "  ${BLUE}codey2 status${NC}"
    echo
    echo "Documentation: ${BLUE}$CODEY_V2_DIR/README.md${NC}"
    echo
    echo -e "${YELLOW}Note: If models weren't downloaded, you can download them manually:${NC}"
    echo "  ${BLUE}wget -P $PRIMARY_MODEL_DIR $PRIMARY_MODEL_URL${NC}"
    echo "  ${BLUE}wget -P $SECONDARY_MODEL_DIR $SECONDARY_MODEL_URL${NC}"
    echo "  ${BLUE}wget -P $EMBED_MODEL_DIR $EMBED_MODEL_URL${NC}"
    echo
}

# Main installation flow
main() {
    # Check for non-interactive flag
    SKIP_CONFIRM=false
    for arg in "$@"; do
        if [ "$arg" = "--yes" ] || [ "$arg" = "-y" ]; then
            SKIP_CONFIRM=true
            break
        fi
    done

    echo "This script will install Codey-v2 and all dependencies."
    echo "Estimated download size: ~7GB (models) + ~500MB (llama.cpp)"
    echo "Build time: 5-15 minutes on mobile devices"
    echo

    if [ "$SKIP_CONFIRM" = false ]; then
        read -p "Continue? [Y/n] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Installation cancelled."
            exit 0
        fi
    else
        echo "Running in non-interactive mode..."
    fi
    echo

    check_termux
    install_dependencies
    install_python_deps
    
    # Install llama.cpp (required for inference)
    if ! install_llama_cpp; then
        print_error "llama.cpp installation failed"
        print_warning "You can manually build llama.cpp later:"
        print_warning "  git clone --depth 1 https://github.com/ggerganov/llama.cpp ~/llama.cpp"
        print_warning "  cd ~/llama.cpp && cmake -B build -DLLAMA_CURL=ON && cmake --build build --config Release"
        exit 1
    fi
    
    # Download models (optional - can be done manually later)
    if ! download_models; then
        print_warning "Model download failed or was interrupted"
        print_warning "You can download models manually later:"
        print_warning "  wget -c -P $PRIMARY_MODEL_DIR $PRIMARY_MODEL_URL"
        print_warning "  wget -c -P $SECONDARY_MODEL_DIR $SECONDARY_MODEL_URL"
        print_warning "  wget -c -P $EMBED_MODEL_DIR $EMBED_MODEL_URL"
    fi
    
    make_executable
    setup_daemon_dir
    setup_path
    verify_installation
    print_completion
}

# Run main function
main "$@"
