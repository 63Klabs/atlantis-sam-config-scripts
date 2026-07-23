# role_arn Further Fix - Bugfix Design

## Overview

`role_arn` (the active SAM deploy parameter written into `samconfig` `deploy.parameters`) must be resolved from the infra-type-specific persisted default key for the stack's infra type — `PipelineServiceRoleArn`, `StorageServiceRoleArn`, or `NetworkServiceRoleArn` — with a generic `role_arn` default acting only as a fallback.

The `ConfigManager` constructor (`cli/config.py` ~lines 126-133) inverts this precedence: it only maps the infra-specific `*ServiceRoleArn` into `role_arn` when a generic `role_arn` is absent from defaults. When a defaults file contains both a generic `role_arn` and the infra-specific keys, the infra-specific override is skipped, so `storage` and `network` deployments inherit the generic (typically pipeline) role. The constructor also mutates `self.defaults['atlantis']['role_arn']`, programmatically injecting a key the maintainer wants to remain file-sourced only.

There are two divergent resolution locations:

- **Constructor** (`__init__`, ~lines 126-133): inverted precedence, mutates `self.defaults`. This value flows into the **interactive** path — `main()` reads `config_manager.defaults` and passes it to `build_config()` → `gather_atlantis_deploy_parameters()`, which uses `atlantis_deploy_parameter_defaults.get('role_arn', ...)` as the prompt default.
- **`generate_skeleton()`** (~lines 1200-1209): **correct** precedence (infra-specific first, generic last) and loads its own fresh defaults via a new `DefaultsLoader`, so it is not contaminated by the constructor mutation. This feeds the **headless** path (skeleton → `atlantis_params` → `build_config_headless()`).

> **Note:** The planning document (SPEC.md) referred to this second block as `build_samconfig`. The actual function is `generate_skeleton()`; there is no `build_samconfig` in `cli/config.py`. The design reflects the real code.

The fix removes the constructor's inverted-precedence mutation and introduces a single authoritative resolution helper used by both paths, so the interactive and headless paths produce identical results and generic `role_arn` is treated strictly as a fallback that is only ever read from a defaults file.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — `infra_type` is pipeline/storage/network, the defaults contain both a non-empty generic `role_arn` and the matching non-empty infra-specific `*ServiceRoleArn`, no existing samconfig `role_arn` overrides, and resolution yields the generic value instead of the infra-specific one.
- **Property (P)**: The desired behavior — `role_arn` resolves to the matching infra-specific `*ServiceRoleArn` when it is present and non-empty.
- **Preservation**: For non-bug inputs (generic-only defaults, infra-specific-only defaults, existing samconfig value present, `service-role` type), resolution and all other config output remain unchanged.
- **`role_arn`**: Active SAM deploy parameter consumed by SAM at deploy time, stored in `samconfig` `deploy.parameters`.
- **`{Pipeline|Storage|Network}ServiceRoleArn`**: Persisted, per-infra-type default keys in a defaults file that hold a distinct service role ARN for each infrastructure type.
- **Infra-specific key**: The `*ServiceRoleArn` key that corresponds to a given `infra_type` (pipeline → `PipelineServiceRoleArn`, storage → `StorageServiceRoleArn`, network → `NetworkServiceRoleArn`). `service-role` has no infra-specific key.
- **`__init__` (constructor)**: `ConfigManager.__init__` in `cli/config.py`; currently mutates `self.defaults['atlantis']['role_arn']`.
- **`gather_atlantis_deploy_parameters()`**: Interactive method that prompts for deploy params; uses the defaults dict `role_arn` as the prompt default value.
- **`build_config()` / `build_config_headless()`**: Methods that assemble the full config dictionary for the interactive and headless paths respectively.
- **`generate_skeleton()`**: Method that builds the headless skeleton; already resolves `role_arn` with correct precedence from a freshly loaded defaults dict.
- **`set_future_defaults()`**: Method that persists a deploy `role_arn` back into a defaults file under the infra-specific key.

## Bug Details

### Bug Condition

The bug manifests when a defaults file contains both a generic `role_arn` and the matching infra-specific `*ServiceRoleArn` for a pipeline/storage/network stack, and no existing samconfig `role_arn` is present to override. The constructor's guard `if 'role_arn' not in self.defaults['atlantis']` evaluates False, so the infra-specific override is skipped and the generic value wins on the interactive path.

**Formal Specification:**
```
FUNCTION infraSpecificKey(infra_type)
  RETURN CASE infra_type OF
    'pipeline' -> 'PipelineServiceRoleArn'
    'storage'  -> 'StorageServiceRoleArn'
    'network'  -> 'NetworkServiceRoleArn'
    OTHERWISE  -> NONE
  END CASE
END FUNCTION

FUNCTION isBugCondition(input)
  INPUT: input = (infra_type, atlantis_defaults, samconfig_role_arn)
  OUTPUT: boolean

  key := infraSpecificKey(input.infra_type)

  RETURN input.infra_type IN ['pipeline', 'storage', 'network']
     AND key != NONE
     AND nonEmpty(input.atlantis_defaults[key])
     AND nonEmpty(input.atlantis_defaults['role_arn'])
     AND isEmpty(input.samconfig_role_arn)
     AND resolvedRoleArn_current(input) != input.atlantis_defaults[key]
END FUNCTION
```

Where `resolvedRoleArn_current` is the value the current (unfixed) interactive path produces — the generic `role_arn` — instead of the infra-specific value.

**Expected behavior for bug-condition inputs:**
```
FUNCTION expectedBehavior(result, input)
  key := infraSpecificKey(input.infra_type)
  RETURN result == input.atlantis_defaults[key]
END FUNCTION
```

### Examples

Given a defaults file:
```json
{
  "atlantis": {
    "PipelineServiceRoleArn": "arn:aws:iam::123456789012:role/service_role/ACME-Pipeline",
    "StorageServiceRoleArn": "arn:aws:iam::123456789012:role/service_role/ACME-Storage",
    "NetworkServiceRoleArn": "arn:aws:iam::123456789012:role/service_role/ACME-Network",
    "role_arn": "arn:aws:iam::123456789012:role/service_role/ACME-Pipeline"
  }
}
```

- `config.py storage acme myapp` (interactive) → resolves `role_arn` to the generic `ACME-Pipeline` value; expected `ACME-Storage`. **(bug)**
- `config.py network acme myapp test` (interactive) → resolves `role_arn` to `ACME-Pipeline`; expected `ACME-Network`. **(bug)**
- `config.py pipeline acme myapp test` (interactive) → resolves `role_arn` to the generic value; expected `ACME-Pipeline`. Correct only because the two are equal here. **(latent bug)**
- Same defaults, headless skeleton generation for storage → already resolves to `ACME-Storage` (correct); the fix must preserve this.
- Defaults with only `role_arn` and no `*ServiceRoleArn` for storage → resolves to generic `role_arn` (correct fallback; not a bug case).

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Generic `role_arn` fallback: when no matching infra-specific key is present, the generic `role_arn` is still used.
- Infra-specific-only defaults: when only the matching `*ServiceRoleArn` exists, it is still resolved (this already worked).
- Existing samconfig `role_arn` remains highest precedence.
- `service-role` infra type still falls through to the generic `role_arn`; no infra-specific handling is added.
- Resolved `role_arn` still propagates to every deployment's `deploy.parameters` and to the `atlantis` section for pipeline/storage/network (behavior from prior v0.0.18 fixes).
- `set_future_defaults()` still persists a deploy `role_arn` under the infra-specific key.
- Headless (`generate_skeleton`) output is unchanged for every case it already resolved correctly.
- When no `role_arn` is available anywhere, interactive mode still prompts and headless mode still yields an empty value.

**Scope:**
All inputs where the bug condition does NOT hold are unaffected. This includes:
- Defaults with a generic `role_arn` but no matching infra-specific key.
- Defaults with only the matching infra-specific key.
- Any config where an existing samconfig `role_arn` is present.
- `service-role` infra type.

## Hypothesized Root Cause

Based on code analysis, the root cause is confirmed:

1. **Inverted precedence guard in the constructor**: `if 'role_arn' not in self.defaults['atlantis']` gates the infra-specific mapping so it only runs when the generic key is absent. When both are present, the infra-specific value is ignored. This is the primary defect.

2. **Programmatic mutation of `self.defaults`**: The constructor writes the resolved value back into `self.defaults['atlantis']['role_arn']`. Per the maintainer decision, generic `role_arn` must only ever be read from a defaults file, never injected. The mutation also makes the interactive path depend on constructor state rather than an explicit resolution at the point of use.

3. **Two divergent resolution paths**: The constructor (interactive path) and `generate_skeleton()` (headless path) implement resolution independently. `generate_skeleton()` is correct and reads a fresh defaults dict, so the headless path already behaves correctly; the interactive path does not. This divergence is the reconciliation target.

4. **No true contamination between paths**: Because `generate_skeleton()` loads its own defaults via a new `DefaultsLoader`, the constructor's mutation of `self.defaults` does not leak into the headless path. The observable defect is confined to the interactive path, but the two paths must still be consolidated onto one authoritative precedence to guarantee consistency going forward.

## Correctness Properties

Property 1: Bug Condition - Infra-specific role ARN wins over generic role_arn

_For any_ input where the bug condition holds (isBugCondition returns true) — that is, `infra_type` is pipeline/storage/network, both a non-empty generic `role_arn` and the matching non-empty infra-specific `*ServiceRoleArn` are present in defaults, and no existing samconfig `role_arn` overrides — the fixed resolution SHALL return the matching infra-specific `*ServiceRoleArn` value, and the interactive and headless paths SHALL return the same value.

**Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6**

Property 2: Preservation - Fallback, samconfig precedence, and non-injection unchanged

_For any_ input where the bug condition does NOT hold (isBugCondition returns false) — generic-only defaults, infra-specific-only defaults, an existing samconfig `role_arn`, or `service-role` type — the fixed resolution SHALL produce the same result as the original correct behavior: generic `role_arn` used only as a fallback, infra-specific value used when it is the only one present, existing samconfig value taking highest precedence, and `service-role` falling through to the generic value. In addition, the fixed code SHALL NOT inject `role_arn` into `self.defaults`.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 2.4**

## Fix Implementation

### Changes Required

**File**: `cli/config.py`

**1. New authoritative resolution helper**

Add a single method that both paths call. It implements the maintainer-confirmed precedence and never mutates its inputs:

```python
def resolve_role_arn(self, atlantis_defaults, samconfig_role_arn=None):
    """Resolve the deploy role_arn using authoritative precedence.

    Precedence (highest to lowest):
        1. An existing samconfig role_arn (samconfig_role_arn), if non-empty.
        2. The infra-specific service role ARN for self.infra_type
           (PipelineServiceRoleArn / StorageServiceRoleArn / NetworkServiceRoleArn).
        3. The generic role_arn from defaults (fallback only).

    Args:
        atlantis_defaults (dict): The 'atlantis' section of the loaded defaults.
        samconfig_role_arn (str, optional): role_arn already present in an existing
            samconfig. Defaults to None.

    Returns:
        str: The resolved role ARN, or '' if none is available.
    """
    if samconfig_role_arn:
        return samconfig_role_arn

    infra_key = {
        'pipeline': 'PipelineServiceRoleArn',
        'storage': 'StorageServiceRoleArn',
        'network': 'NetworkServiceRoleArn',
    }.get(self.infra_type)

    if infra_key and atlantis_defaults.get(infra_key):
        return atlantis_defaults[infra_key]

    return atlantis_defaults.get('role_arn', '')
```

**2. Remove the constructor mutation block** (`__init__`, ~lines 126-133)

Delete the entire block that injects `role_arn` into `self.defaults['atlantis']`. The constructor no longer mutates defaults.

**3. Interactive path — resolve at point of use** (`main()` / `build_config()`)

Where `atlantis_deploy_parameter_defaults` is assembled in `main()` (before it is passed to `build_config()` and then to `gather_atlantis_deploy_parameters()`), seed the `role_arn` default from the helper so the prompt default reflects correct precedence, while still allowing an existing samconfig value to take precedence:

```python
atlantis_deploy_parameter_defaults = defaults.get('atlantis', {})
# Resolve role_arn with correct precedence for the prompt default (fallback aware),
# without mutating the loaded defaults.
resolved_role_arn = config_manager.resolve_role_arn(defaults.get('atlantis', {}))
if resolved_role_arn:
    atlantis_deploy_parameter_defaults = {**atlantis_deploy_parameter_defaults,
                                          'role_arn': resolved_role_arn}
if local_config:
    atlantis_deploy_parameter_defaults.update(
        local_config.get('atlantis', {}).get('deploy', {}).get('parameters', {})
    )
```

The subsequent `local_config` update preserves an existing samconfig `role_arn` as highest precedence (requirement 3.3). Using a new dict avoids mutating `config_manager.defaults`.

**4. Headless path — consolidate onto the helper** (`generate_skeleton()`, ~lines 1200-1209)

Replace the inline `if 'role_arn' not in atlantis_deploy_params: ... elif ...` block with a call to `resolve_role_arn()`, passing any samconfig-sourced value as the override so behavior is identical to today:

```python
resolved = self.resolve_role_arn(
    atlantis_defaults,
    samconfig_role_arn=atlantis_deploy_params.get('role_arn')
)
if resolved:
    atlantis_deploy_params['role_arn'] = resolved
```

This preserves the existing correct precedence (samconfig → infra-specific → generic) while eliminating the duplicated logic.

**5. Leave `set_future_defaults()` unchanged**

Its mapping of `role_arn` → infra-specific key on save is correct and out of scope for this fix (requirement 3.6).

### Consolidation Assessment

Consolidation is feasible and low-risk: both resolution sites are internal to `ConfigManager`, and `resolve_role_arn()` reproduces the precedence `generate_skeleton()` already uses (so the headless path is behavior-preserving) while correcting the interactive path. No other scripts or callers read the constructor-injected `self.defaults['atlantis']['role_arn']`, so removing the mutation does not affect `deploy.py`, `delete.py`, `import.py`, or `update.py`. `service-role` maps to no infra-specific key and therefore falls through to the generic `role_arn`, matching requirement 3.4.

## Testing Strategy

### Validation Approach

The strategy is two-phase: first surface counterexamples that demonstrate the precedence inversion on the unfixed interactive path, then verify the fix resolves the infra-specific key and preserves all fallback and non-bug behavior. Tests extend `tests/test_config_role_arn.py` and follow its existing style (pytest + hypothesis, `_create_config_manager` mock helper).

Test file: `tests/test_config_role_arn.py`
Framework: pytest with hypothesis for property-based testing
Environment: project virtual environment at `.ve`

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples proving that when both a generic `role_arn` and the matching infra-specific key are present, resolution returns the generic value instead of the infra-specific one — BEFORE implementing the fix.

**Test Plan**: Drive the resolution used by the interactive path with defaults containing both keys, for each of pipeline, storage, and network, and assert the resolved `role_arn` equals the infra-specific `*ServiceRoleArn`. Because the fix introduces `resolve_role_arn()`, the exploration test targets the authoritative resolution behavior; on unfixed code the equivalent inline/constructor logic returns the generic value, so the assertion fails.

**Test Cases**:
1. **Storage both-present**: defaults have generic `role_arn` (= pipeline ARN) and a differing `StorageServiceRoleArn`; assert resolution returns `StorageServiceRoleArn` (fails on unfixed code).
2. **Network both-present**: defaults have generic `role_arn` and a differing `NetworkServiceRoleArn`; assert resolution returns `NetworkServiceRoleArn` (fails on unfixed code).
3. **Pipeline both-present (differing)**: defaults have a generic `role_arn` that differs from `PipelineServiceRoleArn`; assert resolution returns `PipelineServiceRoleArn` (fails on unfixed code).

**Expected Counterexamples**:
- Storage/network resolution returns the generic (pipeline) ARN rather than the infra-specific ARN.
- Root cause: the `if 'role_arn' not in ...` guard skips the infra-specific override when the generic key is present.

### Fix Checking

**Goal**: Verify that for all bug-condition inputs, resolution returns the matching infra-specific value.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := resolve_role_arn(input.atlantis_defaults, samconfig_role_arn=None)
  ASSERT result == input.atlantis_defaults[infraSpecificKey(input.infra_type)]
END FOR
```

### Preservation Checking

**Goal**: Verify that for all non-bug-condition inputs, resolution and config output match the original correct behavior.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT resolve_role_arn_fixed(input) == resolve_role_arn_expected(input)
END FOR
```

Concretely:
- Generic-only defaults → resolves to generic `role_arn`.
- Infra-specific-only defaults → resolves to the infra-specific value.
- samconfig `role_arn` present → resolves to the samconfig value regardless of defaults.
- `service-role` type → resolves to the generic `role_arn` (or empty if absent).
- `self.defaults` is not mutated by resolution (no injected `role_arn` key).

**Testing Approach**: Property-based testing with hypothesis is recommended because it generates many ARN values and key combinations, catches edge cases (empty strings, differing-but-valid ARNs), and provides strong guarantees that fallback and samconfig precedence are unchanged.

**Test Plan**: Observe current behavior on unfixed code for generic-only, infra-specific-only, and `service-role` inputs (all already correct), then write property-based tests that assert those same outcomes hold after the fix. Add an assertion that `self.defaults` gains no `role_arn` key after resolution.

**Test Cases**:
1. **Generic fallback**: only `role_arn` present, no infra-specific key → resolves to generic (unchanged).
2. **Infra-specific only**: only `*ServiceRoleArn` present → resolves to infra-specific (unchanged).
3. **samconfig precedence**: samconfig `role_arn` present with differing defaults → resolves to samconfig value.
4. **service-role fallthrough**: `service-role` type with a generic `role_arn` → resolves to generic; existing `service-role` config output (no infra-specific handling) unchanged.
5. **No injection**: after resolution, `self.defaults['atlantis']` contains no programmatically added `role_arn` key.

### Unit Tests

- `resolve_role_arn()` returns infra-specific value when both keys present (pipeline, storage, network).
- `resolve_role_arn()` returns generic value when only generic present.
- `resolve_role_arn()` returns samconfig value when provided as override.
- `resolve_role_arn()` returns `''` when nothing is available.
- Constructor no longer adds a `role_arn` key to `self.defaults` when only infra-specific keys are present.

### Property-Based Tests

- Generate three distinct valid ARNs for the infra-specific keys plus a generic `role_arn`; for each infra type assert resolution returns its own infra-specific ARN (no cross-contamination, generic never wins).
- Generate generic-only and infra-specific-only defaults; assert fallback and infra-specific resolution respectively.
- Generate a samconfig `role_arn` with arbitrary differing defaults; assert samconfig value always wins.

### Integration Tests

- Interactive `build_config()` for storage/network with both-present defaults yields a samconfig whose `role_arn` (in the atlantis section and every deployment) equals the infra-specific value.
- Headless `generate_skeleton()` + `build_config_headless()` for the same defaults yields the same resolved `role_arn` as the interactive path (consistency between paths).
- `service-role` config build is unchanged end to end.
