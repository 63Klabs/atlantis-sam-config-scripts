# SPEC: role_arn Further Fix

Planning scratchpad for GitHub issue [#3](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/3).
This document is for investigation and planning only — it is not a formal requirements/design/tasks spec yet.

## Issue Summary (as reported)

Issue #3 asks: *What is the difference between `atlantis.role_arn` and `atlantis.PipelineServiceRoleArn` (and the Storage/Network variants)?* Given a defaults file like:

```json
{
  "atlantis": {
    "PipelineServiceRoleArn": "arn:aws:iam::123456789012:role/service_role/ACME-CloudFormation-Service-Role-Pipeline-Management",
    "StorageServiceRoleArn": "arn:aws:iam::123456789012:role/service_role/ACME-CloudFormation-Service-Role-Storage-Management",
    "NetworkServiceRoleArn": "arn:aws:iam::123456789012:role/service_role/ACME-CloudFormation-Service-Role-Network-CloudFront-Mgmt",
    "role_arn": "arn:aws:iam::123456789012:role/service_role/ACME-CloudFormation-Service-Role-Pipeline-Management"
  }
}
```

Does `config.py` use these correctly? The reporter expects: **depending on the infra type of the stack, `role_arn` should be set to the corresponding `ServiceRoleArn`.**

## How the two concepts are meant to relate

- `PipelineServiceRoleArn` / `StorageServiceRoleArn` / `NetworkServiceRoleArn` are **persisted, per-infra-type defaults**. They let a user store a distinct service role ARN for each infrastructure type in their defaults files.
- `role_arn` is the **active SAM deploy parameter** that gets written into `samconfig` under `deploy.parameters`. It is the key SAM actually consumes at deploy time.
- Intended behavior: when configuring a stack of a given infra type, `role_arn` should be **derived from the matching `*ServiceRoleArn`** for that infra type.

## Investigation Findings

### Confirmed defect — constructor guard (`cli/config.py` ~lines 126-133)

```python
# if role_arn is not in self.defaults, then check for StorageServiceRole
if 'role_arn' not in self.defaults['atlantis']:
    if self.infra_type == 'storage' and 'StorageServiceRoleArn' in self.defaults['atlantis']:
        self.defaults['atlantis']['role_arn'] = self.defaults['atlantis']['StorageServiceRoleArn']
    elif self.infra_type == 'pipeline' and 'PipelineServiceRoleArn' in self.defaults['atlantis']:
        self.defaults['atlantis']['role_arn'] = self.defaults['atlantis']['PipelineServiceRoleArn']
    elif self.infra_type == 'network' and 'NetworkServiceRoleArn' in self.defaults['atlantis']:
        self.defaults['atlantis']['role_arn'] = self.defaults['atlantis']['NetworkServiceRoleArn']
```

The per-infra-type mapping is **only applied when `role_arn` is absent** from defaults. In the exact scenario from the issue — where defaults contain a generic `role_arn` (equal to the Pipeline ARN) **alongside** all three `*ServiceRoleArn` keys — the `if 'role_arn' not in ...` guard is `False`, so the infra-specific override never runs.

**Result:** A `storage` or `network` deployment incorrectly inherits the generic `role_arn` (the Pipeline role) instead of `StorageServiceRoleArn` / `NetworkServiceRoleArn`. This matches the reporter's suspicion.

### Expected precedence (proposed)

For a given `infra_type`, resolution of `role_arn` from defaults should be:

1. Infra-specific key (`{Pipeline|Storage|Network}ServiceRoleArn`) when present and non-empty — **highest precedence**
2. Generic `role_arn` — fallback only when no infra-specific key applies

The current code has the precedence inverted (generic `role_arn` wins).

### Second location to verify — `build_samconfig` (`cli/config.py` ~lines 1200-1209)

```python
if 'role_arn' not in atlantis_deploy_params:
    if self.infra_type == 'storage' and atlantis_defaults.get('StorageServiceRoleArn'):
        atlantis_deploy_params['role_arn'] = atlantis_defaults['StorageServiceRoleArn']
    elif self.infra_type == 'pipeline' and atlantis_defaults.get('PipelineServiceRoleArn'):
        atlantis_deploy_params['role_arn'] = atlantis_defaults['PipelineServiceRoleArn']
    elif self.infra_type == 'network' and atlantis_defaults.get('NetworkServiceRoleArn'):
        atlantis_deploy_params['role_arn'] = atlantis_defaults['NetworkServiceRoleArn']
    elif atlantis_defaults.get('role_arn'):
        atlantis_deploy_params['role_arn'] = atlantis_defaults['role_arn']
```

This block has the *correct* precedence (infra-specific first, generic `role_arn` last). However, because the constructor mutates `self.defaults['atlantis']['role_arn']`, the effective value flowing in here may already be contaminated by the generic value depending on how `atlantis_defaults` and `atlantis_deploy_params` are sourced. **Needs verification during design** to ensure the two locations are consistent and one authoritative resolution path is used.

### Relationship to prior v0.0.18 work

- `0-0-18-network-role-arn-support` — added network `role_arn` support and the `NetworkServiceRoleArn` defaults key.
- `0-0-18-role-arn-propagation-fix` — fixed `role_arn` not propagating into per-environment `deploy.parameters`.

Neither addressed the **precedence bug** where a generic `role_arn` default overrides the infra-specific `*ServiceRoleArn`. That is the remaining gap this issue targets.

## Open Questions

1. Should a generic `role_arn` in defaults be supported at all, or should it be deprecated in favor of the infra-specific keys?
2. When both a generic `role_arn` and the matching `*ServiceRoleArn` exist but differ, is silent override acceptable or should the user be warned?
3. Should the fix consolidate role_arn resolution into a single helper to eliminate the two divergent code paths (constructor vs `build_samconfig`)?
4. Does `service-role` infra type need any role_arn handling, or is it correctly excluded?

## Proposed Next Step

This is a **bugfix** (incorrect existing behavior). Recommend proceeding as a bugfix spec that:
- Inverts the precedence so the infra-type-specific `*ServiceRoleArn` always wins over a generic `role_arn`.
- Consolidates resolution to a single authoritative path.
- Adds/extends tests in `tests/test_config_role_arn.py` covering the "both keys present" scenario per infra type.

Awaiting decision before creating formal spec documents.

---

## Answers to Open Questions

1. Support generic role_arn as a fall back. It should only be manually added to a defaults.json file and read from the file, never programatically added.
2. Silent override is acceptable, it is a configuration choice
3. If feasible and doesn't impact other scripts, consolidate
4. service-role infra type is deprecated, but should still be supported, yet does not need to be part of this. If anything it can fall down into the default role_arn.
