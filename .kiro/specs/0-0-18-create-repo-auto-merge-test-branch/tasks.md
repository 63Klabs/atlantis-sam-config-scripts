# Implementation Plan: create_repo Auto-Merge dev to test

## Overview

This plan implements the automatic `dev` → `test` merge after repository seeding in `cli/create_repo.py`. The feature adds a `--skip-test-merge` opt-out flag, provider-specific merge logic (CodeCommit server-side fast-forward and GitHub clone-reuse merge), non-fatal failure handling, and a follow-up hint for test pipeline creation. Property-based tests use Hypothesis.

## Tasks

- [x] 1. Add `--skip-test-merge` flag and instance state to `RepositoryCreator`
  - [x] 1.1 Add `--skip-test-merge` argument to `parse_args()` and update EPILOG
    - Add the `--skip-test-merge` `store_true` argument to `parse_args()`
    - Update `EPILOG` to document the default merge behavior and opt-out flag with examples
    - Pass `skip_test_merge=args.skip_test_merge` to the `RepositoryCreator` constructor in `main()`
    - _Requirements: 2.1, 7.2, 7.3_

  - [x] 1.2 Add new instance attributes to `RepositoryCreator.__init__()`
    - Add `skip_test_merge` keyword parameter (default `False`)
    - Add `self._github_clone_dir = None` attribute
    - Add `self.test_branch_updated = False` attribute
    - _Requirements: 2.1, 5.1_

- [x] 2. Implement merge logic and failure handling
  - [x] 2.1 Implement `_merge_dev_to_test()` dispatcher method
    - Create provider-dispatch method mirroring existing `_seed_repository()` pattern
    - _Requirements: 1.3_

  - [x] 2.2 Implement `_merge_dev_to_test_codecommit()`
    - Call `self.codecommit_client.merge_branches_by_fast_forward()` with `repositoryName`, `sourceCommitSpecifier='dev'`, `destinationCommitSpecifier='test'`, `targetBranch='test'`
    - Set `self.test_branch_updated = True` on success
    - Emit progress/success output via `Colorize` and `Log`
    - Catch exceptions and route to `_handle_merge_failure()`
    - _Requirements: 1.1, 1.4, 3.1, 4.1, 4.2, 7.1_

  - [x] 2.3 Implement `_merge_dev_to_test_github()`
    - Guard against missing `self._github_clone_dir`
    - Call `GitHubUtils.merge_branches_fast_forward()` with the clone dir
    - Set `self.test_branch_updated = True` on success
    - Emit progress/success output via `Colorize` and `Log`
    - Catch exceptions and route to `_handle_merge_failure()`
    - _Requirements: 1.1, 1.4, 3.1, 5.1, 5.2, 7.1_

  - [x] 2.4 Implement `_handle_merge_failure()` non-fatal handler
    - Set `self.test_branch_updated = False`
    - Log warning via `Log.warning()`
    - Print warning via `Colorize.warning()`
    - Print manual merge instructions via `_build_manual_merge_instructions()`
    - Never call `delete_repository` or `sys.exit`
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

  - [x] 2.5 Implement `_build_manual_merge_instructions()` helper
    - Return list of manual merge command strings using HTTPS clone URL
    - _Requirements: 3.4_

  - [x] 2.6 Implement `_skip_test_merge_notice()`
    - Print informational skip message and manual merge instructions
    - _Requirements: 2.5_

- [x] 3. Implement GitHub merge utility and clone lifecycle
  - [x] 3.1 Add `GitHubUtils.merge_branches_fast_forward()` static method in `cli/lib/gh_utils.py`
    - Implement `git checkout <dest_branch>`, `git merge --ff-only <source_branch>`, `git push origin <dest_branch>` with `cwd=git_dir`
    - Raise on any `CalledProcessError`
    - _Requirements: 5.2, 5.3_

  - [x] 3.2 Modify `_seed_repository_github()` to retain clone for reuse
    - Store `git_dir` as `self._github_clone_dir` instead of cleaning it up
    - Remove the `shutil.rmtree(git_dir, ...)` from this method (move to centralized cleanup)
    - _Requirements: 5.1, 5.5_

  - [x] 3.3 Implement `_cleanup_github_clone()` method
    - Remove `self._github_clone_dir` directory if it exists
    - Reset `self._github_clone_dir = None`
    - No-op when `_github_clone_dir` is `None` (CodeCommit path)
    - _Requirements: 5.5_

- [x] 4. Wire merge into `create_and_seed_repository()` and follow-up hint into `main()`
  - [x] 4.1 Insert merge/skip/cleanup into `create_and_seed_repository()`
    - Add `try/finally` block after `_seed_repository()` inside the `if self.source:` block
    - Call `_skip_test_merge_notice()` when `self.skip_test_merge` is True
    - Call `_merge_dev_to_test()` otherwise
    - Call `_cleanup_github_clone()` in the `finally` block
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 2.2, 2.3, 2.4, 5.5, 7.4_

  - [x] 4.2 Implement `build_test_pipeline_hint()` and print it in `main()`
    - Build command string with `./cli/config.py pipeline <prefix> <project_id> test`
    - Append `--profile <profile>` only when profile is truthy
    - Include line with actual `repo_name` for the Repository parameter
    - In `main()`, print the hint after clone URLs when `repo_creator.test_branch_updated` is True
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Property-based tests with Hypothesis
  - [x] 6.1 Write property test for merge gating logic
    - **Property 1: Merge is attempted exactly when seeded and not opted out**
    - **Validates: Requirements 1.1, 2.2, 2.3, 2.4**
    - Test a pure `should_merge_test(source, skip_test_merge)` predicate with generated `source` values (None, empty string, random S3/GitHub URIs) and `skip_test_merge` booleans

  - [x] 6.2 Write property test for follow-up hint command construction
    - **Property 2: Follow-up hint command construction**
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5**
    - Test `build_test_pipeline_hint()` with generated `repo_name` and `profile` values; assert placeholder preservation, conditional `--profile` appendage, and `repo_name` presence

  - [x] 6.3 Write property test for non-fatal failure handling
    - **Property 3: Merge failure is non-fatal and leaves the hint suppressed**
    - **Validates: Requirements 3.2, 3.3, 3.4, 6.6**
    - Test `_handle_merge_failure()` with generated exception types/messages; assert no `SystemExit`, no `delete_repository` call, `test_branch_updated` remains False

  - [x] 6.4 Write property test for hint gating on success/skip/failure
    - **Property 4: Successful merge enables the hint; skip/failure disables it**
    - **Validates: Requirements 6.1, 6.6**
    - Parametrize success/skip/failure outcomes and verify `test_branch_updated` state

  - [x] 6.5 Write property test for GitHub clone reuse and cleanup
    - **Property 5: GitHub merge reuses the seed clone and cleans it up**
    - **Validates: Requirements 5.1, 5.5**
    - Create temp dirs, verify merge uses `_github_clone_dir`, verify cleanup removes the directory and resets attribute

- [x] 7. Unit tests for merge behavior
  - [x] 7.1 Write unit tests for flag parsing and CodeCommit merge path
    - Test `--skip-test-merge` defaults False and present yields True
    - Test CodeCommit merge calls `merge_branches_by_fast_forward` with correct arguments
    - Test CodeCommit merge failure is non-fatal (no `delete_repository`, no `sys.exit`)
    - _Requirements: 2.1, 4.1, 3.2, 3.3_

  - [x] 7.2 Write unit tests for GitHub merge path and `GitHubUtils.merge_branches_fast_forward()`
    - Test `merge_branches_fast_forward` issues correct `git` commands in order with `cwd=git_dir`
    - Test GitHub merge failure is handled non-fatally; clone is still cleaned up
    - Test reuse of `_github_clone_dir` (no second clone created)
    - _Requirements: 5.1, 5.2, 5.4, 5.5_

  - [x] 7.3 Write unit tests for skip path, no-source path, and hint output
    - Test `--skip-test-merge` prevents merge call, prints skip notice, cleans GitHub clone, leaves `test_branch_updated` False
    - Test no source resolved means neither seeding nor merge invoked
    - Test hint printed only when `test_branch_updated` True; contains placeholders, conditional `--profile`, and `repo_name`
    - Test EPILOG/help documents `--skip-test-merge`
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 6.1, 6.6, 7.2, 7.3_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python (matching the existing codebase)
- Test files: `tests/test_create_repo_merge.py` (properties + unit tests) and `tests/test_gh_utils_merge.py` (GitHubUtils merge command tests)
- Hypothesis is already available in this repository (see `.hypothesis/` directory)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "3.1"] },
    { "id": 1, "tasks": ["2.1", "2.4", "2.5", "2.6", "3.2", "3.3"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5", "7.1", "7.2", "7.3"] }
  ]
}
```
