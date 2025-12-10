#!/usr/bin/env python3
"""
Hansel - Unit Tests
"""

import os
import sys
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import hansel

class TestColors:
    """ANSI color codes for test output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'

class HanselTestCase(unittest.TestCase):
    """Base test case with setup/teardown for Hansel tests."""

    def setUp(self):
        """Set up test fixtures."""
        # Backup existing config
        self.original_hansel_dir = Path.home() / ".hansel"
        self.backup_dir = None

        if self.original_hansel_dir.exists():
            self.backup_dir = Path(tempfile.mkdtemp())
            shutil.move(str(self.original_hansel_dir), str(self.backup_dir / ".hansel"))

        # Create fresh test directory
        self.original_hansel_dir.mkdir(parents=True, exist_ok=True)

        # Store original env vars
        self.original_env = {
            'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY'),
            'OPENAI_MODEL': os.environ.get('OPENAI_MODEL'),
            'RESPONSE_DELAY': os.environ.get('RESPONSE_DELAY'),
        }

        # Clear env vars for tests
        for key in self.original_env:
            if key in os.environ:
                del os.environ[key]

    def tearDown(self):
        """Tear down test fixtures."""
        # Remove test directory
        if self.original_hansel_dir.exists():
            shutil.rmtree(self.original_hansel_dir)

        # Restore backup
        if self.backup_dir and (self.backup_dir / ".hansel").exists():
            shutil.move(str(self.backup_dir / ".hansel"), str(self.original_hansel_dir))
            shutil.rmtree(self.backup_dir)

        # Restore env vars
        for key, value in self.original_env.items():
            if value is not None:
                os.environ[key] = value
            elif key in os.environ:
                del os.environ[key]


class TestQuestionDetection(HanselTestCase):
    """Tests for question detection logic."""

    def test_question_mark_ending(self):
        """Lines ending with ? should be detected as questions."""
        self.assertTrue(hansel.is_question("Should I use PostgreSQL?"))
        self.assertTrue(hansel.is_question("What do you think?"))
        self.assertTrue(hansel.is_question("Is this correct?  "))

    def test_would_you_pattern(self):
        """'Would you' patterns should be detected."""
        self.assertTrue(hansel.is_question("Would you like me to proceed?"))
        self.assertTrue(hansel.is_question("Would you prefer option A or B?"))

    def test_do_you_pattern(self):
        """'Do you' patterns should be detected."""
        self.assertTrue(hansel.is_question("Do you want me to continue?"))
        self.assertTrue(hansel.is_question("Do you have any preferences?"))

    def test_should_i_pattern(self):
        """'Should I' patterns should be detected."""
        self.assertTrue(hansel.is_question("Should I use Express or Fastify?"))
        self.assertTrue(hansel.is_question("Should I create a new file?"))

    def test_what_how_which_patterns(self):
        """What/How/Which patterns should be detected."""
        self.assertTrue(hansel.is_question("What framework should we use?"))
        self.assertTrue(hansel.is_question("How should I structure this?"))
        self.assertTrue(hansel.is_question("Which option is better?"))

    def test_proceed_continue_patterns(self):
        """Proceed/continue patterns should be detected."""
        self.assertTrue(hansel.is_question("Shall I proceed with this?"))
        self.assertTrue(hansel.is_question("Should I continue with the implementation?"))

    def test_skip_code_lines(self):
        """Code lines should not be detected as questions."""
        self.assertFalse(hansel.is_question("# What is this comment?"))
        self.assertFalse(hansel.is_question("// Should I fix this?"))
        self.assertFalse(hansel.is_question("import what_module"))
        self.assertFalse(hansel.is_question("from where import something"))
        self.assertFalse(hansel.is_question("def how_to_do():"))
        self.assertFalse(hansel.is_question("class WhatClass:"))

    def test_skip_diff_lines(self):
        """Diff lines should not be detected as questions."""
        self.assertFalse(hansel.is_question("+ Should this be added?"))
        self.assertFalse(hansel.is_question("- What was removed?"))

    def test_empty_lines(self):
        """Empty lines should not be detected as questions."""
        self.assertFalse(hansel.is_question(""))
        self.assertFalse(hansel.is_question("   "))
        self.assertFalse(hansel.is_question(None))


class TestAnsiCleaning(HanselTestCase):
    """Tests for ANSI code cleaning."""

    def test_remove_color_codes(self):
        """ANSI color codes should be removed."""
        text = "\033[0;31mRed text\033[0m"
        self.assertEqual(hansel.clean_ansi(text), "Red text")

    def test_remove_multiple_codes(self):
        """Multiple ANSI codes should be removed."""
        text = "\033[0;32mGreen\033[0m and \033[0;34mBlue\033[0m"
        self.assertEqual(hansel.clean_ansi(text), "Green and Blue")

    def test_remove_carriage_return(self):
        """Carriage returns should be removed."""
        text = "Line with\r carriage return"
        self.assertEqual(hansel.clean_ansi(text), "Line with carriage return")

    def test_plain_text_unchanged(self):
        """Plain text should remain unchanged."""
        text = "Plain text without codes"
        self.assertEqual(hansel.clean_ansi(text), text)


class TestConfig(HanselTestCase):
    """Tests for configuration management."""

    def test_default_values(self):
        """Config should have default values."""
        config = hansel.Config()
        self.assertEqual(config.openai_model, "gpt-4o")
        self.assertEqual(config.response_delay, 2)

    def test_env_var_override(self):
        """Environment variables should override defaults."""
        os.environ['OPENAI_API_KEY'] = 'test-key'
        os.environ['OPENAI_MODEL'] = 'gpt-3.5-turbo'
        os.environ['RESPONSE_DELAY'] = '5'

        config = hansel.Config()

        self.assertEqual(config.openai_api_key, 'test-key')
        self.assertEqual(config.openai_model, 'gpt-3.5-turbo')
        self.assertEqual(config.response_delay, 5)

    def test_config_file_load(self):
        """Config should load from file."""
        config_content = """# Test config
OPENAI_API_KEY=file-key
OPENAI_MODEL=gpt-4
RESPONSE_DELAY=3
"""
        hansel.ensure_dirs()
        with open(hansel.CONFIG_FILE, 'w') as f:
            f.write(config_content)

        config = hansel.Config()

        self.assertEqual(config.openai_api_key, 'file-key')
        self.assertEqual(config.openai_model, 'gpt-4')
        self.assertEqual(config.response_delay, 3)

    def test_config_save(self):
        """Config should save to file."""
        config = hansel.Config()
        config.openai_api_key = 'saved-key'
        config.openai_model = 'gpt-4-turbo'
        config.response_delay = 10

        hansel.ensure_dirs()
        config.save_config()

        # Read back
        with open(hansel.CONFIG_FILE, 'r') as f:
            content = f.read()

        self.assertIn('OPENAI_API_KEY=saved-key', content)
        self.assertIn('OPENAI_MODEL=gpt-4-turbo', content)
        self.assertIn('RESPONSE_DELAY=10', content)


class TestEnsureDirs(HanselTestCase):
    """Tests for directory setup."""

    def test_creates_hansel_dir(self):
        """ensure_dirs should create .hansel directory."""
        shutil.rmtree(hansel.HANSEL_DIR, ignore_errors=True)
        hansel.ensure_dirs()
        self.assertTrue(hansel.HANSEL_DIR.exists())

    def test_creates_log_dir(self):
        """ensure_dirs should create logs directory."""
        shutil.rmtree(hansel.HANSEL_DIR, ignore_errors=True)
        hansel.ensure_dirs()
        self.assertTrue(hansel.LOG_DIR.exists())

    def test_creates_config_file(self):
        """ensure_dirs should create config.env."""
        shutil.rmtree(hansel.HANSEL_DIR, ignore_errors=True)
        hansel.ensure_dirs()
        self.assertTrue(hansel.CONFIG_FILE.exists())

    def test_creates_system_prompt(self):
        """ensure_dirs should create system_prompt.txt."""
        shutil.rmtree(hansel.HANSEL_DIR, ignore_errors=True)
        hansel.ensure_dirs()
        self.assertTrue(hansel.SYSTEM_PROMPT_FILE.exists())

    def test_system_prompt_content(self):
        """System prompt should contain expected content."""
        shutil.rmtree(hansel.HANSEL_DIR, ignore_errors=True)
        hansel.ensure_dirs()

        with open(hansel.SYSTEM_PROMPT_FILE, 'r') as f:
            content = f.read()

        self.assertIn('system architect', content)
        self.assertIn('CRITICAL RULES', content)


class TestBufferOperations(HanselTestCase):
    """Tests for buffer operations."""

    def test_clear_buffer(self):
        """clear_buffer should remove buffer file."""
        hansel.ensure_dirs()
        hansel.BUFFER_FILE.write_text("test content")

        hansel.clear_buffer()

        self.assertFalse(hansel.BUFFER_FILE.exists())

    def test_show_buffer_empty(self):
        """show_buffer should handle missing file."""
        hansel.ensure_dirs()
        if hansel.BUFFER_FILE.exists():
            hansel.BUFFER_FILE.unlink()

        # Should not raise
        with patch('builtins.print') as mock_print:
            hansel.show_buffer()
            mock_print.assert_called_with("Buffer is empty")

    def test_last_lines(self):
        """last_lines should show correct number of lines."""
        hansel.ensure_dirs()

        lines = [f"Line {i}" for i in range(100)]
        hansel.BUFFER_FILE.write_text('\n'.join(lines) + '\n')

        with patch('builtins.print') as mock_print:
            hansel.last_lines(10)

        # Check that it printed last 10 lines
        calls = [str(call) for call in mock_print.call_args_list]
        self.assertEqual(len(calls), 10)


class TestCLI(HanselTestCase):
    """Tests for CLI interface."""

    def test_help_command(self):
        """help command should work."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'help'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Hansel', result.stdout)
        self.assertIn('auto', result.stdout)
        self.assertIn('watch', result.stdout)

    def test_help_flag(self):
        """--help flag should work."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), '--help'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Hansel', result.stdout)

    def test_h_flag(self):
        """-h flag should work."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), '-h'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Hansel', result.stdout)

    def test_no_args_shows_help(self):
        """No arguments should show help."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py')],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('USAGE', result.stdout)

    def test_unknown_command(self):
        """Unknown command should show error."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'unknowncommand'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('Unknown command', result.stdout)

    def test_status_command(self):
        """status command should work."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'status'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Hansel Status', result.stdout)
        self.assertIn('Directory', result.stdout)
        self.assertIn('Buffer', result.stdout)

    def test_auto_no_command(self):
        """auto without command should show usage."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'auto'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('Usage', result.stdout)

    def test_watch_no_command(self):
        """watch without command should show usage."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'watch'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('Usage', result.stdout)

    def test_ask_no_question(self):
        """ask without question should show usage."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'ask'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('Usage', result.stdout)

    def test_clear_command(self):
        """clear command should work."""
        # Create buffer first
        hansel.ensure_dirs()
        hansel.BUFFER_FILE.write_text("test content")

        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'hansel.py'), 'clear'],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('cleared', result.stdout)


class TestChatGPTIntegration(HanselTestCase):
    """Tests for ChatGPT API integration."""

    def test_no_api_key_error(self):
        """Should return error when no API key."""
        config = hansel.Config()
        config.openai_api_key = ""

        result = hansel.call_chatgpt("test question", "test context", config)
        self.assertIn("Error", result)
        self.assertIn("OPENAI_API_KEY", result)

    @patch('hansel.requests')
    def test_api_call_structure(self, mock_requests):
        """API call should have correct structure."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }
        mock_requests.post.return_value = mock_response

        config = hansel.Config()
        config.openai_api_key = "test-key"
        config.openai_model = "gpt-4o"

        hansel.ensure_dirs()
        result = hansel.call_chatgpt("test question", "test context", config)

        # Verify API was called
        mock_requests.post.assert_called_once()

        # Check URL
        call_args = mock_requests.post.call_args
        self.assertEqual(call_args[0][0], "https://api.openai.com/v1/chat/completions")

        # Check headers
        headers = call_args[1]['headers']
        self.assertIn("Authorization", headers)
        self.assertIn("test-key", headers["Authorization"])


def run_tests():
    """Run all tests with custom output."""
    print(f"{TestColors.CYAN}Hansel Unit Tests (Python){TestColors.NC}")
    print("=" * 40)

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestAnsiCleaning))
    suite.addTests(loader.loadTestsFromTestCase(TestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestEnsureDirs))
    suite.addTests(loader.loadTestsFromTestCase(TestBufferOperations))
    suite.addTests(loader.loadTestsFromTestCase(TestCLI))
    suite.addTests(loader.loadTestsFromTestCase(TestChatGPTIntegration))

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print()
    print("=" * 40)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    print(f"Results: {TestColors.GREEN}{passed} passed{TestColors.NC}, {TestColors.RED}{failed} failed{TestColors.NC}")

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
