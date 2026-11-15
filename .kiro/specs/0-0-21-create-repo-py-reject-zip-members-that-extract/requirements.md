# Requirements: Reject Zip Members That Extract Outside the Temp Directory

## Introduction

When `create_repo.py` extracts a starter zip, it builds each output path as `Path(temp_dir) / <member name>` and writes to it without checking that the path stays inside `temp_dir`. A member whose name contains `..` segments, or is absolute, is written outside the temporary directory. This is reported in [issue #12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12) as a hardening finding found by reading the code. No incident is known. The decisions behind these requirements are locked in [PLAN.md](PLAN.md).

`RepositoryCreator._download_and_extract_into` (`cli/create_repo.py`) computes `output_path` at three places: after stripping the common top-level prefix of a GitHub zip, for a GitHub member that does not start with that prefix, and for every member of an S3 zip. It then creates parent directories (or the directory itself for directory members), unlinks any existing file at `output_path`, and writes the member's bytes. PLAN.md Section 2 reproduces the flaw in a scratch directory with a mocked download: a `..` member and an absolute member were written outside the extraction directory for S3 sources, and `repo-main/../../x` escaped after prefix stripping for GitHub sources. The write replaces an existing file, so the reachable damage is replacement of any file the user can write.

The zip comes from `--source` or the organization's starter list. The risk is low when the source is trusted and matters when someone points `--source` at a zip they do not control (any `s3://.../*.zip` or `https://github.com/.../*.zip` URL is accepted).

**Bug condition C(X):** a zip member, after the GitHub common prefix is stripped when it applies, produces an `output_path` whose resolved location is not the extraction directory or inside it. This covers file members and directory members, and both source types.

The fix adds one private containment check that runs on the final `output_path` for every member before anything is created or written for that member. An unsafe member fails the whole run with a specific error that shows the member name escaped. The run then follows the existing failure path (CodeCommit repository deleted, GitHub cleanup prompt or `--cleanup-on-failure`, temporary directory removed, exit status 1). The repository is still created before the zip is downloaded, so "without creating the repository" in the issue is read as "without seeding" (PLAN.md Decision 2).

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN an S3 zip contains a file member whose name has a `..` segment that leads outside the extraction directory (for example `../outside-test.txt`) THEN the system creates parent directories and writes the file outside the extraction directory

1.2 WHEN an S3 zip contains a file member with an absolute name THEN the system writes the file at that absolute path, because `Path(temp_dir) / <absolute name>` is the absolute name

1.3 WHEN a GitHub zip contains a member that, after the common top-level prefix is stripped, has a `..` segment that leads outside the extraction directory (for example `repo-main/../../x`) THEN the system writes the file outside the extraction directory

1.4 WHEN a zip contains a directory member that resolves outside the extraction directory THEN the system calls `mkdir(parents=True, exist_ok=True)` and creates the directories outside the extraction directory

1.5 WHEN a member resolves outside the extraction directory and a file already exists at that location THEN the system removes the existing file with `unlink()` and writes the member's bytes in its place

1.6 WHEN extraction fails for any reason, including an unsafe member THEN the system prints only "Error in download and extract process. Check logs for more information." and does not tell the user that the zip contains an unsafe path

### Expected Behavior (Correct)

2.1 WHEN `_download_and_extract_into` determines the `output_path` of a member, for an S3 source or a GitHub source, with or without common-prefix stripping, THEN the system SHALL resolve that path and SHALL require it to be the extraction directory or inside it, using one shared private check that takes the extraction directory and the member's relative name

2.2 WHEN the member is a directory member THEN the system SHALL run the same check before `mkdir` is called

2.3 WHEN the check fails THEN the system SHALL raise `UnsafeZipMemberError` (a `ValueError` subclass defined in `cli/create_repo.py`) before creating any directory, unlinking any file, or writing any byte for that member

2.4 WHEN `UnsafeZipMemberError` is raised during extraction THEN the system SHALL print a specific error through `Colorize.error` that names the member using `repr()`-style escaping with a length cap, says the source zip contains a path outside the extraction directory, and says nothing was seeded, and SHALL log the same escaped name at ERROR level, so control characters or terminal escape sequences in an untrusted name cannot alter the terminal display or forge log lines

2.5 WHEN `UnsafeZipMemberError` is raised THEN the system SHALL stop the run, SHALL NOT skip the member and continue, and SHALL NOT extract any further member

2.6 WHEN `UnsafeZipMemberError` is raised for the CodeCommit provider THEN the system SHALL delete the CodeCommit repository through `_delete_codecommit_repository()` exactly once and exit with status 1

2.7 WHEN `UnsafeZipMemberError` is raised for the GitHub provider THEN the system SHALL exit with status 1 and SHALL leave the cleanup decision to `create_and_seed_repository` (the "Delete repository? (y/N)" prompt with default `N`, or automatic deletion with `--cleanup-on-failure`), without a second prompt

2.8 WHEN `UnsafeZipMemberError` is raised THEN the system SHALL remove the temporary directory through the existing `_download_and_extract` cleanup, and the exit status SHALL be 1

2.9 WHEN a member's path, after prefix stripping, stays inside the extraction directory THEN the system SHALL accept it, including a name such as `a/../b.txt` that normalizes to a path inside (containment is the only rule, PLAN.md D1)

2.10 WHEN the check runs THEN it SHALL work for the Windows path forms that are non-relative on the right side of a join (`C:/x`, `D:x`, `\\host\share\x`) as well as POSIX absolute and `..` forms, because it resolves the path rather than matching strings

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a zip contains only members that stay inside the extraction directory THEN the system SHALL CONTINUE TO extract them exactly as before: same files, same bytes (`write_bytes`, no decoding), same directory entries

3.2 WHEN a GitHub zip has one common top-level directory THEN the system SHALL CONTINUE TO strip that prefix and skip the root directory entry itself; and WHEN every member of a GitHub zip starts with `../` THEN the system SHALL CONTINUE TO treat `../` as the common prefix and extract the members inside the extraction directory

3.3 WHEN extraction runs THEN the system SHALL CONTINUE TO remove an existing file inside the extraction directory before writing, create parent directories, remove the downloaded zip, and print and log the extracted file count

3.4 WHEN a zip member carries symlink mode bits THEN the system SHALL CONTINUE TO write it as a regular file containing the member's bytes, and SHALL NOT create a symlink

3.5 WHEN extraction fails for a reason other than an unsafe member (an invalid zip, a download error) THEN the system SHALL CONTINUE TO print the generic "Error in download and extract process. Check logs for more information." message, log the error, delete the CodeCommit repository for the CodeCommit provider, and exit with status 1

3.6 WHEN the S3 or GitHub download fails THEN the system SHALL CONTINUE TO behave as specified by the locked `issue-creating-github-repository-error-getting` and tempdir-cleanup work, with the same messages, cleanup handler calls, and exit codes

3.7 WHEN `create_and_seed_repository` runs THEN the order SHALL CONTINUE TO be: create the repository, create the branch structure, download and extract, seed (PLAN.md Decision 2)

3.8 WHEN `create_repo.py` is invoked THEN the system SHALL CONTINUE TO accept the same command-line options with the same behavior, and SHALL NOT add a flag

3.9 WHEN a repository is seeded successfully THEN the system SHALL CONTINUE TO seed the same files, merge `dev` into `test` as specified in the v0.0.18 auto-merge feature, and clean up temporary directories as before

3.10 WHEN `cli/update.py` runs THEN it SHALL CONTINUE TO behave exactly as before (PLAN.md Decision 3 and D2)

---

## Testing Requirements

4.1 Tests SHALL run on Linux under the existing pytest and Hypothesis setup (`cli/requirements-test.txt`) and SHALL NOT require Windows, AWS, GitHub, or network access. Zips SHALL be built inside the tests and no zip fixture SHALL be committed.

4.2 New tests SHALL live in `tests/test_create_repo_zip_safety.py`, follow the style of `tests/test_create_repo_tempdir_cleanup.py` (build a `RepositoryCreator` without `__init__`, stub the download, call `_download_and_extract_into` or `_download_and_extract`), and place the extraction directory under a test-owned parent so that "outside" is a directory the test controls

4.3 Tests SHALL cover the S3 branch and the GitHub branch (with the stripped prefix and without it) for each of: a `..` file member, an absolute file member, a `..` directory member, and a member that is unsafe only after prefix stripping (requirements 2.1 to 2.3, 1.1 to 1.4)

4.4 For every rejected case a test SHALL assert that a sentinel file placed outside the extraction directory is unchanged, that no new file or directory appears outside it, that `UnsafeZipMemberError` is raised by the check and the run exits with status 1 through `_download_and_extract`, and that the temporary directory no longer exists (requirements 2.3, 2.5, 2.8, 1.5)

4.5 A test SHALL assert that for the CodeCommit provider `_delete_codecommit_repository` is called exactly once, and a test SHALL assert that for the GitHub provider the extraction step does not call the cleanup handler itself (the outer handler runs it once, as in `tests/test_create_repo_download_failure_cleanup.py`) (requirements 2.6 and 2.7)

4.6 A test SHALL assert that the printed error and the log line contain the escaped member name (`repr()` form, length capped) and contain no raw control character or escape sequence from the name, using a member name that contains a newline and an ANSI escape (requirement 2.4)

4.7 A test SHALL assert that an unsafe member listed after safe members stops extraction and that no later member is written (requirement 2.5)

4.8 Tests SHALL cover the unchanged cases: nested directories, `a/../b.txt` staying inside, a GitHub zip whose members all start with `../` (extracted inside), a symlink-mode member written as a regular file, and byte-identical output for a CRLF member and a binary member (requirements 2.9, 3.1, 3.2, 3.4)

4.9 A test SHALL cover the generic failure path with an invalid zip and assert it still prints the generic message, deletes the CodeCommit repository, and exits 1 (requirement 3.5)

4.10 Windows path forms SHALL be tested at the pure-path level: the check's decision logic is exercised with `PureWindowsPath` inputs for `C:/x`, `D:x`, `\\host\share\x`, and `..\x`, without requiring Windows (requirement 2.10). If the helper cannot take a `PureWindowsPath` base, the test SHALL state the limit and rely on R2 (Verification Requirements)

4.11 A property-based test SHALL generate member names (from a mix of ordinary segments, `..`, `.`, empty segments, leading `/`, and separators), extract in a test-owned directory, and assert that either every written path is inside the extraction directory or the run raised `UnsafeZipMemberError`, and that nothing outside the extraction directory changed (requirements 2.1 and 2.3)

4.12 Existing tests in `tests/` and `cli/lib/test_*.py` SHALL continue to pass (137 `tests/test_create_repo_*.py` tests pass at `74f0688`)

---

## Version and Documentation Requirements

5.1 `cli/create_repo.py` SHALL have its `VERSION` marker reviewed per `.kiro/steering/ascs-cli-script-versioning.md`. It is `v0.2.5/2026-11-14`. If the embedded date differs from the implementation date, the PATCH number SHALL be incremented and the date set to the implementation date (hardening, no interface change). If the date already matches, the marker SHALL stay unchanged.

5.2 `CHANGELOG.md` SHALL gain an entry under `### Security` in `v0.0.21 (unreleased)` for `create_repo.py` that links this spec, addresses [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12), and states that zip members that resolve outside the extraction directory are now rejected. The entry SHALL state that a rejected zip exits with status 1, that the repository is created before the zip is checked, and that on GitHub the existing cleanup prompt or `--cleanup-on-failure` applies. The entry version SHALL match the `VERSION` marker. Existing changelog text SHALL NOT be edited, and the entry SHALL NOT include exploit steps.

5.3 `docs/SCRIPT-GUIDE.md`, in the `create_repo.py` section, SHALL gain a short note that a source zip containing a path that resolves outside the extraction directory is rejected, the run exits with status 1, a CodeCommit repository is deleted, and a GitHub repository is kept unless the prompt is answered `y` or `--cleanup-on-failure` is given

5.4 New and changed Python code SHALL carry Google-style docstrings with Args, Returns, Raises, and Example per `.kiro/steering/documentation-standards-python.md`: `UnsafeZipMemberError`, the check helper, and the updated `_download_and_extract_into`. Names SHALL follow `naming-conventions-python` (`UnsafeZipMemberError`, `_resolve_member_path`).

5.5 The helper and exception SHALL live in `cli/create_repo.py`, not in `cli/lib/` (PLAN.md D2). `README.md` and `AGENTS-FOR-END-USE.md` SHALL NOT change.

---

## Verification Requirements

6.1 Before release, the maintainer SHALL download the four public Atlantis app-starter zips (`atlantis-TEST::list_starters` lists them) and run them through the new check, and SHALL confirm that none is rejected (PLAN.md Section 8, false-rejection risk)

6.2 Before release, the maintainer SHALL run one rejected-zip run on Windows Git Bash (R2): upload a zip with a harmless `..\outside-test.txt` member to a test S3 location, run `create_repo.py --source s3://...` from a scratch directory with a throwaway CodeCommit repository name, and confirm exit status 1, the specific error message, the repository deleted, and no file outside the extraction directory

6.3 The maintainer SHALL delete any throwaway repository and test S3 object after verification. The implementing agent SHALL NOT create or delete repositories or upload objects without the maintainer's go-ahead.

---

## Out of Scope

- Reordering `create_and_seed_repository` to download and validate the zip before creating the repository (PLAN.md Decision 5, to be filed as a separate issue)
- The prefix-match containment check in `cli/update.py` (PLAN.md Decision 3, to be filed as a separate issue)
- Limits on member count, per-member size, and total extracted size (PLAN.md Decision 4, to be filed as a separate issue)
- Storing `source.zip` outside the extraction directory, and the `source.zip` member name collision (PLAN.md Section 7, note only)
- Windows alternate data streams, reserved device names, trailing dots and spaces, and case-colliding member names (PLAN.md D5, note only)
- A skip-and-report mode for unsafe members, and any new command-line flag
- Changes to `README.md` or `AGENTS-FOR-END-USE.md`
- A Windows runner in CI
