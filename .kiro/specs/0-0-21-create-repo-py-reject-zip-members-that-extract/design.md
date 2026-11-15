# Reject Zip Members That Extract Outside the Temp Directory - Bugfix Design

## Overview

`RepositoryCreator._download_and_extract_into` (`cli/create_repo.py`) builds each member's `output_path` as `Path(temp_dir) / <name>` at three places (S3 members, GitHub members with the common prefix stripped, GitHub members without it) and then creates directories, unlinks any existing file, and writes bytes. Nothing checks that the path stays inside `temp_dir`, so a member such as `../outside-test.txt`, an absolute name, or `repo-main/../../x` is written outside the extraction directory ([issue #12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12)).

The fix adds one private check and one exception to `cli/create_repo.py`:

- `_resolve_member_path(base_dir, relative_name, member_name=None)` resolves `base_dir / relative_name`, requires the result to be `base_dir` or inside it, and returns the resolved path. Otherwise it raises `UnsafeZipMemberError`.
- The extraction loop computes the member's relative name once (replacing the three `output_path = Path(temp_dir) / ...` assignments), calls the helper once, and uses the returned path for every later step (`mkdir`, `parent.mkdir`, `unlink`, `write_bytes`).
- The existing `except Exception` block in `_download_and_extract_into` prints a specific message when the exception is `UnsafeZipMemberError`, and otherwise behaves as before. Cleanup, CodeCommit deletion, exit status, and temporary directory removal are the existing steps.

No CLI option, function signature, AWS call, or repository-creation order changes. The decisions behind this design are locked in [PLAN.md](PLAN.md) (Decisions 1 to 5, D1 to D6), and the numbered requirements are in [requirements.md](requirements.md).

## Glossary

- **Bug_Condition (C)**: A zip member whose `output_path`, after the GitHub common prefix is stripped when it applies, resolves outside the extraction directory.
- **Property (P)**: No directory is created, no file is removed, and no byte is written outside the extraction directory. The run fails with a specific error instead.
- **Preservation**: Members that stay inside the extraction directory are extracted exactly as before. Failure handling for every other error, repository creation order, CLI options, and `update.py` are unchanged.
- **Extraction directory**: The directory created by `tempfile.mkdtemp()` in `_download_and_extract` and passed to `_download_and_extract_into` as `temp_dir`.
- **Relative name**: The member name the loop joins to the extraction directory: `zip_info.filename` for S3, and for GitHub the name with `common_prefix` removed when it applies.
- **Containment**: `Path(base_dir).resolve()` is the resolved target or one of its parents (`Path.is_relative_to`).

## Bug Details

### Bug Condition

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type ExtractionRun (source type, zip members, extraction directory B)
  OUTPUT: boolean
  RETURN EXISTS member IN X.members WHERE
      LET name = relativeName(member, X.sourceType)
      NOT isWithin(resolve(B / name), resolve(B))
END FUNCTION
```

`relativeName` is the member's name after prefix stripping for GitHub sources and the member's name otherwise. `B / name` follows `pathlib` rules: an absolute `name` replaces `B` (on Windows also `C:/x`, `D:x`, and `\\host\share\x`).

### Examples

- S3 zip with `../outside-test.txt`: written in the directory above the extraction directory (reproduced, PLAN.md Section 2).
- S3 zip with an absolute member name: written at that absolute path (reproduced).
- GitHub zip with `repo-main/ok.txt` and `repo-main/../../outside2.txt`: the second member strips to `../../outside2.txt` and was written two levels above (reproduced).
- Directory member `../evil/`: `mkdir(parents=True)` creates it outside (by reading).
- Existing file at the target: `unlink()` removes it before the write (by reading).
- GitHub zip where every member starts with `../`: `../` is detected as the common prefix and stripped, so members land inside. Safe by accident, unchanged by this fix.

## Expected Behavior

### Preservation Requirements

- Safe members: same files, same bytes (`write_bytes`), same directory entries, same `unlink` before write, same file count message.
- GitHub prefix detection and stripping: unchanged.
- Failure handling for invalid zips, download errors, and access errors: unchanged (generic message, CodeCommit deletion, exit 1).
- `create_and_seed_repository` order and cleanup ownership: unchanged. The GitHub cleanup prompt still runs once, in the outer handler.
- No new option, no `cli/lib/` change, no `update.py` change.

## Hypothesized Root Cause

The extraction loop treats zip member names as trusted relative paths. `pathlib` does not constrain a join: `Path('/t') / '../x'` stays a `..` path, and `Path('/t') / '/etc/x'` is `/etc/x`. The loop was written to handle the GitHub outer directory, not hostile names, and the original author's trust model was "the user chooses the zip". There is no commit message or comment giving another reason (PLAN.md Section 3).

## Correctness Properties

**Property 1: Bug Condition - Containment.**
FOR ANY extraction run X where isBugCondition(X) holds, `_download_and_extract_into` SHALL raise `UnsafeZipMemberError` for the first offending member, before any directory is created, any file removed, or any byte written for that member or any later member, and the run SHALL end with exit status 1. Nothing outside the extraction directory is created, changed, or removed.
Validates: requirements 2.1 to 2.5, 2.8.

**Property 2: Fail-closed failure path.**
FOR ANY X where isBugCondition(X) holds, the CodeCommit provider SHALL call `_delete_codecommit_repository` exactly once, the GitHub provider SHALL leave cleanup to `create_and_seed_repository`, and the printed error and log line SHALL contain the member name only in escaped `repr()` form, length capped.
Validates: requirements 2.4, 2.6, 2.7.

**Property 3: Preservation - Safe archives.**
FOR ANY extraction run X where NOT isBugCondition(X), the extracted tree SHALL equal the tree produced by the unfixed code: same relative paths, same bytes, same directories.
Validates: requirements 2.9, 3.1 to 3.4.

**Property 4: Preservation - Other failures and flow.**
The generic failure message, exit codes, cleanup handler calls, repository creation order, and CLI options SHALL be unchanged.
Validates: requirements 3.5 to 3.9.

## Fix Implementation

### Changes Required

All changes are in `cli/create_repo.py`, plus `docs/SCRIPT-GUIDE.md`, `CHANGELOG.md`, and a new test file.

**1. Exception (module level, after the imports, before `RepositoryCreator`).**

```python
class UnsafeZipMemberError(ValueError):
    """Raised when a zip member would be extracted outside the extraction directory.

    The message already holds the member name in escaped form, so it is safe to
    print or log as is.

    Example:
        >>> raise UnsafeZipMemberError("zip member '../x' resolves outside the extraction directory")
        Traceback (most recent call last):
        ...
        UnsafeZipMemberError: zip member '../x' resolves outside the extraction directory
    """
```

`ValueError` is the base because the error is an invalid input value, and it keeps the existing `except Exception` handler catching it.

**2. Name escaping (static method on `RepositoryCreator`).**

```python
@staticmethod
def _escape_member_name(name: str, max_length: int = 200) -> str:
    escaped = repr(name)
    if len(escaped) > max_length:
        escaped = escaped[:max_length - 3] + '...'
    return escaped
```

`repr()` escapes control characters, `\n`, `\x1b` (so ANSI sequences print as text), and non-printable Unicode such as bidirectional overrides. It also quotes the name, which makes a name with trailing spaces visible. The cap keeps a very long name from flooding the terminal or the log. Full docstring with Args, Returns, and Example per `documentation-standards-python`.

**3. Containment check (static method on `RepositoryCreator`).**

```python
@staticmethod
def _resolve_member_path(base_dir, relative_name: str, member_name: Optional[str] = None) -> Path:
    base = Path(base_dir).resolve()
    target = (base / relative_name).resolve()
    if not target.is_relative_to(base):
        shown = member_name if member_name is not None else relative_name
        raise UnsafeZipMemberError(
            f"zip member {RepositoryCreator._escape_member_name(shown)} "
            f"resolves outside the extraction directory"
        )
    return target
```

- `Path.is_relative_to` is true when `target == base`, so a member that normalizes to the extraction directory itself is not an escape. For a file member this later fails at `exists()`/`unlink()`/`write_bytes` on a directory, which goes through the generic failure path and exit 1. A zip member with that name is malformed, so failing closed is the right result.
- It compares whole path parts, so a sibling such as `<base>-evil/x` is rejected (checked with a prototype: sibling `False`). This is the case a string `startswith` check gets wrong, and the reason PLAN.md does not reuse the `update.py` check.
- `resolve()` is not strict, so targets that do not exist yet resolve normally. The extraction directory is created by this process and nothing creates symlinks in it (the loop writes regular files only), so resolving the target does not follow a link out of the directory.
- `member_name` is the original zip member name, passed so the error shows what is in the zip even after prefix stripping. It defaults to `relative_name`.
- The method returns the resolved path, and the loop uses it for writing. The checked path and the written path are therefore the same path, with no gap between check and use.
- Platform behavior (checked with `PureWindowsPath` and the stdlib source in PLAN.md Section 3): on Windows `ZipInfo` already turns `\` into `/`, a right side of `C:/x`, `D:x`, or `\\host\share\x` replaces the left side in a join, and Windows path comparison is case-insensitive. The resolved comparison handles all of these without special cases. On Linux a backslash is an ordinary character, so `..\x` is a literal file name inside the directory.
- Any other exception from `resolve()` (for example `OSError`) is not caught here. It reaches the generic handler and the run fails closed with exit 1.

**4. Extraction loop (`_download_and_extract_into`).** The three assignments become a relative name, and one call produces the path.

```python
# Extract all files
for zip_info in zip_ref.filelist:
    relative_name = zip_info.filename
    # For GitHub sources, handle the outer directory
    if self.source_type == 'github':
        # Skip the root directory entry itself
        if common_prefix and zip_info.filename == common_prefix:
            continue

        # Remove the common prefix if it exists
        if common_prefix and zip_info.filename.startswith(common_prefix):
            relative_name = zip_info.filename[len(common_prefix):]

    # Reject names that resolve outside temp_dir before anything is created
    output_path = self._resolve_member_path(temp_dir, relative_name, zip_info.filename)

    if zip_info.filename.endswith('/'):
        output_path.mkdir(parents=True, exist_ok=True)
        continue
    ...  # unchanged from here: parent mkdir, read bytes, unlink, write_bytes
```

The comparison with the current code: in the GitHub branch without a prefix and in the S3 branch the name is `zip_info.filename`, which is the initial value of `relative_name`. The prefix detection pass above the loop is not touched.

**5. Failure handler (`except Exception as e` at the end of `_download_and_extract_into`).** Keep one handler, so the cleanup steps are not duplicated, and pick the message by type:

```python
except Exception as e:
    if isinstance(e, UnsafeZipMemberError):
        click.echo(Colorize.error(f"Unsafe source zip: {e}. Nothing was seeded."))
        Log.error(f"Unsafe source zip rejected: {e}")
    else:
        click.echo(Colorize.error(f"Error in download and extract process. Check logs for more information."))
        Log.error(f"Error in download and extract process: {str(e)}")
    if self.provider == 'codecommit':
        self._delete_codecommit_repository()
    # GitHub: cleanup is offered once by create_and_seed_repository
    # The temp dir is removed by _download_and_extract
    sys.exit(1)
```

`e` already holds the escaped name (built in the helper), so the message and the log line never contain the raw name. `sys.exit(1)` raises `SystemExit`, which `create_and_seed_repository` catches for the GitHub cleanup prompt and re-raises unchanged. `_download_and_extract` removes the temporary directory in its `finally`. This is the existing flow, so no call site changes.

**6. Documentation, version, changelog** (requirements 5.1 to 5.5).

- `docs/SCRIPT-GUIDE.md`, `create_repo.py` section: add a short paragraph after the usage block stating that a source zip with a path that resolves outside the extraction directory is rejected, the run exits with status 1, a CodeCommit repository is deleted, and a GitHub repository is kept unless the prompt is answered `y` or `--cleanup-on-failure` is set.
- `VERSION`: `cli/create_repo.py` is `v0.2.5/2026-11-14`. Compare the date with the implementation date. If it differs, PATCH to `v0.2.6/<date>`. If it matches, leave it.
- `CHANGELOG.md`: add a `### Security` entry under `v0.0.21 (unreleased)` in the style of the neighbouring entries, with the spec link and `addresses #12`. State what is rejected, the exit status, the repository-created-first behavior with the existing cleanup options, and that nothing already seeded is affected. No exploit steps. The version in the entry matches the `VERSION` marker.

### Files Not Changed

- `cli/update.py` and everything in `cli/lib/`.
- `README.md`, `AGENTS-FOR-END-USE.md`.
- `create_and_seed_repository`, `_download_and_extract`, and the S3 and GitHub download code.
- Existing tests (none encodes traversal behavior).

## Testing Strategy

### Validation Approach

Write the tests first and run them against the unfixed code to see them fail (exploration), then apply the fix and run them again (fix checking), then run the whole suite (preservation). Every test builds its zips in the test, stubs the download, and uses a test-owned directory.

**Test safety.** Run against the unfixed code, a traversal test really writes outside the extraction directory. So every test places the extraction directory deep inside a sandbox under pytest's `tmp_path` (for example `tmp_path/sandbox/a/b/c/d/work`), and every name that can escape is bounded to stay within the sandbox: at most four `..` segments, and absolute names are built from the sandbox path, never from a real path such as `/etc`. The sentinel files and the before/after tree snapshot live in the sandbox, outside `work`.

### Exploratory Bug Condition Checking

Goal: show the flaw on the unfixed code and confirm the root cause.
Plan:
1. S3 zip with `../outside-test.txt`: unfixed code writes it in the parent of `work`.
2. S3 zip with an absolute name built from the sandbox: unfixed code writes at that path.
3. GitHub zip with `repo-main/../../outside2.txt`: unfixed code writes two levels above.
4. Directory member `../evil/`: unfixed code creates the directory above.
5. Existing sentinel file at the target: unfixed code replaces its content.
These must fail (the assertions say nothing is written outside) before the fix and pass after it. If one does not fail, the hypothesis about that path is wrong and the design is revisited.

### Fix Checking

Tests in `tests/test_create_repo_zip_safety.py` (requirements 4.2 to 4.7):

- `TestRejectsEscapingMembers`: parameterized over source (`s3`, `github` with prefix, `github` without prefix) and member kind (`..` file, absolute file, `..` directory, unsafe only after prefix stripping). Each case calls `_download_and_extract` through the `temp_dirs` and `mocks` fixtures from `tests/test_create_repo_tempdir_cleanup.py` (copied, not imported, matching how the existing modules are written), asserts `SystemExit` with code 1, the sentinel outside `work` unchanged, no new entry in the sandbox snapshot outside `work`, and the temporary directory gone.
- `TestFailurePath`: CodeCommit calls `_delete_codecommit_repository` once. GitHub does not call `_handle_github_seeding_failure` from the extraction step. A run through `create_and_seed_repository` with `_create_repository`, `_create_dev_test_branches`, and the GitHub failure handler mocked checks that the handler runs once.
- `TestMessage`: a member name with a newline and an ANSI escape is printed and logged only as its `repr()`. The test asserts the output contains `\\n` and `\\x1b` as text, contains no raw `\n` from the name inside the message and no raw `\x1b`, and that a 1,000-character name is capped. The generic "Error in download and extract process" text is absent for this error.
- `TestStopsAtFirstUnsafeMember`: members `a.txt`, `../b.txt`, `c.txt` in that order. After rejection `c.txt` was never written. (`a.txt` may exist in the temp directory until cleanup. The test asserts on what was written outside, and that the temp directory is removed.)

### Preservation Checking

- `TestSafeArchivesUnchanged`: nested directories, `a/../b.txt` (extracted as `b.txt`), a GitHub zip whose members all start with `../` (extracted inside), a symlink-mode member (`ZipInfo.external_attr` with `0o120000 << 16`) written as a regular file with the member's bytes, a CRLF member and a non-UTF-8 member byte-identical. For the S3 and GitHub-prefix cases the extracted tree is compared with the expected tree built in the test.
- `TestOtherFailuresUnchanged`: invalid zip, S3 403, and access denied still print the generic message, delete the CodeCommit repository, and exit 1. These duplicate checks in `test_create_repo_tempdir_cleanup.py` for the unsafe-member branch only, so that a regression in the handler's `else` branch is caught here too.
- The existing 137 `tests/test_create_repo_*.py` tests, and the rest of `tests/` and `cli/lib/test_*.py`, run unchanged.

### Unit Tests

- `_resolve_member_path`, called directly with a real directory: `ok.txt`, `a/b/c.txt`, `a/../b.txt`, `.` and the empty name (resolve to the base, accepted), `../x`, `a/../../x`, an absolute path, and a sibling-prefix case (name resolving to `<base>-evil/x`, rejected). The returned path is the resolved path.
- `_escape_member_name`: ordinary name, control characters, ANSI escape, a bidirectional override character (escaped by `repr()`), and a name longer than the cap (ends with `...`, length at most the cap).
- Windows path forms (requirement 4.10): `_resolve_member_path` resolves against the real filesystem, so it cannot take a `PureWindowsPath` base on Linux. One characterization test asserts that for `PureWindowsPath('C:/tmp/work')`, joining `C:/x`, `D:x`, and `\\host\share\x` yields a path that is not relative to the base, and joining `..\x` and `..` forms yields a lexical path that normalizes outside it. Its docstring says it documents the stdlib rule the helper relies on and does not exercise the helper. The helper itself is verified on Windows by R2.

### Property-Based Tests

`hypothesis` is already in `cli/requirements-test.txt`. One property in `tests/test_create_repo_zip_safety.py` (requirement 4.11):

- Strategy: a list of 1 to 8 member names, each a join of 1 to 5 segments drawn from ordinary names (`a`, `dir`, `x.txt`), `..`, `.`, and the empty string, optionally prefixed by `/` or by the sandbox path as an absolute name, with `..` bounded as in the safety note. Names ending in `/` are directory members.
- Property: after running `_download_and_extract_into` (catching `SystemExit`), every path under the sandbox that is outside `work` is unchanged compared with the snapshot taken before the run, and the run either raised `SystemExit(1)` (rejected) or left every written path inside `work`. A second property for names with no `..` and no absolute form asserts the run succeeds and the extracted tree equals the expected tree.
- `@settings(max_examples=100, deadline=None)`, using `tmp_path_factory` or a fresh directory per example (the pytest `tmp_path` fixture is shared across examples and must not be used directly with Hypothesis unless the test cleans the sandbox each example).

### Integration Tests

No network, AWS, or GitHub test. Real behavior is covered by the verification steps (requirements 6.1 to 6.3):

- The four public starter zips run through the check (all must pass). This can be a maintainer script, not a committed test.
- R2 on Windows Git Bash with a throwaway CodeCommit repository and a harmless `..\outside-test.txt` member.

### Additions Beyond requirements.md

These choices were made in the design and can be vetoed:

1. The helper returns the resolved path and the loop writes to it, so the checked path and the written path are identical. This changes the written path only for names like `a/../b.txt`, which is written as `b.txt`, the location the OS would have used.
2. The helper has an optional third parameter `member_name` so the error shows the original zip name rather than the stripped name. Requirements 2.1 say the helper "takes the extraction directory and the member's relative name", and the optional parameter does not conflict with that.
3. One `except Exception` handler with an `isinstance` branch replaces the "separate `except UnsafeZipMemberError` in front" described in PLAN.md Section 4.2, to avoid duplicating the CodeCommit deletion and `sys.exit(1)`. The behavior is the same.
4. A member that normalizes to the extraction directory itself is accepted by the check and fails later through the generic path. It is not given its own message.
5. The error text is "Unsafe source zip: zip member '<escaped>' resolves outside the extraction directory. Nothing was seeded." The exact wording can change if tests assert on the key parts only (escaped name, "outside the extraction directory", "Nothing was seeded").
6. Tests use a deep sandbox and bounded `..` counts so that exploration against the unfixed code cannot write outside `tmp_path`.
