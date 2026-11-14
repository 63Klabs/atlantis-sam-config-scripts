#!/usr/bin/env python3

"""
Unit tests for GitHubUtils.get_repository() method.
Tests the debug logging functionality.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the cli/lib directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from gh_utils import GitHubUtils


class TestGetRepositoryDebugLogging(unittest.TestCase):
    """Tests for get_repository debug logging."""

    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.Log.info')
    def test_debug_log_called_before_gh_repo_view(self, mock_log_info, mock_subprocess_run):
        """Test that Log.info is called with the correct message before gh repo view."""
        # Arrange
        repo_name = "owner/test-repo"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "name": "test-repo",
            "nameWithOwner": "owner/test-repo",
            "owner": {"login": "owner"},
            "repositoryTopics": {"nodes": []},
            "sshUrl": "git@github.com:owner/test-repo.git",
            "isTemplate": False,
            "templateRepository": None,
            "visibility": "PUBLIC",
            "url": "https://github.com/owner/test-repo"
        })
        mock_subprocess_run.return_value = mock_result

        # Act
        result = GitHubUtils.get_repository(repo_name)

        # Assert
        # Verify Log.info was called with the correct message (a second
        # success message is logged after the lookup completes)
        mock_log_info.assert_any_call(f"Calling gh repo view for repository: {repo_name}")
        
        # Verify subprocess.run was called
        mock_subprocess_run.assert_called_once()
        
        # Verify the result is correct
        self.assertTrue(result["exists"])
        self.assertIn("repositoryMetadata", result)

    @patch('gh_utils.subprocess.run')
    @patch('gh_utils.Log.info')
    def test_debug_log_includes_correct_repo_name(self, mock_log_info, mock_subprocess_run):
        """Test that the debug log includes the correct repository name."""
        # Arrange
        repo_name = "different-owner/another-repo"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "name": "another-repo",
            "nameWithOwner": "different-owner/another-repo",
            "owner": {"login": "different-owner"},
            "repositoryTopics": {"nodes": []},
            "sshUrl": "git@github.com:different-owner/another-repo.git",
            "isTemplate": False,
            "templateRepository": None,
            "visibility": "PUBLIC",
            "url": "https://github.com/different-owner/another-repo"
        })
        mock_subprocess_run.return_value = mock_result

        # Act
        result = GitHubUtils.get_repository(repo_name)

        # Assert
        # Get the first logged message (logged before gh repo view runs)
        call_args = mock_log_info.call_args_list[0][0][0]
        
        # Verify the message contains the repository name
        self.assertIn(repo_name, call_args)
        self.assertEqual(call_args, f"Calling gh repo view for repository: {repo_name}")


if __name__ == '__main__':
    unittest.main()
