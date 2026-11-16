# Design: Warn When Prefix, ProjectId, and StageId Exceed Recommended Lengths

## Overview

`config.py` gains three module-level pieces and four one-line call sites. Everything lives in `cli/config.py` (PLAN.md D6). No file in `cli/lib/` changes.

| Piece | Kind | Purpose |
|-------|------|---------|
| `RECOMMENDED_MAX_*` constants and `NAME_LENGTH_WARNING_NOTE` | module constants | Fixed recommendation limits and the explanation sentence (Requirements 1.1, 1.8) |
| `get_name_length_warnings(prefix, project_id, stage_id, parameters)` | pure function | Returns warning lines. No I/O (1.2) |
| `show_name_length_warnings(warnings, headless=False, heading=...)` | printer | Prints and logs the lines. Never prompts, never exits, swallows its own failures (2.1 to 2.5) |
| `warn_if_final_names_exceed(initial_names, parameter_values, parameters)` | small wrapper | Interactive second check: compares the final values with the first-check values and warns only if they changed (3.2) |

The call sites are interactive `main()` (two calls), `run_skeleton_mode` (one), and `run_headless_mode` (one). The warning is advisory. `validate_parameter`, `validate_all_parameters`, and the prompt loop are untouched, so the template maximums stay enforced exactly as before (4.1).

## Current vs. target flow

```text
Interactive main()                      Target
------------------------------------    ------------------------------------------------
read samconfig, pick template           (unchanged)
get_template_parameters()               (unchanged)
                                        initial_names = (prefix, project_id, stage_id)
                                        show_name_length_warnings(get_name_length_warnings(*initial_names, parameters))
"Enter to accept default" line          (unchanged)
prompt_for_parameters()                 (unchanged)
                                        warn_if_final_names_exceed(initial_names, parameter_values, parameters)
tags, build_config, save_config ...     (unchanged)

run_skeleton_mode()                     Target
------------------------------------    ------------------------------------------------
get_template_parameters()               (unchanged)
                                        show_name_length_warnings(get_name_length_warnings(cm.prefix, cm.project_id, cm.stage_id, parameters))
generate_skeleton()                     (unchanged)

run_headless_mode()                     Target
------------------------------------    ------------------------------------------------
validate_all_parameters() ... exit      (unchanged; the check does not run when this exits)
parameter_values = skeleton[...]        (unchanged)
                                        show_name_length_warnings(get_name_length_warnings(values from parameter_values, parameters), headless=True)
build_config_headless()                 (unchanged)
```

## Constants

Placed directly after `VALID_INFRA_TYPES` (`cli/config.py:49`), `UPPER_SNAKE_CASE`, with a comment per figure naming its source (1.1, 7.5).

```python
# Recommended (not enforced) name lengths. Source: Atlantis template parameter text
# (Prefix "2-6 characters", Prefix + ProjectId "should not exceed 28", ProjectId
# "suggested maximum of 20") and issue #8 (StageId 6, combined 32). 6 + 20 + 6 = 32.
# The templates enforce the absolute maximums (Prefix 8, ProjectId 26, StageId 8).
RECOMMENDED_MAX_PREFIX_LENGTH = 6
RECOMMENDED_MAX_PROJECT_ID_LENGTH = 20
RECOMMENDED_MAX_STAGE_ID_LENGTH = 6
RECOMMENDED_MAX_PREFIX_PROJECT_LENGTH = 28
RECOMMENDED_MAX_COMBINED_LENGTH = 32
# AWS limits: S3 general purpose bucket names 3-63 characters, IAM role names 64.
NAME_LENGTH_WARNING_NOTE = (
    "Combined lengths of Prefix+ProjectId+StageId > 32 may cause deployment errors "
    "when creating resources with name-length restrictions. (e.g., S3 bucket names "
    "must not exceed 63 characters and IAM role names must not exceed 64 characters)"
)
```

The note text matches Requirement 1.8 character for character, and a test pins it.

## `get_name_length_warnings`

```python
def get_name_length_warnings(prefix, project_id, stage_id, parameters) -> List[str]:
```

Steps:

1. Build `lengths`, a dict of the values to consider. A value is considered only if its parameter is declared and the value is a `str`.
   - `'Prefix'` in `parameters` and `isinstance(prefix, str)`: `lengths['Prefix'] = len(prefix)`.
   - `'ProjectId'` in `parameters` and `isinstance(project_id, str)`: `lengths['ProjectId'] = len(project_id)`.
   - `'StageId'` in `parameters` and `isinstance(stage_id, str)` and `stage_id` not in `('', 'default')`: `lengths['StageId'] = len(stage_id)`.
   - `parameters` of `None` is treated as `{}`.
2. For each of `Prefix`, `ProjectId`, `StageId` in that order, if it is in `lengths` and over its limit, append `"<Name> is <n> characters (recommended maximum: <limit>)."` (1.5). A value at its limit adds nothing.
3. If `Prefix` and `ProjectId` are both in `lengths` and their sum is over 28, append `"Prefix+ProjectId is <n> characters (recommended maximum: 28)."` (1.6).
4. If all three are in `lengths` and their sum is over 32, append `"Prefix+ProjectId+StageId is <n> characters (recommended maximum: 32)."` (1.7).
5. If the list is not empty, append `NAME_LENGTH_WARNING_NOTE` (1.8). Otherwise return `[]` (1.9).

Design notes:

- The lines contain the parameter name and a number, never the value (1.5, D4). A value with escape sequences cannot reach the terminal or the log.
- Non-`str` values count as absent. The three parameters' `AllowedPattern` requires a leading letter, so a non-string cannot pass template validation anyway, and ignoring it keeps the function total for any input, including the `MagicMock` attributes some existing tests set on `ConfigManager`.
- The function reads no state and has no dependencies besides the constants, so it can be tested without mocks.
- No character or minimum-length rule appears here (1.10, D5). A `StageId` with dashes is measured by length only.

Docstring: Google style with Args, Returns, and a doctest-style Example, per `documentation-standards-python.md` (7.5).

```python
>>> get_name_length_warnings('acme', 'myapp', 'test', {'Prefix': {}, 'ProjectId': {}, 'StageId': {}})
[]
>>> get_name_length_warnings('acmecorp', 'myapp', 'dev', {'Prefix': {}, 'ProjectId': {}, 'StageId': {}})[0]
'Prefix is 8 characters (recommended maximum: 6).'
```

## `show_name_length_warnings`

```python
def show_name_length_warnings(warnings: List[str], headless: bool = False,
                              heading: str = NAME_LENGTH_HEADING) -> None:
```

`NAME_LENGTH_HEADING = "Prefix, ProjectId, and StageId exceed the recommended lengths:"` is a module constant. The second interactive check passes `heading=NAME_LENGTH_HEADING_FINAL` (`"The values you entered exceed the recommended lengths:"`) so the user can tell why the warning appears again. These two constants are a design addition; the requirements do not fix the heading text.

Behavior:

- Empty `warnings`: return without printing or logging (2.1).
- `headless=False` (interactive and skeleton, 2.2): print a blank line, `click.echo(Colorize.warning(heading))`, then `click.echo(Colorize.warning(f"  {line}"))` per line, then a blank line. This is the same `Colorize.warning` style used at `cli/config.py:767-787`. `Colorize.box_warning` is not used because `box_text` breaks lines on spaces only and does not handle a list of separate lines (`cli/lib/tools.py:432-437`).
- `headless=True` (2.3): `click.echo(f"Warning: {line}", err=True)` per line, no color, no heading, no blank lines. Standard output is unchanged (R1).
- Logging (2.1): `Log.warning(line)` per line, in every mode. `Log.warning` writes to the file only, so nothing prints twice. `ConsoleAndLog.warning` is not used for that reason.
- Failure isolation (2.5, R2): the printing block and each `Log.warning` call sit in their own `try/except Exception: pass`. `KeyboardInterrupt` is not caught. Silent swallowing is deliberate: the check is advisory, and the logger is the likely cause of a failure here, so logging the failure would repeat it.
- No prompts, no `sys.exit`, no return value (2.4).

## `warn_if_final_names_exceed`

```python
def warn_if_final_names_exceed(initial_names, parameter_values, parameters) -> bool:
```

- `initial_names` is the `(prefix, project_id, stage_id)` tuple used for the first check.
- Final values: `final_prefix = parameter_values.get('Prefix', initial_names[0])`, and the same for `ProjectId` and `StageId`. A parameter the template does not declare is absent from `parameter_values`, so it keeps its initial value and cannot cause a false difference.
- If `final_names == initial_names`, return `False` and print nothing (3.2).
- Otherwise call `show_name_length_warnings(get_name_length_warnings(*final_names, parameters), heading=NAME_LENGTH_HEADING_FINAL)` and return `True`. Warnings are printed only when the final values produce lines. The return value reports whether a second check ran, which the tests use.

The tuple is captured before `prompt_for_parameters` because the prompt loop overwrites `self.prefix`, `self.project_id`, and `self.stage_id` as the user answers (`cli/config.py:312-323`).

## Call sites

### Interactive `main()`

After `parameter_groups, parameters = config_manager.get_template_parameters(template_file)` (`:3156`):

```python
initial_names = (config_manager.prefix, config_manager.project_id, config_manager.stage_id)
show_name_length_warnings(get_name_length_warnings(*initial_names, parameters))
```

After `parameter_values = config_manager.prompt_for_parameters(...)` (`:3184`):

```python
warn_if_final_names_exceed(initial_names, parameter_values, parameters)
```

The first call is before the existing `print()` and the "Enter to accept default" line, so it follows the template version output from `get_template_parameters` and precedes the prompts (3.1). `prompt_for_stage_id` has already set `config_manager.stage_id` when no stage argument was given, so `config_manager.stage_id` is used, not `args.stage_id`. The check runs whether or not `local_config` exists. The extra blank line from the printer plus the existing `print()` gives two blank lines before the divider. This is accepted.

### `run_skeleton_mode`

After `get_template_parameters` (`:2808`) and before `generate_skeleton` (`:2812`):

```python
show_name_length_warnings(get_name_length_warnings(
    config_manager.prefix, config_manager.project_id, config_manager.stage_id, parameters))
```

`generate_skeleton` writes these same instance values into the skeleton (`:1282-1287`), so the argument values are the right ones to check (3.3).

### `run_headless_mode`

After `parameter_values` is extracted from the skeleton (`:2916-2923`), which is after the validation exit at `:2905-2911`:

```python
show_name_length_warnings(get_name_length_warnings(
    parameter_values.get('Prefix'), parameter_values.get('ProjectId'),
    parameter_values.get('StageId'), parameters), headless=True)
```

A value missing from `parameter_values` is `None` and counts as absent (3.5). A failed validation exits before this line, so no warning is printed in that case (3.4). `build_config_headless`, `save_config`, and the git steps follow unchanged.

## Error handling

| Situation | Behavior |
|-----------|----------|
| `parameters` is `None`, empty, or lacks a name | The value is not considered. No exception (1.3). |
| A value is `None`, empty, or not a string | Absent, or length 0 for `''`. No exception (1.2). |
| `stage_id` is `None`, `''`, or `'default'` | `StageId` is absent (1.4). |
| `click.echo` or `Log.warning` raises | Swallowed per call. The run continues (2.5). |
| `parameter_values` lacks `Prefix`, `ProjectId`, or `StageId` after prompts | Initial value is used. No false second warning. |

The check cannot cause a non-zero exit or add a prompt in any mode (2.4, 5.4).

## Logging

One `Log.warning` per warning line, including the note line, to the file logger already configured by `ScriptLogger.setup('config')` at import (`cli/config.py:44`). Nothing is logged when there are no lines. Values are never logged (D4).

## Testing strategy

New files in `tests/`, run under the existing pytest and Hypothesis setup (6.1). Baseline: 519 tests pass at `b189708` (6.11).

### `tests/test_name_length_warnings.py`

| Test group | Covers |
|------------|--------|
| Boundaries: Prefix 6/7, ProjectId 20/21, StageId 6/7, Prefix+ProjectId 28/29, total 32/33 | 6.2, 1.5 to 1.7 |
| Value over its limit while combined limits are not; only a combined limit over | 6.2 |
| Explanation line present exactly when another line is present; exact text pinned | 6.2, 1.8, 1.9 |
| Declared-parameter rules: `Prefix` only, `Prefix`+`ProjectId` with a stage argument, all three, empty `parameters`, `None`; `stage_id` of `None`, `''`, `'default'`; non-`str` values | 6.3, 1.3, 1.4 |
| No line contains the value, using a value with a newline and an ANSI escape; dashes and below-minimum values add no line | 6.4, 1.5, 1.10 |
| Property test (Hypothesis, 100+ examples): random lengths and random declared subset; oracle computed in the test from the constants; asserts no exception, each line present exactly when its condition holds, empty result exactly when nothing is over | 6.5 |
| `show_name_length_warnings`: styled output for interactive, `Warning: ` on stderr for headless (via `CliRunner` or `capsys`), `Log.warning` per line, nothing for `[]`, no output on stdout in headless | 2.1 to 2.3 |
| `show_name_length_warnings` with `click.echo` or `Log.warning` patched to raise: no exception | 6.9, 2.5 |
| No prompt function (`click.confirm`, `click.prompt`, `Colorize.prompt`) is called | 6.10, 2.4 |
| `warn_if_final_names_exceed`: unchanged values return `False` and print nothing; a changed value returns `True` and warns only when over a limit; a missing key keeps the initial value | 6.6, 3.2 |

### `tests/test_name_length_flow.py`

Follows `tests/test_skeleton_flow.py` and `tests/test_headless_flow.py`.

| Flow | Approach | Covers |
|------|----------|--------|
| Skeleton | Reuse the skeleton-flow mocks. Long `prefix` argument and a template declaring `Prefix`. Assert the warning is shown and the skeleton is written. | 6.7, 3.3 |
| Headless warns | Reuse the `run_headless_mode` patch stack from `test_headless_flow.py`. Skeleton file with a long `Prefix`. Assert `Warning: ` on stderr, stdout empty of warnings, `save_config` called, no `SystemExit`. | 6.8, 3.4, 5.4 |
| Headless validation failure | `validate_all_parameters` returns failures. Assert `SystemExit` as before and that `get_name_length_warnings` was not called. | 6.8, 3.4 |
| Headless missing `StageId` | Skeleton without `StageId`. Assert no exception. | 6.8, 3.5 |
| Interactive order | Patch `parse_args`, `ConfigManager` (class mock), `Git`, `FileNameListUtils`, `TagUtils`, `click.confirm`. Record call order with a shared `MagicMock` manager: `get_template_parameters`, then the first `show_name_length_warnings`, then `prompt_for_parameters`. | 6.6, 3.1 |
| Interactive second check | Same patch stack, `prompt_for_parameters` returns a changed `Prefix`. Assert a second call with `heading=NAME_LENGTH_HEADING_FINAL`. With unchanged values assert one call only. | 6.6, 3.2 |

The interactive tests patch `config.show_name_length_warnings` and `config.get_name_length_warnings` where they check call order, so the many other mocks in `main()` only need to let the flow reach the prompt and return.

### Existing tests

No existing test in `test_skeleton_flow.py` or `test_headless_flow.py` asserts on printed output (checked by search for `capsys`, `CliRunner`, and echo mocks). The skeleton and headless tests use dicts for `parameters` and short values, so no new output is printed there. If one test's mock produces a long `prefix` string, it prints a warning and still passes. The full suite is run after implementation to confirm 519 existing tests pass.

## Versioning, changelog, and docs

| Item | Change | Requirement |
|------|--------|-------------|
| `cli/config.py` `VERSION` | `v0.1.9/2026-07-24` to `v0.2.0/<implementation date>` (new behavior, no interface change); unchanged if the date already matches | 7.1 |
| `CHANGELOG.md` | New `## v0.0.22 (unreleased)` header above `## v0.0.21 (2026-11-15)`; `### Added` entry `**Script: config.py v0.2.0** - ...` linking this spec and #8 | 7.2 |
| `docs/SCRIPT-GUIDE.md`, `config.py` section | Short note: recommended lengths, advisory, all three modes | 7.3 |
| `EPILOG` in `cli/config.py` | One line under `Notes:` | 7.4 |
| Docstrings | Google style on the three functions; constants commented | 7.5 |
| `README.md`, `AGENTS-FOR-END-USE.md` | No change | 7.6 |

All changes stay in `cli/`, `docs/`, `tests/`, and `CHANGELOG.md`, so `update.py` delivers the user-facing files.

## Design decisions beyond the requirements

These refine the requirements. They can be vetoed before tasks are written.

| # | Decision | Why |
|---|----------|-----|
| G1 | Interactive and skeleton output uses `Colorize.warning` lines with a heading, not `Colorize.box_warning` | `box_text` does not handle separate lines (`cli/lib/tools.py:432-437`). `Colorize.warning` matches `config.py`'s other warnings. |
| G2 | The second interactive warning uses its own heading text | Explains why the warning appears again. |
| G3 | Non-`str` values are treated as absent | Keeps the function total. The three parameters cannot be non-strings after validation. |
| G4 | `warn_if_final_names_exceed` is a separate function and returns a `bool` | Makes requirement 3.2 testable without driving the whole prompt loop. |
| G5 | Failures in printing or logging are swallowed silently | The logger is the most likely cause, so logging the failure would repeat it. |

## Requirements traceability

| Requirement | Design section |
|-------------|----------------|
| 1.1 | Constants |
| 1.2 to 1.10 | `get_name_length_warnings` |
| 2.1 to 2.5 | `show_name_length_warnings`, Error handling, Logging |
| 3.1 | Call sites: interactive |
| 3.2 | `warn_if_final_names_exceed`, Call sites: interactive |
| 3.3 | Call sites: `run_skeleton_mode` |
| 3.4, 3.5 | Call sites: `run_headless_mode` |
| 4.1, 4.2 | Overview (no change to validation); `get_name_length_warnings` (no extra message) |
| 5.1 to 5.5 | Overview; Error handling; changes stay in `cli/config.py` |
| 6.1 to 6.11 | Testing strategy |
| 7.1 to 7.6 | Versioning, changelog, and docs |
| 8.1 to 8.4 | Manual verification by the maintainer, described in the requirements |
