# Design: GitHub Repository Creation Error Fix

**Spec**: 0-0-21-issue-creating-github-repository-error-getting  
**Status**: Draft  
**Last Updated**: 2026-11-14

## Overview

This document specifies the implementation design for adding retry logic, enhanced error logging, and user-prompted cleanup to GitHub repository creation in `create_repo.py`. The design minimizes changes to existing code structure while adding robust error handling for transient `gh repo view` failures.

## Architecture

### Component Overview

```
create_repo.py (RepositoryCreator)
    │
    ├── __init__() 
    │   └── New: parse --cleanup-on-failure flag
    │
    ├── _create_repository_github()
    │   └── calls get_repository() [retry logic inside]
    │
    └── _seed_repository_github()
        └── New: cleanup prompt or auto-delete on failure

gh_utils.py (GitHubUtils)
    │
    ├── get_repository()
    │   ├── New: _retry_gh_command() helper
    │   └── New: stderr logging
    │
    └── [other methods]
        └── New: stderr logging in exception handlers
```

### Data Flow

```
User runs: ./cli/create_repo.py owner/repo --provider github [--cleanup-on-failure]
    │
    ▼
RepositoryCreator.__init__()
    │ Parse args, store cleanup_on_failure flag
    │
    ▼
_create_repository_github()
    │ GitHubUtils.create_repo() → repository created
    │
    ▼
get_repository() → FAILS with CalledProcessError
    │
    ▼
_retry_gh_command()
    │ Attempt 1: sleep 1s, retry
    │ Attempt 2: sleep 2s, retry
    │ Attempt 3: sleep 4s, retry
    │ All attempts exhausted
    │
    ▼
Log stderr, re-raise exception
    │
    ▼
_create_repository_github() catches, logs, exits
    │
    OR (if seeding path)
    │
    ▼
_seed_repository_github() → FAILS
    │
    ▼
if cleanup_on_failure:
    │ Auto-delete repository
    │
else:
    │ Prompt user: "Delete repository? (y/N)"
    │ ├─ y: delete
    │ └─ N: keep
    │
    ▼
Exit with error code
```

## Detailed Design

### 1. Retry Logic Helper (`gh_utils.py`)

#### New Method: `_retry_gh_command()`

```python
@staticmethod
def _retry_gh_command(command: List[str], max_retries: int = 3) -> subprocess.CompletedProcess:
    """Execute a GitHub CLI command with retry logic and exponential backoff.
    
    Retries the command up to max_retries times if it fails with a
    CalledProcessError. Uses exponential backoff delays: 1s, 2s, 4s.
    
    Args:
        command: GitHub CLI command as a list (e.g., ["gh", "repo", "view", "owner/repo"])
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        subprocess.CompletedProcess: The successful command result
    
    Raises:
        subprocess.CalledProcessError: If all retry attempts are exhausted
        
    Example:
        >>> result = GitHubUtils._retry_gh_command(
        ...     ["gh", "repo", "view", "owner/repo", "--json", "name"],
        ...     max_retries=3
        ... )
    """
    import time
    from lib.logger import Log
    
    delays = [1, 2, 4]  # Exponential backoff delays in seconds
    last_error = None
    
    # Initial attempt (not counted as a retry)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        return result
    except subprocess.CalledProcessError as e:
        last_error = e
        # Log stderr from initial attempt
        stderr_text = e.stderr if e.stderr else "(no stderr)"
        Log.error(f"gh command failed (initial attempt): {' '.join(command)}")
        Log.error(f"gh command stderr: {stderr_text}")
    
    # Retry attempts
    for attempt in range(1, max_retries + 1):
        delay = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
        
        Log.info(f"Retrying gh command (attempt {attempt} of {max_retries}) after {delay} second(s)...")
        time.sleep(delay)
        
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )
            Log.info(f"gh command succeeded on retry attempt {attempt}")
            return result
        except subprocess.CalledProcessError as e:
            last_error = e
            stderr_text = e.stderr if e.stderr else "(no stderr)"
            Log.error(f"gh command failed (attempt {attempt} of {max_retries}): {' '.join(command)}")
            Log.error(f"gh command stderr: {stderr_text}")
    
    # All retries exhausted
    repo_name = command[3] if len(command) > 3 else "unknown"
    Log.error(f"gh command failed after {max_retries + 1} attempts (1 initial + {max_retries} retries) for repository: {repo_name}")
    raise last_error
```

**Design Rationale:**
- Static method keeps it reusable for other GitHub CLI commands
- Accepts `command` as a list to avoid shell injection
- Returns `CompletedProcess` on success for flexibility
- Logs each attempt with clear retry count
- Re-raises original exception after exhaustion for existing error handling

#### Updated Method: `get_repository()`

```python
@staticmethod
def get_repository(repo_name: str) -> Dict[str, str]:
    """Get information about a GitHub repository using the GitHub CLI.
    
    Retries up to 3 times with exponential backoff (1s, 2s, 4s) if the
    command fails with a subprocess error. Logs stderr for failed attempts.
    
    Args:
        repo_name: Repository name (e.g., "owner/repo")
    
    Returns:
        Dictionary containing 'exists' and 'repositoryMetadata' keys
    
    Raises:
        Exception: When gh repo view fails after all retry attempts
        
    Example:
        >>> info = GitHubUtils.get_repository("owner/repo")
        >>> print(info['repositoryMetadata']['url'])
    """
    from lib.logger import Log
    
    Log.debug(f"Calling gh repo view for repository: {repo_name}")
    
    try:
        result = GitHubUtils._retry_gh_command([
            "gh", "repo", "view", repo_name, "--json",
            "name,nameWithOwner,owner,repositoryTopics,sshUrl,isTemplate,templateRepository,visibility,url"
        ])
        
        Log.debug(f"Successfully retrieved repository info for: {repo_name}")
        
        info = json.loads(result.stdout)
        info["cloneUrlHttp"] = f"{info.get('url')}.git"
        info["cloneUrlSsh"] = f"{info.get('sshUrl')}"
        
        return {
            "exists": True,
            "repositoryMetadata": info
        }
    except subprocess.CalledProcessError as e:
        # Stderr already logged by _retry_gh_command
        raise Exception(f"Failed to get repository info: {e}")
    except Exception as e:
        # Non-CalledProcessError exceptions (JSON parse, etc.)
        Log.error(f"Unexpected error in get_repository: {e}")
        raise Exception(f"Failed to get repository info: {str(e)}")
```

**Changes from current implementation:**
- Replace direct `subprocess.run()` with `_retry_gh_command()`
- Add debug logging before and after the call
- Stderr logging moved into `_retry_gh_command()` (no duplication)
- Exception wrapping remains the same for backward compatibility

### 2. Cleanup Prompt (`create_repo.py`)

#### Updated: `RepositoryCreator.__init__()`

Add new parameter and instance variable:

```python
def __init__(
    self,
    repo_name: str,
    source: Optional[str] = None,
    region: Optional[str] = None,
    profile: Optional[str] = None,
    prefix: Optional[str] = None,
    provider: Optional[str] = None,
    no_browser: Optional[bool] = False,
    skip_test_merge: Optional[bool] = False,
    cleanup_on_failure: Optional[bool] = False  # NEW
) -> None:
    # ... existing initialization ...
    self.cleanup_on_failure = cleanup_on_failure  # NEW
```

#### Updated: `_seed_repository_github()`

Add cleanup logic in the exception handler:

```python
def _seed_repository_github(self, temp_dir):
    try:
        # ... existing seeding logic ...
        
    except Exception as e:
        click.echo(Colorize.error(f"Error in seeding process. Check logs for more information."))
        Log.error(f"Error in seeding process: {str(e)}")
        
        # NEW: Cleanup prompt or auto-delete
        self._handle_github_seeding_failure()
        
        sys.exit(1)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
```

#### New Method: `_handle_github_seeding_failure()`

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

#### New Method: `_delete_github_repository()`

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

**Design Rationale:**
- Separate method for deletion allows reuse and testing
- Best-effort deletion (no exception raised) since seeding already failed
- Provides manual deletion command if automatic deletion fails
- Handles `EOFError` for non-interactive environments

### 3. Command-Line Flag (`create_repo.py`)

#### Updated: Argument Parser

Add new flag in the argument parser section (after `--skip-test-merge`):

```python
parser.add_argument(
    '--cleanup-on-failure',
    action='store_true',
    default=False,
    help='Automatically delete GitHub repository if seeding fails (no prompt)'
)
```

#### Updated: RepositoryCreator Instantiation

Pass the new flag to the constructor:

```python
creator = RepositoryCreator(
    repo_name=args.repo_name,
    source=args.source,
    region=args.region,
    profile=args.profile,
    prefix=args.prefix,
    provider=args.provider,
    no_browser=args.no_browser,
    skip_test_merge=args.skip_test_merge,
    cleanup_on_failure=args.cleanup_on_failure  # NEW
)
```

### 4. Comprehensive Stderr Logging (`gh_utils.py`)

Update all methods that call `gh` CLI to log stderr on failure. The pattern:

```python
except subprocess.CalledProcessError as e:
    stderr_text = e.stderr if e.stderr else "(no stderr)"
    Log.error(f"<method_name> stderr: {stderr_text}")
    raise Exception(f"<user-friendly message>: {e}")
```

#### Methods to Update

**`create_repo()`**
```python
@staticmethod
def create_repo(repo_name: str, private: bool = True, description: str = None) -> Dict:
    """Create a GitHub repository using the GitHub CLI.
    
    Args:
        repo_name: Repository name
        private: Whether the repository should be private
        description: Repository description
    
    Returns:
        True if repository was created successfully
        
    Raises:
        Exception: If the repository creation fails
    """
    try:
        cmd = ["gh", "repo", "create", repo_name]
        if private:
            cmd.append("--private")
        else:
            cmd.append("--public")
        if description:
            cmd.extend(["--description", description])
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr if e.stderr else "(no stderr)"
        Log.error(f"gh repo create stderr: {stderr_text}")
        raise Exception(f"Failed to create repository: {e.stderr}")
    except Exception as e:
        raise Exception(f"Failed to create repository: {e}")
```

**`create_branch_structure()`** (similar pattern)
```python
# Add stderr logging in the existing exception handler:
except subprocess.CalledProcessError as e:
    stderr_text = e.stderr if e.stderr else "(no stderr)"
    Log.error(f"gh repo clone stderr: {stderr_text}")
    raise Exception(f"Failed to create branch structure: {e}")
# ... similar for each subprocess.run() call in the method
```

**`create_init_commit()`** (similar pattern)
```python
except subprocess.CalledProcessError as e:
    stderr_text = e.stderr if e.stderr else "(no stderr)"
    Log.error(f"git command stderr: {stderr_text}")
    raise Exception(f"Error in GitHub CLI command: {e.cmd}\nError: {stderr_text}")
```

**`merge_branches_fast_forward()`** (similar pattern)
```python
except subprocess.CalledProcessError as e:
    stderr_text = e.stderr if e.stderr else "(no stderr)"
    Log.error(f"git merge stderr: {stderr_text}")
    raise Exception(f"Failed to merge branches: {stderr_text}")
```

**Design Rationale:**
- Consistent error logging pattern across all methods
- Stderr always logged at ERROR level when available
- User-facing error messages remain concise (stderr in logs only)
- `errors='replace'` not needed since we're using `text=True` in `subprocess.run()`

### 5. Version Updates

#### `gh_utils.py`

```python
VERSION = "v0.2.0/2026-11-14"
```

**Rationale**: MINOR version bump because retry logic changes observable behavior (timing, log output).

#### `create_repo.py`

```python
VERSION = "v0.2.2/2026-11-14"
```

**Rationale**: PATCH version bump because cleanup prompt is a backward-compatible fix (only affects error path).

## File Changes Summary

| File | Changes | LOC Added | LOC Removed |
|------|---------|-----------|-------------|
| `cli/lib/gh_utils.py` | Add `_retry_gh_command()`, update `get_repository()`, add stderr logging | ~100 | ~15 |
| `cli/create_repo.py` | Add `--cleanup-on-failure` flag, `_handle_github_seeding_failure()`, `_delete_github_repository()`, update `__init__()` and `_seed_repository_github()` | ~80 | ~5 |
| **Total** | | ~180 | ~20 |

## Error Handling Strategy

### Retry Logic

| Scenario | Behavior |
|----------|----------|
| `gh repo view` succeeds on first attempt | No retries, immediate return |
| `gh repo view` fails with `CalledProcessError` | Retry 3 times with 1s, 2s, 4s delays |
| Retry succeeds on attempt 2 | Stop retrying, return success |
| All retries exhausted | Log error, re-raise `CalledProcessError` |
| Non-`CalledProcessError` exception (e.g., JSON parse error) | No retry, immediate re-raise |

### Cleanup Prompt

| Scenario | Behavior |
|----------|----------|
| User responds "y" or "Y" | Delete repository, log success |
| User responds "n", "N", or Enter | Keep repository, show manual deletion command |
| User input fails (`EOFError`) | Default to "N", log warning |
| `--cleanup-on-failure` flag provided | Skip prompt, auto-delete |
| Deletion fails | Log error, show manual command, do NOT raise exception |

### Stderr Logging

| Scenario | Behavior |
|----------|----------|
| `gh` command succeeds | No stderr logged |
| `gh` command fails with stderr | Log stderr at ERROR level |
| `gh` command fails without stderr | Log "(no stderr)" |
| Non-interactive environment | Logs are the primary diagnostic source |

## Testing Strategy

### Unit Test Fixtures

**`test_gh_utils.py`**

```python
import pytest
from unittest.mock import patch, MagicMock
import subprocess
from cli.lib.gh_utils import GitHubUtils

class TestRetryLogic:
    """Tests for _retry_gh_command retry logic."""
    
    @patch('subprocess.run')
    @patch('time.sleep')
    def test_success_on_first_attempt(self, mock_sleep, mock_run):
        """Should not retry when first attempt succeeds."""
        mock_run.return_value = MagicMock(returncode=0, stdout='{"name": "repo"}', stderr='')
        
        result = GitHubUtils._retry_gh_command(["gh", "repo", "view", "owner/repo"])
        
        assert mock_run.call_count == 1
        assert mock_sleep.call_count == 0
    
    @patch('subprocess.run')
    @patch('time.sleep')
    def test_success_on_retry(self, mock_sleep, mock_run):
        """Should retry and succeed on second attempt."""
        # First call fails, second call succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'gh', stderr='error'),
            MagicMock(returncode=0, stdout='{"name": "repo"}', stderr='')
        ]
        
        result = GitHubUtils._retry_gh_command(["gh", "repo", "view", "owner/repo"])
        
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(1)  # First retry delay
    
    @patch('subprocess.run')
    @patch('time.sleep')
    def test_all_retries_exhausted(self, mock_sleep, mock_run):
        """Should raise after all retries are exhausted."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'gh', stderr='error')
        
        with pytest.raises(subprocess.CalledProcessError):
            GitHubUtils._retry_gh_command(["gh", "repo", "view", "owner/repo"])
        
        assert mock_run.call_count == 4  # 1 initial + 3 retries
        assert mock_sleep.call_count == 3
        # Verify exponential backoff delays
        assert mock_sleep.call_args_list[0][0][0] == 1
        assert mock_sleep.call_args_list[1][0][0] == 2
        assert mock_sleep.call_args_list[2][0][0] == 4
    
    @patch('subprocess.run')
    def test_non_calledprocesserror_not_retried(self, mock_run):
        """Should not retry non-CalledProcessError exceptions."""
        mock_run.side_effect = ValueError("Invalid JSON")
        
        with pytest.raises(ValueError):
            GitHubUtils._retry_gh_command(["gh", "repo", "view", "owner/repo"])
        
        assert mock_run.call_count == 1  # No retries
```

**`test_create_repo.py`**

```python
import pytest
from unittest.mock import patch, MagicMock, call
from cli.create_repo import RepositoryCreator

class TestCleanupPrompt:
    """Tests for GitHub seeding failure cleanup."""
    
    @patch('click.prompt')
    @patch('subprocess.run')
    def test_user_confirms_deletion(self, mock_run, mock_prompt):
        """Should delete repository when user responds 'y'."""
        mock_prompt.return_value = 'y'
        mock_run.return_value = MagicMock(returncode=0)
        
        creator = RepositoryCreator(
            repo_name='owner/repo',
            provider='github',
            cleanup_on_failure=False
        )
        creator._handle_github_seeding_failure()
        
        # Verify gh repo delete was called
        mock_run.assert_called_once_with(
            ["gh", "repo", "delete", "owner/repo", "--yes"],
            check=True,
            capture_output=True,
            text=True
        )
    
    @patch('click.prompt')
    @patch('subprocess.run')
    def test_user_declines_deletion(self, mock_run, mock_prompt):
        """Should not delete repository when user responds 'N'."""
        mock_prompt.return_value = 'N'
        
        creator = RepositoryCreator(
            repo_name='owner/repo',
            provider='github',
            cleanup_on_failure=False
        )
        creator._handle_github_seeding_failure()
        
        # Verify gh repo delete was NOT called
        mock_run.assert_not_called()
    
    @patch('subprocess.run')
    def test_auto_delete_with_flag(self, mock_run):
        """Should auto-delete without prompting when flag is set."""
        mock_run.return_value = MagicMock(returncode=0)
        
        creator = RepositoryCreator(
            repo_name='owner/repo',
            provider='github',
            cleanup_on_failure=True
        )
        creator._handle_github_seeding_failure()
        
        # Verify deletion happened without prompt
        mock_run.assert_called_once()
    
    @patch('click.prompt')
    @patch('subprocess.run')
    def test_deletion_failure_handled_gracefully(self, mock_run, mock_prompt):
        """Should log error but not raise when deletion fails."""
        mock_prompt.return_value = 'y'
        mock_run.side_effect = subprocess.CalledProcessError(1, 'gh', stderr='error')
        
        creator = RepositoryCreator(
            repo_name='owner/repo',
            provider='github',
            cleanup_on_failure=False
        )
        
        # Should not raise exception
        creator._handle_github_seeding_failure()
    
    @patch('click.prompt')
    def test_eoferror_defaults_to_no(self, mock_prompt):
        """Should default to 'N' when EOFError occurs (non-interactive)."""
        mock_prompt.side_effect = EOFError()
        
        creator = RepositoryCreator(
            repo_name='owner/repo',
            provider='github',
            cleanup_on_failure=False
        )
        
        # Should not raise exception
        creator._handle_github_seeding_failure()
```

### Integration Test Scenarios

**Scenario 1: Successful retry**
1. Mock `gh repo view` to fail twice, then succeed
2. Run `create_repo.py owner/repo --provider github`
3. Verify repository is created
4. Verify logs show 2 retry attempts
5. Verify total time is approximately 3 seconds (1s + 2s delays)

**Scenario 2: Cleanup prompt - user confirms**
1. Mock repository creation to succeed, seeding to fail
2. Mock user input to respond "y"
3. Run `create_repo.py owner/repo --provider github`
4. Verify `gh repo delete` was called
5. Verify logs show deletion confirmation

**Scenario 3: Cleanup flag - auto-delete**
1. Mock repository creation to succeed, seeding to fail
2. Run `create_repo.py owner/repo --provider github --cleanup-on-failure`
3. Verify `gh repo delete` was called without prompt
4. Verify logs show auto-deletion

## Performance Considerations

### Timing Analysis

| Scenario | Time Added |
|----------|------------|
| Success on first attempt | 0ms (no change) |
| Success on first retry | ~1000ms (1s delay) |
| Success on second retry | ~3000ms (1s + 2s) |
| Success on third retry | ~7000ms (1s + 2s + 4s) |
| All retries exhausted | ~7000ms (same) |

### Memory Impact

- Retry logic adds minimal memory overhead (function stack, delay counter)
- Stderr capture already exists in current code (`capture_output=True`)
- Prompt adds one string variable for user input
- Overall memory impact: negligible

### Network Impact

- Retry logic makes up to 4 total requests to GitHub API (1 initial + 3 retries)
- This is well within GitHub API rate limits for authenticated requests (5000/hour)
- No bulk operations or parallel requests

## Security Considerations

### Command Injection

- All `subprocess.run()` calls use list format, not shell strings
- Repository names are validated before use
- No risk of command injection

### Information Disclosure

- Stderr may contain GitHub API error messages (e.g., rate limits, authentication errors)
- Stderr is logged but NOT displayed to users
- Log files should be secured per standard practices

### Authentication

- `gh` CLI authentication is validated before script runs
- Script does not handle credentials directly
- Retry logic does not affect authentication flow

## Backward Compatibility

### API Compatibility

- `GitHubUtils.get_repository()` signature unchanged
- `RepositoryCreator.__init__()` adds optional parameter with default value
- Existing callers work without modification

### Behavioral Compatibility

- Without `--cleanup-on-failure`, behavior is unchanged (user is prompted)
- Retry logic is transparent to callers (same result, just takes longer on failure)
- CodeCommit operations completely unaffected

### Configuration Compatibility

- No configuration files are modified
- No environment variables added
- Command-line flag is optional

## Rollback Plan

If issues are discovered after deployment:

1. **Revert retry logic**: Change `get_repository()` to call `subprocess.run()` directly instead of `_retry_gh_command()`
2. **Revert cleanup prompt**: Remove call to `_handle_github_seeding_failure()` in `_seed_repository_github()`
3. **Revert version numbers**: Restore previous VERSION constants
4. **Keep stderr logging**: This is a pure improvement with no side effects

## Future Enhancements

**Out of scope for this spec, but noted for future consideration:**

- Make retry count and delays configurable via environment variables
- Add telemetry/metrics for retry success rates
- Extend retry logic to other GitHub CLI commands (e.g., `gh repo create`)
- Add `--no-retry` flag to disable retry logic for debugging

## Documentation Updates

### Code Comments

All new methods include comprehensive docstrings (see method signatures above).

### README.md (Optional)

Consider adding a troubleshooting section:

```markdown
## Troubleshooting

### Repository Creation Fails with "Failed to get repository info"

The script automatically retries up to 3 times if `gh repo view` fails immediately 
after repository creation. This is typically caused by GitHub API propagation delay.

If the error persists after retries:
1. Check your GitHub CLI authentication: `gh auth status`
2. Verify the repository exists: `gh repo view owner/repo`
3. Check logs for detailed stderr output

### Seeding Failures

If repository seeding fails, you will be prompted to delete the repository.
- Respond `y` to delete the repository and start over
- Respond `N` to keep the repository for manual inspection

For automated/CI environments, use `--cleanup-on-failure` to automatically 
delete failed repositories without prompting.
```

## Approval

**Design Author**: [Generated from requirements.md]  
**Date**: 2026-11-14  
**Status**: Draft - Pending Review

---

**Next Steps**: Proceed to tasks.md to break down implementation into atomic work items.
