#!/usr/bin/env python3
"""Unit tests for GitHubUtils.create_repo stderr logging."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path to import lib modules
sys.path.insert(0, str(Path(__file__).parent))

from gh_utils import GitHubUtils


class TestCreateRepoStderrLogging(unittest.TestCase):
    """Test stderr logging in create_repo method."""
    
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_successful_creation_no_logging(self, mock_run, mock_log):
        """Test successful repository creation doesn't trigger error logging."""
        # Setup: Successful repository creation
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        # Execute
        result = GitHubUtils.create_repo('test-repo', private=True, description='Test repo')
        
        # Verify: Success is returned
        self.assertTrue(result)
        
        # Verify: No error logging occurred
        mock_log.error.assert_not_called()
    
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_failure_with_stderr_logs_error(self, mock_run, mock_log):
        """Test that failure with stderr logs the error message."""
        # Setup: Command fails with stderr
        error_message = "repository already exists"
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'gh repo create', stderr=error_message
        )
        
        # Execute and verify exception is raised
        with self.assertRaises(Exception) as context:
            GitHubUtils.create_repo('test-repo', private=True)
        
        # Verify: Error message is logged
        mock_log.error.assert_called_once_with(f"gh repo create stderr: {error_message}")
        
        # Verify: Exception contains stderr
        self.assertIn(error_message, str(context.exception))
    
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_failure_with_none_stderr_logs_placeholder(self, mock_run, mock_log):
        """Test that failure with None stderr logs placeholder message."""
        # Setup: Command fails with None stderr
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'gh repo create', stderr=None
        )
        
        # Execute and verify exception is raised
        with self.assertRaises(Exception) as context:
            GitHubUtils.create_repo('test-repo', private=True)
        
        # Verify: Placeholder is logged when stderr is None
        mock_log.error.assert_called_once_with("gh repo create stderr: (no stderr)")
        
        # Verify: Exception contains "None"
        self.assertIn("None", str(context.exception))
    
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_failure_with_empty_stderr_logs_placeholder(self, mock_run, mock_log):
        """Test that failure with empty stderr logs placeholder (empty string is falsy)."""
        # Setup: Command fails with empty stderr
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'gh repo create', stderr=""
        )
        
        # Execute and verify exception is raised
        with self.assertRaises(Exception) as context:
            GitHubUtils.create_repo('test-repo', private=True)
        
        # Verify: Placeholder is logged when stderr is empty (empty string is falsy)
        mock_log.error.assert_called_once_with("gh repo create stderr: (no stderr)")
        
        # Verify: Exception is raised
        self.assertIn("Failed to create repository", str(context.exception))
    
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_exception_message_unchanged(self, mock_run, mock_log):
        """Test that user-facing exception message remains unchanged."""
        # Setup: Command fails with stderr
        error_message = "authentication required"
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'gh repo create', stderr=error_message
        )
        
        # Execute and verify exception message format
        with self.assertRaises(Exception) as context:
            GitHubUtils.create_repo('test-repo')
        
        # Verify: Exception message follows expected format
        expected_message = f"Failed to create repository: {error_message}"
        self.assertEqual(str(context.exception), expected_message)
    
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_command_options_passed_correctly(self, mock_run, mock_log):
        """Test that command options are correctly passed to subprocess."""
        # Setup: Successful creation
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        # Execute with various options
        GitHubUtils.create_repo('my-repo', private=False, description='Public repo')
        
        # Verify: subprocess.run was called with correct command
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args[0], "gh")
        self.assertEqual(call_args[1], "repo")
        self.assertEqual(call_args[2], "create")
        self.assertEqual(call_args[3], "my-repo")
        self.assertIn("--public", call_args)
        self.assertIn("--description", call_args)
        self.assertIn("Public repo", call_args)


if __name__ == '__main__':
    unittest.main()
