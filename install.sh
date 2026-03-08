#!/usr/bin/env bash
#
# Codey v2 Installation Script
#
# This script installs everything needed for Codey v2:
# - Python dependencies
# - llama.cpp binary
# - Both models (7B primary + 1.5B secondary)
# - PATH configuration
#
# After installation, just type 'codey2' anywhere to start.
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
PRIMARY_MODEL_FILE="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
SECONDARY_MODEL_FILE="Qwen2.5-1.5B-Instruct-Q8_0.gguf"

# URLs for model downloads (HuggingFace)
PRIMARY_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
SECONDARY_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q8_0.gguf"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           Codey v2 Installation Script                    ║"
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
        git pull
    else
        print_status "Cloning llama.cpp..."
        git clone https://github.com/ggerganov/llama.cpp "$LLAMA_CPP_DIR"
    fi
    
    # Build llama.cpp
    cd "$LLAMA_CPP_DIR"
    print_status "Building llama.cpp (this may take a few minutes)..."
    cmake -B build -DLLAMA_CURL=OFF
    cmake --build build --config Release -j$(nproc)
    
    # Verify build
    if [ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        print_success "llama.cpp installed successfully"
    else
        print_error "llama.cpp build failed"
        return 1
    fi
}

# Download a file with progress
download_file() {
    local url="$1"
    local output="$2"
    local description="$3"
    
    print_status "Downloading $description..."
    
    if command -v wget &> /dev/null; then
        wget --show-progress -c -O "$output" "$url"
    elif command -v curl &> /dev/null; then
        curl -L -# -o "$output" "$url"
    else
        print_error "Neither wget nor curl found"
        return 1
    fi
}

# Download models
download_models() {
    print_status "Setting up model directories..."
    mkdir -p "$PRIMARY_MODEL_DIR"
    mkdir -p "$SECONDARY_MODEL_DIR"
    
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
        print_status "Codey v2 already in PATH"
    else
        # Add to PATH
        echo "" >> "$SHELL_CONFIG"
        echo "# Codey v2" >> "$SHELL_CONFIG"
        echo "export PATH=\"$CODEY_V2_DIR:\$PATH\"" >> "$SHELL_CONFIG"
        print_success "Added Codey v2 to PATH in $SHELL_CONFIG"
    fi
    
    # Source the config file
    if [ -f "$SHELL_CONFIG" ]; then
        source "$SHELL_CONFIG"
    fi
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
    
    # Check codey2 command
    if command -v codey2 &> /dev/null; then
        print_success "codey2 command: available"
    else
        print_warning "codey2 command: not in PATH (restart terminal or run: source $SHELL_CONFIG)"
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
    echo "To start using Codey v2:"
    echo
    echo "  1. Restart your terminal OR run:"
    echo "     ${BLUE}source $SHELL_CONFIG${NC}"
    echo
    echo "  2. Start the daemon:"
    echo "     ${BLUE}codeyd2 start${NC}"
    echo
    echo "  3. Send your first task:"
    echo "     ${BLUE}codey2 \"Hello, create a hello world Python script\"${NC}"
    echo
    echo "  4. Check status anytime:"
    echo "     ${BLUE}codey2 status${NC}"
    echo
    echo "Useful commands:"
    echo "  ${BLUE}codeyd2 start|stop|status|restart|reload|config${NC}"
    echo "  ${BLUE}codey2 \"your prompt\"${NC}"
    echo "  ${BLUE}codey2 task list${NC}"
    echo "  ${BLUE}codey2 status${NC}"
    echo
    echo "Documentation: ${BLUE}$CODEY_V2_DIR/README.md${NC}"
    echo
    echo -e "${YELLOW}Note: If models weren't downloaded, you can download them manually:${NC}"
    echo "  ${BLUE}wget -P $PRIMARY_MODEL_DIR $PRIMARY_MODEL_URL${NC}"
    echo "  ${BLUE}wget -P $SECONDARY_MODEL_DIR $SECONDARY_MODEL_URL${NC}"
    echo
}

# Main installation flow
main() {
    echo "This script will install Codey v2 and all dependencies."
    echo "Estimated download size: ~7GB (models) + ~500MB (llama.cpp)"
    echo
    read -p "Continue? [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
    echo
    
    check_termux
    install_dependencies
    install_python_deps
    install_llama_cpp
    download_models
    make_executable
    setup_daemon_dir
    setup_path
    verify_installation
    print_completion
}

# Run main function
main "$@"
