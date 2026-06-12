# Requirements Document

## Introduction

Extend `role_arn` support to the `network` infrastructure type in the Atlantis SAM Config CLI. Currently, `role_arn` handling (prompting, persisting, defaulting, and propagating) is gated to `pipeline` and `storage` infra types only. This feature adds `network` to that set so that network deployments receive the same IAM role ARN treatment during interactive configuration, headless configuration, skeleton generation, and future-defaults saving.

## Glossary

- **Config_CLI**: The `cli/config.py` script that interactively or headlessly generates and manages samconfig deployment configurations.
- **Infra_Type**: A classification of the deployment target passed as the first positional argument to Config_CLI. Valid values include `pipeline`, `storage`, `network`, and `service-role`.
- **Role_ARN**: An AWS IAM role Amazon Resource Name used to assume a role during CloudFormation deployments. Format: `arn:aws:iam::<account-id>:role/<role-name>`.
- **Atlantis_Default_Deploy_Parameters**: The top-level `atlantis.deploy.parameters` section of a samconfig file that applies to all deployment environments within a project.
- **NetworkServiceRoleArn**: A defaults-file key that stores the saved Role_ARN for `network` Infra_Type configurations, analogous to `StorageServiceRoleArn` and `PipelineServiceRoleArn`.
- **Defaults_File**: A JSON file that stores saved user preferences (region, S3 bucket, role ARNs) for reuse across future configurations.
- **Skeleton**: The intermediate configuration structure generated during `generate_skeleton()` that pre-populates deployment parameters before final config assembly.

## Requirements

### Requirement 1: Interactive Role ARN Prompting for Network Deployments

**User Story:** As a developer configuring a network deployment, I want to be prompted for a Role_ARN during interactive configuration, so that my network stack deploys using the correct IAM role.

#### Acceptance Criteria

1. WHEN Infra_Type is `network`, THE Config_CLI SHALL prompt the user for a Role_ARN during `gather_atlantis_deploy_parameters()`
2. WHEN the user provides a valid Role_ARN for a network deployment, THE Config_CLI SHALL store the Role_ARN in the returned atlantis deploy parameters dictionary
3. WHEN the user provides an invalid Role_ARN for a network deployment, THE Config_CLI SHALL display a validation error and re-prompt
4. THE Config_CLI SHALL validate Role_ARN for network deployments using the same validation rules applied to pipeline and storage deployments

### Requirement 2: Role ARN in Atlantis Default Deploy Parameters

**User Story:** As a developer deploying network infrastructure, I want Role_ARN included in the atlantis default deploy parameters, so that it propagates to all environments within my network stack.

#### Acceptance Criteria

1. WHEN Infra_Type is `network` and a Role_ARN is provided, THE Config_CLI SHALL include `role_arn` in Atlantis_Default_Deploy_Parameters during `build_config()`
2. WHEN Infra_Type is `network` and a Role_ARN is provided, THE Config_CLI SHALL include `role_arn` in Atlantis_Default_Deploy_Parameters during `build_config_headless()`
3. WHEN Infra_Type is `network`, THE Config_CLI SHALL propagate `role_arn` from Atlantis_Default_Deploy_Parameters to per-environment deployment parameters

### Requirement 3: Role ARN in Skeleton Generation

**User Story:** As a developer configuring a network deployment, I want Role_ARN to appear in the generated skeleton, so that my configuration is pre-populated with the correct role from defaults or existing samconfig.

#### Acceptance Criteria

1. WHEN Infra_Type is `network` and a Role_ARN default exists, THE Config_CLI SHALL include `role_arn` in the generated atlantis section of the skeleton
2. WHEN Infra_Type is `network` and NetworkServiceRoleArn is present in the Defaults_File, THE Config_CLI SHALL use NetworkServiceRoleArn as the default Role_ARN value
3. WHEN Infra_Type is `network` and no NetworkServiceRoleArn exists but an existing samconfig contains `role_arn`, THE Config_CLI SHALL use the samconfig value as the default

### Requirement 4: Role ARN Default Resolution from Defaults File

**User Story:** As a developer, I want previously saved network Role_ARN values to be loaded as defaults, so that I do not have to re-enter the same ARN on subsequent configurations.

#### Acceptance Criteria

1. WHEN Infra_Type is `network` and NetworkServiceRoleArn is stored in the Defaults_File, THE Config_CLI SHALL resolve it as the default `role_arn` value during initialization
2. WHEN Infra_Type is `network` and no NetworkServiceRoleArn exists in the Defaults_File, THE Config_CLI SHALL fall back to the generic `role_arn` default if present
3. THE Config_CLI SHALL use the NetworkServiceRoleArn key exclusively for network Infra_Type default resolution, separate from StorageServiceRoleArn and PipelineServiceRoleArn

### Requirement 5: Saving Role ARN as Future Default for Network

**User Story:** As a developer, I want the option to save my network Role_ARN as a default for future configurations, so that I do not have to re-enter it each time.

#### Acceptance Criteria

1. WHEN `set_future_defaults()` is called for a network deployment with a Role_ARN, THE Config_CLI SHALL prompt the user to save the Role_ARN as a default
2. WHEN the user confirms saving the Role_ARN default for a network deployment, THE Config_CLI SHALL persist the value under the NetworkServiceRoleArn key in the Defaults_File
3. WHEN the user declines saving the Role_ARN default for a network deployment, THE Config_CLI SHALL leave the Defaults_File unchanged

### Requirement 6: Consistent Behavior Across Pipeline, Storage, and Network

**User Story:** As a developer, I want Role_ARN handling for network deployments to behave identically to pipeline and storage deployments, so that the user experience is predictable across infra types.

#### Acceptance Criteria

1. THE Config_CLI SHALL apply the same Role_ARN validation logic to network deployments as it applies to pipeline and storage deployments
2. THE Config_CLI SHALL apply the same Role_ARN prompting flow to network deployments as it applies to pipeline and storage deployments
3. THE Config_CLI SHALL apply the same Role_ARN propagation logic to network deployments as it applies to pipeline and storage deployments
4. THE Config_CLI SHALL NOT modify Role_ARN behavior for `service-role` Infra_Type
