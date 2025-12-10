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
import pty
import select
import tty
import termios
from pathlib import Path
from typing import Optional
import shutil

try:
    import requests
except ImportError:
    requests = None

# =============================================================================
# Configuration
# =============================================================================

HANSEL_DIR = Path.home() / ".hansel"
BUFFER_FILE = HANSEL_DIR / "buffer.txt"
LOG_DIR = HANSEL_DIR / "logs"
CONFIG_FILE = HANSEL_DIR / "config.env"
SYSTEM_PROMPT_FILE = HANSEL_DIR / "system_prompt.txt"
LANG_DIR = HANSEL_DIR / "lang"

# Script directory for bundled lang files
SCRIPT_DIR = Path(__file__).parent.resolve() if '__file__' in dir() else Path.cwd()

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

# Cache for loaded patterns
_question_patterns_cache = None

def load_question_patterns() -> list:
    """Load question patterns from lang files."""
    global _question_patterns_cache

    if _question_patterns_cache is not None:
        return _question_patterns_cache

    patterns = []

    # Look for lang files in multiple locations
    lang_dirs = [
        SCRIPT_DIR / "lang",  # Bundled with script
        LANG_DIR,             # User's ~/.hansel/lang
    ]

    for lang_dir in lang_dirs:
        if lang_dir.exists() and lang_dir.is_dir():
            for lang_file in lang_dir.glob("*.txt"):
                try:
                    with open(lang_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            # Skip empty lines and comments
                            if line and not line.startswith('#'):
                                patterns.append(line)
                except Exception:
                    pass  # Skip files that can't be read

    # Fallback patterns if no files found
    if not patterns:
        patterns = [
            r'\?\s*$',
            r'^Would you',
            r'^Do you',
            r'^Should I',
            r'want me to',
            r'like me to',
            r'proceed',
        ]

    _question_patterns_cache = patterns
    return patterns


def is_question(line: str) -> bool:
    """Detect if a line is a question from Claude."""
    if not line or not line.strip():
        return False

    line = line.strip()

    # Minimum length for a real question
    if len(line) < 15:
        return False

    # Skip lines that are clearly not questions (UI hints, shortcuts, code, menus)
    skip_patterns = [
        r'^[\s]*[#/\*]',      # Comments
        r'^[\s]*import ',     # Import statements
        r'^[\s]*from ',       # From imports
        r'^[\s]*def ',        # Function definitions
        r'^[\s]*class ',      # Class definitions
        r'^\+',               # Diff additions
        r'^\-',               # Diff removals
        r'^\?',               # Lines starting with ? (help hints)
        r'for shortcuts',     # UI hint text
        r'to interrupt',      # UI hint text (esc to interrupt)
        r'to edit',           # UI hint text (ctrl-g to edit)
        r'ctrl[-+]',          # Keyboard shortcuts
        r'esc\s+to',          # Escape key hints
        r'^>',                # Input prompts
        r'Spelunking',        # Claude status messages
        r'Thinking',          # Claude status messages
        r'Reading',           # Claude status messages
        r'Writing',           # Claude status messages
        r'Searching',         # Claude status messages
        # Interactive menu/checkbox patterns
        r'^\d+\.',            # Numbered list items (1. 2. 3.)
        r'^\[\s*[\]xX✓✔]\s*\]',  # Checkbox items [ ] [x] [✓]
        r'Enter to select',   # Menu navigation hints
        r'Tab.*to navigate',  # Tab navigation hints
        r'Arrow keys',        # Arrow key hints
        r'to cancel',         # Cancel hints
        r'^←|^→|^↑|^↓',       # Arrow symbols
        r'^\s*Next\s*$',      # "Next" button
        r'Submit',            # Submit button
        r'Package',           # Menu items
        r'Features',          # Menu items
        r'Rendering',         # Menu items
        r'Styling',           # Menu items
        r'initial version',   # Interactive menu question
        r'core features',     # Interactive menu question
        r'want in the',       # Interactive menu question pattern
    ]

    for pattern in skip_patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return False

    # Load patterns from lang files
    question_patterns = load_question_patterns()

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
    line_buffer = ""
    start_time = time.time()
    listening_started = False
    master_fd = None
    last_response_lines = set()  # Track our last response lines to avoid loops
    last_question_time = 0  # Cooldown between questions
    cooldown_seconds = 15  # Wait at least 15 seconds between questions
    response_cooldown_until = 0  # Don't detect questions until this time
    user_typing_until = [0]  # Cooldown after user types (list for mutability)

    # Create session log file
    session_id = time.strftime('%Y%m%d_%H%M%S')
    log_file = LOG_DIR / f"session_{session_id}.log"

    def log_to_file(msg: str):
        """Write to session log."""
        with open(log_file, 'a', encoding='utf-8') as f:
            ts = time.strftime('%H:%M:%S')
            f.write(f"[{ts}] {msg}\n")

    log_to_file(f"Session started: {cmd}")

    # Save original terminal settings
    old_tty = termios.tcgetattr(sys.stdin)

    def handle_output(data: str):
        """Process output data and check for questions."""
        nonlocal line_buffer, listening_started, buffer_lines, last_question_time, response_cooldown_until

        line_buffer += data

        # Skip if user recently typed (to avoid processing echo)
        if time.time() < user_typing_until[0]:
            return

        # Process complete lines
        while '\n' in line_buffer or '\r' in line_buffer:
            # Split on newline or carriage return
            for sep in ['\r\n', '\n', '\r']:
                if sep in line_buffer:
                    line, line_buffer = line_buffer.split(sep, 1)
                    break
            else:
                break

            clean_line = clean_ansi(line)
            if not clean_line.strip():
                continue

            # Log to buffer and file
            with open(BUFFER_FILE, 'a') as f:
                f.write(clean_line + '\n')
            buffer_lines.append(clean_line)
            log_to_file(f"OUT: {clean_line[:100]}")

            # Keep buffer reasonable size
            if len(buffer_lines) > 200:
                buffer_lines = buffer_lines[-100:]

            # Check startup delay
            elapsed = time.time() - start_time
            if not listening_started and elapsed >= config.startup_delay:
                listening_started = True
                print(f"\n{Colors.GREEN}Now listening for questions...{Colors.NC}", file=sys.stderr)
                log_to_file("Listening started")

            # Skip if this looks like our own response
            line_normalized = clean_line.strip().lower()[:50]
            for resp_line in last_response_lines:
                if line_normalized and resp_line and (
                    line_normalized.startswith(resp_line) or
                    resp_line.startswith(line_normalized)
                ):
                    log_to_file(f"SKIP (own response): {clean_line[:50]}")
                    return  # Skip this entire line

            # Check response cooldown (don't detect anything as question right after we sent response)
            if time.time() < response_cooldown_until:
                log_to_file(f"SKIP (response cooldown): {clean_line[:50]}")
                continue

            # Check cooldown between questions
            time_since_last = time.time() - last_question_time
            if time_since_last < cooldown_seconds:
                continue

            # Check for questions (only after startup delay)
            if listening_started and is_question(clean_line):
                last_question_time = time.time()
                log_to_file(f"QUESTION: {clean_line}")
                # Run in background thread to not block
                threading.Thread(
                    target=respond_to_question,
                    args=(clean_line, list(buffer_lines), config, master_fd),
                    daemon=True
                ).start()

    def is_confirmation_prompt(question: str, context: list) -> bool:
        """Check if this is a simple yes/no confirmation with menu options."""
        q_lower = question.lower()
        # Check if it's a proceed/confirm type question
        confirm_patterns = ['do you want to proceed', 'want to continue', 'should i proceed',
                           'do you want me to', 'shall i continue', 'ready to proceed']
        if any(p in q_lower for p in confirm_patterns):
            # Check if recent context has numbered options (1. Yes, 2. No, etc.)
            recent = '\n'.join(context[-10:]).lower()
            if '1.' in recent and ('yes' in recent or 'no' in recent):
                return True
        return False

    def respond_to_question(question: str, context_lines: list, cfg: Config, fd: int):
        """Get AI response and send it."""
        nonlocal last_response_lines, response_cooldown_until

        # Check if this is a simple confirmation prompt with menu
        if is_confirmation_prompt(question, context_lines):
            print(f"\n{Colors.CYAN}Confirmation prompt detected:{Colors.NC} {question}", file=sys.stderr)
            print(f"{Colors.GREEN}Auto-confirming with Enter{Colors.NC}", file=sys.stderr)
            log_to_file(f"CONFIRM: {question}")
            time.sleep(cfg.response_delay)
            response_cooldown_until = time.time() + 10
            if fd:
                os.write(fd, b'\r')  # Just press Enter to confirm default (Yes)
            return

        print(f"\n{Colors.CYAN}Question detected:{Colors.NC} {question}", file=sys.stderr)
        print(f"{Colors.YELLOW}   Consulting AI advisor...{Colors.NC}", file=sys.stderr)

        context = '\n'.join(context_lines[-100:])
        response = call_chatgpt(question, context, cfg)

        # Store response lines to avoid detecting them as questions
        # Normalize and store each line of the response
        last_response_lines.clear()
        for line in response.split('\n'):
            normalized = line.strip().lower()[:50]
            if normalized:
                last_response_lines.add(normalized)
        # Also store the first part of the whole response
        last_response_lines.add(response.strip().lower()[:50])

        print(f"{Colors.GREEN}Response:{Colors.NC} {response}", file=sys.stderr)
        log_to_file(f"RESPONSE: {response}")

        # Wait before responding
        time.sleep(cfg.response_delay)

        # Set cooldown - don't detect questions for 20 seconds after sending response
        response_cooldown_until = time.time() + 20

        # Send response to the PTY
        if fd:
            # Type response character by character with small delay
            for char in response:
                os.write(fd, char.encode())
                time.sleep(0.01)  # 10ms delay between chars
            # Send Enter key (try multiple approaches)
            time.sleep(0.1)
            os.write(fd, b'\r')  # Carriage return
            time.sleep(0.05)
            os.write(fd, b'\n')  # Newline

    try:
        # Create pseudo-terminal
        pid, master_fd = pty.fork()

        if pid == 0:
            # Child process - execute command
            os.execlp('/bin/sh', '/bin/sh', '-c', cmd)
        else:
            # Parent process
            # Set terminal to raw mode so keystrokes go through
            tty.setraw(sys.stdin.fileno())

            try:
                while True:
                    # Wait for input from either stdin or the PTY
                    rlist, _, _ = select.select([sys.stdin, master_fd], [], [], 0.1)

                    for fd in rlist:
                        if fd == sys.stdin:
                            # User typed something - forward to PTY
                            data = os.read(sys.stdin.fileno(), 1024)
                            if data:
                                os.write(master_fd, data)
                                # Track that user is typing - don't process output for 0.5s
                                user_typing_until[0] = time.time() + 0.5
                        elif fd == master_fd:
                            # Output from PTY - display and analyze
                            try:
                                data = os.read(master_fd, 1024)
                                if data:
                                    # Write to stdout
                                    os.write(sys.stdout.fileno(), data)
                                    # Process for questions
                                    handle_output(data.decode('utf-8', errors='replace'))
                                else:
                                    # EOF
                                    raise EOFError()
                            except OSError:
                                raise EOFError()

                    # Check if child process has exited
                    result = os.waitpid(pid, os.WNOHANG)
                    if result[0] != 0:
                        break

            except EOFError:
                pass

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.NC}")
        return 1
    finally:
        # Restore terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)

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
    if requests is not None:
        print(f"   requests:    {Colors.GREEN}installed{Colors.NC}")
    else:
        print(f"   requests:    {Colors.RED}not installed{Colors.NC} (needed for API calls)")

    # Show loaded languages
    patterns = load_question_patterns()
    print(f"   Patterns:    {len(patterns)} loaded")

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
