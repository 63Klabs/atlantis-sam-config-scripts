"""Tests for cleanup after a failure that follows GitHub repository creation.

Covers ``RepositoryCreator.create_and_seed_repository()``: on the GitHub
provider, a failure while creating branches, downloading or extracting the
seed source, or seeding must run ``_handle_github_seeding_failure()`` exactly
once, never touch ``codecommit_client``, and keep the original exit behavior.
The CodeCommit path must keep its own delete-on-failure logic and must not
offer the GitHub cleanup. Nothing here calls GitHub, AWS, or the network:
the S3 client, ``GitHubUtils``, ``subprocess.run``, the prompt, ``Log``, and
``click.echo`` are all mocked.

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


REPO_NAME = "acme/test-repo"
SOURCE_URL = "s3://invalid-bucket/invalid.zip"
EXPECTED_DELETE_COMMAND = ["gh", "repo", "delete", REPO_NAME, "--yes"]


def _make_creator(provider="github", cleanup_on_failure=False, source=SOURCE_URL):
    """Build a RepositoryCreator without running ``__init__`` (no AWS session).

    ``_create_repository`` is stubbed because the repository is assumed to be
    created already. Download, extract, seed, and cleanup methods are real.
    ``codecommit_client`` and ``s3_client`` are mocks.

    Args:
        provider (str): ``'github'`` or ``'codecommit'``.
        cleanup_on_failure (bool): Value for the ``--cleanup-on-failure`` flag.
        source (str): Seed source URL.

    Returns:
        RepositoryCreator: Minimally initialized instance.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = REPO_NAME
    creator.provider = provider
    creator.source = source
    creator.source_type = 's3'
    creator.skip_test_merge = False
    creator.cleanup_on_failure = cleanup_on_failure
    creator.test_branch_updated = False
    creator._github_clone_dir = None
    creator.codecommit_client = MagicMock()
    creator.s3_client = MagicMock()
    creator.s3_client_anonymous = MagicMock()
    creator.is_bucket_public = MagicMock(return_value=False)
    creator.get_init_commit_author = MagicMock(return_value="author")
    creator.get_init_commit_email = MagicMock(return_value="a@example.com")
    creator._create_init_readme = MagicMock(return_value="# Hello\n")
    creator._create_repository = MagicMock()
    creator._merge_dev_to_test = MagicMock()
    creator._cleanup_github_clone = MagicMock()
    return creator


def _client_error(code):
    """Build a botocore ClientError with the given error code."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "boom"}}, "GetObject"
    )


@pytest.fixture
def mocks():
    """Patch the prompt, subprocess.run, Log, click.echo, and GitHubUtils.

    Yields:
        MagicMock with ``prompt``, ``run``, ``log``, ``echo`` and ``gh_utils``.
    """
    with mock.patch.object(create_repo.Colorize, "prompt") as prompt, \
            mock.patch.object(create_repo.subprocess, "run") as run, \
            mock.patch.object(create_repo, "Log") as log, \
            mock.patch.object(create_repo.click, "echo") as echo, \
            mock.patch.object(create_repo, "GitHubUtils") as gh_utils:
        yield MagicMock(prompt=prompt, run=run, log=log, echo=echo, gh_utils=gh_utils)


class TestGithubDownloadFailure:
    """Download/extract failures on the GitHub path offer cleanup once."""

    def test_s3_403_runs_cleanup_handler_once_and_propagates(self, mocks):
        """A 403 from S3 escapes the download step; cleanup runs once, error still propagates."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("403")
        creator._handle_github_seeding_failure = MagicMock()
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(botocore.exceptions.ClientError):
            creator.create_and_seed_repository()

        creator._handle_github_seeding_failure.assert_called_once_with()
        creator._merge_dev_to_test.assert_not_called()
        assert creator.codecommit_client.mock_calls == []

    def test_s3_access_denied_exits_1_and_runs_cleanup_handler_once(self, mocks):
        """AccessDenied leaves no zip, so extraction fails and exits 1; cleanup runs once."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("AccessDenied")
        creator._handle_github_seeding_failure = MagicMock()
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator._handle_github_seeding_failure.assert_called_once_with()
        assert creator.codecommit_client.mock_calls == []

    def test_invalid_zip_exits_1_and_runs_cleanup_handler_once(self, mocks):
        """A corrupt zip fails extraction, exits 1, and offers cleanup once."""
        creator = _make_creator()

        def write_bad_zip(bucket, key, path):
            Path(path).write_bytes(b"not a zip")

        creator.s3_client.download_file.side_effect = write_bad_zip
        creator._handle_github_seeding_failure = MagicMock()
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator._handle_github_seeding_failure.assert_called_once_with()
        assert creator.codecommit_client.mock_calls == []

    def test_prompt_path_prompts_once_and_deletes_when_confirmed(self, mocks):
        """Without the flag, the user is prompted once; 'y' runs ``gh repo delete``."""
        mocks.prompt.return_value = "y"
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("403")
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(botocore.exceptions.ClientError):
            creator.create_and_seed_repository()

        mocks.prompt.assert_called_once()
        mocks.run.assert_called_once()
        assert mocks.run.call_args.args[0] == EXPECTED_DELETE_COMMAND
        assert creator.codecommit_client.mock_calls == []

    def test_prompt_path_keeps_repository_when_declined(self, mocks):
        """Answering 'N' keeps the repository and still exits non-zero."""
        mocks.prompt.return_value = "N"
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("AccessDenied")
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        mocks.prompt.assert_called_once()
        mocks.run.assert_not_called()

    def test_flag_path_deletes_without_prompt(self, mocks):
        """With ``--cleanup-on-failure`` the repository is deleted once, no prompt."""
        creator = _make_creator(cleanup_on_failure=True)
        creator.s3_client.download_file.side_effect = _client_error("403")
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(botocore.exceptions.ClientError):
            creator.create_and_seed_repository()

        mocks.prompt.assert_not_called()
        mocks.run.assert_called_once()
        assert mocks.run.call_args.args[0] == EXPECTED_DELETE_COMMAND
        assert creator.codecommit_client.mock_calls == []

    def test_invalid_source_type_exits_1_and_runs_cleanup_handler_once(self, mocks):
        """The unsupported source type exit (code 1) also offers cleanup once."""
        creator = _make_creator()
        creator.source_type = 'bogus'
        creator._handle_github_seeding_failure = MagicMock()
        creator._create_dev_test_branches = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator._handle_github_seeding_failure.assert_called_once_with()


class TestGithubOtherPostCreateFailures:
    """Other failures after creation use the same single handler."""

    def test_seeding_failure_runs_cleanup_handler_once(self, mocks, tmp_path):
        """A seeding failure exits 1 and offers cleanup once (no double prompt)."""
        mocks.gh_utils.create_init_commit.side_effect = RuntimeError("push failed")
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator._create_dev_test_branches = MagicMock()
        creator._download_and_extract = MagicMock(return_value=str(tmp_path))
        creator._handle_github_seeding_failure = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator._handle_github_seeding_failure.assert_called_once_with()
        # The seeding step's own finally block still removes the temp dir.
        assert not tmp_path.exists()
        assert creator.codecommit_client.mock_calls == []

    def test_seeding_failure_prompts_only_once(self, mocks, tmp_path):
        """With the real handler, a seeding failure prompts a single time."""
        mocks.prompt.return_value = "N"
        mocks.gh_utils.create_init_commit.side_effect = RuntimeError("push failed")
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator._create_dev_test_branches = MagicMock()
        creator._download_and_extract = MagicMock(return_value=str(tmp_path))

        with pytest.raises(SystemExit):
            creator.create_and_seed_repository()

        mocks.prompt.assert_called_once()

    def test_file_collection_failure_does_not_touch_codecommit(self, mocks, tmp_path):
        """A per-file read error on GitHub offers cleanup once and skips CodeCommit."""
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator()
        creator._create_dev_test_branches = MagicMock()
        creator._download_and_extract = MagicMock(return_value=str(tmp_path))
        creator._handle_github_seeding_failure = MagicMock()

        with mock.patch("builtins.open", side_effect=OSError("unreadable")):
            with pytest.raises(SystemExit) as exit_info:
                creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator._handle_github_seeding_failure.assert_called_once_with()
        assert creator.codecommit_client.mock_calls == []

    def test_branch_structure_failure_runs_cleanup_handler_once(self, mocks):
        """A branch structure failure exits 1 and offers cleanup once."""
        mocks.gh_utils.create_branch_structure.side_effect = RuntimeError("no branches")
        creator = _make_creator()
        creator._handle_github_seeding_failure = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator._handle_github_seeding_failure.assert_called_once_with()
        assert creator.codecommit_client.mock_calls == []

    def test_repository_creation_failure_never_offers_cleanup(self, mocks):
        """If creation itself fails (for example the repo already exists), nothing is deleted."""
        creator = _make_creator()
        creator._create_repository = MagicMock(side_effect=SystemExit(1))
        creator._handle_github_seeding_failure = MagicMock()

        with pytest.raises(SystemExit):
            creator.create_and_seed_repository()

        creator._handle_github_seeding_failure.assert_not_called()
        mocks.run.assert_not_called()

    def test_success_never_offers_cleanup(self, mocks):
        """A successful run does not invoke the cleanup handler."""
        creator = _make_creator()
        creator._create_dev_test_branches = MagicMock()
        creator._download_and_extract = MagicMock(return_value="/tmp/seed")
        creator._seed_repository = MagicMock()
        creator._handle_github_seeding_failure = MagicMock()

        creator.create_and_seed_repository()

        creator._handle_github_seeding_failure.assert_not_called()
        creator._merge_dev_to_test.assert_called_once()


class TestCodeCommitUnchanged:
    """The CodeCommit path keeps its own delete-on-failure logic."""

    def test_extract_failure_deletes_via_codecommit_and_skips_github_cleanup(self, mocks):
        """AccessDenied then extraction failure deletes via CodeCommit and exits 1."""
        creator = _make_creator(provider="codecommit")
        creator.s3_client.download_file.side_effect = _client_error("AccessDenied")
        creator._create_dev_test_branches = MagicMock()
        creator._handle_github_seeding_failure = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(
            repositoryName=REPO_NAME
        )
        creator._handle_github_seeding_failure.assert_not_called()
        mocks.prompt.assert_not_called()
        mocks.run.assert_not_called()

    def test_download_403_propagates_without_github_cleanup(self, mocks):
        """A 403 on CodeCommit propagates as before and offers no GitHub cleanup."""
        creator = _make_creator(provider="codecommit")
        creator.s3_client.download_file.side_effect = _client_error("403")
        creator._create_dev_test_branches = MagicMock()
        creator._handle_github_seeding_failure = MagicMock()

        with pytest.raises(botocore.exceptions.ClientError):
            creator.create_and_seed_repository()

        creator._handle_github_seeding_failure.assert_not_called()
        mocks.prompt.assert_not_called()

    def test_file_collection_failure_still_deletes_via_codecommit(self, mocks, tmp_path):
        """A per-file read error on CodeCommit still deletes via CodeCommit."""
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator(provider="codecommit")

        with mock.patch("builtins.open", side_effect=OSError("unreadable")):
            with pytest.raises(SystemExit) as exit_info:
                creator._seed_collect_files(str(tmp_path))

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(
            repositoryName=REPO_NAME
        )

    def test_seeding_failure_does_not_offer_github_cleanup(self, mocks, tmp_path):
        """A CodeCommit seeding failure deletes via CodeCommit and never prompts."""
        (tmp_path / "README.md").write_text("hi")
        creator = _make_creator(provider="codecommit")
        creator.codecommit_client.get_branch.side_effect = RuntimeError("down")
        creator._create_dev_test_branches = MagicMock()
        creator._download_and_extract = MagicMock(return_value=str(tmp_path))
        creator._handle_github_seeding_failure = MagicMock()

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called()
        creator._handle_github_seeding_failure.assert_not_called()
        mocks.prompt.assert_not_called()
