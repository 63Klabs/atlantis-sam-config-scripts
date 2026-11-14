# Binary and Non-UTF-8 Files Are Seeded as Base64 - Bugfix Design

## Overview

`RepositoryCreator._seed_collect_files` (`cli/create_repo.py`) returns each starter file's content as UTF-8 text when it decodes, and as base64 text when it does not. That `str` becomes `fileContent` for CodeCommit `create_commit` and for `GitHubUtils.create_init_commit`. boto3 encodes a `str` blob as UTF-8 and then base64-encodes it for the wire, so CodeCommit stores the base64 text. `create_init_commit` opens each file in `'w'` mode (its `'wb'` branch is unreachable), so the GitHub clone also receives the base64 text ([issue #11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11)).

The fix keeps content as `bytes` end to end:

- `_seed_collect_files` returns the file's bytes unchanged.
- `create_init_commit` always writes in `'wb'`, and the seeding clone is created with `core.autocrlf=false` ([issue #10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10) is folded in).
- Extraction writes every zip member with `write_bytes`, which removes the Windows `\n` to `\r\n` rewrite that turns CRLF into `\r\r\n`. The text-or-binary heuristic that this makes unused is deleted.
- `create_branch_structure` writes its README with `encoding='utf-8'` and `newline=''`.

No CLI option, function signature, or AWS call changes. The decisions behind this design are locked in [PLAN.md](PLAN.md) (Decisions 1 to 7), and the numbered requirements are in [requirements.md](requirements.md).

## Glossary

- **Bug_Condition (C)**: A starter file is not valid UTF-8 (any platform, either provider), OR the platform is Windows and extraction writes a text-classified member, OR the provider is GitHub and the machine has `core.autocrlf=true` and the starter has a CRLF file, OR the platform is Windows and the provider is GitHub (bootstrap README).
- **Property (P)**: The bytes stored in the repository for every starter file equal the bytes of the zip member.
- **Preservation**: Valid UTF-8 text on Linux, macOS, and WSL is stored with the same bytes as before. Paths, modes, batching, cleanup, merge, and CLI options are unchanged.
- **`fileContent`**: The key in each `putFiles` entry (and in each `all_files` entry given to `create_init_commit`) that holds a file's content. Becomes `bytes`.
- **Wire form**: What boto3 puts in the JSON request. A blob is base64-encoded by the serializer. A `str` is UTF-8-encoded first.
- **`core.autocrlf`**: Git setting that converts line endings at checkout and `git add`. `true` is the Git for Windows installer default.

## Bug Details

### Bug Condition

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type SeedRun (platform, provider, git autocrlf setting, starter files)
  OUTPUT: boolean
  RETURN EXISTS file IN X.starter WHERE file.bytes is not valid UTF-8
      OR (X.platform = 'windows' AND EXISTS file IN X.starter WHERE file is classified as text by extraction)
      OR (X.provider = 'github' AND X.autocrlf = true AND EXISTS file IN X.starter WHERE file.bytes contains CRLF)
      OR (X.platform = 'windows' AND X.provider = 'github')
END FUNCTION
```

The last clause covers the README written by `create_branch_structure`, which runs for every GitHub run.

### Examples

| Starter file | Provider | Pre-fix stored content | Post-fix stored content |
|---|---|---|---|
| `logo.png` (`\x89PNG\r\n\x1a\n\x00\xff\xfe`) | CodeCommit | The ASCII text `iVBORw0KGgoA//4=` | The original 11 bytes |
| `logo.png` | GitHub | The ASCII text `iVBORw0KGgoA//4=` | The original 11 bytes |
| `notes.txt` encoded as Latin-1 (`caf\xe9`) | Either | The ASCII text `Y2Fm6Q==` | `caf\xe9` |
| `README.md`, UTF-8 | Either, Linux | The UTF-8 bytes | The same UTF-8 bytes (preserved) |
| `.gitignore` with `a\r\nb\r\n` | Either, Windows | `a\r\r\nb\r\r\n` (extraction `write_text`) | `a\r\nb\r\n` |
| `.gitignore` with `a\r\nb\r\n` | GitHub, any platform with global `autocrlf=true` | `a\nb\n` (`git add` converts CRLF to LF, reproduced in a scratch repository) | `a\r\nb\r\n` |
| Empty file | Either | Empty | Empty |
| Repository README (bootstrap) | GitHub, Windows | `\r\n` line endings, locale code page | `\n` line endings, UTF-8 |

## Expected Behavior

### Preservation Requirements

- **UTF-8 text on POSIX:** the stored bytes are identical to before (requirement 3.1). Previously the `str` was UTF-8-encoded by boto3 or by the file write. Now the same bytes are passed directly.
- **Paths and modes:** `filePath` normalization by `_to_codecommit_path` and `fileMode: 'NORMAL'` are unchanged (2.10, 3.2).
- **Error handling:** the read-failure branch of `_seed_collect_files`, the 100-file batching and repository deletion in CodeCommit seeding, and GitHub cleanup are unchanged (3.3 to 3.5).
- **`create_init_commit` contract:** same parameters, same git sequence, same commit message and push, same failure logging and exception text (3.6).
- **Extraction layout:** directory creation, unlink-before-write, GitHub prefix stripping, zip removal, and file count reporting are unchanged (3.7).
- **README for repository initialization** in `create_repo.py` stays a `str` (3.8). Auto-merge and CLI options are unchanged (3.9, 3.10). `create_branch_structure` keeps its clone, branches, and cleanup (3.11).

## Hypothesized Root Cause

This is a confirmed cause, not a hypothesis.

1. **Base64 fallback.** `_seed_collect_files` (`cli/create_repo.py`) tries `content.decode('utf-8')` and falls back to `base64.b64encode(content).decode('utf-8')`. The fallback came in with the first CodeCommit seeding code (`2805697`, 2025-01-22). It looks like a workaround for a belief that `fileContent` must be a JSON-safe string, which is wrong: boto3 accepts `bytes` and base64-encodes it on the wire. An offline probe with a `before-send.codecommit.CreateCommit` hook (boto3 in `.ve`, Python 3.12.3) showed the wire form for the bytes `b'\x89PNG\r\n\x1a\n\x00\xff\xfe'` is `iVBORw0KGgoA//4=`, while for the base64 `str` it is `aVZCT1J3MEtHZ29BLy80PQ==`, which decodes to the ASCII text `iVBORw0KGgoA//4=`.
2. **Unreachable `'wb'` branch.** `create_init_commit` chooses `'w' if isinstance(file_content, str) else 'wb'` (`5b85ea2`, 2025-06-03). `fileContent` is always a `str`, so `'wb'` never runs, and text mode on Windows adds locale-dependent encoding and newline translation.
3. **Text-mode extraction write.** `Path.write_text(decoded_content, encoding='utf-8')` has no `newline` argument. On Windows `\n` becomes `\r\n`, so existing CRLF becomes `\r\r\n` (reproduced with `open(..., newline='\r\n')`). All four public starters contain CRLF files.
4. **`core.autocrlf` ordering.** With global `autocrlf=true`, `gh repo clone` writes tracked files with CRLF. A scratch reproduction showed that running `git config core.autocrlf false` after the clone leaves the clone's `README.md` staged as modified by `git add .` (12 bytes on disk against the 10-byte LF blob). Passing `-c core.autocrlf=false` to the clone keeps the README at 10 bytes and `git add .` clean. With `autocrlf=true` throughout, a CRLF `.gitignore` is committed as LF.
5. **README bootstrap.** `create_branch_structure` writes the README with `open(readme_path, 'w')`, the same text-mode pattern.

## Correctness Properties

**Property 1: Bug Condition - Collected content equals file bytes**
For any `bytes` written to a file in a temporary tree, `_seed_collect_files` SHALL return one entry whose `fileContent` is a `bytes` object equal to the input.
**Validates: Requirements 2.1, 2.2**

**Property 2: Bug Condition - `create_init_commit` writes the given bytes**
For any list of entries whose `fileContent` is `bytes`, `create_init_commit` SHALL write each file with content equal to the input. For an entry whose `fileContent` is a `str`, it SHALL write the UTF-8 encoding of the `str`. No text-mode `open` is used, so no newline translation occurs.
**Validates: Requirements 2.4, 2.5**

**Property 3: Bug Condition - Extraction preserves member bytes**
For any `bytes` stored as a zip member, `_download_and_extract_into` SHALL create a file whose content equals the member's bytes, for the S3 branch and for the GitHub common-prefix branch, and `Path.write_text` SHALL NOT be called.
**Validates: Requirements 2.7, 2.9**

**Property 4: Preservation - Valid UTF-8 text is stored with the same bytes as before**
For any text `t` that is valid UTF-8, the new `fileContent` for a file holding `t.encode('utf-8')` SHALL equal `t.encode('utf-8')`, which is the content the previous `str` produced after boto3 or the file write encoded it.
**Validates: Requirements 3.1**

**Property 5: Clone-time autocrlf**
`create_init_commit` SHALL clone with `-- -c core.autocrlf=false` and SHALL NOT run `git config core.autocrlf`.
**Validates: Requirements 2.6**

**Property 6: Bootstrap README bytes**
`create_branch_structure` SHALL write README bytes equal to `readme_content.encode('utf-8')` with no `\r` that is not in `readme_content`.
**Validates: Requirements 2.11**

## Fix Implementation

### Changes Required

**Change 1: `_seed_collect_files` returns bytes** (`cli/create_repo.py`)

```python
# Before
try:
    with open(full_path, 'rb') as f:
        content = f.read()

    try:
        file_content = content.decode('utf-8')
    except UnicodeDecodeError:
        file_content = base64.b64encode(content).decode('utf-8')

    all_files.append({
        'filePath': relative_path,
        'fileContent': file_content,
        'fileMode': 'NORMAL'
    })
except Exception as e:
    ...

# After
try:
    with open(full_path, 'rb') as f:
        file_content = f.read()

    all_files.append({
        'filePath': relative_path,
        'fileContent': file_content,
        'fileMode': 'NORMAL'
    })
except Exception as e:
    ...
```

The `except` block, the cleanup call, and `sys.exit(1)` are untouched. The one-line docstring becomes a Google-style docstring (per `.kiro/steering/documentation-standards-python.md`) that states `fileContent` is `bytes` and gives an example. The unused `import base64` at the top of the module is removed. A search shows `base64` has no other use in `cli/create_repo.py`.

**Change 2: Extraction writes bytes** (`cli/create_repo.py`, `_download_and_extract_into`)

The block from `text_extensions = {...}` through the `is_text_file` branches is replaced. The `with zip_ref.open(zip_info) as source:` structure stays, so the diff is the deleted lines only.

```python
# After
with zip_ref.open(zip_info) as source:
    content = source.read()

    if output_path.exists():
        output_path.unlink()

    output_path.write_bytes(content)
```

Deleted: the `text_extensions` set, the `is_text_file` expression, and the `decode`/`write_text`/`UnicodeDecodeError` branches. The unlink of an existing file stays so a repeated member name still replaces the earlier file, as before. The directory-entry branch (`zip_info.filename.endswith('/')`) and `output_path.parent.mkdir(...)` above this block are untouched.

**Change 3: Remove `_is_binary_string`** (`cli/create_repo.py`)

Delete the `_is_binary_string` method. A search of `cli/` and `tests/` shows its only caller was the deleted expression. Its sample-length ratio was also miscalculated for files over 1 KB, which no longer matters.

**Change 4: `create_init_commit` clones with autocrlf off and always writes bytes** (`cli/lib/gh_utils.py`)

```python
# Before
subprocess.run(
    ["gh", "repo", "clone", repo_name, git_dir],
    check=True, capture_output=True
)
...
with open(full_path, 'w' if isinstance(file_content, str) else 'wb') as f:
    f.write(file_content)

# After
# core.autocrlf=false is set at clone time so the clone's own tracked files are
# checked out without line-ending conversion and "git add ." does not restage them
subprocess.run(
    ["gh", "repo", "clone", repo_name, git_dir, "--", "-c", "core.autocrlf=false"],
    check=True, capture_output=True
)
...
if isinstance(file_content, str):
    file_content = file_content.encode('utf-8')
with open(full_path, 'wb') as f:
    f.write(file_content)
```

Design notes:
- `gh repo clone <repo> <dir> -- <gitflags>` forwards flags to `git clone`, and `-c` on `git clone` is stored in the clone's `.git/config` (verified in a scratch repository). `merge_branches_fast_forward` reuses this clone and does not convert line endings, so it is unaffected.
- The `user.name`, `user.email`, `checkout`, `add`, `commit`, and `push` calls and the failure handling are unchanged. The failure message now includes the extra clone arguments through `_format_failed_command`, which reads the actual failed command.
- The `str` branch keeps the function backward compatible (PLAN.md D3). The docstring states that `fileContent` is `bytes` or `str`.
- `create_branch_structure` also clones, but it only commits a README written by this script, so its clone command is unchanged (requirement 3.11).

**Change 5: README bootstrap write** (`cli/lib/gh_utils.py`, `create_branch_structure`)

```python
# Before
with open(readme_path, 'w') as f:
    f.write(readme_content)

# After
with open(readme_path, 'w', encoding='utf-8', newline='') as f:
    f.write(readme_content)
```

`newline=''` disables translation, so the `\n` characters in `readme_content` are written as `\n` on every platform.

**Change 6: Versions and CHANGELOG**

Per `.kiro/steering/ascs-cli-script-versioning.md`, each file's marker is compared with the implementation date. If it differs, the PATCH number is incremented and the date set. If it matches, the marker stays. Both files are bug fixes with no interface change. Draft CHANGELOG entries under `## v0.0.21 (unreleased)` / `### Fixed`, with versions set by the rule at implementation time:

```markdown
- **Script: create_repo.py vX.X.X** - Fixed binary and non-UTF-8 files in application starters being seeded as base64 text instead of their original bytes in both CodeCommit and GitHub repositories [Spec: 0-0-21-binary-and-non-utf-8-files-are-seeded-as-base64](.kiro/specs/0-0-21-binary-and-non-utf-8-files-are-seeded-as-base64/), addresses [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11)
  - File content is now kept as bytes from extraction through seeding. Text files are no longer decoded and re-encoded.
  - Extracted files are written as bytes, so on Windows existing CRLF line endings are no longer turned into `\r\r\n`.
  - Repositories already seeded from a starter that contained binary or non-UTF-8 files hold base64 text for those files. This update does not repair them. Delete and recreate them, or re-commit those files.
- **Library: gh_utils.py vX.X.X** - Fixed GitHub seeding writing files in text mode, which on Windows used the locale code page and rewrote line endings [Spec: 0-0-21-binary-and-non-utf-8-files-are-seeded-as-base64](.kiro/specs/0-0-21-binary-and-non-utf-8-files-are-seeded-as-base64/), addresses [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10) and [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11)
  - `create_init_commit` writes every file as bytes (a `str` is encoded as UTF-8) and clones with `core.autocrlf=false`, so the seeded files match the starter regardless of the user's git line-ending settings.
  - `create_branch_structure` writes the bootstrap README as UTF-8 with `\n` line endings on every platform.
```

The CHANGELOG already holds entries for `create_repo.py` v0.2.1 and v0.2.5 and `gh_utils.py` v0.2.0 in this version. The new entries are added next to them without editing existing text.

### Files Not Changed

`README.md`, `docs/`, `AGENTS-FOR-END-USE.md`, the zip path check in extraction (tracked in [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12)), `_to_codecommit_path`, the CodeCommit batching code, and the `create_branch_structure` clone command.

## Testing Strategy

### Validation Approach

Two phases: first show the new tests fail on the unfixed code (exploratory), then show they pass after the fix and that preserved behavior holds. Everything runs on Linux with pytest and Hypothesis and needs no AWS, GitHub, or network access (requirement 4.1).

Test infrastructure follows the existing files:

- `RepositoryCreator` is built with `RepositoryCreator.__new__(RepositoryCreator)`, as in `tests/test_create_repo_seed_paths.py` and `tests/test_create_repo_download_failure_cleanup.py`. Extraction tests set `source_type`, `source`, `s3_client`, `is_bucket_public`, and patch `create_repo.Log` and `create_repo.click.echo`, with `s3_client.download_file.side_effect` writing a real zip, as the existing `write_bad_zip` helper does.
- `GitHubUtils` tests import `from lib.gh_utils import GitHubUtils` (as `tests/test_gh_utils.py` does) and patch `subprocess.run`. The `cli/lib/test_gh_utils_stderr_logging.py` file imports the module as `gh_utils` instead. New tests go under `tests/`, so they patch `lib.gh_utils.subprocess.run` and `lib.gh_utils.Log`.
- Hypothesis tests that write files create their directory with `tempfile.TemporaryDirectory()` inside the test body, not with the function-scoped `tmp_path` fixture, to avoid the `function_scoped_fixture` health check. They use `@settings(max_examples=200)` as the existing tests do, with a lower count for tests that build zips.

### Exploratory Bug Condition Checking

Goal: show the defect on the unfixed code before implementing.

- Property 1 on the unfixed code: `_seed_collect_files` returns a `str` for a non-UTF-8 file. Expected counterexample: `fileContent == 'iVBORw0KGgoA//4='` for the PNG-like bytes.
- Extraction test with `Path.write_text` patched to raise: on the unfixed code a text-classified member (`.gitignore` with CRLF) reaches `write_text` and the test fails on Linux. This is the Linux-visible proof of the Windows defect.
- `create_init_commit` clone test: on the unfixed code the clone command has no `-- -c core.autocrlf=false`.
- `create_branch_structure` test: the unfixed `open(readme_path, 'w')` call passes no `encoding` or `newline`. On Linux the bytes are already correct, so this test asserts the `open` arguments by patching `builtins.open` with a wrapper that records them and delegates to the real `open`.

### Fix Checking

```pascal
FOR ALL X WHERE isBugCondition(X) DO
  FOR EACH file IN X.starter DO
    stored := stored_bytes(seed'(X), file)
    ASSERT stored = file.zip_member_bytes
  END FOR
END FOR
```

On Linux CI this is checked by the mechanism tests above (bytes in, bytes out, no text-mode write, clone arguments). The end-to-end statement is checked by the maintainer's runs R1 and R2 (requirements 6.1 to 6.3).

### Preservation Checking

```pascal
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT seed'(X) = seed(X)
END FOR
```

Property-based test (Property 4) compares the new `fileContent` bytes with `text.encode('utf-8')` for generated text, which is what the old `str` encoded to. Example tests keep the existing assertions that `filePath` values are `/`-separated and `fileMode` is `'NORMAL'`.

### Unit Tests

In `tests/test_create_repo_seed_paths.py`:

- Replace `test_utf8_file_content_is_text_and_mode_is_normal` with a test that asserts `fileContent == text.encode('utf-8')`, a `bytes` instance, and `fileMode == 'NORMAL'` (requirement 4.2).
- Replace `test_non_utf8_file_content_is_base64_text_and_mode_is_normal` with a test that asserts `fileContent == raw` for non-UTF-8 bytes. Remove `import base64`.
- Add tests for a PNG-like payload (signature, NUL, `0xFF`), Latin-1 text, a file with a UTF-8 byte order mark, and an empty file (requirement 4.4). Binary data is generated in the test (PLAN.md D2).
- Add a test that `create_repo` has no `base64` attribute and that `RepositoryCreator` has no `_is_binary_string` (requirement 4.9).

In a new `tests/test_create_repo_byte_fidelity.py` (name follows the existing `test_create_repo_*` files):

- CodeCommit test: build a creator with a mocked `codecommit_client` (`get_branch` returning a branch dict with a `commitId`, and `create_commit` returning a `commitId`), run `_seed_repository_codecommit` on a temporary tree, and assert every `putFiles[*]['fileContent']` in `create_commit` calls is `bytes` equal to the file bytes (requirement 4.7).
- Extraction tests (S3 branch and GitHub common-prefix branch): a zip with a CRLF `.gitignore`, a Latin-1 `notes.txt`, and a PNG-like `logo.png`; assert extracted bytes equal the members and `Path.write_text` was never called (requirement 4.8). The GitHub branch stubs `GitHubUtils.download_zip_from_url` to write the zip and uses a zip whose members share one top-level directory.

In a new `tests/test_gh_utils_byte_fidelity.py`:

- `create_init_commit` with `subprocess.run` patched and a real `git_dir` under `tmp_path`: entries with `bytes` (including `\r\n` and `0xFF`) and a non-ASCII `str`; assert written bytes (requirement 4.5).
- Clone arguments test: the recorded calls contain `["gh", "repo", "clone", repo, git_dir, "--", "-c", "core.autocrlf=false"]` and none starts with `["git", "config", "core.autocrlf"`; `user.name` and `user.email` calls remain (requirements 2.6, 3.6, 4.6).
- `create_branch_structure` test: `tempfile.mkdtemp` is patched to return a directory under `tmp_path`, the test first calls `monkeypatch.chdir(tmp_path)` so the function's own `os.chdir` calls are undone at teardown, and `subprocess.run` is patched with a side effect that reads `README.md` when it sees the `git add README.md` call. Assert the bytes equal `readme_content.encode('utf-8')` and contain no `\r` (requirement 4.11). The `finally` block removes the directory, which is why the side effect captures the bytes while it still exists.

### Property-Based Tests

- Property 1: `st.binary()` written to a file in a `TemporaryDirectory`, `_seed_collect_files` returns `fileContent == data` (bytes).
- Property 2: `st.lists(st.one_of(st.binary(), st.text()))` as `fileContent` values into `create_init_commit`; assert each written file equals the bytes or `text.encode('utf-8')`. `st.text()` is restricted to characters that encode as UTF-8 (surrogates excluded) with `st.characters(blacklist_categories=('Cs',))`.
- Property 3: `st.binary()` as the member of a one-file zip through `_download_and_extract_into`; assert extracted bytes equal the input. Uses a small `max_examples`.
- Property 4: `st.text(alphabet=st.characters(blacklist_categories=('Cs',)))` written as UTF-8; assert collected `fileContent == text.encode('utf-8')`.

### Integration Tests

No automated integration test calls AWS or GitHub. End-to-end verification is the maintainer's manual runs (requirements 6.1 to 6.4):

1. **R1 (Linux or macOS).** Build a zip with a small PNG, a Latin-1 text file, and a CRLF `.gitignore`. Host it at an S3 location the maintainer controls. Run `./cli/create_repo.py <throwaway-name> --source s3://<bucket>/<key>.zip` and the same with `--provider github`. `git clone`, `git checkout dev` and `git checkout test`, and compare `sha256sum` of each file with the original. Delete both throwaway repositories.
2. **R2 (Windows Git Bash).** Repeat both provider runs with `git config --global core.autocrlf true`. Compare checksums, check that no file contains `\r\r\n`, check that the bootstrap `README.md` on `main` has LF endings, and check that the seeding commit on `dev` does not change that README unless the starter supplies one.

### Additions Beyond requirements.md

- **Test layout.** requirements.md names behaviors, not files. The design puts the CodeCommit, extraction, and `create_init_commit` tests in two new files, `tests/test_create_repo_byte_fidelity.py` and `tests/test_gh_utils_byte_fidelity.py`, so the existing seed-path file keeps its focus on paths and content collection.
- **`builtins.open` recorder for the README test.** On Linux the README bytes are correct before and after the fix, so a bytes assertion alone cannot fail on the unfixed code. The design adds an assertion on the `open` arguments (`encoding='utf-8'`, `newline=''`) next to the bytes assertion in the `create_branch_structure` test.
- **Hypothesis fixture note.** Property tests that write files use `TemporaryDirectory()` rather than `tmp_path`, to avoid the function-scoped fixture health check.
- **CHANGELOG draft.** requirements.md 5.2 and 5.3 require the entries. The design gives the draft text above, with version numbers left to the versioning rule at implementation time.
