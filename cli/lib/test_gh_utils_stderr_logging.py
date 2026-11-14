#!/usr/bin/env python3
"""Unit tests for stderr logging in GitHubUtils git/gh helper methods.

Covers create_branch_structure, create_init_commit, and
merge_branches_fast_forward.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path to import lib modules
sys.path.insert(0, str(Path(__file__).parent))

from gh_utils import GitHubUtils


def _push_failure(cmd, **kwargs):
    """Fake subprocess.run that fails only for 'git push' commands."""
    if cmd[:2] == ["git", "push"]:
        raise subprocess.CalledProcessError(
            1, cmd, stderr=b"remote: Permission denied"
        )
    return MagicMock(returncode=0)


class TestCreateBranchStructureStderrLogging(unittest.TestCase):
    """Test stderr logging in create_branch_structure method."""

    @patch('gh_utils.shutil.rmtree')
    @patch('gh_utils.os.chdir')
    @patch('gh_utils.tempfile.mkdtemp', return_value='/tmp/fake-branch-dir')
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_failure_logs_command_and_stderr_and_reraises(
            self, mock_run, mock_log, _mock_mkdtemp, _mock_chdir, _mock_rmtree):
        """Failed command and stderr are logged at ERROR level and the error is re-raised."""
        mock_run.side_effect = subprocess.CalledProcessError(
            128, ["gh", "repo", "clone", "owner/repo"], stderr=b"fatal: repository not found"
        )

        with self.assertRaises(subprocess.CalledProcessError):
            GitHubUtils.create_branch_structure("owner/repo", "# readme", "Jane", "jane@example.com")

        mock_log.error.assert_any_call(
            "create_branch_structure command failed: gh repo clone owner/repo"
        )
        mock_log.error.assert_any_call("stderr: fatal: repository not found")

    @patch('gh_utils.shutil.rmtree')
    @patch('gh_utils.os.chdir')
    @patch('gh_utils.tempfile.mkdtemp', return_value='/tmp/fake-branch-dir')
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_cleanup_still_runs_on_failure(
            self, mock_run, _mock_log, _mock_mkdtemp, mock_chdir, mock_rmtree):
        """The finally block still changes directory and removes the temp dir."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["gh", "repo", "clone"], stderr="boom")

        with self.assertRaises(subprocess.CalledProcessError):
            GitHubUtils.create_branch_structure("owner/repo", "# readme", "Jane", "jane@example.com")

        mock_chdir.assert_called_with("/")
        mock_rmtree.assert_called_once_with('/tmp/fake-branch-dir', ignore_errors=True)

    @patch('gh_utils.shutil.rmtree')
    @patch('gh_utils.os.chdir')
    @patch('gh_utils.tempfile.mkdtemp', return_value='/tmp/fake-branch-dir')
    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_none_stderr_and_non_string_command_items_are_handled(
            self, mock_run, mock_log, _mock_mkdtemp, _mock_chdir, _mock_rmtree):
        """Missing stderr logs a placeholder and non-string command items do not break logging."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["git", Path("/tmp/x")], stderr=None
        )

        with self.assertRaises(subprocess.CalledProcessError):
            GitHubUtils.create_branch_structure("owner/repo", "# readme", "Jane", "jane@example.com")

        mock_log.error.assert_any_call("create_branch_structure command failed: git /tmp/x")
        mock_log.error.assert_any_call("stderr: (no stderr)")


class TestCreateInitCommitStderrLogging(unittest.TestCase):
    """Test stderr logging in create_init_commit method."""

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_failure_logs_command_and_stderr(self, mock_run, mock_log):
        """Failed command and stderr are logged at ERROR level."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["git", "push", "origin", "dev"], stderr=b"remote: Permission denied"
        )

        with self.assertRaises(Exception):
            GitHubUtils.create_init_commit([], "owner/repo", "dev", "Jane", "jane@example.com", "/tmp/clone")

        logged = [c.args[0] for c in mock_log.error.call_args_list]
        self.assertIn("git command failed in create_init_commit: git push origin dev", logged)
        self.assertIn("stderr: remote: Permission denied", logged)

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_exception_message_includes_command_and_stderr(self, mock_run, mock_log):
        """The raised Exception includes the command and stderr text."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["gh", "repo", "clone", "owner/repo"], stderr=b"fatal: not found"
        )

        with self.assertRaises(Exception) as context:
            GitHubUtils.create_init_commit([], "owner/repo", "dev", "Jane", "jane@example.com", "/tmp/clone")

        self.assertEqual(
            str(context.exception),
            "Error in GitHub CLI command: gh repo clone owner/repo\nError: fatal: not found"
        )

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_none_stderr_logs_placeholder(self, mock_run, mock_log):
        """Missing stderr logs and raises with the placeholder text."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["git", "add", "."], stderr=None)

        with self.assertRaises(Exception) as context:
            GitHubUtils.create_init_commit([], "owner/repo", "dev", "Jane", "jane@example.com", "/tmp/clone")

        mock_log.error.assert_any_call("stderr: (no stderr)")
        self.assertIn("(no stderr)", str(context.exception))


class TestMergeBranchesFastForwardStderrLogging(unittest.TestCase):
    """Test stderr logging in merge_branches_fast_forward method."""

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_success_does_not_log_errors(self, mock_run, mock_log):
        """A successful merge does not log any errors."""
        mock_run.return_value = MagicMock(returncode=0)

        GitHubUtils.merge_branches_fast_forward("/tmp/clone")

        mock_log.error.assert_not_called()

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_failure_logs_command_and_stderr(self, mock_run, mock_log):
        """Failed command and stderr are logged at ERROR level."""
        mock_run.side_effect = _push_failure

        with self.assertRaises(Exception):
            GitHubUtils.merge_branches_fast_forward("/tmp/clone")

        mock_log.error.assert_any_call(
            "git command failed in merge_branches_fast_forward: git push origin test"
        )
        mock_log.error.assert_any_call("git merge stderr: remote: Permission denied")

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_exception_message_includes_stderr(self, mock_run, mock_log):
        """The raised Exception keeps its prefix and includes the stderr text."""
        mock_run.side_effect = _push_failure

        with self.assertRaises(Exception) as context:
            GitHubUtils.merge_branches_fast_forward("/tmp/clone")

        message = str(context.exception)
        self.assertIn("Error in GitHub CLI command", message)
        self.assertIn("remote: Permission denied", message)

    @patch('gh_utils.Log')
    @patch('gh_utils.subprocess.run')
    def test_none_stderr_logs_placeholder(self, mock_run, mock_log):
        """Missing stderr logs the placeholder and still raises."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["git", "merge", "--ff-only", "dev"], stderr=None
        )

        with self.assertRaises(Exception):
            GitHubUtils.merge_branches_fast_forward("/tmp/clone")

        mock_log.error.assert_any_call("git merge stderr: (no stderr)")


if __name__ == '__main__':
    unittest.main()
