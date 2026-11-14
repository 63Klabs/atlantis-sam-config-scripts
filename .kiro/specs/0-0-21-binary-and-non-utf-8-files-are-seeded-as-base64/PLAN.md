# Binary and non-UTF-8 files are seeded as base64 text instead of bytes

> **Status**: Locked, 2026-11-14 (reopened and re-locked the same day for Q6 and Q7)
> **Issue**: [ISSUE.md](ISSUE.md) (GitHub issue #11)
> **Reviewed against**: `dev` at `5abe0ef` on 2026-11-14. The working tree has uncommitted changes to `cli/create_repo.py` (`v0.2.5`) and `cli/lib/gh_utils.py` (`v0.2.0`) from the locked spec `0-0-21-issue-creating-github-repository-error-getting`. Line numbers below are from the working tree, not from `main` at `480e089` as in the issue.

## 1. Summary

`RepositoryCreator._seed_collect_files` reads each starter file as bytes. If the bytes are not valid UTF-8, it base64-encodes them into a `str` and returns that as `fileContent`. Both providers then treat that `str` as the file content. For CodeCommit, botocore encodes the `str` as UTF-8 and base64-encodes it again on the wire, so the repository stores the base64 text, not the original bytes (reproduced offline, Section 2). For GitHub, `create_init_commit` writes the `str` in text mode, so the clone gets the same base64 text. Any PNG, archive, compiled asset, or non-UTF-8 text file in a starter is corrupted, on every platform and both providers.

None of the four public Atlantis starters contain a non-UTF-8 file today (checked from the published S3 zips), so the live impact is limited to custom starters supplied through `--source` or an organization's own starter list. The same scan found CRLF line endings in `.gitignore` and `buildspec.yml` files of every starter. That matters for the "original bytes" goal because the extraction step rewrites text files through a text-mode write that doubles the CR on Windows (Section 3, Section 5).

The recommended fix keeps file content as `bytes` from extraction through both providers, removes the base64 step, makes `create_init_commit` always write in `'wb'`, and replaces the text-mode write in extraction with a byte write. This also covers the write-mode defect in the sibling issue #10, which is folded into this spec (Decision 1).

## 2. Assessment of the issue

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | `_seed_collect_files` reads bytes, keeps valid UTF-8 as text, and base64-encodes everything else into a `str` | **Confirmed** | `cli/create_repo.py:797-812` (`content.decode('utf-8')`, fallback `base64.b64encode(content).decode('utf-8')`). The issue cites `687-690`, which is stale. |
| 2 | That `str` is sent as `fileContent` to CodeCommit `create_commit` | **Confirmed** | `cli/create_repo.py:812-818` builds the dict. `putFiles=current_batch` at `:867`. |
| 3 | `GitHubUtils.create_init_commit` receives the same `str`, and its `'wb'` branch is never taken | **Confirmed** | `cli/lib/gh_utils.py:538` (`open(full_path, 'w' if isinstance(file_content, str) else 'wb')`). `_seed_collect_files` is the only producer of `all_files` (`create_repo.py:832`, `:902`) and always sets a `str`. The issue cites `:377`, which is stale. |
| 4 | botocore accepts a `str` for a blob parameter, so the base64 text, not the bytes, is stored | **Confirmed on the wire, not yet on the server** | Offline probe with a hook on `before-send.codecommit.CreateCommit` (boto3 in `.ve`, Python 3.12.3). Content `b'\x89PNG\r\n\x1a\n\x00\xff\xfe'`: passing `bytes` puts `iVBORw0KGgoA//4=` on the wire, which decodes to the original bytes. Passing the base64 `str` puts `aVZCT1J3MEtHZ29BLy80PQ==` on the wire, which decodes to the ASCII text `iVBORw0KGgoA//4=`. The server stores what the wire decodes to. See R1. |
| 5 | This corrupts any binary file and any non-UTF-8 text file in a starter | **Confirmed by the same probe** | Same evidence as claim 4. The base64 step is applied to every file that fails `decode('utf-8')`. |
| 6 | Applies to every platform and both providers | **Confirmed** | `_seed_collect_files` has no platform branch and is shared (`create_repo.py:832`, `:902`). |
| 7 | Starters that contain only UTF-8 text are not affected | **Partially confirmed** | True for the bytes stored from this function. On Windows, a separate step (extraction `write_text`, claim in Section 5) rewrites line endings of text files before `_seed_collect_files` reads them. |
| 8 | Open point: whether any current starter contains non-UTF-8 files | **Answered: none** | Downloaded the four public zips (`s3://63klabs/atlantis/app-starters/v2/*.zip`, anonymous HTTPS) and ran `bytes.decode('utf-8')` on every member: 0 failures across 145 files. No file has a unix exec bit. Largest member is 175,117 bytes. |
| 9 | Suggested fix: keep `bytes` through `_seed_collect_files` and both writers, drop base64 | **Confirmed as sound, with additions** | Matches the plan in Section 6. The additions are the extraction-time write (Section 5) and `core.autocrlf` in the GitHub clone (Decision 3). |
| 10 | The sibling Windows text-mode issue changes the same write path | **Confirmed** | `cli/lib/gh_utils.py:538` is the line both issues change. See Decision 1. |

**Needs runtime verification**

- **R1.** Server-side storage. Seed a throwaway CodeCommit repository and a throwaway GitHub repository from a local zip containing a small PNG and a non-UTF-8 text file (for example Latin-1 bytes). `git clone`, then compare `sha256sum` of the committed files with the originals. Delete both repositories afterward. The wire probe above already shows what CodeCommit receives. This run proves what is stored, and that GitHub is also correct.
- **R2.** Windows CRLF round trip (Section 5). On Windows Git Bash, seed both providers from a starter that contains a CRLF file (all four public starters do, for example `.gitignore`) and compare bytes. This is where the extraction `write_text` and `core.autocrlf` (Decision 3) can change the result. Cannot be tested on Linux. The maintainer runs R1 and R2 before release (Decision 4).
- **R3.** Resolved by automated tests: bytes pass through `_seed_collect_files` and `create_init_commit` unchanged on Linux (Section 6).

## 3. Current state

- **Extraction** (`cli/create_repo.py:620-780`, `_download_and_extract_into`): reads each zip member as bytes (`:705`), builds a large `text_extensions` set (`:707-760`), and computes `is_text_file` from the extension and `_is_binary_string(content)` (`:762`). Text files are decoded as UTF-8 and written with `Path.write_text(decoded, encoding='utf-8')` (`:771`). Everything else, and any `UnicodeDecodeError`, is written with `write_bytes` (`:773`, `:775`). `write_text` is called without `newline`, so on Windows every `\n` becomes `\r\n`.
- **Collection** (`:797-825`): walks the temp directory, reads bytes, decodes UTF-8 or base64-encodes, and returns dicts of `filePath`, `fileContent`, `fileMode` (always `'NORMAL'`). Paths are normalized by `_to_codecommit_path` (added by the #9 fix).
- **CodeCommit** (`:828-895`): sends the list in batches of 100 as `putFiles`.
- **GitHub** (`:898-930`): passes the list to `GitHubUtils.create_init_commit` (`cli/lib/gh_utils.py:489-560`), which clones, configures `user.name` and `user.email` (`:514-520`), writes each file (`:538`), runs `git add .` (`:543`), commits, and pushes.
- **History.** The base64 fallback came in with the first CodeCommit seeding code (`2805697`, 2025-01-22, "added create_repo script"). The `'w' if isinstance(...) else 'wb'` write came in with the GitHub seeding (`5b85ea2`, 2025-06-03). No commit message or comment gives a reason for base64. It reads as a workaround for the belief that `fileContent` must be a JSON-safe string, which is wrong: boto3 takes `bytes` and does the wire encoding itself (Section 2, claim 4).
- **Tests that encode current behavior** (`tests/test_create_repo_seed_paths.py`, added by the #9 spec):
  - `test_utf8_file_content_is_text_and_mode_is_normal` (line ~165) asserts `fileContent == text` (a `str`).
  - `test_non_utf8_file_content_is_base64_text_and_mode_is_normal` (line ~183) asserts base64 text.
  - Both change. `import base64` in that file becomes unused.
- **Other `fileContent` use.** `create_repo.py:507` and `:522` pass a `str` README to `put_file`/`create_commit` for repository initialization. UTF-8 text, correct, unaffected.
- **Sibling specs in this version.** The #9 spec is locked and implemented (`_to_codecommit_path`). The `issue-creating-github-repository-error-getting` spec is locked and has uncommitted edits in both files. The #10 spec directory holds only `ISSUE.md`. The zip-slip spec (#12) holds only `ISSUE.md` and touches the same extraction loop.
- `cli/` ships to users through `update.py`, so the fix reaches users on their next update.

## 4. Review

### 4.1 Security

- **Trust boundary.** Starter zips are chosen by the user (S3, GitHub, organization list). Content is never executed by this script. Passing raw bytes through removes a decode/encode step and adds no new interpretation of untrusted data.
- **Resource use.** Whole files are read into memory, as today. CodeCommit rejects files over 6 MB through the API (quota page, "File size"), so a very large member fails the commit and triggers the existing repository cleanup. No change.
- **Fail-open or fail-closed.** Corruption is silent today: the script prints "seeded successfully". A post-seed content check was declined for the same reason in the #9 spec (its Decision 3). Automated byte-equality tests pin the behavior instead.
- **Zip-slip.** Extraction still lacks a path check. Tracked separately in #12 and not changed here, but this spec edits the same loop (Decision 2), so the two edits need to merge cleanly.
- **IAM.** No change. Same `codecommit:CreateCommit` and `gh` calls.
- **Disclosure.** Data-integrity bug, not an exploitable weakness. No special handling of the spec directory.

### 4.2 Software engineering

- **Correctness.** Bytes in, bytes out is the simplest contract and removes three code paths (UTF-8 decode, base64, `isinstance` branch). Empty files stay `b''`, which boto3 accepts. A UTF-8 BOM is preserved (currently also preserved, as `\ufeff`).
- **Line endings on Windows.** The extraction `write_text` rewrites `\n` to `\r\n`. For a file already holding CRLF, the result is `\r\r\n` (reproduced with `open(..., newline='\r\n')`, which is what Windows text mode does: `b'a\r\nb\r\n'` becomes `b'a\r\r\nb\r\r\n'`). The CodeCommit path then sends those bytes. The GitHub path is also affected by `core.autocrlf` at `git add`. All four public starters contain at least one CRLF file, so this affects real starters on Windows, unlike the binary case.
- **Dead code after the change.** With a byte write in extraction, `text_extensions`, `is_text_file`, and `_is_binary_string` (`:1213`) have no effect. `_is_binary_string` also divides a whole-file count by the 1024-byte sample length, so its ratio is wrong for files over 1 KB. Harmless today because both branches write identical bytes on Linux. Removal is Decision 2.
- **Fit with existing patterns.** `_to_codecommit_path` (the #9 helper) is already in the same function. This change touches adjacent lines only.
- **Library contract.** `GitHubUtils.create_init_commit` currently takes `fileContent` as `str`, or as `bytes` in a branch that never runs. The only caller is `create_repo.py:914`. Accepting `bytes` and also encoding a `str` as UTF-8 keeps it backward compatible (Section 6, decided item D3).
- **Testability.** `_seed_collect_files` runs on a real temp directory, as in the #9 tests. `create_init_commit` can run against a temp directory with `subprocess.run` patched. Hypothesis (already in `cli/requirements-test.txt`) fits a property test: for any `bytes`, a file written to a temp tree is returned unchanged. `write_text` Windows translation cannot be reproduced on Linux (`TextIOWrapper` takes its newline from a compile-time constant), so the extraction fix is tested by asserting that a zip member's bytes, including CRLF, land on disk unchanged and that `Path.write_text` is never called (patched to raise).
- **Versioning** (`.kiro/steering/ascs-cli-script-versioning.md`). `create_repo.py` and `gh_utils.py` both carry today's date (2026-11-14) in their markers. If implementation happens on the same day, the version stays; otherwise PATCH for both files (the interface does not change, because `create_init_commit` still accepts `str`). Applied at implementation time by the rule.
- **Documentation.** `CHANGELOG.md` gets `### Fixed` entries under `v0.0.21 (unreleased)` that link this spec and address #11 and #10. No user doc mentions base64 or binary handling (grep of `README.md` and `docs/`), so no other doc changes.

### 4.3 Cloud engineering

- **Topology.** Client-side only, in the boto3 `create_commit` payload and the local git clone. No templates, stacks, IAM, or stages.
- **Payload.** Passing bytes reduces what CodeCommit receives for binary files. Today a binary file is base64'd twice (33% growth each). Batches stay at 100 files. CodeCommit documents no total-size limit for files in one commit, but a 6 MB cap per file and 6 MB for commit metadata ([quotas](https://docs.aws.amazon.com/codecommit/latest/userguide/limits.html)). The largest public starter member is 175 KB.
- **Existing repositories.** Repositories already seeded from a starter with non-UTF-8 files hold base64 text in place of the files. The fix does not repair them (Decision D6).
- **Pipelines.** A starter whose binary assets were corrupted would fail or misbehave in the build. Not detectable by the script.
- **Rollout and rollback.** Ships through `update.py`. Rollback is a revert and re-release.
- **Observability.** Existing logging only. No new log lines are needed.

## 5. Gaps and observations

- **Extraction write on Windows (new, not in the issue).** `output_path.write_text(decoded_content, encoding='utf-8')` (`create_repo.py:771`) changes line endings on Windows before the seeding step reads the file. It contradicts the issue's expected behavior ("committed with their original bytes") for text files, so it belongs with this fix (Decision 2). It also overlaps with the Windows expectations in #10 ("written byte-for-byte as extracted") and #9.
- **`core.autocrlf` in the GitHub clone (new).** With `core.autocrlf=true` (the Git for Windows installer default), `git add` converts CRLF to LF in the index for files that are not binary by git's own detection. A starter's CRLF `.gitignore` would be committed with LF, so the seed would differ from the starter even with correct bytes on disk. Needs R2 to confirm. Decision 3.
- **`fileMode` is always `NORMAL`.** Executable files lose their exec bit in both providers. No public starter contains an executable member, so no impact today. Noted only (Decision 5).
- **Per-file 6 MB CodeCommit limit** is not checked before sending, so an oversized file fails at `create_commit` and triggers repository cleanup. Existing behavior, unchanged.
- **Zip member names in CP437 vs UTF-8.** Python decodes names per the zip flag. Not part of this issue.
- **Issue is silent on** whether the seeded `test` branch (auto-merged from `dev` since v0.0.18) is affected. It is, because the merge is a fast-forward of the same commits.
- **Issue line references are stale** relative to the working tree. The fix should be located by symbol, not line number.
- **Ordering of `core.autocrlf false` (found while designing, resolved by Decision 6).** Decision 3 sets `git config core.autocrlf false` after the clone. On a machine with global `core.autocrlf=true`, `gh repo clone` has already written the clone's tracked files with CRLF. Reproduced in a scratch repository with a global `autocrlf=true`: clone, then `git config core.autocrlf false`, then `git checkout dev` and `git add .` leaves the repository's `README.md` staged as modified (12 bytes on disk with CRLF against the 10-byte LF blob). The seeding commit would then change the README's line endings whenever the starter does not supply its own `README.md`. Passing the setting at clone time (`git clone -c core.autocrlf=false`, which `gh repo clone <repo> <dir> -- -c core.autocrlf=false` forwards) leaves the working tree LF and `git add .` clean. The same scratch run confirmed the underlying defect: with `autocrlf=true` throughout, a CRLF `.gitignore` is committed as LF. Decision 6.
- **README bootstrap write is also text mode (found while designing).** `GitHubUtils.create_branch_structure` writes the repository README with `open(readme_path, 'w')` (`cli/lib/gh_utils.py:465`), the same pattern as #10 in a different function. On Windows it rewrites `\n` as `\r\n` and uses the locale code page. The content is ASCII in practice (fixed text, an S3 URL, clone URLs), so the visible effect is CRLF in the generated README. Not covered by #10 or #11. Folded in by Decision 7.
- **Concurrent edits.** Two locked or in-progress specs (#1 fix, #9 fix) have uncommitted changes in the same two files. This work builds on top of them and should not be started until those changes are committed or the user confirms the order.

## 6. Proposed approach

This section describes what will be built. The decisions behind it are in Section 9.

1. **`_seed_collect_files`** (`cli/create_repo.py`): read each file with `open(full_path, 'rb')` and store the `bytes` as `fileContent`. Remove the UTF-8 decode, the base64 fallback, and `import base64`. Keep `_to_codecommit_path`, `fileMode: 'NORMAL'`, and the existing error handling. Update the docstring: `fileContent` is `bytes`.
2. **`GitHubUtils.create_init_commit`** (`cli/lib/gh_utils.py`): open every file with `'wb'`. If `fileContent` is a `str`, encode it as UTF-8 first (D3). No `encoding` or `newline` argument remains, because no text-mode write remains. Update the docstring to state the accepted types.
3. **Extraction** (`_download_and_extract_into`): write every member with `write_bytes(content)`. Delete `text_extensions`, `is_text_file`, and `_is_binary_string` (`create_repo.py:1213`), which have no effect after the change. The `output_path.exists()` unlink and the directory handling stay as they are.
4. **GitHub clone**: clone with `["gh", "repo", "clone", repo_name, git_dir, "--", "-c", "core.autocrlf=false"]` so `core.autocrlf` is `false` from the first checkout and persists in the clone's `.git/config` (Decision 3, refined by Decision 6). The existing `git config user.name` and `user.email` calls stay. No separate `git config core.autocrlf` call is added. The setting applies to the throwaway seeding clone only. A `.gitattributes` file inside a starter still governs line endings, as the starter author intended. The clone in `create_branch_structure` is not changed: it only commits an LF README written by this script.
5. **README bootstrap write** (Decision 7): in `GitHubUtils.create_branch_structure`, open the README with `open(readme_path, 'w', encoding='utf-8', newline='')`, so the bytes written are UTF-8 with `\n` line endings on every platform.
6. **Tests**:
   - Update the two tests in `tests/test_create_repo_seed_paths.py` to assert `bytes` for UTF-8 and non-UTF-8 content, and remove the unused `base64` import there.
   - Add a Hypothesis property test: for generated `bytes` written to a file in a temp tree, `_seed_collect_files` returns identical `bytes`.
   - Add a test with a small binary fixture generated in the test (PNG signature plus NUL and 0xFF bytes) for the collection step.
   - Add a `create_init_commit` test with `subprocess.run` patched, using a real temp directory, asserting written file bytes equal the input for `bytes` and for a non-ASCII `str`.
   - Add an extraction test that a zip member containing CRLF and non-UTF-8 bytes is on disk unchanged, with `Path.write_text` patched to raise.
   - A CodeCommit test that `putFiles[*]['fileContent']` passed to `create_commit` is `bytes` (client mocked).
   - A test that the `create_init_commit` clone command carries `-- -c core.autocrlf=false` and that no separate `git config core.autocrlf` call runs.
   - A `create_branch_structure` test with `subprocess.run` patched, using a real temporary directory, asserting the README bytes contain no `\r` and are UTF-8.
7. **Documentation**: one `CHANGELOG.md` `### Fixed` entry under `v0.0.21 (unreleased)` for `create_repo.py` and one for `gh_utils.py`, linking this spec and addressing both [#11](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/11) and [#10](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/10). State that repositories already seeded from a starter with binary or non-UTF-8 files are not repaired and must be recreated or the files re-committed. Version markers follow the steering rule: PATCH for both files (bug fix, no interface change, because `create_init_commit` still accepts `str`), and no change to a file whose marker already carries the implementation date.
8. **Verification before release** (Decision 4): the maintainer runs R1 on Linux or macOS and R2 on Windows, each against a throwaway CodeCommit repository and a throwaway GitHub repository, deleting them afterward. Nothing is created or deleted by the agent without the maintainer's go-ahead.
9. **Housekeeping for #10**: the spec directory `0-0-21-github-seeding-writes-files-in-text-mode-without` is covered by this spec. Issue #10 is closed with a reference to this fix once it ships. The agent does not delete or edit that directory.
10. **Sequencing**: implementation starts after the uncommitted edits from the `issue-creating-github-repository-error-getting` spec in `create_repo.py` and `gh_utils.py` are committed, or the maintainer confirms the order.

**Alternatives considered**

- **Pass base64 to CodeCommit and decode on the server.** Rejected. `create_commit` has no such flag. boto3 already base64-encodes `bytes` on the wire.
- **Keep text as `str`, bytes only for non-UTF-8.** Rejected. Two types for one field keeps the `isinstance` branch and the Windows encoding exposure, and gains nothing, since UTF-8 text round-trips as bytes unchanged.
- **Use the CodeCommit `sourceFile` option or `put_file`.** Rejected. Different API shape, one commit per file, no benefit.
- **Write files through `git` plumbing (`hash-object`) on the GitHub path.** Rejected. A larger change than `'wb'`.
- **Add a content-integrity check after seeding.** Not planned, consistent with the #9 decision.

**Decided in this plan** (no question asked; veto any of these)

| # | Item | Rationale |
|---|------|-----------|
| D1 | `fileContent` is `bytes` for every file, including pure-ASCII text. | One type, no branches. |
| D2 | Test binary data is generated inside the tests, with no binary fixture committed to the repository. | Keeps the repo free of binary files and the test intent readable. |
| D3 | `create_init_commit` accepts `bytes` and `str`. A `str` is encoded as UTF-8 and written with `'wb'`. | Backward compatible for any other caller and removes the text-mode write. |
| D4 | `fileMode` stays `'NORMAL'` for all files. | Out of scope. See Decision 5. |
| D5 | Locate code by symbol, not by the issue's line numbers. | Issue lines are stale. |
| D6 | Repositories already seeded with base64 content are not repaired. The CHANGELOG says so and gives the recovery path (recreate, or re-commit the files). No repair script or troubleshooting doc. | Same approach as the #9 fix. Rare case, since no public starter is affected. |
| D7 | `README.md`, `docs/`, and `AGENTS-FOR-END-USE.md` do not change. | They do not describe file encoding. |

## 7. Related improvements

| Item | Class (Include / Spin off / Note) | Rationale | Effort | Risk |
|------|-----------------------------------|-----------|--------|------|
| Replace `write_text` in extraction with `write_bytes` | Include (Decision 2) | Same goal (original bytes). On Windows it turns CRLF into `\r\r\n` in all four public starters. | S | Low |
| Remove `text_extensions`, `is_text_file`, `_is_binary_string` after the byte write | Include (Decision 2) | Dead after the change. `_is_binary_string` is also miscalculated for files over 1 KB. | S | Low |
| `core.autocrlf=false` at clone time in the GitHub seeding clone | Include (Decisions 3 and 6) | Without it a Windows user's global `autocrlf=true` can still rewrite CRLF at `git add`. | S | Low to Medium (needs R2) |
| README bootstrap write in `create_branch_structure` opened with `encoding='utf-8', newline=''` | Include (Decision 7) | Same text-mode defect as #10 in the same file, one line. | S | Low |
| `create_init_commit` always opens files with `'wb'` | Include, covers #10's write-mode defect (Decision 1) | Same line and same cause as #11. | S | Low |
| Preserve the exec bit (`fileMode: EXECUTABLE`) | Note only (Decision 5) | Needs zip `external_attr` handling and a CodeCommit mode. No public starter has an executable member. | M | Medium |
| Zip-slip check on extraction (#12) | Already a separate spec | Same loop, different concern. | S | Low |
| Check per-file size against the 6 MB CodeCommit limit before sending | Note only | Failure is already clean (error plus repository deletion). | S | Low |
| Windows round-trip test in CI | Note only | No Windows runner in this repository. | L | Low |

## 8. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Changing the type of `fileContent` breaks a caller or test that expects `str` | Only `create_repo.py` calls `create_init_commit`. The two tests that expect `str` are updated. D3 keeps `str` accepted. Search for other users before the change. |
| Byte write in extraction changes behavior for text files on Windows (removes CRLF doubling) | Intended. Verified by R2 on Windows (Decision 4). |
| `core.autocrlf false` surprises users who rely on automatic conversion | It applies only to the throwaway seeding clone, not to the user's machine config or later clones. |
| Windows behavior cannot be tested in Linux CI | Assert on mechanism (`write_text` never called, bytes equal), and run R1 and R2 manually before release (Decision 4). |
| `core.autocrlf false` applied after the clone restages the clone's README as CRLF (reproduced) | The setting is applied at clone time instead (Decision 6). |
| Merge conflicts with uncommitted edits from the other two 0.0.21 specs in the same files | Commit or sequence those first (Section 6, item 10). |
| Users believe the update repaired existing repositories | CHANGELOG states otherwise (D6). Residual risk: users who do not read it. |

## 9. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Q1: Fold issue #10 (GitHub text-mode write) into this spec. `create_init_commit` always writes with `'wb'`. | Same line and cause as #11. After the change #10's symptoms cannot occur. #10 is closed by this fix and its spec directory is covered here. |
| 2 | Q2: Write every extracted member with `write_bytes`, and delete `text_extensions`, `is_text_file`, and `_is_binary_string`. | Removes the Windows `\n` to `\r\n` rewrite that turns CRLF into `\r\r\n` in all four public starters. The heuristic is dead afterward and its ratio is miscalculated for files over 1 KB. |
| 3 | Q3: Set `core.autocrlf false` in the GitHub seeding clone. The mechanism is refined by Decision 6. | The clone is only used to push the seed, and the goal is the original bytes regardless of the user's global git config. |
| 4 | Q4: Before release the maintainer runs R1 (Linux or macOS) and R2 (Windows), each for CodeCommit and GitHub, using throwaway repositories deleted afterward. | Only real runs show what the providers store and what Windows git does to line endings. Matches the #9 fix's verification. |
| 5 | Q5: Executable-bit loss is noted only. No issue is filed. | No public starter has an executable member. Revisit if one appears. |
| 6 | Q6: Apply `core.autocrlf=false` at clone time with `gh repo clone <repo> <dir> -- -c core.autocrlf=false`, not with a `git config` call after the clone. Replaces the mechanism in Decision 3. | A scratch reproduction with global `autocrlf=true` showed that setting it after the clone leaves the clone's CRLF `README.md` staged by `git add .`. Setting it at clone time keeps the README LF and `git add .` clean. |
| 7 | Q7: Fold in the README write in `create_branch_structure`: `open(readme_path, 'w', encoding='utf-8', newline='')`, with a test. | Same text-mode defect as #10, same file, one line, covered by the same Windows run (R2). |

## 10. Open questions and recommendations

No open questions.
