#!/bin/bash
set -e

echo "Installing Claude CLI..."

# Method 1: Try official installer
if curl -fsSL https://claude.ai/download/cli/install.sh | sh 2>/dev/null; then
    echo "✓ Installed via official installer"
    exit 0
fi

# Method 2: Direct download from known stable location
echo "Trying direct download..."
INSTALL_DIR="/usr/local/bin"
mkdir -p "$INSTALL_DIR"

ARCH=$(uname -m)
case "$ARCH" in
    x86_64)
        BINARY_URL="https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-v2.1.5/claude-cli-linux-x64"
        ;;
    aarch64|arm64)
        BINARY_URL="https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-v2.1.5/claude-cli-linux-arm64"
        ;;
    *)
        echo "ERROR: Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "Downloading from: $BINARY_URL"
if curl -fsSL "$BINARY_URL" -o "$INSTALL_DIR/claude"; then
    chmod +x "$INSTALL_DIR/claude"
    echo "✓ Claude CLI installed to $INSTALL_DIR/claude"
    exit 0
fi

echo "ERROR: All installation methods failed"
exit 1
