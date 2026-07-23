# Bugfix Requirements Document

## Introduction

`role_arn` is the active SAM deploy parameter written into `samconfig` under `deploy.parameters`. For a stack of a given infrastructure type, it should be derived from the infra-type-specific persisted default key — `PipelineServiceRoleArn` (pipeline), `StorageServiceRoleArn` (storage), or `NetworkServiceRoleArn` (network). A generic `role_arn` key in a defaults file is only a fallback.

The defect is a precedence inversion in `cli/config.py`. The `ConfigManager` constructor only maps the infra-specific `*ServiceRoleArn` into `role_arn` when a generic `role_arn` is NOT already present in defaults (`if 'role_arn' not in self.defaults['atlantis']`). When a defaults file contains BOTH a generic `role_arn` (for example equal to the pipeline ARN) AND the infra-specific keys, the guard is False and the infra-specific override never runs. As a result, a `storage` or `network` deployment incorrectly inherits the generic (pipeline) role. This matches the scenario reported in [issue #3](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/3).

A second resolution block (in `generate_skeleton`, which feeds the headless path) already uses the correct precedence — infra-specific first, generic `role_arn` last — and loads its own fresh defaults, so it is not contaminated. The constructor's mutation of `self.defaults['atlantis']['role_arn']`, however, feeds the interactive `build_config` path and produces the wrong value. This fix reconciles the two paths onto a single authoritative precedence and stops the constructor from programmatically injecting `role_arn` into the defaults.

Generic `role_arn` remains supported as a fallback only: it may be manually added to a defaults file and read from that file, but it must never be programmatically injected into the defaults dictionary.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `infra_type` is 'storage' AND the defaults contain BOTH a non-empty generic `role_arn` AND a non-empty `StorageServiceRoleArn` THEN the system resolves `role_arn` to the generic `role_arn` value instead of `StorageServiceRoleArn`, because the constructor guard `if 'role_arn' not in self.defaults['atlantis']` is False and the infra-specific override never runs

1.2 WHEN `infra_type` is 'network' AND the defaults contain BOTH a non-empty generic `role_arn` AND a non-empty `NetworkServiceRoleArn` THEN the system resolves `role_arn` to the generic `role_arn` value instead of `NetworkServiceRoleArn`

1.3 WHEN `infra_type` is 'pipeline' AND the defaults contain BOTH a generic `role_arn` AND a `PipelineServiceRoleArn` that differ THEN the system resolves `role_arn` from the generic `role_arn` rather than authoritatively from `PipelineServiceRoleArn` (correct only by coincidence when the two happen to be equal)

1.4 WHEN the constructor resolves `role_arn` from an infra-specific key THEN the system mutates `self.defaults['atlantis']['role_arn']`, programmatically injecting a key that was not present in the defaults file

1.5 WHEN `role_arn` is resolved THEN the system applies resolution in two divergent locations — the constructor (inverted precedence, feeding the interactive `build_config` path) and `generate_skeleton` (correct precedence, feeding the headless path) — so identical defaults can produce different results between interactive and headless configuration

### Expected Behavior (Correct)

2.1 WHEN `infra_type` is 'storage' AND the defaults contain BOTH a generic `role_arn` AND a non-empty `StorageServiceRoleArn` THEN the system SHALL resolve `role_arn` to `StorageServiceRoleArn`

2.2 WHEN `infra_type` is 'network' AND the defaults contain BOTH a generic `role_arn` AND a non-empty `NetworkServiceRoleArn` THEN the system SHALL resolve `role_arn` to `NetworkServiceRoleArn`

2.3 WHEN `infra_type` is 'pipeline' AND the defaults contain BOTH a generic `role_arn` AND a non-empty `PipelineServiceRoleArn` THEN the system SHALL resolve `role_arn` to `PipelineServiceRoleArn`

2.4 WHEN resolving `role_arn` for any infra type THEN the system SHALL NOT mutate or inject `role_arn` into `self.defaults`; resolution SHALL occur at the point of use

2.5 WHEN both the interactive (`build_config`) and headless (`generate_skeleton`) paths resolve `role_arn` THEN the system SHALL apply a single authoritative precedence order so that identical defaults produce identical results in both paths

2.6 WHEN resolving `role_arn` THEN the system SHALL apply the precedence: existing samconfig `role_arn` (highest) → infra-specific `*ServiceRoleArn` → generic `role_arn` (fallback)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the defaults contain a generic `role_arn` but NO matching infra-specific key THEN the system SHALL CONTINUE TO use the generic `role_arn` as the resolved value (fallback)

3.2 WHEN the defaults contain only the matching infra-specific `*ServiceRoleArn` (no generic `role_arn`) THEN the system SHALL CONTINUE TO resolve `role_arn` to that infra-specific value

3.3 WHEN an existing samconfig already defines `role_arn` THEN the system SHALL CONTINUE TO treat that saved value as the highest precedence

3.4 WHEN `infra_type` is 'service-role' THEN the system SHALL CONTINUE TO fall through to the generic `role_arn` with no infra-specific handling

3.5 WHEN `infra_type` is 'pipeline', 'storage', or 'network' THEN the system SHALL CONTINUE TO propagate the resolved `role_arn` to every deployment's `deploy.parameters` and to the `atlantis` section (behavior from prior v0.0.18 fixes)

3.6 WHEN `set_future_defaults()` saves a `role_arn` THEN the system SHALL CONTINUE TO persist it under the infra-specific key (`StorageServiceRoleArn`, `PipelineServiceRoleArn`, or `NetworkServiceRoleArn`)

3.7 WHEN no `role_arn` is available from samconfig or defaults THEN the system SHALL CONTINUE TO behave as before (prompt in interactive mode, empty value in headless mode)
