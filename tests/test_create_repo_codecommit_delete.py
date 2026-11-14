"""Tests for the best-effort CodeCommit repository delete in create_repo.py.

Covers ``RepositoryCreator._delete_codecommit_repository()`` and its five
call sites. The helper must never raise, must treat a missing repository as
success, must print the manual delete command when the delete fails, and must
attempt the delete only once per run. At every call site a failing delete must
leave the original error message visible and the exit code at 1.

Nothing here calls AWS, GitHub, or the network: ``codecommit_client``,
``s3_client``, ``Log``, and ``click.echo`` are mocks.

Feature: issue-creating-github-repository-error-getting
"""

import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import botocore.exceptions
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import create_repo
from create_repo import RepositoryCreator


REPO_NAME = "acme-test-repo"
ORIGINAL_ERROR = "original seeding failure"


class FakeRepositoryDoesNotExistException(Exception):
    """Stand-in for ``codecommit_client.exceptions.RepositoryDoesNotExistException``."""


class FakeBranchDoesNotExistException(Exception):
    """Stand-in for ``codecommit_client.exceptions.BranchDoesNotExistException``."""


def _client_error(code, operation="DeleteRepository"):
    """Build a botocore ClientError with the given error code."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "boom"}}, operation
    )


def _make_creator(provider="codecommit", profile=None):
    """Build a RepositoryCreator without running ``__init__`` (no AWS session).

    Args:
        provider (str): ``'github'`` or ``'codecommit'``.
        profile (str, optional): AWS profile name, or None.

    Returns:
        RepositoryCreator: Minimally initialized instance with mock clients.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = REPO_NAME
    creator.provider = provider
    creator.profile = profile
    creator.source = "s3://invalid-bucket/seed.zip"
    creator.source_type = 's3'
    creator._codecommit_delete_attempted = False
    creator.codecommit_client = MagicMock()
    creator.codecommit_client.exceptions.RepositoryDoesNotExistException = FakeRepositoryDoesNotExistException
    creator.codecommit_client.exceptions.BranchDoesNotExistException = FakeBranchDoesNotExistException
    creator.s3_client = MagicMock()
    creator.s3_client_anonymous = MagicMock()
    creator.is_bucket_public = MagicMock(return_value=False)
    creator.get_init_commit_author = MagicMock(return_value="author")
    creator.get_init_commit_email = MagicMock(return_value="a@example.com")
    return creator


def _echoed(echo):
    """Return everything passed to the mocked ``click.echo`` as strings, in order."""
    return [str(call.args[0]) for call in echo.call_args_list]


def _first_index(lines, text):
    """Return the index of the first echoed line containing ``text``."""
    for index, line in enumerate(lines):
        if text in line:
            return index
    raise AssertionError(f"{text!r} was not echoed: {lines}")


@pytest.fixture
def mocks():
    """Patch ``Log`` and ``click.echo``.

    Yields:
        MagicMock with ``log`` and ``echo``.
    """
    with mock.patch.object(create_repo, "Log") as log, \
            mock.patch.object(create_repo.click, "echo") as echo:
        yield MagicMock(log=log, echo=echo)


class TestDeleteCodecommitRepository:
    """Behavior of the helper itself."""

    def test_success_calls_delete_once_and_reports(self, mocks):
        creator = _make_creator()

        creator._delete_codecommit_repository()

        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        assert any(f"Repository {REPO_NAME} deleted." in line for line in _echoed(mocks.echo))
        mocks.log.info.assert_called()
        mocks.log.error.assert_not_called()

    def test_generic_failure_does_not_raise_and_prints_manual_command(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        creator._delete_codecommit_repository()

        lines = _echoed(mocks.echo)
        assert any("Failed to delete repository" in line and "delete it manually" in line for line in lines)
        assert any(
            f"aws codecommit delete-repository --repository-name {REPO_NAME}" in line
            and "--profile" not in line
            for line in lines
        )
        mocks.log.error.assert_called_once()
        assert "AccessDeniedException" in mocks.log.error.call_args.args[0]

    def test_non_client_error_does_not_raise(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = RuntimeError("throttled")

        creator._delete_codecommit_repository()

        mocks.log.error.assert_called_once()

    def test_manual_command_includes_profile_when_set(self, mocks):
        creator = _make_creator(profile="my-profile")
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        creator._delete_codecommit_repository()

        assert any(
            f"aws codecommit delete-repository --repository-name {REPO_NAME} --profile my-profile" in line
            for line in _echoed(mocks.echo)
        )

    def test_manual_command_includes_region_from_client(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.meta.region_name = "us-west-2"
        creator.codecommit_client.delete_repository.side_effect = RuntimeError("nope")

        creator._delete_codecommit_repository()

        assert any("--region us-west-2" in line for line in _echoed(mocks.echo))

    def test_manual_command_omits_region_when_unavailable(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = RuntimeError("nope")

        creator._delete_codecommit_repository()

        assert not any("--region" in line for line in _echoed(mocks.echo))

    def test_modeled_repository_does_not_exist_is_success(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = FakeRepositoryDoesNotExistException("gone")

        creator._delete_codecommit_repository()

        mocks.log.error.assert_not_called()
        assert not any("Failed" in line or "manually" in line for line in _echoed(mocks.echo))
        mocks.log.info.assert_called()

    def test_client_error_repository_does_not_exist_is_success(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = _client_error("RepositoryDoesNotExistException")

        creator._delete_codecommit_repository()

        mocks.log.error.assert_not_called()
        assert not any("Failed" in line or "manually" in line for line in _echoed(mocks.echo))

    def test_second_call_does_not_delete_again(self, mocks):
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = RuntimeError("nope")

        creator._delete_codecommit_repository()
        creator._delete_codecommit_repository()

        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        mocks.log.error.assert_called_once()

    def test_second_call_after_success_does_not_delete_again(self, mocks):
        creator = _make_creator()

        creator._delete_codecommit_repository()
        creator._delete_codecommit_repository()

        creator.codecommit_client.delete_repository.assert_called_once()


class TestCallSitesWithFailingDelete:
    """The original error stays visible and the exit code stays 1 at every call site."""

    @staticmethod
    def _assert_original_before_delete_message(echo, original):
        lines = _echoed(echo)
        assert _first_index(lines, original) < _first_index(lines, "Failed to delete repository")

    def test_branch_structure_failure(self, mocks):
        creator = _make_creator()
        creator._create_init_readme = MagicMock(side_effect=RuntimeError(ORIGINAL_ERROR))
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        with pytest.raises(SystemExit) as exit_info:
            creator._create_dev_test_branches_codecommit()

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        self._assert_original_before_delete_message(mocks.echo, "Error creating branch structure")

    def test_download_and_extract_failure(self, mocks, tmp_path):
        creator = _make_creator()

        def write_bad_zip(bucket, key, path):
            Path(path).write_bytes(b"not a zip")

        creator.s3_client.download_file.side_effect = write_bad_zip
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract_into(str(tmp_path))

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        self._assert_original_before_delete_message(mocks.echo, "Error in download and extract process")

    def test_file_collection_failure(self, mocks, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        with mock.patch("builtins.open", side_effect=OSError("unreadable")):
            with pytest.raises(SystemExit) as exit_info:
                creator._seed_collect_files(str(tmp_path))

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        self._assert_original_before_delete_message(mocks.echo, "Error processing file README.md")

    def test_batch_commit_failure_deletes_exactly_once(self, mocks, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator.codecommit_client.get_branch.side_effect = FakeBranchDoesNotExistException("no dev")
        creator.codecommit_client.create_commit.side_effect = RuntimeError(ORIGINAL_ERROR)
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        with pytest.raises(SystemExit) as exit_info:
            creator._seed_repository_codecommit(str(tmp_path))

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        lines = _echoed(mocks.echo)
        assert not any("Error in seeding process" in line for line in lines)
        self._assert_original_before_delete_message(mocks.echo, "Error creating commit for batch 1-1")
        assert not tmp_path.exists()

    def test_outer_seeding_failure(self, mocks, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator.codecommit_client.get_branch.side_effect = RuntimeError(ORIGINAL_ERROR)
        creator.codecommit_client.delete_repository.side_effect = _client_error("AccessDeniedException")

        with pytest.raises(SystemExit) as exit_info:
            creator._seed_repository_codecommit(str(tmp_path))

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        self._assert_original_before_delete_message(mocks.echo, "Error in seeding process")

    def test_successful_delete_at_call_site_still_exits_1(self, mocks, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator.codecommit_client.get_branch.side_effect = RuntimeError(ORIGINAL_ERROR)

        with pytest.raises(SystemExit) as exit_info:
            creator._seed_repository_codecommit(str(tmp_path))

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME)
        assert any(f"Repository {REPO_NAME} deleted." in line for line in _echoed(mocks.echo))


class TestGithubNeverUsesCodecommit:
    """Regression: the GitHub provider does not call ``codecommit_client``."""

    def test_download_failure_on_github(self, mocks, tmp_path):
        creator = _make_creator(provider="github")

        def write_bad_zip(bucket, key, path):
            Path(path).write_bytes(b"not a zip")

        creator.s3_client.download_file.side_effect = write_bad_zip

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract_into(str(tmp_path))

        assert exit_info.value.code == 1
        assert creator.codecommit_client.delete_repository.mock_calls == []

    def test_file_collection_failure_on_github(self, mocks, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator(provider="github")

        with mock.patch("builtins.open", side_effect=OSError("unreadable")):
            with pytest.raises(SystemExit) as exit_info:
                creator._seed_collect_files(str(tmp_path))

        assert exit_info.value.code == 1
        assert creator.codecommit_client.delete_repository.mock_calls == []
