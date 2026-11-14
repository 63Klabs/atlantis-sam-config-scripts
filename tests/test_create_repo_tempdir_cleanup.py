"""Tests for temporary directory cleanup in create_repo.py and the GitHub create error path.

Covers two defects in ``RepositoryCreator``:

* Temporary directories created for seeding (the extracted seed source and the
  GitHub seed clone) must be removed on every failure path and on success, and
  the GitHub seed clone must still exist when the dev-to-test merge runs.
* ``_create_repository_github`` must not reference an undefined ``e`` when
  ``GitHubUtils.create_repo`` returns a falsy value.

Real directories are created under pytest's ``tmp_path`` by patching
``tempfile.mkdtemp``, so the tests assert that the paths no longer exist.
Nothing here calls GitHub, AWS, or the network: the S3 client, ``GitHubUtils``,
``subprocess.run``, the prompt, ``Log``, and ``click.echo`` are mocked.

Feature: issue-creating-github-repository-error-getting
"""

import sys
import zipfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import botocore.exceptions
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import create_repo
from create_repo import RepositoryCreator


REPO_NAME = "acme/test-repo"
SOURCE_URL = "s3://invalid-bucket/seed.zip"


def _make_creator(provider="github", source_type="s3"):
    """Build a RepositoryCreator without running ``__init__`` (no AWS session).

    Download, extract, seed, merge, and cleanup methods are real. The clients
    and the branch-structure/repository-creation steps are mocks.

    Args:
        provider (str): ``'github'`` or ``'codecommit'``.
        source_type (str): ``'s3'`` or ``'github'``.

    Returns:
        RepositoryCreator: Minimally initialized instance.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = REPO_NAME
    creator.provider = provider
    creator.source = SOURCE_URL
    creator.source_type = source_type
    creator.profile = None
    creator.skip_test_merge = False
    creator.cleanup_on_failure = False
    creator.test_branch_updated = False
    creator._github_clone_dir = None
    creator.clone_url_https = "https://example.com/repo"
    creator.clone_url_ssh = None
    creator.codecommit_client = MagicMock()
    creator.s3_client = MagicMock()
    creator.s3_client_anonymous = MagicMock()
    creator.is_bucket_public = MagicMock(return_value=False)
    creator.get_init_commit_author = MagicMock(return_value="author")
    creator.get_init_commit_email = MagicMock(return_value="a@example.com")
    creator._create_repository = MagicMock()
    creator._create_dev_test_branches = MagicMock()
    return creator


def _write_valid_zip(path):
    """Write a small valid zip file at ``path``."""
    with zipfile.ZipFile(path, 'w') as zip_file:
        zip_file.writestr("template.yml", "Resources: {}\n")
        zip_file.writestr("src/app.py", "print('hi')\n")


def _write_bad_zip(path):
    """Write bytes that are not a zip file at ``path``."""
    Path(path).write_bytes(b"not a zip")


def _client_error(code):
    """Build a botocore ClientError with the given error code."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "boom"}}, "HeadObject"
    )


@pytest.fixture
def temp_dirs(tmp_path):
    """Make ``tempfile.mkdtemp`` create real directories under ``tmp_path``.

    Yields:
        list[str]: Paths of every directory created through ``mkdtemp``, in order.
    """
    created = []

    def fake_mkdtemp(*_args, **_kwargs):
        path = tmp_path / f"tmp-{len(created)}"
        path.mkdir()
        created.append(str(path))
        return str(path)

    with mock.patch.object(create_repo.tempfile, "mkdtemp", side_effect=fake_mkdtemp):
        yield created


@pytest.fixture
def mocks():
    """Patch the prompt, subprocess.run, Log, click.echo, and GitHubUtils.

    Yields:
        MagicMock with ``prompt``, ``run``, ``log``, ``echo`` and ``gh_utils``.
    """
    with mock.patch.object(create_repo.Colorize, "prompt", return_value="N") as prompt, \
            mock.patch.object(create_repo.subprocess, "run") as run, \
            mock.patch.object(create_repo, "Log") as log, \
            mock.patch.object(create_repo.click, "echo") as echo, \
            mock.patch.object(create_repo, "GitHubUtils") as gh_utils:
        yield MagicMock(prompt=prompt, run=run, log=log, echo=echo, gh_utils=gh_utils)


def _assert_all_removed(paths):
    """Assert every path in ``paths`` no longer exists."""
    assert paths, "expected at least one temp dir to have been created"
    for path in paths:
        assert not Path(path).exists(), f"temp dir leaked: {path}"


class TestDownloadAndExtractCleanup:
    """``_download_and_extract`` removes its temp dir on failure, hands it off on success."""

    def test_s3_403_removes_temp_dir_and_propagates(self, mocks, temp_dirs):
        """A 403 from S3 escapes the download step and the temp dir is removed."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("403")

        with pytest.raises(botocore.exceptions.ClientError):
            creator._download_and_extract()

        assert len(temp_dirs) == 1
        _assert_all_removed(temp_dirs)

    def test_github_download_failure_removes_temp_dir(self, mocks, temp_dirs):
        """A failed GitHub zip download removes the temp dir and propagates."""
        creator = _make_creator(source_type='github')
        mocks.gh_utils.download_zip_from_url.side_effect = RuntimeError("network down")

        with pytest.raises(RuntimeError, match="network down"):
            creator._download_and_extract()

        _assert_all_removed(temp_dirs)

    def test_bad_zip_removes_temp_dir_and_exits_1(self, mocks, temp_dirs):
        """A corrupt zip fails extraction, exits 1, and the temp dir is removed."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_bad_zip(path)

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1
        _assert_all_removed(temp_dirs)

    def test_access_denied_removes_temp_dir_and_exits_1(self, mocks, temp_dirs):
        """AccessDenied leaves no zip, extraction fails, exits 1, temp dir is removed."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("AccessDenied")

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1
        _assert_all_removed(temp_dirs)

    def test_invalid_source_type_removes_temp_dir_and_exits_1(self, mocks, temp_dirs):
        """An unsupported source type exits 1 and the temp dir is removed."""
        creator = _make_creator(source_type='bogus')

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1
        _assert_all_removed(temp_dirs)

    def test_codecommit_bad_zip_deletes_repository_and_removes_temp_dir(self, mocks, temp_dirs):
        """CodeCommit keeps its delete-on-failure behavior and the temp dir is removed."""
        creator = _make_creator(provider='codecommit')
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_bad_zip(path)

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(
            repositoryName=REPO_NAME)
        _assert_all_removed(temp_dirs)

    def test_codecommit_delete_failure_still_removes_temp_dir(self, mocks, temp_dirs):
        """If deleting the CodeCommit repo raises, the helper absorbs it: exit 1 and the temp dir is still removed."""
        creator = _make_creator(provider='codecommit')
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_bad_zip(path)
        creator.codecommit_client.delete_repository.side_effect = RuntimeError("delete failed")

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1

        _assert_all_removed(temp_dirs)

    def test_success_hands_off_temp_dir_with_extracted_files(self, mocks, temp_dirs):
        """On success the directory is kept for the caller and holds the extracted files."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_valid_zip(path)

        result = creator._download_and_extract()

        assert result == temp_dirs[0]
        assert (Path(result) / "template.yml").is_file()
        assert (Path(result) / "src" / "app.py").is_file()


class TestSeedingCleanup:
    """``create_and_seed_repository`` leaves no temp dirs behind."""

    def _github_creator(self):
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_valid_zip(path)
        return creator

    def test_github_seeding_failure_removes_extract_and_clone_dirs(self, mocks, temp_dirs):
        """A failed GitHub seed removes both temp dirs and keeps exit code 1."""
        creator = self._github_creator()
        mocks.gh_utils.create_init_commit.side_effect = RuntimeError("push failed")

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        assert len(temp_dirs) == 2  # extracted source + seed clone
        _assert_all_removed(temp_dirs)
        assert creator._github_clone_dir is None
        mocks.prompt.assert_called_once()  # the failure prompt flow still ran once
        mocks.run.assert_not_called()  # default answer is N, nothing deleted

    def test_github_cleanup_runs_after_failure_handler(self, mocks, temp_dirs):
        """The seed clone still exists while ``_handle_github_seeding_failure`` runs."""
        creator = self._github_creator()
        mocks.gh_utils.create_init_commit.side_effect = RuntimeError("push failed")
        seen = {}

        def fake_handler():
            seen["clone_dir"] = creator._github_clone_dir
            seen["clone_exists"] = Path(creator._github_clone_dir).exists()

        creator._handle_github_seeding_failure = MagicMock(side_effect=fake_handler)

        with pytest.raises(SystemExit):
            creator.create_and_seed_repository()

        creator._handle_github_seeding_failure.assert_called_once_with()
        assert seen["clone_exists"] is True
        assert not Path(seen["clone_dir"]).exists()

    def test_github_failure_handler_error_still_removes_clone(self, mocks, temp_dirs):
        """If the failure handler itself raises, the clone is still removed."""
        creator = self._github_creator()
        mocks.gh_utils.create_init_commit.side_effect = RuntimeError("push failed")
        creator._handle_github_seeding_failure = MagicMock(side_effect=ValueError("handler broke"))

        with pytest.raises(ValueError, match="handler broke"):
            creator.create_and_seed_repository()

        _assert_all_removed(temp_dirs)

    def test_github_keyboard_interrupt_removes_clone_without_prompt(self, mocks, temp_dirs):
        """Ctrl-C during seeding removes the clone and does not offer repository deletion."""
        creator = self._github_creator()
        mocks.gh_utils.create_init_commit.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            creator.create_and_seed_repository()

        _assert_all_removed(temp_dirs)
        mocks.prompt.assert_not_called()

    def test_github_download_failure_removes_temp_dir(self, mocks, temp_dirs):
        """A failed download inside the full flow leaves nothing behind."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = _client_error("403")

        with pytest.raises(botocore.exceptions.ClientError):
            creator.create_and_seed_repository()

        _assert_all_removed(temp_dirs)

    def test_github_success_keeps_clone_for_merge_then_removes_everything(self, mocks, temp_dirs):
        """The merge sees an existing clone; afterwards every temp dir is gone."""
        creator = self._github_creator()
        seen = {}

        def fake_merge(clone_dir, source_branch, dest_branch):
            seen["clone_dir"] = clone_dir
            seen["clone_exists"] = Path(clone_dir).is_dir()
            seen["branches"] = (source_branch, dest_branch)

        mocks.gh_utils.merge_branches_fast_forward.side_effect = fake_merge

        creator.create_and_seed_repository()

        assert seen["clone_exists"] is True
        assert seen["clone_dir"] == temp_dirs[1]
        assert seen["branches"] == ("dev", "test")
        assert creator.test_branch_updated is True
        assert len(temp_dirs) == 2
        _assert_all_removed(temp_dirs)
        assert creator._github_clone_dir is None

    def test_github_merge_failure_is_non_fatal_and_removes_clone(self, mocks, temp_dirs):
        """A merge failure keeps the repo, does not raise, and the clone is removed."""
        creator = self._github_creator()
        mocks.gh_utils.merge_branches_fast_forward.side_effect = RuntimeError("merge failed")

        creator.create_and_seed_repository()

        assert creator.test_branch_updated is False
        _assert_all_removed(temp_dirs)
        mocks.prompt.assert_not_called()
        mocks.run.assert_not_called()

    def test_github_skip_test_merge_removes_clone(self, mocks, temp_dirs):
        """With ``skip_test_merge`` the clone is still removed."""
        creator = self._github_creator()
        creator.skip_test_merge = True

        creator.create_and_seed_repository()

        mocks.gh_utils.merge_branches_fast_forward.assert_not_called()
        _assert_all_removed(temp_dirs)

    def test_codecommit_seeding_failure_removes_temp_dir_and_deletes_repository(self, mocks, temp_dirs):
        """CodeCommit keeps its delete-on-failure logic; the extracted dir is removed."""
        creator = _make_creator(provider='codecommit')
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_valid_zip(path)
        creator.codecommit_client.exceptions.BranchDoesNotExistException = type(
            "BranchDoesNotExistException", (Exception,), {})
        creator.codecommit_client.get_branch.side_effect = RuntimeError("down")

        with pytest.raises(SystemExit) as exit_info:
            creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        creator.codecommit_client.delete_repository.assert_called_once_with(
            repositoryName=REPO_NAME)
        mocks.prompt.assert_not_called()  # the GitHub cleanup prompt is not used
        assert len(temp_dirs) == 1
        _assert_all_removed(temp_dirs)

    def test_codecommit_success_removes_temp_dir_and_merges(self, mocks, temp_dirs):
        """CodeCommit success removes the extracted dir and still merges server-side."""
        creator = _make_creator(provider='codecommit')
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_valid_zip(path)
        creator.codecommit_client.exceptions.BranchDoesNotExistException = type(
            "BranchDoesNotExistException", (Exception,), {})
        creator.codecommit_client.get_branch.return_value = {'branch': {'commitId': 'abc'}}
        creator.codecommit_client.create_commit.return_value = {'commitId': 'def'}

        creator.create_and_seed_repository()

        creator.codecommit_client.merge_branches_by_fast_forward.assert_called_once()
        creator.codecommit_client.delete_repository.assert_not_called()
        assert creator.test_branch_updated is True
        assert len(temp_dirs) == 1
        _assert_all_removed(temp_dirs)


class TestCleanupFailureDoesNotMaskError:
    """A failure inside temp dir removal never replaces the original error."""

    def test_remove_temp_dir_swallows_errors(self, mocks):
        """``_remove_temp_dir`` never raises, even if ``shutil.rmtree`` does."""
        with mock.patch.object(create_repo.shutil, "rmtree", side_effect=RuntimeError("rm failed")):
            RepositoryCreator._remove_temp_dir("/nonexistent/path")  # must not raise

        mocks.log.warning.assert_called_once()

    def test_remove_temp_dir_ignores_empty_path(self, mocks):
        """``None`` or an empty path is a no-op."""
        with mock.patch.object(create_repo.shutil, "rmtree") as rmtree:
            RepositoryCreator._remove_temp_dir(None)
            RepositoryCreator._remove_temp_dir("")

        rmtree.assert_not_called()

    def test_download_failure_original_error_survives_cleanup_failure(self, mocks, temp_dirs):
        """The S3 error propagates unchanged when removing the temp dir also fails."""
        creator = _make_creator()
        original = _client_error("403")
        creator.s3_client.download_file.side_effect = original

        with mock.patch.object(create_repo.shutil, "rmtree", side_effect=OSError("rm failed")):
            with pytest.raises(botocore.exceptions.ClientError) as error_info:
                creator._download_and_extract()

        assert error_info.value is original

    def test_bad_zip_exit_code_survives_cleanup_failure(self, mocks, temp_dirs):
        """The extract failure still exits 1 when removing the temp dir fails."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_bad_zip(path)

        with mock.patch.object(create_repo.shutil, "rmtree", side_effect=OSError("rm failed")):
            with pytest.raises(SystemExit) as exit_info:
                creator._download_and_extract()

        assert exit_info.value.code == 1

    def test_seeding_failure_exit_code_survives_cleanup_failure(self, mocks, temp_dirs):
        """A GitHub seeding failure still exits 1 when every removal fails."""
        creator = _make_creator()
        creator.s3_client.download_file.side_effect = \
            lambda bucket, key, path: _write_valid_zip(path)
        mocks.gh_utils.create_init_commit.side_effect = RuntimeError("push failed")

        with mock.patch.object(create_repo.shutil, "rmtree", side_effect=OSError("rm failed")):
            with pytest.raises(SystemExit) as exit_info:
                creator.create_and_seed_repository()

        assert exit_info.value.code == 1
        mocks.prompt.assert_called_once()

    def test_cleanup_github_clone_does_not_raise_and_resets_attribute(self, mocks, tmp_path):
        """``_cleanup_github_clone`` resets the attribute even if removal fails, and never double-deletes."""
        creator = _make_creator()
        clone_dir = tmp_path / "clone"
        clone_dir.mkdir()
        creator._github_clone_dir = str(clone_dir)

        with mock.patch.object(create_repo.shutil, "rmtree", side_effect=OSError("rm failed")) as rmtree:
            creator._cleanup_github_clone()
            creator._cleanup_github_clone()  # second call is a no-op

        assert creator._github_clone_dir is None
        rmtree.assert_called_once()


class TestCreateRepositoryGithubErrorPath:
    """``_create_repository_github`` builds its message from variables that exist."""

    def test_falsy_create_result_exits_1_with_clear_message(self, mocks):
        """No NameError/UnboundLocalError; the message says the CLI did not report success."""
        creator = _make_creator()
        mocks.gh_utils.create_repo.return_value = False

        with pytest.raises(SystemExit) as exit_info:
            creator._create_repository_github()

        assert exit_info.value.code == 1
        echoed = " ".join(str(call.args[0]) for call in mocks.echo.call_args_list)
        assert "Error creating GitHub repository: GitHub CLI did not report success" in echoed
        assert "not defined" not in echoed
        logged = " ".join(str(call.args[0]) for call in mocks.log.error.call_args_list)
        assert "GitHub CLI did not report success" in logged
        assert "not defined" not in logged
        mocks.run.assert_not_called()  # no repository deletion

    def test_create_exception_still_reports_original_message(self, mocks):
        """An exception from ``create_repo`` is still reported with its own message."""
        creator = _make_creator()
        mocks.gh_utils.create_repo.side_effect = Exception("Failed to create repository: boom")

        with pytest.raises(SystemExit) as exit_info:
            creator._create_repository_github()

        assert exit_info.value.code == 1
        echoed = " ".join(str(call.args[0]) for call in mocks.echo.call_args_list)
        assert "Error creating GitHub repository: Failed to create repository: boom" in echoed

    def test_repo_view_failure_after_creation_leaves_repository_in_place(self, mocks):
        """If ``get_repository`` fails after creation the repo is intentionally not deleted."""
        creator = _make_creator()
        mocks.gh_utils.create_repo.return_value = True
        mocks.gh_utils.get_repository.side_effect = Exception("gh repo view failed")

        with pytest.raises(SystemExit) as exit_info:
            creator._create_repository_github()

        assert exit_info.value.code == 1
        mocks.run.assert_not_called()
        mocks.prompt.assert_not_called()
