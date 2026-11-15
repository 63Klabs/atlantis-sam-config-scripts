# Implementation Plan

## Overview

Fix binary and non-UTF-8 files being seeded as base64 text ([issue #11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11)), and the GitHub text-mode write defects folded into this spec ([issue #10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10)). File content stays `bytes` from extraction through both providers. Extraction writes bytes, `create_init_commit` always writes `'wb'` and clones with `core.autocrlf=false`, and `create_branch_structure` writes its README as UTF-8 without newline translation. Requirements are in [requirements.md](requirements.md), the design is in [design.md](design.md), and the decisions are in [PLAN.md](PLAN.md).

**Reminder: write the exploration tests (task 2) BEFORE implementing the fix, and run them on the UNFIXED code first to confirm the failures.**

**Test conventions:**

- Import modules as the existing tests do: `sys.path.insert(0, <repo>/cli)`, then `import create_repo` and `from lib.gh_utils import GitHubUtils`. Patch `subprocess.run` and `Log` through `lib.gh_utils` (`patch('lib.gh_utils.subprocess.run')`, `patch('lib.gh_utils.Log')`).
- Build a `RepositoryCreator` with `RepositoryCreator.__new__(RepositoryCreator)`, following `tests/test_create_repo_seed_paths.py` and `tests/test_create_repo_download_failure_cleanup.py`. Patch `create_repo.Log` and `create_repo.click.echo` in extraction tests.
- Hypothesis tests that write files use `tempfile.TemporaryDirectory()` inside the test body, not `tmp_path`, and `@settings(max_examples=200)` (fewer for tests that build zips).
- Test data is generated inside the tests. No binary fixture is committed (PLAN.md D2).
- Run tests with `source .ve/bin/activate && python -m pytest ...`. Baseline before any change: `python -m pytest tests cli/lib -q` reports 403 passed.
- Running tests rewrites `cli/cli/logs/script-create_repo.log`. Ignore that file when reviewing `git diff`.

## Tasks

- [x] 1. Confirm the starting state
  - Run `git status --short` and confirm which files carry uncommitted changes. `cli/create_repo.py` and `cli/lib/gh_utils.py` currently hold uncommitted edits from the `0-0-21-issue-creating-github-repository-error-getting` spec.
  - **Ask the maintainer** to commit those edits, or to confirm that this work may build on top of them, before changing either file (requirement 5.6)
  - Record the current `VERSION` markers of `cli/create_repo.py` and `cli/lib/gh_utils.py` and today's date, for task 4.6
  - Run the baseline: `source .ve/bin/activate && python -m pytest tests cli/lib -q`. Record the pass count.
  - No code is changed in this task
  - _Requirements: 4.10, 5.6_

- [x] 2. Write bug condition exploration tests
  - **Property 1: Bug Condition** - File content reaches both providers as the file's bytes, and the Windows write paths do not alter bytes
  - **CRITICAL**: These tests MUST FAIL on unfixed code. Failure confirms the defects exist.
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior. They validate the fix when they pass after implementation.
  - **GOAL**: Show, on Linux, each defect that cannot be reproduced end to end without Windows
  - [x] 2.1 Collection and CodeCommit tests (`tests/test_create_repo_byte_fidelity.py`, new file)
    - Create the file with a module docstring that has a `Feature: binary-and-non-utf-8-files-are-seeded-as-base64` line and test classes grouped by concern
    - Test: `_seed_collect_files` on a temporary tree holding a PNG-like file (`b'\x89PNG\r\n\x1a\n\x00\xff\xfe'`) returns `fileContent` that is a `bytes` object equal to the file bytes
    - Test: the same for Latin-1 text (`'caf\u00e9'.encode('latin-1')`)
    - Test: `_seed_repository_codecommit` with a mocked `codecommit_client` (`get_branch` returns `{'branch': {'commitId': 'c0'}}`, `create_commit` returns `{'commitId': 'c1'}`, and `get_init_commit_author` and `get_init_commit_email` are mocked, as in `_make_creator` in `tests/test_create_repo_download_failure_cleanup.py`; the method removes the temporary directory when it finishes) passes `putFiles` entries whose `fileContent` is `bytes` equal to the file bytes
    - _Requirements: 1.1, 1.2, 2.1, 2.3, 4.4, 4.7_
  - [x] 2.2 Extraction test (same file)
    - Build a zip in `tmp_path` with a CRLF `.gitignore` (`b'a\r\nb\r\n'`), a Latin-1 `notes.txt`, and a PNG-like `logo.png`
    - Run `_download_and_extract_into` with the S3 source (`source_type='s3'`, `s3_client.download_file.side_effect` copies the zip to the requested path, `is_bucket_public` returns `False`) and again with the GitHub common-prefix branch (`source_type='github'`, `GitHubUtils.download_zip_from_url` patched to write a zip whose members share one top-level directory)
    - Patch `pathlib.Path.write_text` to raise `AssertionError('write_text must not be used')` for the duration of each run
    - Assert the extracted files equal the zip members byte for byte
    - Add a comment documenting the root cause: on Windows `write_text` translates `\n` to `\r\n`, so `b'a\r\nb\r\n'` becomes `b'a\r\r\nb\r\r\n'` (reproduced with `open(..., newline='\r\n')`)
    - _Requirements: 1.5, 2.7, 2.9, 4.8_
  - [x] 2.3 `GitHubUtils` tests (`tests/test_gh_utils_byte_fidelity.py`, new file)
    - Test: with `subprocess.run` patched (returns a `MagicMock`) and a real `git_dir` under `tmp_path`, `create_init_commit` called with a `bytes` entry containing `\r\n` and `0xFF`, and a non-ASCII `str` entry, writes bytes equal to the input and the UTF-8 encoding of the `str` (requirement 4.5). Expect this test to PASS on unfixed code on Linux, because the `'wb'` branch exists for `bytes` and the default encoding is UTF-8. Record that result.
    - Test: the recorded `subprocess.run` calls include `["gh", "repo", "clone", repo_name, git_dir, "--", "-c", "core.autocrlf=false"]` and no call starts with `["git", "config", "core.autocrlf"` (requirement 4.6). Expect FAIL.
    - Test: `create_branch_structure` with `tempfile.mkdtemp` patched to a directory under `tmp_path`, `monkeypatch.chdir(tmp_path)` applied first, and `subprocess.run` patched with a side effect that reads `README.md` when it sees the `git add README.md` call. Assert the captured bytes equal `readme_content.encode('utf-8')` and contain no `\r`. Also wrap `builtins.open` with a recorder that delegates to the real `open`, and assert the README was opened with `encoding='utf-8'` and `newline=''` (requirement 4.11). Expect the `open` argument assertion to FAIL on unfixed code.
    - _Requirements: 1.3, 1.4, 1.6, 1.7, 2.4, 2.5, 2.6, 2.11, 4.5, 4.6, 4.11_
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_create_repo_byte_fidelity.py tests/test_gh_utils_byte_fidelity.py -v`
  - **EXPECTED OUTCOME**: collection, CodeCommit, extraction, clone-argument, and README-`open` tests FAIL. The `create_init_commit` byte-write test passes.
  - Document the counterexamples in the task notes: for example `fileContent == 'iVBORw0KGgoA//4='` (a `str`) for the PNG-like bytes, and `AssertionError: write_text must not be used` during extraction
  - Mark the task complete when the tests are written, run, and the failures are documented

- [x] 3. Write preservation tests (BEFORE implementing the fix)
  - **Property 4: Preservation** - Valid UTF-8 text is stored with the same bytes as before, and unrelated behavior is unchanged
  - **IMPORTANT**: Follow observation-first methodology. Observe current behavior on UNFIXED code, then encode it.
  - Add the tests to the two new files, in their own classes (for example `TestSeedCollectFilesPreservation`, `TestExtractionPreservation`, `TestCreateInitCommitPreservation`), written so that they pass both before and after the fix:
    - Valid UTF-8 text: a helper `as_bytes(value)` returns `value` for `bytes` and `value.encode('utf-8')` for `str`. Assert `as_bytes(entry['fileContent']) == file_bytes` for valid UTF-8 text, including non-ASCII characters (requirement 3.1). This passes on the unfixed `str` and on the fixed `bytes`.
    - Property test (Hypothesis, `st.text()`): for any text written as UTF-8, `as_bytes(collected fileContent) == text.encode('utf-8')` (Property 4)
    - `filePath` normalization and `fileMode == 'NORMAL'` for nested files (requirements 2.10, 3.2). The existing path tests in `tests/test_create_repo_seed_paths.py` already cover this and stay unchanged.
    - Read failure: with `open` patched to raise for one file, `_seed_collect_files` prints the error, deletes the CodeCommit repository for the CodeCommit provider, and exits 1 (requirement 3.3)
    - Extraction layout: directory entries are created, an existing file is replaced, the GitHub common prefix is stripped, the zip file is removed, and the "Extracted files" count is echoed (requirement 3.7)
    - `create_init_commit` git sequence: with `subprocess.run` patched, the calls after the clone are `git config user.name`, `git config user.email`, `git checkout <branch>`, `git add .`, `git commit -m "Seeding repository with N files"`, `git push origin <branch>`, in that order (requirement 3.6). Do not assert the exact clone argv here.
    - `create_branch_structure` sequence: clone, `user.name`, `user.email`, `checkout -B main`, `add README.md`, commit, push `main`, then `test` and `dev` branches pushed (requirement 3.11), with the clone command equal to `["gh", "repo", "clone", repo_name, temp_dir]`
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_create_repo_byte_fidelity.py tests/test_gh_utils_byte_fidelity.py -v -k Preservation`
  - **EXPECTED OUTCOME**: Tests PASS (confirms the baseline to preserve)
  - Mark the task complete when the tests are written, run, and passing on unfixed code
  - _Requirements: 2.10, 3.1, 3.2, 3.3, 3.6, 3.7, 3.11, 4.3_

- [x] 4. Fix byte handling in `cli/create_repo.py` and `cli/lib/gh_utils.py`
  - [x] 4.1 `_seed_collect_files` returns bytes
    - In `cli/create_repo.py`, read each file with `open(full_path, 'rb')` and store the bytes as `fileContent`. Remove the UTF-8 decode, the `UnicodeDecodeError` fallback, and the base64 encoding.
    - Remove `import base64` from the top of the module after confirming with a search that nothing else uses it
    - Keep `_to_codecommit_path`, `fileMode: 'NORMAL'`, and the `except` block (error message, CodeCommit cleanup, `sys.exit(1)`) unchanged
    - Replace the one-line docstring with a Google-style docstring (Description, Args, Returns, Example) that states `fileContent` is `bytes`, following `.kiro/steering/documentation-standards-python.md`
    - _Requirements: 2.1, 2.2, 2.3, 2.10, 3.2, 3.3, 5.4_
  - [x] 4.2 Extraction writes bytes
    - In `_download_and_extract_into`, delete `text_extensions`, the `is_text_file` expression, and the decode/`write_text`/`UnicodeDecodeError` branches
    - Keep, inside the existing `with zip_ref.open(zip_info) as source:` block: `content = source.read()`, the `if output_path.exists(): output_path.unlink()` step, and `output_path.write_bytes(content)`
    - Do not change the directory-entry branch, `output_path.parent.mkdir`, the GitHub prefix handling, the file count, or the error handler
    - _Requirements: 2.7, 2.8, 2.9, 3.7_
  - [x] 4.3 Remove `_is_binary_string`
    - Delete the `RepositoryCreator._is_binary_string` method after confirming with a search of `cli/` and `tests/` that nothing else calls it
    - _Requirements: 2.8_
  - [x] 4.4 `create_init_commit` clones with autocrlf off and writes bytes
    - In `cli/lib/gh_utils.py`, change the clone command to `["gh", "repo", "clone", repo_name, git_dir, "--", "-c", "core.autocrlf=false"]`, with a short comment explaining why the setting is applied at clone time
    - Do not add a `git config core.autocrlf` call
    - In the write loop, encode a `str` `fileContent` as UTF-8, then open every file with `'wb'` and write the bytes. No `encoding` or `newline` argument remains.
    - Keep the `user.name`, `user.email`, `checkout`, `add`, `commit`, and `push` calls and the `CalledProcessError` handling unchanged
    - Update the docstring: `fileContent` may be `bytes` or `str`, and the clone is created with `core.autocrlf=false`
    - _Requirements: 2.4, 2.5, 2.6, 3.5, 3.6, 5.4_
  - [x] 4.5 README bootstrap write
    - In `create_branch_structure`, change `open(readme_path, 'w')` to `open(readme_path, 'w', encoding='utf-8', newline='')`
    - Do not change the clone command or any other call in the function
    - _Requirements: 2.11, 3.11_
  - [x] 4.6 Review the version markers
    - Per `.kiro/steering/ascs-cli-script-versioning.md`, compare each file's `VERSION` date with the implementation date (recorded in task 1). If it differs, increment PATCH and set the date. If it matches, leave the marker unchanged. Both files are bug fixes with no interface change.
    - Apply the rule to `cli/create_repo.py` and `cli/lib/gh_utils.py` independently
    - _Requirements: 5.1_
  - [x] 4.7 Update the tests that encode the old behavior
    - In `tests/test_create_repo_seed_paths.py`, update `test_utf8_file_content_is_text_and_mode_is_normal` to assert `fileContent == text.encode('utf-8')`, a `bytes` instance, and `fileMode == 'NORMAL'`
    - Update `test_non_utf8_file_content_is_base64_text_and_mode_is_normal` to assert `fileContent == raw` and rename it to match (for example `test_non_utf8_file_content_is_raw_bytes_and_mode_is_normal`)
    - Remove the now unused `import base64` from that file
    - Add a short comment that these tests supersede requirement 3.4 of the `git-for-windows-bug-in-file-seeding` spec for `fileContent`
    - _Requirements: 4.2_
  - [x] 4.8 Add the remaining unit and property tests
    - In `tests/test_create_repo_byte_fidelity.py` and `tests/test_gh_utils_byte_fidelity.py`, add the tests from requirement 4 that were not written in task 2:
      - Collection unit tests for valid UTF-8 text, a UTF-8 byte order mark, and an empty file (requirement 4.4)
      - Property 1 (Hypothesis, `st.binary()`): `_seed_collect_files` returns `fileContent == data` as `bytes` (requirement 4.3)
      - Property 2 (Hypothesis, `st.lists(st.one_of(st.binary(), st.text()))`): `create_init_commit` writes the bytes or the UTF-8 encoding of the `str` for each entry
      - Property 3 (Hypothesis, `st.binary()`, small `max_examples`): a one-member zip extracts to the same bytes through `_download_and_extract_into`
      - A test that `create_repo` has no `base64` attribute and `RepositoryCreator` has no `_is_binary_string` (requirement 4.9)
    - Include `# Feature: binary-and-non-utf-8-files-are-seeded-as-base64, Property N: ...` and `# Validates: Requirements ...` comments, matching `tests/test_create_repo_seed_paths.py`
    - Check the changed docstrings: run `doctest.run_docstring_examples(create_repo.RepositoryCreator._seed_collect_files, vars(create_repo))` from a throwaway Python command and confirm it prints no failures. Skip any example that needs a live instance and keep the example runnable or clearly illustrative.
    - _Requirements: 4.3, 4.4, 4.9, 5.4_
  - [x] 4.9 Verify the exploration tests now pass
    - **Property 1: Expected Behavior** - File content reaches both providers as the file's bytes
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests for this step.
    - Run: `source .ve/bin/activate && python -m pytest tests/test_create_repo_byte_fidelity.py tests/test_gh_utils_byte_fidelity.py -v`
    - **EXPECTED OUTCOME**: The task 2 tests PASS
    - Mutation checks, one at a time, restoring the change after each and confirming the matching test fails:
      - restore `write_text` for text members in extraction (2.2 test fails)
      - remove `"--", "-c", "core.autocrlf=false"` from the clone command (clone-argument test fails)
      - remove `encoding='utf-8', newline=''` from the README `open` (README `open` assertion fails)
      - re-add the base64 fallback in `_seed_collect_files` (collection and CodeCommit tests fail)
    - _Requirements: 2.1 to 2.11, 4.3 to 4.9_
  - [x] 4.10 Verify the preservation tests still pass
    - **Property 4: Preservation** - Valid UTF-8 text is stored with the same bytes as before
    - **IMPORTANT**: Re-run the SAME tests from task 3. Do NOT write new tests for this step.
    - Run: `source .ve/bin/activate && python -m pytest tests/test_create_repo_byte_fidelity.py tests/test_gh_utils_byte_fidelity.py tests/test_create_repo_seed_paths.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (no regressions)

- [x] 5. Checkpoint - Ensure all tests pass
  - Run the new suites: `source .ve/bin/activate && python -m pytest tests/test_create_repo_byte_fidelity.py tests/test_gh_utils_byte_fidelity.py tests/test_create_repo_seed_paths.py -v`
  - Run the full suite: `source .ve/bin/activate && python -m pytest tests cli/lib -q` and compare the pass count with the baseline from task 1 (the count increases by the number of new tests, and nothing fails)
  - Confirm `cli/lib/test_gh_utils_stderr_logging.py` and the tests that mock `create_init_commit` and `_seed_collect_files` still pass
  - Confirm `git diff --stat` shows changes only in `cli/create_repo.py`, `cli/lib/gh_utils.py`, `tests/test_create_repo_seed_paths.py`, the two new test files, and `CHANGELOG.md` (after task 6), plus the spec directory. Ignore `cli/cli/logs/script-create_repo.log`.
  - Search `README.md`, `docs/`, and `AGENTS-FOR-END-USE.md` once more for `base64`, `binary`, and `line ending` to confirm no documentation describes the old behavior (requirement 5.5)
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: 4.1, 4.10, 5.5_

- [x] 6. Update CHANGELOG.md
  - Add `### Fixed` entries under the existing `## v0.0.21 (unreleased)` header for `create_repo.py` and for `lib/gh_utils.py`, next to the entries already present. Do not modify existing text.
  - Use the entries drafted in design.md (Change 6), with the version numbers from the `VERSION` markers as set in task 4.6
  - Link this spec and [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11), and link [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10) in the `gh_utils.py` entry
  - Include the sub-bullet stating that repositories already seeded from a starter with binary or non-UTF-8 files are not repaired and must be deleted and recreated, or have those files re-committed
  - Follow `.kiro/steering/changelog-convention.md` and the format of the neighboring `v0.0.21` entries
  - _Requirements: 5.2, 5.3_

- [x] 7. Release verification and issue housekeeping (maintainer task)
  - **This task needs AWS and GitHub credentials and a Windows machine, and it creates real repositories. The agent does not run it. Ask the maintainer to do it, and record the result.**
  - **R1 (Linux or macOS):** build a zip with a small PNG, a Latin-1 text file, and a CRLF `.gitignore`, and host it at an S3 location the maintainer controls. Run `./cli/create_repo.py <throwaway-name> --source s3://<bucket>/<key>.zip` and the same with `--provider github`. For each repository, `git clone`, `git checkout dev`, `git checkout test`, and compare `sha256sum` of every file with the original.
  - **R2 (Windows Git Bash, `.ve` venv):** repeat both runs with `git config --global core.autocrlf true`. Confirm checksums match, no file contains `\r\r\n`, the bootstrap `README.md` on `main` has LF endings, and the seeding commit on `dev` does not change that README unless the starter supplies its own.
  - Delete every throwaway repository afterward
  - Record the outcome of both runs (PLAN.md Decision 4 requires them before release)
  - **Housekeeping:** after the fix ships, close issue #10 with a reference to this spec. The spec directory `0-0-21-github-seeding-writes-files-in-text-mode-without` is covered by this spec. The agent does not delete or edit it.
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
