# Role ARN Propagation Fix - Bugfix Design

## Overview

The `role_arn` parameter is required for pipeline and storage deployments but is not propagated to individual deployment environments. Both `build_config()` and `build_config_headless()` construct `atlantis_default_deploy_parameters` without `role_arn`, then add it only to `config['atlantis']['deploy']['parameters']` after the dict has already been copied to each deployment. This means per-environment `deployments[stage_id]['deploy']['parameters']` never receives `role_arn`, causing SAM deployments requiring an execution role to fail.

The fix moves the conditional `role_arn` insertion into `atlantis_default_deploy_parameters` before it is copied to deployments, and removes the redundant late addition.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — `infra_type in ['pipeline', 'storage']`, causing `role_arn` to be missing from per-deployment parameters
- **Property (P)**: The desired behavior — `role_arn` is present in every deployment's `deploy.parameters` when `infra_type` is pipeline or storage
- **Preservation**: For non-pipeline/non-storage infra types (network, service-role), `role_arn` must NOT appear in any parameters, and all other fields must remain unchanged
- **`build_config()`**: Interactive method in `cli/config.py` that builds the complete config dictionary with user prompts
- **`build_config_headless()`**: Non-interactive method in `cli/config.py` that builds config from pre-validated inputs
- **`atlantis_default_deploy_parameters`**: Dict containing deployment parameters (template_file, s3_bucket, region, capabilities, confirm_changeset) that gets propagated to all deployment environments
- **`gather_atlantis_deploy_parameters()`**: Interactive method that collects deploy params including `role_arn` for pipeline/storage types

## Bug Details

### Bug Condition

The bug manifests when `infra_type` is 'pipeline' or 'storage'. The `atlantis_default_deploy_parameters` dict is built without `role_arn`, then copied to each deployment's parameters. The `role_arn` is added to `config['atlantis']['deploy']['parameters']` only after this copy has already occurred, so it never reaches per-environment deployment configs.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ConfigBuildInput (infra_type, atlantis_params with role_arn)
  OUTPUT: boolean
  
  RETURN input.infra_type IN ['pipeline', 'storage']
         AND input.atlantis_params.role_arn IS NOT EMPTY
         AND role_arn NOT IN deployments[any_stage]['deploy']['parameters']
END FUNCTION
```

### Examples

- `build_config('pipeline', ...)` → `config['atlantis']['deploy']['parameters']` has `role_arn`, but `config['deployments']['dev']['deploy']['parameters']` does NOT have `role_arn`
- `build_config_headless('storage', ..., atlantis_params={'role_arn': 'arn:aws:iam::123:role/my-role', ...})` → same issue: top-level has `role_arn`, deployments do not
- `build_config('pipeline', ...)` with multiple deployments, user selects "apply to all" → `atlantis_default_deploy_parameters` (missing `role_arn`) is applied to all deployments, then `role_arn` is added only to the top-level config
- `build_config('network', ...)` → correctly has no `role_arn` anywhere (not a bug case)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- For `infra_type` in ['network', 'service-role'], `role_arn` must NOT appear in `atlantis_default_deploy_parameters` or any deployment parameters
- `template_file`, `s3_bucket`, `region`, `capabilities`, and `confirm_changeset` must continue to be present in `atlantis_default_deploy_parameters` for all infra types
- `stack_name`, `s3_prefix`, `parameter_overrides`, and `tags` must continue to be added to per-stage deployment parameters
- When multiple deployments exist and user chooses NOT to apply to all, only the current stage is updated
- The `role_arn` value in `config['atlantis']['deploy']['parameters']` must match the value in each deployment's `deploy.parameters`

**Scope:**
All inputs where `infra_type` is NOT in ['pipeline', 'storage'] should be completely unaffected by this fix. This includes:
- Network infrastructure configs (`infra_type='network'`)
- Service role configs (`infra_type='service-role'`)
- Any other non-pipeline/non-storage type

## Hypothesized Root Cause

Based on the code analysis, the root cause is confirmed:

1. **Late addition pattern in `build_config()`**: Lines build `atlantis_default_deploy_parameters` as a dict with 5 keys (template_file, s3_bucket, region, capabilities, confirm_changeset). This dict is then copied via `.copy()` to `deployment_parameters` and used in the multi-deployment update loop. Only after all deployments are built does the code add `role_arn` to `config['atlantis']['deploy']['parameters']` — which is the same reference as `atlantis_default_deploy_parameters` at that point, but by then all copies have already been made without it.

2. **Same pattern in `build_config_headless()`**: Identical structure — `atlantis_default_deploy_parameters` is built without `role_arn`, copied to `deployment_parameters`, placed in the config, and then `role_arn` is added to `config['atlantis']['deploy']['parameters']` after the fact.

3. **The fix is straightforward**: Add `role_arn` to `atlantis_default_deploy_parameters` conditionally (when `infra_type in ['pipeline', 'storage']`) immediately after building the dict, before any copies are made. Then remove the late addition at the end of each function.

## Correctness Properties

Property 1: Bug Condition - role_arn propagates to all deployments for pipeline/storage

_For any_ input where `infra_type` is 'pipeline' or 'storage' and a valid `role_arn` is provided, the fixed `build_config()` and `build_config_headless()` functions SHALL include `role_arn` in every deployment's `deploy.parameters`, and the value SHALL match `config['atlantis']['deploy']['parameters']['role_arn']`.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - role_arn absent for network/service-role types

_For any_ input where `infra_type` is 'network' or 'service-role', the fixed functions SHALL NOT include `role_arn` in `atlantis_default_deploy_parameters` or in any deployment's `deploy.parameters`, and all other parameters (template_file, s3_bucket, region, capabilities, confirm_changeset, stack_name, s3_prefix, parameter_overrides, tags) SHALL remain unchanged.

**Validates: Requirements 3.1, 3.2, 3.3**

## Fix Implementation

### Changes Required

**File**: `cli/config.py`

**Function**: `build_config()`

**Specific Changes**:
1. **Add `role_arn` to `atlantis_default_deploy_parameters`**: After building the dict (with template_file, s3_bucket, region, capabilities, confirm_changeset), conditionally add `role_arn` when `infra_type in ['pipeline', 'storage']`:
   ```python
   # Add role_arn for pipeline/storage deployments so it propagates to all environments
   if infra_type in ['pipeline', 'storage']:
       atlantis_default_deploy_parameters['role_arn'] = atlantis_deploy_params['role_arn']
   ```

2. **Remove redundant late addition**: Delete the block at the end:
   ```python
   # Remove this:
   if infra_type in ['pipeline', 'storage']:
       config['atlantis']['deploy']['parameters']['role_arn'] = atlantis_deploy_params['role_arn']
   ```

**Function**: `build_config_headless()`

**Specific Changes**:
3. **Add `role_arn` to `atlantis_default_deploy_parameters`**: Same pattern — after building the dict, conditionally add `role_arn`:
   ```python
   # Add role_arn for pipeline/storage deployments so it propagates to all environments
   if infra_type in ['pipeline', 'storage']:
       atlantis_default_deploy_parameters['role_arn'] = atlantis_params.get('role_arn', '')
   ```

4. **Remove redundant late addition**: Delete the block at the end:
   ```python
   # Remove this:
   if infra_type in ['pipeline', 'storage']:
       config['atlantis']['deploy']['parameters']['role_arn'] = atlantis_params.get('role_arn', '')
   ```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code (role_arn missing from deployment parameters), then verify the fix works correctly and preserves existing behavior.

Test file: `tests/test_config_role_arn.py`
Framework: pytest with hypothesis for property-based testing

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate `role_arn` is missing from per-deployment parameters BEFORE implementing the fix.

**Test Plan**: Call `build_config_headless()` with pipeline/storage infra types and valid role_arn values, then assert role_arn is present in each deployment's `deploy.parameters`. Run on UNFIXED code to observe failures.

**Test Cases**:
1. **Pipeline deployment**: Call `build_config_headless('pipeline', ...)` with role_arn, check deployments have role_arn (will fail on unfixed code)
2. **Storage deployment**: Call `build_config_headless('storage', ...)` with role_arn, check deployments have role_arn (will fail on unfixed code)
3. **Value consistency**: Assert role_arn value in deployments matches `config['atlantis']['deploy']['parameters']['role_arn']` (will fail on unfixed code)

**Expected Counterexamples**:
- `config['deployments']['dev']['deploy']['parameters']` does not contain key `role_arn`
- role_arn exists at `config['atlantis']['deploy']['parameters']['role_arn']` but not in any deployment

### Fix Checking

**Goal**: Verify that for all inputs where infra_type is pipeline/storage and a valid role_arn is provided, every deployment's `deploy.parameters` contains `role_arn` with the correct value.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  config := build_config_headless(input.infra_type, input.template, input.atlantis_params, ...)
  FOR EACH deployment IN config['deployments'] DO
    ASSERT 'role_arn' IN deployment['deploy']['parameters']
    ASSERT deployment['deploy']['parameters']['role_arn'] = config['atlantis']['deploy']['parameters']['role_arn']
  END FOR
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where infra_type is NOT pipeline/storage, role_arn does NOT appear in any parameters, and all other fields remain correct.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  config := build_config_headless(input.infra_type, input.template, input.atlantis_params, ...)
  ASSERT 'role_arn' NOT IN config['atlantis']['deploy']['parameters']
  FOR EACH deployment IN config['deployments'] DO
    ASSERT 'role_arn' NOT IN deployment['deploy']['parameters']
    ASSERT 'template_file' IN deployment['deploy']['parameters']
    ASSERT 's3_bucket' IN deployment['deploy']['parameters']
    ASSERT 'region' IN deployment['deploy']['parameters']
    ASSERT 'capabilities' IN deployment['deploy']['parameters']
    ASSERT 'confirm_changeset' IN deployment['deploy']['parameters']
    ASSERT 'stack_name' IN deployment['deploy']['parameters']
    ASSERT 'parameter_overrides' IN deployment['deploy']['parameters']
    ASSERT 'tags' IN deployment['deploy']['parameters']
  END FOR
END FOR
```

**Testing Approach**: Property-based testing with hypothesis is recommended because:
- It generates many combinations of infra_type, role_arn values, and parameter configurations
- It catches edge cases with empty strings, special characters in ARNs
- It provides strong guarantees that behavior is unchanged for network/service-role types

### Unit Tests

- Test `build_config_headless('pipeline', ...)` includes role_arn in deployment parameters
- Test `build_config_headless('storage', ...)` includes role_arn in deployment parameters
- Test `build_config_headless('network', ...)` does NOT include role_arn anywhere
- Test `build_config_headless('service-role', ...)` does NOT include role_arn anywhere
- Test role_arn value consistency between atlantis params and deployment params

### Property-Based Tests

- Generate random valid role_arn values with pipeline/storage infra types, verify propagation to all deployments
- Generate random configs with network/service-role infra types, verify role_arn is absent
- Generate random parameter sets and verify all non-role_arn fields remain unchanged across both infra type categories

### Integration Tests

- Test end-to-end config build with multiple existing deployments and "apply to all" for pipeline type
- Test that saved config TOML file contains role_arn in each deployment section for pipeline/storage
- Test that deploy command can read role_arn from per-deployment parameters
