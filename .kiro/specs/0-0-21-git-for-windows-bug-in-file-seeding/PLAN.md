# Git for Windows bug in file seeding

> **Status**: Locked, 2026-11-13
> **Issue**: [ISSUE.md](ISSUE.md) (GitHub issue #9)
> **Reviewed against**: `main` at `480e089` on 2026-11-13 (working tree has an uncommitted `CHANGELOG.md` edit adding the `v0.0.21 (unreleased)` header)

## 1. Summary

When `create_repo.py` runs on Windows (Git Bash with the `.ve` venv), `_seed_collect_files` builds each CodeCommit `filePath` with `os.path.relpath`, which returns backslash-separated paths on Windows. CodeCommit `CreateCommit` treats only `/` as a separator, so every seeded file in a subdirectory is stored at the repository root with literal backslashes in its name. The script reports success, and the next `git checkout` fails with `invalid path`. Anyone seeding a CodeCommit repository from Windows is affected. Linux, macOS, and WSL are not.

The recommended fix is a one-line normalization of the relative path to forward slashes in `_seed_collect_files`, written so it can be unit tested on the Linux CI/dev machine, plus a patch version bump, a CHANGELOG entry, and a note for users who already have a broken repository.

## 2. Assessment of the issue

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | `_seed_collect_files` computes `relative_path` with `os.path.relpath(full_path, temp_dir)` near line 681 and stores it as `filePath` near line 693 | **Confirmed** | `cli/create_repo.py:675-700` (`relative_path = os.path.relpath(full_path, temp_dir)`, `'filePath': relative_path`) |
| 2 | On Windows `os.path.relpath` returns `\` separators | **Confirmed** | Python's `ntpath.relpath` behavior. Reproduced offline: `ntpath.relpath('C:\\t\\.github\\w\\d.yml','C:\\t')` returns `.github\w\d.yml` |
| 3 | CodeCommit `CreateCommit` treats only `/` as a separator, so backslashes become part of the file name | **Partially confirmed** | The reporter's `git ls-tree` output (27 files at root with literal backslashes) matches this. Not verifiable by reading the code. See runtime check R1. The CodeCommit API reference should be checked for the documented `filePath` constraints before the requirements are written. |
| 4 | No later normalization exists in `create_repo.py` or `cli/lib/` | **Confirmed** | `grep` for `as_posix`, `os.sep`, `replace`, `relpath`, `filePath` across `cli/` finds only `create_repo.py:681,693`, `gh_utils.py:373` (consumer, no normalization), and two unrelated `relpath` calls in `config.py:1961,2071` |
| 5 | The unzip step uses `pathlib` and is fine | **Confirmed** | `cli/create_repo.py:541-576` builds `Path(temp_dir) / zip_info.filename`. Zip member names always use `/`, so extraction is correct on Windows. |
| 6 | Only the CodeCommit file list is affected | **Partially confirmed** | `_seed_collect_files` is shared by both providers (`create_repo.py:708` and `:778`). The GitHub path consumes the same list through `os.path.join(git_dir, file_path)` (`gh_utils.py:373`). Windows accepts `\` there, and `git add` normalizes to `/`, so GitHub seeding is not corrupted. The shared function is where the fix belongs. |
| 7 | Suggested fix `Path(os.path.relpath(full_path, temp_dir)).as_posix()` resolves it | **Partially confirmed** | Correct on Windows, where `Path` is a `WindowsPath`. On Linux `Path('a\\b').as_posix()` returns `a\b` unchanged (reproduced), so a test on the Linux dev machine cannot exercise the fix unless Windows semantics are injected. |
| 8 | The script "reported success" | **Confirmed** | `create_commit` succeeds, and nothing in `_seed_repository_codecommit` (`create_repo.py:705-772`) inspects the stored paths. |
| 9 | Windows is a supported environment | **Confirmed** | `README.md:57` and `docs/00-Set-Up-Local-Environment.md:3` both name Git for Windows as supported. The issue's "use WSL" workaround contradicts the documented support. |

**Needs runtime verification**

- **R1.** Before release, the maintainer runs `create_repo.py` from Windows Git Bash (`.ve` venv) against a throwaway CodeCommit repository and again against a throwaway GitHub repository (`--provider github`), seeding both from the same starter. For each, `git clone`, `git checkout dev`, `git checkout test`, and `git ls-tree -r --name-only origin/dev` must show `/`-separated nested paths (for example `.github/workflows/...`) and no file names containing `\`. Both throwaway repositories are deleted afterward. The GitHub run is a regression check, because the helper changes the paths GitHub seeding receives (Decision 5).
- **R2.** Regression check that nested directories still seed correctly on Linux/macOS. Resolved by an automated test over a real temporary directory tree (see Section 6), so no manual run is needed.
- **R3 and R4** (Section 5) move to the spin-off issues confirmed in Decision 4 and are verified there.

## 3. Current state

- `_seed_collect_files(self, temp_dir)` walks the extracted starter with `os.walk`, reads each file as bytes, decodes as UTF-8 (falling back to base64 text), and returns dicts with `filePath`, `fileContent`, `fileMode` (`cli/create_repo.py:675-703`).
- `_seed_repository_codecommit` sends those dicts unchanged as `putFiles` in batches of 100 (`cli/create_repo.py:705-772`).
- `_seed_repository_github` passes the same list to `GitHubUtils.create_init_commit`, which writes each file into a local clone and runs `git add .` (`cli/create_repo.py:775-800`, `cli/lib/gh_utils.py:369-376`).
- The function has not changed since it was added in `5b85ea22` (2025-06-03, "wip: added copy files to gh in create_repo.py"). The Windows bug has therefore existed since the first CodeCommit seeding code. No earlier deliberate decision about separators was found in `git log`.
- `cli/` is shipped to users and updated through `update.py`, so a fix here reaches users on their next update (per `AGENTS.md`).
- Existing tests for `create_repo.py` (`tests/test_create_repo_merge.py`) cover only merge gating and instantiate `RepositoryCreator` with mocks. No test covers `_seed_collect_files`.

## 4. Review

### 4.1 Security

- **Trust boundary.** The extracted file names come from a zip chosen by the user (S3 object, GitHub repo, or the organization's starter list). The fix does not change what is trusted.
- **Path traversal on extraction (existing, out of scope).** `output_path = Path(temp_dir) / zip_info.filename` (`create_repo.py:571-576`) does not check for `..` or absolute members (zip-slip). The source is chosen by the user running the script, so the risk is low, but it is real if a user points `--source` at an untrusted zip. Classified as a spin-off in Section 7.
- **Normalization must not weaken anything.** Converting `\` to `/` only on the OS separator cannot introduce new traversal, because `os.walk` already yields paths under `temp_dir`.
- **Fail-open behavior.** The current failure is silent: the script prints "seeded successfully" for a repository whose layout is wrong. A post-condition check would fail closed, but it was declined (Decision 3). The normalization and the real-tree test pin the behavior instead.
- **Disclosure.** Not a security vulnerability. No special handling of the spec directory is needed.
- **IAM.** No change. The same `codecommit:CreateCommit` calls are made.

### 4.2 Software engineering

- **Correctness.** The fix is one expression in a shared function. Edge cases: nested directories (the bug), files at the repo root (no separator, unchanged), Unicode names (unchanged), and files on Linux/macOS that legitimately contain a backslash in the name (a rare but legal name). Replacing every `\` unconditionally would rewrite such a name on POSIX. Replacing only `os.sep` (and `os.altsep` when set) or using `Path.as_posix()` leaves POSIX names intact.
- **Testability.** `Path(...).as_posix()` is a no-op for backslashes on Linux, so a test that passes a Windows-style path through it proves nothing there. Two ways to test on Linux: (a) extract a small helper that takes the separator as a parameter, or (b) patch `os.path.relpath` and `os.sep` with `ntpath` equivalents. Option (a) is simpler and keeps the production call identical. Property-based tests fit: for any list of path segments that contain no `/` or `\`, joining with the Windows separator and normalizing yields the `/`-joined string.
- **Fit with existing patterns.** The repository uses `pathlib` in the extraction step and `os.path` in the walk. `as_posix()` matches the issue's suggestion and the `pathlib` usage already in the file.
- **Tests that change.** None encode the current behavior. New tests are needed for `_seed_collect_files`.
- **Versioning.** Per `.kiro/steering/ascs-cli-script-versioning.md`, `cli/create_repo.py` moves from `v0.2.0/2026-07-24` to `v0.2.1/2026-11-13` (PATCH: bug fix, no interface change). `cli/lib/gh_utils.py` is not changed (Decision 4), so its version stays `v0.1.0/2026-07-24`.
- **Documentation.** `CHANGELOG.md` gets a `### Fixed` entry under `v0.0.21 (unreleased)`, linking this spec. Existing changelog text must not be edited. No user docs describe separator handling, and Decision 2 limits remediation guidance to the CHANGELOG, so no other doc changes are required.

### 4.3 Cloud engineering

- **Topology.** Client-side only. The change is in the boto3 `create_commit` payload. No templates, IAM, stacks, or stages are touched.
- **Existing broken repositories.** Repositories already seeded from Windows hold files named with literal backslashes at the root on `dev` and, because of the automatic dev-to-test merge added in v0.0.18, on `test` as well. The fix does not repair them. If a test pipeline already ran, it deployed from a malformed tree, so the pipeline likely failed or deployed nothing useful. Users receive remediation guidance in the CHANGELOG only (Decision 2).
- **Failure cleanup.** On a seeding failure the script deletes the repository (`create_repo.py:759-771`). Because this bug does not raise, no cleanup occurs and the broken repo stays.
- **Cost and quotas.** No change. Batch size and `putFiles` limits are untouched.
- **Rollout and rollback.** Ships through `update.py`. Rollback is to revert the one-line change and re-release.

## 5. Gaps and observations

- The issue reports script `v0.2.0/2026-07-24` only. It does not say whether the reporter's Python was the Windows build run from Git Bash or a MSYS Python. The two behave differently for `os.sep` (MSYS Python reports `/`). The reporter's output shows backslashes, so this is a native Windows Python. Flagged for completeness; the fix covers both.
- The issue does not say whether the reporter's `test` branch had a pipeline created from it.
- **Adjacent Windows defects found while reading, not in the issue** (see Section 7):
  - `GitHubUtils.create_init_commit` opens files with `open(full_path, 'w' ...)` without `encoding` or `newline` (`gh_utils.py:377`). On Windows that uses the locale code page (typically cp1252) and writes `\r\n` for `\n`. This can raise `UnicodeEncodeError` on UTF-8 content or silently change file bytes. Needs runtime verification on Windows (R3).
  - Non-UTF-8 files are base64-encoded to text in `_seed_collect_files` (`create_repo.py:687-690`) and then sent as `fileContent` or written as text. The `'wb'` branch in `gh_utils.py:377` is unreachable because `fileContent` is always `str`. botocore accepts a `str` blob (validated offline), so a binary file would be stored as its base64 text, not as its bytes. Needs runtime verification (R4), and it affects all platforms.
- The issue's "use WSL" workaround conflicts with `README.md:57`, which lists Git Bash as supported.

## 6. Proposed approach

1. Add a module-level helper in `cli/create_repo.py`, `_to_codecommit_path(relative_path, sep=os.sep, altsep=os.altsep)`, that returns `relative_path` with `sep` (and `altsep` when set) replaced by `/`. When `sep` is already `/` the value is returned unchanged, so a POSIX file name that contains a backslash is not rewritten. Parameter defaults are bound at call time through `None` sentinels or an equivalent so that tests can inject `\` on Linux. Final signature is a design decision.
2. In `RepositoryCreator._seed_collect_files`, pass the result of `os.path.relpath(full_path, temp_dir)` through the helper before it is stored as `filePath` and before it is used in the error messages. Both CodeCommit and GitHub seeding consume the normalized list.
3. Add `tests/test_create_repo_seed_paths.py` with:
   - a unit test that a Windows-style relative path (`sep='\\'`) becomes `/`-separated,
   - a unit test that a root-level file is unchanged, and that with `sep='/'` a name containing a backslash is unchanged,
   - a property-based test (Hypothesis, already in `cli/requirements-test.txt`) over generated path segments that contain neither `/` nor `\`: joining with `\` and normalizing equals joining with `/`,
   - a test that runs `_seed_collect_files` against a real temporary directory tree with nested directories and asserts every `filePath` is `/`-separated, relative, and free of `..` (replaces runtime check R2).
4. Bump `cli/create_repo.py` to `v0.2.1/2026-11-13` (PATCH). No other script or library changes.
5. Add a `### Fixed` entry under `v0.0.21 (unreleased)` in `CHANGELOG.md` that references this spec and issue #9. The entry states that Windows seeding of CodeCommit repositories produced backslash-named files at the repository root, and that repositories already seeded from Windows must be deleted and recreated, or have their files re-committed into the correct directories.
6. Before release, the maintainer performs the Windows verification described in R1 for both the CodeCommit and GitHub providers (Decision 5).
7. Out of scope: `gh_utils.py`, zip extraction, the post-seed guard, and any docs beyond the CHANGELOG.

Alternatives considered:

- **Inline `Path(...).as_posix()`** (the issue's suggestion). Correct on Windows, but a Linux test cannot fail on it (Decision 1).
- **Normalize at the CodeCommit call site only.** Rejected: leaves the shared list in OS-specific form and spreads the fix.
- **Normalize in `GitHubUtils` as well.** Rejected: GitHub is not affected, and `os.path.join` accepts `/` on Windows.
- **Fail-closed guard before `create_commit`.** Declined (Decision 3).
- **Troubleshooting section in `docs/SCRIPT-GUIDE.md` or a repair script.** Declined (Decision 2).
- **Document WSL as the only supported Windows path.** Rejected: contradicts `README.md:57` and leaves the defect.

## 7. Related improvements

| Item | Class | Rationale | Effort | Risk |
|------|-------|-----------|--------|------|
| Post-seed check that no `filePath` contains `\` or starts with `/` before calling `create_commit`, aborting and cleaning up if so | Dropped (Decision 3) | Declined. Normalization plus the real-tree test pins the behavior. | S | Low |
| Explicit `encoding='utf-8'` and `newline=''` (and binary-safe writes) in `GitHubUtils.create_init_commit` | Spin off, filed as [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10) (Decision 6) | Separate Windows defect in the GitHub path, needs a Windows runtime check (R3) | S | Medium (changes bytes written) |
| Binary files are sent as base64 text rather than bytes in both providers | Spin off, filed as [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11) (Decision 6) | Possible data corruption on all platforms, needs runtime check (R4) | M | Medium |
| Zip-slip guard on extraction (`..`, absolute names) | Spin off, filed as [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12) (Decision 6) | Hardening of untrusted-zip handling, unrelated to separators | S | Low |
| Test coverage for `_seed_collect_files` | Include | Needed to lock the fix | S | Low |
| Reconcile "use WSL" guidance with `README.md:57` | Note only | Wording only, resolved once the fix ships | S | Low |

## 8. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Fix cannot be exercised on Windows in CI, so a regression could return unnoticed | Test the normalization with an injected separator and a real temp tree on Linux. The maintainer runs the manual Windows check (R1) on both providers before release (Decision 5). |
| A POSIX file legitimately named with a backslash gets rewritten | Normalize only `os.sep`/`os.altsep` or use `Path.as_posix()`, never a blanket `replace('\\', '/')`. |
| Users with already-broken repositories assume the update fixed them | CHANGELOG `Fixed` entry states that existing repositories are not repaired and must be recreated or re-committed (Decision 2). Residual risk: users who do not read the CHANGELOG. |
| Scope creep into the GitHub encoding, binary, and zip-extraction issues | Kept as separate issues (Decision 4). |
| No guard means a future separator regression would again print "success" for a broken tree | The real-tree test fails on regression. Accepted residual risk (Decision 3). |

## 9. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Q1: Add a module-level helper `_to_codecommit_path` that replaces the OS separator with `/`, called from `_seed_collect_files`. | Testable on Linux by injecting `\`, and leaves POSIX names containing a backslash untouched. |
| 2 | Q2: CHANGELOG note only for repositories already seeded from Windows. No troubleshooting docs and no repair script. | Rare case, and recreating a freshly seeded repository is the simplest path. |
| 3 | Q3: No fail-closed guard after collecting files. | The normalization and the real-tree test pin the behavior, and a `\` guard would need to special-case legal POSIX names. |
| 4 | Q4: Create separate issues for (a) GitHub text-mode encoding and newline handling in `create_init_commit` (R3), (b) binary files sent as base64 text (R4), (c) zip extraction path check (zip-slip). None are touched in this fix. | Separable, two need runtime checks this fix does not need, and bundling would delay a small fix. |
| 5 | Q5: The maintainer verifies the fix on Windows before release (R1), for both CodeCommit and GitHub seeding, using throwaway repositories that are deleted afterward. | Only a Windows run proves the end-to-end result. The GitHub run confirms that the changed paths do not regress that provider. |
| 6 | Spin-offs filed on 2026-11-13 in `63Klabs/atlantis-sam-config-scripts` with the `bug` or `enhancement` label (not `approved for development`, which is the maintainer's triage label): [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10) GitHub text-mode write (R3), [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11) binary content as base64 text (R4), [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12) zip extraction path check. | Carries out Decision 4. The zip item is described as low-risk hardening, with no exploit detail, because the repository is public. |

## 10. Open questions and recommendations

No open questions.
