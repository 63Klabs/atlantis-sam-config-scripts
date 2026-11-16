# Implementation Plan

## Overview

Warn in `config.py` when Prefix, ProjectId, or StageId exceed the recommended lengths ([issue #8](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/8)). The work adds five constants, a note constant, and three functions (`get_name_length_warnings`, `show_name_length_warnings`, `warn_if_final_names_exceed`) to `cli/config.py`, and four call sites: two in interactive `main()`, one in `run_skeleton_mode`, one in `run_headless_mode`. The warning is advisory in every mode. Requirements are in [requirements.md](requirements.md) and the design in [design.md](design.md).

**Order of work:** pure function first (with its tests), then the printer, then the call sites, then documentation, then release verification. Each code task is followed by its tests so a failure points at one change.

**Test conventions:**
- New tests go in `tests/test_name_length_warnings.py` (function, printer, wrapper) and `tests/test_name_length_flow.py` (call sites). Import as the existing tests do: `sys.path.insert(0, <repo>/cli)`, then `from config import ...`.
- Follow `tests/test_validation.py` for Hypothesis tests (`@settings(max_examples=100, deadline=None)`), `tests/test_skeleton_flow.py` for skeleton-mode flow tests, and `tests/test_headless_flow.py` for headless-mode flow tests (the stacked `patch.object(ConfigManager, ...)` pattern with `__init__` replaced).
- Tests need no AWS, git, or network access. Patch `Git`, `ConfigManager` methods, and file access as the existing tests do.
- Run tests with `source .ve/bin/activate && python -m pytest ...`. Baseline before any change: `python -m pytest tests cli/lib -q` reports 519 passed (checked 2026-11-15 at `b189708`).
- Running tests rewrites log files under `cli/logs/`. Ignore them when reviewing `git diff`.
- Names follow `naming-conventions-python`: constants `UPPER_SNAKE_CASE`, functions `snake_case`, test functions `test_<what>_<expected>`.

## Tasks

- [x] 1. Confirm the starting state
  - Run `git status --short -- cli tests docs CHANGELOG.md` and confirm there are no uncommitted changes to those paths. Uncommitted files under `.kiro/specs/` belong to this spec and other work.
  - Record the current `VERSION` of `cli/config.py` (`v0.1.9/2026-07-24` at planning time) and today's date, for task 6.1
  - Run the baseline: `source .ve/bin/activate && python -m pytest tests cli/lib -q`. Record the pass count (519 at planning time).
  - No code is changed in this task
  - _Requirements: 6.11, 7.1_

- [x] 2. Constants and the pure warning function
  - [x] 2.1 Add the constants (`cli/config.py`)
    - Directly after `VALID_INFRA_TYPES` (`cli/config.py:49`), add `RECOMMENDED_MAX_PREFIX_LENGTH = 6`, `RECOMMENDED_MAX_PROJECT_ID_LENGTH = 20`, `RECOMMENDED_MAX_STAGE_ID_LENGTH = 6`, `RECOMMENDED_MAX_PREFIX_PROJECT_LENGTH = 28`, `RECOMMENDED_MAX_COMBINED_LENGTH = 32`
    - Add `NAME_LENGTH_WARNING_NOTE` with the exact text of requirement 1.8, and `NAME_LENGTH_HEADING` and `NAME_LENGTH_HEADING_FINAL` with the texts in design.md
    - Comment each figure with its source as in design.md (Atlantis template text, issue #8, and the S3 63 and IAM 64 limits)
    - Do not read the limits from `defaults/settings.json`, defaults files, arguments, or the environment
    - _Requirements: 1.1, 1.8, 7.5_
  - [x] 2.2 Add `get_name_length_warnings` (`cli/config.py`)
    - Place it in a new section with a header comment before `parse_args`, so the three new functions stay together
    - Signature `get_name_length_warnings(prefix, project_id, stage_id, parameters) -> List[str]`
    - Follow the steps in design.md: build the `lengths` dict from declared parameters and `str` values (stage of `''` or `'default'` is absent; `parameters` of `None` is `{}`), append one line per value over its limit in the order Prefix, ProjectId, StageId, then the Prefix+ProjectId line, then the three-way line, then `NAME_LENGTH_WARNING_NOTE` only if any line was added
    - Line formats: `"<Name> is <n> characters (recommended maximum: <limit>)."`, `"Prefix+ProjectId is <n> characters (recommended maximum: 28)."`, `"Prefix+ProjectId+StageId is <n> characters (recommended maximum: 32)."`
    - No I/O, no `sys.exit`, never include the value in a line, no character or minimum-length checks
    - Add a Google-style docstring with Args, Returns, and an Example (doctest style) per `documentation-standards-python.md`
    - _Requirements: 1.2 to 1.10, 7.5_
  - [x] 2.3 Unit tests for the function (`tests/test_name_length_warnings.py`, new file)
    - Create the file with a module docstring that has a `Feature: config-name-length-warnings` line, and a helper `_declared(*names)` that returns a `parameters` dict with those names
    - `TestBoundaries`: Prefix 6 and 7, ProjectId 20 and 21, StageId 6 and 7, Prefix+ProjectId 28 and 29, total 32 and 33. At the limit gives no line, one over gives exactly the expected line (requirements 1.5 to 1.7)
    - `TestCombinedOnly`: a value over its own limit while the combined limits are not; only a combined limit over while each value is within its own (requirements 1.5 to 1.7)
    - `TestNote`: the note line is last and present exactly when another line is present; the note text equals the text in requirement 1.8 (pin the literal string in the test) (requirements 1.8, 1.9)
    - `TestDeclaredParameters`: a `Prefix`-only template with long `project_id` and `stage_id` arguments gives no ProjectId or StageId line; a `Prefix`+`ProjectId` template ignores a long `stage_id` and gives no three-way line; all three declared gives all lines; empty `parameters` and `None` give `[]`; `stage_id` of `None`, `''`, and `'default'` is absent; non-`str` values (`None`, `123`, a `MagicMock`) are absent and do not raise (requirements 1.3, 1.4, 1.7)
    - `TestNoValueInOutput`: use a value that has a newline and `\x1b[31m` and is longer than the limit; assert no returned line contains the value, the newline, or the escape. Assert that a `StageId` with dashes of length 6, and a one-character `Prefix`, produce no line (requirements 1.5, 1.10)
    - Run `source .ve/bin/activate && python -m pytest tests/test_name_length_warnings.py -v`. All must pass.
    - _Requirements: 6.2, 6.3, 6.4_
  - [x] 2.4 Property test for the function (same file)
    - `TestWarningsProperty`: Hypothesis strategy draws lengths 0 to 40 for the three values, builds strings of `a` repeated, and draws a subset of `{'Prefix', 'ProjectId', 'StageId'}` as declared
    - The oracle is computed inside the test from the numeric limits, not by calling the function's internals: expected individual lines, expected combined lines, and expected empty result
    - Assert: no exception; each individual line is present exactly when that declared value is over its limit; the Prefix+ProjectId line is present exactly when both are declared and the sum is over 28; the three-way line is present exactly when all three are declared and the sum is over 32; the result is empty exactly when none of these hold
    - Style: follow `tests/test_validation.py`, 100 or more examples
    - _Requirements: 6.5_
  - Run `source .ve/bin/activate && python -m pytest tests/test_name_length_warnings.py -q` and then the full baseline command. Confirm 519 existing tests still pass. No call site has been added yet, so behavior is unchanged.

- [x] 3. Printer and final-values wrapper
  - [x] 3.1 Add `show_name_length_warnings` (`cli/config.py`)
    - Signature `show_name_length_warnings(warnings: List[str], headless: bool = False, heading: str = NAME_LENGTH_HEADING) -> None`, in the same section as `get_name_length_warnings`
    - Empty list: return with no output and no logging
    - `headless=False`: blank line, `click.echo(Colorize.warning(heading))`, one `click.echo(Colorize.warning(f"  {line}"))` per line, blank line
    - `headless=True`: one `click.echo(f"Warning: {line}", err=True)` per line, no color, no heading, no blank lines
    - In both modes call `Log.warning(line)` once per line (`Log.warning` writes to the file only)
    - Wrap the printing block, and each `Log.warning` call, in its own `try/except Exception: pass`. Do not catch `KeyboardInterrupt`. Add a comment that explains why the failure is swallowed.
    - No prompt, no `sys.exit`, no return value. Add a Google-style docstring.
    - _Requirements: 2.1 to 2.5, 7.5_
  - [x] 3.2 Add `warn_if_final_names_exceed` (`cli/config.py`)
    - Signature `warn_if_final_names_exceed(initial_names, parameter_values, parameters) -> bool`
    - Final values: `parameter_values.get('Prefix', initial_names[0])`, and the same for `ProjectId` (index 1) and `StageId` (index 2)
    - If the final tuple equals `initial_names`, return `False` and print nothing. Otherwise call `show_name_length_warnings(get_name_length_warnings(*final_names, parameters), heading=NAME_LENGTH_HEADING_FINAL)` and return `True`
    - Add a Google-style docstring
    - _Requirements: 3.2, 7.5_
  - [x] 3.3 Printer and wrapper tests (`tests/test_name_length_warnings.py`)
    - `TestShowWarnings`: patch `config.click.echo` and `config.Log`. Interactive style: heading and each line echoed with `Colorize.warning` formatting, `Log.warning` called once per line. Empty list: `click.echo` and `Log.warning` not called. Headless: each line echoed with `err=True` and the `Warning: ` prefix, no heading, `Log.warning` called per line. Also run one headless call with `capsys` and no patches and assert stdout is empty and stderr has the `Warning: ` lines (requirements 2.1 to 2.3)
    - `TestFailureIsolation`: `click.echo` patched to raise, then `Log.warning` patched to raise. In each case the call returns without an exception (requirement 2.5)
    - `TestNoPrompts`: patch `click.confirm`, `click.prompt`, and `Colorize.prompt` to raise `AssertionError`; call `show_name_length_warnings` and `warn_if_final_names_exceed` in both modes; they must not trip (requirement 2.4)
    - `TestFinalNames`: unchanged values return `False` and `show_name_length_warnings` is not called; a changed `Prefix` that is over the limit returns `True` and the call uses `NAME_LENGTH_HEADING_FINAL`; a changed value within the limits returns `True` and prints nothing; a `parameter_values` dict without the three keys returns `False`; a changed `StageId` from `'default'` to a long value is detected (requirements 3.2, 6.6)
    - Run `source .ve/bin/activate && python -m pytest tests/test_name_length_warnings.py -v`. All must pass.
    - _Requirements: 6.6, 6.9, 6.10_

- [x] 4. Call sites
  - [x] 4.1 Interactive `main()` (`cli/config.py`)
    - After `parameter_groups, parameters = config_manager.get_template_parameters(template_file)` (`:3156`), add `initial_names = (config_manager.prefix, config_manager.project_id, config_manager.stage_id)` and `show_name_length_warnings(get_name_length_warnings(*initial_names, parameters))`, before the existing `print()` and the "Enter to accept default" line
    - After `parameter_values = config_manager.prompt_for_parameters(...)` (`:3184`), add `warn_if_final_names_exceed(initial_names, parameter_values, parameters)`
    - Use `config_manager.stage_id`, not `args.stage_id`, because `prompt_for_stage_id` may have set it
    - Do not wrap the calls in extra `try/except`, and do not change anything else in `main()`
    - _Requirements: 3.1, 3.2_
  - [x] 4.2 `run_skeleton_mode` (`cli/config.py`)
    - After `get_template_parameters` (`:2808`) and before `generate_skeleton` (`:2812`), add `show_name_length_warnings(get_name_length_warnings(config_manager.prefix, config_manager.project_id, config_manager.stage_id, parameters))`
    - _Requirements: 3.3_
  - [x] 4.3 `run_headless_mode` (`cli/config.py`)
    - After `parameter_values` is extracted from the skeleton (`:2916-2923`), which is after the validation exit, add `show_name_length_warnings(get_name_length_warnings(parameter_values.get('Prefix'), parameter_values.get('ProjectId'), parameter_values.get('StageId'), parameters), headless=True)`
    - Do not run the check before the validation exit
    - _Requirements: 3.4, 3.5_
  - [x] 4.4 Flow tests (`tests/test_name_length_flow.py`, new file)
    - Create the file with a module docstring that has a `Feature: config-name-length-warnings` line. Reuse the helper style of `_make_headless_args` and `_valid_skeleton` from `tests/test_headless_flow.py` (copy what is needed).
    - `TestSkeletonModeWarns`: reuse the mock setup of `tests/test_skeleton_flow.py`. `ConfigManager` mock with `prefix='acmecorp'` and `get_template_parameters` returning `({}, {'Prefix': {}, 'ProjectId': {}, 'StageId': {}})`. Patch `config.show_name_length_warnings` and assert it is called once with the lines for a 8-character Prefix, before `generate_skeleton` (use a shared manager mock to record order), and that the skeleton file is still written. A second case with short values asserts the printer is called with an empty list or not at all (requirement 5.1) (requirements 3.3, 6.7)
    - `TestHeadlessWarns`: reuse the patch stack of `TestHeadlessSuccessfulFlow` in `tests/test_headless_flow.py` with a skeleton whose `Prefix` is 8 characters and `get_template_parameters` declaring all three. Use `capsys`. Assert `Warning: Prefix is 8 characters` is in stderr, the warning text is not in stdout, `save_config` was called once, and no `SystemExit` was raised (requirements 2.3, 3.4, 5.4, 6.8)
    - `TestHeadlessValidationFailure`: `validate_all_parameters` returns one failure. Assert `SystemExit` as before and that `config.get_name_length_warnings` (patched) was not called (requirement 3.4)
    - `TestHeadlessMissingStageId`: skeleton without `StageId` and a template that declares it. Assert the run completes and no `StageId` line is printed (requirement 3.5)
    - `TestInteractiveOrder`: patch `config.parse_args` (returns a `Namespace` with `infra_type='pipeline'`, `prefix='acmecorp'`, `project_id='myapp'`, `stage_id='dev'`, `check_stack=False`, `skeleton=False`, `skeleton_verbose=False`, `headless=False`, `deploy=False`, `profile=None`, `region=None`, `no_browser=False`), `config.ConfigManager` (class mock; instance attributes `prefix`, `project_id`, `stage_id`, `defaults = {}`, `read_samconfig` returns `None`, `discover_templates` returns `['t.yml']`, `get_template_parameters` returns `([], params)`, `resolve_role_arn` returns `''`, `calculate_stage_defaults` returns `{}`, `merge_tags` returns `[]`, `get_default_tags` returns `{}`), `config.Git`, `config.FileNameListUtils` (select returns `'t.yml'`), `config.TagUtils`, `config.CodeCommitUtils`, and `config.click.confirm` (returns `False`). Attach `get_template_parameters`, `prompt_for_parameters`, and the patched `show_name_length_warnings` to one parent mock and assert the call order: `get_template_parameters`, then the first `show_name_length_warnings`, then `prompt_for_parameters` (requirements 3.1, 6.6)
    - `TestInteractiveSecondCheck`: the same patch stack. When `prompt_for_parameters` returns `{'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}` and the argument values were `acmecorp`, assert a second printer call with `heading=NAME_LENGTH_HEADING_FINAL`. When it returns values equal to the argument values, assert only one printer call (requirements 3.2, 6.6)
    - If the `main()` patch stack becomes brittle (a call in `main()` that no patch covers), add the missing patch rather than changing `main()`
    - Run `source .ve/bin/activate && python -m pytest tests/test_name_length_flow.py -v`. All must pass.
    - _Requirements: 6.6, 6.7, 6.8_
  - Run the full baseline command. Confirm the 519 existing tests plus the new ones pass.

- [x] 5. Checkpoint - Ensure all tests pass
  - Run `source .ve/bin/activate && python -m pytest tests cli/lib -q`. Confirm all pass, and that the count is the 519 baseline plus the new tests.
  - Run `git diff --stat` and confirm the code changes are limited to `cli/config.py` and the two new test files. Nothing under `cli/lib/`, `cli/deploy.py`, `cli/delete.py`, `cli/import.py`, `cli/create_repo.py`, `cli/update.py`, `README.md`, or `AGENTS-FOR-END-USE.md` changed.
  - Confirm with a short manual dry run that needs no AWS: `source .ve/bin/activate && python -c "import sys; sys.path.insert(0,'cli'); from config import get_name_length_warnings as g; print(g('acmecorp','a'*21,'test-1',{'Prefix':{},'ProjectId':{},'StageId':{}}))"` prints four warning lines (Prefix, ProjectId, Prefix+ProjectId, total) plus the note
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: 5.1 to 5.5, 6.11, 7.6_

- [x] 6. Version, help text, and user documentation
  - [x] 6.1 Version marker (`cli/config.py`)
    - Read the current `VERSION` (`v0.1.9/2026-07-24` at planning time) and compare its date with today's date, per `.kiro/steering/ascs-cli-script-versioning.md`
    - If the date differs, set `VERSION = "v0.2.0/<today>"` (MINOR: new behavior, no interface change). If the date already matches, leave it unchanged.
    - Note the final value for task 7
    - _Requirements: 7.1_
  - [x] 6.2 `EPILOG` note (`cli/config.py`)
    - Under `Notes:` in `EPILOG` (`cli/config.py:2603-2663`), add one line: a warning is shown when Prefix, ProjectId, or StageId exceed the recommended lengths (Prefix 6, ProjectId 20, StageId 6; Prefix+ProjectId 28; all three 32), and it does not stop the run
    - Check `./cli/config.py -h` runs and shows the line
    - _Requirements: 7.4_
  - [x] 6.3 Update `docs/SCRIPT-GUIDE.md`
    - In the `config.py` section, after the usage block, add a short paragraph: the script warns when Prefix, ProjectId, or StageId exceed the recommended lengths; list the limits; the warning is advisory and the template still enforces the maximums (8, 26, 8); it appears in interactive, `--skeleton`, and `--headless` modes; it does not prompt or change exit codes
    - Follow `.kiro/steering/documentation-standards-markdown.md` (code blocks with a language, relative links) and keep user documentation free of implementation detail
    - Confirm the statements match the code (limits, modes, S3 63 and IAM 64 wording in the warning)
    - _Requirements: 7.3_
  - [x] 6.4 Confirm no other documentation changes
    - Search `README.md` and `AGENTS-FOR-END-USE.md` for statements about `config.py` that the feature makes inaccurate. Change them only if one is. Otherwise leave both files unchanged.
    - _Requirements: 7.6_

- [x] 7. Update CHANGELOG.md
  - Add a new `## v0.0.22 (unreleased)` header directly above `## v0.0.21 (2026-11-15)`, with an `### Added` section under it. Do not modify existing text.
  - Entry: `- **Script: config.py vX.Y.Z** - Added a warning when Prefix, ProjectId, or StageId exceed the recommended lengths [Spec: 0-0-22-the-config-py-script-should-ensure-prefix](.kiro/specs/0-0-22-the-config-py-script-should-ensure-prefix/), addresses [#8](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/8)`, with `vX.Y.Z` equal to the final `VERSION` from task 6.1
  - Sub-bullets: the recommended lengths (Prefix 6, ProjectId 20, StageId 6, Prefix+ProjectId 28, all three 32) and that the warning names which values exceed; it is advisory and never prompts, blocks, or changes exit codes; it applies in interactive, `--skeleton`, and `--headless` modes (headless writes `Warning:` lines to standard error); only parameters the selected template declares are checked; template validation still enforces the maximums
  - Follow `.kiro/steering/changelog-convention.md` and the format of the neighboring `v0.0.21` entries
  - _Requirements: 7.2_

- [x] 8. Final checkpoint
  - Run `source .ve/bin/activate && python -m pytest tests cli/lib -q`. All tests pass.
  - Run `git status --short` and confirm only the expected files changed: `cli/config.py`, `tests/test_name_length_warnings.py`, `tests/test_name_length_flow.py`, `docs/SCRIPT-GUIDE.md`, `CHANGELOG.md`, and the spec files
  - Check that `VERSION`, the CHANGELOG entry version, and the `EPILOG` and docs wording agree
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: 6.11, 7.1 to 7.6_

- [x] 9. Release verification and housekeeping (maintainer task)
  - **The agent does not deploy, create stacks, push commits, or close issues without the maintainer's go-ahead.**
  - **Interactive, pipeline template (requirement 8.1):** run `./cli/config.py pipeline <prefix> <project> <stage> --profile <profile>` from a scratch copy with a Prefix of 8, ProjectId of 22, and StageId of 8 characters, and a pipeline template. Confirm the warning lists each value, the Prefix+ProjectId and total lines, and the note; that it appears after the template version output and before the prompts; and that the run continues. Retype a shorter Prefix at the prompt and confirm the second warning appears with the "values you entered" heading only when the final values still exceed a limit. Press `^` at the first prompt to exit without saving.
  - **Service-role and storage templates (requirement 8.2):** run the script against a service-role template and a storage template with the same long values. Confirm no warning mentions ProjectId or StageId for service-role, and none mentions StageId for storage.
  - **Skeleton and headless (requirement 8.3):** run `--skeleton`, then edit the skeleton to long values and run `--headless`. Confirm the warning appears on standard error in headless mode (`2>warn.txt` captures it), standard output has no warning lines, and the exit status matches a run with short values. Delete any skeleton, samconfig, and defaults files created in the scratch copy.
  - **Housekeeping:** after the release ships, close issue #8 with a reference to this spec. The spin-off [#18](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/18) stays open and is planned separately.
  - Record the outcome of the verification runs
  - _Requirements: 8.1, 8.2, 8.3, 8.4_
