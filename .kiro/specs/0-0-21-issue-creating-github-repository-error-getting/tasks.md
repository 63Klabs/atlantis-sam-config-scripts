# Tasks: GitHub Repository Creation Error Fix

**Spec**: 0-0-21-issue-creating-github-repository-error-getting  
**Status**: Complete  
**Last Updated**: 2026-11-14

## Overview

Implementation tasks for adding retry logic, enhanced error logging, and user-prompted cleanup to GitHub repository creation. Tasks are ordered by dependency and can be implemented incrementally with testing at each stage.

## Task Breakdown

### Phase 1: Retry Logic and Stderr Logging (Core Fix)

#### Task 1.1: Add retry helper method to `gh_utils.py`

**File**: `cli/lib/gh_utils.py`

**Description**: Create a new static method `_retry_gh_command()` that executes a GitHub CLI command with retry logic and exponential backoff.

**Implementation Details**:
- [x] Add `import time` at the top of the file
- [x] Create `_retry_gh_command()` static method with signature:
  ```python
  @staticmethod
  def _retry_gh_command(command: List[str], max_retries: int = 3) -> subprocess.CompletedProcess:
  ```
- [x] Implement initial attempt with `subprocess.run(command, capture_output=True, text=True, check=True)`
- [x] Catch `subprocess.CalledProcessError` and log stderr at ERROR level
- [x] Implement retry loop with delays: `[1, 2, 4]` seconds
- [x] Log each retry attempt at INFO level: `"Retrying gh command (attempt X of Y) after Z second(s)..."`
- [x] Sleep before each retry using `time.sleep(delay)`
- [x] On successful retry, log at INFO level: `"gh command succeeded on retry attempt X"`
- [x] After all retries exhausted, log at ERROR level: `"gh command failed after N attempts..."`
- [x] Re-raise the last `CalledProcessError`
- [x] Add comprehensive docstring with Args, Returns, Raises, Example

**Acceptance Criteria**:
- Method accepts command as `List[str]` and optional `max_retries` parameter
- Initial attempt does not count toward retry limit
- Exponential backoff delays are 1s, 2s, 4s
- Each attempt logs appropriately (initial, retries, exhaustion)
- Stderr from failed attempts is logged at ERROR level
- Returns `subprocess.CompletedProcess` on success
- Raises `subprocess.CalledProcessError` after exhaustion

**Estimated Effort**: 1 hour  
**Risk**: Low

---

#### Task 1.2: Update `get_repository()` to use retry logic

**File**: `cli/lib/gh_utils.py`

**Description**: Replace direct `subprocess.run()` call in `get_repository()` with `_retry_gh_command()` and add debug logging.

**Implementation Details**:
- [x] Add debug log before calling `gh repo view`: `Log.debug(f"Calling gh repo view for repository: {repo_name}")`
- [x] Replace the `subprocess.run()` call with:
  ```python
  result = GitHubUtils._retry_gh_command([
      "gh", "repo", "view", repo_name, "--json",
      "name,nameWithOwner,owner,repositoryTopics,sshUrl,isTemplate,templateRepository,visibility,url"
  ])
  ```
- [x] Use `result.stdout` instead of `result.stdout` (no change in access pattern)
- [x] Add debug log after successful retrieval: `Log.debug(f"Successfully retrieved repository info for: {repo_name}")`
- [x] Keep existing exception handling for `CalledProcessError` (stderr already logged by `_retry_gh_command`)
- [x] Add exception handler for non-`CalledProcessError` exceptions:
  ```python
  except Exception as e:
      Log.error(f"Unexpected error in get_repository: {e}")
      raise Exception(f"Failed to get repository info: {str(e)}")
  ```
- [x] Update docstring to mention retry behavior

**Acceptance Criteria**:
- `get_repository()` uses `_retry_gh_command()` instead of direct `subprocess.run()`
- Debug logs added before and after `gh repo view` call
- Exception handling covers both `CalledProcessError` and other exceptions
- Docstring updated to document retry behavior
- Method signature and return type unchanged

**Estimated Effort**: 30 minutes  
**Risk**: Low

---

#### Task 1.3: Add stderr logging to `create_repo()`

**File**: `cli/lib/gh_utils.py`

**Description**: Update `create_repo()` to log stderr when `gh repo create` fails.

**Implementation Details**:
- [x] Locate the existing `except subprocess.CalledProcessError as e:` handler
- [x] Add before the `raise Exception(...)` line:
  ```python
  stderr_text = e.stderr if e.stderr else "(no stderr)"
  Log.error(f"gh repo create stderr: {stderr_text}")
  ```
- [x] Keep existing exception wrapping: `raise Exception(f"Failed to create repository: {e.stderr}")`

**Acceptance Criteria**:
- Stderr is logged at ERROR level when `gh repo create` fails
- Handles case where stderr is None
- User-facing exception message unchanged

**Estimated Effort**: 10 minutes  
**Risk**: Low

---

#### Task 1.4: Add stderr logging to `create_branch_structure()`

**File**: `cli/lib/gh_utils.py`

**Description**: Update `create_branch_structure()` to log stderr for failed git/gh commands.

**Implementation Details**:
- [x] Locate the `finally:` block with `shutil.rmtree(temp_dir, ignore_errors=True)`
- [x] Wrap the entire method body in try/except to catch `subprocess.CalledProcessError`:
  ```python
  try:
      # ... existing code ...
  except subprocess.CalledProcessError as e:
      stderr_text = e.stderr if e.stderr else "(no stderr)"
      Log.error(f"create_branch_structure command failed: {' '.join(e.cmd) if hasattr(e, 'cmd') else 'unknown'}")
      Log.error(f"stderr: {stderr_text}")
      raise
  finally:
      os.chdir("/")
      shutil.rmtree(temp_dir, ignore_errors=True)
  ```
- [x] Ensure `finally` block still executes for cleanup

**Acceptance Criteria**:
- Stderr is logged for any failed subprocess command
- Exception is re-raised after logging
- Cleanup in `finally` block still executes
- Command that failed is identified in log message

**Estimated Effort**: 15 minutes  
**Risk**: Low

---

#### Task 1.5: Add stderr logging to `create_init_commit()`

**File**: `cli/lib/gh_utils.py`

**Description**: Update `create_init_commit()` to log stderr for failed git commands during seeding.

**Implementation Details**:
- [x] Locate the existing `except subprocess.CalledProcessError as e:` handler
- [x] Update the exception handling to log stderr:
  ```python
  except subprocess.CalledProcessError as e:
      stderr_text = e.stderr if e.stderr else "(no stderr)"
      cmd_str = ' '.join(e.cmd) if hasattr(e, 'cmd') else 'unknown'
      Log.error(f"git command failed in create_init_commit: {cmd_str}")
      Log.error(f"stderr: {stderr_text}")
      raise Exception(f"Error in GitHub CLI command: {cmd_str}\nError: {stderr_text}")
  ```

**Acceptance Criteria**:
- Stderr is logged at ERROR level for failed git commands
- Command that failed is identified in log
- Exception message includes stderr text

**Estimated Effort**: 10 minutes  
**Risk**: Low

---

#### Task 1.6: Add stderr logging to `merge_branches_fast_forward()`

**File**: `cli/lib/gh_utils.py`

**Description**: Update `merge_branches_fast_forward()` to log stderr for failed merge operations.

**Implementation Details**:
- [x] Check if method exists and has exception handling (added in v0.1.0)
- [x] If exception handler exists, add stderr logging:
  ```python
  except subprocess.CalledProcessError as e:
      stderr_text = e.stderr if e.stderr else "(no stderr)"
      Log.error(f"git merge stderr: {stderr_text}")
      raise Exception(f"Failed to merge branches: {stderr_text}")
  ```
- [x] If no exception handler, wrap subprocess calls in try/except with stderr logging

**Acceptance Criteria**:
- Stderr is logged for failed merge operations
- Exception message includes stderr text
- Method behavior unchanged (still raises exception on failure)

**Estimated Effort**: 10 minutes  
**Risk**: Low

---

#### Task 1.7: Update VERSION in `gh_utils.py`

**File**: `cli/lib/gh_utils.py`

**Description**: Update VERSION constant to reflect new retry behavior.

**Implementation Details**:
- [x] Locate `VERSION = "v0.1.0/2026-07-24"` at the top of the file
- [x] Update to `VERSION = "v0.2.0/2026-11-14"`
- [x] Verify date matches implementation date (update if different)

**Acceptance Criteria**:
- VERSION updated to `v0.2.0/YYYY-MM-DD`
- Date reflects actual implementation date

**Estimated Effort**: 2 minutes  
**Risk**: None

---

### Phase 2: Cleanup Prompt and Flag

#### Task 2.1: Add `--cleanup-on-failure` flag to argument parser

**File**: `cli/create_repo.py`

**Description**: Add new command-line flag for automatic repository deletion on seeding failure.

**Implementation Details**:
- [x] Locate the argument parser section (after `--skip-test-merge`)
- [x] Add new argument:
  ```python
  parser.add_argument(
      '--cleanup-on-failure',
      action='store_true',
      default=False,
      help='Automatically delete GitHub repository if seeding fails (no prompt)'
  )
  ```
- [x] Verify flag appears in help output: `./cli/create_repo.py -h`

**Acceptance Criteria**:
- Flag is defined with correct name and action
- Default value is False
- Help text is descriptive
- Flag appears in `--help` output

**Estimated Effort**: 5 minutes  
**Risk**: None

---

#### Task 2.2: Update `RepositoryCreator.__init__()` signature

**File**: `cli/create_repo.py`

**Description**: Add `cleanup_on_failure` parameter to constructor and store as instance variable.

**Implementation Details**:
- [x] Add parameter to `__init__()` signature after `skip_test_merge`:
  ```python
  cleanup_on_failure: Optional[bool] = False
  ```
- [x] Add instance variable after `self.skip_test_merge = skip_test_merge`:
  ```python
  self.cleanup_on_failure = cleanup_on_failure
  ```
- [x] Locate the `RepositoryCreator` instantiation in `main()` or similar
- [x] Add argument to constructor call:
  ```python
  cleanup_on_failure=args.cleanup_on_failure
  ```

**Acceptance Criteria**:
- Constructor accepts `cleanup_on_failure` parameter with default False
- Parameter stored as instance variable `self.cleanup_on_failure`
- Constructor call passes `args.cleanup_on_failure` to constructor

**Estimated Effort**: 5 minutes  
**Risk**: None

---

#### Task 2.3: Create `_delete_github_repository()` method

**File**: `cli/create_repo.py`

**Description**: Add helper method to delete a GitHub repository using `gh` CLI.

**Implementation Details**:
- [x] Add new method after `_seed_repository_github()`:
  ```python
  def _delete_github_repository(self) -> None:
      """Delete a GitHub repository using gh CLI.
      
      Logs success or failure. Does not raise exceptions (deletion is best-effort
      after a seeding failure).
      """
      try:
          subprocess.run(
              ["gh", "repo", "delete", self.repo_name, "--yes"],
              check=True,
              capture_output=True,
              text=True
          )
          click.echo(Colorize.success(f"Repository {self.repo_name} deleted."))
          Log.info(f"Deleted failed repository: {self.repo_name}")
      except subprocess.CalledProcessError as e:
          stderr_text = e.stderr if e.stderr else "(no stderr)"
          Log.error(f"Failed to delete repository {self.repo_name}: {e}")
          Log.error(f"gh repo delete stderr: {stderr_text}")
          click.echo(Colorize.error("Failed to delete repository. You may need to delete it manually."))
          click.echo(Colorize.output(f"Manual deletion command: gh repo delete {self.repo_name}"))
      except Exception as e:
          Log.error(f"Unexpected error deleting repository {self.repo_name}: {e}")
          click.echo(Colorize.error("Failed to delete repository. You may need to delete it manually."))
  ```
- [x] Ensure `subprocess` is imported at the top of the file

**Acceptance Criteria**:
- Method takes no parameters (uses `self.repo_name`)
- Calls `gh repo delete` with `--yes` flag
- Logs success at INFO level
- Logs failure at ERROR level with stderr
- Shows user-friendly error message on failure
- Does NOT raise exceptions (best-effort deletion)

**Estimated Effort**: 15 minutes  
**Risk**: Low

---

#### Task 2.4: Create `_handle_github_seeding_failure()` method

**File**: `cli/create_repo.py`

**Description**: Add method to handle cleanup prompt or auto-deletion after seeding failure.

**Implementation Details**:
- [x] Add new method after `_delete_github_repository()`:
  ```python
  def _handle_github_seeding_failure(self) -> None:
      """Handle cleanup after GitHub repository seeding fails.
      
      If --cleanup-on-failure flag is set, automatically deletes the repository.
      Otherwise, prompts the user to decide whether to delete.
      
      Does not raise exceptions if deletion fails (seeding failure is the primary error).
      """
      if self.cleanup_on_failure:
          # Auto-delete without prompting
          click.echo(Colorize.output(f"Auto-deleting failed repository (--cleanup-on-failure): {self.repo_name}"))
          Log.info(f"Auto-deleting failed repository (--cleanup-on-failure): {self.repo_name}")
          self._delete_github_repository()
      else:
          # Prompt user
          try:
              response = click.prompt(
                  Colorize.prompt(f"Seeding failed. Delete repository {self.repo_name}? (y/N)"),
                  type=str,
                  default="N",
                  show_default=False
              )
              
              if response.lower() == 'y':
                  click.echo(Colorize.output(f"Deleting repository: {self.repo_name}"))
                  Log.info(f"User confirmed deletion of failed repository: {self.repo_name}")
                  self._delete_github_repository()
              else:
                  click.echo(Colorize.output(f"Repository {self.repo_name} was not deleted."))
                  click.echo(Colorize.output(f"You can delete it manually with: gh repo delete {self.repo_name}"))
                  Log.info(f"Repository {self.repo_name} was not deleted (user declined).")
          except EOFError:
              # Non-interactive environment (e.g., piped input, CI/CD)
              Log.warning("Failed to read user input for cleanup prompt, defaulting to 'N' (do not delete)")
              click.echo(Colorize.output(f"Repository {self.repo_name} was not deleted (non-interactive environment)."))
              click.echo(Colorize.output(f"You can delete it manually with: gh repo delete {self.repo_name}"))
  ```

**Acceptance Criteria**:
- Checks `self.cleanup_on_failure` flag
- If True: auto-deletes without prompt, logs appropriately
- If False: prompts user with default "N"
- Responds to "y" or "Y" by deleting
- Responds to "n", "N", or Enter by keeping repository
- Handles `EOFError` by defaulting to "N" and logging warning
- Shows manual deletion command when repository is kept
- Does NOT raise exceptions

**Estimated Effort**: 20 minutes  
**Risk**: Low

---

#### Task 2.5: Update `_seed_repository_github()` exception handler

**File**: `cli/create_repo.py`

**Description**: Call cleanup handler when GitHub seeding fails.

**Implementation Details**:
- [x] Locate `_seed_repository_github()` method
- [x] Find the `except Exception as e:` block (around line 837)
- [x] After the error logging, before `sys.exit(1)`, add:
  ```python
  # Handle cleanup prompt or auto-deletion
  self._handle_github_seeding_failure()
  ```
- [x] Ensure the `finally:` block still executes (cleanup temp_dir)

**Acceptance Criteria**:
- `_handle_github_seeding_failure()` is called in the exception handler
- Call happens after error logging but before `sys.exit(1)`
- `finally` block still executes for temp directory cleanup

**Estimated Effort**: 5 minutes  
**Risk**: Low

---

#### Task 2.6: Update VERSION in `create_repo.py`

**File**: `cli/create_repo.py`

**Description**: Update VERSION constant to reflect cleanup prompt feature.

**Implementation Details**:
- [x] Locate `VERSION = "v0.2.1/2026-11-13"` at the top of the file
- [x] Update to `VERSION = "v0.2.2/2026-11-14"`
- [x] Verify date matches implementation date (update if different)

**Acceptance Criteria**:
- VERSION updated to `v0.2.2/YYYY-MM-DD`
- Date reflects actual implementation date

**Note**: `v0.2.2` was the version at the end of this task. Task 2.7 later bumped it to the final `v0.2.3/2026-11-14`.

**Estimated Effort**: 2 minutes  
**Risk**: None

---

#### Task 2.7: Follow-up fix - cleanup for all post-creation failures on GitHub

**File**: `cli/create_repo.py`, `tests/test_create_repo_download_failure_cleanup.py`

**Description**: Manual testing showed that `--source s3://invalid-bucket/invalid.zip` fails at the S3 download with `403 Forbidden`. That failure happened before the seeding step, so the cleanup prompt never appeared and the new GitHub repository was left behind. Cleanup is now offered for any failure after the repository is created.

**Implementation Details**:
- [x] In `create_and_seed_repository()`, wrap the post-creation steps (branch structure, download/extract, seeding) in one `try/except (Exception, SystemExit)` that calls `_handle_github_seeding_failure()` when `provider == 'github'` and the failure is real (not a clean exit), then re-raises unchanged
- [x] Failures in download, extract, branch structure, file collection, and seeding on the GitHub path trigger the cleanup exactly once (one prompt, or one auto-delete with `--cleanup-on-failure`)
- [x] Guard the CodeCommit `delete_repository` calls in the download/extract and file-processing error handlers with `provider == 'codecommit'`
- [x] Update `VERSION` to `v0.2.3/2026-11-14`
- [x] Add `tests/test_create_repo_download_failure_cleanup.py` covering GitHub download/extract/seeding/branch failures, prompt and flag paths, and unchanged CodeCommit behavior

**Acceptance Criteria**:
- A download or extract failure on the GitHub path offers cleanup once and keeps the original exit code and error messages
- A failure to create the repository itself never offers cleanup
- CodeCommit behavior is unchanged (its own delete-on-failure logic still runs, and no GitHub cleanup is offered)
- `create_repo.py` VERSION is `v0.2.3/2026-11-14`
- New unit tests pass

**Estimated Effort**: 1 hour  
**Risk**: Low

---

### Phase 3: Testing

#### Task 3.1: Create unit tests for retry logic

**File**: `tests/test_gh_utils.py`

**Description**: Add unit tests for `_retry_gh_command()` covering all scenarios.

**Implementation Details**:
- [x] Create test file if it doesn't exist
- [x] Add imports: `pytest`, `unittest.mock`, `subprocess`, and `from lib.gh_utils import GitHubUtils` (with a `sys.path` insert for `cli/` so `lib.gh_utils` resolves)
- [x] Create test class `TestRetryLogic`
- [x] Add test: `test_success_on_first_attempt` - mock success, verify no retries
- [x] Add test: `test_success_on_first_retry` - fail once, succeed on retry 1
- [x] Add test: `test_success_on_second_retry` - fail twice, succeed on retry 2
- [x] Add test: `test_success_on_third_retry` - fail three times, succeed on retry 3
- [x] Add test: `test_all_retries_exhausted` - always fail, verify 4 total attempts
- [x] Add test: `test_exponential_backoff_delays` - verify sleep(1), sleep(2), sleep(4)
- [x] Add test: `test_non_calledprocesserror_not_retried` - verify other exceptions not retried
- [x] Add test: `test_stderr_logged_on_failure` - verify stderr logged at ERROR level
- [x] Run tests: `pytest tests/test_gh_utils.py::TestRetryLogic -v`

**Acceptance Criteria**:
- All 8 tests pass
- Tests patch `subprocess.run` and `time.sleep` in `lib.gh_utils`, and patch `lib.logger.Log` (`_retry_gh_command` imports `Log` locally, so patching `lib.gh_utils.Log` would have no effect)
- Tests verify call counts, delays, and exception behavior
- Tests verify the failed command's stderr is logged with `Log.error`

**Estimated Effort**: 1.5 hours  
**Risk**: Low

---

#### Task 3.2: Create unit tests for cleanup prompt

**File**: `tests/test_create_repo_cleanup.py`

**Description**: Add unit tests for cleanup prompt and auto-deletion logic.

**Implementation Details**:
- [x] Create test file if it doesn't exist
- [x] Add imports: `pytest`, `click`, `unittest.mock`, and `import create_repo` / `from create_repo import RepositoryCreator` (with a `sys.path` insert for `cli/`)
- [x] Create test class `TestCleanupPrompt`
- [x] Add test: `test_user_confirms_deletion` - mock "y" response, verify delete called
- [x] Add test: `test_user_declines_deletion_lowercase_n` - mock "n", verify no delete
- [x] Add test: `test_user_declines_deletion_uppercase_n` - mock "N", verify no delete
- [x] Add test: `test_user_declines_deletion_default` - mock Enter (empty), verify no delete
- [x] Add test: `test_auto_delete_with_flag` - set flag True, verify delete without prompt
- [x] Add test: `test_deletion_failure_handled_gracefully` - delete fails, verify no exception
- [x] Add test: `test_eoferror_defaults_to_no` - mock EOFError, verify no delete and warning logged
- [x] Run tests: `pytest tests/test_create_repo_cleanup.py::TestCleanupPrompt -v`

**Additional tests beyond the list above**: `test_user_confirms_deletion_uppercase_y`, `test_deletion_failure_after_prompt_handled_gracefully`, and `test_abort_defaults_to_no` (click `Abort`, e.g. Ctrl+C at the prompt). `test_user_declines_deletion_default` is parametrized over `""`, `"N"`, and `"   "`.

**Acceptance Criteria**:
- All tests in `TestCleanupPrompt` pass (10 test functions)
- Tests patch `Colorize.prompt`, `subprocess.run`, `Log`, and `click.echo` in `create_repo`; the `RepositoryCreator` is built with `object.__new__` so no AWS session is created
- Tests verify `gh repo delete <name> --yes` is called or not called appropriately
- Tests verify no exceptions raised on deletion failure, EOFError, or Abort

**Estimated Effort**: 1.5 hours  
**Risk**: Low

---

#### Task 3.3: Manual testing - retry logic

**Description**: Manually test retry logic with real `gh` CLI commands.

**Test Steps**:
- [x] Set up: Ensure `gh` CLI is installed and authenticated
- [x] Test 1: Create repository and verify no retries (normal success case)
  - Run: `./cli/create_repo.py chadkluck/test-retry-1 --provider github`
  - Expected: Repository created, no retry messages in logs
- [x] Test 2: Simulate failure by temporarily disabling network (optional)
  - Expected: Retry attempts logged, eventual failure after 4 attempts
- [x] Test 3: Check logs for stderr output when failure occurs
  - Expected: Stderr logged at ERROR level
- [x] Clean up: Delete test repositories

**Acceptance Criteria**:
- Repository creation succeeds in normal case
- Retry messages appear in logs when failures occur
- Stderr is logged for failed attempts

**Manual test results**: Run on 2026-11-14 against real GitHub in the `chadkluck` account. All tests PASS. 8 throwaway repositories were created during the 3.3 and 3.4 manual tests, and all 8 were deleted.

**Estimated Effort**: 30 minutes  
**Risk**: Low (uses real GitHub API)

---

#### Task 3.4: Manual testing - cleanup prompt

**Description**: Manually test cleanup prompt with real GitHub repositories.

**Note**: The invalid-source command below (`--source s3://invalid-bucket/invalid.zip`) fails at the S3 download with `403 Forbidden`. Before Task 2.7 that failure happened before the cleanup code ran, so no prompt appeared and the repository was left behind. Since Task 2.7, download and extract failures on the GitHub path also reach the cleanup prompt (or the `--cleanup-on-failure` auto-delete), so the commands below now behave as described.

**Test Steps**:
- [x] Set up: Ensure `gh` CLI is installed and authenticated
- [x] Test 1: Trigger seeding failure, respond "y" to prompt
  - Run: `./cli/create_repo.py chadkluck/test-cleanup-1 --source s3://invalid-bucket/invalid.zip --provider github`
  - At prompt, type: `y`
  - Expected: Repository deleted, success message shown
  - Verify: `gh repo view chadkluck/test-cleanup-1` returns error (repo deleted)
- [x] Test 2: Trigger seeding failure, respond "N" to prompt
  - Run: `./cli/create_repo.py chadkluck/test-cleanup-2 --source s3://invalid-bucket/invalid.zip --provider github`
  - At prompt, press Enter (default N)
  - Expected: Repository NOT deleted, manual command shown
  - Verify: `gh repo view chadkluck/test-cleanup-2` succeeds (repo exists)
  - Clean up: `gh repo delete chadkluck/test-cleanup-2 --yes`
- [x] Test 3: Use `--cleanup-on-failure` flag
  - Run: `./cli/create_repo.py chadkluck/test-cleanup-3 --source s3://invalid-bucket/invalid.zip --provider github --cleanup-on-failure`
  - Expected: No prompt, repository auto-deleted
  - Verify: `gh repo view chadkluck/test-cleanup-3` returns error

**Acceptance Criteria**:
- Prompt appears after seeding failure
- "y" response deletes repository
- "N" or Enter keeps repository
- `--cleanup-on-failure` skips prompt and auto-deletes
- Manual deletion command is correct

**Manual test results**: Run on 2026-11-14 against real GitHub in the `chadkluck` account. Tests 1 to 3 were originally carried out using a valid starter with a simulated clone failure (the invalid S3 source failed before the cleanup code at that time). All tests PASS. 8 throwaway repositories were created across the 3.3 and 3.4 manual tests, and all 8 were deleted.

**Not re-run**: The post-fix invalid-S3-source behavior is covered by unit tests in `tests/test_create_repo_download_failure_cleanup.py`. It has NOT been re-run against real GitHub.

**Estimated Effort**: 30 minutes  
**Risk**: Low (uses real GitHub API)

---

### Phase 4: Documentation and Polish

#### Task 4.1: Update CHANGELOG.md

**File**: `CHANGELOG.md`

**Description**: Add entry for this fix under the unreleased v0.0.21 section.

**Implementation Details**:
- [x] Locate `## v0.0.21 (unreleased)` section
- [x] Add entry under `### Fixed` (or create section if it doesn't exist):
  ```markdown
  ### Fixed
  - **Script: create_repo.py v0.2.3** - Added retry logic for intermittent `gh repo view` failures after GitHub repository creation [Spec: 0-0-21-issue-creating-github-repository-error-getting](.kiro/specs/0-0-21-issue-creating-github-repository-error-getting/), addresses [#1](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/1)
    - `gh repo view` now retries up to 3 times with exponential backoff (1s, 2s, 4s) to handle GitHub API propagation delays
    - Added user prompt after seeding failures: "Delete repository? (y/N)" to clean up partial repositories
    - Added `--cleanup-on-failure` flag for automatic deletion in headless/CI environments
    - Enhanced error logging: stderr from all `gh` CLI commands is now logged for troubleshooting
  - **Library: gh_utils.py v0.2.0** - Added retry logic and comprehensive stderr logging for GitHub CLI operations
    - New `_retry_gh_command()` helper for reusable retry logic with exponential backoff
    - Stderr is now captured and logged at ERROR level for all failed `gh` CLI commands
  ```

**Acceptance Criteria**:
- Entry added under v0.0.21 unreleased section
- Entry references the spec directory with relative link
- Entry references GitHub issue #1
- Entry describes user-facing changes clearly
- Both script and library versions mentioned

**Estimated Effort**: 10 minutes  
**Risk**: None

---

#### Task 4.2: Verify help text

**Description**: Ensure `--cleanup-on-failure` flag appears in help output with correct description.

**Test Steps**:
- [x] Run: `./cli/create_repo.py -h`
- [x] Verify `--cleanup-on-failure` appears in optional arguments
- [x] Verify help text reads: "Automatically delete GitHub repository if seeding fails (no prompt)"
- [x] Verify help text is clear and concise

**Acceptance Criteria**:
- Flag appears in help output
- Help text is accurate and user-friendly
- No typos or formatting issues

**Estimated Effort**: 5 minutes  
**Risk**: None

---

#### Task 4.3: Update script help comments (optional)

**File**: `cli/create_repo.py`

**Description**: Update top-of-file comments to mention new flag.

**Implementation Details**:
- [x] Locate usage comments near the top of the file (if any)
- [x] Add mention of `--cleanup-on-failure` flag
- [x] Update examples if present

**Note**: This is optional and may not be necessary if help text is comprehensive.

**Acceptance Criteria**:
- Comments are updated if they exist and reference command-line options
- Examples include the new flag if applicable

**Estimated Effort**: 5 minutes  
**Risk**: None

---

## Task Summary

| Phase | Task | File | Effort | Risk |
|-------|------|------|--------|------|
| 1 | 1.1 | `gh_utils.py` | 1h | Low |
| 1 | 1.2 | `gh_utils.py` | 30m | Low |
| 1 | 1.3 | `gh_utils.py` | 10m | Low |
| 1 | 1.4 | `gh_utils.py` | 15m | Low |
| 1 | 1.5 | `gh_utils.py` | 10m | Low |
| 1 | 1.6 | `gh_utils.py` | 10m | Low |
| 1 | 1.7 | `gh_utils.py` | 2m | None |
| 2 | 2.1 | `create_repo.py` | 5m | None |
| 2 | 2.2 | `create_repo.py` | 5m | None |
| 2 | 2.3 | `create_repo.py` | 15m | Low |
| 2 | 2.4 | `create_repo.py` | 20m | Low |
| 2 | 2.5 | `create_repo.py` | 5m | Low |
| 2 | 2.6 | `create_repo.py` | 2m | None |
| 2 | 2.7 | `create_repo.py`, `tests/test_create_repo_download_failure_cleanup.py` | 1h | Low |
| 3 | 3.1 | `tests/test_gh_utils.py` | 1.5h | Low |
| 3 | 3.2 | `tests/test_create_repo_cleanup.py` | 1.5h | Low |
| 3 | 3.3 | Manual | 30m | Low |
| 3 | 3.4 | Manual | 30m | Low |
| 4 | 4.1 | `CHANGELOG.md` | 10m | None |
| 4 | 4.2 | Manual | 5m | None |
| 4 | 4.3 | `create_repo.py` | 5m | None |
| **Total** | | | **~7 hours** | |

## Dependencies

### Task Dependencies

```
Phase 1 (Core Fix):
  1.1 (retry helper) → 1.2 (use in get_repository)
  1.3, 1.4, 1.5, 1.6 (stderr logging) can run in parallel
  1.7 (version) after all Phase 1 tasks

Phase 2 (Cleanup):
  2.1, 2.2 (flag and init) can run in parallel
  2.3 (delete method) → 2.4 (handle failure method) → 2.5 (call handler)
  2.6 (version) after all Phase 2 tasks

Phase 3 (Testing):
  3.1 requires Phase 1 complete
  3.2 requires Phase 2 complete
  3.3, 3.4 can run in parallel after their respective phases

Phase 4 (Documentation):
  4.1, 4.2, 4.3 can run in parallel
  Should run after all implementation complete
```

### External Dependencies

- Python 3.x with `subprocess`, `time`, `json` modules
- GitHub CLI (`gh`) installed and authenticated
- `click` library for prompts and output
- `pytest` and `unittest.mock` for testing
- Access to GitHub API (for manual testing)
- S3 access (for seeding tests, optional)

## Testing Checklist

Before marking implementation complete, verify:

- [x] All unit tests pass (`pytest tests/test_gh_utils.py tests/test_create_repo_cleanup.py tests/test_create_repo_download_failure_cleanup.py`)
- [x] Manual test: Repository creation succeeds without retries
- [x] Manual test: Retry logic works when `gh repo view` initially fails
- [x] Manual test: Cleanup prompt appears after seeding failure
- [x] Manual test: "y" response deletes repository
- [x] Manual test: "N" response keeps repository
- [x] Manual test: `--cleanup-on-failure` auto-deletes without prompt
- [x] Manual test: Deletion failure is handled gracefully (no crash)
- [x] CodeCommit operations still work (not affected by changes)
- [x] Help text displays correctly (`--help`)
- [x] Version numbers updated in both files (final: `create_repo.py v0.2.3`, `gh_utils.py v0.2.0`)
- [x] CHANGELOG.md entry added

## Rollback Plan

If critical issues are discovered:

1. **Revert Phase 1 only** (keep Phase 2):
   - In `get_repository()`, replace `_retry_gh_command()` call with original `subprocess.run()`
   - Keep stderr logging (harmless improvement)
   - Revert `gh_utils.py` version to v0.1.0

2. **Revert Phase 2 only** (keep Phase 1):
   - Remove call to `_handle_github_seeding_failure()` in `_seed_repository_github()`
   - Keep retry logic (independent improvement)
   - Revert `create_repo.py` version to v0.2.1
   - Also revert the Task 2.7 changes (the wrapper in `create_and_seed_repository()` calls the same handler)

3. **Full revert**:
   - Revert all changes in both files
   - Restore previous VERSION constants
   - Remove CHANGELOG.md entry
   - Remove test files

**Accepted behavior**: If `gh repo view` still fails after all retries following repository creation, the repository is intentionally left in place and no cleanup is offered.

## Success Criteria

Implementation is complete when:

1. All tasks marked complete (checkboxes ticked)
2. All unit tests pass
3. Manual testing confirms expected behavior
4. CHANGELOG.md updated
5. Version numbers updated
6. No regressions in existing functionality
7. Documentation is accurate

## Notes

- **Phase 1** can be deployed independently (retry logic is self-contained)
- **Phase 2** depends on Phase 1 for consistent error handling
- **Phase 3** tests can be written incrementally as each phase completes
- Manual testing requires real GitHub account and repositories
- Consider running tests in a test organization to avoid cluttering main namespace

## Approval

**Tasks Author**: [Generated from design.md]  
**Date**: 2026-11-14  
**Status**: Complete

---

**Completion**: All tasks (1.1 to 4.3, including the Task 2.7 follow-up fix) were implemented and verified on 2026-11-14.
