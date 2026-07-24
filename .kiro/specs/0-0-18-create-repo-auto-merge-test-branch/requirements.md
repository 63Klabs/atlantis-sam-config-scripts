# Requirements Document

## Introduction

This feature updates the repository creation utility (`cli/create_repo.py`) so that, after a new repository is created and its `dev` branch is seeded with starter/application code, the code is automatically merged from `dev` into `test`. Today the seeded code lands on `dev` only, leaving `test` (and `main`) with just the initial `README.md`. To stand up a **test** pipeline, a developer must manually clone the new repository, check out `test`, merge `dev`, and push — a context switch that is error-prone for an infrequent, first-time task.

By performing the `dev` → `test` merge automatically at creation time, the developer can immediately create a test pipeline (for example with `config.py`) without cloning and switching repositories. The merge is the default behavior when the repository is seeded, is skippable via a flag, and must work for both the `codecommit` and `github` providers. This feature addresses [issue #2](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/2).

## Glossary

- **Repository_Creator**: The `RepositoryCreator` class in `cli/create_repo.py` that orchestrates repository creation, branch structure creation, and seeding.
- **GitHub_Utils**: The `GitHubUtils` class in `cli/lib/gh_utils.py` that wraps GitHub CLI (`gh`) and `git` operations.
- **Provider**: The repository backend, one of `codecommit` or `github`.
- **Source**: The seed input that populates the `dev` branch — an S3 zip URL, a GitHub repository/release URL (via `--source`), or an application starter selected interactively.
- **Main_Branch**: The `main` branch, which contains only the initial `README.md`.
- **Dev_Branch**: The `dev` branch, which receives the seeded starter/application code.
- **Test_Branch**: The `test` branch, from which a test-stage pipeline is deployed.
- **Seeding**: The existing operation that commits Source content onto the Dev_Branch (`_seed_repository`).
- **Test_Merge**: The new operation that merges the Dev_Branch into the Test_Branch after Seeding.
- **Fast_Forward_Merge**: A merge in which the destination branch pointer advances to the source commit without creating a merge commit, valid when the destination is an ancestor of the source.
- **Skip_Test_Merge_Flag**: The `--skip-test-merge` command-line flag that opts out of the Test_Merge.
- **Follow_Up_Hint**: An informational, non-interactive message (not a prompt) shown after a successful Test_Merge that guides the developer to create a test pipeline.
- **Manual_Merge_Instructions**: An informational message shown when the Test_Merge fails, describing how to merge `dev` into `test` manually.

## Requirements

### Requirement 1: Automatic dev-to-test Merge After Seeding

**User Story:** As a developer creating a new repository, I want the seeded `dev` branch automatically merged into `test`, so that I can create a test pipeline without first cloning the repository and merging by hand.

#### Acceptance Criteria

1. WHEN the Repository_Creator completes Seeding of the Dev_Branch from a resolved Source AND the Skip_Test_Merge_Flag is not set, THE Repository_Creator SHALL perform the Test_Merge (merge Dev_Branch into Test_Branch).
2. THE Repository_Creator SHALL perform the Test_Merge only after Seeding completes successfully.
3. THE Repository_Creator SHALL perform the Test_Merge for both the `codecommit` and `github` Providers.
4. WHEN the Test_Merge completes successfully, THE Test_Branch SHALL contain the same seeded content as the Dev_Branch.
5. THE Repository_Creator SHALL NOT modify the Main_Branch as part of the Test_Merge.
6. THE Repository_Creator SHALL perform the Test_Merge without requiring the developer to clone or switch to the newly created repository.

### Requirement 2: Skip Conditions and Opt-Out Flag

**User Story:** As a developer who sometimes wants only a seeded `dev` branch, I want to control whether the merge happens, so that I am not forced to populate `test`.

#### Acceptance Criteria

1. THE Repository_Creator SHALL accept a `--skip-test-merge` boolean optional flag that defaults to false when not provided.
2. WHEN the Skip_Test_Merge_Flag is set, THE Repository_Creator SHALL NOT perform the Test_Merge even when the Dev_Branch was seeded.
3. WHEN no Source is resolved (neither `--source` is provided nor an application starter is selected, including when the user selects the "None" option), THE Repository_Creator SHALL NOT perform the Test_Merge.
4. WHEN the Test_Merge is skipped because no Source was resolved, THE Repository_Creator SHALL continue and exit normally without error.
5. WHEN the Test_Merge is skipped because the Skip_Test_Merge_Flag is set, THE Repository_Creator SHALL emit an informational message indicating the merge was skipped and how to perform it later.

### Requirement 3: Fast-Forward Strategy and Non-Fatal Failure Handling

**User Story:** As a developer, I want the merge to use a safe fast-forward and to never leave my new repository in a broken state, so that a merge problem does not undo the repository creation and seeding.

#### Acceptance Criteria

1. THE Repository_Creator SHALL attempt the Test_Merge as a Fast_Forward_Merge.
2. IF the Test_Merge cannot be completed as a Fast_Forward_Merge OR any error occurs during the Test_Merge, THEN THE Repository_Creator SHALL NOT delete the repository.
3. IF the Test_Merge fails, THEN THE Repository_Creator SHALL NOT exit with a non-zero exit code solely because of the merge failure.
4. IF the Test_Merge fails, THEN THE Repository_Creator SHALL emit a warning and display Manual_Merge_Instructions describing how to clone the repository, check out `test`, merge `dev`, and push.
5. WHEN the Test_Merge fails, THE Repository_Creator SHALL record the failure via `Log` and surface it to the console via `Colorize`, consistent with the existing error/warning output style.

### Requirement 4: CodeCommit Merge Behavior

**User Story:** As a developer using CodeCommit, I want the `dev` → `test` merge performed server-side, so that no local clone is required.

#### Acceptance Criteria

1. WHEN the Provider is `codecommit`, THE Repository_Creator SHALL perform the Test_Merge using the CodeCommit fast-forward merge operation (`merge_branches_by_fast_forward`) with source specifier `dev` and destination specifier `test`.
2. THE Repository_Creator SHALL NOT create or require a local clone to perform the CodeCommit Test_Merge.
3. IF the CodeCommit merge operation raises an error, THEN THE Repository_Creator SHALL handle it as a non-fatal Test_Merge failure per Requirement 3.

### Requirement 5: GitHub Merge Behavior

**User Story:** As a developer using GitHub, I want the merge to reuse the clone already created during seeding, so that the operation is efficient and does not create a second clone.

#### Acceptance Criteria

1. WHEN the Provider is `github`, THE Repository_Creator SHALL perform the Test_Merge by reusing the local clone created during GitHub Seeding rather than creating an additional clone.
2. THE GitHub_Utils SHALL provide a merge operation that checks out the Test_Branch, fast-forward merges the Dev_Branch, and pushes the Test_Branch to `origin`.
3. THE GitHub Test_Merge SHALL use the commit author identity already configured on the reused clone, sourced from `get_init_commit_author()` and `get_init_commit_email()`.
4. IF any `git` or `gh` command performed during the GitHub Test_Merge returns a non-zero status, THEN THE Repository_Creator SHALL handle it as a non-fatal Test_Merge failure per Requirement 3.
5. THE Repository_Creator SHALL remove the reused local clone directory after the Test_Merge completes, whether the merge succeeded or failed.

### Requirement 6: Follow-Up Hint for Test Pipeline Creation

**User Story:** As a developer, once the `test` branch contains code, I want a hint on how to create the test pipeline, so that I know the next step without leaving the tool.

#### Acceptance Criteria

1. WHEN the Test_Merge completes successfully, THE Repository_Creator SHALL display a Follow_Up_Hint that is informational only and does not prompt for or wait on user input.
2. THE Follow_Up_Hint SHALL reference the `config.py` script as the way to create a test pipeline.
3. THE Follow_Up_Hint SHALL present, on a single line, a suggested command of the form `./cli/config.py pipeline <prefix> <project_id> test`, WHERE `<prefix>` and `<project_id>` remain literal placeholders (because the prefix is not known at creation time and a descriptive `repo_name` may exceed the character limit allowed for a `project_id`) and `test` is the literal, known stage id.
4. IF a `--profile` value was provided to `create_repo.py`, THEN THE Follow_Up_Hint SHALL append `--profile <profile>` to the suggested command using the actual profile value; OTHERWISE THE suggested command SHALL omit the `--profile` option.
5. THE Follow_Up_Hint SHALL include a separate line instructing the developer to use the created repository name — the actual `repo_name` value — when prompted for the Repository parameter (for example: `Use <repo_name> when prompted for the Repository parameter`).
6. WHEN the Test_Merge is skipped (per Requirement 2) OR fails (per Requirement 3), THE Repository_Creator SHALL NOT display the Follow_Up_Hint.

### Requirement 7: Output, Logging, and Help Text Consistency

**User Story:** As a user, I want the merge step to look, log, and document itself like the rest of `create_repo.py`, so that the experience is consistent and discoverable.

#### Acceptance Criteria

1. THE Repository_Creator SHALL emit progress and success output for the Test_Merge using `Colorize` and `Log` consistent with the existing branch-creation and seeding output.
2. THE Repository_Creator help/EPILOG text SHALL document the `--skip-test-merge` flag, including that the Test_Merge is the default behavior when the repository is seeded.
3. THE Repository_Creator help/EPILOG text SHALL indicate that the Test_Merge occurs only when the repository is seeded from a Source.
4. THE Repository_Creator SHALL preserve all existing behavior for repository creation, branch structure creation, and seeding that is unrelated to the Test_Merge.
