# GitHub Repository Creation Error - "Failed to get repository info"

> **Status**: Locked on 2026-11-14
> **Issue**: [ISSUE.md](ISSUE.md)
> **Reviewed against**: dev at 5abe0ef on 2026-11-14

## 1. Summary

Users attempting to create GitHub repositories with `create_repo.py` encounter one of two errors: (1) `Failed to get repository info` immediately after repository creation, which occurs when the `gh repo view` call in `GitHubUtils.get_repository()` fails, or (2) `'charmap' codec can't encode character '\u2192'` during file seeding on Windows, which occurs when UTF-8 content is written without explicit encoding. The first error blocks repository creation entirely. The second error aborts seeding after the repository and branch structure are already created, leaving a partially seeded repository. Both errors occur on Windows (Git Bash) and are traced to the November 13-14, 2026 logs. The first error is sporadic and its root cause is unconfirmed. The second error is deterministic when a starter contains non-ASCII UTF-8 characters and overlaps with issues #10 and #11.

Recommended fix: investigate and harden the `gh repo view` error path, and address the encoding issue by writing files with explicit `encoding='utf-8'` and `newline=''` (the same fix proposed for #10).

## 2. Assessment of the issue

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | `gh repo view` returned non-zero exit status 1 after repository creation | Confirmed | `cli/create_repo.py:410`, called after `create_repo` succeeds at line 405; error message matches stack trace format from `GitHubUtils.get_repository()` at `cli/lib/gh_utils.py:279-291` |
| 2 | Error is "Failed to get repository info" | Confirmed | Error message constructed at `cli/lib/gh_utils.py:290`: `raise Exception(f"Failed to get repository info: {str(e)}")`, wrapped by `create_repo.py:1103` |
| 3 | Occurred on 2026-04-05 20:33:08 and 2026-11-14 11:49:01 | Confirmed as reported | Timestamps in ISSUE.md logs; no verification of actual execution |
| 4 | `charmap` codec error during seeding on Windows | Confirmed as overlapping with #10 | Error matches Windows default encoding; `cli/lib/gh_utils.py:377` opens files with `'w'` and no `encoding` argument, which uses locale default (cp1252 on Windows) |
| 5 | Character `\u2192` (rightward arrow) cannot be encoded in cp1252 | Confirmed | Unicode U+2192 is not in Windows-1252 code page; would raise `UnicodeEncodeError` when writing |
| 6 | Error occurred at position 8396 in a file | Unverifiable by reading | Position is in the file content; requires runtime inspection of the specific starter |
| 7 | Repository was successfully created before the encoding error | Confirmed | Log shows "GitHub Repository created" at 11:49:01.784, then seeding started, then encoding error at 11:49:10.182 |
| 8 | Issue is "unknown if specific or widespread" | Needs runtime verification | Only two instances reported; unclear whether this is environment-specific, intermittent GitHub API issue, or race condition |

## 3. Current state

### Repository creation flow (GitHub)

1. `RepositoryCreator._create_repository_github()` (`cli/create_repo.py:403-425`)
   - Calls `GitHubUtils.create_repo(self.repo_name, True, "asdf")` at line 405
   - If successful, calls `self.get_repository()` at line 410 to fetch metadata
   - Returns response or exits on error

2. `RepositoryCreator.get_repository()` (`cli/create_repo.py:1093-1104`)
   - Delegates to `GitHubUtils.get_repository(self.repo_name)` for GitHub provider
   - Logs and re-raises any exception

3. `GitHubUtils.get_repository()` (`cli/lib/gh_utils.py:266-291`)
   - Executes `gh repo view <repo> --json name,nameWithOwner,...`
   - Parses JSON output on success
   - Wraps any exception (including `subprocess.CalledProcessError`) as `Exception(f"Failed to get repository info: {str(e)}")`

### File seeding flow (GitHub)

1. `RepositoryCreator._seed_repository_github()` (`cli/create_repo.py:814-841`)
   - Collects files via `_seed_collect_files(temp_dir)` (reads as bytes, decodes UTF-8 or base64-encodes)
   - Calls `GitHubUtils.create_init_commit(...)` at line 829

2. `GitHubUtils.create_init_commit()` (`cli/lib/gh_utils.py:338-412`)
   - Clones repository, configures git, checks out seed branch
   - Writes each file with `open(full_path, 'w' if isinstance(file_content, str) else 'wb')` at line 377
   - **No `encoding` or `newline` argument** when opening in `'w'` mode

The `'w'` mode without `encoding` uses the system default encoding (`cp1252` on Windows, `utf-8` on Linux/macOS). Non-ASCII UTF-8 characters that are not in cp1252 (like `\u2192`) raise `UnicodeEncodeError`.

### Why the error occurs (hypotheses)

**For `gh repo view` failure:**
- **H1**: GitHub API propagation delay. Repository exists but is not yet visible to the API endpoint `gh repo view` queries. The immediate `get_repository()` call at line 410 races with GitHub's internal replication.
- **H2**: GitHub CLI bug or transient API failure. The repository exists but `gh repo view` fails for reasons unrelated to the repository state.
- **H3**: Network or authentication issue. Transient connectivity or credential refresh during the call.

**For encoding error:**
- **H4**: Windows default encoding (cp1252) cannot represent UTF-8 characters outside the cp1252 range. This is deterministic and overlaps with issue #10.

### Prior decisions

- Script version `v0.2.1/2026-11-13` was released with CodeCommit path separator fixes for Windows (#9) but predates this issue report
- GitHub seeding was added in `v0.2.0/2026-07-24` (per CHANGELOG.md)
- No retry logic exists for `gh repo view`
- No explicit encoding is set when writing files (current code assumes system default)

## 4. Review

### 4.1 Security

- **Input validation**: `repo_name` is validated against GitHub format at `cli/create_repo.py:176-181`; no injection risk identified
- **Command construction**: `gh` CLI commands use argument lists, not shell strings; no injection risk
- **Error disclosure**: Error messages include repository name (user-provided) and command output; acceptable for a CLI tool where the user controls the input
- **Credential handling**: `gh` CLI handles authentication; script does not touch credentials directly

No security concerns identified. The errors are operational, not security-related.

### 4.2 Software engineering

- **Error handling**: `get_repository()` re-raises exceptions after logging, which correctly propagates to the caller. However, the immediate call after creation at line 410 has no retry or delay, so transient failures abort the operation.
- **Encoding assumptions**: Opening files in `'w'` mode without explicit encoding is platform-dependent and violates the principle that repository content should be identical across platforms.
- **Overlap with #10 and #11**: The encoding error is a manifestation of the same root cause as #10 (missing explicit encoding) and is related to #11 (binary content mishandling). Fixing the encoding issue here would benefit from the same solution as #10.
- **Error context**: The `gh repo view` error message does not include stderr from the `gh` command, which would help diagnose the root cause. The error wrapping at `cli/lib/gh_utils.py:290` should preserve stderr.
- **Testability**: No tests currently cover GitHub repository creation or file seeding with non-ASCII content.

### 4.3 Cloud engineering

- **GitHub API propagation**: GitHub's API is eventually consistent. Repositories are typically visible within seconds, but under load or in certain regions propagation can be delayed. The immediate `get_repository()` call at line 410 assumes synchronous availability.
- **Rate limiting**: GitHub API and CLI have rate limits. Repeated retries without backoff could hit rate limits. However, a single retry with a short delay is unlikely to cause issues.
- **GitHub CLI dependencies**: The script assumes `gh` CLI is installed and authenticated. The checks at lines 166-175 validate this, but do not detect transient authentication issues or `gh` CLI bugs.
- **Deployment impact**: End users run this script locally. Failures do not affect production infrastructure. However, the script may leave a partially created repository (branch structure exists, seeding incomplete) if seeding fails, which is not automatically cleaned up for GitHub repositories (unlike CodeCommit at line 809).

## 5. Gaps and observations

### Missing information

- **Root cause of `gh repo view` failure**: The error is sporadic (two reported instances separated by months). Without stderr output from the `gh` command, we cannot confirm whether this is a propagation delay, a GitHub CLI bug, or a network issue.
- **Starter content**: The encoding error mentions position 8396 and character `\u2192`, but the specific starter or file is not identified. We assume it is one of the S3-hosted starters (per log line "Discovering app starters from s3://63klabs/atlantis/app-starters/v2").
- **Reproducibility**: Neither error has been reproduced locally. The `gh repo view` error may require specific conditions (GitHub API load, network state, or timing). The encoding error is deterministic on Windows when a starter contains `\u2192` but has not been confirmed by runtime test.

### Assumptions

- The `gh repo view` failure is transient and a retry would succeed (H1 or H3). If it is a GitHub CLI bug (H2), a retry would not help, but would not worsen the situation.
- The encoding error occurs only on Windows because Linux and macOS use UTF-8 as the system default encoding. This is consistent with the log showing "C:\Users\..." paths.
- Fixing the encoding issue in `create_init_commit` is the correct solution, rather than changing how files are collected. This aligns with #10's recommendation.

### Contradictions

- The first error log (2026-04-05) shows "Error getting repository information" immediately after "Creating GitHub repository: <ORG>/serverless-image-resizer" with no "GitHub Repository created" success message, but the code at line 407 logs success before line 410 calls `get_repository()`. Either the log is incomplete, or the error occurred in a different code path.
- The second error log (2026-11-14) shows the repository was successfully created before seeding failed, which is consistent with the current code path.

### Affected tests and docs

- No tests currently cover `GitHubUtils.get_repository()` or `create_init_commit()` failure scenarios
- No tests exercise file seeding with non-ASCII UTF-8 content on Windows
- No documentation mentions the possibility of `gh repo view` failure or encoding issues on Windows
- Script `--help` does not mention Windows-specific considerations

### Tangential observations

- **Incomplete cleanup**: When GitHub seeding fails, the repository and branch structure remain but are not seeded. CodeCommit seeding deletes the repository on failure (line 809), but GitHub seeding does not (line 838). This is inconsistent.
- **Hardcoded description**: `GitHubUtils.create_repo()` is called with description `"asdf"` at line 405. This should be user-configurable or derived from repository metadata.
- **Binary content overlap**: This issue shares the encoding problem with #10 and the binary content problem with #11. A coordinated fix across all three issues would avoid repeated refactoring.

## 6. Proposed approach

This spec addresses only the `gh repo view` failure (the first error in the issue). The encoding error reported in the November 14 log will be resolved by issue #10, which comprehensively addresses the missing explicit UTF-8 encoding for both CodeCommit and GitHub seeding.

### Phase 1: Harden `gh repo view` error handling

1. **Add retry logic with exponential backoff** to `GitHubUtils.get_repository()` when the exception is a `subprocess.CalledProcessError`. Retry up to 3 times with delays of 1s, 2s, 4s.
2. **Log stderr at ERROR level** by catching `subprocess.CalledProcessError` explicitly and logging `e.stderr` (if available) before re-raising. User-facing error messages remain unchanged.
3. **Add debug logging** before and after the `gh repo view` call to capture timing and confirm whether the failure is due to propagation delay (H1).

**Rationale**: If the failure is due to GitHub API propagation delay (H1) or transient network issues (H3), a short retry with backoff will resolve it. If the failure is a persistent GitHub CLI bug (H2), the retry will exhaust and the error will still be reported, but with stderr logged for troubleshooting. Logging stderr instead of including it in user-facing messages avoids exposing internal GitHub API details or sensitive information.

### Phase 2: Add cleanup for GitHub seeding failures

1. **Prompt the user before deleting** a failed GitHub repository in `_seed_repository_github()` at line 838: "Seeding failed. Delete repository <name>? (y/N)".
2. **Default to "N" (do not delete)** to avoid accidental data loss.
3. **Add a `--cleanup-on-failure` flag** (optional) to enable automatic deletion without prompting, for headless/CI usage.

**Rationale**: Seeding failures may be due to environmental issues (network, encoding) rather than user error. Users may want to inspect the repository state or retry seeding manually. Prompting gives users control while maintaining consistency with CodeCommit's cleanup behavior when the user confirms deletion.

### Phase 3: Improve observability

1. **Add stderr capture and logging** to all `subprocess.run()` calls in `gh_utils.py` that invoke `gh` CLI commands. Log stderr at ERROR level when a command fails.
2. **Consider adding a test** that simulates `gh repo view` failure and verifies retry behavior (if a test harness for `gh` CLI commands is available).

### Order of implementation

- Phase 1 (retry logic and stderr logging) can be implemented immediately and independently.
- Phase 2 (cleanup prompt) can be implemented in parallel with Phase 1.
- Phase 3 (comprehensive stderr logging) can be done after Phase 1 to ensure consistency across all `gh` CLI calls.

**Note**: The encoding error is not addressed in this spec. It will be resolved by issue #10 as part of a comprehensive fix for both CodeCommit and GitHub.

## 7. Related improvements

| Item | Class | Rationale | Effort | Risk |
|------|-------|-----------|--------|------|
| Coordinate encoding fix with #10 and #11 | Spin off | Confirmed: #10 will address the encoding issue comprehensively for both providers; this spec defers Phase 2 to #10 | M | L |
| Make repository description user-configurable | Note only | Hardcoded "asdf" at line 405 is unprofessional but does not affect functionality; low priority | S | L |
| Add test for `gh repo view` retry behavior | Include | Retry logic is a new control path that should be tested if a test harness for `gh` CLI commands is available | M | L |
| Add `--cleanup-on-failure` flag for headless usage | Include | Enables automatic cleanup in CI/CD environments where prompting is not possible | S | L |

## 8. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Retry logic adds latency when `gh repo view` fails for a persistent reason (H2) | Use exponential backoff with a maximum of 3 retries (total ~7 seconds); log each attempt to make the delay visible |
| Prompting for cleanup may interrupt automated workflows | Add `--cleanup-on-failure` flag to enable automatic deletion without prompting for headless/CI usage |
| Logging stderr may expose sensitive information if logs are shared | Ensure logs are properly secured and instruct users to redact sensitive information when sharing log files for troubleshooting |
| Coordinating with #10 may delay the encoding fix for this specific error | Implement Phase 1 (retry logic) immediately as a standalone improvement; users experiencing the encoding error can be directed to track #10 for the fix |

## 9. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Defer encoding fix to issue #10 | Issue #10 already comprehensively describes the encoding problem (missing explicit UTF-8) and recommends the same fix for both CodeCommit and GitHub. Including the encoding fix here would duplicate planning and implementation effort. This spec focuses on the `gh repo view` error, which is unique to this issue. The November 14 encoding error will be resolved by #10. |
| 2 | Binary content handling is not applicable to this spec | Since the encoding fix is deferred to #10 (Decision 1), the question of whether to also fix binary content handling (#11) is moot. Issues #10 and #11 will coordinate on a comprehensive solution. |
| 3 | Prompt user before deleting failed GitHub repositories | Seeding failures may be due to environmental issues (network, encoding) rather than user error. Users may want to inspect the repository state or retry seeding manually. Prompting with a default of "N" (do not delete) gives users control while avoiding accidental data loss. For headless/CI usage, a `--cleanup-on-failure` flag will enable automatic deletion without prompting. |
| 4 | Log stderr only, not in user-facing error messages | Stderr from `gh` CLI commands may contain sensitive information (authentication tokens, internal GitHub API details) or technical jargon that is not user-friendly. Logging stderr at ERROR level ensures it is available for troubleshooting (via log files) without cluttering user-facing error messages. Users reporting issues can share log files with stderr included for diagnosis. |

## 10. Open questions and recommendations

No open questions.
