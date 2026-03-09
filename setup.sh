#!/usr/bin/env bash
#
# Quick setup for Codey-v2 - adds to PATH
#
# Run this if you've already installed dependencies
# and just need to make codey2 available system-wide.
#

CODEY_V2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Determine shell config
if [ -n "$BASH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
elif [ -n "$ZSH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
else
    SHELL_CONFIG="$HOME/.bashrc"
fi

# Make scripts executable
chmod +x "$CODEY_V2_DIR/codey2"
chmod +x "$CODEY_V2_DIR/codeyd2"

# Add to PATH if not already there
if ! grep -q "codey-v2" "$SHELL_CONFIG" 2>/dev/null; then
    echo "" >> "$SHELL_CONFIG"
    echo "# Codey-v2" >> "$SHELL_CONFIG"
    echo "export PATH=\"$CODEY_V2_DIR:\$PATH\"" >> "$SHELL_CONFIG"
    echo "Added codey2 to PATH in $SHELL_CONFIG"
else
    echo "codey2 already in PATH"
fi

# Source the config
source "$SHELL_CONFIG"

# Create daemon directory
mkdir -p "$HOME/.codey-v2"

echo ""
echo "Setup complete!"
echo ""
echo "Now you can use Codey-v2:"
echo "  codeyd2 start          # Start the daemon"
echo "  codey2 \"hello\"         # Send a task"
echo "  codey2 status          # Check status"
echo ""
