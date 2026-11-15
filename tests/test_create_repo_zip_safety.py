"""Tests for zip member containment during seed source extraction in create_repo.py.

``RepositoryCreator._download_and_extract_into`` must reject any zip member whose
output path resolves outside the extraction directory (``..`` segments, absolute
names, or names that only escape after the GitHub common prefix is stripped), and
must keep extracting safe archives exactly as before.

Test safety: these tests are written to run against UNFIXED code, which really
writes outside the extraction directory. Every test therefore builds a sandbox
under a test-owned temporary directory with the extraction directory five levels
deep (``<sandbox>/a/b/c/d/work``) and patches ``tempfile.mkdtemp`` to return that
``work`` path. Names that can escape use at most four ``..`` segments (which
reaches ``<sandbox>/a`` and no further), and absolute names are built from the
sandbox path, never from a real path such as ``/etc``. Sentinel files and the
before/after snapshots live in the sandbox, outside ``work``. The input zips live
beside the sandbox, not inside it. No zip fixture is committed: every archive is
generated inside the test.

Nothing here calls GitHub, AWS, or the network: the S3 client, ``GitHubUtils``,
``subprocess.run``, the prompt, ``Log``, and ``click.echo`` are mocked.

Helpers in this module:

* ``_make_creator`` builds a ``RepositoryCreator`` without ``__init__``.
* ``build_sandbox`` / the ``sandbox`` fixture build the deep sandbox.
* ``_write_zip`` writes a zip from ``(name, bytes)`` pairs.
* ``_stub_download`` makes the download step copy that zip into place.
* ``_snapshot`` records everything in the sandbox outside ``work``.

Counterexamples recorded on the unfixed code (bug condition exploration):

* Rejection tests (all 12 source/kind cases): the member is written outside the
  extraction directory (``outside-test.txt`` in the parent of ``work``,
  ``abs-test.txt`` for the absolute name, ``evil-dir`` created, the
  after-strip member written one or two levels above ``work``), the run
  returns normally instead of exiting 1, and ``work`` is not removed.
* Sentinel tests (``dotdot-file`` and ``absolute-file`` for each source): an
  existing file at the escape target is replaced (``original sentinel bytes``
  becomes ``escaped``) because the extractor calls ``unlink()`` before writing.
* Failure path: CodeCommit never calls ``_delete_codecommit_repository``, and
  ``create_and_seed_repository`` does not raise ``SystemExit``.
* Message: no ``SystemExit`` and no message holds the escaped name; with a
  1,000-character name the generic "Error in download and extract process"
  message is the only report path and no 200-character cap applies.
* First member order: with ``a.txt``, ``../b.txt``, ``c.txt`` all three are
  written (``c.txt`` inside ``work``, ``b.txt`` in the parent of ``work``).
* Property 1 (``test_nothing_outside_work_is_touched``), shrunk by Hypothesis to
  ``specs=[('relative', ['..', 'a'], False)]``, that is the single member
  ``../a``: file ``a/b/c/d/a`` is added outside ``work`` and the run does not
  exit. Property 2 (``test_safe_names_extract_to_expected_tree``) passes.

Feature: create-repo-py-reject-zip-members-that-extract
"""

import contextlib
import ntpath
import shutil
import sys
import tempfile
import warnings
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union
from unittest import mock
from unittest.mock import MagicMock

import botocore.exceptions
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import create_repo
from create_repo import RepositoryCreator


REPO_NAME = "acme/test-repo"
SOURCE_URL = "s3://invalid-bucket/seed.zip"

# The extraction directory is this many levels below the sandbox root.
WORK_DEPTH = 5
# Names that escape must never use more ``..`` segments than this. ``N`` leading
# ``..`` segments land N levels above ``work`` (``work / "../x"`` is ``d/x``), so
# four lands in ``<sandbox>/a``, one level inside the sandbox root.
MAX_DOTDOT = WORK_DEPTH - 1

# A snapshot maps a path (relative to the sandbox root, posix form) to
# ``(is_dir, bytes or None)``.
Snapshot = Dict[str, Tuple[bool, Optional[bytes]]]
# A zip member is ``(name, data)`` or ``(ZipInfo, data)``.
ZipMember = Tuple[Union[str, zipfile.ZipInfo], bytes]


def _make_creator(provider="github", source_type="s3"):
    """Build a RepositoryCreator without running ``__init__`` (no AWS session).

    Download, extract, seed, merge, and cleanup methods are real. The clients
    and the branch-structure/repository-creation steps are mocks.

    Args:
        provider (str): ``'github'`` or ``'codecommit'``.
        source_type (str): ``'s3'`` or ``'github'``.

    Returns:
        RepositoryCreator: Minimally initialized instance.

    Example:
        >>> creator = _make_creator(provider='codecommit', source_type='s3')
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


class Sandbox:
    """A deep, test-owned directory tree around the extraction directory.

    Attributes:
        root (Path): Sandbox root. Everything an unsafe member could reach (with
            at most four ``..`` segments) is inside it.
        work (Path): Extraction directory, ``root/a/b/c/d/work``. It exists when
            the sandbox is built and is what ``tempfile.mkdtemp`` returns.
        inputs (Path): Directory beside the sandbox (not inside it) that holds
            the generated input zips.

    Example:
        >>> with build_sandbox(Path(tmp_dir)) as sandbox:
        ...     escaped = sandbox.root / "a" / "outside.txt"
    """

    def __init__(self, base_dir: Path):
        self.root = Path(base_dir) / "sandbox"
        self.work = self.root / "a" / "b" / "c" / "d" / "work"
        self.inputs = Path(base_dir) / "inputs"
        self.work.mkdir(parents=True)
        self.inputs.mkdir(parents=True)

    def dotdot_name(self, levels: int, name: str) -> str:
        """Build a member name that climbs ``levels`` directories above ``work``.

        Args:
            levels (int): Number of ``..`` segments, 1 to ``MAX_DOTDOT``.
            name (str): Name appended after the ``..`` segments.

        Returns:
            str: For example ``'../../outside.txt'`` for ``levels=2``.

        Raises:
            ValueError: When ``levels`` is outside 1 to ``MAX_DOTDOT``, which
                would let a write leave the sandbox.

        Example:
            >>> sandbox.dotdot_name(1, "outside-test.txt")
            '../outside-test.txt'
        """
        if not 1 <= levels <= MAX_DOTDOT:
            raise ValueError(f"levels must be 1 to {MAX_DOTDOT}, got {levels}")
        return "/".join([".."] * levels + [name])

    def landing_path(self, levels: int, name: str) -> Path:
        """Return where ``work / dotdot_name(levels, name)`` lands.

        Args:
            levels (int): Number of ``..`` segments, 1 to ``MAX_DOTDOT``.
            name (str): Name appended after the ``..`` segments.

        Returns:
            Path: Absolute path inside the sandbox.

        Example:
            >>> sandbox.landing_path(1, "x.txt") == sandbox.work.parent / "x.txt"
            True
        """
        self.dotdot_name(levels, name)  # validates levels
        return self.work.parents[levels - 1] / name

    def absolute_name(self, relative: str) -> str:
        """Build an absolute member name that points inside the sandbox.

        Args:
            relative (str): Path relative to the sandbox root (posix form).

        Returns:
            str: ``<sandbox root>/<relative>`` as a posix path.

        Example:
            >>> sandbox.absolute_name("a/abs.txt").endswith("/sandbox/a/abs.txt")
            True
        """
        return (self.root / relative).as_posix()

    def make_zip(self, members: Iterable[ZipMember], name: str = "seed.zip") -> Path:
        """Write a zip in ``inputs`` and return its path.

        Args:
            members (Iterable[ZipMember]): Members as for ``_write_zip``.
            name (str): File name of the zip. Defaults to ``seed.zip``.

        Returns:
            Path: Path of the written zip, outside the sandbox.

        Example:
            >>> zip_path = sandbox.make_zip([("ok.txt", b"ok")])
        """
        zip_path = self.inputs / name
        _write_zip(zip_path, members)
        return zip_path

    def snapshot(self) -> Snapshot:
        """Snapshot everything in the sandbox outside ``work``.

        Returns:
            Snapshot: See ``_snapshot``.

        Example:
            >>> before = sandbox.snapshot()
        """
        return _snapshot(self.root, self.work)


@contextlib.contextmanager
def build_sandbox(base_dir: Path) -> Iterator[Sandbox]:
    """Build a ``Sandbox`` under ``base_dir`` and patch ``tempfile.mkdtemp``.

    While the context is active, ``create_repo.tempfile.mkdtemp()`` returns the
    sandbox ``work`` directory, so the code under test extracts into it.
    Hypothesis tests call this with their own ``tempfile.TemporaryDirectory()``;
    other tests use the ``sandbox`` fixture.

    Args:
        base_dir (Path): Existing directory that owns the sandbox. Must be a
            test-owned temporary directory.

    Yields:
        Sandbox: The sandbox.

    Example:
        >>> with tempfile.TemporaryDirectory() as tmp_dir:
        ...     with build_sandbox(Path(tmp_dir)) as sandbox:
        ...         pass
    """
    sandbox = Sandbox(base_dir)
    with mock.patch.object(
        create_repo.tempfile, "mkdtemp", return_value=str(sandbox.work)
    ):
        yield sandbox


def _write_zip(path, members: Iterable[ZipMember]) -> None:
    """Write a zip file from ``(name, bytes)`` pairs.

    The first element of a pair is either a plain name or a ``ZipInfo``. Use a
    ``ZipInfo`` for directory entries (a name ending in ``/``) and to set
    attributes such as symlink mode (see ``_symlink_info``). Plain names are
    stored exactly as given, including ``..`` segments and absolute names.

    Args:
        path (str or Path): Zip file to create.
        members (Iterable[ZipMember]): ``(name_or_zipinfo, data)`` pairs.

    Example:
        >>> _write_zip(tmp_path / "seed.zip", [("a/b.txt", b"hi"), ("d/", b"")])
    """
    with zipfile.ZipFile(path, 'w') as zip_file:
        for name_or_info, data in members:
            zip_file.writestr(name_or_info, data)


def _symlink_info(name: str) -> zipfile.ZipInfo:
    """Build a ``ZipInfo`` whose Unix mode marks the member as a symlink.

    Args:
        name (str): Member name.

    Returns:
        zipfile.ZipInfo: Info with ``external_attr = 0o120000 << 16``.

    Example:
        >>> info = _symlink_info("link")
        >>> (info.external_attr >> 16) == 0o120000
        True
    """
    info = zipfile.ZipInfo(name)
    info.external_attr = 0o120000 << 16
    return info


def _dir_info(name: str) -> zipfile.ZipInfo:
    """Build a ``ZipInfo`` for a directory member (``name`` ends in ``/``).

    Args:
        name (str): Member name. A trailing ``/`` is added when missing.

    Returns:
        zipfile.ZipInfo: Directory info.

    Example:
        >>> _dir_info("src").filename
        'src/'
    """
    info = zipfile.ZipInfo(name if name.endswith('/') else name + '/')
    info.external_attr = (0o40755 << 16) | 0x10
    return info


@contextlib.contextmanager
def _stub_download(creator: RepositoryCreator, zip_path) -> Iterator[None]:
    """Make the creator's download step copy ``zip_path`` into place.

    For ``source_type == 's3'`` the S3 client's ``download_file`` copies the zip
    and ``is_bucket_public`` returns ``False``. For ``'github'`` the
    ``GitHubUtils.download_zip_from_url`` attribute is patched to copy the zip.
    Works whether or not the ``mocks`` fixture has replaced ``GitHubUtils``.

    Args:
        creator (RepositoryCreator): Creator from ``_make_creator``.
        zip_path (str or Path): Zip to serve as the download.

    Yields:
        None: The stub is active inside the ``with`` block.

    Example:
        >>> with _stub_download(creator, zip_path):
        ...     creator._download_and_extract()
    """
    if creator.source_type == 's3':
        creator.is_bucket_public.return_value = False
        creator.s3_client.download_file.side_effect = (
            lambda bucket, key, dest: shutil.copyfile(zip_path, dest)
        )
        yield
    else:
        with mock.patch.object(
            create_repo.GitHubUtils,
            "download_zip_from_url",
            side_effect=lambda url, dest: shutil.copyfile(zip_path, dest),
        ):
            yield


def _snapshot(sandbox_root, exclude) -> Snapshot:
    """Record every path under ``sandbox_root`` except ``exclude`` and below.

    Args:
        sandbox_root (str or Path): Directory to walk.
        exclude (str or Path): Directory (normally ``work``) whose contents are
            skipped. The directory entry itself is skipped as well.

    Returns:
        Snapshot: Maps each path, relative to ``sandbox_root`` in posix form, to
            ``(is_dir, content)`` where ``content`` is the file bytes or
            ``None`` for a directory.

    Example:
        >>> before = _snapshot(sandbox.root, sandbox.work)
        >>> # ... run the code under test ...
        >>> assert _snapshot(sandbox.root, sandbox.work) == before
    """
    root = Path(sandbox_root)
    skipped = Path(exclude)
    snapshot: Snapshot = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        for entry in sorted(directory.iterdir()):
            if entry == skipped:
                continue
            relative = entry.relative_to(root).as_posix()
            if entry.is_dir() and not entry.is_symlink():
                snapshot[relative] = (True, None)
                stack.append(entry)
            else:
                snapshot[relative] = (False, entry.read_bytes())
    return snapshot


@pytest.fixture
def sandbox(tmp_path):
    """Deep sandbox under ``tmp_path`` with ``tempfile.mkdtemp`` patched to ``work``.

    Yields:
        Sandbox: See ``Sandbox``.
    """
    with build_sandbox(tmp_path) as built:
        yield built


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


class TestSandboxHelpers:
    """Smoke tests for the sandbox helpers (pass on unfixed and fixed code)."""

    def test_sandbox_is_deep_and_mkdtemp_returns_work(self, sandbox):
        """``work`` is five levels below the root and is what mkdtemp returns."""
        assert sandbox.work.is_dir()
        assert len(sandbox.work.relative_to(sandbox.root).parts) == WORK_DEPTH
        assert create_repo.tempfile.mkdtemp() == str(sandbox.work)
        assert sandbox.root not in sandbox.inputs.parents

    def test_dotdot_name_is_bounded(self, sandbox):
        """``..`` counts above four are refused, and four still lands inside the sandbox."""
        assert sandbox.dotdot_name(1, "x.txt") == "../x.txt"
        assert sandbox.landing_path(1, "x.txt") == sandbox.work.parent / "x.txt"
        landing = sandbox.landing_path(MAX_DOTDOT, "x.txt")
        assert landing == sandbox.root / "a" / "x.txt"
        assert sandbox.root in landing.parents
        with pytest.raises(ValueError):
            sandbox.dotdot_name(MAX_DOTDOT + 1, "x.txt")
        with pytest.raises(ValueError):
            sandbox.dotdot_name(0, "x.txt")

    def test_absolute_name_is_inside_sandbox(self, sandbox):
        """Absolute names are built from the sandbox path."""
        name = sandbox.absolute_name("a/abs.txt")
        assert name.startswith("/") or name[1:3] == ":/"
        assert Path(name) == sandbox.root / "a" / "abs.txt"

    def test_snapshot_ignores_work_and_sees_outside_changes(self, sandbox):
        """The snapshot skips ``work`` and records files and directories outside it."""
        (sandbox.work / "inside.txt").write_bytes(b"inside")
        (sandbox.root / "sentinel.txt").write_bytes(b"keep")
        before = sandbox.snapshot()

        assert before["sentinel.txt"] == (False, b"keep")
        assert before["a"] == (True, None)
        assert not any(key.endswith("work") or "inside.txt" in key for key in before)

        (sandbox.work / "more.txt").write_bytes(b"more")
        assert sandbox.snapshot() == before

        (sandbox.root / "sentinel.txt").write_bytes(b"changed")
        assert sandbox.snapshot() != before

    def test_write_zip_stores_names_unchanged_and_supports_zipinfo(self, sandbox):
        """Names with ``..`` and absolute names are stored as given, plus dir and symlink info."""
        absolute = sandbox.absolute_name("a/abs.txt")
        zip_path = sandbox.make_zip([
            ("ok.txt", b"ok"),
            ("../escape.txt", b"e"),
            (absolute, b"abs"),
            (_dir_info("d"), b""),
            (_symlink_info("link"), b"target"),
        ])

        with zipfile.ZipFile(zip_path) as zip_file:
            names = [info.filename for info in zip_file.filelist]
            link_info = zip_file.getinfo("link")

        assert names == ["ok.txt", "../escape.txt", absolute, "d/", "link"]
        assert (link_info.external_attr >> 16) == 0o120000
        assert zip_path.parent == sandbox.inputs

    @pytest.mark.parametrize("source_type", ["s3", "github"])
    def test_stub_download_feeds_safe_zip_through_extraction(
        self, mocks, sandbox, source_type
    ):
        """A safe zip extracts into ``work`` for both sources and nothing changes outside."""
        creator = _make_creator(source_type=source_type)
        prefix = "repo-main/" if source_type == "github" else ""
        zip_path = sandbox.make_zip([
            (prefix + "ok.txt", b"ok"),
            (prefix + "src/app.py", b"print('hi')\n"),
        ])
        before = sandbox.snapshot()

        with _stub_download(creator, zip_path):
            result = creator._download_and_extract()

        assert result == str(sandbox.work)
        assert (sandbox.work / "ok.txt").read_bytes() == b"ok"
        assert (sandbox.work / "src" / "app.py").read_bytes() == b"print('hi')\n"
        assert not (sandbox.work / "source.zip").exists()
        assert sandbox.snapshot() == before


# ---------------------------------------------------------------------------
# Rejection tests (bug condition exploration, run on unfixed code first)
# ---------------------------------------------------------------------------

# Shared top-level directory used by the "github with prefix" source.
GITHUB_PREFIX = "repo-main/"

# source id -> (source_type, has_shared_prefix)
SOURCE_CASES = {
    "s3": ("s3", False),
    "github-prefix": ("github", True),
    "github-no-prefix": ("github", False),
}

MEMBER_KINDS = ["dotdot-file", "absolute-file", "dotdot-dir", "unsafe-after-strip"]


def _base_members(source_id: str) -> list:
    """Return safe members that give the archive its prefix shape.

    ``github-prefix`` members share ``repo-main/`` so the common prefix is
    detected and stripped. ``github-no-prefix`` has two different top-level
    directories, so no prefix is detected. ``s3`` never strips a prefix.

    Args:
        source_id (str): Key of ``SOURCE_CASES``.

    Returns:
        list: ``(name, bytes)`` pairs.

    Example:
        >>> _base_members("github-prefix")
        [('repo-main/ok.txt', b'ok')]
    """
    if source_id == "github-prefix":
        return [(GITHUB_PREFIX + "ok.txt", b"ok")]
    if source_id == "github-no-prefix":
        return [("dir1/ok.txt", b"ok"), ("dir2/ok.txt", b"ok")]
    return [("ok.txt", b"ok")]


def _escaping_member(sandbox: Sandbox, source_id: str, kind: str):
    """Build the escaping member for a source and kind, and where it lands.

    Every name uses at most two ``..`` segments or an absolute name built from
    the sandbox, so unfixed code writes only inside the sandbox.

    Args:
        sandbox (Sandbox): The sandbox the extraction directory belongs to.
        source_id (str): Key of ``SOURCE_CASES``.
        kind (str): One of ``MEMBER_KINDS``.

    Returns:
        tuple: ``(member, target, is_dir)``. ``member`` is a ``(name_or_info,
            data)`` pair, ``target`` is where unfixed code writes it (a path
            inside the sandbox), ``is_dir`` is True for a directory member.

    Example:
        >>> member, target, is_dir = _escaping_member(sandbox, "s3", "dotdot-file")
    """
    _, has_prefix = SOURCE_CASES[source_id]
    prefix = GITHUB_PREFIX if has_prefix else ""

    if kind == "dotdot-file":
        # With a prefix, "repo-main/../x" strips to "../x".
        return ((prefix + sandbox.dotdot_name(1, "outside-test.txt"), b"escaped"),
                sandbox.landing_path(1, "outside-test.txt"), False)
    if kind == "absolute-file":
        name = sandbox.absolute_name("a/abs-test.txt")
        return ((name, b"escaped"), sandbox.root / "a" / "abs-test.txt", False)
    if kind == "dotdot-dir":
        name = prefix + sandbox.dotdot_name(1, "evil-dir") + "/"
        return ((_dir_info(name), b""), sandbox.landing_path(1, "evil-dir"), True)
    if kind == "unsafe-after-strip":
        name = GITHUB_PREFIX + sandbox.dotdot_name(2, "after-strip-test.txt")
        # With the shared prefix stripped the name is "../../x" (two levels
        # above work). Without stripping, "repo-main/../../x" is one level up.
        levels = 2 if has_prefix else 1
        return ((name, b"escaped"),
                sandbox.landing_path(levels, "after-strip-test.txt"), False)
    raise ValueError(kind)


def _describe_changes(before: Snapshot, after: Snapshot) -> list:
    """List what changed between two snapshots, for assertion messages.

    Args:
        before (Snapshot): Snapshot before the run.
        after (Snapshot): Snapshot after the run.

    Returns:
        list: Strings such as ``"added file a/x.txt"``. Empty when equal.

    Example:
        >>> _describe_changes({}, {"x": (False, b"1")})
        ["added file x"]
    """
    changes = []
    for path in sorted(set(after) - set(before)):
        changes.append(f"added {'dir' if after[path][0] else 'file'} {path}")
    for path in sorted(set(before) - set(after)):
        changes.append(f"removed {path}")
    for path in sorted(set(before) & set(after)):
        if before[path] != after[path]:
            changes.append(f"changed {path}: {before[path][1]!r} -> {after[path][1]!r}")
    return changes


def _run_extraction(creator, sandbox: Sandbox, zip_path, before: Snapshot) -> list:
    """Run ``_download_and_extract`` and collect every violated expectation.

    Expected (fixed) behavior: ``SystemExit`` with code 1, nothing changed in
    the sandbox outside ``work``, and ``work`` removed.

    Args:
        creator (RepositoryCreator): Creator from ``_make_creator``.
        sandbox (Sandbox): The sandbox.
        zip_path (Path): Zip served as the download.
        before (Snapshot): Snapshot taken before the run.

    Returns:
        list: Problem descriptions. Empty when the behavior is as expected.

    Example:
        >>> problems = _run_extraction(creator, sandbox, zip_path, sandbox.snapshot())
    """
    outcome = "returned normally"
    exit_code = None
    exited = False
    try:
        with _stub_download(creator, zip_path):
            result = creator._download_and_extract()
        outcome = f"returned {result!r}"
    except SystemExit as exc:
        exited = True
        exit_code = exc.code

    problems = []
    changes = _describe_changes(before, sandbox.snapshot())
    if changes:
        problems.append("outside work: " + "; ".join(changes))
    if not exited:
        problems.append(f"no SystemExit, {outcome}")
    elif exit_code != 1:
        problems.append(f"SystemExit code {exit_code!r}, expected 1")
    if sandbox.work.exists():
        problems.append("work directory still exists")
    return problems


class TestRejectsEscapingMembers:
    """Unsafe members are rejected before anything is written outside ``work``.

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.8, 4.3, 4.4
    """

    @pytest.mark.parametrize("kind", MEMBER_KINDS)
    @pytest.mark.parametrize("source_id", list(SOURCE_CASES))
    def test_escaping_member_is_rejected(self, mocks, sandbox, source_id, kind):
        """Exit 1, nothing outside ``work`` changes, and ``work`` is removed."""
        source_type, _ = SOURCE_CASES[source_id]
        creator = _make_creator(source_type=source_type)
        member, _target, _is_dir = _escaping_member(sandbox, source_id, kind)
        zip_path = sandbox.make_zip(_base_members(source_id) + [member])
        before = sandbox.snapshot()

        problems = _run_extraction(creator, sandbox, zip_path, before)

        assert not problems, "; ".join(problems)

    @pytest.mark.parametrize("kind", ["dotdot-file", "absolute-file"])
    @pytest.mark.parametrize("source_id", list(SOURCE_CASES))
    def test_existing_file_at_escape_target_is_not_replaced(
        self, mocks, sandbox, source_id, kind
    ):
        """A file already at the escape target keeps its bytes (the ``unlink()`` case)."""
        source_type, _ = SOURCE_CASES[source_id]
        creator = _make_creator(source_type=source_type)
        member, target, _is_dir = _escaping_member(sandbox, source_id, kind)
        original = b"original sentinel bytes"
        target.write_bytes(original)
        zip_path = sandbox.make_zip(_base_members(source_id) + [member])
        before = sandbox.snapshot()
        assert before[target.relative_to(sandbox.root).as_posix()] == (False, original)

        problems = _run_extraction(creator, sandbox, zip_path, before)

        assert target.read_bytes() == original, (
            f"sentinel replaced: {original!r} -> {target.read_bytes()!r}"
        )
        assert not problems, "; ".join(problems)


# ---------------------------------------------------------------------------
# Failure-path, message, and ordering tests (bug condition exploration)
# ---------------------------------------------------------------------------

# The design caps the escaped member name at 200 characters. The rest of the
# message ("Unsafe source zip: zip member ... resolves outside the extraction
# directory. Nothing was seeded.") adds fewer than 100 characters, so any single
# reported message stays below this bound when the cap is applied.
MAX_MESSAGE_LENGTH = 400
GENERIC_FAILURE_TEXT = "Error in download and extract process"


@pytest.fixture
def plain_colors():
    """Make ``Colorize.error``, ``output``, and ``output_with_value`` return plain text.

    ``click.style`` adds ANSI escape codes, which would hide a raw ``\\x1b``
    coming from a member name. With plain colors, any ``\\x1b`` in a captured
    message must come from the name.

    Yields:
        None: The patches are active inside the test.
    """
    with mock.patch.object(
            create_repo.Colorize, "error", side_effect=lambda text: text), \
            mock.patch.object(
                create_repo.Colorize, "output",
                side_effect=lambda text, **kwargs: text), \
            mock.patch.object(
                create_repo.Colorize, "output_with_value",
                side_effect=lambda text, value: f"{text} {value}"):
        yield


def _reported_messages(mocks) -> list:
    """Collect every positional argument given to ``click.echo`` and ``Log.error``.

    Args:
        mocks (MagicMock): The ``mocks`` fixture value.

    Returns:
        list: The arguments as strings, in call order.

    Example:
        >>> messages = _reported_messages(mocks)
    """
    messages = []
    for call in mocks.echo.call_args_list:
        messages.extend(str(arg) for arg in call.args)
    for call in mocks.log.error.call_args_list:
        messages.extend(str(arg) for arg in call.args)
    return messages


def _run_and_get_exit(creator, zip_path):
    """Run ``_download_and_extract`` and return the ``SystemExit`` code, if any.

    Args:
        creator (RepositoryCreator): Creator from ``_make_creator``.
        zip_path (Path): Zip served as the download.

    Returns:
        tuple: ``(exited, code)``. ``exited`` is False when the call returned
            normally.

    Example:
        >>> exited, code = _run_and_get_exit(creator, zip_path)
    """
    try:
        with _stub_download(creator, zip_path):
            creator._download_and_extract()
    except SystemExit as exc:
        return True, exc.code
    return False, None


class TestFailurePath:
    """An unsafe member uses the existing fail-closed cleanup flow.

    Validates: Requirements 2.4, 2.5, 4.5
    """

    def test_codecommit_deletes_repository_once(self, mocks, sandbox):
        """CodeCommit: ``_delete_codecommit_repository`` is called exactly once."""
        creator = _make_creator(provider="codecommit", source_type="s3")
        creator._delete_codecommit_repository = MagicMock()
        member, _target, _is_dir = _escaping_member(sandbox, "s3", "dotdot-file")
        zip_path = sandbox.make_zip(_base_members("s3") + [member])
        before = sandbox.snapshot()

        problems = _run_extraction(creator, sandbox, zip_path, before)

        assert creator._delete_codecommit_repository.call_count == 1, (
            f"_delete_codecommit_repository called "
            f"{creator._delete_codecommit_repository.call_count} times, expected 1"
        )
        assert not problems, "; ".join(problems)

    def test_github_extraction_step_does_not_call_failure_handler(
        self, mocks, sandbox
    ):
        """GitHub: the extraction step leaves cleanup to ``create_and_seed_repository``."""
        creator = _make_creator(provider="github", source_type="s3")
        creator._handle_github_seeding_failure = MagicMock()
        creator._delete_codecommit_repository = MagicMock()
        member, _target, _is_dir = _escaping_member(sandbox, "s3", "dotdot-file")
        zip_path = sandbox.make_zip(_base_members("s3") + [member])
        before = sandbox.snapshot()

        problems = _run_extraction(creator, sandbox, zip_path, before)

        creator._handle_github_seeding_failure.assert_not_called()
        creator._delete_codecommit_repository.assert_not_called()
        assert not problems, "; ".join(problems)

    def test_github_run_calls_handler_once_and_reraises_exit_1(
        self, mocks, sandbox
    ):
        """GitHub: ``create_and_seed_repository`` calls the handler once, re-raises exit 1."""
        creator = _make_creator(provider="github", source_type="s3")
        creator._handle_github_seeding_failure = MagicMock()
        creator._seed_repository = MagicMock()
        creator._merge_dev_to_test = MagicMock()
        member, _target, _is_dir = _escaping_member(sandbox, "s3", "dotdot-file")
        zip_path = sandbox.make_zip(_base_members("s3") + [member])
        before = sandbox.snapshot()

        with _stub_download(creator, zip_path):
            with pytest.raises(SystemExit) as exc_info:
                creator.create_and_seed_repository()

        assert exc_info.value.code == 1
        creator._create_repository.assert_called_once()
        creator._create_dev_test_branches.assert_called_once()
        creator._handle_github_seeding_failure.assert_called_once()
        creator._seed_repository.assert_not_called()
        creator._merge_dev_to_test.assert_not_called()
        assert _describe_changes(before, sandbox.snapshot()) == []


class TestMessage:
    """The member name is reported only in escaped ``repr()`` form, with a length cap.

    Validates: Requirements 2.6, 2.7, 4.6
    """

    def test_control_characters_are_reported_escaped(
        self, mocks, sandbox, plain_colors
    ):
        """``\\n`` and ``\\x1b`` appear as text, never as raw characters."""
        creator = _make_creator(provider="github", source_type="s3")
        name = sandbox.dotdot_name(1, "evil\n\x1b[31mred.txt")
        zip_path = sandbox.make_zip(_base_members("s3") + [(name, b"escaped")])

        exited, code = _run_and_get_exit(creator, zip_path)
        messages = _reported_messages(mocks)
        joined = "\n".join(messages)

        problems = []
        if not exited:
            problems.append("no SystemExit, the run returned normally")
        elif code != 1:
            problems.append(f"SystemExit code {code!r}, expected 1")
        if not any("\\n" in message for message in messages):
            problems.append("no message contains the escaped text \\n")
        if not any("\\x1b" in message for message in messages):
            problems.append("no message contains the escaped text \\x1b")
        if "\x1b" in joined:
            problems.append("a message contains a raw ESC character from the name")
        if any("\n" in message for message in messages):
            problems.append("a message contains a raw newline from the name")
        if GENERIC_FAILURE_TEXT in joined:
            problems.append(f"generic text {GENERIC_FAILURE_TEXT!r} was reported")
        assert not problems, "; ".join(problems)

    def test_error_and_log_both_carry_escaped_name(
        self, mocks, sandbox, plain_colors
    ):
        """Both the echoed error and the ``Log.error`` line hold the escaped name."""
        creator = _make_creator(provider="github", source_type="s3")
        name = sandbox.dotdot_name(1, "evil\n\x1b[31mred.txt")
        zip_path = sandbox.make_zip(_base_members("s3") + [(name, b"escaped")])

        _run_and_get_exit(creator, zip_path)

        echoed = [str(arg) for call in mocks.echo.call_args_list for arg in call.args]
        logged = [str(arg) for call in mocks.log.error.call_args_list
                  for arg in call.args]
        assert any("\\x1b" in message for message in echoed), "echo lacks \\x1b text"
        assert any("\\x1b" in message for message in logged), "Log.error lacks \\x1b text"
        assert not any("\x1b" in message for message in echoed + logged)

    def test_long_name_is_capped(self, mocks, sandbox, plain_colors):
        """A 1,000-character name is shortened to the 200-character cap, ending with ``...``."""
        creator = _make_creator(provider="github", source_type="s3")
        name = sandbox.dotdot_name(1, "x" * 1000)
        zip_path = sandbox.make_zip(_base_members("s3") + [(name, b"escaped")])

        exited, code = _run_and_get_exit(creator, zip_path)
        messages = _reported_messages(mocks)

        problems = []
        if not exited:
            problems.append("no SystemExit, the run returned normally")
        too_long = [len(message) for message in messages
                    if len(message) > MAX_MESSAGE_LENGTH]
        if too_long:
            problems.append(f"messages longer than {MAX_MESSAGE_LENGTH}: {too_long}")
        if any("x" * 201 in message for message in messages):
            problems.append("a message holds more than 200 characters of the name")
        if not any("x" * 100 + "..." in message for message in messages):
            problems.append("no message shows the capped name ending with '...'")
        if GENERIC_FAILURE_TEXT in "\n".join(messages):
            problems.append(f"generic text {GENERIC_FAILURE_TEXT!r} was reported")
        assert not problems, "; ".join(problems)


class TestStopsAtFirstUnsafeMember:
    """Extraction stops at the first unsafe member, so later members are never written.

    Validates: Requirements 2.5, 4.7
    """

    def test_member_after_unsafe_member_is_never_written(self, mocks, sandbox):
        """``a.txt``, ``../b.txt``, ``c.txt``: nothing outside ``work``, no write for ``c.txt``."""
        creator = _make_creator(provider="github", source_type="s3")
        zip_path = sandbox.make_zip([
            ("a.txt", b"a"),
            (sandbox.dotdot_name(1, "b.txt"), b"b"),
            ("c.txt", b"c"),
        ])
        before = sandbox.snapshot()
        written = []
        original_write_bytes = Path.write_bytes

        def recording_write_bytes(path_self, data):
            written.append(Path(path_self))
            return original_write_bytes(path_self, data)

        with mock.patch.object(
                Path, "write_bytes", autospec=True,
                side_effect=recording_write_bytes):
            problems = _run_extraction(creator, sandbox, zip_path, before)

        written_names = [path.name for path in written]
        if "c.txt" in written_names:
            problems.append(f"c.txt was written: {[str(p) for p in written if p.name == 'c.txt']}")
        if "b.txt" in written_names:
            problems.append(f"b.txt was written: {[str(p) for p in written if p.name == 'b.txt']}")
        assert not problems, "; ".join(problems)


# ---------------------------------------------------------------------------
# Property tests (bug condition exploration, run on unfixed code first)
# ---------------------------------------------------------------------------

# Segments used to build member names. ``..`` and the empty string can make a
# name escape (or collapse), ``.`` is dropped by ``pathlib``.
SEGMENT_CHOICES = ["a", "dir", "x.txt", "..", ".", ""]
# ``relative``: the name as joined. ``absolute``: ``<work>/<name>``.
# ``absolute-double-slash``: ``/<work>/<name>`` (a leading ``/`` before the
# already absolute sandbox path). Absolute names are rooted at ``work``, so with
# at most four ``..`` segments they still land inside the sandbox.
MEMBER_FORMS = ["relative", "absolute", "absolute-double-slash"]


def _is_valid_member_spec(spec) -> bool:
    """Keep specs that cannot leave the sandbox or reach the real root.

    A relative name must not start with an empty segment (it would become
    ``/x``, an absolute path in the real filesystem), and no name may hold more
    than ``MAX_DOTDOT`` ``..`` segments.

    Args:
        spec (tuple): ``(form, segments, is_dir)``.

    Returns:
        bool: True when the spec is safe to run against unfixed code.

    Example:
        >>> _is_valid_member_spec(("relative", ["..", "a"], False))
        True
        >>> _is_valid_member_spec(("relative", ["", "a"], False))
        False
    """
    form, segments, _is_dir = spec
    if segments.count("..") > MAX_DOTDOT:
        return False
    return not (form == "relative" and segments[0] == "")


_MEMBER_SPEC = st.tuples(
    st.sampled_from(MEMBER_FORMS),
    st.lists(st.sampled_from(SEGMENT_CHOICES), min_size=1, max_size=5),
    st.booleans(),
).filter(_is_valid_member_spec)

_MEMBER_SPECS = st.lists(_MEMBER_SPEC, min_size=1, max_size=8)

# Safe names: ordinary names and ``.`` only (no ``..``, no absolute form, no
# empty segment). A trailing ``/`` marks a directory member.
_SAFE_SEGMENTS = ["a", "dir", "x.txt", "."]
_SAFE_MEMBER_SPEC = st.tuples(
    st.lists(st.sampled_from(_SAFE_SEGMENTS), min_size=1, max_size=5),
    st.booleans(),
)
_SAFE_MEMBER_SPECS = st.lists(_SAFE_MEMBER_SPEC, min_size=1, max_size=8)


def _member_name(sandbox: Sandbox, form: str, segments: List[str], is_dir: bool) -> str:
    """Build a zip member name from a generated spec.

    Args:
        sandbox (Sandbox): The sandbox (absolute names are rooted at ``work``).
        form (str): One of ``MEMBER_FORMS``.
        segments (List[str]): Name segments joined with ``/``.
        is_dir (bool): Add a trailing ``/`` when the joined name has none.

    Returns:
        str: The member name. It ends with ``/`` for directory members.

    Example:
        >>> _member_name(sandbox, "relative", ["a", "x.txt"], False)
        'a/x.txt'
    """
    path = "/".join(segments)
    if is_dir and not path.endswith("/"):
        path += "/"
    if form == "relative":
        return path
    base = sandbox.work.as_posix()
    if form == "absolute":
        return base + "/" + path
    return "/" + base + "/" + path


def _zip_members(names: List[str]) -> List[ZipMember]:
    """Turn member names into ``_write_zip`` members with distinct contents.

    Args:
        names (List[str]): Member names. Names ending in ``/`` become directories.

    Returns:
        List[ZipMember]: ``(name_or_info, bytes)`` pairs. File ``i`` holds
            ``b"data-<i>"`` so an overwrite changes the bytes.

    Example:
        >>> _zip_members(["a.txt", "d/"])[0]
        ('a.txt', b'data-0')
    """
    members: List[ZipMember] = []
    for index, name in enumerate(names):
        if name.endswith("/"):
            members.append((_dir_info(name), b""))
        else:
            members.append((name, f"data-{index}".encode()))
    return members


def _add_sentinels(sandbox: Sandbox) -> None:
    """Put an ``x.txt`` sentinel in each directory above ``work``.

    Args:
        sandbox (Sandbox): The sandbox. Files go in ``a``, ``a/b``, ``a/b/c`` and
            ``a/b/c/d`` so a replaced or removed file shows up in the snapshot.

    Example:
        >>> _add_sentinels(sandbox)
    """
    for parent in sandbox.work.parents:
        if parent == sandbox.root.parent:
            break
        if parent != sandbox.root:
            (parent / "x.txt").write_bytes(b"sentinel " + parent.name.encode())


@contextlib.contextmanager
def _quiet_environment() -> Iterator[None]:
    """Mock the prompt, ``subprocess.run``, ``Log``, ``click.echo`` and ``GitHubUtils``.

    Same patches as the ``mocks`` fixture, usable inside a Hypothesis test body
    (function-scoped fixtures are not allowed with ``@given``).

    Yields:
        None: The patches are active inside the ``with`` block.

    Example:
        >>> with _quiet_environment():
        ...     pass
    """
    with mock.patch.object(create_repo.Colorize, "prompt", return_value="N"), \
            mock.patch.object(create_repo.subprocess, "run"), \
            mock.patch.object(create_repo, "Log"), \
            mock.patch.object(create_repo.click, "echo"), \
            mock.patch.object(create_repo, "GitHubUtils"):
        yield


def _run_into_work(sandbox: Sandbox, members: List[ZipMember]):
    """Run ``_download_and_extract_into`` on a generated zip and record writes.

    Args:
        sandbox (Sandbox): The sandbox. The zip is written beside it.
        members (List[ZipMember]): Zip members.

    Returns:
        tuple: ``(exited, code, written)``. ``exited`` is True when ``SystemExit``
            was raised, ``code`` is its code, and ``written`` lists every path
            passed to ``Path.write_bytes`` during the run.

    Example:
        >>> exited, code, written = _run_into_work(sandbox, [("a.txt", b"a")])
    """
    creator = _make_creator(provider="github", source_type="s3")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate member names warn on write
        zip_path = sandbox.make_zip(members)

    written: List[Path] = []
    original_write_bytes = Path.write_bytes

    def recording_write_bytes(path_self, data):
        written.append(Path(path_self))
        return original_write_bytes(path_self, data)

    exited = False
    code = None
    with _quiet_environment(), \
            mock.patch.object(Path, "write_bytes", autospec=True,
                              side_effect=recording_write_bytes), \
            _stub_download(creator, zip_path):
        try:
            creator._download_and_extract_into(str(sandbox.work))
        except SystemExit as exc:
            exited = True
            code = exc.code
    return exited, code, written


def _tree_of(directory: Path) -> Dict[str, Tuple[bool, Optional[bytes]]]:
    """Map every path under ``directory`` to ``(is_dir, bytes or None)``.

    Args:
        directory (Path): Directory to walk.

    Returns:
        dict: Relative posix path to ``(is_dir, content)``.

    Example:
        >>> _tree_of(sandbox.work)
        {}
    """
    tree: Dict[str, Tuple[bool, Optional[bytes]]] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        tree[relative] = (True, None) if path.is_dir() else (False, path.read_bytes())
    return tree


def _expected_tree(members: List[ZipMember]):
    """Model what extracting safe members should leave in ``work``.

    The model applies members in archive order with the extractor's semantics:
    ``.`` segments and empty segments disappear, a later file replaces an
    earlier file at the same path, parent directories are created on demand,
    and a conflict (a file where a directory is needed, a directory where a
    file is written, or a file member that names ``work`` itself) is an error
    that makes the run exit 1.

    Args:
        members (List[ZipMember]): ``(name_or_info, bytes)`` pairs.

    Returns:
        tuple: ``(tree, has_conflict)``. ``tree`` maps relative posix paths to
            ``(is_dir, content)``. ``has_conflict`` is True when the run is
            expected to fail with exit 1 (``tree`` is then not meaningful).

    Example:
        >>> _expected_tree([("a/b.txt", b"x")])
        ({'a': (True, None), 'a/b.txt': (False, b'x')}, False)
    """
    nodes: Dict[Tuple[str, ...], Tuple[bool, Optional[bytes]]] = {}
    for name_or_info, data in members:
        name = name_or_info.filename if isinstance(name_or_info, zipfile.ZipInfo) else name_or_info
        parts = tuple(part for part in name.split("/") if part not in ("", "."))
        is_dir = name.endswith("/")
        if not is_dir and not parts:
            return {}, True  # a file named ``.``: unlink() of ``work`` fails
        last_dir_index = len(parts) if is_dir else len(parts) - 1
        for end in range(1, last_dir_index + 1):
            existing = nodes.get(parts[:end])
            if existing is not None and not existing[0]:
                return {}, True  # a file is in the way of a directory
            nodes[parts[:end]] = (True, None)
        if not is_dir:
            existing = nodes.get(parts)
            if existing is not None and existing[0]:
                return {}, True  # a directory is in the way of a file
            nodes[parts] = (False, data)
    return {"/".join(parts): node for parts, node in nodes.items()}, False


class TestZipMemberProperties:
    """Property tests over generated member names.

    Validates: Requirements 2.1, 2.3, 2.9, 4.11
    """

    @settings(max_examples=100, deadline=None)
    @given(specs=_MEMBER_SPECS)
    def test_nothing_outside_work_is_touched(self, specs):
        """Property 1: the snapshot outside ``work`` is unchanged, and the run exits 1 or writes only inside ``work``.

        **Validates: Requirements 2.1, 2.3, 4.11**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with build_sandbox(Path(tmp_dir)) as sandbox:
                _add_sentinels(sandbox)
                names = [_member_name(sandbox, form, segments, is_dir)
                         for form, segments, is_dir in specs]
                before = sandbox.snapshot()

                exited, code, written = _run_into_work(sandbox, _zip_members(names))

                problems = []
                changes = _describe_changes(before, sandbox.snapshot())
                if changes:
                    problems.append("outside work: " + "; ".join(changes))
                if not (exited and code == 1):
                    work = sandbox.work.resolve()
                    outside = [str(path) for path in written
                               if not path.resolve().is_relative_to(work)]
                    if outside:
                        exit_text = repr(code) if exited else "none"
                        problems.append(
                            f"exit {exit_text}, wrote outside work: {outside}"
                        )
                assert not problems, f"names={names!r}: " + "; ".join(problems)

    @settings(max_examples=100, deadline=None)
    @given(specs=_SAFE_MEMBER_SPECS)
    def test_safe_names_extract_to_expected_tree(self, specs):
        """Property 2: names with no ``..``, no absolute form and no empty segment extract as modeled.

        The expected tree comes from ``_expected_tree`` (same overwrite
        semantics as the extractor). When the model finds a file/directory
        conflict, the run must exit 1, as it does today.

        **Validates: Requirements 2.9, 4.11**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with build_sandbox(Path(tmp_dir)) as sandbox:
                _add_sentinels(sandbox)
                names = [_member_name(sandbox, "relative", segments, is_dir)
                         for segments, is_dir in specs]
                members = _zip_members(names)
                expected, has_conflict = _expected_tree(members)
                before = sandbox.snapshot()

                exited, code, _written = _run_into_work(sandbox, members)

                assert _describe_changes(before, sandbox.snapshot()) == [], f"names={names!r}"
                if has_conflict:
                    assert exited and code == 1, (
                        f"names={names!r}: expected exit 1 on conflict, got "
                        f"exited={exited} code={code!r}"
                    )
                else:
                    assert not exited, f"names={names!r}: exited with code {code!r}"
                    assert _tree_of(sandbox.work) == expected, f"names={names!r}"


# ---------------------------------------------------------------------------
# Preservation tests (observed on unfixed code, must pass before and after the fix)
# ---------------------------------------------------------------------------

# The two sources whose members are stripped (or not) the same way for every
# safe archive below: S3 never strips, ``github-prefix`` strips ``repo-main/``.
SAFE_SOURCE_IDS = ["s3", "github-prefix"]

# A member spec is ``(name, data, kind)`` where kind is ``file``, ``dir`` or
# ``symlink``. ``_build_members`` turns it into a ``_write_zip`` member.
MemberSpec = Tuple[str, bytes, str]


def _build_members(prefix: str, specs: Iterable[MemberSpec]) -> List[ZipMember]:
    """Turn member specs into ``_write_zip`` members, with an optional name prefix.

    Args:
        prefix (str): Text put in front of every member name (``''`` or
            ``'repo-main/'``).
        specs (Iterable[MemberSpec]): ``(name, data, kind)`` triples.

    Returns:
        List[ZipMember]: ``(name_or_info, bytes)`` pairs. ``dir`` members use
            ``_dir_info`` and ``symlink`` members use ``_symlink_info``.

    Example:
        >>> _build_members("", [("a.txt", b"a", "file")])
        [('a.txt', b'a')]
    """
    members: List[ZipMember] = []
    for name, data, kind in specs:
        full_name = prefix + name
        if kind == "dir":
            members.append((_dir_info(full_name), b""))
        elif kind == "symlink":
            members.append((_symlink_info(full_name), data))
        else:
            members.append((full_name, data))
    return members


def _expected_tree_of(
    files: Dict[str, bytes], dirs: Iterable[str] = ()
) -> Dict[str, Tuple[bool, Optional[bytes]]]:
    """Build the tree the test expects in ``work`` (same shape as ``_tree_of``).

    Parent directories of every file and directory are added automatically.

    Args:
        files (Dict[str, bytes]): Relative posix file path to its bytes.
        dirs (Iterable[str]): Relative posix directory paths that must exist
            (for example empty directories).

    Returns:
        dict: Relative posix path to ``(is_dir, content)``.

    Example:
        >>> _expected_tree_of({"a/b.txt": b"x"})
        {'a': (True, None), 'a/b.txt': (False, b'x')}
    """
    tree: Dict[str, Tuple[bool, Optional[bytes]]] = {}
    for directory in dirs:
        parts = Path(directory).parts
        for end in range(1, len(parts) + 1):
            tree["/".join(parts[:end])] = (True, None)
    for path, data in files.items():
        parts = Path(path).parts
        for end in range(1, len(parts)):
            tree["/".join(parts[:end])] = (True, None)
        tree[path] = (False, data)
    return tree


def _files_of(tree) -> Dict[str, bytes]:
    """Return only the file entries of a ``_tree_of`` result.

    Args:
        tree (dict): Result of ``_tree_of``.

    Returns:
        Dict[str, bytes]: Relative posix file path to its bytes.

    Example:
        >>> _files_of({"a": (True, None), "a/b.txt": (False, b"x")})
        {'a/b.txt': b'x'}
    """
    return {path: content for path, (is_dir, content) in tree.items() if not is_dir}


def _extract_safe(
    sandbox: Sandbox,
    source_id: str,
    specs: Iterable[MemberSpec],
    existing: Optional[Dict[str, bytes]] = None,
    prefix: Optional[str] = None,
) -> str:
    """Extract a safe archive through ``_download_and_extract`` and check the invariants.

    Invariants asserted for every safe archive: the call returns the
    extraction directory, ``source.zip`` is gone, and nothing outside ``work``
    changed. The caller must use the ``mocks`` fixture.

    Args:
        sandbox (Sandbox): The sandbox.
        source_id (str): Key of ``SOURCE_CASES``.
        specs (Iterable[MemberSpec]): Members, before the source prefix is added.
        existing (Optional[Dict[str, bytes]]): Files to create in ``work``
            before extraction (relative posix path to bytes).
        prefix (Optional[str]): Name prefix for every member. Defaults to the
            prefix of ``source_id``.

    Returns:
        str: The path returned by ``_download_and_extract``.

    Example:
        >>> result = _extract_safe(sandbox, "s3", [("a.txt", b"a", "file")])
    """
    source_type, has_prefix = SOURCE_CASES[source_id]
    if prefix is None:
        prefix = GITHUB_PREFIX if has_prefix else ""
    creator = _make_creator(source_type=source_type)
    for relative, data in (existing or {}).items():
        target = sandbox.work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    zip_path = sandbox.make_zip(_build_members(prefix, specs))
    before = sandbox.snapshot()

    with _stub_download(creator, zip_path):
        result = creator._download_and_extract()

    assert result == str(sandbox.work)
    assert not (sandbox.work / "source.zip").exists(), "source.zip was not removed"
    assert _describe_changes(before, sandbox.snapshot()) == []
    return result


class TestSafeArchivesUnchanged:
    """Archives whose members stay inside ``work`` extract exactly as before.

    Every case here passes on the unfixed code and must keep passing after the
    fix (the extracted tree, the bytes, and the messages do not change).

    Validates: Requirements 2.9, 3.1, 3.2, 3.3, 3.4, 4.8
    """

    @pytest.mark.parametrize("source_id", SAFE_SOURCE_IDS)
    def test_nested_directories_and_directory_entries(self, mocks, sandbox, source_id):
        """Nested files, directory entries, and an empty directory entry are extracted."""
        _extract_safe(sandbox, source_id, [
            ("src/", b"", "dir"),
            ("src/app/main.py", b"print('main')\n", "file"),
            ("deep/a/b/c/d.txt", b"deep", "file"),
            ("empty/", b"", "dir"),
            ("top.txt", b"top", "file"),
        ])

        expected = _expected_tree_of(
            {"src/app/main.py": b"print('main')\n",
             "deep/a/b/c/d.txt": b"deep",
             "top.txt": b"top"},
            dirs=["src", "empty"],
        )
        assert _tree_of(sandbox.work) == expected

    @pytest.mark.parametrize("source_id", SAFE_SOURCE_IDS)
    def test_inner_dotdot_that_stays_inside_is_extracted_as_b_txt(
        self, mocks, sandbox, source_id
    ):
        """``a/../b.txt`` ends up as ``b.txt`` inside ``work`` and nothing escapes.

        Only the file tree is compared. The unfixed code also leaves an empty
        ``a`` directory behind (``mkdir`` of ``a/..`` creates ``a`` first), and
        the fixed code writes to the resolved path and does not. Both are
        accepted here.
        """
        _extract_safe(sandbox, source_id, [
            ("a/../b.txt", b"inner dotdot", "file"),
            ("c.txt", b"c", "file"),
        ])

        tree = _tree_of(sandbox.work)
        assert _files_of(tree) == {"b.txt": b"inner dotdot", "c.txt": b"c"}
        assert not any(path.startswith("..") for path in tree)

    @pytest.mark.parametrize("source_id", SAFE_SOURCE_IDS)
    def test_existing_file_inside_work_is_replaced(self, mocks, sandbox, source_id):
        """A file already in ``work`` is replaced by the member's bytes; others are kept."""
        _extract_safe(
            sandbox, source_id,
            [("existing.txt", b"new", "file"),
             ("src/app.py", b"new app", "file")],
            existing={"existing.txt": b"old",
                      "src/app.py": b"old app",
                      "keep.txt": b"keep"},
        )

        expected = _expected_tree_of({
            "existing.txt": b"new",
            "src/app.py": b"new app",
            "keep.txt": b"keep",
        })
        assert _tree_of(sandbox.work) == expected

    @pytest.mark.parametrize("source_id", SAFE_SOURCE_IDS)
    def test_symlink_mode_member_is_written_as_regular_file(
        self, mocks, sandbox, source_id
    ):
        """A member with symlink mode bits becomes a regular file with the member's bytes."""
        _extract_safe(sandbox, source_id, [
            ("link", b"../target/path", "symlink"),
            ("real.txt", b"real", "file"),
        ])

        link = sandbox.work / "link"
        assert not link.is_symlink()
        assert link.is_file()
        assert link.read_bytes() == b"../target/path"
        expected = _expected_tree_of({"link": b"../target/path", "real.txt": b"real"})
        assert _tree_of(sandbox.work) == expected

    @pytest.mark.parametrize("source_id", SAFE_SOURCE_IDS)
    def test_crlf_and_non_utf8_members_are_byte_identical(
        self, mocks, sandbox, source_id
    ):
        """CRLF text, non-UTF-8 bytes, and every byte value are written unchanged."""
        crlf = b"line one\r\nline two\r\n\r\nend\r\n"
        non_utf8 = bytes([0xFF, 0xFE, 0x00, 0x80, 0xC3, 0x28, 0xA0, 0xA1])
        all_bytes = bytes(range(256))
        _extract_safe(sandbox, source_id, [
            ("crlf.txt", crlf, "file"),
            ("data/non-utf8.bin", non_utf8, "file"),
            ("data/all-bytes.bin", all_bytes, "file"),
        ])

        assert (sandbox.work / "crlf.txt").read_bytes() == crlf
        assert (sandbox.work / "data" / "non-utf8.bin").read_bytes() == non_utf8
        assert (sandbox.work / "data" / "all-bytes.bin").read_bytes() == all_bytes
        expected = _expected_tree_of({
            "crlf.txt": crlf,
            "data/non-utf8.bin": non_utf8,
            "data/all-bytes.bin": all_bytes,
        })
        assert _tree_of(sandbox.work) == expected

    @pytest.mark.parametrize("source_id", SAFE_SOURCE_IDS)
    def test_source_zip_is_removed_and_file_count_is_echoed(
        self, mocks, sandbox, plain_colors, source_id
    ):
        """``source.zip`` is removed and the extracted file count is echoed and logged."""
        _extract_safe(sandbox, source_id, [
            ("a.txt", b"a", "file"),
            ("dir/", b"", "dir"),
            ("dir/b.txt", b"b", "file"),
            ("dir/sub/c.txt", b"c", "file"),
        ])

        assert not (sandbox.work / "source.zip").exists()
        echoed = [str(arg) for call in mocks.echo.call_args_list for arg in call.args]
        counts = [text for text in echoed if "Extracted files:" in text]
        assert len(counts) == 1, f"expected one 'Extracted files:' message, got {counts}"
        assert counts[0] == "Extracted files: 3"
        mocks.log.info.assert_any_call(f"Extracted 3 files to {sandbox.work}")

    def test_github_shared_prefix_is_stripped_and_root_entry_skipped(
        self, mocks, sandbox
    ):
        """The shared top-level directory is removed and its own entry creates nothing."""
        _extract_safe(sandbox, "github-prefix", [
            ("", b"", "dir"),  # the root entry ``repo-main/``
            ("README.md", b"readme", "file"),
            ("src/", b"", "dir"),
            ("src/app.py", b"app", "file"),
        ])

        tree = _tree_of(sandbox.work)
        assert "repo-main" not in tree
        assert tree == _expected_tree_of(
            {"README.md": b"readme", "src/app.py": b"app"}, dirs=["src"]
        )

    def test_github_members_all_starting_with_dotdot_land_inside_work(
        self, mocks, sandbox
    ):
        """``../`` is detected as the common prefix, stripped, and members land inside ``work``."""
        _extract_safe(sandbox, "github-no-prefix", [
            ("a.txt", b"a", "file"),
            ("sub/b.txt", b"b", "file"),
        ], prefix="../")

        assert _tree_of(sandbox.work) == _expected_tree_of(
            {"a.txt": b"a", "sub/b.txt": b"b"}
        )

    def test_github_without_common_prefix_keeps_member_names(self, mocks, sandbox):
        """With two different top-level directories nothing is stripped."""
        _extract_safe(sandbox, "github-no-prefix", [
            ("dir1/ok.txt", b"one", "file"),
            ("dir2/ok.txt", b"two", "file"),
        ])

        assert _tree_of(sandbox.work) == _expected_tree_of(
            {"dir1/ok.txt": b"one", "dir2/ok.txt": b"two"}
        )

    def test_github_root_file_beside_prefixed_members_keeps_its_name(
        self, mocks, sandbox
    ):
        """A top-level file does not take part in prefix detection and is extracted as named."""
        _extract_safe(sandbox, "github-no-prefix", [
            ("README.md", b"readme", "file"),
            ("repo-main/app.py", b"app", "file"),
            ("repo-main/lib/util.py", b"util", "file"),
        ])

        assert _tree_of(sandbox.work) == _expected_tree_of(
            {"README.md": b"readme", "app.py": b"app", "lib/util.py": b"util"}
        )


def _client_error(code: str) -> botocore.exceptions.ClientError:
    """Build a botocore ``ClientError`` with the given error code.

    Args:
        code (str): Error code such as ``'403'`` or ``'AccessDenied'``.

    Returns:
        botocore.exceptions.ClientError: The error.

    Example:
        >>> _client_error("403").response["Error"]["Code"]
        '403'
    """
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "boom"}}, "GetObject"
    )


def _echoed_and_logged(mocks) -> Tuple[List[str], List[str]]:
    """Return the ``click.echo`` arguments and the ``Log.error`` arguments as strings.

    Args:
        mocks (MagicMock): The ``mocks`` fixture value.

    Returns:
        tuple: ``(echoed, logged)`` lists of strings, in call order.

    Example:
        >>> echoed, logged = _echoed_and_logged(mocks)
    """
    echoed = [str(arg) for call in mocks.echo.call_args_list for arg in call.args]
    logged = [str(arg) for call in mocks.log.error.call_args_list for arg in call.args]
    return echoed, logged


class TestOtherFailuresUnchanged:
    """Failures that are not unsafe members keep their messages, cleanup, and exit codes.

    The outcomes are the ones ``test_create_repo_tempdir_cleanup.py`` and
    ``test_create_repo_download_failure_cleanup.py`` check, observed on the
    unfixed code: an invalid zip and ``AccessDenied`` print the generic message
    and exit 1, while a 403 from ``download_file`` is raised before the
    extraction ``try`` block, so it propagates as a ``ClientError`` with no
    generic message and no CodeCommit deletion from this step.

    Validates: Requirements 3.5, 3.6, 4.9
    """

    @staticmethod
    def _assert_generic_failure(mocks, creator, sandbox, provider):
        """Assert the generic message, log line, cleanup calls, and removed ``work``."""
        echoed, logged = _echoed_and_logged(mocks)
        assert any(GENERIC_FAILURE_TEXT in text for text in echoed), echoed
        assert any(
            text.startswith(f"{GENERIC_FAILURE_TEXT}:") for text in logged
        ), logged
        assert not any("Unsafe source zip" in text for text in echoed + logged)
        assert not sandbox.work.exists(), "temp dir leaked"
        if provider == "codecommit":
            creator.codecommit_client.delete_repository.assert_called_once_with(
                repositoryName=REPO_NAME
            )
        else:
            creator.codecommit_client.delete_repository.assert_not_called()
            mocks.prompt.assert_not_called()
            mocks.run.assert_not_called()

    @pytest.mark.parametrize("provider", ["github", "codecommit"])
    def test_invalid_s3_zip_prints_generic_message_and_exits_1(
        self, mocks, sandbox, provider
    ):
        """A corrupt S3 zip: generic message, CodeCommit repository deleted, exit 1."""
        creator = _make_creator(provider=provider, source_type="s3")
        creator.s3_client.download_file.side_effect = (
            lambda bucket, key, path: Path(path).write_bytes(b"not a zip")
        )

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1
        self._assert_generic_failure(mocks, creator, sandbox, provider)

    @pytest.mark.parametrize("provider", ["github", "codecommit"])
    def test_invalid_github_zip_prints_generic_message_and_exits_1(
        self, mocks, sandbox, provider
    ):
        """A corrupt GitHub zip: generic message, CodeCommit repository deleted, exit 1."""
        creator = _make_creator(provider=provider, source_type="github")
        bad_zip = sandbox.inputs / "bad.zip"
        bad_zip.write_bytes(b"not a zip")

        with _stub_download(creator, bad_zip):
            with pytest.raises(SystemExit) as exit_info:
                creator._download_and_extract()

        assert exit_info.value.code == 1
        self._assert_generic_failure(mocks, creator, sandbox, provider)

    @pytest.mark.parametrize("provider", ["github", "codecommit"])
    def test_access_denied_prints_access_message_then_generic_and_exits_1(
        self, mocks, sandbox, provider
    ):
        """AccessDenied leaves no zip: access message, generic message, delete, exit 1."""
        creator = _make_creator(provider=provider, source_type="s3")
        creator.s3_client.download_file.side_effect = _client_error("AccessDenied")

        with pytest.raises(SystemExit) as exit_info:
            creator._download_and_extract()

        assert exit_info.value.code == 1
        echoed, _logged = _echoed_and_logged(mocks)
        assert any("Access denied when using authenticated access" in text
                   for text in echoed), echoed
        self._assert_generic_failure(mocks, creator, sandbox, provider)

    @pytest.mark.parametrize("provider", ["github", "codecommit"])
    def test_s3_403_propagates_without_generic_message_or_deletion(
        self, mocks, sandbox, provider
    ):
        """A 403 escapes the extraction ``try``: ``ClientError``, no generic message, temp dir removed."""
        creator = _make_creator(provider=provider, source_type="s3")
        creator.s3_client.download_file.side_effect = _client_error("403")

        with pytest.raises(botocore.exceptions.ClientError):
            creator._download_and_extract()

        echoed, logged = _echoed_and_logged(mocks)
        assert not any(GENERIC_FAILURE_TEXT in text for text in echoed + logged)
        assert not sandbox.work.exists(), "temp dir leaked"
        creator.codecommit_client.delete_repository.assert_not_called()
        mocks.prompt.assert_not_called()
        mocks.run.assert_not_called()

    def test_github_run_offers_cleanup_once_for_each_failure(self, mocks, sandbox):
        """Through ``create_and_seed_repository`` the GitHub handler runs once per failure."""
        failures = [
            ("invalid zip", None, SystemExit),
            ("AccessDenied", _client_error("AccessDenied"), SystemExit),
            ("403", _client_error("403"), botocore.exceptions.ClientError),
        ]
        for label, error, expected in failures:
            creator = _make_creator(provider="github", source_type="s3")
            creator._handle_github_seeding_failure = MagicMock()
            if error is None:
                creator.s3_client.download_file.side_effect = (
                    lambda bucket, key, path: Path(path).write_bytes(b"not a zip")
                )
            else:
                creator.s3_client.download_file.side_effect = error
            # The sandbox ``work`` directory is removed by each failed run.
            sandbox.work.mkdir(parents=True, exist_ok=True)

            with pytest.raises(expected) as exc_info:
                creator.create_and_seed_repository()

            if expected is SystemExit:
                assert exc_info.value.code == 1, label
            creator._handle_github_seeding_failure.assert_called_once_with()
            creator.codecommit_client.delete_repository.assert_not_called()
            assert not sandbox.work.exists(), f"{label}: temp dir leaked"


class TestFlowUnchanged:
    """``create_and_seed_repository`` keeps its step order.

    Validates: Requirements 3.7, 3.9, 4.9
    """

    @staticmethod
    def _recording_creator(provider: str):
        """Build a creator whose four flow steps record their call order.

        Args:
            provider (str): ``'github'`` or ``'codecommit'``.

        Returns:
            tuple: ``(creator, order, seeded)``. ``order`` collects step names
                and ``seeded`` collects the argument given to ``_seed_repository``.
        """
        creator = _make_creator(provider=provider)
        order: List[str] = []
        seeded: List[str] = []

        creator._create_repository = MagicMock(
            side_effect=lambda: order.append("_create_repository"))
        creator._create_dev_test_branches = MagicMock(
            side_effect=lambda: order.append("_create_dev_test_branches"))

        def fake_download_and_extract():
            order.append("_download_and_extract")
            return "/tmp/seed-dir"

        def fake_seed_repository(temp_dir):
            order.append("_seed_repository")
            seeded.append(temp_dir)

        creator._download_and_extract = MagicMock(side_effect=fake_download_and_extract)
        creator._seed_repository = MagicMock(side_effect=fake_seed_repository)
        creator._merge_dev_to_test = MagicMock()
        return creator, order, seeded

    @pytest.mark.parametrize("provider", ["github", "codecommit"])
    def test_steps_run_in_order_and_seed_gets_the_extracted_dir(self, mocks, provider):
        """Create, branches, download and extract, then seed (with the extracted dir)."""
        creator, order, seeded = self._recording_creator(provider)

        creator.create_and_seed_repository()

        assert order == [
            "_create_repository",
            "_create_dev_test_branches",
            "_download_and_extract",
            "_seed_repository",
        ]
        assert seeded == ["/tmp/seed-dir"]
        creator._merge_dev_to_test.assert_called_once_with()

    @pytest.mark.parametrize("provider", ["github", "codecommit"])
    def test_without_source_only_create_and_branches_run(self, mocks, provider):
        """With no ``--source`` nothing is downloaded, seeded, or merged."""
        creator, order, _seeded = self._recording_creator(provider)
        creator.source = None

        creator.create_and_seed_repository()

        assert order == ["_create_repository", "_create_dev_test_branches"]
        creator._merge_dev_to_test.assert_not_called()


# ---------------------------------------------------------------------------
# Helper unit tests (_resolve_member_path, _escape_member_name)
# ---------------------------------------------------------------------------

class TestResolveMemberPath:
    """``_resolve_member_path`` accepts names inside the base and rejects the rest.

    The helper is called directly with a real directory. The returned path is the
    resolved path, which is also the path the extractor writes to.

    Validates: Requirements 2.1, 2.3, 2.4, 2.9
    """

    @pytest.fixture
    def base(self, tmp_path):
        """A real extraction directory, resolved so comparisons are exact."""
        base_dir = tmp_path / "work"
        base_dir.mkdir()
        return base_dir.resolve()

    @pytest.mark.parametrize("name, expected_parts", [
        ("ok.txt", ("ok.txt",)),
        ("a/b/c.txt", ("a", "b", "c.txt")),
        ("a/../b.txt", ("b.txt",)),
        ("./x.txt", ("x.txt",)),
    ])
    def test_name_inside_base_returns_resolved_path(self, base, name, expected_parts):
        """Names that stay inside the base return ``<base>/<normalized name>``."""
        result = RepositoryCreator._resolve_member_path(base, name)

        assert result == base.joinpath(*expected_parts)
        assert result == result.resolve()

    @pytest.mark.parametrize("name", [".", ""])
    def test_name_resolving_to_base_is_accepted(self, base, name):
        """``.`` and the empty name resolve to the base itself and are not an escape."""
        assert RepositoryCreator._resolve_member_path(base, name) == base

    def test_base_dir_may_be_a_string(self, base):
        """A ``str`` base works the same as a ``Path``."""
        result = RepositoryCreator._resolve_member_path(str(base), "a/b.txt")

        assert result == base / "a" / "b.txt"

    @pytest.mark.parametrize("name", [
        "../x",
        "a/../../x",
        "../work-evil/x",
    ])
    def test_name_outside_base_is_rejected(self, base, name):
        """``..`` names and a sibling that shares the base name as a prefix are rejected."""
        with pytest.raises(create_repo.UnsafeZipMemberError) as excinfo:
            RepositoryCreator._resolve_member_path(base, name)

        message = str(excinfo.value)
        assert repr(name) in message
        assert "outside the extraction directory" in message

    def test_sibling_prefix_name_resolves_to_base_evil(self, base):
        """The sibling-prefix name lands in ``<base>-evil``, which a string prefix test would accept."""
        sibling = Path(str(base) + "-evil")
        name = "../" + sibling.name + "/x"

        assert (base / name).resolve() == sibling / "x"
        assert str(sibling / "x").startswith(str(base))
        with pytest.raises(create_repo.UnsafeZipMemberError) as excinfo:
            RepositoryCreator._resolve_member_path(base, name)

        assert repr(name) in str(excinfo.value)
        assert "outside the extraction directory" in str(excinfo.value)

    def test_absolute_name_is_rejected(self, base, tmp_path):
        """An absolute name built from the test directory is rejected."""
        name = (tmp_path / "abs-test.txt").as_posix()

        with pytest.raises(create_repo.UnsafeZipMemberError) as excinfo:
            RepositoryCreator._resolve_member_path(base, name)

        message = str(excinfo.value)
        assert repr(name) in message
        assert "outside the extraction directory" in message

    def test_error_shows_member_name_when_given(self, base):
        """``member_name`` is the name shown, not the stripped ``relative_name``."""
        with pytest.raises(create_repo.UnsafeZipMemberError) as excinfo:
            RepositoryCreator._resolve_member_path(
                base, "../x", "repo-main/../../x"
            )

        message = str(excinfo.value)
        assert repr("repo-main/../../x") in message
        assert repr("../x") not in message

    def test_error_escapes_control_characters_in_name(self, base):
        """A name with a newline and an ESC byte is reported only in escaped form."""
        name = "../x\n\x1b[31m"

        with pytest.raises(create_repo.UnsafeZipMemberError) as excinfo:
            RepositoryCreator._resolve_member_path(base, name)

        message = str(excinfo.value)
        assert "\\n" in message
        assert "\\x1b" in message
        assert "\n" not in message
        assert "\x1b" not in message

    def test_rejection_creates_nothing(self, base, tmp_path):
        """The helper only computes a path. It does not create or change anything."""
        before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

        with pytest.raises(create_repo.UnsafeZipMemberError):
            RepositoryCreator._resolve_member_path(base, "../new/x")
        RepositoryCreator._resolve_member_path(base, "new/x")

        after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        assert after == before


class TestEscapeMemberName:
    """``_escape_member_name`` returns a quoted, escaped, length-capped name.

    Validates: Requirements 2.4, 2.9
    """

    def test_ordinary_name_is_quoted(self):
        """An ordinary name is returned in ``repr()`` form."""
        assert RepositoryCreator._escape_member_name("src/app.py") == "'src/app.py'"

    def test_newline_is_escaped(self):
        """A newline appears as ``\\n`` and never as a raw line break."""
        escaped = RepositoryCreator._escape_member_name("a\nb")

        assert escaped == "'a\\nb'"
        assert "\n" not in escaped

    def test_escape_character_is_escaped(self):
        """An ESC byte appears as ``\\x1b`` and never as a raw control character."""
        escaped = RepositoryCreator._escape_member_name("x\x1b[31m")

        assert escaped == "'x\\x1b[31m'"
        assert "\x1b" not in escaped

    def test_bidirectional_override_is_escaped(self):
        """``repr()`` escapes the right-to-left override ``\\u202e`` as text."""
        escaped = RepositoryCreator._escape_member_name("evil\u202etxt.exe")

        assert escaped == "'evil\\u202etxt.exe'"
        assert "\u202e" not in escaped

    def test_long_name_is_cut_with_ellipsis(self):
        """A name longer than the cap ends with ``...`` and is at most the cap."""
        escaped = RepositoryCreator._escape_member_name("a" * 1000)

        assert escaped.endswith("...")
        assert len(escaped) == 200

    def test_custom_cap_is_respected(self):
        """The ``max_length`` argument sets the cap."""
        escaped = RepositoryCreator._escape_member_name("a" * 100, max_length=20)

        assert escaped.endswith("...")
        assert len(escaped) <= 20

    def test_name_at_the_cap_is_not_cut(self):
        """A quoted name of exactly the cap length is returned whole."""
        escaped = RepositoryCreator._escape_member_name("a" * 198)

        assert len(escaped) == 200
        assert not escaped.endswith("...")


# ---------------------------------------------------------------------------
# Windows path forms (characterization of the stdlib rule only)
# ---------------------------------------------------------------------------

class TestWindowsPathFormsCharacterization:
    """Documents the stdlib path rule that the containment check relies on.

    This does not run ``_resolve_member_path``. The helper resolves against the
    real filesystem, which a pure path cannot stand in for on Linux, so these
    tests only record how ``PureWindowsPath`` treats the Windows name forms: a
    drive-absolute name (``C:/x``), a drive-relative name (``D:x``), and a UNC
    name (``\\\\host\\share\\x``) replace the base when joined, so the result is
    not relative to the base. A ``..\\x`` name keeps the base as a lexical prefix
    when joined, and only leaves it once normalized, which is why the helper
    resolves the joined path before comparing.

    R2 verifies the helper itself on Windows (requirement 4.10).

    Validates: Requirements 4.10
    """

    BASE = PureWindowsPath("C:/tmp/work")

    @pytest.mark.parametrize("name", [
        "C:/x",
        "D:x",
        "\\\\host\\share\\x",
    ])
    def test_replacing_forms_are_not_relative_to_base(self, name):
        """Joining a drive, drive-relative, or UNC name replaces the base."""
        joined = self.BASE / name

        assert not joined.is_relative_to(self.BASE)

    @pytest.mark.parametrize("name", [
        "..\\x",
        "a\\..\\..\\x",
    ])
    def test_dotdot_forms_leave_base_once_normalized(self, name):
        """``..`` names look relative until the ``..`` segments are applied."""
        joined = self.BASE / name
        normalized = PureWindowsPath(ntpath.normpath(str(joined)))

        assert joined.is_relative_to(self.BASE)
        assert not normalized.is_relative_to(self.BASE)
        assert normalized == PureWindowsPath("C:/tmp/x")

    def test_ordinary_name_stays_relative_to_base(self):
        """A plain relative name is inside the base, with or without normalization."""
        joined = self.BASE / "a\\b.txt"
        normalized = PureWindowsPath(ntpath.normpath(str(joined)))

        assert joined.is_relative_to(self.BASE)
        assert normalized.is_relative_to(self.BASE)
