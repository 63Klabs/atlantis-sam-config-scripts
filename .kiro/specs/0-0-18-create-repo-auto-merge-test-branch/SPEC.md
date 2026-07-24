# SPEC: create_repo Auto-Merge dev to test

Planning scratchpad for GitHub issue [#2](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/2).
This document is for investigation and planning only — it is not a formal requirements/design/tasks spec yet.

## Issue Reference

- **Issue:** [#2 Update create_repo script to immediately merge dev to test](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/2)
- **Author:** Chad Kluck (@chadkluck)
- **State:** OPEN
- **Labels:** enhancement
- **Created:** 2026-07-22
- **Target version:** v0.0.18 (unreleased)

## Issue Summary (as reported)

> Currently, when creating a new repository and facilitating the first deploy, developers have to context switch but creating the repo, then cloning it, then performing the merge to test before creating the pipeline.
>
> They are going back and forth between two repositories and it can be confusing for a first time task, or a not-very often task.
>
> After the repository is created and the dev branch is seeded, perform the operation to merge dev to test.
>
> This allows the developer to immediately create the test pipeline without first cloning and switching to the new repo to perform this task.
>
> If a developer does not want to deploy right away, they can still skip the pipeline creation.
>
> This new feature will ensure that there is test code in the test branch prior to creating the test pipeline.

## Current Behavior (investigation)

Traced through `cli/create_repo.py` (`v0.1.4/2025-06-04`) and `cli/lib/gh_utils.py`.

### Orchestration — `RepositoryCreator.create_and_seed_repository()`

```text
1. _create_repository()          # create repo (codecommit | github)
2. _create_dev_test_branches()   # main (README) -> test -> dev
3. if self.source:
     temp_dir = _download_and_extract()
     _seed_repository(temp_dir)  # commits starter code onto the "dev" branch only
```

### Branch creation

- **CodeCommit** (`_create_dev_test_branches_codecommit`): commits `README.md` to `main`, then creates `test` from `main`'s commit id, then creates `dev` from the same `main` commit id.
- **GitHub** (`GitHubUtils.create_branch_structure`): commits/pushes `README.md` to `main`, `checkout -b test` + push, `checkout -b dev` + push.

### Seeding

- Both `_seed_repository_codecommit` and `_seed_repository_github` use `seed_branch = "dev"`. Starter code lands on `dev` **only**.

### The gap

After `create_and_seed_repository()` completes, `test` (and `main`) still contain only the initial `README.md`. The starter/app code lives solely on `dev`. To stand up a **test** pipeline, the developer must currently:

1. Clone the new repo locally
2. `git checkout test`
3. `git merge dev`
4. `git push origin test`

That is the manual context switch the issue wants to eliminate.

### Fast-forward feasibility (good news)

For both providers, `test` was branched from `main` and `dev` was branched from the same point, then `dev` received the seeding commit(s). So `test`'s HEAD is an **ancestor** of `dev`'s HEAD → a **fast-forward** merge of `dev` into `test` is valid. No merge commit / conflict resolution should be required in the standard create-and-seed path.

- CodeCommit: `codecommit.merge_branches_by_fast_forward(repositoryName, sourceCommitSpecifier='dev', destinationCommitSpecifier='test')` is a strong candidate (no local clone needed).
- GitHub: perform `checkout test` + `merge --ff-only dev` + `push` inside a clone. Note `_seed_repository_github` already clones into a temp `git_dir` — the merge could reuse that clone to avoid a second clone.

## What the update needs to do (draft)

1. Add a merge step after successful seeding: `_merge_dev_to_test()` dispatching to `_merge_dev_to_test_codecommit()` and `_merge_dev_to_test_github()` (mirrors the existing dispatch pattern).
2. Only run when the repo was actually seeded (i.e., `self.source` is set). If nothing was seeded, `test` == `dev` already and the merge is a no-op / should be skipped.
3. Add a `GitHubUtils.merge_branches(...)` helper (or reuse the seeding clone) for the GitHub path.
4. Keep behavior consistent between providers, matching existing logging/`Colorize`/`Log` output style.
5. Failure handling: the repo is already created + seeded, so a merge failure should **warn** and print manual merge instructions rather than deleting the repo (unlike the seed-failure path, which deletes the repo).
6. Follow the `-h`, `--profile`, login-facilitation, and "prompt to commit/push" conventions from `AGENTS.md` where applicable (note: this script creates a *remote* repo, so the "commit your samconfig" prompt may not apply — confirm during design).

## Open Questions

1. **Opt-out flag?** Should there be a `--no-merge-to-test` (or `--skip-test-merge`) flag for users who want only `dev` seeded? The issue implies the merge should be the default behavior, with pipeline creation being the separately-skippable step. Recommend: merge by default, provide an opt-out flag.
2. **No-source case.** When `create_repo` is run without a `--source` (README-only repo), should the merge be skipped entirely? (Leaning yes — nothing to merge.)
3. **Merge strategy exposure.** Fast-forward is expected to always succeed here. Do we hard-require fast-forward (`--ff-only` / `merge_branches_by_fast_forward`) and treat a non-ff as an error, or fall back to a three-way/standard merge? Recommend: attempt fast-forward, and on failure warn with manual instructions.
4. **GitHub clone reuse.** Should `_merge_dev_to_test_github()` reuse the clone created during seeding (`git_dir`) for efficiency, or clone fresh for clean separation of concerns?
5. **Merge commit author/email.** Reuse `get_init_commit_author()` / `get_init_commit_email()` for any non-ff merge commit? (Fast-forward needs no commit identity.)
6. **Does this touch the "immediately create the test pipeline" step?** The issue mentions the developer can then create the test pipeline (and skip it if not deploying). Confirm whether this spec is scoped *only* to the merge, or should also surface a follow-up hint/prompt about running `config.py`/`deploy.py pipeline ... test`.

## Proposed Next Step

This is an **enhancement** (new feature) targeting `create_repo.py` for `v0.0.18`. Recommend proceeding to a formal spec (`requirements.md` → `design.md` → `tasks.md`) once the Open Questions above are answered — especially #1 (opt-out flag), #2 (no-source behavior), and #6 (scope boundary re: pipeline creation).

Awaiting decision before creating formal spec documents.

---

## Answers to Open Questions

1. Provide --skip-test-merge opt out flag
2. I need clarification. If no `--source` is provided then the script i beleive prompts the user for which start to use. IF the user skips --source AND does not choose a starter, then no we would not merge dev to test. But if a user skips --source BUT chooses a starter then yes, we merge to test
3. perform recommendation: attempt fast-forward, and on failure warn with manual instructions.
4. reuse clone
5. yes, reuse author
6. Yes, surface a follow-up hint (not a prompt) to run config.py and use <repo_name> as the repository name