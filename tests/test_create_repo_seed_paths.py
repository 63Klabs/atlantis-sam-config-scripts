"""Tests for CodeCommit seed file paths in cli/create_repo.py.

This module holds the exploration, preservation, and helper tests for the
git-for-windows-bug-in-file-seeding fix. Tests are grouped into classes by
concern so later tasks can append cleanly.

The module is imported as ``create_repo`` and the helper is reached as
``create_repo._to_codecommit_path`` only inside the tests that need it, so
this file imports before the helper exists.

Feature: git-for-windows-bug-in-file-seeding
"""

import base64
import os
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import create_repo
from create_repo import RepositoryCreator


# Nested starter-style tree used by the tests in this module. Paths are
# written with "/" and converted per platform when the files are created.
SEED_TREE_PATHS = [
    'README.md',
    '.github/workflows/deploy-to-s3.yml',
    'application-infrastructure/build-scripts/generate-put-ssm.py',
]


def _build_seed_tree(root: Path) -> None:
    """Create the nested sample tree under root."""
    for relative in SEED_TREE_PATHS:
        target = root.joinpath(*relative.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"content of {relative}\n", encoding='utf-8')


def _build_creator() -> RepositoryCreator:
    """Build a RepositoryCreator without running __init__ (no AWS session)."""
    creator = RepositoryCreator.__new__(RepositoryCreator)
    # Only used on the error path of _seed_collect_files.
    creator.codecommit_client = MagicMock()
    creator.repo_name = 'seed-paths-test'
    return creator


class TestSeedCollectFilesWindowsPaths:
    """Property 1: Bug Condition - Windows relative paths become "/"-separated."""

    # Feature: git-for-windows-bug-in-file-seeding, Property 1: Bug Condition.
    # Root cause: on Windows, os.path is ntpath, and
    # ntpath.relpath('C:\\t\\.github\\w\\d.yml', 'C:\\t') returns
    # '.github\\w\\d.yml'. _seed_collect_files stores that value as filePath,
    # and CodeCommit treats "\" as part of a file name, so nested files are
    # created as single flat files with "\" in their names.
    # Validates: Requirements 1.1, 1.2, 2.1, 2.4, 4.1, 4.8
    def test_file_paths_use_forward_slashes_when_relpath_returns_backslashes(
        self, tmp_path
    ):
        """filePath values contain no "\\" and match the "/"-separated tree."""
        _build_seed_tree(tmp_path)
        creator = _build_creator()
        real_relpath = os.path.relpath

        def windows_style_relpath(path, start=os.curdir):
            return real_relpath(path, start).replace('/', '\\')

        # Narrow patch: only around the call under test. os.sep is patched as
        # well because the fix reads the host separator (os.sep) to decide
        # whether to normalize. A Windows host has both a "\\"-returning
        # relpath and os.sep == "\\"; patching only relpath would leave the
        # Linux os.sep ("/"), where the helper is intentionally the identity.
        with mock.patch.object(
            create_repo.os.path, 'relpath', side_effect=windows_style_relpath
        ), mock.patch.object(create_repo.os, 'sep', '\\'), mock.patch.object(
            create_repo.os, 'altsep', '/'
        ):
            collected = creator._seed_collect_files(str(tmp_path))

        actual_paths = sorted(entry['filePath'] for entry in collected)
        expected_paths = sorted(SEED_TREE_PATHS)

        for file_path in actual_paths:
            assert '\\' not in file_path, (
                f"filePath contains a backslash: {file_path!r}"
            )
        assert actual_paths == expected_paths


class TestSeedCollectFilesPreservation:
    """Property 2: Preservation - POSIX output is unchanged, and shape is correct.

    These tests use real temporary trees with no patching. They encode the
    behavior observed on the unfixed code on a POSIX host, so they must pass
    both before and after the fix.
    """

    # Feature: git-for-windows-bug-in-file-seeding, Property 2: Preservation.
    # Validates: Requirements 3.1, 4.6
    def test_file_paths_equal_relpath_and_expected_slash_set_on_real_tree(
        self, tmp_path
    ):
        """filePath values equal os.path.relpath and the "/"-separated set."""
        _build_seed_tree(tmp_path)
        creator = _build_creator()

        collected = creator._seed_collect_files(str(tmp_path))

        expected_from_relpath = sorted(
            os.path.relpath(os.path.join(root, name), str(tmp_path))
            for root, _, names in os.walk(str(tmp_path))
            for name in names
        )
        actual_paths = sorted(entry['filePath'] for entry in collected)

        assert actual_paths == expected_from_relpath
        assert actual_paths == sorted(SEED_TREE_PATHS)

    # Feature: git-for-windows-bug-in-file-seeding, Property 3: Output shape.
    # Validates: Requirements 2.6, 4.6
    def test_file_paths_are_relative_without_parent_segments_or_backslashes(
        self, tmp_path
    ):
        """Every filePath is relative, has no ".." segment, and no "\\"."""
        _build_seed_tree(tmp_path)
        creator = _build_creator()

        collected = creator._seed_collect_files(str(tmp_path))

        assert len(collected) == len(SEED_TREE_PATHS)
        for entry in collected:
            file_path = entry['filePath']
            assert not file_path.startswith('/'), (
                f"filePath is not relative: {file_path!r}"
            )
            assert '..' not in file_path.split('/'), (
                f"filePath has a '..' segment: {file_path!r}"
            )
            assert '\\' not in file_path, (
                f"filePath contains a backslash: {file_path!r}"
            )

    # Feature: git-for-windows-bug-in-file-seeding, Preservation of root files.
    # Validates: Requirements 3.2
    def test_root_level_file_keeps_its_bare_name(self, tmp_path):
        """A file with no directory component keeps its bare file name."""
        (tmp_path / 'README.md').write_text('root file\n', encoding='utf-8')
        creator = _build_creator()

        collected = creator._seed_collect_files(str(tmp_path))

        assert [entry['filePath'] for entry in collected] == ['README.md']

    # Feature: git-for-windows-bug-in-file-seeding, Preservation of content.
    # Validates: Requirements 3.4
    def test_utf8_file_content_is_text_and_mode_is_normal(self, tmp_path):
        """A UTF-8 file is returned as decoded text with fileMode NORMAL."""
        text = 'caf\u00e9 \u2713 plain text\n'
        nested = tmp_path / 'docs'
        nested.mkdir()
        (nested / 'notes.txt').write_bytes(text.encode('utf-8'))
        creator = _build_creator()

        collected = creator._seed_collect_files(str(tmp_path))

        assert len(collected) == 1
        assert collected[0]['filePath'] == 'docs/notes.txt'
        assert collected[0]['fileContent'] == text
        assert collected[0]['fileMode'] == 'NORMAL'

    # Feature: git-for-windows-bug-in-file-seeding, Preservation of content.
    # Validates: Requirements 3.4
    def test_non_utf8_file_content_is_base64_text_and_mode_is_normal(
        self, tmp_path
    ):
        """A non-UTF-8 file is returned as base64 text with fileMode NORMAL."""
        raw = b'\xff\xfe\x00\x80binary\x81\x00'
        with pytest.raises(UnicodeDecodeError):
            raw.decode('utf-8')
        nested = tmp_path / 'assets'
        nested.mkdir()
        (nested / 'blob.bin').write_bytes(raw)
        creator = _build_creator()

        collected = creator._seed_collect_files(str(tmp_path))

        assert len(collected) == 1
        assert collected[0]['filePath'] == 'assets/blob.bin'
        assert collected[0]['fileContent'] == base64.b64encode(raw).decode('utf-8')
        assert base64.b64decode(collected[0]['fileContent']) == raw
        assert collected[0]['fileMode'] == 'NORMAL'


# Path segments for Property 1: non-empty text that excludes both separators
# and NUL, so joining and splitting on "\" is unambiguous.
_path_segment = st.text(
    alphabet=st.characters(blacklist_characters='/\\\x00'),
    min_size=1,
)


class TestToCodecommitPathHelper:
    """Unit tests for the _to_codecommit_path helper."""

    # Feature: git-for-windows-bug-in-file-seeding, Property 1: Bug Condition
    # (nested Windows path example).
    # Validates: Requirements 2.2, 4.2
    def test_windows_nested_path_becomes_forward_slashes(self):
        """A "\\"-separated nested path is converted to "/" separators."""
        result = create_repo._to_codecommit_path(
            '.github\\workflows\\deploy.yml', sep='\\'
        )

        assert result == '.github/workflows/deploy.yml'

    # Feature: git-for-windows-bug-in-file-seeding, Property 1: Bug Condition
    # (root file example).
    # Validates: Requirements 2.2, 4.3
    def test_windows_root_file_is_unchanged(self):
        """A path with no separator keeps its bare name."""
        result = create_repo._to_codecommit_path('README.md', sep='\\')

        assert result == 'README.md'

    # Feature: git-for-windows-bug-in-file-seeding, Property 2: Preservation
    # (POSIX backslash file name example).
    # Validates: Requirements 4.4
    def test_posix_backslash_in_file_name_is_preserved(self):
        """With sep "/" a backslash is part of the file name and is kept."""
        result = create_repo._to_codecommit_path('weird\\name.txt', sep='/')

        assert result == 'weird\\name.txt'

    # Feature: git-for-windows-bug-in-file-seeding, Property 1: Bug Condition
    # (Windows separator pair).
    # Validates: Requirements 2.2
    def test_windows_altsep_slash_gives_same_result_as_sep_alone(self):
        """altsep "/" (the Windows pair) does not change the result."""
        path = '.github\\workflows\\deploy.yml'

        with_altsep = create_repo._to_codecommit_path(
            path, sep='\\', altsep='/'
        )
        without_altsep = create_repo._to_codecommit_path(path, sep='\\')

        assert with_altsep == without_altsep == '.github/workflows/deploy.yml'


class TestToCodecommitPathProperties:
    """Property-based tests for the _to_codecommit_path helper."""

    # Feature: git-for-windows-bug-in-file-seeding, Property 1: For any list of
    # non-empty segments without "/", "\" or NUL, joining with "\" and
    # normalizing with sep="\" equals joining the segments with "/".
    # Validates: Requirements 2.1, 2.2, 2.4, 4.5
    @settings(max_examples=200)
    @given(segments=st.lists(_path_segment, min_size=1))
    def test_backslash_joined_segments_become_slash_joined(self, segments):
        """Windows-style joined segments normalize to "/"-joined segments."""
        result = create_repo._to_codecommit_path('\\'.join(segments), sep='\\')

        assert result == '/'.join(segments)

    # Feature: git-for-windows-bug-in-file-seeding, Property 2: For any string
    # s, _to_codecommit_path(s, sep="/") returns s unchanged, including strings
    # that contain "\".
    # Validates: Requirements 3.1, 3.3, 4.4
    @settings(max_examples=200)
    @given(s=st.text())
    def test_posix_separator_is_identity(self, s):
        """With sep "/" the helper returns its input unchanged."""
        assert create_repo._to_codecommit_path(s, sep='/') == s
