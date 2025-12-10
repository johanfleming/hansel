#!/bin/bash

# =============================================================================
# 🍞 Hansel Installer
# =============================================================================

set -e

INSTALL_DIR="${HOME}/.local/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# Copy hansel
cp "${SCRIPT_DIR}/hansel" "${INSTALL_DIR}/hansel"
chmod +x "${INSTALL_DIR}/hansel"

echo "✅ Hansel installed: ${INSTALL_DIR}/hansel"

# PATH check
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo ""
    echo "⚠️  ${INSTALL_DIR} is not in PATH."
    echo ""
    echo "Add this line to your ~/.bashrc or ~/.zshrc:"
    echo ""
    echo "    export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    echo ""
    echo "Then restart your terminal or run:"
    echo ""
    echo "    source ~/.bashrc  # or source ~/.zshrc"
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
