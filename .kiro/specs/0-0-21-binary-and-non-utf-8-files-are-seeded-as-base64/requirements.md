# Requirements: Binary and Non-UTF-8 Files Are Seeded as Base64

## Introduction

When `create_repo.py` seeds a repository from a starter, any file whose bytes are not valid UTF-8 (a PNG, an archive, a compiled asset, a Latin-1 text file) is committed as its base64 text instead of its original bytes. This is reported in [issue #11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11). The decisions behind these requirements are locked in [PLAN.md](PLAN.md). The same change also resolves [issue #10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10) (GitHub seeding writes files in text mode), which PLAN.md Decision 1 folds into this spec.

`RepositoryCreator._seed_collect_files` (`cli/create_repo.py`) reads each file as bytes, keeps the content as text when it is valid UTF-8, and otherwise base64-encodes it into a `str`. That `str` is the `fileContent` given to CodeCommit `create_commit`. boto3 encodes a `str` blob as UTF-8 and then base64-encodes it for the wire, so CodeCommit stores the base64 text (reproduced offline in PLAN.md Section 2). For GitHub, `GitHubUtils.create_init_commit` (`cli/lib/gh_utils.py`) opens each file in `'w'` mode because `fileContent` is always a `str`, so the clone also receives the base64 text. The `'wb'` branch is never taken. In text mode on Windows the same call uses the locale code page and rewrites `\n` as `\r\n`.

Two further steps change file bytes on Windows before or after the seeding step. During extraction, `Path.write_text` (`cli/create_repo.py`, in `_download_and_extract_into`) rewrites `\n` as `\r\n`, so a CRLF line ending becomes `\r\r\n`. All four public starters contain at least one CRLF file (for example `.gitignore`). In the GitHub seeding clone, `git add .` on a machine with `core.autocrlf=true` can convert CRLF to LF in the commit. Setting `core.autocrlf false` after the clone is not enough, because the clone has already written its own tracked files (the repository `README.md`) with CRLF, and `git add .` then stages them as modified (reproduced in PLAN.md Section 5). The setting must be in effect from the first checkout. Separately, `GitHubUtils.create_branch_structure` writes the bootstrap README in text mode (`cli/lib/gh_utils.py`), the same defect as [issue #10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10).

**Bug condition C(X):** a file in the starter is not valid UTF-8 (any platform, either provider), OR the platform is Windows AND the starter contains a file classified as text by the extraction step, OR the provider is GitHub AND the seeding machine has `core.autocrlf=true` AND the starter contains a CRLF file, OR the platform is Windows AND the provider is GitHub (the bootstrap README is written in text mode).

The fix keeps file content as `bytes` from extraction through both providers. `_seed_collect_files` returns the file's bytes unchanged. `create_init_commit` always writes in `'wb'`, and the seeding clone is created with `core.autocrlf=false` from the first checkout. `create_branch_structure` writes the README with explicit UTF-8 and no newline translation. Extraction writes every member with `write_bytes`, and the text-or-binary heuristic that becomes unused is removed.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `_seed_collect_files` reads a file whose bytes are not valid UTF-8 THEN the system returns `fileContent` as a base64 `str` of the file's bytes instead of the bytes

1.2 WHEN `_seed_repository_codecommit` sends such an entry in `putFiles` THEN boto3 UTF-8-encodes and base64-encodes the base64 `str`, and CodeCommit stores the base64 text instead of the original file

1.3 WHEN `_seed_repository_github` passes such an entry to `GitHubUtils.create_init_commit` THEN the system opens the file with `'w'` (the `'wb'` branch is unreachable because `fileContent` is always a `str`) and writes the base64 text into the clone

1.4 WHEN `create_init_commit` writes a `str` on Windows THEN the system opens the file without `encoding` or `newline`, so it uses the locale code page (which can raise `UnicodeEncodeError` for UTF-8 content or write bytes that are no longer UTF-8) and rewrites `\n` as `\r\n`

1.5 WHEN extraction runs on Windows and a member is classified as text THEN `Path.write_text` rewrites `\n` as `\r\n`, so a CRLF line ending reaches the seeding step as `\r\r\n`

1.6 WHEN `git add .` runs in the GitHub seeding clone on a machine where `core.autocrlf` is `true` THEN git can convert CRLF to LF, so the committed file differs from the starter

1.7 WHEN `GitHubUtils.create_branch_structure` writes the bootstrap README on Windows THEN the system opens it with `open(readme_path, 'w')` without `encoding` or `newline`, so it uses the locale code page and rewrites `\n` as `\r\n`

1.8 WHEN any of 1.1 to 1.7 occurs THEN the system still reports that the repository was seeded successfully, because nothing compares the stored content with the starter

### Expected Behavior (Correct)

2.1 WHEN `_seed_collect_files` runs THEN the system SHALL return `fileContent` as a `bytes` object that equals the exact bytes of the file on disk, for every file, including valid UTF-8 text, non-UTF-8 text, binary content, content with a UTF-8 byte order mark, and an empty file (`b''`)

2.2 WHEN `_seed_collect_files` runs THEN the system SHALL NOT decode the content as text and SHALL NOT base64-encode it, and `cli/create_repo.py` SHALL no longer import `base64`

2.3 WHEN `_seed_repository_codecommit` calls `create_commit` THEN every entry in `putFiles` SHALL carry `fileContent` as `bytes` equal to the file's bytes

2.4 WHEN `GitHubUtils.create_init_commit` writes a file THEN the system SHALL open it in `'wb'` mode for every entry and write the bytes unchanged, with no text-mode open, no `encoding` argument, and no newline translation on any platform

2.5 WHEN `GitHubUtils.create_init_commit` receives an entry whose `fileContent` is a `str` THEN the system SHALL encode it as UTF-8 and write the result in `'wb'` mode

2.6 WHEN `GitHubUtils.create_init_commit` clones the repository THEN the system SHALL clone with `gh repo clone <repo_name> <git_dir> -- -c core.autocrlf=false`, so `core.autocrlf` is `false` from the first checkout and is stored in the clone's configuration, and SHALL NOT rely on a `git config core.autocrlf` call made after the clone

2.7 WHEN extraction writes a zip member to the temporary directory THEN the system SHALL write the member's bytes with `write_bytes`, for every member and for every source type (S3 and GitHub, with or without common-prefix stripping), without decoding them

2.8 WHEN extraction runs THEN `text_extensions`, `is_text_file`, and the `RepositoryCreator._is_binary_string` method SHALL no longer exist in `cli/create_repo.py`

2.9 WHEN a repository is seeded on any platform with either provider THEN the stored file content SHALL be byte-identical to the corresponding member of the starter zip, except where a `.gitattributes` file inside the starter itself specifies line-ending conversion

2.10 WHEN `_seed_collect_files` builds each entry THEN the system SHALL keep `fileMode` as `'NORMAL'` and `filePath` normalized by `_to_codecommit_path`

2.11 WHEN `GitHubUtils.create_branch_structure` writes the bootstrap README THEN the system SHALL open it with `encoding='utf-8'` and `newline=''`, so the file holds UTF-8 bytes with the `\n` line endings of `readme_content` on every platform

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a starter file is valid UTF-8 text on Linux, macOS, or WSL THEN the system SHALL CONTINUE TO store the same bytes in the repository as before this change (the previous `str` was encoded as UTF-8 by boto3 or the file write, which yields the same bytes)

3.2 WHEN `_seed_collect_files` returns THEN every `filePath` SHALL CONTINUE TO be a relative, `/`-separated path with no leading `/` and no `..` segment, as specified by the v0.0.21 separator fix ([issue #9](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/9))

3.3 WHEN `_seed_collect_files` fails to read a file THEN the system SHALL CONTINUE TO print "Error processing file", log the error, delete the CodeCommit repository for the CodeCommit provider, and exit with status 1, leaving GitHub cleanup to `create_and_seed_repository`

3.4 WHEN CodeCommit seeding runs THEN the system SHALL CONTINUE TO commit in batches of 100 files, chain `parentCommitId` between batches, delete the repository on failure, and exit non-zero on failure

3.5 WHEN GitHub seeding fails THEN the system SHALL CONTINUE TO log stderr of failed `gh` and `git` commands, raise the same `Exception` from `create_init_commit` for a failed command, and offer or perform repository cleanup and temporary directory removal as specified by the locked `issue-creating-github-repository-error-getting` spec

3.6 WHEN `create_init_commit` runs THEN the system SHALL CONTINUE TO accept the same parameters (`all_files`, `repo_name`, `seed_branch`, `author`, `email`, `git_dir`), clone the repository, set `user.name` and `user.email`, check out the seed branch, create directories as needed, run `git add .`, commit with the message `Seeding repository with {total_files} files`, and push to `origin`

3.7 WHEN extraction runs THEN the system SHALL CONTINUE TO create directories for directory entries, remove an existing file before writing, strip the common top-level prefix for GitHub sources, remove the downloaded zip file, log and print the extracted file count, and clean up and exit non-zero on failure

3.8 WHEN a repository is initialized with the README (`put_file` or `create_commit` with `readme_content`) THEN the system SHALL CONTINUE TO pass the README as a `str`, unchanged by this fix

3.9 WHEN a repository is seeded and merging is enabled THEN the system SHALL CONTINUE TO merge `dev` into `test` as specified in the v0.0.18 auto-merge feature

3.10 WHEN `create_repo.py` is invoked THEN the system SHALL CONTINUE TO accept the same command-line options with the same behavior

3.11 WHEN `GitHubUtils.create_branch_structure` runs THEN the system SHALL CONTINUE TO clone the repository, configure `user.name` and `user.email`, create the `main`, `test`, and `dev` branches with the README on `main`, push each branch, log failed commands with stderr, and remove its temporary directory, with the clone command unchanged (it does not receive `-c core.autocrlf=false`)

---

## Testing Requirements

4.1 Tests SHALL run on Linux under the existing pytest and Hypothesis setup (`cli/requirements-test.txt`) and SHALL NOT require Windows, AWS, GitHub, or network access

4.2 The two tests in `tests/test_create_repo_seed_paths.py` that encode the previous behavior (`test_utf8_file_content_is_text_and_mode_is_normal` and `test_non_utf8_file_content_is_base64_text_and_mode_is_normal`) SHALL be updated to assert `bytes` content equal to the file's bytes and `fileMode` `'NORMAL'`, and the unused `import base64` in that file SHALL be removed. These updates supersede requirement 3.4 of the separator-fix spec for `fileContent`.

4.3 A property-based test SHALL generate arbitrary `bytes`, write them to a file in a temporary tree, call `_seed_collect_files`, and assert the returned `fileContent` is a `bytes` object equal to the input (requirements 2.1 and 2.2)

4.4 Unit tests SHALL cover, through `_seed_collect_files`: a binary payload generated in the test (PNG signature, NUL bytes, and `0xFF`), non-UTF-8 text (Latin-1 encoded), valid UTF-8 text, content that starts with a UTF-8 byte order mark, and an empty file. No binary fixture SHALL be committed to the repository (PLAN.md D2).

4.5 A test SHALL call `GitHubUtils.create_init_commit` against a real temporary directory with `subprocess.run` patched, and assert that the written files are byte-identical to the input for `bytes` entries (including `\r\n` and non-UTF-8 content) and for a non-ASCII `str` entry (requirements 2.4 and 2.5)

4.6 A test SHALL record the `subprocess.run` calls made by `create_init_commit` and assert that the clone command is `gh repo clone <repo_name> <git_dir> -- -c core.autocrlf=false` and that no call runs `git config core.autocrlf` (requirement 2.6)

4.7 A test SHALL run `_seed_repository_codecommit` with a mocked CodeCommit client and assert that every `putFiles[*]['fileContent']` passed to `create_commit` is `bytes` equal to the file's bytes (requirement 2.3)

4.8 A test SHALL build a zip in a temporary directory that contains a CRLF text member, a non-UTF-8 member, and a binary member, run `_download_and_extract_into` with the download stubbed, and assert the extracted files are byte-identical to the zip members. The test SHALL patch `Path.write_text` to raise, so that reintroducing a text-mode write fails the test (requirements 2.7 and 2.9). Both the S3 branch and the GitHub common-prefix branch SHALL be covered.

4.9 A test SHALL assert that `RepositoryCreator` no longer has `_is_binary_string` and that `cli/create_repo.py` does not import `base64` (requirements 2.2 and 2.8)

4.10 Existing tests in `tests/` and `cli/lib/test_*.py` SHALL continue to pass, including the tests that mock `create_init_commit` and `_seed_collect_files`

4.11 A test SHALL call `GitHubUtils.create_branch_structure` against a real temporary directory with `subprocess.run` patched (and the temporary directory creation redirected to a test-owned path), and assert that the README file bytes equal `readme_content.encode('utf-8')` and contain no `\r` (requirement 2.11)

---

## Version and Documentation Requirements

5.1 `cli/create_repo.py` and `cli/lib/gh_utils.py` SHALL each have their `VERSION` marker reviewed per `.kiro/steering/ascs-cli-script-versioning.md`. If the embedded date differs from the implementation date, the PATCH number SHALL be incremented and the date set to the implementation date (bug fix, no interface change, because `create_init_commit` still accepts `str`). If the date already matches, the marker SHALL stay unchanged.

5.2 `CHANGELOG.md` SHALL gain `### Fixed` entries under `v0.0.21 (unreleased)` for `create_repo.py` and for `lib/gh_utils.py` that link this spec, address [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11) and [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10), and describe the byte-for-byte seeding, the extraction change, the clone-time `core.autocrlf=false`, and the README write. Existing changelog text SHALL NOT be edited. The entry versions SHALL match the `VERSION` markers.

5.3 The CHANGELOG entry SHALL state that repositories already seeded from a starter that contained binary or non-UTF-8 files hold base64 text for those files, that this update does not repair them, and that they must be deleted and recreated, or have those files re-committed

5.4 Changed or new Python functions SHALL carry docstrings that follow `.kiro/steering/documentation-standards-python.md`. The `_seed_collect_files` docstring SHALL state that `fileContent` is `bytes`, and the `create_init_commit` docstring SHALL state that `fileContent` may be `bytes` or `str`.

5.5 `README.md`, `docs/`, and `AGENTS-FOR-END-USE.md` SHALL NOT change (PLAN.md D7)

5.6 Implementation SHALL start after the uncommitted changes to `cli/create_repo.py` and `cli/lib/gh_utils.py` from the `issue-creating-github-repository-error-getting` spec are committed, or after the maintainer confirms the order (PLAN.md Section 6, item 10)

---

## Verification Requirements

6.1 Before release, the maintainer SHALL seed a throwaway CodeCommit repository and a throwaway GitHub repository (`--provider github`) on Linux or macOS from a test zip that contains a small PNG and a non-UTF-8 text file, and SHALL compare each committed file with the original by checksum (for example `sha256sum` after `git clone` and `git checkout dev`) (R1)

6.2 Before release, the maintainer SHALL repeat the run on Windows Git Bash (`.ve` venv) for both providers, from a starter that contains a CRLF file such as `.gitignore`, and SHALL confirm the committed bytes equal the starter's bytes with no `\r\r\n` and no CRLF-to-LF change, with `core.autocrlf` set to `true` in the maintainer's global git configuration (R2). For the GitHub provider the run SHALL also confirm that the repository's bootstrap `README.md` on `main` has LF line endings and that the seeding commit on `dev` does not change that README's line endings unless the starter supplies its own `README.md`

6.3 The maintainer SHALL confirm that the seeded `test` branch, fast-forwarded from `dev`, holds the same bytes

6.4 The maintainer SHALL delete every throwaway repository after verification. The implementing agent SHALL NOT create or delete repositories without the maintainer's go-ahead.

---

## Out of Scope

- Preserving the executable bit (`fileMode: EXECUTABLE`), noted only (PLAN.md Decision 5)
- Zip extraction path check (`..` and absolute member names), tracked in [#12](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/12). This spec edits the same extraction loop, so the two changes must merge cleanly.
- A content-integrity check after seeding, or a check of each file against the 6 MB CodeCommit per-file limit before sending
- Repair tooling or troubleshooting documentation for repositories already seeded with base64 content (PLAN.md D6)
- A Windows runner in CI
- Changes to `README.md`, `docs/`, or `AGENTS-FOR-END-USE.md`
