# Requirements: Warn When Prefix, ProjectId, and StageId Exceed Recommended Lengths

## Introduction

`config.py` takes `Prefix`, `ProjectId`, and `StageId` as arguments and uses them as the defaults for the template parameters of the same names. The Atlantis templates enforce only the absolute maximums (Prefix 8, ProjectId 26, StageId 8). Names that are valid but long can fail later in CloudFormation, when a resource name exceeds a service limit. [Issue #8](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/8) asks `config.py` to warn when the three values exceed the recommended lengths and to leave enforcement of the maximums to template validation. The decisions behind these requirements are locked in [PLAN.md](PLAN.md).

The feature adds a pure helper that compares the lengths against fixed recommendation constants and returns warning lines, and a printer that shows and logs them. Interactive, `--skeleton`, and `--headless` modes call it. It never prompts, never blocks, and never changes an exit code. Only parameters that the selected template declares are checked, because service-role templates declare `Prefix` only and storage templates declare no `StageId`.

## Terminology

- **Recommendation limits** - Prefix 6, ProjectId 20, StageId 6 characters; Prefix+ProjectId 28; Prefix+ProjectId+StageId 32. They are the recommendations stated in the Atlantis templates and in issue #8, not the template `MaxLength` values.
- **Declared parameter** - a parameter name present in the `parameters` dict that `get_template_parameters()` returns for the selected template.
- **Length** - the number of characters in the value. Combined lengths are the sum of the individual lengths, with no separators (PLAN.md D2).
- **Warning lines** - the strings that the helper returns. Their content is defined in 1.6 to 1.10.

---

## Requirements

### 1. Warning content and rules

1.1 The system SHALL define the recommendation limits as module-level constants in `cli/config.py`, in `UPPER_SNAKE_CASE`, with fixed values: `RECOMMENDED_MAX_PREFIX_LENGTH = 6`, `RECOMMENDED_MAX_PROJECT_ID_LENGTH = 20`, `RECOMMENDED_MAX_STAGE_ID_LENGTH = 6`, `RECOMMENDED_MAX_PREFIX_PROJECT_LENGTH = 28`, `RECOMMENDED_MAX_COMBINED_LENGTH = 32`. The limits SHALL NOT be configurable through `defaults/settings.json`, defaults files, arguments, or environment variables (PLAN.md Decision 3)

1.2 The system SHALL provide a pure function `get_name_length_warnings(prefix, project_id, stage_id, parameters)` in `cli/config.py` that returns a `List[str]` of warning lines. It SHALL perform no I/O, SHALL NOT call `sys.exit`, and SHALL NOT raise for any `str` or `None` inputs (PLAN.md D6)

1.3 WHEN the template does not declare a parameter THEN the function SHALL ignore the matching value. `Prefix` is considered only if `'Prefix'` is in `parameters`, `ProjectId` only if `'ProjectId'` is in `parameters`, and `StageId` only if `'StageId'` is in `parameters` (PLAN.md D3)

1.4 WHEN `stage_id` is `None`, empty, or the string `'default'` THEN the function SHALL treat `StageId` as absent for all rules in this section

1.5 WHEN a considered value is longer than its recommendation limit (Prefix over 6, ProjectId over 20, StageId over 6) THEN the function SHALL return one line for that value that names the parameter, states its length, and states the recommended maximum. The line SHALL NOT contain the value itself (PLAN.md D4). A value exactly at its limit SHALL NOT produce a line

1.6 WHEN both `Prefix` and `ProjectId` are considered and their combined length is over 28 THEN the function SHALL return one line that names `Prefix+ProjectId`, states the combined length, and states the recommended maximum of 28

1.7 WHEN `Prefix`, `ProjectId`, and `StageId` are all considered and their combined length is over 32 THEN the function SHALL return one line that names `Prefix+ProjectId+StageId`, states the combined length, and states the recommended maximum of 32. The three-way line SHALL NOT be returned when any of the three is not considered

1.8 WHEN the function returns at least one line from 1.5 to 1.7 THEN it SHALL also return, after those lines, this explanation line: `Combined lengths of Prefix+ProjectId+StageId > 32 may cause deployment errors when creating resources with name-length restrictions. (e.g., S3 bucket names must not exceed 63 characters and IAM role names must not exceed 64 characters)` (PLAN.md Decision 4)

1.9 WHEN no value or combination is over its limit THEN the function SHALL return an empty list

1.10 The function SHALL NOT warn about the characters in a value, including dashes in `StageId`, and SHALL NOT warn about values that are shorter than a template minimum. Character and minimum checks remain the job of template validation (PLAN.md D5)

### 2. Display and logging

2.1 The system SHALL provide a function `show_name_length_warnings(...)` in `cli/config.py` that takes the warning lines (or the inputs to compute them), prints them, and writes each line to the log with `Log.warning`. It SHALL print and log nothing when there are no lines

2.2 WHEN it is called from interactive or `--skeleton` mode THEN it SHALL print the lines with the existing warning style from `cli/lib/tools.py` (`Colorize.warning` or `Colorize.box_warning`, matching the surrounding output), with a blank line before and after the block

2.3 WHEN it is called from `--headless` mode THEN it SHALL print each line as plain text without color, prefixed with `Warning: `, to standard error, so standard output stays free of added lines

2.4 The function SHALL NOT prompt, SHALL NOT call `sys.exit`, and SHALL NOT change the exit status of the run in any mode (PLAN.md D1, Decision 1)

2.5 IF printing or logging the warning raises an exception THEN the exception SHALL NOT stop the run. The run SHALL continue as if no warning applied

### 3. Where the check runs

3.1 WHEN `config.py` runs in interactive mode THEN the system SHALL run the check after `get_template_parameters()` returns and before the "Enter to accept default" line is printed, using `config_manager.prefix`, `config_manager.project_id`, and `config_manager.stage_id` and the declared parameters. The check SHALL run whether or not a samconfig already exists for the stack

3.2 WHEN `prompt_for_parameters()` has returned in interactive mode THEN the system SHALL compare the final `Prefix`, `ProjectId`, and `StageId` values with the values used in 3.1. IF any of the three differ THEN the system SHALL run the check again on the final values and show the result. IF none differ THEN the system SHALL NOT show the warning a second time (PLAN.md Decision 2)

3.3 WHEN `config.py` runs with `--skeleton` or `--skeleton-verbose` THEN the system SHALL run the check after `get_template_parameters()` returns and before the skeleton is generated, using the argument values held by `ConfigManager` (PLAN.md Decision 1)

3.4 WHEN `config.py` runs with `--headless` THEN the system SHALL run the check after parameter validation has succeeded and before `build_config_headless()` is called, using the `Prefix`, `ProjectId`, and `StageId` values from the skeleton file's `parameter_overrides` for the active stage. WHEN validation fails THEN the system SHALL NOT run the check, because the run exits with the validation errors

3.5 WHEN a value is missing from the skeleton file's `parameter_overrides` in headless mode THEN the check SHALL treat that value as absent and SHALL NOT raise

### 4. Interaction with existing validation

4.1 The system SHALL NOT change `validate_parameter()`, `validate_all_parameters()`, or the prompt loop. A value over the template `MaxLength` SHALL continue to be rejected with the existing messages

4.2 The warning for a value over the template `MaxLength` SHALL be the same as for any value over its recommendation. The system SHALL NOT add a separate "will be rejected" message

### Unchanged behavior

5.1 WHEN all lengths are within the recommendation limits THEN the output of `config.py` in every mode SHALL be identical to the output before this change

5.2 `config.py` SHALL CONTINUE TO accept the same arguments and options, with the same behavior. The system SHALL NOT add a flag or option

5.3 The system SHALL CONTINUE TO generate the same samconfig file, skeleton file, defaults files, tags, and git commit messages as before

5.4 Exit codes SHALL CONTINUE TO be unchanged in every mode, including when a warning is shown

5.5 `deploy.py`, `delete.py`, `import.py`, `create_repo.py`, `update.py`, and `cli/lib/` SHALL CONTINUE TO behave exactly as before. The feature SHALL NOT change them

---

## Testing Requirements

6.1 Tests SHALL run on Linux under the existing pytest and Hypothesis setup (`cli/requirements-test.txt`) and SHALL NOT require AWS, git, or network access. Existing tests mock `ConfigManager` and `Git`; new flow tests SHALL do the same

6.2 Unit tests for `get_name_length_warnings` SHALL live in `tests/test_name_length_warnings.py` and SHALL cover the boundaries at each limit (6 and 7, 20 and 21, 28 and 29, 32 and 33), the case where a value is over its own limit while the combined limits are not, the case where only the combined limit is over, and the explanation line being present exactly when another line is present (requirements 1.5 to 1.9)

6.3 Unit tests SHALL cover the declared-parameter rules: a `Prefix`-only template (service-role), a `Prefix` and `ProjectId` template (storage) with a `stage_id` argument ignored, a template with all three, an empty `parameters` dict, and `stage_id` of `None`, `''`, and `'default'` (requirements 1.3, 1.4, 1.7)

6.4 A test SHALL assert that no returned line contains the value, using a value with a newline and an ANSI escape sequence, and that dashes in `StageId` and values below the template minimum produce no line of their own (requirements 1.5, 1.10)

6.5 A property-based test with Hypothesis SHALL generate lengths for the three values and a random subset of declared parameters, and SHALL assert that: the function never raises, each individual line is present exactly when that declared value is over its limit, the combined lines are present exactly when their conditions hold, and the result is empty exactly when nothing is over a limit. It SHALL follow the style of `tests/test_validation.py`

6.6 Flow tests SHALL cover the interactive path. They SHALL assert that the check runs once before `prompt_for_parameters`, that it runs a second time only when a final value differs from the argument value, and that it does not run a second time when no value differs (requirements 3.1, 3.2). They SHALL follow the mocking style of the existing `main()` tests in `tests/`

6.7 Flow tests SHALL cover skeleton mode, following `tests/test_skeleton_flow.py`, and SHALL assert that the warning is shown for long arguments and that the skeleton is still written (requirement 3.3)

6.8 Flow tests SHALL cover headless mode, following `tests/test_headless_flow.py`, and SHALL assert that: long skeleton values produce `Warning: ` lines on standard error and the run still completes with the same exit status as before; the check does not run when validation fails; a missing `StageId` in the skeleton does not raise (requirements 2.3, 3.4, 3.5, 5.4)

6.9 A test SHALL assert that a failure inside the printer (for example `Log.warning` raising) does not stop the run (requirement 2.5)

6.10 A test SHALL assert that no prompt function (`click.confirm`, `click.prompt`, `Colorize.prompt`) is called by the check or the printer (requirement 2.4)

6.11 All existing tests SHALL continue to pass (519 tests in `tests/` and `cli/lib/test_*.py` pass at `b189708`)

---

## Version and Documentation Requirements

7.1 `cli/config.py` SHALL have its `VERSION` marker reviewed per `.kiro/steering/ascs-cli-script-versioning.md`. It is `v0.1.9/2026-07-24`. The feature adds behavior without breaking the interface, so on the implementation date the system SHALL set it to `v0.2.0/<implementation date>`. IF the embedded date already matches the implementation date THEN the marker SHALL stay unchanged

7.2 `CHANGELOG.md` SHALL gain a new `## v0.0.22 (unreleased)` header above `## v0.0.21 (2026-11-15)`, and an entry under `### Added` for `config.py` that links this spec, addresses [#8](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/8), and states: the script warns when Prefix, ProjectId, or StageId exceed the recommended lengths or their combined lengths exceed 28 and 32; the warning is advisory and never blocks, prompts, or changes exit codes; it applies in interactive, skeleton, and headless modes; and template validation still enforces the maximums. The entry version SHALL match the `VERSION` marker. Existing changelog text SHALL NOT be edited

7.3 `docs/SCRIPT-GUIDE.md`, in the `config.py` section, SHALL gain a short note that lists the recommended lengths, says the check is advisory, and says it applies to all three modes

7.4 The `EPILOG` text in `cli/config.py` SHALL gain a line under `Notes:` that says a warning is shown when Prefix, ProjectId, or StageId exceed the recommended lengths and that it does not stop the run

7.5 New Python code SHALL carry Google-style docstrings with Args, Returns, and Example per `.kiro/steering/documentation-standards-python.md`, and SHALL follow `naming-conventions-python` and `naming-conventions-common` (the new function names are `get_name_length_warnings` and `show_name_length_warnings`). The constants' comments SHALL name the source of each figure (Atlantis template text and the S3 and IAM limits)

7.6 `README.md` and `AGENTS-FOR-END-USE.md` SHALL NOT change unless a script usage statement in them becomes inaccurate. All changes SHALL stay inside `cli/`, `docs/`, `tests/`, and `CHANGELOG.md`, so `update.py` delivers the user-facing files

---

## Verification Requirements

8.1 Before release, the maintainer SHALL run `config.py` interactively against one pipeline template with a Prefix, ProjectId, and StageId that exceed the limits, and confirm the warning text, the position before the prompts, and that the run continues

8.2 Before release, the maintainer SHALL run `config.py` interactively against a service-role template and a storage template, and confirm that no warning mentions `ProjectId` or `StageId` for the service-role template and no warning mentions `StageId` for the storage template

8.3 Before release, the maintainer SHALL run a `--skeleton` and a `--headless` run with long values, and confirm that the warning appears on standard error in headless mode and that the exit status is unchanged

8.4 The implementing agent SHALL NOT deploy, create stacks, or push commits for these checks without the maintainer's go-ahead

---

## Additions beyond PLAN.md

These were decided while writing the requirements. They can be vetoed before design starts.

| # | Addition | Why |
|---|----------|-----|
| R1 | Headless warnings go to standard error, as plain `Warning: ` lines (2.3) | Keeps standard output unchanged for agents and pipelines that parse it. Existing headless errors also go to standard error through `sys.exit`. |
| R2 | A failure while printing or logging the warning never stops the run (2.5) | The check is advisory and must not become a new way for `config.py` to fail. |
| R3 | The check runs on every `config.py` run, including for stacks that already have a samconfig (3.1) | Matches PLAN.md section 4.2. The warning stays visible until the names are changed. |
| R4 | Over-`MaxLength` values get the same warning, with no extra message (4.2) | PLAN.md section 5 item 7: the extra message adds code for a rare path. |

---

## Out of Scope

- Making the recommendation limits configurable (PLAN.md Decision 3)
- Prompting for confirmation after a warning, and blocking the run (PLAN.md D1)
- Validating the `Prefix` and `ProjectId` arguments before they are used in paths (PLAN.md Decision 5, filed as [#18](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/18))
- Printing the same warning from `deploy.py`, `delete.py`, `import.py`, or `create_repo.py` (PLAN.md Section 7, note only)
- Changes to the Atlantis templates, including documenting the 32 and StageId limits there (PLAN.md Section 7, note only)
- Computing exact S3 bucket or IAM role name lengths from region, account id, resource id, or `S3BucketNameOrgPrefix`
