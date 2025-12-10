#!/bin/bash

# =============================================================================
# 🍞 Hansel Installer
# =============================================================================
# Usage:
#   source <(curl -fsSL https://raw.githubusercontent.com/johanfleming/hansel/main/install.sh)
# =============================================================================

# Don't use set -e - it breaks the user's shell when sourced

INSTALL_DIR="${HOME}/.local/bin"
REPO_URL="https://raw.githubusercontent.com/johanfleming/hansel/main"

# Check if running from local clone or remote
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""

echo "🍞 Hansel Installation"
echo "════════════════════════════════════════"

# Check dependencies
echo "Checking dependencies..."

if ! command -v curl &> /dev/null; then
    echo "❌ curl is required but not installed"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo "⚠️  jq is recommended for JSON parsing"
    echo "   Install with: sudo apt install jq (Ubuntu) or brew install jq (macOS)"
fi

echo "✅ Dependencies OK"
echo ""

# Create directory
mkdir -p "${INSTALL_DIR}"

# Install hansel (from local or remote)
if [[ -n "${SCRIPT_DIR}" && -f "${SCRIPT_DIR}/hansel" ]]; then
    echo "Installing from local source..."
    cp "${SCRIPT_DIR}/hansel" "${INSTALL_DIR}/hansel"
else
    echo "Downloading from GitHub..."
    curl -fsSL "${REPO_URL}/hansel" -o "${INSTALL_DIR}/hansel"
fi
chmod +x "${INSTALL_DIR}/hansel"

echo "✅ Hansel installed: ${INSTALL_DIR}/hansel"

# PATH check and auto-add
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo ""
    echo "⚠️  ${INSTALL_DIR} is not in PATH."

    # Detect shell config file
    SHELL_CONFIG=""
    if [[ -n "$ZSH_VERSION" ]] || [[ "$SHELL" == */zsh ]]; then
        SHELL_CONFIG="${HOME}/.zshrc"
    elif [[ -n "$BASH_VERSION" ]] || [[ "$SHELL" == */bash ]]; then
        SHELL_CONFIG="${HOME}/.bashrc"
    fi

    if [[ -n "$SHELL_CONFIG" ]]; then
        # Check if already in config file
        if ! grep -q '.local/bin' "$SHELL_CONFIG" 2>/dev/null; then
            echo "   Adding to ${SHELL_CONFIG}..."
            echo '' >> "$SHELL_CONFIG"
            echo '# Hansel - added by installer' >> "$SHELL_CONFIG"
            echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "$SHELL_CONFIG"
            echo "✅ PATH added to ${SHELL_CONFIG}"
        else
            echo "   PATH already in ${SHELL_CONFIG}"
        fi
        echo ""
        # Update PATH for current session (works when sourced)
        export PATH="${HOME}/.local/bin:${PATH}"
        echo "✅ PATH updated for current session"
    else
        echo ""
        echo "Add this line to your shell config:"
        echo ""
        echo "    export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    fi
else
    echo "✅ PATH already configured"
fi

echo ""
echo "🎉 Installation complete!"
echo ""
echo "Next steps:"
echo "    hansel config             # Set OpenAI API key"
echo "    hansel watch 'claude'     # Watch Claude CLI"
echo "    hansel help               # Show help"
echo ""
echo "Quick start with auto-respond:"
echo "    AUTO_RESPOND=true hansel watch 'claude'"
