#!/usr/bin/env python3
"""
Hansel Installer

Usage:
    python install.py

Or with curl:
    curl -fsSL https://raw.githubusercontent.com/johanfleming/hansel/main/install.py | python3
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

INSTALL_DIR = Path.home() / ".local" / "bin"
REPO_URL = "https://raw.githubusercontent.com/johanfleming/hansel/main"

def check_command(cmd):
    """Check if a command is available."""
    return shutil.which(cmd) is not None

def main():
    print("Hansel Installation (Python)")
    print("=" * 40)

    # Check Python version
    if sys.version_info < (3, 7):
        print("Error: Python 3.7+ is required")
        sys.exit(1)
    print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}")

    # Check dependencies
    print("\nChecking dependencies...")

    missing_packages = []

    try:
        import requests
        print("  requests: installed")
    except ImportError:
        print("  requests: NOT installed")
        missing_packages.append("requests")

    try:
        import pexpect
        print("  pexpect: installed")
    except ImportError:
        print("  pexpect: NOT installed (needed for auto mode)")
        missing_packages.append("pexpect")

    if missing_packages:
        print(f"\nInstalling missing packages: {', '.join(missing_packages)}")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install"] + missing_packages,
                check=True
            )
            print("Packages installed successfully")
        except subprocess.CalledProcessError:
            print(f"\nWarning: Could not install packages automatically.")
            print(f"Run: pip install {' '.join(missing_packages)}")

    print()

    # Create install directory
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # Determine source
    script_dir = Path(__file__).parent.resolve()
    source_file = script_dir / "hansel.py"

    dest_file = INSTALL_DIR / "hansel"

    if source_file.exists():
        print("Installing from local source...")
        shutil.copy(source_file, dest_file)
    else:
        print("Downloading from GitHub...")
        try:
            import urllib.request
            urllib.request.urlretrieve(f"{REPO_URL}/hansel.py", dest_file)
        except Exception as e:
            print(f"Error downloading: {e}")
            sys.exit(1)

    # Make executable
    os.chmod(dest_file, 0o755)
    print(f"Hansel installed: {dest_file}")

    # PATH check
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    install_dir_str = str(INSTALL_DIR)

    if install_dir_str not in path_dirs:
        print(f"\nWarning: {INSTALL_DIR} is not in PATH.")

        # Detect shell config
        shell = os.environ.get("SHELL", "")
        if "zsh" in shell:
            shell_config = Path.home() / ".zshrc"
        else:
            shell_config = Path.home() / ".bashrc"

        # Check if already in config (must be uncommented export line)
        path_line = 'export PATH="${HOME}/.local/bin:${PATH}"'

        if shell_config.exists():
            content = shell_config.read_text()
            # Check for active (uncommented) .local/bin in PATH
            has_active_path = False
            for line in content.splitlines():
                line_stripped = line.strip()
                if '.local/bin' in line_stripped and not line_stripped.startswith('#'):
                    has_active_path = True
                    break

            if not has_active_path:
                print(f"   Adding to {shell_config}...")
                with open(shell_config, 'a') as f:
                    f.write('\n# Hansel - added by installer\n')
                    f.write(path_line + '\n')
                print(f"PATH added to {shell_config}")
            else:
                print(f"   PATH already in {shell_config}")
        else:
            print(f"\nAdd this line to your shell config:")
            print(f"    {path_line}")

        print()
        print("To use hansel, either:")
        print("    1. Open a new terminal, or")
        print("    2. Run: source ~/.zshrc")
    else:
        print("PATH already configured")

    print()
    print("Installation complete!")
    print()
    print("Next steps:")
    print("    hansel config             # Set OpenAI API key")
    print("    hansel watch 'claude'     # Watch Claude CLI")
    print("    hansel help               # Show help")
    print()
    print("Quick start with auto-respond:")
    print("    hansel auto claude")
    print()
    print("Or run directly:")
    print(f"    {dest_file} help")

if __name__ == "__main__":
    main()
