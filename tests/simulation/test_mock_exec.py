"""Tests for Mock Process Executor."""

import os
import sys

# Ensure we import from the local project, not system packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import unittest
import time

from pulldb.simulation.adapters.mock_exec import MockProcessExecutor
from pulldb.simulation.core.state import get_simulation_state


class TestMockProcessExecutor(unittest.TestCase):
    def setUp(self):
        self.state = get_simulation_state()
        self.state.clear()
        # Use fast_mode=False to test delays
        self.executor = MockProcessExecutor(fast_mode=False)
        self.executor.default_config.delay_seconds = 0.01

    def test_run_command(self):
        start = time.time()
        exit_code = self.executor.run_command(["echo", "hello"])
        duration = time.time() - start
        
        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(duration, 0.01)

    def test_fast_mode_skips_sleep(self):
        """fast_mode=True should skip delays."""
        fast_executor = MockProcessExecutor(fast_mode=True)
        fast_executor.default_config.delay_seconds = 1.0  # Would be very slow
        
        start = time.time()
        exit_code = fast_executor.run_command(["echo", "hello"])
        duration = time.time() - start
        
        self.assertEqual(exit_code, 0)
        self.assertLess(duration, 0.5)  # Should be near-instant

    def test_run_command_streaming(self):
        output = []
        def callback(line):
            output.append(line)
            
        from pulldb.simulation.adapters.mock_exec import MockCommandConfig
        self.executor.configure_command(
            "myloader", 
            MockCommandConfig(stdout="myloader: starting restore\nmyloader: finished")
        )

        result = self.executor.run_command_streaming(
            ["myloader", "--directory", "backup"],
            callback
        )
        
        self.assertEqual(result.exit_code, 0)
        self.assertIn("myloader: starting restore", output)
        self.assertIn("myloader: finished", output)
