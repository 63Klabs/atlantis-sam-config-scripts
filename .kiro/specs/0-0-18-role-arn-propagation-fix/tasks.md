# Implementation Plan

## Overview

Fix the `role_arn` propagation bug in `cli/config.py` where `role_arn` is added to `config['atlantis']['deploy']['parameters']` after `atlantis_default_deploy_parameters` has already been copied to per-deployment configs. The fix moves the conditional `role_arn` insertion into `atlantis_default_deploy_parameters` before copies are made.

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - role_arn missing from per-deployment parameters for pipeline/storage
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate role_arn is missing from deployment parameters
  - **Scoped PBT Approach**: Use hypothesis to generate valid role_arn strings and infra_type from ['pipeline', 'storage'], then assert role_arn propagates to all deployments
  - Create test file at `tests/test_config_role_arn.py`
  - Use pytest + hypothesis; the project virtual environment is at `.ve`
  - Mock ConfigManager using the pattern from `tests/test_build_config_headless.py` (patch `__init__`, set attributes manually)
  - Call `build_config_headless()` with infra_type in ['pipeline', 'storage'] and a valid `role_arn` in `atlantis_params`
  - Assert `'role_arn' in config['deployments'][stage_id]['deploy']['parameters']` for each deployment
  - Assert `config['deployments'][stage_id]['deploy']['parameters']['role_arn'] == atlantis_params['role_arn']`
  - Run test on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -v`
  - **EXPECTED OUTCOME**: Test FAILS (this confirms the bug — role_arn is in `config['atlantis']['deploy']['parameters']` but NOT in per-deployment parameters)
  - Document counterexamples found (e.g., "role_arn exists at top-level but config['deployments']['dev']['deploy']['parameters'] has no 'role_arn' key")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - network/service-role types must NOT have role_arn, and all standard parameters must remain intact
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `build_config_headless('network', ...)` returns config without `role_arn` in any parameters on unfixed code
  - Observe: `build_config_headless('service-role', ...)` returns config without `role_arn` in any parameters on unfixed code
  - Observe: All infra types include `template_file`, `s3_bucket`, `region`, `capabilities`, `confirm_changeset` in `atlantis_default_deploy_parameters`
  - Observe: Per-stage deployments include `stack_name`, `s3_prefix`, `parameter_overrides`, `tags`
  - Add preservation tests to `tests/test_config_role_arn.py` using hypothesis:
    - Generate random valid parameter sets with infra_type from ['network', 'service-role']
    - Assert `'role_arn' not in config['atlantis']['deploy']['parameters']`
    - Assert `'role_arn' not in config['deployments'][stage_id]['deploy']['parameters']`
    - Assert standard keys (`template_file`, `s3_bucket`, `region`, `capabilities`, `confirm_changeset`) are present in `config['atlantis']['deploy']['parameters']`
    - Assert per-stage keys (`stack_name`, `s3_prefix`, `parameter_overrides`, `tags`) are present in each deployment's `deploy.parameters`
  - Run tests on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k preservation -v`
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Fix role_arn propagation in config.py

  - [x] 3.1 Implement the fix
    - In `cli/config.py`, function `build_config_headless()`: add `role_arn` to `atlantis_default_deploy_parameters` dict immediately after it is built, conditionally when `infra_type in ['pipeline', 'storage']`:
      ```python
      if infra_type in ['pipeline', 'storage']:
          atlantis_default_deploy_parameters['role_arn'] = atlantis_params.get('role_arn', '')
      ```
    - Remove the redundant late addition block at the end of `build_config_headless()`:
      ```python
      # Remove this block:
      if infra_type in ['pipeline', 'storage']:
          config['atlantis']['deploy']['parameters']['role_arn'] = atlantis_params.get('role_arn', '')
      ```
    - In `cli/config.py`, function `build_config()`: apply the same pattern — add `role_arn` to `atlantis_default_deploy_parameters` right after it is built, and remove the late addition at the end of the function
    - _Bug_Condition: isBugCondition(input) where input.infra_type IN ['pipeline', 'storage'] AND role_arn NOT IN deployments[stage]['deploy']['parameters']_
    - _Expected_Behavior: role_arn present in every deployment's deploy.parameters with value matching atlantis_params['role_arn']_
    - _Preservation: network/service-role types must NOT gain role_arn; all other parameters unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - role_arn propagates to all deployments for pipeline/storage
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior (role_arn in each deployment's parameters)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k "bug_condition" -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed — role_arn now propagates to deployments)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - network/service-role behavior unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -k "preservation" -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions — network/service-role types still have no role_arn)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run the full test suite: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -v`
  - Verify all property-based tests pass (both bug condition and preservation)
  - Run existing tests to ensure no regressions: `source .ve/bin/activate && python -m pytest tests/ -v`
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- The project uses a Python virtual environment at `.ve` — activate with `source .ve/bin/activate`
- Tests use pytest + hypothesis for property-based testing
- `build_config_headless()` is the primary test target since it doesn't require interactive prompts
- Mock ConfigManager `__init__` to avoid AWS API calls (pattern in `tests/test_build_config_headless.py`)
- Write exploration tests BEFORE implementing the fix to confirm the bug exists
- Run tests on UNFIXED code first to understand the actual bug behavior

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "2"],
    ["3.1"],
    ["3.2", "3.3"],
    ["4"]
  ]
}
```
