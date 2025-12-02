"""Tests for Mock Process Executor."""

import unittest
import time

from pulldb.simulation.adapters.mock_exec import MockProcessExecutor
from pulldb.simulation.core.state import get_simulation_state


class TestMockProcessExecutor(unittest.TestCase):
    def setUp(self):
        self.state = get_simulation_state()
        self.state.clear()
        self.executor = MockProcessExecutor(delay=0.01)

    def test_run_command(self):
        start = time.time()
        exit_code = self.executor.run_command(["echo", "hello"])
        duration = time.time() - start
        
        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(duration, 0.01)

    def test_run_command_streaming(self):
        output = []
        def callback(line):
            output.append(line)
            
        result = self.executor.run_command_streaming(
            ["myloader", "--directory", "backup"],
            callback
        )
        
        self.assertEqual(result.exit_code, 0)
        self.assertIn("myloader: starting restore", output)
        self.assertIn("myloader: finished", output)
