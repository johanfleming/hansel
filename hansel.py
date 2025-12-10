#!/usr/bin/env python3
"""
Hansel - Autonomous Terminal AI Bridge

Watches Claude CLI, detects questions, consults ChatGPT, and automatically
types the response back to Claude. Fully autonomous operation.

Usage:
    hansel auto "claude"            # Full autonomous mode
    hansel watch "claude"           # Watch only (no auto-type)
"""

import os
import sys
import re
import json
import time
import signal
import subprocess
import threading
import argparse
from pathlib import Path
from typing import Optional
import shutil

try:
    import requests
except ImportError:
    requests = None

try:
    import pexpect
except ImportError:
    pexpect = None

# =============================================================================
# Configuration
# =============================================================================

HANSEL_DIR = Path.home() / ".hansel"
BUFFER_FILE = HANSEL_DIR / "buffer.txt"
LOG_DIR = HANSEL_DIR / "logs"
CONFIG_FILE = HANSEL_DIR / "config.env"
SYSTEM_PROMPT_FILE = HANSEL_DIR / "system_prompt.txt"

# Colors
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    NC = '\033[0m'  # No Color

# Default system prompt
DEFAULT_SYSTEM_PROMPT = """You are a senior system architect helping Claude (another AI) implement a software project.

CRITICAL RULES:
1. Give DIRECT, ACTIONABLE answers - no fluff
2. When asked yes/no questions, start with "yes" or "no"
3. When asked to choose between options, state your choice first
4. Keep responses concise (2-4 sentences max for simple questions)
5. For technical questions, include brief code snippets if helpful

Your response will be automatically typed into Claude's terminal, so:
- Don't use markdown formatting (no ```, no ##, no **)
- Write plain text only
- Be concise - long responses slow things down

Examples:
Q: "Should I use PostgreSQL or MongoDB?"
A: PostgreSQL. Better for relational data, ACID compliance, and complex queries. MongoDB only if you need flexible schemas for unstructured data.

Q: "Do you want me to proceed with this implementation?"
A: Yes, proceed.

Q: "How should I structure the API endpoints?"
A: Use RESTful conventions: GET /users for list, POST /users for create, GET /users/:id for single, PUT /users/:id for update, DELETE /users/:id for delete.
"""

DEFAULT_CONFIG = """# Hansel Configuration
# OPENAI_API_KEY=sk-your-key-here
# OPENAI_MODEL=gpt-4o
# RESPONSE_DELAY=2
# STARTUP_DELAY=5
"""

# =============================================================================
# Configuration Management
# =============================================================================

class Config:
    def __init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        self.response_delay = int(os.environ.get("RESPONSE_DELAY", "2"))
        self.startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
        self.load_config()

    def load_config(self):
        """Load configuration from config file."""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == "OPENAI_API_KEY" and value:
                            self.openai_api_key = value
                        elif key == "OPENAI_MODEL" and value:
                            self.openai_model = value
                        elif key == "RESPONSE_DELAY" and value:
                            try:
                                self.response_delay = int(value)
                            except ValueError:
                                pass
                        elif key == "STARTUP_DELAY" and value:
                            try:
                                self.startup_delay = int(value)
                            except ValueError:
                                pass

    def save_config(self):
        """Save configuration to config file."""
        content = f"""# Hansel Configuration
OPENAI_API_KEY={self.openai_api_key}
OPENAI_MODEL={self.openai_model}
RESPONSE_DELAY={self.response_delay}
STARTUP_DELAY={self.startup_delay}
"""
        with open(CONFIG_FILE, 'w') as f:
            f.write(content)

# =============================================================================
# Setup
# =============================================================================

def ensure_dirs():
    """Create necessary directories and default files."""
    HANSEL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'w') as f:
            f.write(DEFAULT_CONFIG)

    if not SYSTEM_PROMPT_FILE.exists():
        with open(SYSTEM_PROMPT_FILE, 'w') as f:
            f.write(DEFAULT_SYSTEM_PROMPT)

# =============================================================================
# ChatGPT Integration
# =============================================================================

def call_chatgpt(question: str, context: str, config: Config) -> str:
    """Call ChatGPT API with question and context."""
    if requests is None:
        return "Error: requests library not installed. Run: pip install requests"

    if not config.openai_api_key:
        return "Error: OPENAI_API_KEY not set"

    system_prompt = ""
    if SYSTEM_PROMPT_FILE.exists():
        with open(SYSTEM_PROMPT_FILE, 'r') as f:
            system_prompt = f.read()

    user_message = f"""CONTEXT (recent terminal output):
{context}

CLAUDE'S QUESTION:
{question}

Provide a direct, actionable response."""

    payload = {
        "model": config.openai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.openai_api_key}"
            },
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "Error: No response")
    except requests.exceptions.RequestException as e:
        return f"Error: API request failed - {e}"
    except (KeyError, json.JSONDecodeError) as e:
        return f"Error: Failed to parse response - {e}"

# =============================================================================
# Question Detection
# =============================================================================

def is_question(line: str) -> bool:
    """Detect if a line is a question from Claude."""
    if not line or not line.strip():
        return False

    line = line.strip()

    # Skip lines that are clearly not questions
    skip_patterns = [
        r'^[\s]*[#/\*]',  # Comments
        r'^[\s]*import ',  # Import statements
        r'^[\s]*from ',    # From imports
        r'^[\s]*def ',     # Function definitions
        r'^[\s]*class ',   # Class definitions
        r'^\+',            # Diff additions
        r'^\-',            # Diff removals
    ]

    for pattern in skip_patterns:
        if re.match(pattern, line):
            return False

    # Question patterns
    question_patterns = [
        r'\?\s*$',           # Ends with ?
        r'^Would you',       # Would you...
        r'^Do you',          # Do you...
        r'^Should I',        # Should I...
        r'^Can I',           # Can I...
        r'^Could you',       # Could you...
        r'^What ',           # What...
        r'^How ',            # How...
        r'^Which ',          # Which...
        r'^Where ',          # Where...
        r'^Is this',         # Is this...
        r'^Are you',         # Are you...
        r'want me to',       # ...want me to...
        r'like me to',       # ...like me to...
        r'proceed',          # ...proceed...
        r'continue',         # ...continue...
        r'confirm',          # ...confirm...
        r'approve',          # ...approve...
    ]

    for pattern in question_patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return True

    return False

# =============================================================================
# ANSI Code Cleaning
# =============================================================================

def clean_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_pattern.sub('', text).replace('\r', '')

# =============================================================================
# Autonomous Mode
# =============================================================================

def autonomous_mode(cmd: str, config: Config):
    """Run in full autonomous mode with auto-typing responses."""
    if pexpect is None:
        print(f"{Colors.RED}Error: pexpect library not installed.{Colors.NC}")
        print("Run: pip install pexpect")
        return 1

    if not config.openai_api_key:
        print(f"{Colors.RED}Error: OPENAI_API_KEY not set{Colors.NC}")
        print("Run: hansel config")
        return 1

    print(f"{Colors.GREEN}Hansel Autonomous Mode{Colors.NC}")
    print(f"   Command: {Colors.BLUE}{cmd}{Colors.NC}")
    print(f"   Model: {Colors.CYAN}{config.openai_model}{Colors.NC}")
    print(f"   Response delay: {config.response_delay}s")
    print(f"   Startup delay: {config.startup_delay}s")
    print()
    print(f"{Colors.YELLOW}Press Ctrl+C to exit{Colors.NC}")
    print("=" * 40)
    print()

    # Initialize buffer
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(BUFFER_FILE, 'a') as f:
        f.write(f"[{timestamp}] Starting: {cmd}\n")

    buffer_lines = []
    start_time = time.time()
    listening_started = False

    try:
        # Spawn the process
        child = pexpect.spawn(cmd, encoding='utf-8', timeout=None)
        child.logfile_read = sys.stdout

        while True:
            try:
                # Read output
                index = child.expect(['\r\n', '\n', pexpect.EOF, pexpect.TIMEOUT], timeout=0.5)

                if index in [0, 1]:  # Got a line
                    line = child.before
                    clean_line = clean_ansi(line)

                    # Log to buffer
                    with open(BUFFER_FILE, 'a') as f:
                        f.write(clean_line + '\n')
                    buffer_lines.append(clean_line)

                    # Keep buffer reasonable size
                    if len(buffer_lines) > 200:
                        buffer_lines = buffer_lines[-100:]

                    # Wait for startup delay before listening for questions
                    elapsed = time.time() - start_time
                    if not listening_started and elapsed >= config.startup_delay:
                        listening_started = True
                        print(f"\n{Colors.GREEN}Now listening for questions...{Colors.NC}", file=sys.stderr)

                    # Check for questions (only after startup delay)
                    if listening_started and is_question(clean_line):
                        print(f"\n{Colors.CYAN}Question detected:{Colors.NC} {clean_line}", file=sys.stderr)
                        print(f"{Colors.YELLOW}   Consulting ChatGPT...{Colors.NC}", file=sys.stderr)

                        # Get context
                        context = '\n'.join(buffer_lines[-100:])

                        # Get response
                        response = call_chatgpt(clean_line, context, config)
                        print(f"{Colors.GREEN}Response:{Colors.NC} {response}", file=sys.stderr)

                        # Wait before responding
                        time.sleep(config.response_delay)

                        # Type response
                        child.sendline(response)

                elif index == 2:  # EOF
                    break

            except pexpect.TIMEOUT:
                continue

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.NC}")
        return 1

    return 0

# =============================================================================
# Watch Mode
# =============================================================================

def watch_command(cmd: str, config: Config):
    """Watch command output and suggest responses (no auto-typing)."""
    print(f"{Colors.BLUE}Watching:{Colors.NC} {cmd}")
    print(f"   Startup delay: {config.startup_delay}s")
    print()

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(BUFFER_FILE, 'a') as f:
        f.write("=" * 40 + '\n')
        f.write(f"[{timestamp}] $ {cmd}\n")
        f.write("=" * 40 + '\n')

    buffer_lines = []
    start_time = time.time()
    listening_started = False

    try:
        # Use subprocess with PTY-like behavior
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in iter(process.stdout.readline, ''):
            clean_line = clean_ansi(line.rstrip())
            print(line, end='')

            with open(BUFFER_FILE, 'a') as f:
                f.write(clean_line + '\n')
            buffer_lines.append(clean_line)

            # Keep buffer reasonable
            if len(buffer_lines) > 200:
                buffer_lines = buffer_lines[-100:]

            # Wait for startup delay before listening for questions
            elapsed = time.time() - start_time
            if not listening_started and elapsed >= config.startup_delay:
                listening_started = True
                print(f"\n{Colors.GREEN}Now listening for questions...{Colors.NC}", file=sys.stderr)

            # Detect questions (only after startup delay)
            if listening_started and is_question(clean_line):
                print(f"\n{Colors.CYAN}Question detected:{Colors.NC} {clean_line}", file=sys.stderr)

                if config.openai_api_key:
                    context = '\n'.join(buffer_lines[-50:])
                    response = call_chatgpt(clean_line, context, config)
                    print(f"{Colors.GREEN}Suggested:{Colors.NC} {response}", file=sys.stderr)
                    print(f"{Colors.YELLOW}(Copy and paste, or type your own){Colors.NC}", file=sys.stderr)

        process.wait()

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.NC}")
        return 1

    return 0

# =============================================================================
# Buffer Operations
# =============================================================================

def show_buffer():
    """Show full buffer contents."""
    if BUFFER_FILE.exists():
        with open(BUFFER_FILE, 'r') as f:
            print(f.read())
    else:
        print("Buffer is empty")

def last_lines(n: int = 50):
    """Show last N lines of buffer."""
    if BUFFER_FILE.exists():
        with open(BUFFER_FILE, 'r') as f:
            lines = f.readlines()
            for line in lines[-n:]:
                print(line, end='')
    else:
        print("Buffer is empty")

def clear_buffer():
    """Clear the buffer file."""
    if BUFFER_FILE.exists():
        BUFFER_FILE.unlink()
    print(f"{Colors.GREEN}Buffer cleared{Colors.NC}")

# =============================================================================
# Ask ChatGPT Directly
# =============================================================================

def ask_gpt(question: str, config: Config):
    """Ask ChatGPT directly with buffer context."""
    print(f"{Colors.CYAN}Asking ChatGPT...{Colors.NC}", file=sys.stderr)

    context = ""
    if BUFFER_FILE.exists():
        with open(BUFFER_FILE, 'r') as f:
            lines = f.readlines()
            context = ''.join(lines[-100:])

    response = call_chatgpt(question, context, config)
    print(response)

# =============================================================================
# Configuration
# =============================================================================

def configure(config: Config):
    """Interactive configuration."""
    ensure_dirs()

    print(f"{Colors.GREEN}Hansel Configuration{Colors.NC}")
    print("=" * 40)

    # API Key
    current_key = config.openai_api_key[:10] + "..." if config.openai_api_key else ""
    new_key = input(f"OpenAI API Key [{current_key}]: ").strip()
    if new_key:
        config.openai_api_key = new_key

    # Model
    new_model = input(f"OpenAI Model [{config.openai_model}]: ").strip()
    if new_model:
        config.openai_model = new_model

    # Response delay
    new_delay = input(f"Response delay seconds [{config.response_delay}]: ").strip()
    if new_delay:
        try:
            config.response_delay = int(new_delay)
        except ValueError:
            print(f"{Colors.YELLOW}Invalid number, keeping current value{Colors.NC}")

    # Startup delay
    new_startup = input(f"Startup delay seconds [{config.startup_delay}]: ").strip()
    if new_startup:
        try:
            config.startup_delay = int(new_startup)
        except ValueError:
            print(f"{Colors.YELLOW}Invalid number, keeping current value{Colors.NC}")

    config.save_config()
    print()
    print(f"{Colors.GREEN}Configuration saved{Colors.NC}")

    # Edit system prompt
    edit_prompt = input("Edit system prompt? (y/N): ").strip().lower()
    if edit_prompt == 'y':
        editor = os.environ.get('EDITOR', 'nano')
        subprocess.run([editor, str(SYSTEM_PROMPT_FILE)])

# =============================================================================
# Uninstall
# =============================================================================

def uninstall_hansel():
    """Uninstall Hansel."""
    print(f"{Colors.RED}Hansel Uninstall{Colors.NC}")
    print("=" * 40)

    confirm = input("Remove Hansel and all data? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return

    # Remove binary
    bin_path = Path.home() / ".local" / "bin" / "hansel"
    bin_path_py = Path.home() / ".local" / "bin" / "hansel.py"

    for path in [bin_path, bin_path_py]:
        if path.exists():
            path.unlink()
            print(f"{Colors.GREEN}Removed {path}{Colors.NC}")

    # Remove data directory
    if HANSEL_DIR.exists():
        confirm_data = input(f"Remove config and data ({HANSEL_DIR})? (y/N): ").strip().lower()
        if confirm_data == 'y':
            shutil.rmtree(HANSEL_DIR)
            print(f"{Colors.GREEN}Removed {HANSEL_DIR}{Colors.NC}")
        else:
            print(f"   Kept {HANSEL_DIR}")

    print()
    print("Hansel uninstalled.")
    print()
    print("Note: PATH entry in ~/.zshrc or ~/.bashrc was not removed.")
    print("You can remove it manually if desired.")

# =============================================================================
# Status
# =============================================================================

def show_status(config: Config):
    """Show Hansel status."""
    ensure_dirs()

    print("Hansel Status")
    print("=" * 40)
    print(f"   Directory:   {HANSEL_DIR}")

    if BUFFER_FILE.exists():
        with open(BUFFER_FILE, 'r') as f:
            lines = len(f.readlines())
        size = BUFFER_FILE.stat().st_size
        if size < 1024:
            size_str = f"{size}B"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f}K"
        else:
            size_str = f"{size / (1024 * 1024):.1f}M"
        print(f"   Buffer:      {lines} lines ({size_str})")
    else:
        print("   Buffer:      empty")

    print()
    key_display = config.openai_api_key[:10] + "..." if config.openai_api_key else "not set"
    print(f"   OpenAI Key:  {key_display}")
    print(f"   Model:       {config.openai_model}")
    print(f"   Delay:       {config.response_delay}s")
    print(f"   Startup:     {config.startup_delay}s")

    # Check dependencies
    if pexpect is not None:
        print(f"   pexpect:     {Colors.GREEN}installed{Colors.NC}")
    else:
        print(f"   pexpect:     {Colors.RED}not installed{Colors.NC} (needed for auto mode)")

    if requests is not None:
        print(f"   requests:    {Colors.GREEN}installed{Colors.NC}")
    else:
        print(f"   requests:    {Colors.RED}not installed{Colors.NC} (needed for API calls)")

# =============================================================================
# Help
# =============================================================================

def show_help():
    """Show help message."""
    help_text = """Hansel - Autonomous Terminal AI Bridge

Watches Claude CLI, detects questions, consults ChatGPT, and automatically
responds. Full autopilot mode available.

USAGE:
    hansel <COMMAND> [ARGUMENTS]

COMMANDS:
    auto <cmd>      FULL AUTONOMOUS MODE - auto-detects and responds
                    Example: hansel auto claude

    watch <cmd>     Watch mode - detects questions, suggests responses
                    Example: hansel watch "npm run dev"

    ask <question>  Ask ChatGPT directly (uses buffer as context)

    buffer          Show full buffer
    last [N]        Show last N lines (default: 50)
    clear           Clear buffer

    config          Configure settings
    status          Show status
    uninstall       Remove Hansel
    help            Show this help

EXAMPLES:
    # Full autopilot (recommended)
    hansel auto claude

    # Watch only, manual responses
    hansel watch claude

    # Ask ChatGPT with context
    hansel ask "How should I implement this?"

CONFIGURATION:
    Config: ~/.hansel/config.env
    System prompt: ~/.hansel/system_prompt.txt

    Variables:
      OPENAI_API_KEY    Your OpenAI API key
      OPENAI_MODEL      Model to use (default: gpt-4o)
      RESPONSE_DELAY    Seconds before auto-responding (default: 2)

HOW IT WORKS:
    1. Hansel spawns Claude CLI in a PTY
    2. Monitors output for question patterns
    3. When question detected, sends context to ChatGPT
    4. ChatGPT (as system architect) provides answer
    5. Answer is automatically typed into Claude CLI

REQUIREMENTS:
    pip install requests pexpect
"""
    print(help_text)

# =============================================================================
# Main
# =============================================================================

def main():
    """Main entry point."""
    ensure_dirs()
    config = Config()

    if len(sys.argv) < 2:
        show_help()
        return 0

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    if command in ['auto', 'autopilot', 'autonomous']:
        if not args:
            print("Usage: hansel auto <command>")
            print("Example: hansel auto claude")
            return 1
        return autonomous_mode(' '.join(args), config)

    elif command == 'watch':
        if not args:
            print("Usage: hansel watch <command>")
            return 1
        return watch_command(' '.join(args), config)

    elif command == 'ask':
        if not args:
            print("Usage: hansel ask <question>")
            return 1
        ask_gpt(' '.join(args), config)
        return 0

    elif command == 'buffer':
        show_buffer()
        return 0

    elif command == 'last':
        n = 50
        if args:
            try:
                n = int(args[0])
            except ValueError:
                pass
        last_lines(n)
        return 0

    elif command == 'clear':
        clear_buffer()
        return 0

    elif command in ['config', 'configure']:
        configure(config)
        return 0

    elif command == 'status':
        show_status(config)
        return 0

    elif command == 'uninstall':
        uninstall_hansel()
        return 0

    elif command in ['help', '--help', '-h']:
        show_help()
        return 0

    else:
        print(f"{Colors.RED}Unknown command:{Colors.NC} {command}")
        show_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())
