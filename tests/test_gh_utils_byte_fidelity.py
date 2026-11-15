"""Byte-fidelity tests for GitHubUtils in cli/lib/gh_utils.py.

This module holds the exploration, preservation, and unit tests for the
binary-and-non-utf-8-files-are-seeded-as-base64 fix on the GitHub path.
``create_init_commit`` must write file bytes unchanged and clone with
``core.autocrlf=false``. ``create_branch_structure`` must write its README as
UTF-8 without newline translation. Tests are grouped into classes by concern
so later tasks can append cleanly (preservation and property tests).

``subprocess.run`` is patched, so no git or gh process runs. Test data is
generated inside the tests. No binary fixture is committed.

Feature: binary-and-non-utf-8-files-are-seeded-as-base64
"""

import builtins
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Add cli/ to path so lib.gh_utils resolves its ``lib.logger`` import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from lib.gh_utils import GitHubUtils

REPO_NAME = 'owner/byte-fidelity-test'
SEED_BRANCH = 'dev'
AUTHOR = 'Jane Doe'
EMAIL = 'jane@example.com'

# Contains CRLF and 0xFF, which is not valid UTF-8.
BINARY_BYTES = b'\x89PNG\r\n\x1a\n\x00\xff\xfe\r\n'
NON_ASCII_TEXT = 'caf\u00e9 \u2603 \u65e5\u672c\u8a9e\n'


@pytest.fixture
def mock_run():
    """Patch ``lib.gh_utils.subprocess.run`` and ``lib.gh_utils.Log``.

    Yields:
        MagicMock: The patched ``subprocess.run``.
    """
    with patch('lib.gh_utils.subprocess.run') as run, \
            patch('lib.gh_utils.Log'):
        run.return_value = MagicMock(returncode=0)
        yield run


class TestCreateInitCommitWritesBytes:
    """create_init_commit writes the file bytes and the UTF-8 of str entries."""

    def test_bytes_and_str_entries_are_written_exactly(self, mock_run, tmp_path):
        """Requirement 4.5. Expected to PASS on unfixed code on Linux.

        The ``'wb'`` branch exists for ``bytes`` and the default text
        encoding is UTF-8 on Linux, so this passes before the fix.
        """
        git_dir = tmp_path / 'clone'
        git_dir.mkdir()
        all_files = [
            {'filePath': 'assets/logo.png', 'fileContent': BINARY_BYTES,
             'fileMode': 'NORMAL'},
            {'filePath': 'docs/notes.txt', 'fileContent': NON_ASCII_TEXT,
             'fileMode': 'NORMAL'},
        ]

        GitHubUtils.create_init_commit(
            all_files, REPO_NAME, SEED_BRANCH, AUTHOR, EMAIL, str(git_dir))

        assert (git_dir / 'assets' / 'logo.png').read_bytes() == BINARY_BYTES
        assert (git_dir / 'docs' / 'notes.txt').read_bytes() == \
            NON_ASCII_TEXT.encode('utf-8')


class TestCreateInitCommitCloneArguments:
    """create_init_commit clones with core.autocrlf=false."""

    def test_clone_disables_autocrlf_at_clone_time(self, mock_run, tmp_path):
        """Requirement 4.6. Expected to FAIL on unfixed code."""
        git_dir = tmp_path / 'clone'
        git_dir.mkdir()
        all_files = [
            {'filePath': 'a.txt', 'fileContent': b'a\r\n', 'fileMode': 'NORMAL'},
        ]

        GitHubUtils.create_init_commit(
            all_files, REPO_NAME, SEED_BRANCH, AUTHOR, EMAIL, str(git_dir))

        recorded = [c.args[0] for c in mock_run.call_args_list]
        expected_clone = [
            'gh', 'repo', 'clone', REPO_NAME, str(git_dir),
            '--', '-c', 'core.autocrlf=false',
        ]
        assert expected_clone in recorded, (
            f'clone argv with core.autocrlf=false not found. '
            f'Recorded clone calls: '
            f'{[c for c in recorded if c[:3] == ["gh", "repo", "clone"]]}')

    def test_no_separate_git_config_autocrlf_call(self, mock_run, tmp_path):
        """Requirement 4.6. The setting is applied at clone time only."""
        git_dir = tmp_path / 'clone'
        git_dir.mkdir()
        all_files = [
            {'filePath': 'a.txt', 'fileContent': b'a', 'fileMode': 'NORMAL'},
        ]

        GitHubUtils.create_init_commit(
            all_files, REPO_NAME, SEED_BRANCH, AUTHOR, EMAIL, str(git_dir))

        recorded = [c.args[0] for c in mock_run.call_args_list]
        assert not any(
            argv[:3] == ['git', 'config', 'core.autocrlf'] for argv in recorded)


class TestCreateBranchStructureReadme:
    """create_branch_structure writes README.md as UTF-8 with no translation."""

    def test_readme_bytes_and_open_arguments(self, mock_run, tmp_path, monkeypatch):
        """Requirement 4.11.

        The captured bytes assertions pass on Linux. The ``open`` argument
        assertions are expected to FAIL on unfixed code, because the README
        is opened with ``open(readme_path, 'w')`` and no encoding/newline.
        """
        # create_branch_structure calls os.chdir(temp_dir) and os.chdir('/').
        # Start in tmp_path so monkeypatch restores a valid directory.
        monkeypatch.chdir(tmp_path)
        temp_dir = tmp_path / 'bootstrap'
        temp_dir.mkdir()
        readme_content = '# Caf\u00e9 \u2603\nLine two\n'

        captured = {}

        def side_effect(argv, *args, **kwargs):
            # The function removes temp_dir in its finally block, so read the
            # README at the moment it is staged.
            if argv == ['git', 'add', 'README.md']:
                readme = os.path.join(kwargs['cwd'], 'README.md')
                with open_real(readme, 'rb') as f:
                    captured['bytes'] = f.read()
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        open_real = builtins.open
        readme_open_kwargs = []

        def recording_open(file, *args, **kwargs):
            if os.path.basename(str(file)) == 'README.md' and \
                    str(temp_dir) in str(file):
                mode = args[0] if args else kwargs.get('mode', 'r')
                if 'w' in mode:
                    readme_open_kwargs.append({'args': args, 'kwargs': kwargs})
            return open_real(file, *args, **kwargs)

        with patch('lib.gh_utils.tempfile.mkdtemp', return_value=str(temp_dir)), \
                patch('builtins.open', recording_open):
            GitHubUtils.create_branch_structure(
                REPO_NAME, readme_content, AUTHOR, EMAIL)

        # Bytes on disk when staged: UTF-8, no carriage returns.
        assert captured['bytes'] == readme_content.encode('utf-8')
        assert b'\r' not in captured['bytes']

        # README was opened for writing exactly once, with explicit encoding
        # and newline arguments.
        assert len(readme_open_kwargs) == 1, readme_open_kwargs
        used = readme_open_kwargs[0]['kwargs']
        assert used.get('encoding') == 'utf-8', (
            f'README open() kwargs were {readme_open_kwargs[0]}')
        assert used.get('newline') == '', (
            f'README open() kwargs were {readme_open_kwargs[0]}')


class TestCreateInitCommitPreservation:
    """Property 4: Preservation - the create_init_commit git sequence."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Observed: after the clone, calls run with cwd=git_dir in this order:
    # config user.name, config user.email, checkout <branch>, add ., commit,
    # push origin <branch>. The clone argv is not asserted here, because the
    # fix adds clone arguments.
    # Validates: Requirements 3.6
    def test_git_sequence_after_clone(self, mock_run, tmp_path):
        """Calls after the clone run in the required order with the same text."""
        git_dir = tmp_path / 'clone'
        git_dir.mkdir()
        all_files = [
            {'filePath': 'a.txt', 'fileContent': b'a', 'fileMode': 'NORMAL'},
            {'filePath': 'd/b.txt', 'fileContent': 'b', 'fileMode': 'NORMAL'},
        ]

        GitHubUtils.create_init_commit(
            all_files, REPO_NAME, SEED_BRANCH, AUTHOR, EMAIL, str(git_dir))

        calls = mock_run.call_args_list
        assert calls[0].args[0][:3] == ['gh', 'repo', 'clone']
        assert [c.args[0] for c in calls[1:]] == [
            ['git', 'config', 'user.name', AUTHOR],
            ['git', 'config', 'user.email', EMAIL],
            ['git', 'checkout', SEED_BRANCH],
            ['git', 'add', '.'],
            ['git', 'commit', '-m', 'Seeding repository with 2 files'],
            ['git', 'push', 'origin', SEED_BRANCH],
        ]
        for call in calls[1:]:
            assert call.kwargs['cwd'] == str(git_dir)
            assert call.kwargs['check'] is True
            assert call.kwargs['capture_output'] is True


class TestCreateBranchStructurePreservation:
    """Property 4: Preservation - the create_branch_structure git sequence."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Observed: clone (argv without core.autocrlf), user.name, user.email,
    # checkout -B main, add README.md, commit, push main, then the test and
    # dev branches are created and pushed. Every call after the clone runs
    # with cwd=temp_dir, and temp_dir is removed afterward.
    # Validates: Requirements 3.11
    def test_clone_branches_and_cleanup(self, mock_run, tmp_path, monkeypatch):
        """The clone is unchanged and the main, test, dev branches are pushed."""
        # The function calls os.chdir(temp_dir) and os.chdir('/'); start in
        # tmp_path so monkeypatch restores a valid directory.
        monkeypatch.chdir(tmp_path)
        temp_dir = tmp_path / 'bootstrap'
        temp_dir.mkdir()

        with patch('lib.gh_utils.tempfile.mkdtemp', return_value=str(temp_dir)):
            GitHubUtils.create_branch_structure(
                REPO_NAME, '# Readme\n', AUTHOR, EMAIL)

        calls = mock_run.call_args_list
        assert calls[0].args[0] == ['gh', 'repo', 'clone', REPO_NAME, str(temp_dir)]
        assert [c.args[0] for c in calls[1:]] == [
            ['git', 'config', 'user.name', AUTHOR],
            ['git', 'config', 'user.email', EMAIL],
            ['git', 'checkout', '-B', 'main'],
            ['git', 'add', 'README.md'],
            ['git', 'commit', '-m', 'Initial README.md commit'],
            ['git', 'push', '-u', 'origin', 'main'],
            ['git', 'checkout', '-b', 'test'],
            ['git', 'push', '-u', 'origin', 'test'],
            ['git', 'checkout', '-b', 'dev'],
            ['git', 'push', '-u', 'origin', 'dev'],
        ]
        for call in calls[1:]:
            assert call.kwargs['cwd'] == str(temp_dir)
        assert not temp_dir.exists()


class TestCreateInitCommitProperties:
    """Property-based tests for the bytes written by create_init_commit."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 2: For any list of entries, create_init_commit writes each
    # file with the given bytes, or the UTF-8 encoding of a str entry. No
    # text-mode open is used, so no newline translation occurs.
    # Validates: Requirements 2.4, 2.5
    @settings(max_examples=100)
    @given(contents=st.lists(st.one_of(
        st.binary(),
        st.text(alphabet=st.characters(blacklist_categories=('Cs',))),
    )))
    def test_each_entry_is_written_as_bytes_or_utf8(self, contents):
        """Each file holds the bytes, or the UTF-8 encoding of the str."""
        all_files = [
            {'filePath': f'file_{index}.bin', 'fileContent': content,
             'fileMode': 'NORMAL'}
            for index, content in enumerate(contents)
        ]

        with tempfile.TemporaryDirectory() as git_dir, \
                patch('lib.gh_utils.subprocess.run') as run, \
                patch('lib.gh_utils.Log'):
            run.return_value = MagicMock(returncode=0)

            GitHubUtils.create_init_commit(
                all_files, REPO_NAME, SEED_BRANCH, AUTHOR, EMAIL, git_dir)

            for index, content in enumerate(contents):
                expected = content if isinstance(content, bytes) \
                    else content.encode('utf-8')
                with open(os.path.join(git_dir, f'file_{index}.bin'), 'rb') as f:
                    assert f.read() == expected
