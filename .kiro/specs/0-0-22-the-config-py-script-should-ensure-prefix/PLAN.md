# config.py: warn when Prefix, ProjectId, and StageId exceed recommended lengths

> **Status**: Locked, 2026-11-15
> **Issue**: [ISSUE.md](ISSUE.md) (GitHub issue #8)
> **Reviewed against**: `dev` at `b189708` on 2026-11-15 (clean `cli/` tree; the only working-tree changes are spec files). The CHANGELOG has no `v0.0.22 (unreleased)` header yet.

## 1. Summary

`config.py` takes `Prefix`, `ProjectId`, and `StageId` as arguments, then uses them as defaults for the template parameters of the same names. Nothing checks how long they are against the Atlantis recommendations. The templates enforce only the absolute maximums (8, 26, 8). Long combinations pass template validation and fail later in CloudFormation, when a resource name exceeds a service limit (S3 bucket names, IAM role names).

The recommended fix adds one pure helper that compares the three lengths against fixed recommendation constants and returns warning lines. `config.py` prints them, without prompting and without blocking, once the template parameters are known and before they are prompted for. Only parameters that the selected template declares are checked, because service-role templates declare only `Prefix` and storage templates declare no `StageId`. Template validation stays the only hard enforcement.

## 2. Assessment of the issue

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Templates already cap Prefix at 8, ProjectId at 26, StageId at 8 | **Confirmed** | `MaxLength` in `template-pipeline-github.yml`, `template-storage-cache-data.yml`, `template-network-route53-cloudfront-s3-apigw.yml` at `atlantis-sam-templates` v0.0.45 (`Prefix` 2-8, `ProjectId` 2-26, `StageId` 2-8). |
| 2 | Recommended: Prefix 2-6, ProjectId ≤ 20, Prefix+ProjectId ≤ 28 | **Confirmed** | Same templates. Prefix description: "Short, descriptive 2-6 character values work best ... length of Prefix + Project ID should not exceed 28 characters." ProjectId `ConstraintDescription`: "suggested maximum of 20". |
| 3 | Recommended: StageId 2-6, Prefix+ProjectId+StageId ≤ 32, StageId "lowercase alphanumeric" | **Partially confirmed** | The 2-6 and 32 figures are not in the template text I read. The StageId description only says to use short names. They are consistent with the other limits: 6 + 20 + 6 = 32. The templates also allow dashes in StageId (`^[a-z][a-z0-9-]{0,6}[a-z0-9]$`), so the check must not warn about dashes. |
| 4 | The warning should come "after template version, etc." and just before parameters are configured | **Confirmed as feasible** | Interactive: `get_template_parameters` at `cli/config.py:3156` prints version info through `process_template_content`; `prompt_for_parameters` is called at `:3184`. |
| 5 | Template validation still enforces the absolute maximums | **Confirmed** | `validate_parameter` rejects values over `MaxLength` (`cli/config.py:548-556`); the interactive loop re-prompts (`:307-333`); headless collects failures through `validate_all_parameters` (`:614-659`, called at `:2899`). A default taken from a too-long CLI argument is rejected at the prompt and must be retyped. |
| 6 | "S3 bucket and IAM Role names must not exceed 64 characters" | **Not confirmed for S3** | S3 general purpose bucket names are 3-63 characters ([bucket naming rules](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html)). IAM role names are 64 ([IAM and STS character limits](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html)). The warning text states both (Decision 4). |
| 7 | `config.py` has no such check today | **Confirmed** | `_validate_args` (`cli/config.py:167-180`) checks only `infra_type` and the service-role project id. No length check exists in the script. |

Nothing needs runtime verification. The new logic is a pure function and is unit-testable without AWS.

## 3. Current state

- `ConfigManager.__init__` stores `prefix`, `project_id`, `stage_id` (`stage_id` becomes the string `'default'` when omitted) (`cli/config.py:92-94`).
- Interactive `main()` order: read samconfig, pick template, `get_template_parameters` (`:3156`), build defaults, `prompt_for_parameters` (`:3184`).
- `prompt_for_parameters` seeds defaults from the three arguments only when the template declares the parameter (`:211-222`). The user can retype any of them. `self.prefix`, `self.project_id`, `self.stage_id` update with the typed value (`:312-323`).
- `run_skeleton_mode` calls `get_template_parameters` at `:2808` and `generate_skeleton` at `:2812`. `generate_skeleton` writes the three values from the instance (`:1282-1287`).
- `run_headless_mode` calls `get_template_parameters` at `:2894`, then `validate_all_parameters` and `validate_atlantis_deploy_params` (`:2899-2903`). It exits through `sys.exit("Error: ...")` on failure. The skeleton file can hold values that differ from the arguments.
- Which templates declare which parameters (atlantis-sam-templates v0.0.45, checked by reading each template): all four `service-role` templates declare `Prefix` only; the five `storage` templates declare `Prefix` and `ProjectId`; the `network` template and four `pipeline` templates declare all three.
- Colors and warning output come from `Colorize.warning` and `Colorize.box_warning` (`cli/lib/tools.py:331`, `:369`). `ConsoleAndLog.warning` writes to console and log (`cli/lib/logger.py:158`).
- Git history for `cli/config.py` shows no earlier length handling to preserve.

## 4. Review

### 4.1 Security

- **Untrusted values in output.** In headless mode the three values come from a skeleton JSON file that an AI agent or a pipeline may have written. Echoing them could print terminal escape sequences. The warning should name the parameter and its length, not its value.
- **Fail direction.** The check is advisory only. It cannot weaken validation, because `validate_parameter` and CloudFormation are untouched. A bug in the check must not abort a run: wrap nothing in `sys.exit`, and keep the helper free of I/O.
- **Disclosure.** The issue is a usability improvement. Nothing in it needs embargo handling.
- **Unrelated, noticed while reading.** `Prefix` and `ProjectId` arguments flow into file paths (`get_samconfig_dir`, `cli/config.py:2554-2558`; `{prefix}-defaults.json`) before any pattern check. The user owns these inputs, so the risk is low. It is separable. Spin-off confirmed (Decision 5).

### 4.2 Software engineering

- **Where it lives.** A module-level constant block (UPPER_SNAKE_CASE per `naming-conventions-python`) plus one method or function that takes the three lengths and the template `parameters` dict and returns a list of warning strings. A thin printer calls it from three places. This matches the existing split between pure helpers (`validate_parameter`) and callers.
- **Gating on template parameters.** The check must test `'Prefix' in parameters` and so on, as `prompt_for_parameters` does at `:211-222`. Without it, a service-role run would be checked against a `ProjectId` of `pipeline` or `storage`, and a storage run against a `StageId` that the template does not use.
- **`'default'` stage.** When `stage_id` is `'default'` it is not a real StageId and must count as length 0.
- **Counting.** "Prefix+ProjectId ≤ 28" is read as the sum of the character counts, with no separators. Evidence: 6 + 20 + 6 = 32 matches the three-way limit only without hyphens, and the template text says "length of Prefix + Project ID".
- **Existing stacks.** An existing samconfig that already exceeds a recommendation will trigger the warning on every `config.py` run. This is acceptable and informative.
- **Interactive edits.** The user can change the three values at the prompts, so a check done only on the arguments can miss the final values. Handled by a second check (Decision 2).
- **Tests to add.** Unit tests for the helper (boundaries 6/7, 20/21, 28/29, 32/33; missing parameters; `'default'` stage; the warning names which values exceed). Property-based tests with Hypothesis, matching `tests/test_validation.py`. Flow tests for the three call sites, matching `tests/test_skeleton_flow.py` and `tests/test_headless_flow.py`. No existing test encodes behavior that this change breaks.
- **Documentation and release items.** `docs/SCRIPT-GUIDE.md` `config.py` section; the `EPILOG` notes in `cli/config.py:2603-2663`; CHANGELOG `v0.0.22 (unreleased)` header plus an "Added" entry (the header does not exist yet, so it must be created per `changelog-convention`); `VERSION` bump per `ascs-cli-script-versioning` (new behavior is a MINOR change: `v0.1.9/2026-07-24` becomes `v0.2.0/<date>`). Changes stay inside `cli/` and `docs/`, so `update.py` delivers them.

### 4.3 Cloud engineering

- No IaC change and no new IAM. The templates stay as they are, and this repository does not own them.
- The 32-character figure only approximates the real constraint. Bucket names default to `<Prefix>-<Region>-<AccountId>-<ProjectId>-<StageId>-<ResourceId>` (`S3BucketNameOrgPrefix` description in the pipeline template), so the S3 limit of 63 also depends on region length, the 12-digit account id, and the resource id. The check is a rule of thumb, and the warning text should say "may cause". Organizations that set `S3BucketNameOrgPrefix` use a different pattern.
- Stage behavior: the check applies identically to every stage. No stage-specific config.
- Observability: log each warning with `Log.warning` so it appears in `cli/logs`.
- Rollout and rollback: ships with `update.py`. Rolling back means re-running `update.py` to an earlier release. No stored data changes.

## 5. Gaps and observations

1. The issue's 2-6 (StageId) and 32 (combined) figures are not in the template text. They are consistent with the other limits. The constants should cite the Atlantis template documentation so a reader can trace them.
2. The issue says "state which ones" exceed. This means a per-value line and a separate combined-length line, because a user can exceed a combined limit while each value is within its own limit (for example 6 + 20 + 6 with an extra character anywhere).
3. The issue does not say how the warning behaves in `--skeleton` and `--headless` modes. The headless mode must not prompt (Decision 1).
4. The issue does not say whether the values to check are the arguments or the values the user finally enters. Decision 2.
5. The issue does not say whether the recommendations should be adjustable for organizations that use custom templates with different limits (Decision 3: fixed constants).
6. The issue text gives 64 as the S3 limit (corrected, Decision 4).
7. The over-maximum case: when an argument already exceeds the template's `MaxLength`, the warning appears and the prompt then rejects the default. The user sees two messages about the same value. This is acceptable. A distinct "will be rejected" message adds code for a rare path, so the plan does not include it.

## 6. Proposed approach

1. **Constants** near the other module constants in `cli/config.py` (after `VALID_INFRA_TYPES`), fixed and not configurable: `RECOMMENDED_MAX_PREFIX_LENGTH = 6`, `RECOMMENDED_MAX_PROJECT_ID_LENGTH = 20`, `RECOMMENDED_MAX_STAGE_ID_LENGTH = 6`, `RECOMMENDED_MAX_PREFIX_PROJECT_LENGTH = 28`, `RECOMMENDED_MAX_COMBINED_LENGTH = 32`. Comments cite the Atlantis template text and the AWS limits.
2. **Pure helper** `get_name_length_warnings(prefix, project_id, stage_id, parameters) -> List[str]`:
   - Lengths are plain character counts, summed without separators.
   - Considers a value only if the template declares its parameter. A `stage_id` of `'default'` or empty counts as absent.
   - Emits one line per individual value over its recommendation, naming the parameter, its length, and the recommended maximum. It never includes the value itself. Dashes in `StageId` are not warned about.
   - Emits a line for Prefix+ProjectId over 28 when both are declared, and a line for the three-way total over 32 when all three are declared.
   - When any line is emitted, appends: "Combined lengths of Prefix+ProjectId+StageId > 32 may cause deployment errors when creating resources with name-length restrictions. (e.g., S3 bucket names must not exceed 63 characters and IAM role names must not exceed 64 characters)".
   - Returns an empty list when nothing is over a recommendation.
3. **Printer** `show_name_length_warnings(...)` renders the lines with the existing warning style (`Colorize.box_warning` or `Colorize.warning`, matching nearby output) and logs each with `Log.warning`. It never prompts and never exits. No mode asks for confirmation.
4. **Call sites** (all three modes warn; none prompts or changes an exit code):
   - Interactive `main()`: after `get_template_parameters` (`:3156`) and before the "Enter to accept default" line, using the argument values. After `prompt_for_parameters` (`:3184`), compare the final `Prefix`, `ProjectId`, and `StageId` with the argument values. If any changed, run the check again on the final values.
   - `run_skeleton_mode`: after `get_template_parameters` (`:2808`), using the argument values.
   - `run_headless_mode`: after validation succeeds (`:2899-2911`), using the `Prefix`, `ProjectId`, and `StageId` values from the skeleton file, as a plain-text `Warning:` message.
5. **Docs and release**: `docs/SCRIPT-GUIDE.md` `config.py` section, `EPILOG` note, a new `v0.0.22 (unreleased)` CHANGELOG header with an "Added" entry linking this spec and issue #8, and a MINOR `VERSION` bump of `config.py` (`v0.1.9/2026-07-24` to `v0.2.0/<date>`).
6. **Tests** as listed in 4.2.

**Alternatives considered**
- *Prompt "Continue? (y/N)" after the warning.* Rejected: the issue says the user may ignore the recommendation, and a prompt would stall headless runs. Interactive users can already press `^` at the first prompt to exit.
- *Hard-fail above the recommendations.* Rejected by the issue.
- *Read the maximums from each template's `MaxLength`.* Not needed. The template already enforces those. The recommendations are not in the template metadata and must be constants.
- *Make the limits overridable in `defaults/settings.json`.* Not chosen (Decision 3). It can be added later without breaking the constants.
- *Add the check to `_validate_args` in `ConfigManager.__init__`.* Rejected: it runs before the template is known, so it cannot tell whether `StageId` or `ProjectId` applies.

## 7. Related improvements

| Item | Class | Rationale | Effort | Risk |
|------|-------|-----------|--------|------|
| Validate `Prefix` and `ProjectId` arguments against the template `AllowedPattern` before they are used in paths and defaults lookups (`get_samconfig_dir`, `{prefix}-defaults.json`) | Spin off, filed as [#18](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/18) (Decision 5) | Separate from length warnings. It changes failure behavior and touches every infra type. | S | Low |
| Atlantis templates state Prefix+ProjectId ≤ 28 only in text and do not state the 32 or StageId 2-6 limits | Note only | Belongs to `63Klabs/atlantis-sam-templates`. The scripts constants cite it. | S | None |
| Print the same warning from `deploy.py` | Note only | The configuration step is the right place. `deploy.py` reads an already-saved config. | S | None |

## 8. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Noise for existing stacks that exceed a recommendation | Warning only, concise, one box per run. |
| Wrong guidance for organizations using `S3BucketNameOrgPrefix` or custom templates | Text says "may cause"; constants documented. The constants are fixed (Decision 3). |
| A bug in the helper aborts a run | Pure function, no I/O, no `sys.exit`. Tests cover missing parameters and `'default'` stage. |
| Warning text goes stale if AWS limits change | Cite the limits by name in the constants' comments. |
| Headless output parsed by automation | Warnings do not change exit codes. Plain text, prefixed `Warning:`. |

## 9. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Q1-B: the warning appears in interactive, `--skeleton`, and `--headless` modes. It never prompts and never changes an exit code. | Headless runs are where agents and pipelines pick names unattended. One helper call per mode. |
| 2 | Q2-B: interactive mode checks the arguments before the prompts, and checks the final values again if any of the three changed. | Keeps the issue's timing and closes the edit gap. |
| 3 | Q3-A: the recommendation limits are fixed constants in `cli/config.py`. | The figures come from the Atlantis templates. Nothing in the issue asks for tuning. |
| 4 | Q4-A: the warning sentence states S3 bucket names must not exceed 63 characters and IAM role names 64. | AWS documents 63 for S3 buckets and 64 for IAM roles. A wrong limit would mislead users. |
| 5 | Q5-A: validating `Prefix` and `ProjectId` arguments before use in paths is a separate issue, not part of this spec. Filed as [#18](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/18) (label `enhancement`; no duplicate among issues #1-#17). | No shared root cause. Has its own compatibility questions. |
| D1 | Warn only. No confirmation prompt in any mode. | The issue says the user can ignore it. A prompt would stall `--headless`. |
| D2 | Lengths are plain character counts summed without separators. | 6 + 20 + 6 = 32, and the template wording "length of Prefix + Project ID". |
| D3 | Only parameters the template declares are checked. | Service-role templates declare `Prefix` only. Storage templates declare no `StageId`. |
| D4 | The warning names parameters and lengths, never values. | Avoids echoing escape sequences from skeleton files. |
| D5 | Dashes in `StageId` are not warned about. | Templates allow them (`^[a-z][a-z0-9-]{0,6}[a-z0-9]$`). |
| D6 | The helper and constants stay in `cli/config.py`. | Only `config.py` needs them. |
| D7 | `config.py` `VERSION` gets a MINOR bump and a `v0.0.22 (unreleased)` CHANGELOG header is created. | `ascs-cli-script-versioning` and `changelog-convention`. |

D1-D7 were listed for veto in the draft and were not vetoed.

**Spin-off disposition:** Decision 5 is filed as [#18](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/18).

## 10. Open questions and recommendations

No open questions.
