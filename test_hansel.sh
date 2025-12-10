#!/bin/bash

# =============================================================================
# 🍞 Hansel - Unit Tests
# =============================================================================

# Don't use set -e as we handle errors manually

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANSEL="${SCRIPT_DIR}/hansel"
TEST_DIR="${SCRIPT_DIR}/.test_hansel"
PASSED=0
FAILED=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# -----------------------------------------------------------------------------
# Test Helpers
# -----------------------------------------------------------------------------
setup() {
    # Backup existing config
    if [[ -d "${HOME}/.hansel" ]]; then
        mv "${HOME}/.hansel" "${HOME}/.hansel.backup.$$"
    fi
    mkdir -p "${TEST_DIR}"
}

teardown() {
    # Restore original config
    rm -rf "${HOME}/.hansel"
    if [[ -d "${HOME}/.hansel.backup.$$" ]]; then
        mv "${HOME}/.hansel.backup.$$" "${HOME}/.hansel"
    fi
    rm -rf "${TEST_DIR}"
}

pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    echo -e "  ${YELLOW}$2${NC}"
    ((FAILED++))
}

assert_exit_code() {
    local expected="$1"
    local actual="$2"
    local msg="$3"
    if [[ "$actual" -eq "$expected" ]]; then
        pass "$msg"
    else
        fail "$msg" "Expected exit code $expected, got $actual"
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local msg="$3"
    if echo "$haystack" | grep -q "$needle"; then
        pass "$msg"
    else
        fail "$msg" "Output does not contain: $needle"
    fi
}

assert_file_exists() {
    local file="$1"
    local msg="$2"
    if [[ -f "$file" ]]; then
        pass "$msg"
    else
        fail "$msg" "File does not exist: $file"
    fi
}

assert_dir_exists() {
    local dir="$1"
    local msg="$2"
    if [[ -d "$dir" ]]; then
        pass "$msg"
    else
        fail "$msg" "Directory does not exist: $dir"
    fi
}

# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

test_help() {
    echo -e "\n${CYAN}Testing: help command${NC}"

    local output
    output=$("$HANSEL" help 2>&1)
    local exit_code=$?

    assert_exit_code 0 $exit_code "help exits with 0"
    assert_contains "$output" "Hansel" "help shows Hansel name"
    assert_contains "$output" "auto" "help shows auto command"
    assert_contains "$output" "watch" "help shows watch command"
    assert_contains "$output" "config" "help shows config command"
    assert_contains "$output" "USAGE" "help shows USAGE section"
}

test_help_flags() {
    echo -e "\n${CYAN}Testing: help flags${NC}"

    local output1 output2
    output1=$("$HANSEL" --help 2>&1)
    output2=$("$HANSEL" -h 2>&1)

    assert_contains "$output1" "Hansel" "--help works"
    assert_contains "$output2" "Hansel" "-h works"
}

test_no_args() {
    echo -e "\n${CYAN}Testing: no arguments${NC}"

    local output
    output=$("$HANSEL" 2>&1)

    assert_contains "$output" "USAGE" "no args shows help"
}

test_unknown_command() {
    echo -e "\n${CYAN}Testing: unknown command${NC}"

    local output
    output=$("$HANSEL" unknowncommand 2>&1) || true

    assert_contains "$output" "Unknown command" "unknown command shows error"
}

test_status() {
    echo -e "\n${CYAN}Testing: status command${NC}"

    local output
    output=$("$HANSEL" status 2>&1)
    local exit_code=$?

    assert_exit_code 0 $exit_code "status exits with 0"
    assert_contains "$output" "Hansel Status" "status shows title"
    assert_contains "$output" "Directory" "status shows directory"
    assert_contains "$output" "Buffer" "status shows buffer info"
}

test_config_creates_dirs() {
    echo -e "\n${CYAN}Testing: config creates directories${NC}"

    # Run status to trigger ensure_dirs
    "$HANSEL" status > /dev/null 2>&1

    assert_dir_exists "${HOME}/.hansel" "config creates .hansel directory"
    assert_dir_exists "${HOME}/.hansel/logs" "config creates logs directory"
    assert_file_exists "${HOME}/.hansel/config.env" "config creates config.env"
    assert_file_exists "${HOME}/.hansel/system_prompt.txt" "config creates system_prompt.txt"
}

test_buffer_empty() {
    echo -e "\n${CYAN}Testing: buffer when empty${NC}"

    local output
    output=$("$HANSEL" buffer 2>&1)

    assert_contains "$output" "empty" "buffer shows empty message"
}

test_clear_buffer() {
    echo -e "\n${CYAN}Testing: clear buffer${NC}"

    # Create a buffer file
    mkdir -p "${HOME}/.hansel"
    echo "test content" > "${HOME}/.hansel/buffer.txt"

    local output
    output=$("$HANSEL" clear 2>&1)

    assert_contains "$output" "cleared" "clear shows confirmation"

    if [[ ! -f "${HOME}/.hansel/buffer.txt" ]]; then
        pass "clear removes buffer file"
    else
        fail "clear removes buffer file" "Buffer file still exists"
    fi
}

test_last_lines() {
    echo -e "\n${CYAN}Testing: last command${NC}"

    # Create buffer with content
    mkdir -p "${HOME}/.hansel"
    for i in {1..100}; do
        echo "Line $i"
    done > "${HOME}/.hansel/buffer.txt"

    local output
    output=$("$HANSEL" last 10 2>&1)

    assert_contains "$output" "Line 100" "last shows last line"
    assert_contains "$output" "Line 91" "last shows 10 lines back"
}

test_auto_no_command() {
    echo -e "\n${CYAN}Testing: auto without command${NC}"

    local output
    output=$("$HANSEL" auto 2>&1) || true

    assert_contains "$output" "Usage" "auto without command shows usage"
}

test_watch_no_command() {
    echo -e "\n${CYAN}Testing: watch without command${NC}"

    local output
    output=$("$HANSEL" watch 2>&1) || true

    assert_contains "$output" "Usage" "watch without command shows usage"
}

test_ask_no_question() {
    echo -e "\n${CYAN}Testing: ask without question${NC}"

    local output
    output=$("$HANSEL" ask 2>&1) || true

    assert_contains "$output" "Usage" "ask without question shows usage"
}

test_auto_no_api_key() {
    echo -e "\n${CYAN}Testing: auto without API key${NC}"

    # Ensure no API key is set
    unset OPENAI_API_KEY
    rm -f "${HOME}/.hansel/config.env"
    mkdir -p "${HOME}/.hansel"
    echo "# empty config" > "${HOME}/.hansel/config.env"

    local output
    output=$("$HANSEL" auto "echo test" 2>&1) || true

    assert_contains "$output" "OPENAI_API_KEY" "auto without key shows error"
}

test_system_prompt_content() {
    echo -e "\n${CYAN}Testing: system prompt content${NC}"

    "$HANSEL" status > /dev/null 2>&1

    local content
    content=$(cat "${HOME}/.hansel/system_prompt.txt" 2>/dev/null)

    assert_contains "$content" "system architect" "system prompt mentions architect"
    assert_contains "$content" "CRITICAL RULES" "system prompt has rules"
}

test_config_env_content() {
    echo -e "\n${CYAN}Testing: config.env content${NC}"

    # Remove and recreate config to get default
    rm -rf "${HOME}/.hansel"
    "$HANSEL" status > /dev/null 2>&1

    local content
    content=$(cat "${HOME}/.hansel/config.env" 2>/dev/null)

    assert_contains "$content" "OPENAI_API_KEY" "config mentions API key"
    assert_contains "$content" "OPENAI_MODEL" "config mentions model"
}

# -----------------------------------------------------------------------------
# Run Tests
# -----------------------------------------------------------------------------

main() {
    echo -e "${CYAN}🍞 Hansel Unit Tests${NC}"
    echo "════════════════════════════════════════"

    setup
    trap teardown EXIT

    test_help
    test_help_flags
    test_no_args
    test_unknown_command
    test_status
    test_config_creates_dirs
    test_buffer_empty
    test_clear_buffer
    test_last_lines
    test_auto_no_command
    test_watch_no_command
    test_ask_no_question
    test_auto_no_api_key
    test_system_prompt_content
    test_config_env_content

    echo ""
    echo "════════════════════════════════════════"
    echo -e "Results: ${GREEN}${PASSED} passed${NC}, ${RED}${FAILED} failed${NC}"

    if [[ $FAILED -gt 0 ]]; then
        exit 1
    fi
}

main "$@"
