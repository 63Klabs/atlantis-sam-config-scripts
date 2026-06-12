# Bugfix Requirements Document

## Introduction

When configuring pipeline or storage infrastructure via `config.py`, the `role_arn` parameter is saved to `atlantis.deploy.parameters` but is never propagated to individual environment/deployment `deploy.parameters`. This causes SAM deployments that require an execution role to fail because the per-environment config is missing the `role_arn`. The bug affects both `build_config()` (interactive mode) and `build_config_headless()` (headless mode).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `infra_type` is 'pipeline' or 'storage' AND `build_config()` is called THEN the system constructs `atlantis_default_deploy_parameters` WITHOUT `role_arn`, causing per-environment deployments to lack the `role_arn` in their `deploy.parameters`

1.2 WHEN `infra_type` is 'pipeline' or 'storage' AND `build_config_headless()` is called THEN the system constructs `atlantis_default_deploy_parameters` WITHOUT `role_arn`, causing per-environment deployments to lack the `role_arn` in their `deploy.parameters`

1.3 WHEN multiple deployments exist and the user chooses to apply deploy parameters to all THEN the system propagates `atlantis_default_deploy_parameters` (missing `role_arn`) to all deployments via `deployments[deployment]['deploy']['parameters'].update(atlantis_default_deploy_parameters)`

1.4 WHEN `role_arn` is added to `config['atlantis']['deploy']['parameters']` after `atlantis_default_deploy_parameters` is used THEN the system has `role_arn` only at the top-level atlantis config but not in any `deployments[stage_id]['deploy']['parameters']`

### Expected Behavior (Correct)

2.1 WHEN `infra_type` is 'pipeline' or 'storage' AND `build_config()` is called THEN the system SHALL include `role_arn` in `atlantis_default_deploy_parameters` so it propagates to all deployment environments' `deploy.parameters`

2.2 WHEN `infra_type` is 'pipeline' or 'storage' AND `build_config_headless()` is called THEN the system SHALL include `role_arn` in `atlantis_default_deploy_parameters` so it propagates to all deployment environments' `deploy.parameters`

2.3 WHEN multiple deployments exist and the user chooses to apply deploy parameters to all THEN the system SHALL propagate `role_arn` to all deployments as part of `atlantis_default_deploy_parameters`

2.4 WHEN `infra_type` is 'pipeline' or 'storage' THEN the system SHALL NOT redundantly add `role_arn` to `config['atlantis']['deploy']['parameters']` separately, since it is already included via `atlantis_default_deploy_parameters`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `infra_type` is 'network' or 'service-role' THEN the system SHALL CONTINUE TO construct `atlantis_default_deploy_parameters` without `role_arn`

3.2 WHEN `infra_type` is 'pipeline' or 'storage' THEN the system SHALL CONTINUE TO include `template_file`, `s3_bucket`, `region`, `capabilities`, and `confirm_changeset` in `atlantis_default_deploy_parameters`

3.3 WHEN any infra_type is used THEN the system SHALL CONTINUE TO propagate `stack_name`, `s3_prefix`, `parameter_overrides`, and `tags` to the current stage's deployment parameters

3.4 WHEN multiple deployments exist and the user chooses NOT to apply deploy parameters to all THEN the system SHALL CONTINUE TO only update the current stage's deployment parameters
