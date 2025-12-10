# Hansel

Autonomous Terminal AI Bridge. Watches Claude CLI, detects when Claude asks questions, consults an external AI advisor, and **automatically types the response** back to Claude.

> Like Hansel and Gretel - leave breadcrumbs behind, never lose your way.

## Features

- **Full Autopilot Mode** - Zero human intervention needed
- Acts as system architect advisor for Claude
- Captures all terminal output for context
- Customizable system prompt
- Configurable response delay

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Claude CLI │────▶│   Hansel    │────▶│  AI Advisor │
│  (asks Q)   │     │  (detects)  │     │  (answers)  │
└─────────────┘     └─────────────┘     └─────────────┘
       ▲                                       │
       │                                       │
       └───────────────────────────────────────┘
            (auto-types response back)
```

1. Hansel spawns Claude CLI in a PTY
2. Monitors Claude's output for question patterns ("Should I..?", "How..?", etc.)
3. When Claude asks a question, sends context to AI advisor
4. AI advisor (as system architect) provides answer
5. Answer is **automatically typed** into Claude CLI

## Installation

### Install from PyPI (Recommended)

```bash
# macOS (Homebrew Python)
brew install pipx
pipx install hansel-ai

# Linux / Windows
pip install hansel-ai
```

### Install from Source

```bash
git clone https://github.com/johanfleming/hansel.git
cd hansel
python3 install.py
```

### Requirements

- Python 3.8+
- `requests` (installed automatically with pip)

## Quick Start

```bash
# 1. Configure API key
hansel config

# 2. IMPORTANT: First, trust the project folder in Claude
#    Run claude once in your project directory and accept the trust prompt
cd /path/to/your/project
claude
# Select "Yes, continue" when asked "Do you want to work in this folder?"
# Then exit Claude (Ctrl+C)

# 3. Run Claude with full autopilot
hansel auto claude

# That's it! Hansel will:
# - Watch Claude's output
# - Detect when Claude asks a question
# - Consult AI advisor for the answer
# - Automatically type the response
```

> **Note:** You must trust the project folder in Claude before using Hansel. Otherwise, Claude will show a permission prompt that Hansel cannot automatically handle.

## Usage

### Full Autopilot Mode (Recommended)

```bash
# Just run and watch the magic happen
hansel auto claude

# With custom project prompt
hansel auto "claude --project myapp"
```

### Watch Mode (Manual Responses)

```bash
# Detects questions but doesn't auto-respond
hansel watch claude

# Shows suggested response, you copy/paste
```

### Ask Advisor Directly

```bash
# Uses buffer as context
hansel ask "How should I structure the database?"
```

## Commands

| Command | Description |
|---------|-------------|
| `hansel auto <cmd>` | **Full autopilot** - detects and auto-responds |
| `hansel watch <cmd>` | Watch only - suggests but doesn't type |
| `hansel ask <question>` | Ask AI advisor directly |
| `hansel buffer` | Show full buffer |
| `hansel last [N]` | Show last N lines (default: 50) |
| `hansel clear` | Clear buffer |
| `hansel config` | Configure settings |
| `hansel status` | Show status |
| `hansel uninstall` | Remove Hansel |

## Configuration

### Config File

Located at `~/.hansel/config.env`:

```bash
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o
RESPONSE_DELAY=2  # Seconds to wait before auto-responding
```

### System Prompt

Located at `~/.hansel/system_prompt.txt`. This controls how the AI advisor responds:

```
You are a senior system architect helping Claude implement a software project.

CRITICAL RULES:
1. Give DIRECT, ACTIONABLE answers - no fluff
2. When asked yes/no questions, start with "yes" or "no"
3. Keep responses concise (2-4 sentences max)
...
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | Your OpenAI API key | - |
| `OPENAI_MODEL` | Model to use | `gpt-4o` |
| `RESPONSE_DELAY` | Seconds before auto-responding | `2` |

## File Locations

- Config: `~/.hansel/config.env`
- System Prompt: `~/.hansel/system_prompt.txt`
- Buffer: `~/.hansel/buffer.txt`
- Logs: `~/.hansel/logs/`

## Example Session

```bash
$ hansel auto claude
Hansel Autonomous Mode
   Command: claude
   Model: gpt-4o
   Response delay: 2s

Press Ctrl+C to exit
════════════════════════════════════════

Claude: I'll create a REST API for user management.
        Should I use Express.js or Fastify?

Question detected: Should I use Express.js or Fastify?
   Consulting AI advisor...
Response: Fastify. 2-3x faster than Express, built-in validation,
   better TypeScript support. Use Express only if you need its larger
   ecosystem of middleware.

# Response is automatically typed into Claude!

Claude: Got it, I'll use Fastify. Creating the project structure now...
```

## Tips

### Customize the Advisor

Edit `~/.hansel/system_prompt.txt` to change the advisor's behavior:

```bash
# Open in editor
nano ~/.hansel/system_prompt.txt

# Or during config
hansel config  # Then answer "y" to edit prompt
```

### Response Delay

Adjust how long Hansel waits before responding:

```bash
# In config file
RESPONSE_DELAY=5  # Wait 5 seconds

# Or edit during config
hansel config
```

### Shell Aliases

```bash
# Add to ~/.bashrc or ~/.zshrc
alias ha='hansel auto'
alias hw='hansel watch'

# Usage
ha claude
hw "npm run dev"
```

## License

MIT
