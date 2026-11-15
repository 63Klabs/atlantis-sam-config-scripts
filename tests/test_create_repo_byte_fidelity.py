"""Byte-fidelity tests for seeding in cli/create_repo.py.

This module holds the exploration, preservation, and unit tests for the
binary-and-non-utf-8-files-are-seeded-as-base64 fix. File content must reach
both providers as the file's bytes, and extraction must write bytes. Tests are
grouped into classes by concern so later tasks can append cleanly (extraction
tests, preservation tests, and property tests).

Test data is generated inside the tests. No binary fixture is committed.

Feature: binary-and-non-utf-8-files-are-seeded-as-base64
"""

import builtins
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import create_repo
from create_repo import RepositoryCreator


# PNG signature plus bytes that are not valid UTF-8 (0xFF, 0xFE) and a NUL.
PNG_LIKE_BYTES = b'\x89PNG\r\n\x1a\n\x00\xff\xfe'
# Latin-1 text: 0xE9 alone is not valid UTF-8.
LATIN1_BYTES = 'caf\u00e9'.encode('latin-1')

REPO_NAME = 'byte-fidelity-test'


def _build_creator(provider: str = 'codecommit') -> RepositoryCreator:
    """Build a RepositoryCreator without running __init__ (no AWS session).

    Args:
        provider (str): ``'codecommit'`` or ``'github'``.

    Returns:
        RepositoryCreator: Minimally initialized instance with a mocked
        ``codecommit_client`` and mocked commit author/email lookups.
    """
    creator = RepositoryCreator.__new__(RepositoryCreator)
    creator.repo_name = REPO_NAME
    creator.provider = provider
    creator.codecommit_client = MagicMock()
    creator.codecommit_client.get_branch.return_value = {
        'branch': {'commitId': 'c0'}
    }
    creator.codecommit_client.create_commit.return_value = {'commitId': 'c1'}
    creator.get_init_commit_author = MagicMock(return_value='author')
    creator.get_init_commit_email = MagicMock(return_value='a@example.com')
    return creator


def _write_file(root: Path, relative: str, data: bytes) -> None:
    """Write raw bytes to ``root/relative``, creating parent directories."""
    target = root.joinpath(*relative.split('/'))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _by_path(entries):
    """Index collected file entries by their ``filePath``."""
    return {entry['filePath']: entry for entry in entries}


class TestSeedCollectFilesBytes:
    """Property 1: Bug Condition - collected fileContent is the file's bytes."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: Bug Condition.
    # Root cause: _seed_collect_files tries content.decode('utf-8') and, on
    # UnicodeDecodeError, stores base64.b64encode(content).decode('utf-8') as
    # fileContent. CodeCommit stores that str as the file, so a binary file
    # is committed as base64 text.
    # Validates: Requirements 1.1, 1.2, 2.1, 2.3, 4.4
    def test_png_like_file_content_is_bytes_equal_to_file(self, tmp_path):
        """A PNG-like file is collected as the same bytes, not base64 text."""
        _write_file(tmp_path, 'logo.png', PNG_LIKE_BYTES)
        creator = _build_creator()

        entries = _by_path(creator._seed_collect_files(str(tmp_path)))

        content = entries['logo.png']['fileContent']
        assert isinstance(content, bytes), (
            f"fileContent is {type(content).__name__} {content!r}, "
            "expected bytes"
        )
        assert content == PNG_LIKE_BYTES

    # Validates: Requirements 1.1, 1.2, 2.1, 2.3, 4.4
    def test_latin1_text_file_content_is_bytes_equal_to_file(self, tmp_path):
        """A Latin-1 text file is collected as the same bytes."""
        _write_file(tmp_path, 'notes.txt', LATIN1_BYTES)
        creator = _build_creator()

        entries = _by_path(creator._seed_collect_files(str(tmp_path)))

        content = entries['notes.txt']['fileContent']
        assert isinstance(content, bytes), (
            f"fileContent is {type(content).__name__} {content!r}, "
            "expected bytes"
        )
        assert content == LATIN1_BYTES


class TestSeedRepositoryCodecommitPutFiles:
    """Property 1: Bug Condition - CodeCommit putFiles carry the file's bytes."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: Bug Condition.
    # Validates: Requirements 1.1, 1.2, 2.1, 2.3, 4.7
    def test_put_files_file_content_is_bytes_equal_to_file(self):
        """create_commit receives putFiles whose fileContent equals file bytes."""
        temp_dir = tempfile.mkdtemp(prefix='byte-fidelity-')
        try:
            root = Path(temp_dir)
            _write_file(root, 'logo.png', PNG_LIKE_BYTES)
            _write_file(root, 'docs/notes.txt', LATIN1_BYTES)
            creator = _build_creator()

            # _seed_repository_codecommit removes temp_dir when it finishes.
            with mock.patch.object(create_repo, 'Log'), \
                    mock.patch.object(create_repo.click, 'echo'):
                creator._seed_repository_codecommit(temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        create_commit = creator.codecommit_client.create_commit
        assert create_commit.call_count == 1
        put_files = create_commit.call_args.kwargs['putFiles']
        entries = _by_path(put_files)
        assert set(entries) == {'logo.png', 'docs/notes.txt'}

        expected = {
            'logo.png': PNG_LIKE_BYTES,
            'docs/notes.txt': LATIN1_BYTES,
        }
        for file_path, data in expected.items():
            content = entries[file_path]['fileContent']
            assert isinstance(content, bytes), (
                f"putFiles {file_path} fileContent is "
                f"{type(content).__name__} {content!r}, expected bytes"
            )
            assert content == data


# Members of the zip used by the extraction tests. ``config.yaml`` is a UTF-8
# CRLF file with an extension in ``text_extensions``. It is the member that
# reaches ``Path.write_text`` in the unfixed extraction code: ``.gitignore``
# has an empty ``Path.suffix`` and ``notes.txt`` is not valid UTF-8, so the
# unfixed code writes both with ``write_bytes``.
CRLF_BYTES = b'a\r\nb\r\n'
EXTRACTION_MEMBERS = {
    '.gitignore': CRLF_BYTES,
    'notes.txt': LATIN1_BYTES,
    'logo.png': PNG_LIKE_BYTES,
    'config.yaml': b'key: value\r\nother: 1\r\n',
}


def _write_zip(zip_path: Path, members: dict, prefix: str = '') -> None:
    """Write a zip holding ``members`` under an optional top-level directory.

    Args:
        zip_path (Path): Zip file to create.
        members (dict): Member name mapped to its bytes.
        prefix (str): Top-level directory (with trailing ``/``) shared by all
            members, as in a GitHub archive. Empty for no common prefix.
    """
    with zipfile.ZipFile(zip_path, 'w') as zip_file:
        if prefix:
            zip_file.writestr(prefix, b'')
        for name, data in members.items():
            zip_file.writestr(prefix + name, data)


def _build_extraction_creator(source_type: str, zip_path: Path) -> RepositoryCreator:
    """Build a creator whose download step copies ``zip_path`` into place.

    Args:
        source_type (str): ``'s3'`` or ``'github'``.
        zip_path (Path): Zip that the mocked download writes to the target.

    Returns:
        RepositoryCreator: Minimally initialized instance (no AWS session).
    """
    creator = _build_creator('codecommit' if source_type == 's3' else 'github')
    creator.source_type = source_type
    creator.skip_test_merge = False
    creator.cleanup_on_failure = False
    creator._delete_codecommit_repository = MagicMock()
    if source_type == 's3':
        creator.source = 's3://bucket/starter.zip'

        def copy_zip(bucket, key, path):
            shutil.copyfile(zip_path, path)

        creator.s3_client = MagicMock()
        creator.s3_client_anonymous = MagicMock()
        creator.s3_client.download_file.side_effect = copy_zip
        creator.is_bucket_public = MagicMock(return_value=False)
    else:
        creator.source = 'https://github.com/acme/starter'
    return creator


class TestDownloadAndExtractBytes:
    """Property 1: Bug Condition - extraction writes the zip member's bytes."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: Bug Condition.
    # Root cause: _download_and_extract_into writes members classified as text
    # with Path.write_text, which opens the file in text mode. On Windows,
    # text mode translates '\n' to '\r\n', so b'a\r\nb\r\n' is written as
    # b'a\r\r\nb\r\r\n'. This is reproducible on any platform with
    # open(path, 'w', newline='\r\n'). The fix writes every member with
    # write_bytes. Path.write_text is patched to raise so that a text-mode
    # write is caught on Linux and macOS too, not only on Windows.
    # The unfixed code catches the AssertionError inside the extraction
    # try/except and calls sys.exit(1), so the test also records each call.
    # Validates: Requirements 1.5, 2.7, 2.9, 4.8
    @pytest.mark.parametrize('source_type', ['s3', 'github'])
    def test_extracted_files_equal_zip_members_without_write_text(
        self, tmp_path, source_type
    ):
        """Extracted files equal the zip members and write_text is never used."""
        prefix = 'starter-main/' if source_type == 'github' else ''
        zip_path = tmp_path / 'starter.zip'
        _write_zip(zip_path, EXTRACTION_MEMBERS, prefix)
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        creator = _build_extraction_creator(source_type, zip_path)

        write_text_calls = []

        def forbid_write_text(self, *args, **kwargs):
            write_text_calls.append(self.name)
            raise AssertionError('write_text must not be used')

        def copy_github_zip(url, path):
            shutil.copyfile(zip_path, path)

        exit_code = None
        with mock.patch.object(create_repo, 'Log'), \
                mock.patch.object(create_repo.click, 'echo'), \
                mock.patch.object(
                    create_repo.GitHubUtils, 'download_zip_from_url',
                    side_effect=copy_github_zip,
                ), \
                mock.patch.object(Path, 'write_text', forbid_write_text):
            try:
                creator._download_and_extract_into(str(out_dir))
            except SystemExit as exit_info:
                exit_code = exit_info.code

        assert write_text_calls == [], (
            f"write_text must not be used, but was called for "
            f"{write_text_calls} (source_type={source_type}); "
            f"extraction exit code: {exit_code}"
        )
        assert exit_code is None, f"extraction exited with code {exit_code}"
        for name, data in EXTRACTION_MEMBERS.items():
            extracted = out_dir / name
            assert extracted.is_file(), f"{name} was not extracted"
            assert extracted.read_bytes() == data, (
                f"{name} differs from the zip member: "
                f"{extracted.read_bytes()!r} != {data!r}"
            )


def as_bytes(value):
    """Return ``value`` as bytes so a test passes before and after the fix.

    Before the fix valid UTF-8 content is collected as a ``str``. After the
    fix it is collected as ``bytes``. Both encode to the same bytes.

    Args:
        value (bytes | str): A collected ``fileContent`` value.

    Returns:
        bytes: ``value`` unchanged for ``bytes``, else its UTF-8 encoding.
    """
    if isinstance(value, bytes):
        return value
    return value.encode('utf-8')


class TestSeedCollectFilesPreservation:
    """Property 4: Preservation - valid UTF-8 text keeps the same bytes.

    These tests encode behavior observed on the unfixed code. They must pass
    both before and after the fix.
    """

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Validates: Requirements 3.1
    def test_valid_utf8_text_keeps_same_bytes(self, tmp_path):
        """ASCII and non-ASCII UTF-8 files are collected with equal bytes."""
        files = {
            'ascii.txt': b'hello world\n',
            'unicode.txt': 'caf\u00e9 \u2603 \u65e5\u672c\u8a9e\n'.encode('utf-8'),
            'crlf.txt': b'a\r\nb\r\n',
        }
        for name, data in files.items():
            _write_file(tmp_path, name, data)
        creator = _build_creator()

        entries = _by_path(creator._seed_collect_files(str(tmp_path)))

        assert set(entries) == set(files)
        for name, data in files.items():
            assert as_bytes(entries[name]['fileContent']) == data

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Validates: Requirements 3.1, 4.3
    @settings(max_examples=200)
    @given(text=st.text(alphabet=st.characters(blacklist_categories=('Cs',))))
    def test_any_utf8_text_keeps_same_bytes(self, text):
        """For any text written as UTF-8, the collected bytes equal the text."""
        expected = text.encode('utf-8')
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write bytes so no newline translation affects the file.
            with open(os.path.join(temp_dir, 'file.txt'), 'wb') as handle:
                handle.write(expected)
            creator = _build_creator()

            entries = creator._seed_collect_files(temp_dir)

        assert len(entries) == 1
        assert as_bytes(entries[0]['fileContent']) == expected

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Validates: Requirements 2.10, 3.2
    def test_nested_files_have_slash_paths_and_normal_mode(self, tmp_path):
        """filePath is relative and "/"-separated, and fileMode is NORMAL."""
        paths = ['top.txt', 'a/b.txt', 'a/b/c/deep.txt']
        for relative in paths:
            _write_file(tmp_path, relative, b'x')
        creator = _build_creator()

        entries = creator._seed_collect_files(str(tmp_path))

        assert sorted(e['filePath'] for e in entries) == sorted(paths)
        for entry in entries:
            assert entry['fileMode'] == 'NORMAL'
            assert not entry['filePath'].startswith('/')
            assert '\\' not in entry['filePath']
            assert '..' not in entry['filePath'].split('/')

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Observed: on a read failure the method echoes an error naming the file,
    # logs it, deletes the CodeCommit repository only for the CodeCommit
    # provider, and exits with status 1.
    # Validates: Requirements 3.3
    @pytest.mark.parametrize('provider', ['codecommit', 'github'])
    def test_read_failure_reports_cleans_up_and_exits(self, tmp_path, provider):
        """A failed read prints the error, cleans up per provider, exits 1."""
        _write_file(tmp_path, 'bad.txt', b'data')
        creator = _build_creator(provider)
        creator._delete_codecommit_repository = MagicMock()
        real_open = builtins.open

        def failing_open(file, *args, **kwargs):
            if os.path.basename(str(file)) == 'bad.txt':
                raise OSError('simulated read failure')
            return real_open(file, *args, **kwargs)

        with mock.patch.object(create_repo, 'Log') as log, \
                mock.patch.object(create_repo.click, 'echo') as echo, \
                mock.patch('builtins.open', failing_open):
            with pytest.raises(SystemExit) as exit_info:
                creator._seed_collect_files(str(tmp_path))

        assert exit_info.value.code == 1
        echoed = ' '.join(str(c.args[0]) for c in echo.call_args_list)
        assert 'Error processing file bad.txt' in echoed
        assert log.error.called
        assert 'bad.txt' in str(log.error.call_args)
        if provider == 'codecommit':
            creator._delete_codecommit_repository.assert_called_once_with()
        else:
            creator._delete_codecommit_repository.assert_not_called()


# Members for the extraction layout test. All members are LF-only ASCII, so
# the result does not depend on how extraction writes them.
LAYOUT_MEMBERS = {
    'existing.txt': b'new content\n',
    'src/app.py': b'print("hi")\n',
    'data.bin': b'\x00\x01\x02\x03',
    'empty-dir/': b'',
}


class TestExtractionPreservation:
    """Property 4: Preservation - extraction layout and reporting are unchanged."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 4: Preservation.
    # Observed: directory entries are created, an existing file is replaced,
    # the GitHub common prefix is stripped, source.zip is removed, and
    # "Extracted files:" is echoed with the count of files left in the
    # directory.
    # Validates: Requirements 3.7
    @pytest.mark.parametrize('source_type', ['s3', 'github'])
    def test_layout_replace_prefix_zip_removal_and_count(
        self, tmp_path, source_type
    ):
        """Extraction keeps its layout and reports the extracted file count."""
        prefix = 'starter-main/' if source_type == 'github' else ''
        zip_path = tmp_path / 'starter.zip'
        _write_zip(zip_path, LAYOUT_MEMBERS, prefix)
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        (out_dir / 'existing.txt').write_bytes(b'old content\n')
        creator = _build_extraction_creator(source_type, zip_path)

        def copy_github_zip(url, path):
            shutil.copyfile(zip_path, path)

        with mock.patch.object(create_repo, 'Log'), \
                mock.patch.object(create_repo.click, 'echo') as echo, \
                mock.patch.object(
                    create_repo.GitHubUtils, 'download_zip_from_url',
                    side_effect=copy_github_zip,
                ):
            result = creator._download_and_extract_into(str(out_dir))

        assert result == str(out_dir)
        # Directory entry created, existing file replaced.
        assert (out_dir / 'empty-dir').is_dir()
        assert (out_dir / 'existing.txt').read_bytes() == b'new content\n'
        assert (out_dir / 'src' / 'app.py').read_bytes() == b'print("hi")\n'
        assert (out_dir / 'data.bin').read_bytes() == b'\x00\x01\x02\x03'
        # Common prefix stripped for GitHub, never present for S3.
        assert not (out_dir / 'starter-main').exists()
        # Downloaded zip removed.
        assert not (out_dir / 'source.zip').exists()
        # Count of files echoed.
        echoed = [str(c.args[0]) for c in echo.call_args_list]
        count_lines = [line for line in echoed if 'Extracted files:' in line]
        assert len(count_lines) == 1
        assert '3' in count_lines[0]
        assert sum(len(files) for _, _, files in os.walk(out_dir)) == 3


class TestSeedCollectFilesUnitCases:
    """Unit tests: collected fileContent is bytes for common content kinds."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: Bug Condition (valid UTF-8 text example).
    # Validates: Requirements 2.1, 4.4
    def test_valid_utf8_text_is_bytes_equal_to_file(self, tmp_path):
        """Valid UTF-8 text is collected as the same bytes, not a str."""
        data = 'caf\u00e9 \u2603 \u65e5\u672c\u8a9e\nsecond line\n'.encode('utf-8')
        _write_file(tmp_path, 'readme.md', data)
        creator = _build_creator()

        entries = _by_path(creator._seed_collect_files(str(tmp_path)))

        content = entries['readme.md']['fileContent']
        assert isinstance(content, bytes)
        assert content == data

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: Bug Condition (UTF-8 byte order mark example).
    # Validates: Requirements 2.1, 4.4
    def test_utf8_byte_order_mark_is_preserved(self, tmp_path):
        """A leading UTF-8 BOM is kept in the collected bytes."""
        data = b'\xef\xbb\xbf' + 'name: caf\u00e9\n'.encode('utf-8')
        _write_file(tmp_path, 'bom.yaml', data)
        creator = _build_creator()

        entries = _by_path(creator._seed_collect_files(str(tmp_path)))

        content = entries['bom.yaml']['fileContent']
        assert isinstance(content, bytes)
        assert content == data
        assert content.startswith(b'\xef\xbb\xbf')

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: Bug Condition (empty file example).
    # Validates: Requirements 2.1, 4.4
    def test_empty_file_is_empty_bytes(self, tmp_path):
        """An empty file is collected as b'' (a bytes object, not '')."""
        _write_file(tmp_path, '.gitkeep', b'')
        creator = _build_creator()

        entries = _by_path(creator._seed_collect_files(str(tmp_path)))

        content = entries['.gitkeep']['fileContent']
        assert isinstance(content, bytes)
        assert content == b''


class TestSeedCollectFilesProperties:
    """Property-based tests for collection of arbitrary bytes."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 1: For any bytes written to a file, _seed_collect_files returns
    # one entry whose fileContent is a bytes object equal to the input.
    # Validates: Requirements 2.1, 2.2, 4.3
    @settings(max_examples=200)
    @given(data=st.binary())
    def test_collected_file_content_equals_any_bytes(self, data):
        """Arbitrary bytes are collected unchanged as a bytes object."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, 'payload.bin'), 'wb') as handle:
                handle.write(data)
            creator = _build_creator()

            entries = creator._seed_collect_files(temp_dir)

        assert len(entries) == 1
        content = entries[0]['fileContent']
        assert isinstance(content, bytes)
        assert content == data


class TestDownloadAndExtractProperties:
    """Property-based test for extraction of an arbitrary zip member."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Property 3: For any bytes stored as a zip member,
    # _download_and_extract_into creates a file with the same bytes, for the
    # S3 branch and the GitHub common-prefix branch.
    # Validates: Requirements 2.7, 2.9
    @settings(max_examples=25)
    @given(data=st.binary())
    def test_one_member_zip_extracts_to_same_bytes(self, data):
        """A one-member zip extracts to the member's exact bytes."""
        for source_type in ('s3', 'github'):
            prefix = 'starter-main/' if source_type == 'github' else ''
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                zip_path = root / 'starter.zip'
                _write_zip(zip_path, {'payload.bin': data}, prefix)
                out_dir = root / 'out'
                out_dir.mkdir()
                creator = _build_extraction_creator(source_type, zip_path)

                def copy_github_zip(url, path, zip_path=zip_path):
                    shutil.copyfile(zip_path, path)

                with mock.patch.object(create_repo, 'Log'), \
                        mock.patch.object(create_repo.click, 'echo'), \
                        mock.patch.object(
                            create_repo.GitHubUtils, 'download_zip_from_url',
                            side_effect=copy_github_zip,
                        ):
                    creator._download_and_extract_into(str(out_dir))

                extracted = out_dir / 'payload.bin'
                assert extracted.is_file(), source_type
                assert extracted.read_bytes() == data, source_type


class TestRemovedBase64Handling:
    """The base64 fallback and the text heuristic are gone."""

    # Feature: binary-and-non-utf-8-files-are-seeded-as-base64,
    # Removal of base64 import and _is_binary_string.
    # Validates: Requirements 2.2, 2.8, 4.9
    def test_no_base64_import_and_no_is_binary_string(self):
        """create_repo does not import base64 and has no _is_binary_string."""
        assert not hasattr(create_repo, 'base64')
        assert not hasattr(RepositoryCreator, '_is_binary_string')
