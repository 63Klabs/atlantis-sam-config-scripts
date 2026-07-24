"""Unit tests for the GitHub dev-to-test merge path.

Covers two layers of the GitHub Test_Merge:

- ``GitHubUtils.merge_branches_fast_forward()`` in ``cli/lib/gh_utils.py``,
  verifying it issues the correct ``git`` commands in order with
  ``cwd=git_dir`` and raises when any command fails.
- ``RepositoryCreator._merge_dev_to_test_github()`` in ``cli/create_repo.py``,
  verifying it reuses the seed clone (no second clone), and that a failure is
  handled non-fatally while the reused clone is still cleaned up via
  ``_cleanup_github_clone()``.

Requirements: 5.1, 5.2, 5.4, 5.5
"""

import os
import sys
import subprocess
import tempfile
from unittest.mock import patch, call, MagicMock

import pytest

# Add cli/ to path so gh_utils.py and create_repo.py resolve their imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from lib.gh_utils import GitHubUtils
from create_repo import RepositoryCreator


def _make_github_creator(clone_dir=None, repo_name="owner/my-repo"):
    """Build a RepositoryCreator for the GitHub provider without running __init__.

    ``RepositoryCreator.__init__`` establishes an AWS session and loads
    settings/defaults, which is unrelated to the merge path under test. Using
    ``__new__`` lets these unit tests exercise the merge methods in isolation
    with only the attributes those methods touch.

    Args:
        clone_dir (str, optional): Value for ``_github_clone_dir``. Defaults to None.
        repo_name (str): Repository name in owner/repo form.

    Returns:
        RepositoryCreator: A minimally-initialized instance for the GitHub path.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = repo_name
    creator.provider = 'github'
    creator.profile = None
    creator._github_clone_dir = clone_dir
    creator.test_branch_updated = False
    return creator


# =============================================================================
# GitHubUtils.merge_branches_fast_forward() command-sequence tests (Req 5.2)
# =============================================================================

class TestMergeBranchesFastForward:
    """Tests for GitHubUtils.merge_branches_fast_forward()."""

    @patch("lib.gh_utils.subprocess.run")
    def test_issues_git_commands_in_order_with_cwd(self, mock_run):
        """Issues checkout, merge --ff-only, and push in order with cwd=git_dir."""
        mock_run.return_value = MagicMock(returncode=0)
        git_dir = "/tmp/seed-clone"

        GitHubUtils.merge_branches_fast_forward(
            git_dir, source_branch='dev', dest_branch='test'
        )

        expected_calls = [
            call(["git", "checkout", "test"],
                 cwd=git_dir, check=True, capture_output=True),
            call(["git", "merge", "--ff-only", "dev"],
                 cwd=git_dir, check=True, capture_output=True),
            call(["git", "push", "origin", "test"],
                 cwd=git_dir, check=True, capture_output=True),
        ]
        assert mock_run.call_args_list == expected_calls
        assert mock_run.call_count == 3

    @patch("lib.gh_utils.subprocess.run")
    def test_uses_default_branches(self, mock_run):
        """Defaults merge 'dev' into 'test' when branch args are omitted."""
        mock_run.return_value = MagicMock(returncode=0)
        git_dir = "/tmp/seed-clone"

        GitHubUtils.merge_branches_fast_forward(git_dir)

        commands = [c.args[0] for c in mock_run.call_args_list]
        assert commands == [
            ["git", "checkout", "test"],
            ["git", "merge", "--ff-only", "dev"],
            ["git", "push", "origin", "test"],
        ]

    @patch("lib.gh_utils.subprocess.run")
    def test_custom_branches_are_used(self, mock_run):
        """Custom source/dest branch names are threaded into every command."""
        mock_run.return_value = MagicMock(returncode=0)
        git_dir = "/tmp/seed-clone"

        GitHubUtils.merge_branches_fast_forward(
            git_dir, source_branch='feature', dest_branch='staging'
        )

        commands = [c.args[0] for c in mock_run.call_args_list]
        assert commands == [
            ["git", "checkout", "staging"],
            ["git", "merge", "--ff-only", "feature"],
            ["git", "push", "origin", "staging"],
        ]

    @patch("lib.gh_utils.subprocess.run")
    def test_checkout_failure_raises(self, mock_run):
        """A CalledProcessError from 'git checkout' surfaces as an Exception."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["git", "checkout", "test"],
            output=b"", stderr=b"error: pathspec 'test' did not match"
        )

        with pytest.raises(Exception) as exc_info:
            GitHubUtils.merge_branches_fast_forward("/tmp/seed-clone")

        assert "Error in GitHub CLI command" in str(exc_info.value)

    @patch("lib.gh_utils.subprocess.run")
    def test_merge_failure_raises(self, mock_run):
        """A CalledProcessError from 'git merge --ff-only' surfaces as an Exception."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "merge"]:
                raise subprocess.CalledProcessError(
                    returncode=1, cmd=cmd,
                    output=b"", stderr=b"fatal: Not possible to fast-forward"
                )
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        with pytest.raises(Exception) as exc_info:
            GitHubUtils.merge_branches_fast_forward("/tmp/seed-clone")

        assert "Error in GitHub CLI command" in str(exc_info.value)

    @patch("lib.gh_utils.subprocess.run")
    def test_push_failure_raises(self, mock_run):
        """A CalledProcessError from 'git push' surfaces as an Exception."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "push"]:
                raise subprocess.CalledProcessError(
                    returncode=1, cmd=cmd,
                    output=b"", stderr=b"remote: Permission denied"
                )
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        with pytest.raises(Exception) as exc_info:
            GitHubUtils.merge_branches_fast_forward("/tmp/seed-clone")

        assert "Error in GitHub CLI command" in str(exc_info.value)


# =============================================================================
# RepositoryCreator GitHub merge path tests (Req 5.1, 5.4, 5.5)
# =============================================================================

@patch("create_repo.Log")
class TestRepositoryCreatorGithubMergePath:
    """Tests for RepositoryCreator._merge_dev_to_test_github() and cleanup."""

    @patch("create_repo.GitHubUtils")
    def test_reuses_clone_and_creates_no_second_clone(self, mock_gh, _mock_log):
        """Merge reuses _github_clone_dir and does not create another clone (Req 5.1)."""
        with tempfile.TemporaryDirectory() as clone_dir:
            creator = _make_github_creator(clone_dir=clone_dir)

            creator._merge_dev_to_test_github()

            # The existing clone is reused for the fast-forward merge...
            mock_gh.merge_branches_fast_forward.assert_called_once_with(
                clone_dir, source_branch='dev', dest_branch='test'
            )
            # ...and no additional clone/seed is performed.
            mock_gh.create_init_commit.assert_not_called()
            mock_gh.create_repo.assert_not_called()
            assert creator.test_branch_updated is True

    @patch("create_repo.GitHubUtils")
    def test_failure_is_non_fatal_and_clone_is_cleaned_up(self, mock_gh, _mock_log):
        """A merge failure is handled non-fatally and the clone is still removed (Req 5.4, 5.5)."""
        clone_dir = tempfile.mkdtemp()
        try:
            mock_gh.merge_branches_fast_forward.side_effect = Exception(
                "Error in GitHub CLI command: git merge --ff-only dev"
            )
            creator = _make_github_creator(clone_dir=clone_dir)
            # Avoid AWS calls when building manual merge instructions.
            creator.get_clone_urls = lambda: {'https': 'https://example.com/my-repo.git'}

            # Non-fatal: no exception and no SystemExit escapes the merge method.
            creator._merge_dev_to_test_github()

            assert creator.test_branch_updated is False
            assert os.path.isdir(clone_dir) is True  # not yet cleaned up

            # Cleanup (called from the finally block in create_and_seed_repository)
            creator._cleanup_github_clone()

            assert creator._github_clone_dir is None
            assert os.path.isdir(clone_dir) is False
        finally:
            if os.path.isdir(clone_dir):
                import shutil
                shutil.rmtree(clone_dir, ignore_errors=True)

    @patch("create_repo.GitHubUtils")
    def test_missing_clone_dir_is_non_fatal(self, mock_gh, _mock_log):
        """A missing seed clone dir is handled non-fatally without merging (Req 5.4)."""
        creator = _make_github_creator(clone_dir=None)
        creator.get_clone_urls = lambda: {'https': 'https://example.com/my-repo.git'}

        creator._merge_dev_to_test_github()

        mock_gh.merge_branches_fast_forward.assert_not_called()
        assert creator.test_branch_updated is False

    def test_cleanup_removes_directory_and_resets_attribute(self, _mock_log):
        """_cleanup_github_clone removes the clone and resets the attribute (Req 5.5)."""
        clone_dir = tempfile.mkdtemp()
        creator = _make_github_creator(clone_dir=clone_dir)

        assert os.path.isdir(clone_dir) is True
        creator._cleanup_github_clone()

        assert creator._github_clone_dir is None
        assert os.path.isdir(clone_dir) is False

    def test_cleanup_is_noop_when_no_clone(self, _mock_log):
        """_cleanup_github_clone is a no-op when no clone was created (CodeCommit path)."""
        creator = _make_github_creator(clone_dir=None)

        # Should not raise even though there is nothing to clean up.
        creator._cleanup_github_clone()

        assert creator._github_clone_dir is None
