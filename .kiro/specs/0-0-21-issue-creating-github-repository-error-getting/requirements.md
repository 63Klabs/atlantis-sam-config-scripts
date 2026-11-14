# Requirements: GitHub Repository Creation Error Fix

**Spec**: 0-0-21-issue-creating-github-repository-error-getting  
**Status**: Draft  
**Last Updated**: 2026-11-14

## Overview

This document specifies the requirements for fixing the sporadic `gh repo view` failure that occurs immediately after GitHub repository creation with `create_repo.py`. The fix adds retry logic with exponential backoff, enhanced error logging with stderr capture, and user-prompted cleanup for failed repository seeding.

**Note**: The character encoding error (`'charmap' codec can't encode character '\u2192'`) reported in the November 14 log is out of scope for this spec and will be addressed by issue #10.

## Scope

**In Scope:**
- Retry logic for `gh repo view` failures after repository creation
- Stderr capture and logging for GitHub CLI commands
- User-prompted cleanup for failed GitHub repository seeding
- Optional `--cleanup-on-failure` flag for headless/CI environments

**Out of Scope:**
- File encoding issues during seeding (deferred to issue #10)
- Binary content handling (deferred to issue #11)
- CodeCommit repository operations
- Changes to repository creation logic itself

## Functional Requirements

### FR1: Retry Logic for `gh repo view`

**FR1.1** When `GitHubUtils.get_repository()` calls `gh repo view` and receives a `subprocess.CalledProcessError`, the method SHALL retry the command up to 3 times.

**FR1.2** Retry delays SHALL use exponential backoff: 1 second before the first retry, 2 seconds before the second retry, and 4 seconds before the third retry.

**FR1.3** Each retry attempt SHALL be logged at INFO level with the format: `"Retrying gh repo view (attempt X of 3) after Y second(s)..."` where X is the retry number (1, 2, or 3) and Y is the delay.

**FR1.4** If all retry attempts are exhausted and the command still fails, the method SHALL raise the exception with the original error message.

**FR1.5** Retry logic SHALL only apply to `subprocess.CalledProcessError` exceptions. Other exception types (e.g., `TimeoutError`, `ValueError`) SHALL be raised immediately without retry.

**FR1.6** The first attempt (before any retries) SHALL NOT count toward the retry limit. Total attempts = 1 initial + 3 retries = 4 attempts maximum.

### FR2: Enhanced Error Logging

**FR2.1** When `GitHubUtils.get_repository()` catches a `subprocess.CalledProcessError`, it SHALL log the stderr output (if available) at ERROR level before re-raising the exception.

**FR2.2** The stderr log message SHALL use the format: `"gh repo view stderr: <stderr content>"` where `<stderr content>` is `e.stderr.decode('utf-8', errors='replace')` if stderr is not None, otherwise `"(no stderr)"`.

**FR2.3** User-facing error messages SHALL NOT include raw stderr content. Only the wrapped exception message `"Failed to get repository info: <original error>"` SHALL be raised.

**FR2.4** Debug logging SHALL be added before the `gh repo view` call with the format: `"Calling gh repo view for repository: <repo_name>"`

**FR2.5** Debug logging SHALL be added after a successful `gh repo view` call with the format: `"Successfully retrieved repository info for: <repo_name>"`

### FR3: User-Prompted Cleanup for Failed Seeding

**FR3.1** When GitHub repository seeding fails in `RepositoryCreator._seed_repository_github()`, the method SHALL prompt the user: `"Seeding failed. Delete repository <repo_name>? (y/N): "`

**FR3.2** The prompt SHALL default to "N" (do not delete) when the user presses Enter without typing a response.

**FR3.3** If the user responds with "y" or "Y" (case-insensitive), the method SHALL:
- Call `gh repo delete <repo_name> --yes` to delete the repository
- Log at INFO level: `"Deleted failed repository: <repo_name>"`
- Display a success message: `"Repository <repo_name> deleted."`

**FR3.4** If the user responds with "n", "N", or any other input (or presses Enter), the method SHALL:
- Log at INFO level: `"Repository <repo_name> was not deleted."`
- Display a message: `"Repository <repo_name> was not deleted. You can delete it manually with: gh repo delete <repo_name>"`

**FR3.5** If repository deletion fails, the method SHALL:
- Log at ERROR level: `"Failed to delete repository <repo_name>: <error>"`
- Display an error message: `"Failed to delete repository. You may need to delete it manually."`
- NOT raise an exception (seeding already failed; deletion failure is secondary)

### FR4: Headless Cleanup Flag

**FR4.1** The `create_repo.py` script SHALL accept a new optional flag: `--cleanup-on-failure`

**FR4.2** When `--cleanup-on-failure` is provided, failed repository seeding SHALL automatically delete the repository WITHOUT prompting the user.

**FR4.3** Automatic deletion SHALL log at INFO level: `"Auto-deleting failed repository (--cleanup-on-failure): <repo_name>"`

**FR4.4** The `--cleanup-on-failure` flag SHALL only affect GitHub repository cleanup. CodeCommit cleanup behavior (which already deletes on failure) SHALL remain unchanged.

**FR4.5** The flag's help text SHALL be: `"Automatically delete GitHub repository if seeding fails (no prompt)"`

### FR5: Comprehensive Stderr Logging

**FR5.1** All `subprocess.run()` calls in `gh_utils.py` that invoke `gh` CLI commands SHALL capture stderr by ensuring `capture_output=True` or explicit `stderr=subprocess.PIPE`.

**FR5.2** When a `subprocess.CalledProcessError` is caught in any `gh_utils.py` method, stderr SHALL be logged at ERROR level using the format: `"<method_name> stderr: <stderr content>"` where `<method_name>` is the GitHub CLI operation (e.g., "gh repo create", "gh repo clone").

**FR5.3** Stderr logging SHALL use `e.stderr.decode('utf-8', errors='replace')` to handle non-UTF-8 stderr output gracefully.

**FR5.4** Methods affected (minimum list):
- `GitHubUtils.get_repository()`
- `GitHubUtils.create_repo()`
- `GitHubUtils.create_branch_structure()`
- `GitHubUtils.create_init_commit()`
- `GitHubUtils.merge_branches_fast_forward()`

## Non-Functional Requirements

### NFR1: Performance

**NFR1.1** Retry logic SHALL add a maximum of 7 seconds total delay (1 + 2 + 4) when all retries are needed.

**NFR1.2** The first `gh repo view` attempt SHALL have no added delay.

**NFR1.3** If the first or any retry attempt succeeds, subsequent retries SHALL be skipped.

### NFR2: Backward Compatibility

**NFR2.1** Existing behavior of `create_repo.py` SHALL remain unchanged when `--cleanup-on-failure` is NOT provided (user is prompted).

**NFR2.2** The retry logic SHALL be transparent to callers of `GitHubUtils.get_repository()`. The method signature and return type SHALL NOT change.

**NFR2.3** CodeCommit repository creation and seeding SHALL NOT be affected by any changes.

### NFR3: Logging

**NFR3.1** All new log messages SHALL use the existing `Log` utility from `lib.logger`.

**NFR3.2** Log levels SHALL follow the existing convention:
- INFO: Normal operations, retry attempts, cleanup decisions
- ERROR: Command failures, stderr output, deletion failures
- DEBUG: Detailed timing and state information

**NFR3.3** Log messages SHALL NOT contain secrets, credentials, or personally identifiable information.

### NFR4: User Experience

**NFR4.1** User-facing error messages SHALL remain concise and actionable. Raw stderr SHALL NOT be displayed to users.

**NFR4.2** Retry attempts SHALL be visible to users via console output (using `click.echo()` or similar) to indicate the script is still working and has not hung.

**NFR4.3** The cleanup prompt SHALL clearly indicate the default choice ("N") and the consequences of each option.

## Error Handling

### EH1: Retry Exhaustion

When all retry attempts are exhausted:
- Log at ERROR level: `"gh repo view failed after 4 attempts (1 initial + 3 retries) for repository: <repo_name>"`
- Log the last stderr at ERROR level
- Re-raise the original `CalledProcessError` wrapped in an `Exception` with message: `"Failed to get repository info: <original error>"`

### EH2: Repository Deletion Failure

When repository deletion fails after a seeding failure:
- Log at ERROR level with stderr if available
- Display user-friendly message with manual deletion command
- Do NOT raise an exception (seeding failure is the primary error)

### EH3: Prompt Input Error

When reading user input for the cleanup prompt fails (e.g., `EOFError` in non-interactive environments):
- Default to "N" (do not delete)
- Log at WARNING level: `"Failed to read user input for cleanup prompt, defaulting to 'N' (do not delete)"`

### EH4: Non-GitHub Provider

Retry logic and GitHub-specific cleanup SHALL only apply when `self.provider == 'github'`. CodeCommit operations SHALL be unaffected.

## Acceptance Criteria

### AC1: Retry Logic

- [ ] `gh repo view` is retried up to 3 times with 1s, 2s, 4s delays
- [ ] Retry attempts are logged at INFO level
- [ ] Retries only occur for `CalledProcessError`, not other exception types
- [ ] Successful retry stops further attempts
- [ ] Exhausted retries log at ERROR level and re-raise the exception

### AC2: Stderr Logging

- [ ] Stderr is logged at ERROR level for all failed `gh` CLI commands
- [ ] Stderr is decoded with `errors='replace'` to handle non-UTF-8
- [ ] User-facing error messages do not include raw stderr
- [ ] Debug logs are added before and after `gh repo view` calls

### AC3: Cleanup Prompt

- [ ] User is prompted after GitHub seeding failure: `"Seeding failed. Delete repository <repo_name>? (y/N): "`
- [ ] Prompt defaults to "N" when user presses Enter
- [ ] Responding "y" or "Y" deletes the repository and logs/displays success
- [ ] Responding "n", "N", or other input does not delete and shows manual deletion command
- [ ] Deletion failure logs at ERROR level but does not raise exception

### AC4: Headless Flag

- [ ] `--cleanup-on-failure` flag is accepted by `create_repo.py`
- [ ] With flag, failed repositories are deleted without prompting
- [ ] Auto-deletion is logged at INFO level
- [ ] Flag only affects GitHub, not CodeCommit
- [ ] Help text describes the flag's purpose

### AC5: Comprehensive Stderr Logging

- [ ] All `gh` CLI commands in `gh_utils.py` capture stderr
- [ ] Failed commands log stderr at ERROR level
- [ ] Methods in FR5.4 list are updated

### AC6: Non-Functional

- [ ] Maximum retry delay is 7 seconds
- [ ] Existing `create_repo.py` behavior unchanged without `--cleanup-on-failure`
- [ ] `get_repository()` method signature unchanged
- [ ] CodeCommit operations unaffected
- [ ] All logs use `Log` utility with correct levels
- [ ] No secrets or PII in logs
- [ ] User-facing messages remain concise

## Dependencies

### Internal Dependencies

- `cli/create_repo.py` (RepositoryCreator class)
- `cli/lib/gh_utils.py` (GitHubUtils class)
- `cli/lib/logger.py` (Log utility)
- `cli/lib/tools.py` (Colorize utility for user messages)

### External Dependencies

- GitHub CLI (`gh`) must be installed and authenticated
- Python `subprocess` module
- Python `time` module (for retry delays)

### Related Issues

- Issue #1: This issue (source of requirements)
- Issue #10: Character encoding fix for file seeding (deferred, out of scope)
- Issue #11: Binary content handling (deferred, out of scope)

## Test Requirements

### Unit Tests

**UT1: Retry Logic**
- Test `get_repository()` retries 3 times on `CalledProcessError`
- Test successful retry stops further attempts
- Test non-`CalledProcessError` exceptions are not retried
- Test retry delays are 1s, 2s, 4s (using time mocks)
- Test error logging after exhausted retries

**UT2: Stderr Logging**
- Test stderr is logged when `gh repo view` fails
- Test stderr is decoded with `errors='replace'`
- Test user-facing error message does not contain raw stderr

**UT3: Cleanup Prompt**
- Test prompt is shown after seeding failure
- Test "y" response deletes repository
- Test "N" or Enter response does not delete
- Test deletion failure is logged but does not raise exception
- Test `EOFError` defaults to "N"

**UT4: Headless Flag**
- Test `--cleanup-on-failure` enables auto-deletion
- Test auto-deletion skips prompt
- Test auto-deletion logs correctly

### Integration Tests (Optional)

**IT1: End-to-End Repository Creation**
- Create a GitHub repository with `create_repo.py`
- Verify retry logic is invoked if `gh repo view` initially fails (simulated)
- Verify repository is created and seeded successfully after retry

**IT2: Failed Seeding Cleanup**
- Trigger a seeding failure (e.g., invalid starter URL)
- Respond "y" to cleanup prompt
- Verify repository is deleted
- Trigger a seeding failure again
- Respond "N" to cleanup prompt
- Verify repository is NOT deleted

## Documentation Requirements

### Code Documentation

**CD1**: Add docstring to new retry helper method (if extracted) documenting:
- Purpose (retry with exponential backoff)
- Parameters (callable, max_retries, delays)
- Return value
- Exceptions raised

**CD2**: Update `GitHubUtils.get_repository()` docstring to mention retry behavior:
```python
"""
Get information about a GitHub repository using the GitHub CLI.

Retries up to 3 times with exponential backoff (1s, 2s, 4s) if the
command fails with a subprocess error. Logs stderr for failed attempts.

Args:
    repo_name (str): Repository name (e.g., "owner/repo")

Returns:
    Dict[str, str]: Dictionary containing 'exists' and 'repositoryMetadata' keys

Raises:
    Exception: When gh repo view fails after all retry attempts
"""
```

**CD3**: Update `RepositoryCreator._seed_repository_github()` docstring to mention cleanup prompt.

**CD4**: Add docstring for `--cleanup-on-failure` flag in argument parser help.

### User Documentation

**UD1**: Update script help output (`create_repo.py -h`) to include `--cleanup-on-failure` flag.

**UD2**: (Optional) Add a troubleshooting section to README.md or documentation mentioning:
- `gh repo view` may fail immediately after creation due to GitHub API propagation delay
- Script automatically retries up to 3 times
- Users can check logs for detailed stderr output if creation fails

## Version Updates

**V1**: Update `cli/lib/gh_utils.py` VERSION constant:
- Current: `v0.1.0/2026-07-24`
- New: `v0.2.0/YYYY-MM-DD` (where YYYY-MM-DD is implementation date)
- Rationale: New public behavior (retry logic is observable to callers via timing)

**V2**: Update `cli/create_repo.py` VERSION constant:
- Current: `v0.2.1/2026-11-13`
- New: `v0.2.2/YYYY-MM-DD` (where YYYY-MM-DD is implementation date)
- Rationale: PATCH - backward-compatible fix (retry logic and cleanup prompt)

## Success Metrics

**SM1**: Reduction in `gh repo view` failures reported by users after retry logic is deployed.

**SM2**: Improved error logs include stderr output, enabling faster diagnosis of GitHub CLI issues.

**SM3**: Fewer orphaned GitHub repositories after failed seeding (due to cleanup prompt or auto-cleanup flag).

## Open Questions

_None. All questions were resolved during planning phase._

## Approval

**Requirements Author**: [Generated from locked PLAN.md]  
**Date**: 2026-11-14  
**Status**: Draft - Pending Review

---

**Next Steps**: Proceed to design.md to specify implementation details (method signatures, retry helper structure, test fixtures).
