"""Unit tests for headless git operations in cli/lib/gitops.py.

Tests headless_git_pull and headless_git_commit_and_push methods
which are used by headless mode for non-interactive git operations.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
"""

import subprocess
import sys
import os
from unittest.mock import patch, call, MagicMock

import pytest

# Add cli/ to path so gitops.py can resolve its relative imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from lib.gitops import Git


@pytest.fixture(autouse=True)
def mock_logger():
    """Mock the Log class to avoid logger initialization requirement."""
    with patch("lib.gitops.Log") as mock_log:
        yield mock_log


class TestHeadlessGitPull:
    """Tests for Git.headless_git_pull()"""

    @patch("lib.gitops.subprocess.run")
    def test_success(self, mock_run):
        """headless_git_pull succeeds when git pull succeeds (Req 8.1)."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Should not raise SystemExit
        Git.headless_git_pull()

        mock_run.assert_called_once_with(
            ['git', 'pull'], capture_output=True, text=True, check=True
        )

    @patch("lib.gitops.subprocess.run")
    def test_failure_exits_with_error(self, mock_run):
        """headless_git_pull calls sys.exit with error message on failure (Req 8.4)."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=['git', 'pull'],
            stderr="fatal: unable to access remote"
        )

        with pytest.raises(SystemExit) as exc_info:
            Git.headless_git_pull()

        exit_msg = str(exc_info.value)
        assert "git pull failed" in exit_msg
        assert "fatal: unable to access remote" in exit_msg


class TestHeadlessGitCommitAndPush:
    """Tests for Git.headless_git_commit_and_push()"""

    @patch("lib.gitops.subprocess.run")
    def test_success_with_changes(self, mock_run):
        """headless_git_commit_and_push commits and pushes when changes exist (Req 8.2)."""
        def side_effect(cmd, **kwargs):
            result = MagicMock()
            if cmd == ['git', 'diff', '--cached', '--quiet']:
                # returncode=1 means there ARE changes staged
                result.returncode = 1
                return result
            # All other commands succeed
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = side_effect

        # Should not raise SystemExit
        Git.headless_git_commit_and_push("test commit message")

        # Verify correct git commands were called in order
        expected_calls = [
            call(['git', 'add', '.'], check=True, capture_output=True, text=True),
            call(['git', 'diff', '--cached', '--quiet'], capture_output=True),
            call(['git', 'commit', '-m', 'test commit message'], check=True, capture_output=True, text=True),
            call(['git', 'push'], check=True, capture_output=True, text=True),
        ]
        mock_run.assert_has_calls(expected_calls)

    @patch("lib.gitops.subprocess.run")
    def test_no_changes_skips_commit_and_push(self, mock_run):
        """headless_git_commit_and_push skips commit/push when no changes (Req 8.3)."""
        def side_effect(cmd, **kwargs):
            result = MagicMock()
            if cmd == ['git', 'diff', '--cached', '--quiet']:
                # returncode=0 means NO changes staged
                result.returncode = 0
                return result
            # git add succeeds
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = side_effect

        # Should not raise SystemExit
        Git.headless_git_commit_and_push("test commit message")

        # Verify git add and diff were called, but NOT commit or push
        calls = mock_run.call_args_list
        commands_called = [c[0][0] for c in calls]
        assert ['git', 'add', '.'] in commands_called
        assert ['git', 'diff', '--cached', '--quiet'] in commands_called
        assert ['git', 'commit', '-m', 'test commit message'] not in commands_called
        assert ['git', 'push'] not in commands_called

    @patch("lib.gitops.subprocess.run")
    def test_push_failure_exits_with_error(self, mock_run):
        """headless_git_commit_and_push calls sys.exit when push fails (Req 8.5)."""
        def side_effect(cmd, **kwargs):
            if cmd == ['git', 'diff', '--cached', '--quiet']:
                result = MagicMock()
                result.returncode = 1  # changes exist
                return result
            if cmd == ['git', 'push']:
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=['git', 'push'],
                    stderr="remote: Permission denied"
                )
            # git add and git commit succeed
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = side_effect

        with pytest.raises(SystemExit) as exc_info:
            Git.headless_git_commit_and_push("test commit message")

        exit_msg = str(exc_info.value)
        assert "push" in exit_msg
        assert "failed" in exit_msg

    @patch("lib.gitops.subprocess.run")
    def test_git_add_failure_exits_with_error(self, mock_run):
        """headless_git_commit_and_push calls sys.exit when git add fails (Req 8.5)."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=['git', 'add', '.'],
            stderr="error: unable to create file"
        )

        with pytest.raises(SystemExit) as exc_info:
            Git.headless_git_commit_and_push("test commit message")

        exit_msg = str(exc_info.value)
        assert "add" in exit_msg
        assert "failed" in exit_msg
