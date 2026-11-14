"""Tests for the GitHub seeding-failure cleanup logic in cli/create_repo.py.

Covers ``RepositoryCreator._handle_github_seeding_failure()`` (prompt or
auto-delete) and ``RepositoryCreator._delete_github_repository()``
(best-effort ``gh repo delete``). Nothing here calls GitHub, AWS, or the
network: ``subprocess.run``, the prompt, ``Log``, and ``click.echo`` are
all mocked.

Feature: issue-creating-github-repository-error-getting
"""

import subprocess
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import click
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import create_repo
from create_repo import RepositoryCreator


REPO_NAME = "acme/test-repo"
EXPECTED_DELETE_COMMAND = ["gh", "repo", "delete", REPO_NAME, "--yes"]


def _make_creator(cleanup_on_failure=False):
    """Build a RepositoryCreator without running ``__init__``.

    ``__init__`` sets up an AWS session and settings, which the cleanup
    methods do not use. They read only ``repo_name`` and
    ``cleanup_on_failure``.

    Args:
        cleanup_on_failure (bool): Value for the ``--cleanup-on-failure`` flag.

    Returns:
        RepositoryCreator: Minimally initialized instance.
    """
    creator = object.__new__(RepositoryCreator)
    creator.repo_name = REPO_NAME
    creator.cleanup_on_failure = cleanup_on_failure
    return creator


@pytest.fixture
def mocks():
    """Patch the prompt, subprocess.run, Log, and click.echo.

    Yields:
        SimpleNamespace-like object with ``prompt``, ``run``, ``log`` and
        ``echo`` mocks.
    """
    with mock.patch.object(create_repo.Colorize, "prompt") as prompt, \
            mock.patch.object(create_repo.subprocess, "run") as run, \
            mock.patch.object(create_repo, "Log") as log, \
            mock.patch.object(create_repo.click, "echo") as echo:
        yield MagicMock(prompt=prompt, run=run, log=log, echo=echo)


class TestCleanupPrompt:
    """Cleanup prompt and auto-delete behavior after GitHub seeding fails."""

    def test_user_confirms_deletion(self, mocks):
        """Answering 'y' runs ``gh repo delete <name> --yes``."""
        mocks.prompt.return_value = "y"
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.prompt.assert_called_once()
        assert mocks.prompt.call_args.args[1] == "N"
        mocks.run.assert_called_once()
        assert mocks.run.call_args.args[0] == EXPECTED_DELETE_COMMAND

    def test_user_confirms_deletion_uppercase_y(self, mocks):
        """Answering 'Y' also deletes the repository."""
        mocks.prompt.return_value = "Y"
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.run.assert_called_once()
        assert mocks.run.call_args.args[0] == EXPECTED_DELETE_COMMAND

    def test_user_declines_deletion_lowercase_n(self, mocks):
        """Answering 'n' keeps the repository."""
        mocks.prompt.return_value = "n"
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.prompt.assert_called_once()
        mocks.run.assert_not_called()

    def test_user_declines_deletion_uppercase_n(self, mocks):
        """Answering 'N' keeps the repository."""
        mocks.prompt.return_value = "N"
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.prompt.assert_called_once()
        mocks.run.assert_not_called()

    @pytest.mark.parametrize("response", ["", "N", "   "])
    def test_user_declines_deletion_default(self, mocks, response):
        """Pressing Enter (empty or default 'N' response) keeps the repository."""
        mocks.prompt.return_value = response
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.run.assert_not_called()
        # The manual deletion command is shown when the repository is kept.
        echoed = " ".join(str(call.args[0]) for call in mocks.echo.call_args_list)
        assert f"gh repo delete {REPO_NAME}" in echoed

    def test_auto_delete_with_flag(self, mocks):
        """With ``cleanup_on_failure`` True the repo is deleted and no prompt is shown."""
        creator = _make_creator(cleanup_on_failure=True)

        creator._handle_github_seeding_failure()

        mocks.prompt.assert_not_called()
        mocks.run.assert_called_once()
        assert mocks.run.call_args.args[0] == EXPECTED_DELETE_COMMAND

    def test_deletion_failure_handled_gracefully(self, mocks):
        """A failing ``gh repo delete`` is logged and does not raise."""
        mocks.run.side_effect = subprocess.CalledProcessError(
            1, EXPECTED_DELETE_COMMAND, stderr="HTTP 403: forbidden"
        )
        creator = _make_creator(cleanup_on_failure=True)

        creator._handle_github_seeding_failure()  # must not raise

        mocks.run.assert_called_once()
        mocks.log.error.assert_called()
        logged = " ".join(str(call.args[0]) for call in mocks.log.error.call_args_list)
        assert "HTTP 403: forbidden" in logged

    def test_deletion_failure_after_prompt_handled_gracefully(self, mocks):
        """A failing delete after the user answers 'y' does not raise."""
        mocks.prompt.return_value = "y"
        mocks.run.side_effect = subprocess.CalledProcessError(
            1, EXPECTED_DELETE_COMMAND, stderr=None
        )
        creator = _make_creator()

        creator._handle_github_seeding_failure()  # must not raise

        mocks.log.error.assert_called()

    def test_eoferror_defaults_to_no(self, mocks):
        """EOFError (non-interactive) keeps the repository and logs a warning."""
        mocks.prompt.side_effect = EOFError()
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.run.assert_not_called()
        mocks.log.warning.assert_called_once()
        assert "defaulting to 'N'" in mocks.log.warning.call_args.args[0]

    def test_abort_defaults_to_no(self, mocks):
        """click Abort (e.g. Ctrl+C at the prompt) keeps the repository and logs a warning."""
        mocks.prompt.side_effect = click.exceptions.Abort()
        creator = _make_creator()

        creator._handle_github_seeding_failure()

        mocks.run.assert_not_called()
        mocks.log.warning.assert_called_once()
