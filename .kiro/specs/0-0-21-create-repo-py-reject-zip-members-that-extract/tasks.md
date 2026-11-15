# Implementation Plan

## Overview

Reject zip members that extract outside the temporary directory in `create_repo.py` ([issue #12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12)). The work adds `UnsafeZipMemberError`, `_escape_member_name`, and `_resolve_member_path` to `cli/create_repo.py`, routes the three `output_path` assignments in `_download_and_extract_into` through one check, and gives the existing failure handler a specific message for the new error. It also adds one test file, a note in `docs/SCRIPT-GUIDE.md`, and a `### Security` changelog entry. The design is in [design.md](design.md), the requirements in [requirements.md](requirements.md), and the decisions in [PLAN.md](PLAN.md).

**Reminder: write the exploration tests (task 2) BEFORE implementing the fix, and run them on the UNFIXED code first to confirm the failures.**

**Test conventions:**

- New tests go in `tests/test_create_repo_zip_safety.py`. Import as the existing tests do: `sys.path.insert(0, <repo>/cli)`, then `import create_repo` and `from create_repo import RepositoryCreator`.
- Build a `RepositoryCreator` with `RepositoryCreator.__new__(RepositoryCreator)`, following `_make_creator` in `tests/test_create_repo_tempdir_cleanup.py`. Copy the helpers you need (`_make_creator`, a `mocks` fixture that patches `Colorize.prompt`, `subprocess.run`, `Log`, `click.echo`, and `GitHubUtils`). Do not import them from the other test module.
- **Safety: tests run against the unfixed code, which writes outside the extraction directory.** Every test builds a sandbox under a test-owned temporary directory with the extraction directory five levels deep, for example `<sandbox>/a/b/c/d/work`, and patches `create_repo.tempfile.mkdtemp` to return that `work` path. Generated or hand-written names use at most four `..` segments, and absolute names are built from the sandbox path, never from a real path such as `/etc`. Sentinel files and the before/after snapshot live in the sandbox, outside `work`.
- Hypothesis tests use `tempfile.TemporaryDirectory()` inside the test body (not `tmp_path`) and `@settings(max_examples=100, deadline=None)`.
- Test data is generated inside the tests. No zip fixture is committed.
- Run tests with `source .ve/bin/activate && python -m pytest ...`. Baseline before any change: `python -m pytest tests cli/lib -q` reports 428 passed (checked 2026-11-14 at `74f0688`).
- Running tests rewrites `cli/cli/logs/script-create_repo.log`. Ignore that file when reviewing `git diff`.

## Tasks

- [x] 1. Confirm the starting state
  - Run `git status --short -- cli tests docs CHANGELOG.md` and confirm there are no uncommitted changes to `cli/`, `tests/`, `docs/`, or `CHANGELOG.md`. Uncommitted spec files and `docs/00-Set-Up-Local-Environment.md` belong to other work and are not touched.
  - Record the current `VERSION` of `cli/create_repo.py` (`v0.2.5/2026-11-14` at planning time) and today's date, for task 4.5
  - Run the baseline: `source .ve/bin/activate && python -m pytest tests cli/lib -q`. Record the pass count (428 at planning time).
  - No code is changed in this task
  - _Requirements: 4.12, 5.1_

- [x] 2. Write bug condition exploration tests
  - **Property 1: Bug Condition** - A member that resolves outside the extraction directory is rejected before anything is written outside it
  - **CRITICAL**: These tests MUST FAIL on unfixed code. Failure confirms the defects exist.
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior and validate the fix when they pass after implementation. They use only existing names (`_download_and_extract`, `_download_and_extract_into`, `SystemExit`, filesystem state), so they fail on assertions and not on import errors.
  - **GOAL**: Show on Linux that unsafe members are written outside the extraction directory today
  - [x] 2.1 Sandbox helpers (`tests/test_create_repo_zip_safety.py`, new file)
    - Create the file with a module docstring that has a `Feature: create-repo-py-reject-zip-members-that-extract` line and test classes grouped by concern
    - Helpers: `_make_creator(provider, source_type)`, a fixture or context manager that builds the deep sandbox and patches `create_repo.tempfile.mkdtemp` to return `work`, `_write_zip(path, members)` (members are `(name, bytes)` pairs, optional `ZipInfo` for directories and symlink mode), `_stub_download(creator, zip_path)` (S3: `s3_client.download_file.side_effect` copies the zip and `is_bucket_public` returns `False`; GitHub: patch `create_repo.GitHubUtils.download_zip_from_url` to copy the zip), and `_snapshot(sandbox, exclude)` (maps each path outside `work` to `(is_dir, bytes or None)`)
    - _Requirements: 4.1, 4.2_
  - [x] 2.2 Rejection tests (same file)
    - `TestRejectsEscapingMembers`, parameterized over source (`s3`, `github` with a shared top-level prefix, `github` without one) and member kind (`..` file, absolute file built from the sandbox path, `..` directory, a member that is unsafe only after prefix stripping such as `repo-main/../../x`)
    - Each case runs `creator._download_and_extract()` with the `mocks` fixture and asserts: `SystemExit` with code 1, the snapshot outside `work` unchanged (a sentinel at the target path keeps its original bytes), and `work` no longer exists
    - Add a case where a sentinel file exists at the escape target, to cover the `unlink()` replacement (requirement 1.5)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.8, 4.3, 4.4_
  - [x] 2.3 Failure-path, message, and ordering tests (same file)
    - `TestFailurePath`: CodeCommit provider calls `_delete_codecommit_repository` once (patch it with a mock). GitHub provider: the extraction step does not call `_handle_github_seeding_failure`, and a run through `create_and_seed_repository` (with `_create_repository`, `_create_dev_test_branches`, and `_handle_github_seeding_failure` mocked) calls the handler once and re-raises `SystemExit(1)`
    - `TestMessage`: a member name that contains `\n` and `\x1b[31m` is reported only in `repr()` form. Assert on the captured `click.echo` and `Log.error` arguments: they contain the text `\\n` and `\\x1b` (escaped), contain no raw `\x1b` and no raw newline from the name, and do not contain the generic "Error in download and extract process" text. Add a 1,000-character name and assert the message length is capped.
    - `TestStopsAtFirstUnsafeMember`: members `a.txt`, `../b.txt`, `c.txt` in that order. After the run nothing exists outside `work`, and `c.txt` was never extracted (`work` is removed, so assert through a patched `Path.write_bytes` call list that no write happened for `c.txt`)
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 4.5, 4.6, 4.7_
  - [x] 2.4 Property test (same file)
    - Strategy: 1 to 8 member names, each 1 to 5 segments joined with `/` from ordinary names (`a`, `dir`, `x.txt`), `..`, `.`, and the empty string, optionally with a leading `/` or the sandbox path as an absolute name, with `..` bounded to four per name. Names ending in `/` are directory members.
    - Property: after `_download_and_extract_into` (catching `SystemExit`), the snapshot outside `work` is unchanged, and the run either exited 1 or every written path is inside `work`
    - A second property for names with no `..`, no absolute form, and no empty segment: the run succeeds and the extracted tree equals the expected tree
    - _Requirements: 2.1, 2.3, 2.9, 4.11_
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_create_repo_zip_safety.py -v`
  - **EXPECTED OUTCOME**: the rejection, failure-path, message, ordering, and first property tests FAIL. The "safe names" property passes. If a rejection test does not fail, the hypothesis about that path is wrong: stop and revisit design.md.
  - Document the counterexamples in the task notes: for example `outside-test.txt` written in the parent of `work`, or the sentinel replaced, and the Hypothesis counterexample for the first property
  - Mark the task complete when the tests are written, run, and the failures are documented
  - _Requirements: 1.1 to 1.6, 2.1 to 2.8, 4.3 to 4.7, 4.11_

- [x] 3. Write preservation tests (BEFORE implementing the fix)
  - **Property 3 and 4: Preservation** - Safe archives extract as before, and other failures and flow are unchanged
  - **IMPORTANT**: Follow observation-first methodology. Observe the current behavior on UNFIXED code, then encode it. These tests must pass before and after the fix.
  - Add the tests to `tests/test_create_repo_zip_safety.py` in their own classes:
    - `TestSafeArchivesUnchanged`: nested directories, a directory entry, `a/../b.txt` (extracted as `b.txt`), an existing file inside `work` replaced, a GitHub zip with a shared top-level directory (prefix stripped, root entry skipped), a GitHub zip whose members all start with `../` (members land inside `work`), a symlink-mode member (`ZipInfo.external_attr = 0o120000 << 16`) written as a regular file with the member's bytes, a CRLF member and a non-UTF-8 member byte-identical. For S3 and GitHub, compare the extracted tree with the expected tree built in the test. Also assert `source.zip` is removed and the "Extracted files" count is echoed.
    - `TestOtherFailuresUnchanged`: an invalid zip, an S3 `403` from `download_file`, and an `AccessDenied` still print the generic "Error in download and extract process" message where the existing code prints it, delete the CodeCommit repository for the CodeCommit provider, and exit 1. Check the same outcomes the existing tests in `tests/test_create_repo_tempdir_cleanup.py` check, so a regression in the handler's generic branch is caught here too.
    - `TestFlowUnchanged`: `create_and_seed_repository` still calls `_create_repository`, then `_create_dev_test_branches`, then `_download_and_extract`, then `_seed_repository` in that order (mock all four and record the call order)
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_create_repo_zip_safety.py -v -k "SafeArchives or OtherFailures or FlowUnchanged"`
  - **EXPECTED OUTCOME**: Tests PASS (confirms the baseline to preserve)
  - Mark the task complete when the tests are written, run, and passing on unfixed code
  - _Requirements: 2.9, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.8, 4.9_

- [x] 4. Fix extraction in `cli/create_repo.py`
  - [x] 4.1 Add the exception and the two helpers
    - Add `UnsafeZipMemberError(ValueError)` at module level after the imports and before `RepositoryCreator`, with a Google-style docstring (description, example)
    - Add static `RepositoryCreator._escape_member_name(name, max_length=200)` (`repr()` of the name, capped with a trailing `...`) and static `RepositoryCreator._resolve_member_path(base_dir, relative_name, member_name=None)` exactly as in design.md Changes 2 and 3: resolve both paths, require `target.is_relative_to(base)`, raise `UnsafeZipMemberError` with the escaped name, and return the resolved target. Place them next to `_remove_temp_dir`.
    - Docstrings per `.kiro/steering/documentation-standards-python.md`: description, Args, Returns, Raises, Example
    - Names follow `.kiro/steering/naming-conventions-python.md`
    - _Requirements: 2.1, 2.3, 2.4, 2.9, 2.10, 5.4, 5.5_
  - [x] 4.2 Route the loop through the check
    - In `_download_and_extract_into`, replace the three `output_path = Path(temp_dir) / ...` assignments with one `relative_name` (initially `zip_info.filename`, replaced by the prefix-stripped name for GitHub members that start with `common_prefix`) and one call `output_path = self._resolve_member_path(temp_dir, relative_name, zip_info.filename)`
    - Leave the prefix detection pass, the root-entry skip, directory handling, `parent.mkdir`, the `unlink`, and `write_bytes` as they are. The directory-member `mkdir` and every later step now use the returned resolved path.
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 3.3_
  - [x] 4.3 Specific message in the failure handler
    - In the `except Exception as e` block at the end of `_download_and_extract_into`, when `isinstance(e, UnsafeZipMemberError)`, echo `Colorize.error(f"Unsafe source zip: {e}. Nothing was seeded.")` and log `Log.error(f"Unsafe source zip rejected: {e}")`. Otherwise keep the generic message and log line unchanged. Keep the CodeCommit deletion, the comments about GitHub cleanup and the temp dir, and `sys.exit(1)` as they are, shared by both branches.
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 2.8, 3.5, 3.6_
  - [x] 4.4 Helper unit tests (`tests/test_create_repo_zip_safety.py`)
    - `TestResolveMemberPath` with a real directory: `ok.txt`, `a/b/c.txt`, `a/../b.txt` (returns `<base>/b.txt`), `.` and the empty name (resolve to the base, accepted), `../x`, `a/../../x`, an absolute path built from the test directory, and a name that resolves to `<base>-evil/x` (rejected). Assert the returned path is the resolved path and the error text contains the escaped name and "outside the extraction directory".
    - `TestEscapeMemberName`: ordinary name, `\n`, `\x1b`, a bidirectional override (`\u202e`, escaped by `repr()`), and a name longer than the cap (ends with `...`, length at most the cap)
    - `TestWindowsPathFormsCharacterization`: with `PureWindowsPath('C:/tmp/work')`, joining `C:/x`, `D:x`, and `\\host\share\x` gives a path that is not relative to the base. The docstring states that it documents the stdlib rule the helper relies on and does not run the helper, which resolves against the real filesystem, and that R2 verifies the helper on Windows (requirement 4.10).
    - _Requirements: 2.1, 2.3, 2.4, 2.9, 2.10, 4.10_
  - [x] 4.5 Version marker
    - Compare the `VERSION` date of `cli/create_repo.py` with today's date per `.kiro/steering/ascs-cli-script-versioning.md`. If it differs, increment PATCH and set the date (`v0.2.6/<date>` from `v0.2.5`). If it matches, leave it unchanged. Hardening, no interface change.
    - Record the final value for the changelog entry (task 7)
    - _Requirements: 5.1_
  - [x] 4.6 Verify the exploration tests now pass
    - **Property 1: Expected Behavior** - Unsafe members are rejected before anything is written outside the extraction directory
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests for this step.
    - Run: `source .ve/bin/activate && python -m pytest tests/test_create_repo_zip_safety.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed)
  - [x] 4.7 Verify the preservation tests still pass
    - **Property 3 and 4: Preservation** - No regressions
    - **IMPORTANT**: Re-run the SAME tests from task 3. Do NOT write new tests for this step.
    - Run: `source .ve/bin/activate && python -m pytest tests/test_create_repo_zip_safety.py tests/test_create_repo_tempdir_cleanup.py tests/test_create_repo_download_failure_cleanup.py tests/test_create_repo_byte_fidelity.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (no regressions)

- [x] 5. Checkpoint - Ensure all tests pass
  - Run the new suite: `source .ve/bin/activate && python -m pytest tests/test_create_repo_zip_safety.py -v`
  - Run the full suite: `source .ve/bin/activate && python -m pytest tests cli/lib -q` and compare the pass count with the baseline from task 1 (the count increases by the number of new tests, and nothing fails)
  - Confirm `git diff --stat` shows changes only in `cli/create_repo.py`, the new test file, `docs/SCRIPT-GUIDE.md` (after task 6), `CHANGELOG.md` (after task 7), plus the spec directory. Ignore `cli/cli/logs/script-create_repo.log`.
  - Confirm nothing under `cli/lib/`, `cli/update.py`, `README.md`, or `AGENTS-FOR-END-USE.md` changed
  - Check that no test left files outside its sandbox (`git status --short` shows no stray files in the repository, and nothing new in the system temp directory from these tests beyond pytest's own directories)
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: 3.8, 3.10, 4.12, 5.5_

- [x] 6. Update `docs/SCRIPT-GUIDE.md`
  - In the `create_repo.py` section, after the usage block, add a short paragraph: a source zip that contains a path resolving outside the extraction directory is rejected; the run exits with status 1; a CodeCommit repository created for the run is deleted; a GitHub repository is kept unless the prompt "Delete repository? (y/N)" is answered `y` or `--cleanup-on-failure` is given. Confirm the flag name against `./cli/create_repo.py -h` before writing it.
  - Follow `.kiro/steering/documentation-standards-markdown.md` (sentence-case text, code blocks with a language, relative links) and keep user documentation free of implementation detail
  - _Requirements: 5.3_

- [x] 7. Update CHANGELOG.md
  - Add a `### Security` section under the existing `## v0.0.21 (unreleased)` header, after the existing `### Fixed` section and before `## v0.0.20`. Do not modify existing text.
  - Entry: `- **Script: create_repo.py vX.Y.Z** - Rejected zip members that resolve outside the extraction directory [Spec: 0-0-21-create-repo-py-reject-zip-members-that-extract](.kiro/specs/0-0-21-create-repo-py-reject-zip-members-that-extract/), addresses [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12)`, with the version from task 4.5
  - Sub-bullets: names containing `..` segments or absolute paths now stop the run with a clear error and exit status 1 instead of being written outside the temporary directory; the repository is created before the zip is checked, so a CodeCommit repository is deleted and, for GitHub, the existing cleanup prompt or `--cleanup-on-failure` applies; archives whose members stay inside the directory are unaffected. No exploit steps.
  - Follow `.kiro/steering/changelog-convention.md` and the format of the neighboring `v0.0.21` entries
  - _Requirements: 5.2_

- [-] 8. Release verification, spin-offs, and issue housekeeping (maintainer task)
  - **The agent does not create or delete repositories, upload objects, or file issues without the maintainer's go-ahead.**
  - **Starter zips (requirement 6.1):** the four public starter zips download anonymously and need no AWS credentials. With the maintainer's go-ahead, the agent downloads them into a scratch directory and runs each through `_resolve_member_path` (a throwaway script, not committed), and confirms none is rejected. Otherwise the maintainer runs it.
  - **R2 (Windows Git Bash, `.ve` venv):** upload a zip with a harmless `..\outside-test.txt` member to a test S3 location, then run `./cli/create_repo.py <throwaway-name> --source s3://<bucket>/<key>.zip` from a scratch directory. Confirm exit status 1, the specific "Unsafe source zip" message, the CodeCommit repository deleted, and no `outside-test.txt` outside the extraction directory. Delete the throwaway S3 object afterward.
  - **Spin-offs (PLAN.md Decisions 3, 4, and 5):** ask the maintainer whether to file them now. If yes, check `gh issue list --state all` for duplicates, then file each with `gh issue create -R 63Klabs/atlantis-sam-config-scripts`, label `enhancement` only (never `approved for development`), in the ISSUE.md section shape, describing the findings as low-risk with no exploit detail: (1) `update.py` containment check uses `startswith` without a separator, (2) limits on zip member count and size during extraction, (3) download and validate the zip before creating the repository. Record the issue URLs as a decision in PLAN.md and link them in the requirements "Out of Scope" list.
  - **Housekeeping:** after the fix ships, close issue #12 with a reference to this spec
  - Record the outcome of the verification runs
  - _Requirements: 6.1, 6.2, 6.3_
