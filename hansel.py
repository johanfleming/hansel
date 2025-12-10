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
import select
from pathlib import Path
from typing import Optional
import shutil
import platform

# Unix-only modules (not available on Windows)
IS_WINDOWS = platform.system() == "Windows"
if not IS_WINDOWS:
    import pty
    import tty
    import termios
else:
    pty = None
    tty = None
    termios = None

try:
    import requests
except ImportError:
    requests = None

# =============================================================================
# Sound Notification
# =============================================================================

def play_notification_sound():
    """Play a notification sound when AI advisor responds."""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            # Use system sound
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Glass.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        elif system == "Windows":
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        elif system == "Linux":
            # Try paplay (PulseAudio) or aplay (ALSA)
            for cmd in [["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                       ["aplay", "/usr/share/sounds/alsa/Front_Center.wav"]]:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except FileNotFoundError:
                    continue
    except Exception:
        pass  # Silently fail if sound doesn't work

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

# Enable ANSI colors on Windows
if IS_WINDOWS:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Enable ANSI escape sequences on Windows 10+
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass  # Ignore if it fails

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
        r'want to use',       # Interactive menu question
        r'framework.*setup',  # Framework selection menu
        r'do you want to use for', # Selection menu pattern
        r'which.*would you',  # Which would you like/prefer
        r'select.*from',      # Select from options
        r'choose.*from',      # Choose from options
        # Code patterns - skip code snippets that contain ?
        r'\w+\?\s*$',         # TypeScript/Prisma optional types: String?, Int?
        r'===\s*[\'"]?\w+[\'"]?\s*\?',  # Ternary operators: === 'text' ?
        r'\?\s*:',            # Ternary operator: condition ? true : false
        r'\?\.',              # Optional chaining: obj?.prop
        r'\?\[',              # Optional indexing: arr?[0]
        r'^\s*\w+\s+\w+\??$', # Schema fields: fieldName Type?
        r'const\s+\w+',       # Variable declarations
        r'let\s+\w+',         # Variable declarations
        r'var\s+\w+',         # Variable declarations
        r'=>',                # Arrow functions
        r'\{.*\}',            # Objects/blocks with braces
        r'\[.*\]',            # Arrays with brackets
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
# ASCII Art Banner
# =============================================================================

def show_banner(mode: str = "auto", version: str = "0.1.7"):
    """Show Hansel ASCII art banner."""
    # Colors for the house
    BROWN = '\033[38;5;130m'
    YELLOW = '\033[38;5;220m'
    GREEN = '\033[38;5;34m'
    RED = '\033[38;5;196m'
    CYAN = '\033[38;5;51m'
    WHITE = '\033[38;5;255m'
    DIM = '\033[2m'
    NC = '\033[0m'

    house = f"""
{DIM}───────────────────────────────────{NC}
{BROWN}            /\\{NC}
{BROWN}           /  \\{NC}
{BROWN}          /    \\{NC}
{RED}         /______\\{NC}
{YELLOW}        |  {WHITE}_  _{YELLOW}  |{NC}
{YELLOW}        | {CYAN}|o||o|{YELLOW} |{NC}
{YELLOW}        |  {WHITE}‾‾‾{YELLOW}  |{NC}
{YELLOW}        |{GREEN}HANSEL{YELLOW} |{NC}
{YELLOW}        |__{WHITE}[]{YELLOW}__|{NC}
{DIM}───────────────────────────────────{NC}
{WHITE}  Hansel v{version} - {mode} mode{NC}
{DIM}───────────────────────────────────{NC}
"""
    print(house, file=sys.stderr)

# =============================================================================
# ANSI Code Cleaning
# =============================================================================

def clean_ansi(text: str) -> str:
    """Remove ANSI escape codes and terminal control sequences from text."""
    # Remove all ANSI escape sequences
    # CSI sequences: ESC [ ... (parameters) ... (final byte)
    text = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', text)
    # OSC sequences: ESC ] ... BEL or ST
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?', '', text)
    # Other escape sequences
    text = re.sub(r'\x1b[PX^_][^\x1b]*\x1b\\', '', text)
    text = re.sub(r'\x1b.', '', text)
    # Remove carriage returns and other control chars (except newline)
    text = re.sub(r'[\r\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text

# =============================================================================
# Autonomous Mode
# =============================================================================

def autonomous_mode(cmd: str, config: Config):
    """Run in full autonomous mode with auto-typing responses."""
    if IS_WINDOWS:
        print(f"{Colors.RED}Error: Autonomous mode is not supported on Windows{Colors.NC}")
        print("Windows does not support PTY (pseudo-terminal) which is required for auto-typing.")
        print(f"\nYou can use watch mode instead: {Colors.CYAN}hansel watch {cmd}{Colors.NC}")
        return 1

    if not config.openai_api_key:
        print(f"{Colors.RED}Error: OPENAI_API_KEY not set{Colors.NC}")
        print("Run: hansel config")
        return 1

    show_banner("autonomous")
    print(f"   Command: {Colors.BLUE}{cmd}{Colors.NC}", file=sys.stderr)
    print(f"   Model: {Colors.CYAN}{config.openai_model}{Colors.NC}", file=sys.stderr)
    print(f"   Delay: {config.response_delay}s | Startup: {config.startup_delay}s", file=sys.stderr)
    print(f"\n{Colors.YELLOW}Press Ctrl+C to exit{Colors.NC}", file=sys.stderr)
    print(f"{Colors.MAGENTA}[Status: Starting...]{Colors.NC}\n", file=sys.stderr)

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
    cooldown_seconds = 10  # Wait at least 10 seconds between questions
    response_cooldown_until = 0  # Don't detect questions until this time
    user_typing_until = [0]  # Cooldown after user types (list for mutability)
    current_status = ["Starting..."]  # Current status message (list for mutability)
    last_output_time = [time.time()]  # Track last output for inactivity detection
    inactivity_warned = [False]  # Track if we already warned about inactivity
    inactivity_threshold = 30  # Seconds of no output before warning

    def update_status(new_status: str):
        """Update and display the current status."""
        current_status[0] = new_status
        # Print status to stderr (above the terminal output)
        print(f"\r{Colors.MAGENTA}[Status: {new_status}]{Colors.NC}     ", file=sys.stderr, end='', flush=True)

    def show_cooldown_status():
        """Show cooldown remaining time if in cooldown."""
        if time.time() < response_cooldown_until:
            remaining = int(response_cooldown_until - time.time())
            if remaining > 0:
                update_status(f"Cooldown: {remaining}s remaining")
                return True
        return False

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

            # Update last output time and reset inactivity warning
            last_output_time[0] = time.time()
            inactivity_warned[0] = False

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
                update_status("Listening for questions")
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

            # Check if we're in an interactive menu context
            recent_context = '\n'.join(buffer_lines[-15:]).lower()
            in_menu = ('enter to select' in recent_context or
                      'tab/arrow' in recent_context or
                      'arrow keys' in recent_context or
                      'esc to cancel' in recent_context)

            # For menus, trigger when we see the navigation hint line or certain menu patterns
            clean_lower = clean_line.lower()

            # Check for menu option lines (❯ 1. Yes, etc.)
            has_menu_options = ('1. yes' in recent_context or
                               '❯ 1.' in recent_context or
                               '> 1.' in recent_context or
                               '1.' in recent_context)

            # Check for confirmation question in context
            has_confirm_question = ('do you want to proceed' in recent_context or
                                   'do you want to make' in recent_context or
                                   'do you want to' in recent_context)

            # Menu trigger conditions - trigger on last menu item or esc hint
            menu_trigger = False
            if in_menu:
                menu_trigger = ('enter to select' in clean_lower or
                               'esc to cancel' in clean_lower)
            # Trigger when we see "Esc to cancel" or last menu option with confirmation context
            if has_menu_options and has_confirm_question:
                if ('esc to' in clean_lower or
                    'type here to tell' in clean_lower or
                    '3.' in clean_lower or
                    '4.' in clean_lower):
                    menu_trigger = True

            # Check response cooldown - BUT allow menus to bypass cooldown
            if time.time() < response_cooldown_until and not menu_trigger:
                remaining = int(response_cooldown_until - time.time())
                if remaining > 0:
                    update_status(f"Cooldown: {remaining}s")
                log_to_file(f"SKIP (response cooldown): {clean_line[:50]}")
                continue

            # Check cooldown between questions (shorter for menus)
            time_since_last = time.time() - last_question_time
            menu_cooldown = 3  # Only 3 seconds for menus
            if time_since_last < (menu_cooldown if menu_trigger else cooldown_seconds):
                continue

            # Check for questions (only after startup delay)
            # If we're in menu context, ONLY respond to menu_trigger, not is_question
            should_respond = False
            if listening_started:
                if menu_trigger:
                    should_respond = True
                    log_to_file(f"MENU DETECTED: {clean_line}")
                elif not (has_menu_options or has_confirm_question or in_menu):
                    # Only check is_question if we're NOT in a menu context
                    if is_question(clean_line):
                        should_respond = True
                        log_to_file(f"QUESTION: {clean_line}")

            if should_respond:
                last_question_time = time.time()
                # Run in background thread to not block
                threading.Thread(
                    target=respond_to_question,
                    args=(clean_line, list(buffer_lines), config, master_fd),
                    daemon=True
                ).start()

    def is_interactive_menu(context: list) -> bool:
        """Check if we're in an interactive menu context."""
        recent = '\n'.join(context[-15:]).lower()
        return ('enter to select' in recent or
                'tab/arrow' in recent or
                'arrow keys' in recent or
                'esc to cancel' in recent)

    def clean_context_for_ai(lines: list) -> str:
        """Clean context lines for sending to AI."""
        seen = set()
        cleaned = []

        for line in lines:
            # Extra cleaning for AI context
            line = clean_ansi(line)
            stripped = line.strip()

            # Remove lines that are just control sequences or empty
            if not stripped:
                continue

            # Skip UI noise patterns
            skip_patterns = [
                '─', '━', '═',  # Horizontal lines
                '>', '·', '⎿', '⏺', '✽', '✻', '✶', '✳', '✢',  # Status symbols
                'ctrl-g to edit',
                'esc to interrupt',
                '? for shortcuts',
            ]
            if any(p in stripped for p in skip_patterns) and len(stripped) < 80:
                continue

            # Skip lines that are mostly dashes/boxes
            if len(stripped) > 10 and stripped.count('─') > len(stripped) * 0.5:
                continue

            # Normalize for deduplication (remove spinner chars at start)
            normalized = stripped.lstrip('·✽✻✶✳✢⏺☐☒☑✓✔ ')

            # Skip if we've seen this content before
            if normalized in seen:
                continue
            seen.add(normalized)

            cleaned.append(stripped)

        return '\n'.join(cleaned)

    def get_menu_prompt(context_lines: list) -> str:
        """Build a prompt for AI to choose from menu options."""
        # Get recent lines that contain the menu
        recent = context_lines[-20:]
        menu_text = clean_context_for_ai(recent)

        return f"""You are looking at an interactive menu in a terminal.
Based on the context, choose the best option by responding with ONLY the number (1, 2, 3, etc.) or press Enter for the default.

MENU:
{menu_text}

RULES:
1. Respond with ONLY a single number (1, 2, 3, etc.) or "enter" for default
2. Choose the most sensible/recommended option
3. If there's a "(Recommended)" option, prefer that
4. For yes/no confirmations, choose "Yes" (usually option 1)
5. Do NOT explain your choice, just respond with the number

Your choice (number only):"""

    def respond_to_question(question: str, context_lines: list, cfg: Config, fd: int):
        """Get AI response and send it."""
        nonlocal last_response_lines, response_cooldown_until

        # Check if this is an interactive menu
        if is_interactive_menu(context_lines):
            print(f"\n{Colors.CYAN}Interactive menu detected{Colors.NC}", file=sys.stderr)
            print(f"{Colors.YELLOW}   Consulting AI advisor for selection...{Colors.NC}", file=sys.stderr)
            update_status("Selecting menu option...")

            # Ask AI to choose from menu
            menu_prompt = get_menu_prompt(context_lines)

            # Call ChatGPT with menu-specific prompt
            if requests is None or not cfg.openai_api_key:
                choice = "1"  # Default to first option
            else:
                try:
                    payload = {
                        "model": cfg.openai_model,
                        "messages": [
                            {"role": "user", "content": menu_prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 10
                    }
                    resp = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {cfg.openai_api_key}"
                        },
                        json=payload,
                        timeout=15
                    )
                    resp.raise_for_status()
                    choice = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "1").strip()
                except Exception:
                    choice = "1"

            # Clean up choice - extract just the number
            choice_clean = ''.join(c for c in choice if c.isdigit())
            if not choice_clean:
                choice_clean = ""  # Will just press Enter

            print(f"{Colors.GREEN}AI chose:{Colors.NC} {choice_clean if choice_clean else 'Enter (default)'}", file=sys.stderr)
            log_to_file(f"MENU CHOICE: {choice_clean if choice_clean else 'Enter'}")
            play_notification_sound()

            time.sleep(cfg.response_delay)
            response_cooldown_until = time.time() + 15

            if fd:
                if choice_clean:
                    # Type the number
                    os.write(fd, choice_clean.encode())
                    time.sleep(0.1)
                # Press Enter
                os.write(fd, b'\r')
            update_status("Listening for questions")
            return

        print(f"\n{Colors.CYAN}Question detected:{Colors.NC} {question}", file=sys.stderr)
        print(f"{Colors.YELLOW}   Consulting AI advisor...{Colors.NC}", file=sys.stderr)
        update_status("Asking AI advisor...")

        context = clean_context_for_ai(context_lines[-100:])
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
        play_notification_sound()

        # Wait before responding
        time.sleep(cfg.response_delay)

        # Set cooldown - don't detect questions for 10 seconds after sending response
        response_cooldown_until = time.time() + 10

        # Send response to the PTY
        if fd:
            update_status("Typing response...")
            # Type response character by character with small delay
            for char in response:
                os.write(fd, char.encode())
                time.sleep(0.01)  # 10ms delay between chars
            # Send Enter key (try multiple approaches)
            time.sleep(0.1)
            os.write(fd, b'\r')  # Carriage return
            time.sleep(0.05)
            os.write(fd, b'\n')  # Newline
            update_status("Listening for questions")

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

                    # Check for inactivity - warn user to check screen
                    if listening_started and not inactivity_warned[0]:
                        time_since_output = time.time() - last_output_time[0]
                        if time_since_output >= inactivity_threshold:
                            print(f"\n{Colors.YELLOW}[!] No output for {int(time_since_output)}s - check screen for questions/prompts{Colors.NC}", file=sys.stderr)
                            update_status("Check screen - possible question waiting")
                            play_notification_sound()
                            inactivity_warned[0] = True
                            log_to_file(f"INACTIVITY WARNING: {int(time_since_output)}s")

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
    """Watch command output and detect questions (beep only, no AI)."""
    # Windows doesn't support watching interactive CLI programs properly
    if IS_WINDOWS:
        print(f"{Colors.RED}Error: Watch mode is not fully supported on Windows{Colors.NC}")
        print("Windows cannot capture output from interactive CLI programs like Claude.")
        print(f"\n{Colors.YELLOW}Workaround:{Colors.NC} Run Claude directly and use Hansel for other tasks:")
        print(f"  - {Colors.CYAN}hansel config{Colors.NC}  - Configure settings")
        print(f"  - {Colors.CYAN}hansel ask \"your question\"{Colors.NC}  - Ask AI advisor directly")
        print(f"  - {Colors.CYAN}hansel status{Colors.NC}  - Show status")
        print(f"\n{Colors.YELLOW}For full autonomous mode, use macOS or Linux.{Colors.NC}")
        return 1

    show_banner("watch")
    print(f"   Command: {Colors.BLUE}{cmd}{Colors.NC}", file=sys.stderr)
    print(f"   Startup delay: {config.startup_delay}s", file=sys.stderr)
    print(f"\n{Colors.YELLOW}Press Ctrl+C to exit{Colors.NC}\n", file=sys.stderr)

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(BUFFER_FILE, 'a') as f:
        f.write("=" * 40 + '\n')
        f.write(f"[{timestamp}] $ {cmd}\n")
        f.write("=" * 40 + '\n')

    buffer_lines = []
    start_time = time.time()
    listening_started = False

    try:
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
                play_notification_sound()

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

    claude          Quick mode - just detect questions and beep (no AI)
                    Example: hansel claude

    watch <cmd>     Watch mode - detects questions and beeps
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

    elif command == 'claude':
        # Shortcut: hansel claude = hansel watch claude (just detect questions and beep)
        return watch_command('claude', config)

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
