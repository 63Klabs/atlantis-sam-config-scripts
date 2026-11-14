#!/usr/bin/env python3
"""Unit tests for GitHubUtils._retry_gh_command retry loop implementation."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path to import lib modules
sys.path.insert(0, str(Path(__file__).parent))

from gh_utils import GitHubUtils


class TestRetryGhCommandRetryLoop(unittest.TestCase):
    """Test the retry loop with delays [1, 2, 4] seconds."""
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_initial_success_no_retries(self, mock_sleep, mock_run, mock_log):
        """Test that successful initial attempt returns immediately without retries."""
        # Setup: Initial attempt succeeds
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        # Execute
        result = GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'test/repo'])
        
        # Verify: Only called once (initial attempt), no retries
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(mock_sleep.call_count, 0)
        self.assertEqual(result, mock_result)
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_retry_with_delays_1_2_4(self, mock_sleep, mock_run, mock_log):
        """Test that retries use delays [1, 2, 4] seconds."""
        # Setup: Fail initial + 2 retries, succeed on 3rd retry
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error 1'),  # Initial
            subprocess.CalledProcessError(1, 'gh', stderr='error 2'),  # Retry 1
            subprocess.CalledProcessError(1, 'gh', stderr='error 3'),  # Retry 2
            MagicMock(returncode=0)  # Retry 3 (success)
        ]
        
        # Execute
        result = GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'test/repo'], max_retries=3)
        
        # Verify: 1 initial + 3 retries = 4 total calls
        self.assertEqual(mock_run.call_count, 4)
        
        # Verify: 3 sleep calls with delays [1, 2, 4]
        self.assertEqual(mock_sleep.call_count, 3)
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(sleep_calls, [1, 2, 4])
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_all_retries_exhausted_raises_last_error(self, mock_sleep, mock_run, mock_log):
        """Test that after all retries fail, the last error is re-raised."""
        # Setup: All attempts fail
        last_error = subprocess.CalledProcessError(1, 'gh', stderr='final error')
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error 1'),  # Initial
            subprocess.CalledProcessError(1, 'gh', stderr='error 2'),  # Retry 1
            subprocess.CalledProcessError(1, 'gh', stderr='error 3'),  # Retry 2
            last_error  # Retry 3 (final failure)
        ]
        
        # Execute and verify exception
        with self.assertRaises(subprocess.CalledProcessError) as context:
            GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'test/repo'], max_retries=3)
        
        # Verify: The last error is raised
        self.assertEqual(context.exception, last_error)
        self.assertEqual(context.exception.stderr, 'final error')
        
        # Verify: 1 initial + 3 retries = 4 total calls
        self.assertEqual(mock_run.call_count, 4)
        
        # Verify: 3 sleep calls
        self.assertEqual(mock_sleep.call_count, 3)
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_success_on_first_retry(self, mock_sleep, mock_run, mock_log):
        """Test that success on first retry stops further retries."""
        # Setup: Fail initial, succeed on retry 1
        mock_result = MagicMock(returncode=0)
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error 1'),  # Initial
            mock_result  # Retry 1 (success)
        ]
        
        # Execute
        result = GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'test/repo'], max_retries=3)
        
        # Verify: Only 2 calls (initial + 1 retry)
        self.assertEqual(mock_run.call_count, 2)
        
        # Verify: Only 1 sleep call with delay of 1 second
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(mock_sleep.call_args[0][0], 1)
        
        # Verify: Result is returned
        self.assertEqual(result, mock_result)
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_delay_uses_last_value_when_beyond_array(self, mock_sleep, mock_run, mock_log):
        """Test that delays beyond array length use the last array value (4 seconds)."""
        # Setup: Fail many times to exceed delays array length
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error') for _ in range(6)
        ]
        
        # Execute with 5 retries (more than delays array length of 3)
        with self.assertRaises(subprocess.CalledProcessError):
            GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'test/repo'], max_retries=5)
        
        # Verify: 5 sleep calls with delays [1, 2, 4, 4, 4]
        self.assertEqual(mock_sleep.call_count, 5)
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(sleep_calls, [1, 2, 4, 4, 4])
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_retry_logging_format(self, mock_sleep, mock_run, mock_log):
        """Test that retry attempts log with correct INFO-level format."""
        # Setup: Fail initial + 2 retries, succeed on 3rd retry
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error 1'),  # Initial
            subprocess.CalledProcessError(1, 'gh', stderr='error 2'),  # Retry 1
            subprocess.CalledProcessError(1, 'gh', stderr='error 3'),  # Retry 2
            MagicMock(returncode=0)  # Retry 3 (success)
        ]
        
        # Execute
        GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'test/repo'], max_retries=3)
        
        # Verify: Log.info() was called 4 times (3 for retry attempts + 1 for success message)
        info_calls = [call for call in mock_log.info.call_args_list]
        self.assertEqual(len(info_calls), 4)
        
        # Verify: First 3 log messages have the correct retry format
        expected_retry_messages = [
            "Retrying gh command (attempt 1 of 3) after 1 second(s)...",
            "Retrying gh command (attempt 2 of 3) after 2 second(s)...",
            "Retrying gh command (attempt 3 of 3) after 4 second(s)..."
        ]
        
        actual_retry_messages = [call[0][0] for call in info_calls[:3]]
        self.assertEqual(actual_retry_messages, expected_retry_messages)
        
        # Verify: Last log message is the success message
        success_message = info_calls[3][0][0]
        self.assertEqual(success_message, "gh command succeeded on retry attempt 3")
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_error_logging_after_all_retries_exhausted(self, mock_sleep, mock_run, mock_log):
        """Test that ERROR-level log is emitted after all retries are exhausted."""
        # Setup: All attempts fail
        last_error = subprocess.CalledProcessError(1, 'gh', stderr='final error')
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error 1'),  # Initial
            subprocess.CalledProcessError(1, 'gh', stderr='error 2'),  # Retry 1
            subprocess.CalledProcessError(1, 'gh', stderr='error 3'),  # Retry 2
            last_error  # Retry 3 (final failure)
        ]
        
        # Execute and verify exception
        with self.assertRaises(subprocess.CalledProcessError):
            GitHubUtils._retry_gh_command(['gh', 'repo', 'view', 'owner/test-repo'], max_retries=3)
        
        # Verify: Log.error() was called for each failure AND the final summary
        # Initial failure: 2 error calls (command + stderr)
        # Retry 1 failure: 2 error calls (command + stderr)
        # Retry 2 failure: 2 error calls (command + stderr)
        # Retry 3 failure: 2 error calls (command + stderr)
        # Final summary: 1 error call
        # Total: 8 + 1 = 9 error calls
        self.assertEqual(mock_log.error.call_count, 9)
        
        # Get the last error call (the summary)
        last_error_call = mock_log.error.call_args_list[-1]
        last_error_message = last_error_call[0][0]
        
        # Verify: The final error message contains the summary
        self.assertIn("gh command failed after 4 attempts", last_error_message)
        self.assertIn("(1 initial + 3 retries)", last_error_message)
        self.assertIn("for repository: owner/test-repo", last_error_message)
    
    @patch('lib.logger.Log')
    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.time.sleep')
    def test_error_logging_with_unknown_repo_name(self, mock_sleep, mock_run, mock_log):
        """Test that ERROR-level log handles unknown repo name gracefully."""
        # Setup: All attempts fail with a command that doesn't have repo name at index 3
        last_error = subprocess.CalledProcessError(1, 'gh', stderr='final error')
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error 1'),  # Initial
            last_error  # Retry 1 (final failure)
        ]
        
        # Execute with a short command (no repo name at index 3)
        with self.assertRaises(subprocess.CalledProcessError):
            GitHubUtils._retry_gh_command(['gh', 'auth', 'status'], max_retries=1)
        
        # Get the last error call (the summary)
        last_error_call = mock_log.error.call_args_list[-1]
        last_error_message = last_error_call[0][0]
        
        # Verify: The final error message uses "unknown" as fallback
        self.assertIn("for repository: unknown", last_error_message)


if __name__ == '__main__':
    unittest.main()
