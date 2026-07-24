"""Tests for the dev->test auto-merge feature in cli/create_repo.py.

This module holds the property-based and unit tests for the
create-repo-auto-merge-test-branch feature. Tests are grouped into
classes by concern so later tasks (6.x/7.1/7.3) can append cleanly.

Feature: create-repo-auto-merge-test-branch
"""

import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from create_repo import should_merge_test, RepositoryCreator


# Strategies shared across property tests in this module.

# Falsy sources represent "no Source resolved" (None or empty string).
_falsy_sources = st.sampled_from([None, ""])

# Truthy sources represent resolved S3/GitHub URIs and other seed inputs.
_truthy_sources = st.one_of(
    st.just("s3://my-bucket/path/to/app.zip"),
    st.just("https://github.com/acme/starter"),
    st.text(min_size=1).filter(lambda s: bool(s)),
)

_any_source = st.one_of(_falsy_sources, _truthy_sources)


class TestShouldMergeTestProperty:
    """Property 1: merge gating predicate correctness."""

    # Feature: create-repo-auto-merge-test-branch, Property 1: For any combination
    # of source (resolved or not) and skip_test_merge, the dev->test merge is
    # attempted if and only if a Source is resolved AND skip_test_merge is False.
    # Validates: Requirements 1.1, 2.2, 2.3, 2.4
    @settings(max_examples=200)
    @given(source=_any_source, skip_test_merge=st.booleans())
    def test_merge_iff_seeded_and_not_opted_out(self, source, skip_test_merge):
        """Merge is attempted exactly when seeded and not opted out."""
        result = should_merge_test(source, skip_test_merge)
        expected = bool(source) and not skip_test_merge
        assert result is expected

    # Feature: create-repo-auto-merge-test-branch, Property 1 (no-source invariant):
    # When no Source is resolved, no merge is attempted regardless of the flag.
    # Validates: Requirements 2.3, 2.4
    @settings(max_examples=200)
    @given(source=_falsy_sources, skip_test_merge=st.booleans())
    def test_no_source_never_merges(self, source, skip_test_merge):
        """No Source resolved means no merge, regardless of the opt-out flag."""
        assert should_merge_test(source, skip_test_merge) is False

    # Feature: create-repo-auto-merge-test-branch, Property 1 (opt-out invariant):
    # When skip_test_merge is True, no merge is attempted even if seeded.
    # Validates: Requirement 2.2
    @settings(max_examples=200)
    @given(source=_truthy_sources)
    def test_opt_out_suppresses_merge_when_seeded(self, source):
        """The opt-out flag suppresses the merge even when a Source is resolved."""
        assert should_merge_test(source, True) is False

    # Feature: create-repo-auto-merge-test-branch, Property 1 (default behavior):
    # When seeded and not opted out, the merge is attempted.
    # Validates: Requirement 1.1
    @settings(max_examples=200)
    @given(source=_truthy_sources)
    def test_seeded_and_not_opted_out_merges(self, source):
        """A resolved Source with the flag unset triggers the merge."""
        assert should_merge_test(source, False) is True

# =============================================================================
# Property 2: Follow-up hint command construction
# =============================================================================

# The literal command form the hint MUST always present, with <prefix> and
# <project_id> preserved verbatim and 'test' as the literal stage id.
_HINT_COMMAND = "./cli/config.py pipeline <prefix> <project_id> test"

# Safe alphabet for repo/profile names: identifier-like characters only.
# Excludes whitespace/newlines so the command stays on a single line, and the
# "profile" filter guarantees a falsy-profile hint can never accidentally
# contain the "--profile" option text via the repo_name.
_NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"

_name_segment = st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=24).filter(
    lambda s: "profile" not in s
)

# repo_name in both owner/repo and plain forms.
_plain_repo = _name_segment
_owner_repo = st.builds(lambda owner, repo: f"{owner}/{repo}", _name_segment, _name_segment)
_repo_names = st.one_of(_plain_repo, _owner_repo)

# Truthy profile values (random profile names) and falsy ones (None / empty).
_truthy_profiles = st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=24)
_any_profile = st.one_of(st.none(), st.just(""), _truthy_profiles)


def _make_creator(repo_name, profile):
    """Build a RepositoryCreator for hint testing without running __init__.

    ``build_test_pipeline_hint()`` reads only ``self.profile`` and
    ``self.repo_name``. Constructing via ``__new__`` bypasses the AWS session
    and settings setup in ``__init__`` (unrelated to string construction) and
    lets these property tests set just those two attributes directly.

    Args:
        repo_name (str): Repository name (owner/repo or plain form).
        profile (str or None): AWS profile value, possibly None/empty.

    Returns:
        RepositoryCreator: A minimally-initialized instance for hint building.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = repo_name
    creator.profile = profile
    return creator


class TestBuildTestPipelineHintProperty:
    """Property 2: follow-up hint command construction correctness."""

    # Feature: create-repo-auto-merge-test-branch, Property 2: For any repo_name
    # and profile value, build_test_pipeline_hint() produces a command containing
    # the literal './cli/config.py pipeline <prefix> <project_id> test' with the
    # <prefix> and <project_id> placeholders preserved verbatim; appends
    # ' --profile <profile>' with the actual profile value iff profile is truthy;
    # and includes a separate line with the actual repo_name alongside the
    # Repository parameter instruction.
    # Validates: Requirements 6.2, 6.3, 6.4, 6.5
    @settings(max_examples=200)
    @given(repo_name=_repo_names, profile=_any_profile)
    def test_hint_command_construction(self, repo_name, profile):
        """The hint preserves placeholders, gates --profile, and names the repo."""
        creator = _make_creator(repo_name, profile)
        lines = creator.build_test_pipeline_hint()
        joined = "\n".join(lines)

        # The suggested command is present with placeholders preserved verbatim.
        assert _HINT_COMMAND in joined
        assert "<prefix>" in joined
        assert "<project_id>" in joined

        # ' --profile <profile>' is appended iff profile is truthy.
        if profile:
            assert f" --profile {profile}" in joined
        else:
            assert "--profile" not in joined

        # A separate line names the actual repo_name for the Repository parameter.
        assert f"Use {repo_name} when prompted for the Repository parameter." in joined
        assert repo_name in joined
        assert "Repository parameter" in joined

    # Feature: create-repo-auto-merge-test-branch, Property 2 (placeholder invariant):
    # The <prefix>/<project_id> placeholders are never substituted, regardless of
    # repo_name or profile.
    # Validates: Requirements 6.3
    @settings(max_examples=200)
    @given(repo_name=_repo_names, profile=_any_profile)
    def test_placeholders_preserved_verbatim(self, repo_name, profile):
        """<prefix> and <project_id> remain literal placeholders in the command."""
        creator = _make_creator(repo_name, profile)
        joined = "\n".join(creator.build_test_pipeline_hint())
        assert _HINT_COMMAND in joined

    # Feature: create-repo-auto-merge-test-branch, Property 2 (profile appended):
    # When a profile is provided, the command appends ' --profile <profile>' using
    # the actual value.
    # Validates: Requirements 6.4
    @settings(max_examples=200)
    @given(repo_name=_repo_names, profile=_truthy_profiles)
    def test_profile_appended_when_truthy(self, repo_name, profile):
        """A truthy profile appends ' --profile <profile>' with the real value."""
        creator = _make_creator(repo_name, profile)
        joined = "\n".join(creator.build_test_pipeline_hint())
        assert f" --profile {profile}" in joined

    # Feature: create-repo-auto-merge-test-branch, Property 2 (profile omitted):
    # When no profile is provided, the command omits the --profile option.
    # Validates: Requirements 6.4
    @settings(max_examples=200)
    @given(repo_name=_repo_names, profile=st.one_of(st.none(), st.just("")))
    def test_profile_omitted_when_falsy(self, repo_name, profile):
        """A falsy profile omits the --profile option entirely."""
        creator = _make_creator(repo_name, profile)
        joined = "\n".join(creator.build_test_pipeline_hint())
        assert "--profile" not in joined

    # Feature: create-repo-auto-merge-test-branch, Property 2 (repo_name line):
    # A separate line contains the actual repo_name alongside the Repository
    # parameter instruction.
    # Validates: Requirements 6.5
    @settings(max_examples=200)
    @given(repo_name=_repo_names, profile=_any_profile)
    def test_repo_name_line_present(self, repo_name, profile):
        """A dedicated line carries repo_name and the Repository parameter hint."""
        creator = _make_creator(repo_name, profile)
        lines = creator.build_test_pipeline_hint()

        matching = [
            line for line in lines
            if repo_name in line and "Repository parameter" in line
        ]
        assert len(matching) >= 1

# =============================================================================
# Property 3: Merge failure is non-fatal and leaves the hint suppressed
# =============================================================================

import subprocess
from unittest.mock import patch, MagicMock

import pytest


# Simple exception types that a provider merge operation might raise. Each is
# constructed with a Hypothesis-generated message so the handler is exercised
# against arbitrary error text.
_simple_exception_types = st.sampled_from([
    ValueError,
    RuntimeError,
    Exception,
    TypeError,
    OSError,
    KeyError,
])

_simple_exceptions = st.builds(
    lambda exc_type, message: exc_type(message),
    _simple_exception_types,
    st.text(max_size=200),
)

# subprocess.CalledProcessError mirrors the GitHub merge failure path
# (git checkout/merge/push returning non-zero). Its constructor differs from a
# plain Exception, so it is generated separately with random return codes,
# command vectors, and output/stderr bytes.
_called_process_errors = st.builds(
    lambda code, cmd, msg: subprocess.CalledProcessError(
        returncode=code,
        cmd=cmd,
        output=msg.encode(),
        stderr=msg.encode(),
    ),
    st.integers(min_value=1, max_value=255),
    st.lists(
        st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=12),
        min_size=1, max_size=4,
    ),
    st.text(max_size=100),
)

# The full space of exceptions a merge operation can hand to the failure
# handler: diverse built-in types plus the subprocess error from git.
_merge_exceptions = st.one_of(_simple_exceptions, _called_process_errors)


def _make_failure_creator(test_branch_updated):
    """Build a RepositoryCreator for failure-handling tests without __init__.

    ``_handle_merge_failure()`` touches only ``self.test_branch_updated``,
    ``self.repo_name``, ``self.codecommit_client`` (indirectly, to prove it is
    never used to delete the repo), and ``self.get_clone_urls`` (via
    ``_build_manual_merge_instructions``). Constructing via ``__new__`` bypasses
    the AWS session and settings setup in ``__init__`` (unrelated to the
    non-fatal failure path) and lets the property test set just those
    attributes directly.

    Args:
        test_branch_updated (bool): Initial value for ``test_branch_updated``,
            used to prove the handler forces it to ``False`` regardless of its
            prior state.

    Returns:
        RepositoryCreator: A minimally-initialized instance for the failure path.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = "acme-web-app"
    creator.profile = None
    creator.test_branch_updated = test_branch_updated
    # A mocked CodeCommit client proves the handler never issues a delete.
    creator.codecommit_client = MagicMock()
    # Provide clone URLs so manual instructions build without any AWS calls.
    creator.get_clone_urls = MagicMock(
        return_value={'https': 'https://example.com/acme-web-app'}
    )
    return creator


@patch("create_repo.Log")
class TestHandleMergeFailureProperty:
    """Property 3: merge failure is non-fatal and suppresses the hint."""

    # Feature: create-repo-auto-merge-test-branch, Property 3: For any error
    # raised by a provider merge operation, _handle_merge_failure() does NOT
    # raise SystemExit, does NOT invoke repository deletion, and leaves
    # test_branch_updated False so no follow-up hint is printed.
    # Validates: Requirements 3.2, 3.3, 3.4, 6.6
    @settings(max_examples=200)
    @given(error=_merge_exceptions, initial_updated=st.booleans())
    def test_merge_failure_is_non_fatal(self, _mock_log, error, initial_updated):
        """Any merge error is handled without exit, deletion, or hint enablement."""
        creator = _make_failure_creator(initial_updated)

        # Non-fatal: the handler must not raise SystemExit (Requirement 3.3).
        try:
            creator._handle_merge_failure(error)
        except SystemExit as exit_error:  # pragma: no cover - fails the property
            pytest.fail(
                f"_handle_merge_failure raised SystemExit for {error!r}: {exit_error}"
            )

        # The repository is never deleted on a merge failure (Requirement 3.2).
        creator.codecommit_client.delete_repository.assert_not_called()

        # The hint stays suppressed regardless of the prior state
        # (Requirements 3.4, 6.6).
        assert creator.test_branch_updated is False

# =============================================================================
# Property 4: Successful merge enables the hint; skip/failure disables it
# =============================================================================

import os
import shutil
import tempfile


# The three mutually exclusive outcomes of the post-seed merge decision. Only a
# successful provider merge should enable the follow-up hint; a skip (via
# --skip-test-merge) or a failure must leave it disabled.
_merge_outcomes = st.sampled_from(["success", "failure", "skip"])

# Both providers exercise the same test_branch_updated state machine through
# their own merge methods.
_merge_providers = st.sampled_from(["codecommit", "github"])


def _make_outcome_creator(provider):
    """Build a RepositoryCreator for hint-gating tests without running __init__.

    The merge methods and ``_skip_test_merge_notice`` touch only
    ``self.provider``, ``self.test_branch_updated``, ``self.repo_name``,
    ``self.codecommit_client``, ``self._github_clone_dir``, and
    ``self.get_clone_urls`` (via the manual-instructions helper on the failure
    path). Constructing via ``__new__`` bypasses the AWS session and settings
    setup in ``__init__`` (unrelated to the hint-gating state machine) and lets
    the property test set just those attributes directly.

    Args:
        provider (str): Repository provider, one of ``'codecommit'`` or
            ``'github'``.

    Returns:
        RepositoryCreator: A minimally-initialized instance whose
            ``test_branch_updated`` starts ``False``.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = "acme-web-app"
    creator.profile = None
    creator.provider = provider
    creator.test_branch_updated = False
    # A mocked CodeCommit client drives the CodeCommit success/failure outcomes.
    creator.codecommit_client = MagicMock()
    # No GitHub clone by default; set per-outcome for the GitHub path.
    creator._github_clone_dir = None
    # Provide clone URLs so manual instructions build without any AWS calls.
    creator.get_clone_urls = MagicMock(
        return_value={'https': 'https://example.com/acme-web-app'}
    )
    return creator


class TestHintGatingProperty:
    """Property 4: hint is enabled iff a provider merge completed without raising."""

    # Feature: create-repo-auto-merge-test-branch, Property 4: For any execution,
    # test_branch_updated is True if and only if a provider merge operation
    # completed without raising. When the merge is skipped via --skip-test-merge
    # or fails, test_branch_updated remains False.
    # Validates: Requirements 6.1, 6.6
    @settings(max_examples=150)
    @given(outcome=_merge_outcomes, provider=_merge_providers, message=st.text(max_size=200))
    def test_hint_gating_on_outcome(self, outcome, provider, message):
        """Only a successful merge enables the hint; skip/failure keep it off."""
        # Skip path: --skip-test-merge notice must never enable the hint. It is
        # provider-independent, so the generated provider is irrelevant here.
        if outcome == "skip":
            creator = _make_outcome_creator(provider)
            with patch("create_repo.Log"):
                creator._skip_test_merge_notice()
            assert creator.test_branch_updated is False
            return

        if provider == "codecommit":
            creator = _make_outcome_creator("codecommit")
            merge = creator.codecommit_client.merge_branches_by_fast_forward
            if outcome == "success":
                # A merge that completes without raising enables the hint.
                merge.return_value = MagicMock()
                with patch("create_repo.Log"):
                    creator._merge_dev_to_test_codecommit()
                assert creator.test_branch_updated is True
            else:  # failure
                # A merge that raises is non-fatal and leaves the hint disabled.
                merge.side_effect = RuntimeError(message)
                with patch("create_repo.Log"):
                    creator._merge_dev_to_test_codecommit()
                assert creator.test_branch_updated is False
        else:  # github
            creator = _make_outcome_creator("github")
            # A real directory satisfies the seed-clone existence guard so the
            # merge call itself decides the outcome.
            with tempfile.TemporaryDirectory() as clone_dir:
                creator._github_clone_dir = clone_dir
                if outcome == "success":
                    with patch("create_repo.Log"), patch("create_repo.GitHubUtils"):
                        creator._merge_dev_to_test_github()
                    assert creator.test_branch_updated is True
                else:  # failure
                    with patch("create_repo.Log"), \
                            patch("create_repo.GitHubUtils") as mock_gh:
                        mock_gh.merge_branches_fast_forward.side_effect = (
                            Exception(message))
                        creator._merge_dev_to_test_github()
                    assert creator.test_branch_updated is False

    # Feature: create-repo-auto-merge-test-branch, Property 4 (success enables):
    # A provider merge that completes without raising sets test_branch_updated
    # True for both providers.
    # Validates: Requirement 6.1
    @settings(max_examples=150)
    @given(provider=_merge_providers)
    def test_success_enables_hint(self, provider):
        """A merge completing without raising enables the follow-up hint."""
        if provider == "codecommit":
            creator = _make_outcome_creator("codecommit")
            creator.codecommit_client.merge_branches_by_fast_forward.return_value = (
                MagicMock())
            with patch("create_repo.Log"):
                creator._merge_dev_to_test_codecommit()
        else:
            creator = _make_outcome_creator("github")
            with tempfile.TemporaryDirectory() as clone_dir:
                creator._github_clone_dir = clone_dir
                with patch("create_repo.Log"), patch("create_repo.GitHubUtils"):
                    creator._merge_dev_to_test_github()
        assert creator.test_branch_updated is True

    # Feature: create-repo-auto-merge-test-branch, Property 4 (failure disables):
    # A provider merge that raises leaves test_branch_updated False for both
    # providers, so the hint stays suppressed.
    # Validates: Requirement 6.6
    @settings(max_examples=150)
    @given(provider=_merge_providers, message=st.text(max_size=200))
    def test_failure_disables_hint(self, provider, message):
        """A merge that raises keeps the hint disabled (non-fatal)."""
        if provider == "codecommit":
            creator = _make_outcome_creator("codecommit")
            creator.codecommit_client.merge_branches_by_fast_forward.side_effect = (
                RuntimeError(message))
            with patch("create_repo.Log"):
                creator._merge_dev_to_test_codecommit()
        else:
            creator = _make_outcome_creator("github")
            with tempfile.TemporaryDirectory() as clone_dir:
                creator._github_clone_dir = clone_dir
                with patch("create_repo.Log"), \
                        patch("create_repo.GitHubUtils") as mock_gh:
                    mock_gh.merge_branches_fast_forward.side_effect = (
                        Exception(message))
                    creator._merge_dev_to_test_github()
        assert creator.test_branch_updated is False

    # Feature: create-repo-auto-merge-test-branch, Property 4 (skip disables):
    # The --skip-test-merge notice never enables the hint.
    # Validates: Requirement 6.6
    @settings(max_examples=150)
    @given(provider=_merge_providers)
    def test_skip_disables_hint(self, provider):
        """Skipping the merge leaves the hint disabled."""
        creator = _make_outcome_creator(provider)
        with patch("create_repo.Log"):
            creator._skip_test_merge_notice()
        assert creator.test_branch_updated is False

# =============================================================================
# Property 5: GitHub merge reuses the seed clone and cleans it up
# =============================================================================


# Filesystem-safe name segments for Hypothesis-driven temp-dir variation. These
# feed the temp directory suffix and any seeded file names/contents so the
# reuse/cleanup behavior is exercised against arbitrary (but valid) clone
# directories rather than a single fixed path.
_dir_name_segment = st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=16)

# Optional nested files placed inside the fake clone so cleanup is verified to
# remove a populated directory tree, not just an empty folder.
_clone_files = st.lists(
    st.tuples(_dir_name_segment, st.text(max_size=64)),
    max_size=5,
)


def _make_github_merge_creator(clone_dir):
    """Build a RepositoryCreator for GitHub reuse/cleanup tests without __init__.

    ``_merge_dev_to_test_github`` and ``_cleanup_github_clone`` touch only
    ``self.provider``, ``self._github_clone_dir``, ``self.test_branch_updated``,
    ``self.repo_name``, and (on the failure path) ``self.get_clone_urls`` via the
    manual-instructions helper. Constructing via ``__new__`` bypasses the AWS
    session and settings setup in ``__init__`` (unrelated to clone reuse/cleanup)
    and lets the property test set just those attributes directly.

    Args:
        clone_dir (str): Path to an existing directory that stands in for the
            GitHub seed clone retained on ``self._github_clone_dir``.

    Returns:
        RepositoryCreator: A minimally-initialized GitHub-provider instance whose
            ``_github_clone_dir`` is ``clone_dir`` and ``test_branch_updated``
            starts ``False``.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = "acme-web-app"
    creator.profile = None
    creator.provider = "github"
    creator.test_branch_updated = False
    creator._github_clone_dir = clone_dir
    # Provide clone URLs so manual instructions build without any AWS calls on
    # the failure path.
    creator.get_clone_urls = MagicMock(
        return_value={'https': 'https://example.com/acme-web-app'}
    )
    return creator


def _populate_clone_dir(clone_dir, files):
    """Write generated files into the fake clone dir so cleanup has real content.

    Args:
        clone_dir (str): Existing directory to populate.
        files (list): List of (name, content) pairs to write as files.
    """
    for index, (name, content) in enumerate(files):
        # Index-prefix the name to avoid collisions when Hypothesis generates
        # duplicate names; keeps every generated file distinct.
        file_path = os.path.join(clone_dir, f"{index}_{name}")
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)


class TestGitHubCloneReuseAndCleanupProperty:
    """Property 5: GitHub merge reuses the seed clone and cleans it up."""

    # Feature: create-repo-auto-merge-test-branch, Property 5: For any successful
    # GitHub merge, the operation uses self._github_clone_dir (no additional clone
    # is created), and after the merge/cleanup the clone directory is removed and
    # self._github_clone_dir is reset to None.
    # Validates: Requirements 5.1, 5.5
    @settings(max_examples=100)
    @given(suffix=_dir_name_segment, files=_clone_files)
    def test_success_reuses_clone_then_cleans_up(self, suffix, files):
        """A successful merge reuses the seed clone, then cleanup removes it."""
        clone_dir = tempfile.mkdtemp(suffix=f"_{suffix}")
        try:
            _populate_clone_dir(clone_dir, files)
            creator = _make_github_merge_creator(clone_dir)

            with patch("create_repo.Log"), \
                    patch("create_repo.GitHubUtils") as mock_gh:
                creator._merge_dev_to_test_github()

                # The merge reuses the existing clone dir (Requirement 5.1): the
                # merge utility is called exactly once with that dir and the
                # dev->test branches.
                mock_gh.merge_branches_fast_forward.assert_called_once_with(
                    clone_dir, source_branch='dev', dest_branch='test'
                )
                # No additional clone is created: the seeding clone helper is
                # never invoked during the merge.
                mock_gh.create_init_commit.assert_not_called()

            # A merge completing without raising enables the follow-up hint.
            assert creator.test_branch_updated is True
            # The clone dir still exists until cleanup runs.
            assert os.path.isdir(clone_dir)

            # Cleanup removes the directory and resets the attribute
            # (Requirement 5.5).
            creator._cleanup_github_clone()
            assert not os.path.exists(clone_dir)
            assert creator._github_clone_dir is None
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)

    # Feature: create-repo-auto-merge-test-branch, Property 5 (failure path): For
    # any failed GitHub merge, the operation still uses self._github_clone_dir (no
    # additional clone), the failure is non-fatal, and cleanup still removes the
    # clone directory and resets self._github_clone_dir to None.
    # Validates: Requirements 5.1, 5.5
    @settings(max_examples=100)
    @given(suffix=_dir_name_segment, files=_clone_files, message=st.text(max_size=200))
    def test_failure_reuses_clone_then_cleans_up(self, suffix, files, message):
        """A failed merge is non-fatal and cleanup still removes the seed clone."""
        clone_dir = tempfile.mkdtemp(suffix=f"_{suffix}")
        try:
            _populate_clone_dir(clone_dir, files)
            creator = _make_github_merge_creator(clone_dir)

            with patch("create_repo.Log"), \
                    patch("create_repo.GitHubUtils") as mock_gh:
                mock_gh.merge_branches_fast_forward.side_effect = Exception(message)

                # A merge failure is non-fatal: it must not raise SystemExit.
                try:
                    creator._merge_dev_to_test_github()
                except SystemExit as exit_error:  # pragma: no cover
                    pytest.fail(
                        f"_merge_dev_to_test_github raised SystemExit: {exit_error}"
                    )

                # Even on failure the existing clone dir is reused, not recloned.
                mock_gh.merge_branches_fast_forward.assert_called_once_with(
                    clone_dir, source_branch='dev', dest_branch='test'
                )
                mock_gh.create_init_commit.assert_not_called()

            # A failed merge leaves the hint suppressed.
            assert creator.test_branch_updated is False

            # Cleanup happens regardless of merge outcome (Requirement 5.5).
            creator._cleanup_github_clone()
            assert not os.path.exists(clone_dir)
            assert creator._github_clone_dir is None
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)

    # Feature: create-repo-auto-merge-test-branch, Property 5 (cleanup idempotent):
    # Once the clone is cleaned up, self._github_clone_dir is None and a second
    # cleanup is a safe no-op that leaves it None.
    # Validates: Requirement 5.5
    @settings(max_examples=100)
    @given(suffix=_dir_name_segment, files=_clone_files)
    def test_cleanup_is_idempotent(self, suffix, files):
        """Cleanup removes the dir once and a repeat call is a safe no-op."""
        clone_dir = tempfile.mkdtemp(suffix=f"_{suffix}")
        try:
            _populate_clone_dir(clone_dir, files)
            creator = _make_github_merge_creator(clone_dir)

            creator._cleanup_github_clone()
            assert not os.path.exists(clone_dir)
            assert creator._github_clone_dir is None

            # A second cleanup with the attribute already None must be a no-op.
            creator._cleanup_github_clone()
            assert creator._github_clone_dir is None
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)

# =============================================================================
# Task 7.1: Unit tests for flag parsing and the CodeCommit merge path
# =============================================================================

from create_repo import parse_args


def _make_codecommit_merge_creator():
    """Build a RepositoryCreator for CodeCommit merge tests without __init__.

    ``_merge_dev_to_test_codecommit()`` touches only ``self.repo_name``,
    ``self.codecommit_client``, ``self.test_branch_updated``, and (on the
    failure path) ``self.get_clone_urls`` via the manual-instructions helper.
    Constructing via ``__new__`` bypasses the AWS session and settings setup in
    ``__init__`` (unrelated to the CodeCommit merge call) and lets these unit
    tests set just those attributes directly.

    Returns:
        RepositoryCreator: A minimally-initialized ``codecommit`` instance whose
            ``test_branch_updated`` starts ``False`` and whose CodeCommit client
            is a ``MagicMock``.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = "acme-web-app"
    creator.profile = None
    creator.provider = "codecommit"
    creator.test_branch_updated = False
    creator.codecommit_client = MagicMock()
    # Provide clone URLs so manual instructions build without any AWS calls on
    # the failure path.
    creator.get_clone_urls = MagicMock(
        return_value={'https': 'https://example.com/acme-web-app'}
    )
    return creator


class TestSkipTestMergeFlagParsing:
    """Unit tests for the --skip-test-merge flag via parse_args().

    Validates: Requirement 2.1
    """

    def test_skip_test_merge_defaults_false(self):
        """When --skip-test-merge is absent, args.skip_test_merge is False."""
        with patch.object(sys, "argv", ["create_repo.py", "my-repo"]):
            args = parse_args()
        assert args.skip_test_merge is False

    def test_skip_test_merge_present_yields_true(self):
        """When --skip-test-merge is present, args.skip_test_merge is True."""
        with patch.object(
            sys, "argv", ["create_repo.py", "my-repo", "--skip-test-merge"]
        ):
            args = parse_args()
        assert args.skip_test_merge is True


@patch("create_repo.Log")
class TestCodeCommitMergePath:
    """Unit tests for the CodeCommit dev->test merge path.

    Validates: Requirements 4.1, 3.2, 3.3
    """

    def test_merge_calls_fast_forward_with_correct_arguments(self, _mock_log):
        """CodeCommit merge issues merge_branches_by_fast_forward correctly."""
        creator = _make_codecommit_merge_creator()

        creator._merge_dev_to_test_codecommit()

        # The boto3 fast-forward merge is invoked once with the exact arguments
        # required by Requirement 4.1.
        creator.codecommit_client.merge_branches_by_fast_forward.assert_called_once_with(
            repositoryName="acme-web-app",
            sourceCommitSpecifier="dev",
            destinationCommitSpecifier="test",
            targetBranch="test",
        )
        # A successful merge enables the follow-up hint.
        assert creator.test_branch_updated is True

    def test_merge_failure_is_non_fatal(self, _mock_log):
        """A CodeCommit merge error does not delete the repo or exit."""
        creator = _make_codecommit_merge_creator()
        creator.codecommit_client.merge_branches_by_fast_forward.side_effect = (
            RuntimeError("fast-forward not possible")
        )

        # Non-fatal: the merge failure must not raise SystemExit (Requirement 3.3).
        try:
            creator._merge_dev_to_test_codecommit()
        except SystemExit as exit_error:  # pragma: no cover - fails the test
            pytest.fail(
                f"_merge_dev_to_test_codecommit raised SystemExit: {exit_error}"
            )

        # The repository is never deleted on a merge failure (Requirement 3.2).
        creator.codecommit_client.delete_repository.assert_not_called()
        # A failed merge leaves the follow-up hint suppressed.
        assert creator.test_branch_updated is False

# =============================================================================
# Task 7.3: Unit tests for skip path, no-source path, and hint output
# =============================================================================

from create_repo import EPILOG


def _make_flow_creator(source, skip_test_merge, provider="github"):
    """Build a RepositoryCreator for create_and_seed_repository flow tests.

    ``create_and_seed_repository()`` orchestrates repository creation, branch
    creation, seeding, and the post-seed merge/skip/cleanup decision. These
    unit tests exercise that orchestration in isolation, so the collaborating
    steps are replaced with ``MagicMock`` instances on the instance. Building
    via ``__new__`` bypasses the AWS session and settings setup in ``__init__``
    (unrelated to the orchestration logic) and lets each test set only the
    attributes the flow reads (``source`` and ``skip_test_merge``).

    Args:
        source (str or None): The resolved seed source. Falsy values (``None``
            or empty string) model the "no Source resolved" case.
        skip_test_merge (bool): The ``--skip-test-merge`` opt-out flag value.
        provider (str): Repository provider, defaults to ``'github'``.

    Returns:
        RepositoryCreator: A minimally-initialized instance whose collaborating
            steps are all ``MagicMock`` so the orchestration can be asserted.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = "acme-web-app"
    creator.profile = None
    creator.provider = provider
    creator.source = source
    creator.skip_test_merge = skip_test_merge
    creator.test_branch_updated = False
    creator._github_clone_dir = None
    # Stub out the collaborating steps so the orchestration is tested in
    # isolation from AWS/GitHub side effects.
    creator._create_repository = MagicMock()
    creator._create_dev_test_branches = MagicMock()
    creator._download_and_extract = MagicMock(return_value="/tmp/extracted-seed")
    creator._seed_repository = MagicMock()
    creator._merge_dev_to_test = MagicMock()
    creator._skip_test_merge_notice = MagicMock()
    creator._cleanup_github_clone = MagicMock()
    return creator


class TestSkipTestMergePath:
    """Unit tests for the --skip-test-merge path in create_and_seed_repository.

    Validates: Requirements 2.2, 2.5
    """

    def test_skip_prevents_merge_and_prints_notice(self):
        """With --skip-test-merge set, the merge is not called; the notice is."""
        creator = _make_flow_creator(
            source="s3://my-bucket/app.zip", skip_test_merge=True
        )

        creator.create_and_seed_repository()

        # Seeding still happens (a Source was resolved).
        creator._seed_repository.assert_called_once()
        # The automatic merge must NOT be attempted when opted out (Req 2.2).
        creator._merge_dev_to_test.assert_not_called()
        # The skip notice IS emitted so the user knows how to merge later
        # (Req 2.5).
        creator._skip_test_merge_notice.assert_called_once()

    def test_skip_cleans_github_clone(self):
        """The reused GitHub clone is cleaned up even when the merge is skipped."""
        creator = _make_flow_creator(
            source="https://github.com/acme/starter", skip_test_merge=True
        )

        creator.create_and_seed_repository()

        # Cleanup runs in the finally block regardless of the merge decision.
        creator._cleanup_github_clone.assert_called_once()

    def test_skip_leaves_test_branch_updated_false(self):
        """Skipping the merge never enables the follow-up hint."""
        creator = _make_flow_creator(
            source="s3://my-bucket/app.zip", skip_test_merge=True
        )

        creator.create_and_seed_repository()

        assert creator.test_branch_updated is False


class TestNoSourcePath:
    """Unit tests for the no-Source path in create_and_seed_repository.

    Validates: Requirements 2.3, 2.4
    """

    def test_no_source_skips_seeding_and_merge(self):
        """When no Source is resolved, neither seeding nor merge is invoked."""
        creator = _make_flow_creator(source=None, skip_test_merge=False)

        creator.create_and_seed_repository()

        # The repository and branch structure are still created.
        creator._create_repository.assert_called_once()
        creator._create_dev_test_branches.assert_called_once()

        # With no Source resolved, nothing downstream of the seed gate runs
        # (Req 2.3): no download, no seeding, no merge, no skip notice, no
        # clone cleanup.
        creator._download_and_extract.assert_not_called()
        creator._seed_repository.assert_not_called()
        creator._merge_dev_to_test.assert_not_called()
        creator._skip_test_merge_notice.assert_not_called()
        creator._cleanup_github_clone.assert_not_called()

    def test_empty_source_string_skips_seeding_and_merge(self):
        """An empty-string Source is treated as unresolved (no seed, no merge)."""
        creator = _make_flow_creator(source="", skip_test_merge=False)

        creator.create_and_seed_repository()

        creator._seed_repository.assert_not_called()
        creator._merge_dev_to_test.assert_not_called()

    def test_no_source_leaves_test_branch_updated_false(self):
        """No Source means no merge, so the follow-up hint stays suppressed."""
        creator = _make_flow_creator(source=None, skip_test_merge=False)

        creator.create_and_seed_repository()

        assert creator.test_branch_updated is False


class TestTestPipelineHintOutput:
    """Example-based unit tests for build_test_pipeline_hint output.

    The follow-up hint is printed by ``main()`` only when
    ``repo_creator.test_branch_updated`` is True (see ``main()``: the hint loop
    is guarded by ``if repo_creator.test_branch_updated:``). Skip and failure
    paths never set that attribute True, so the hint is suppressed on those
    paths. These tests assert the hint's content contract directly.

    Validates: Requirements 6.1, 6.6, 6.3, 6.4, 6.5
    """

    def test_hint_contains_placeholders_and_repo_name_without_profile(self):
        """Without a profile, the command omits --profile and preserves placeholders."""
        creator = _make_creator("acme-web-app", None)

        joined = "\n".join(creator.build_test_pipeline_hint())

        assert _HINT_COMMAND in joined
        assert "<prefix>" in joined
        assert "<project_id>" in joined
        assert "--profile" not in joined
        assert "Use acme-web-app when prompted for the Repository parameter." in joined

    def test_hint_appends_profile_when_provided(self):
        """With a profile, the command appends --profile using the real value."""
        creator = _make_creator("acme-web-app", "acme")

        joined = "\n".join(creator.build_test_pipeline_hint())

        assert _HINT_COMMAND in joined
        assert " --profile acme" in joined
        assert "Use acme-web-app when prompted for the Repository parameter." in joined

    def test_hint_gated_on_test_branch_updated_in_main(self):
        """main() prints the hint only when test_branch_updated is True.

        This documents the gating contract enforced by ``main()``: the hint is
        produced by ``build_test_pipeline_hint()`` and printed inside a
        ``if repo_creator.test_branch_updated:`` guard. The skip and failure
        paths leave ``test_branch_updated`` False, so the hint is never printed.
        """
        # Skip path leaves the attribute False -> main() suppresses the hint.
        skip_creator = _make_flow_creator(
            source="s3://my-bucket/app.zip", skip_test_merge=True
        )
        skip_creator.create_and_seed_repository()
        assert skip_creator.test_branch_updated is False

        # No-source path also leaves it False -> hint suppressed.
        no_source_creator = _make_flow_creator(source=None, skip_test_merge=False)
        no_source_creator.create_and_seed_repository()
        assert no_source_creator.test_branch_updated is False


class TestEpilogDocumentsSkipTestMerge:
    """Unit tests that the help/EPILOG documents --skip-test-merge.

    Validates: Requirements 7.2, 7.3
    """

    def test_epilog_mentions_skip_test_merge_flag(self):
        """The EPILOG references the --skip-test-merge opt-out flag."""
        assert "--skip-test-merge" in EPILOG

    def test_epilog_documents_default_merge_behavior(self):
        """The EPILOG explains dev is merged into test by default when seeded."""
        # The default behavior and its "only when seeded" gate are documented.
        assert "merged into test by default" in EPILOG
        assert "seeded" in EPILOG

    def test_parser_help_includes_skip_test_merge(self, capsys):
        """The argparse --help output documents the --skip-test-merge flag."""
        # Invoking --help makes argparse print the full help (options + epilog)
        # and exit; capture that output and assert the flag is discoverable.
        with patch.object(sys, "argv", ["create_repo.py", "--help"]):
            with pytest.raises(SystemExit):
                parse_args()

        help_output = capsys.readouterr().out
        assert "--skip-test-merge" in help_output
