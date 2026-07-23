# Implementation Plan

## Overview

Fix the `role_arn` precedence inversion in `cli/config.py`. The `ConfigManager` constructor only maps the infra-specific `*ServiceRoleArn` into `role_arn` when a generic `role_arn` is absent, so when both are present a storage/network stack inherits the generic (pipeline) role. The fix removes the constructor mutation, adds a single authoritative `resolve_role_arn()` helper (precedence: samconfig → infra-specific → generic fallback), and consolidates both the interactive (`build_config`) and headless (`generate_skeleton`) paths onto it. Tests extend `tests/test_config_role_arn.py`.

**Reminder: write the exploration test BEFORE implementing the fix, and run it on the UNFIXED code first to confirm the precedence inversion.**

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Infra-specific role ARN wins over generic role_arn
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the precedence inversion exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples showing resolution returns the generic `role_arn` instead of the infra-specific `*ServiceRoleArn`
  - **Scoped PBT Approach**: Use hypothesis to generate distinct valid role ARNs; for each infra_type in ['pipeline', 'storage', 'network'] build defaults containing BOTH a generic `role_arn` (differing from the infra-specific value) AND the matching `*ServiceRoleArn`, then assert resolution returns the infra-specific value (from Bug Condition `isBugCondition` in design)
  - Add tests to `tests/test_config_role_arn.py` following existing style (pytest + hypothesis, `_create_config_manager` mock helper, `role_arn_strategy`)
  - Target the authoritative resolution used by the interactive path. Since the fix introduces `ConfigManager.resolve_role_arn()`, assert on the resolved value for defaults where both keys are present with `samconfig_role_arn=None`
  - The assertion should match the Expected Behavior in design: `resolved == atlantis_defaults[infraSpecificKey(infra_type)]`
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k "both_present or bug_condition_precedence" -v`
  - **EXPECTED OUTCOME**: Test FAILS (storage/network resolve to the generic pipeline ARN instead of their own key)
  - Document counterexamples found (e.g., "storage with generic role_arn present resolved to ACME-Pipeline instead of ACME-Storage")
  - Mark task complete when the test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Fallback, samconfig precedence, service-role, and non-injection unchanged
  - **IMPORTANT**: Follow observation-first methodology — observe current correct behavior on UNFIXED code, then encode it
  - Observe: defaults with only a generic `role_arn` (no infra-specific key) resolve to the generic value on unfixed code
  - Observe: defaults with only the matching `*ServiceRoleArn` resolve to the infra-specific value on unfixed code
  - Observe: an existing samconfig `role_arn` takes precedence over defaults
  - Observe: `service-role` infra type falls through to the generic `role_arn`
  - Add preservation tests to `tests/test_config_role_arn.py` using hypothesis:
    - Generic-only defaults → resolved value equals the generic `role_arn` (from Preservation Requirement 3.1)
    - Infra-specific-only defaults → resolved value equals the infra-specific value (3.2)
    - samconfig `role_arn` present with differing defaults → resolved value equals the samconfig value (3.3)
    - `service-role` type with a generic `role_arn` → resolved value equals the generic value (3.4)
  - Run on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k "preservation" -v`
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - **NOTE**: These tests target the same resolution behavior the fix consolidates; where they reference `resolve_role_arn()`, keep them runnable by mirroring the current inline/constructor precedence until the helper exists, then point them at the helper in task 3
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix role_arn precedence and consolidate resolution in config.py

  - [x] 3.1 Implement the fix
    - Add `ConfigManager.resolve_role_arn(self, atlantis_defaults, samconfig_role_arn=None)` implementing precedence: non-empty `samconfig_role_arn` → infra-specific `*ServiceRoleArn` for `self.infra_type` → generic `role_arn` fallback → `''`. The helper MUST NOT mutate `atlantis_defaults` (Google-style docstring, snake_case)
    - Remove the constructor mutation block in `__init__` (~lines 126-133) that injects `self.defaults['atlantis']['role_arn']`
    - In the interactive path (`main()` where `atlantis_deploy_parameter_defaults` is assembled), seed the prompt default `role_arn` from `resolve_role_arn(defaults.get('atlantis', {}))` into a NEW dict (do not mutate `config_manager.defaults`), then keep the existing `local_config` update so an existing samconfig `role_arn` still wins
    - In `generate_skeleton()` (~lines 1200-1209), replace the inline `if 'role_arn' not in atlantis_deploy_params: ... elif ...` block with a call to `resolve_role_arn(atlantis_defaults, samconfig_role_arn=atlantis_deploy_params.get('role_arn'))`, assigning the result when non-empty (behavior-preserving for the headless path)
    - Leave `set_future_defaults()` unchanged (it already saves under the infra-specific key)
    - _Bug_Condition: isBugCondition(input) — infra_type in [pipeline, storage, network], both generic role_arn and matching *ServiceRoleArn present, no samconfig override, resolution yields the generic value_
    - _Expected_Behavior: expectedBehavior(result) — resolved role_arn equals the matching infra-specific *ServiceRoleArn; interactive and headless paths agree_
    - _Preservation: generic fallback, infra-specific-only, samconfig precedence, service-role fallthrough, and no injection into self.defaults all unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Infra-specific role ARN wins over generic role_arn
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior (infra-specific value wins when both keys are present)
    - Run: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k "both_present or bug_condition_precedence" -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms the precedence inversion is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Fallback, samconfig precedence, service-role, and non-injection unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests (repoint any that referenced inline logic to `resolve_role_arn()`)
    - Run: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k "preservation" -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions — fallback, samconfig precedence, and service-role behavior preserved; self.defaults not mutated)
    - Confirm all tests still pass after the fix

- [x] 4. Checkpoint - Ensure all tests pass
  - Run the role_arn suite: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -v`
  - Run the full suite to check for regressions: `source .ve/bin/activate && python -m pytest tests/ -v`
  - Pay attention to existing tests that inline-simulate the old constructor block (Property 3/4/5 in `tests/test_config_role_arn.py`); update or supersede them so they reflect the new `resolve_role_arn()` behavior rather than the removed mutation
  - Ensure all tests pass, ask the user if questions arise

- [x] 5. Update CHANGELOG.md
  - Add an entry under the `## v0.0.18 (unreleased)` section, in the existing `### Fixed` category (do not modify existing text)
  - Follow the changelog convention format, for example:
    - `- **Script: config.py** - Fixed \`role_arn\` precedence so infra-specific \`*ServiceRoleArn\` defaults override a generic \`role_arn\` fallback [Spec: 0-0-18-role_arn-further-fix](.kiro/specs/0-0-18-role_arn-further-fix/), addresses [#3](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/3)`
    - Sub-bullets: infra-specific key now wins over generic `role_arn` for pipeline/storage/network; generic `role_arn` is a read-only fallback and is no longer injected into defaults; interactive and headless paths consolidated onto a single `resolve_role_arn()` helper
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

## Notes

- Project uses a Python virtual environment at `.ve` — activate with `source .ve/bin/activate`
- Tests use pytest + hypothesis; reuse `_create_config_manager()` and `role_arn_strategy` from `tests/test_config_role_arn.py`
- Only `cli/*` and `docs/*` ship to end users; keep code changes within `cli/config.py` (and `tests/`)
- Python conventions: snake_case, Google-style docstrings, PascalCase for the infra-specific key names
- Write exploration tests BEFORE implementing the fix, and run on UNFIXED code first to confirm the bug
