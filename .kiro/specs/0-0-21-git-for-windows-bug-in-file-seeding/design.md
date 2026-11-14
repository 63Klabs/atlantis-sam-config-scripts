# Git for Windows Bug in File Seeding - Bugfix Design

## Overview

On Windows, `RepositoryCreator._seed_collect_files` (`cli/create_repo.py:675-703`) builds each `filePath` with `os.path.relpath(full_path, temp_dir)`, which returns `\`-separated paths. CodeCommit `CreateCommit` treats only `/` as a separator, so every file in a subdirectory is committed at the repository root with literal backslashes in its name ([issue #9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9)).

The fix adds one module-level helper, `_to_codecommit_path`, that replaces the platform path separator with `/`, and routes the `os.path.relpath` result through it inside `_seed_collect_files`. `_seed_collect_files` is shared by the CodeCommit and GitHub seeding paths, so both receive the same normalized list. Nothing else in the seeding flow changes.

The helper takes the separators as parameters, defaulting to `os.sep` and `os.altsep`. This lets the Windows case run as an ordinary unit test on Linux, which is where the test suite runs. The decisions behind this design are locked in [PLAN.md](PLAN.md) (Decisions 1 to 6), and the numbered requirements are in [requirements.md](requirements.md).

## Glossary

- **Bug_Condition (C)**: `os.sep` is `\` AND the starter has at least one file in a subdirectory AND the target provider is CodeCommit.
- **Property (P)**: Every `filePath` returned by `_seed_collect_files` uses `/` as its only separator.
- **Preservation**: On platforms where `os.sep` is `/`, `_seed_collect_files` output is identical to its pre-fix output. Content encoding, file mode, batching, cleanup, and GitHub seeding are unchanged.
- **`filePath`**: The key in each `putFiles` entry that names the file's location in the repository. CodeCommit interprets `/` as the directory separator.
- **`_to_codecommit_path`**: The new helper that normalizes a relative path to `/` separators.
- **`os.altsep`**: The alternate separator reported by `os`. It is `/` on Windows and `None` on POSIX.

## Bug Details

### Bug Condition

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type SeedRun (platform separator, provider, starter file tree)
  OUTPUT: boolean

  RETURN X.os_sep = '\'
         AND X.provider = 'codecommit'
         AND EXISTS file IN X.starter WHERE file.relative_path contains a directory component
END FUNCTION
```

Windows seeding to GitHub also receives `\` paths from `_seed_collect_files`, but it is not corrupted: `os.path.join` and `open` accept `\`, and `git add` stores `/`. It is therefore outside the bug condition and is covered by preservation requirement 3.6.

### Examples

| Starter file | Pre-fix `filePath` on Windows | Stored by CodeCommit | Post-fix `filePath` |
|---|---|---|---|
| `README.md` | `README.md` | `README.md` | `README.md` |
| `.github\workflows\deploy-to-s3.yml` (extracted) | `.github\workflows\deploy-to-s3.yml` | one root file with backslashes in its name | `.github/workflows/deploy-to-s3.yml` |
| `application-infrastructure\build-scripts\generate-put-ssm.py` | same, with `\` | one root file with backslashes in its name | `application-infrastructure/build-scripts/generate-put-ssm.py` |
| `weird\name.txt` as a single POSIX file name | `weird\name.txt` | file named `weird\name.txt` | `weird\name.txt` (unchanged on POSIX) |

## Expected Behavior

### Preservation Requirements

- **Unchanged on POSIX:** Linux, macOS, and WSL produce byte-identical `filePath` values (requirements 3.1, 3.3).
- **Root files:** Files without a directory component are unchanged (3.2).
- **Content and mode:** `fileContent` (UTF-8 text or base64 text) and `fileMode: 'NORMAL'` are unchanged (3.4). Binary handling is tracked separately in [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11).
- **CodeCommit flow:** batches of 100, repository deletion on failure, and non-zero exit are unchanged (3.5).
- **GitHub flow:** `GitHubUtils.create_init_commit` is not modified, and Windows seeding keeps its current repository layout (3.6).
- **Auto-merge and CLI:** dev-to-test merge and all command-line options are unchanged (3.7, 3.8).

## Hypothesized Root Cause

This is a confirmed cause, not a hypothesis. `os.path.relpath` returns paths in the host's native form (`ntpath.relpath` returns `\`). `_seed_collect_files` stores that value directly as `filePath` (`cli/create_repo.py:693`), and no later step normalizes it. A search of `cli/` for `as_posix`, `os.sep`, `relpath`, and `filePath` found no other normalization. The function has been unchanged since commit `5b85ea22` (2025-06-03). The cause was reproduced offline by calling `ntpath.relpath('C:\\t\\.github\\w\\d.yml', 'C:\\t')`, which returns `.github\w\d.yml`.

The issue's suggested fix, `Path(os.path.relpath(...)).as_posix()`, is correct on Windows. On Linux, `Path('a\\b').as_posix()` returns `a\b`, so a Linux test could not fail on it. That is why PLAN.md Decision 1 chose a helper with injectable separators.

## Correctness Properties

**Property 1: Bug Condition - Windows relative paths become `/`-separated**

For any list of non-empty path segments that contain neither `/` nor `\`, `_to_codecommit_path('\\'.join(segments), sep='\\')` SHALL equal `'/'.join(segments)`. For the same input on the real `_seed_collect_files`, with `os.path.relpath` returning the Windows form, every returned `filePath` SHALL contain no `\`.

**Validates: Requirements 2.1, 2.2, 2.4**

**Property 2: Preservation - POSIX behavior is the identity**

For any string `s`, `_to_codecommit_path(s, sep='/')` SHALL return `s` unchanged, including strings that contain `\`. For a real temporary tree on the running POSIX host, `_seed_collect_files` SHALL return the same `filePath` values as `os.path.relpath(full_path, temp_dir)` for every file.

**Validates: Requirements 3.1, 3.2, 3.3**

**Property 3: Output shape**

For a real temporary tree with nested directories, every `filePath` returned by `_seed_collect_files` SHALL be relative (no leading `/`), SHALL contain no `..` segment, and SHALL contain no `\` when `os.sep` is `/`.

**Validates: Requirements 2.1, 2.6**

## Fix Implementation

### Changes Required

All production changes are in `cli/create_repo.py`.

**Change 1: add the helper** immediately after `should_merge_test` and before `class RepositoryCreator`, following the module's existing pattern of a documented, pure, module-level function next to the class.

```python
def _to_codecommit_path(relative_path: str, sep: Optional[str] = None,
                        altsep: Optional[str] = None) -> str:
    """Normalize a relative file path to the ``/`` separator CodeCommit expects.

    CodeCommit ``CreateCommit`` treats only ``/`` as a path separator. On
    Windows ``os.path.relpath`` returns ``\\``-separated paths, which would be
    stored as literal backslashes in a file name at the repository root. This
    function replaces the platform separator (and the alternate separator,
    when it is not already ``/``) with ``/``. When the platform separator is
    already ``/`` the input is returned unchanged, so a POSIX file name that
    happens to contain a backslash is not rewritten.

    Args:
        relative_path (str): Path relative to the seed root, in the host's
            native form.
        sep (Optional[str]): Platform separator to replace. Defaults to
            ``os.sep`` when ``None``. Tests pass ``'\\\\'`` to exercise the
            Windows case on any host.
        altsep (Optional[str]): Alternate separator to replace. Defaults to
            ``os.altsep`` when ``None``.

    Returns:
        str: ``relative_path`` with ``sep`` and ``altsep`` replaced by ``/``.

    Example:
        >>> _to_codecommit_path('.github\\\\workflows\\\\deploy.yml', sep='\\\\')
        '.github/workflows/deploy.yml'
        >>> _to_codecommit_path('README.md', sep='\\\\')
        'README.md'
    """
    sep = os.sep if sep is None else sep
    altsep = os.altsep if altsep is None else altsep
    normalized = relative_path
    for separator in (sep, altsep):
        if separator and separator != '/':
            normalized = normalized.replace(separator, '/')
    return normalized
```

Design notes:

- `None` means "use the platform value". On Windows `os.altsep` is `/`, which the `separator != '/'` check skips. On POSIX `os.altsep` is `None`. So passing only `sep='\\'` on Linux behaves as intended and cannot be affected by `altsep`.
- Python's MSYS builds report `os.sep == '/'`; the helper is then the identity, which is correct because `os.path.relpath` also returns `/` paths there.
- The `separator != '/'` check makes `sep='/'` the identity for every string (Property 2).

**Change 2: route the relpath result through the helper** in `_seed_collect_files`:

```python
# Before
relative_path = os.path.relpath(full_path, temp_dir)

# After
relative_path = _to_codecommit_path(os.path.relpath(full_path, temp_dir))
```

Reassigning `relative_path` means the normalized value is used both as `'filePath'` and in the two "Error processing file" messages, which satisfies requirement 2.4 with a one-line diff. The cleanup and exit logic in that `except` block is untouched.

**Change 3: bump `VERSION`** from `v0.2.0/2026-07-24` to `v0.2.1/2026-11-13` (PATCH).

**Change 4: CHANGELOG entry** under `## v0.0.21 (unreleased)`:

```markdown
### Fixed
- **Script: create_repo.py v0.2.1** - Fixed seeding of CodeCommit repositories from Windows (Git Bash), where files in subdirectories were committed at the repository root with backslashes in their names and `git checkout` failed with `invalid path` [Spec: 0-0-21-git-for-windows-bug-in-file-seeding](.kiro/specs/0-0-21-git-for-windows-bug-in-file-seeding/), addresses [#9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9)
  - Seeded file paths are now normalized to `/` separators on every platform before they are committed. Linux, macOS, and WSL output is unchanged.
  - Repositories already seeded from Windows are not repaired by this update. Delete and recreate them, or re-commit the files into the correct directories.
```

### Files Not Changed

`cli/lib/gh_utils.py` (stays `v0.1.0/2026-07-24`), the zip extraction code, `README.md`, and `docs/`.

## Testing Strategy

### Validation Approach

Two phases: first show that the tests fail on the unfixed code (exploratory check), then show they pass after the fix and that POSIX behavior is preserved. Every test runs on Linux with `pytest` and Hypothesis, consistent with `tests/test_create_repo_merge.py`. A `RepositoryCreator` instance for these tests is built with `RepositoryCreator.__new__(RepositoryCreator)` so no AWS session or settings file is needed, as the existing tests do. `_seed_collect_files` only touches `self.codecommit_client` on its error path, so tests set it to a `MagicMock`.

### Exploratory Bug Condition Checking

Goal: show the defect on the unfixed code before implementing.

- Patch `create_repo.os.path.relpath` in a narrow `with` block to return the Windows form of the real result (`result.replace('/', '\\')`), then call `_seed_collect_files` on a temporary tree with nested directories. On the unfixed code the returned `filePath` values contain `\`, so the assertion fails. This is the wiring test described below and doubles as the exploratory check.
- Run `ntpath.relpath` on a Windows-style pair of paths to document the root cause in the test's comment.

Expected counterexample: `filePath == '.github\\workflows\\deploy.yml'`.

### Fix Checking

For all inputs where the bug condition holds, the fixed function returns `/`-separated paths.

```pascal
FOR ALL X WHERE isBugCondition(X) DO
  result := _seed_collect_files'(X.starter)
  ASSERT every result[i].filePath contains no '\'
  ASSERT every result[i].filePath = X.native_path[i] with '\' replaced by '/'
END FOR
```

### Preservation Checking

For inputs outside the bug condition, the fixed function equals the original.

```pascal
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT _seed_collect_files'(X) = _seed_collect_files(X)
END FOR
```

Property-based testing is used because the input space (arbitrary path segments, arbitrary strings) is large and the invariants are simple. The preservation check is the identity property for `sep='/'`, plus a real-tree comparison against `os.path.relpath` on the Linux host.

### Unit Tests (`tests/test_create_repo_seed_paths.py`)

- `_to_codecommit_path('.github\\workflows\\deploy.yml', sep='\\')` returns `.github/workflows/deploy.yml` (requirement 4.2).
- `_to_codecommit_path('README.md', sep='\\')` returns `README.md` (4.3).
- `_to_codecommit_path('weird\\name.txt', sep='/')` returns `weird\name.txt` (4.4).
- `altsep='/'` with `sep='\\'` (the Windows pair) yields the same result as `sep='\\'` alone.
- Real-tree test: create nested directories and files under `tmp_path`, call `_seed_collect_files`, and assert every `filePath` is relative, `/`-separated, and has no `..` segment, and that the set of paths equals the expected set (4.6).
- Wiring test (addition, see below): patch `os.path.relpath` to return the Windows form and assert `_seed_collect_files` still returns `/`-separated paths.

### Property-Based Tests

- Property 1 (4.5): `st.lists(segment, min_size=1)` where `segment` is non-empty text that excludes `/`, `\`, and NUL. `_to_codecommit_path('\\'.join(segments), sep='\\') == '/'.join(segments)`. Run with `@settings(max_examples=200)`, matching the existing tests.
- Property 2: for any text `s`, `_to_codecommit_path(s, sep='/') == s`.

### Integration Tests

No automated integration test calls AWS. End-to-end verification is the manual Windows run in requirement 6, done by the maintainer before release, for both providers:

1. Run `./cli/create_repo.py <throwaway-name>` and `./cli/create_repo.py <throwaway-name> --provider github`, seeded from the same starter.
2. `git clone`, then `git checkout dev` and `git checkout test`. Both must succeed.
3. `git ls-tree -r --name-only origin/dev` must list nested `/` paths and no names containing `\`.
4. Delete both throwaway repositories.

### Additions Beyond requirements.md

- **Wiring test.** requirements.md 4.6 asks for a real-tree test. A real tree on Linux cannot produce `\` from `os.path.relpath`, so it would still pass if the helper call were removed. The design adds a wiring test that patches `os.path.relpath` to return the Windows form. This is the test that fails on the unfixed code. requirements.md gains item 4.8 to match.
