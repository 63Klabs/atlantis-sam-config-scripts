# Requirements: Git for Windows Bug in File Seeding

## Introduction

When `create_repo.py` seeds a repository from a starter on Windows, files in subdirectories are committed to CodeCommit at the repository root with literal backslashes in their names. The script reports success, and the next `git checkout` fails with `error: invalid path '.github\dependabot.yml'`. This is reported in [issue #9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9). The decisions behind these requirements are locked in [PLAN.md](PLAN.md).

`RepositoryCreator._seed_collect_files` (`cli/create_repo.py`) builds each `filePath` with `os.path.relpath(full_path, temp_dir)`. On Windows that returns `\`-separated paths. CodeCommit `CreateCommit` treats only `/` as a path separator, so each backslash becomes part of the file name. The unzip step uses `pathlib` and is not affected. `_seed_collect_files` is shared by the CodeCommit and GitHub seeding paths. GitHub seeding is not corrupted, because Windows file APIs accept `\` and `git add` stores paths with `/`.

**Bug condition C(X):** `os.sep` is `\` (Windows) AND the starter contains at least one file in a subdirectory AND the target provider is CodeCommit.

The fix adds a module-level helper, `_to_codecommit_path`, that replaces the OS path separator with `/`, and calls it from `_seed_collect_files`. Both providers then receive `/`-separated paths on every platform. The helper takes the separators as parameters so that the Windows case is testable on Linux.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `_seed_collect_files` runs on Windows against a starter that contains files in subdirectories THEN the system returns `filePath` values that contain `\` (for example `.github\workflows\deploy-to-s3.yml`)

1.2 WHEN `_seed_repository_codecommit` sends those `filePath` values in `putFiles` THEN CodeCommit stores each file at the repository root with the backslashes as part of its name, and `git checkout` of `dev` and `test` fails with `invalid path`

1.3 WHEN the seeded files are stored with backslash names THEN the system still prints that the repository was seeded successfully, because nothing inspects the stored paths

### Expected Behavior (Correct)

2.1 WHEN `_seed_collect_files` runs on any platform THEN the system SHALL return `filePath` values that use `/` as the only path separator (for example `.github/workflows/deploy-to-s3.yml`)

2.2 WHEN `_to_codecommit_path(relative_path, sep, altsep)` is called THEN the system SHALL return `relative_path` with every occurrence of `sep`, and of `altsep` when it is set, replaced by `/`

2.3 WHEN `_to_codecommit_path` is called without explicit separators THEN the system SHALL use `os.sep` and `os.altsep` of the running platform

2.4 WHEN `_seed_collect_files` computes a relative path THEN the system SHALL pass it through `_to_codecommit_path` before storing it as `filePath` and before using it in the "Error processing file" console and log messages

2.5 WHEN a repository is seeded for either provider THEN the system SHALL give both `_seed_repository_codecommit` and `_seed_repository_github` the same normalized file list

2.6 WHEN `_seed_collect_files` returns THEN every `filePath` SHALL be a relative path with no leading `/` and no `..` segment

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the platform separator is already `/` (Linux, macOS, WSL) THEN the system SHALL CONTINUE TO return `filePath` values identical to those produced before this change

3.2 WHEN a file sits at the root of the starter THEN the system SHALL CONTINUE TO use its bare file name as `filePath`

3.3 WHEN the platform separator is `/` and a file name contains a backslash THEN the system SHALL CONTINUE TO leave that name unchanged

3.4 WHEN `_seed_collect_files` builds each entry THEN the system SHALL CONTINUE TO set `fileContent` (UTF-8 text, or base64 text for content that is not valid UTF-8) and `fileMode: 'NORMAL'` exactly as before

3.5 WHEN CodeCommit seeding runs THEN the system SHALL CONTINUE TO commit in batches of 100 files, delete the repository on failure, and exit non-zero on failure

3.6 WHEN GitHub seeding runs on Windows THEN the system SHALL CONTINUE TO write every file into its subdirectory of the local clone and commit it with the same repository layout as before this change

3.7 WHEN a repository is seeded and merging is enabled THEN the system SHALL CONTINUE TO merge `dev` into `test` as specified in the v0.0.18 auto-merge feature

3.8 WHEN `create_repo.py` is invoked THEN the system SHALL CONTINUE TO accept the same command-line options with the same behavior

---

## Testing Requirements

4.1 The test file `tests/test_create_repo_seed_paths.py` SHALL exist and run under the existing pytest and Hypothesis setup (`cli/requirements-test.txt`) on Linux

4.2 A unit test SHALL pass a Windows-style relative path to `_to_codecommit_path` with `sep='\\'` and assert the result is `/`-separated

4.3 A unit test SHALL assert that a root-level file name is returned unchanged

4.4 A unit test SHALL assert that, with `sep='/'`, a file name containing a backslash is returned unchanged

4.5 A property-based test SHALL generate path segments that contain neither `/` nor `\`, join them with `\`, normalize with `sep='\\'`, and assert the result equals the segments joined with `/`

4.6 A test SHALL run `_seed_collect_files` against a real temporary directory tree that includes nested directories and assert every `filePath` is `/`-separated, relative, and free of `..` segments (requirements 2.1 and 2.6)

4.7 Existing tests in `tests/` SHALL continue to pass

4.8 A wiring test SHALL patch `os.path.relpath` (within a narrow scope) to return the Windows form of each path, call `_seed_collect_files`, and assert every returned `filePath` is `/`-separated, so that removing the helper call fails the test (requirement 2.4)

---

## Version and Documentation Requirements

5.1 `cli/create_repo.py` SHALL change `VERSION` from `v0.2.0/2026-07-24` to `v0.2.1/2026-11-13` (PATCH: bug fix, no interface change), per `.kiro/steering/ascs-cli-script-versioning.md`

5.2 `cli/lib/gh_utils.py` SHALL NOT be modified, so its `VERSION` remains `v0.1.0/2026-07-24`

5.3 `CHANGELOG.md` SHALL gain a `### Fixed` entry under `v0.0.21 (unreleased)` that names `create_repo.py v0.2.1`, links [issue #9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9) and this spec, and describes the fix. Existing changelog text SHALL NOT be edited.

5.4 The CHANGELOG entry SHALL state that repositories already seeded from Windows are not repaired by this update, and that they must be deleted and recreated, or have their files re-committed into the correct directories

5.5 The new helper SHALL carry a Python docstring that follows `.kiro/steering/documentation-standards-python.md`

---

## Verification Requirements

6.1 Before release, the maintainer SHALL run `create_repo.py` from Windows Git Bash (`.ve` venv) against a throwaway CodeCommit repository and against a throwaway GitHub repository (`--provider github`), seeded from the same starter

6.2 For each run, `git clone`, `git checkout dev`, `git checkout test`, and `git ls-tree -r --name-only origin/dev` SHALL show `/`-separated nested paths such as `.github/workflows/...` and no file names that contain `\`

6.3 The maintainer SHALL delete both throwaway repositories after verification

---

## Out of Scope

- Fail-closed validation of `filePath` before `create_commit` (PLAN.md Decision 3)
- Repair tooling or troubleshooting documentation for already-seeded repositories (Decision 2)
- GitHub text-mode encoding and newline handling, tracked in [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10)
- Binary and non-UTF-8 content sent as base64 text, tracked in [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11)
- Zip extraction path check, tracked in [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12)
- Changes to `README.md`, `docs/`, or the "use WSL" workaround wording
