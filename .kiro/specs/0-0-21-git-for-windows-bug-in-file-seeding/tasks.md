# Implementation Plan

## Overview

Fix the Windows path-separator bug in CodeCommit seeding ([issue #9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9)). `RepositoryCreator._seed_collect_files` in `cli/create_repo.py` stores `os.path.relpath(...)` as `filePath`, which contains `\` on Windows. The fix adds a module-level helper, `_to_codecommit_path`, and routes the relpath result through it. All new tests live in `tests/test_create_repo_seed_paths.py`. Requirements are in [requirements.md](requirements.md) and the design is in [design.md](design.md).

**Reminder: write the exploration test BEFORE implementing the fix, and run it on the UNFIXED code first to confirm the failure.**

**Test-file convention:** import the module as `import create_repo` (after the same `sys.path.insert` used in `tests/test_create_repo_merge.py`) and reach the helper as `create_repo._to_codecommit_path` inside the tests that need it. This keeps the file importable before the helper exists, so the exploration test fails on an assertion and not on an `ImportError`.

Run tests with `source .ve/bin/activate && python -m pytest ...`.

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Windows relative paths become `/`-separated
  - **CRITICAL**: This test MUST FAIL on unfixed code. Failure confirms the defect exists.
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior. It validates the fix when it passes after implementation.
  - **GOAL**: Show that `_seed_collect_files` returns `\`-separated `filePath` values when `os.path.relpath` returns the Windows form
  - Create `tests/test_create_repo_seed_paths.py` following the style of `tests/test_create_repo_merge.py` (module docstring with a `Feature:` line, `sys.path.insert` for `cli/`, test classes grouped by concern)
  - Build the instance with `RepositoryCreator.__new__(RepositoryCreator)` and set `codecommit_client = MagicMock()` (used only on the error path)
  - Create a nested tree under `tmp_path` (for example `README.md`, `.github/workflows/deploy-to-s3.yml`, `application-infrastructure/build-scripts/generate-put-ssm.py`)
  - Within a narrow `with mock.patch.object(create_repo.os.path, 'relpath', ...)` block, make `relpath` return the real result with `/` replaced by `\`, then call `_seed_collect_files(str(tmp_path))`
  - Assert every returned `filePath` contains no `\` and equals the expected `/`-separated path
  - Add a short comment documenting the root cause: `ntpath.relpath('C:\\t\\.github\\w\\d.yml', 'C:\\t')` returns `.github\w\d.yml`
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_create_repo_seed_paths.py -v`
  - **EXPECTED OUTCOME**: Test FAILS with `filePath == '.github\\workflows\\deploy-to-s3.yml'`
  - Document the counterexample in the task notes
  - Mark task complete when the test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2, 2.1, 2.4, 4.1, 4.8_

- [x] 2. Write preservation tests (BEFORE implementing fix)
  - **Property 2: Preservation** - POSIX output is unchanged, and output shape is correct
  - **IMPORTANT**: Follow observation-first methodology. Observe current behavior on UNFIXED code, then encode it.
  - Observe: on the Linux host, `_seed_collect_files` returns `filePath` values equal to `os.path.relpath(full_path, tmp_path)` for every file
  - Observe: a root-level file keeps its bare name as `filePath`
  - Observe: `fileContent` is UTF-8 text for text files, base64 text for non-UTF-8 content, and `fileMode` is `'NORMAL'`
  - Add tests to `tests/test_create_repo_seed_paths.py`:
    - Real-tree test: with nested directories and no patching, the set of `filePath` values equals the expected `/`-separated set (requirement 4.6)
    - Output shape: every `filePath` is relative (no leading `/`), has no `..` segment, and has no `\` (Property 3)
    - Root-level file unchanged (3.2)
    - `fileContent` and `fileMode` unchanged for a UTF-8 file and a non-UTF-8 file (3.4)
  - Put the preservation tests in their own class (for example `TestSeedCollectFilesPreservation`) and the exploration test in another (for example `TestSeedCollectFilesWindowsPaths`)
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_create_repo_seed_paths.py -v -k Preservation`
  - **EXPECTED OUTCOME**: Tests PASS (confirms the baseline to preserve)
  - Mark task complete when the tests are written, run, and passing on unfixed code
  - _Requirements: 2.6, 3.1, 3.2, 3.4, 4.6_

- [x] 3. Fix path separators in `cli/create_repo.py`

  - [x] 3.1 Add the `_to_codecommit_path` helper
    - Add a module-level function immediately after `should_merge_test` and before `class RepositoryCreator`
    - Signature: `_to_codecommit_path(relative_path: str, sep: Optional[str] = None, altsep: Optional[str] = None) -> str`
    - Behavior: `None` for `sep` or `altsep` means use `os.sep` or `os.altsep`. Replace each non-empty separator that is not already `/` with `/`. Return the input unchanged when no replacement applies.
    - Add a Google-style docstring with Description, Args, Returns, and a doctest-valid Example, following `.kiro/steering/documentation-standards-python.md` (use the docstring from design.md)
    - Name the function and parameters in `snake_case` with a leading underscore for a private helper
    - _Bug_Condition: isBugCondition(X): `os.sep` is `\`, a nested starter file exists, provider is CodeCommit_
    - _Expected_Behavior: result uses `/` as its only separator_
    - _Requirements: 2.2, 2.3, 5.5_

  - [x] 3.2 Route the relpath result through the helper
    - In `RepositoryCreator._seed_collect_files`, change `relative_path = os.path.relpath(full_path, temp_dir)` to `relative_path = _to_codecommit_path(os.path.relpath(full_path, temp_dir))`
    - Do not change the `'filePath'` entry, the error messages, or the cleanup and exit logic. Reassigning `relative_path` makes all three use the normalized value.
    - Do not modify `cli/lib/gh_utils.py`, the zip extraction code, or any other function
    - _Preservation: fileContent, fileMode, batching, cleanup, and GitHub seeding unchanged_
    - _Requirements: 2.1, 2.4, 2.5, 3.5, 3.6, 3.7, 3.8, 5.2_

  - [x] 3.3 Bump the script version
    - Change `VERSION` in `cli/create_repo.py` from `"v0.2.0/2026-07-24"` to `"v0.2.1/2026-11-13"`
    - The version and date are specified by requirement 5.1, so they take precedence over the automatic date rule in `.kiro/steering/ascs-cli-script-versioning.md`
    - Confirm `cli/lib/gh_utils.py` still reads `v0.1.0/2026-07-24`
    - _Requirements: 5.1, 5.2_

  - [x] 3.4 Add helper unit and property tests
    - Add to `tests/test_create_repo_seed_paths.py`:
      - `_to_codecommit_path('.github\\workflows\\deploy.yml', sep='\\')` returns `.github/workflows/deploy.yml` (4.2)
      - `_to_codecommit_path('README.md', sep='\\')` returns `README.md` (4.3)
      - `_to_codecommit_path('weird\\name.txt', sep='/')` returns `weird\name.txt` (4.4)
      - `sep='\\'` with `altsep='/'` gives the same result as `sep='\\'` alone
      - Property 1 (Hypothesis, `@settings(max_examples=200)`): for non-empty segments that exclude `/`, `\`, and NUL, `_to_codecommit_path('\\'.join(segments), sep='\\') == '/'.join(segments)` (4.5)
      - Property 2 (Hypothesis): for any text `s`, `_to_codecommit_path(s, sep='/') == s`
    - Include `# Feature: git-for-windows-bug-in-file-seeding, Property N: ...` and `# Validates: Requirements ...` comments, matching `tests/test_create_repo_merge.py`
    - Check the docstring example: run `doctest.run_docstring_examples(create_repo._to_codecommit_path, vars(create_repo))` from a throwaway Python command (the script module cannot be run with `python -m doctest`) and confirm it prints no failures
    - _Requirements: 2.2, 4.2, 4.3, 4.4, 4.5_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Windows relative paths become `/`-separated
    - **IMPORTANT**: Re-run the SAME test from task 1. Do NOT write a new test.
    - Run: `source .ve/bin/activate && python -m pytest tests/test_create_repo_seed_paths.py -v`
    - **EXPECTED OUTCOME**: The task 1 test PASSES
    - Mutation check: temporarily remove the helper call from `_seed_collect_files`, confirm the task 1 test fails again, then restore the call
    - _Requirements: 2.1, 2.4, 4.8_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - POSIX output is unchanged, and output shape is correct
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Run: `source .ve/bin/activate && python -m pytest tests/test_create_repo_seed_paths.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run the new suite: `source .ve/bin/activate && python -m pytest tests/test_create_repo_seed_paths.py -v`
  - Run the full suite: `source .ve/bin/activate && python -m pytest tests/ -v`
  - Confirm `tests/test_create_repo_merge.py` still passes (it imports `create_repo`)
  - Confirm `git diff --stat` shows changes only in `cli/create_repo.py`, `tests/test_create_repo_seed_paths.py`, and `CHANGELOG.md` (the last after task 5), plus the spec directory
  - Ensure all tests pass, ask the user if questions arise

- [x] 5. Update CHANGELOG.md
  - Add a `### Fixed` section under the existing `## v0.0.21 (unreleased)` header. Do not modify existing text.
  - Use the entry drafted in design.md: names `create_repo.py v0.2.1`, links [issue #9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9) and this spec, and says that seeded file paths are normalized to `/` on every platform with Linux, macOS, and WSL unchanged
  - Include the sub-bullet stating that repositories already seeded from Windows are not repaired and must be deleted and recreated, or have their files re-committed into the correct directories
  - Follow `.kiro/steering/changelog-convention.md` and the format of the `v0.0.18` and `v0.0.19` entries
  - _Requirements: 5.3, 5.4_

- [ ] 6. Windows verification before release (maintainer task)
  - **This task needs a Windows machine, AWS and GitHub credentials, and creates real repositories. The agent does not run it. Ask the maintainer to do it, and record the result.**
  - Run from Windows Git Bash with the `.ve` venv, using the same starter for both runs:
    - `./cli/create_repo.py <throwaway-name>` (CodeCommit)
    - `./cli/create_repo.py <throwaway-name> --provider github`
  - For each repository: `git clone`, `git checkout dev`, `git checkout test`, then `git ls-tree -r --name-only origin/dev`
  - Confirm both checkouts succeed, nested paths such as `.github/workflows/...` appear with `/` separators, and no file name contains `\`
  - Delete both throwaway repositories afterward
  - Record the outcome of both runs (PLAN.md Decision 5 requires this check before release)
  - _Requirements: 6.1, 6.2, 6.3_
