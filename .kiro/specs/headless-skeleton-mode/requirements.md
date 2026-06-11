# Requirements Document

## Introduction

This feature adds two mutually exclusive non-interactive modes to the Atlantis SAM Config Scripts CLI (`cli/config.py`): a skeleton generation mode and a headless execution mode. Together they enable CI/CD pipelines and automation workflows to configure and deploy infrastructure without human interaction. A complementary `--headless` flag is also added to `cli/deploy.py` for non-interactive deployments.

## Glossary

- **Config_Manager**: The `ConfigManager` class in `cli/config.py` that orchestrates interactive configuration generation
- **Skeleton_File**: A temporary JSON file stored in `local-init/` that mirrors the internal config structure produced by `build_config()`, pre-populated with defaults and annotated with parameter metadata
- **Headless_Mode**: A non-interactive execution mode that reads a Skeleton_File and produces a samconfig without user prompts
- **Skeleton_Mode**: A semi-interactive mode that generates a Skeleton_File, prompting only for template selection
- **Skeleton_Verbose_Mode**: A semi-interactive mode identical to Skeleton_Mode but additionally includes Parameter_Metadata in the generated Skeleton_File
- **Template_Parameters**: CloudFormation template parameter definitions including constraints (AllowedPattern, AllowedValues, MinLength, MaxLength, MinValue, MaxValue)
- **Parameter_Metadata**: Descriptive hints embedded in the Skeleton_File including parameter descriptions, allowed values, and constraint information
- **Defaults_Hierarchy**: The cascading defaults resolution order: existing samconfig → defaults.json → prefix-defaults.json → prefix-project-defaults.json → infra_type/defaults.json
- **Stage_Calculated_Defaults**: Values derived from stage_id including DeployEnvironment, RepositoryBranch, and CodeCommitBranch
- **Automated_Tags**: Tags generated programmatically by Config_Manager (Atlantis, atlantis:Prefix, Provisioner, etc.) that are not user-editable
- **User_Editable_Tags**: Tags sourced from settings tag_keys, defaults files, and custom user entries that appear in the Skeleton_File
- **Deploy_Script**: The `cli/deploy.py` script that performs CloudFormation deployments using samconfig
- **Local_Init_Directory**: The `local-init/` directory at the project root used as a temporary scratch area for Skeleton_Files, with contents git-ignored

## Requirements

### Requirement 1: Mutually Exclusive Mode Flags

**User Story:** As a CLI user, I want clear mutually exclusive flags for skeleton, skeleton-verbose, and headless modes, so that I cannot accidentally invoke incompatible modes simultaneously.

#### Acceptance Criteria

1. THE Config_Manager SHALL accept a `--skeleton` flag, a `--skeleton-verbose` flag, and a `--headless` flag as boolean optional arguments that default to false when not provided
2. IF both `--skeleton` and `--headless` flags are provided, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the flags are mutually exclusive
3. IF both `--skeleton-verbose` and `--headless` flags are provided, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the flags are mutually exclusive
4. IF both `--skeleton` and `--skeleton-verbose` flags are provided, THEN THE Config_Manager SHALL treat the invocation as `--skeleton-verbose` (include parameter metadata)
5. IF `--headless` and `--check-stack` flags are both provided, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the flags are incompatible
6. IF `--skeleton` and `--check-stack` flags are both provided, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the flags are incompatible
7. IF `--skeleton-verbose` and `--check-stack` flags are both provided, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the flags are incompatible
8. WHEN neither `--skeleton`, `--skeleton-verbose`, nor `--headless` is provided, THE Config_Manager SHALL execute the interactive flow prompting the user for input
9. THE Config_Manager SHALL validate flag compatibility before initializing AWS sessions or performing any processing

### Requirement 2: Skeleton File Generation

**User Story:** As a DevOps engineer, I want to generate a pre-populated skeleton file, so that I can review and edit configuration values offline before running headless mode.

#### Acceptance Criteria

1. WHEN `--skeleton` or `--skeleton-verbose` flag is provided, THE Config_Manager SHALL create the Local_Init_Directory if it does not exist
2. WHEN `--skeleton` or `--skeleton-verbose` flag is provided AND no existing samconfig file is found for the given prefix, project_id, infra_type, and stage_id, THE Config_Manager SHALL prompt the user for template selection using the existing template discovery flow (discover_templates and select_from_file_list). WHEN an existing samconfig file IS found containing a template_file value, THE Config_Manager SHALL use that template_file without prompting the user for selection.
3. WHEN `--skeleton` or `--skeleton-verbose` flag is provided, THE Config_Manager SHALL generate a Skeleton_File at `local-init/{prefix}-{project_id}-{stage_id}-{infra_type}.json` where stage_id is included for pipeline and network infra_types, but NOT included for storage or service-role infra_types (resulting in `local-init/{prefix}-{project_id}-{infra_type}.json` for those types)
4. IF a Skeleton_File already exists at the target path, THEN THE Config_Manager SHALL inform the user that the file already exists and prompt to confirm overwrite
5. THE Config_Manager SHALL structure the Skeleton_File with the top-level keys `atlantis.deploy.parameters` (containing template_file, s3_bucket, region, capabilities, confirm_changeset, and role_arn where applicable) and `deployments.{stage_id}.deploy.parameters` (containing stack_name, s3_prefix, parameter_overrides, and tags), mirroring the format produced by `build_config()`
6. THE Config_Manager SHALL store the template as the full S3 URI with versionId in the Skeleton_File for templates sourced from S3, and as the filename only for templates sourced from local-templates
7. THE Config_Manager SHALL include an `applyTemplateUpdateIfAvailable` field with default value `"y"` in the Skeleton_File
8. WHEN generating the Skeleton_File, THE Config_Manager SHALL pre-populate parameter values from the existing samconfig for the given prefix, project_id, infra_type, and stage_id, falling back to the defaults hierarchy (defaults.json, prefix-defaults.json, prefix-project-defaults.json, infra_type/defaults.json) if no samconfig exists
9. THE Config_Manager SHALL include only user-editable tags (those defined in `tag_keys` from settings and defaults) in the Skeleton_File, excluding automated tags generated at deploy time
10. THE Config_Manager SHALL represent only the single stage specified by the `stage_id` argument in the Skeleton_File

### Requirement 3: Skeleton Pre-population from Defaults

**User Story:** As a DevOps engineer, I want the skeleton pre-filled with known values, so that I only need to modify parameters that differ from defaults.

#### Acceptance Criteria

1. WHEN an existing samconfig file is found for the given prefix, project_id, infra_type, and stage_id, THE Config_Manager SHALL pre-populate the Skeleton_File with the atlantis deploy parameters, parameter_overrides, and tags from that samconfig
2. WHEN no existing samconfig is found, THE Config_Manager SHALL pre-populate the Skeleton_File using the Defaults_Hierarchy by merging configuration files in the following order (later files override earlier): defaults.json, {prefix}-defaults.json, {prefix}-{project_id}-defaults.json, {infra_type}/defaults.json, {infra_type}/{prefix}-defaults.json, {infra_type}/{prefix}-{project_id}-defaults.json
3. WHEN a stage_id is provided, THE Config_Manager SHALL calculate and apply Stage_Calculated_Defaults where DeployEnvironment is "DEV" if stage_id starts with "d", "TEST" if stage_id starts with "t", or "PROD" otherwise, and RepositoryBranch and CodeCommitBranch are set to "main" if stage_id equals "prod" or to the stage_id value otherwise
4. THE Config_Manager SHALL represent a single stage only in the Skeleton_File (the stage specified by the stage_id argument)
5. IF an existing samconfig file is found but cannot be parsed, THEN THE Config_Manager SHALL fall back to the Defaults_Hierarchy and indicate to the user that the existing file could not be read

### Requirement 4: Skeleton Verbose Mode with Parameter Metadata

**User Story:** As a DevOps engineer, I want to optionally include parameter metadata in the skeleton using `--skeleton-verbose`, so that I can understand the constraints and valid values for each parameter without consulting template documentation.

#### Acceptance Criteria

1. THE `--skeleton-verbose` flag SHALL be a standalone flag that triggers skeleton generation AND includes Parameter_Metadata in the Skeleton_File
2. WHEN `--skeleton` flag is provided alone (without `--skeleton-verbose`), THE Config_Manager SHALL generate the Skeleton_File WITHOUT Parameter_Metadata
3. IF both `--skeleton` and `--skeleton-verbose` flags are provided, THEN THE Config_Manager SHALL treat the invocation as `--skeleton-verbose` and include Parameter_Metadata
4. WHILE Skeleton_Verbose_Mode is active, THE Config_Manager SHALL include a Parameter_Metadata section in the Skeleton_File containing one metadata entry for each template parameter listed in the parameters section
5. WHILE Skeleton_Verbose_Mode is active, IF a parameter description is defined in the template parameter definition, THEN THE Parameter_Metadata entry SHALL include the description text for that parameter
6. WHILE Skeleton_Verbose_Mode is active, IF AllowedValues are defined in the template parameter definition, THEN THE Parameter_Metadata entry SHALL include the list of AllowedValues for that parameter
7. WHILE Skeleton_Verbose_Mode is active, IF any constraint fields (AllowedPattern, MinLength, MaxLength, MinValue, MaxValue, ConstraintDescription) are defined in the template parameter definition, THEN THE Parameter_Metadata entry SHALL include each defined constraint field and its value for that parameter
8. WHILE Skeleton_Verbose_Mode is active, IF a Default value is defined in the template parameter definition, THEN THE Parameter_Metadata entry SHALL include the Default value for that parameter
9. WHILE Skeleton_Verbose_Mode is active, THE Parameter_Metadata entry for each parameter SHALL include the parameter Type as defined in the template parameter definition
10. WHILE Skeleton_Verbose_Mode is active, IF a template parameter has no description, no AllowedValues, no constraint fields, and no Default value defined, THEN THE Parameter_Metadata entry SHALL include only the parameter Type

### Requirement 5: Skeleton Tag Handling

**User Story:** As a DevOps engineer, I want only user-editable tags in the skeleton, so that I can set meaningful tags without confusion from auto-generated ones.

#### Acceptance Criteria

1. THE Config_Manager SHALL include only User_Editable_Tags in the Skeleton_File, where User_Editable_Tags are tags sourced from the `tag_keys` list in settings, the `tags` array in the Defaults_Hierarchy, and any non-reserved custom tags present in an existing samconfig for the same deployment
2. THE Config_Manager SHALL exclude Automated_Tags from the Skeleton_File, where Automated_Tags are tags identified by `is_atlantis_reserved_tag` (keys starting with "Atlantis" or "atlantis:", and reserved keys: Provisioner, DeployedUsing, Name, Stage, Environment, AlarmNotificationEmail, Repository, RepositoryBranch, CodeCommitRepository, CodeCommitBranch)
3. IF an existing samconfig contains values for User_Editable_Tags for the specified deployment, THEN THE Config_Manager SHALL pre-populate those tags in the Skeleton_File using the samconfig values as the highest-priority source
4. IF no existing samconfig is available for the specified deployment, THEN THE Config_Manager SHALL pre-populate User_Editable_Tags with values from the Defaults_Hierarchy, and SHALL set tag keys that have no value in any source to an empty string
5. IF both the Defaults_Hierarchy and an existing samconfig provide a value for the same User_Editable_Tag, THEN THE Config_Manager SHALL use the samconfig value

### Requirement 6: Headless Configuration Execution

**User Story:** As a CI/CD pipeline, I want to run configuration generation without any user prompts, so that infrastructure can be configured in automated workflows.

#### Acceptance Criteria

1. WHEN `--headless` flag is provided, THE Config_Manager SHALL read the Skeleton_File from `local-init/{prefix}-{project_id}-{stage_id}-{infra_type}.json` where stage_id is included for pipeline and network infra_types, but NOT included for storage or service-role infra_types (resulting in `local-init/{prefix}-{project_id}-{infra_type}.json` for those types)
2. IF the Skeleton_File does not exist at the expected path, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the file path that was not found
3. WHEN `--headless` flag is provided, THE Config_Manager SHALL validate all parameter values from the Skeleton_File against the template constraints (AllowedPattern, AllowedValues, MinLength, MaxLength, MinValue, MaxValue) and execute the full configuration generation without any user prompts
4. IF the Skeleton_File contains invalid or missing required parameter values, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message listing all validation failures
5. WHEN headless configuration completes successfully, THE Config_Manager SHALL save defaults automatically (equivalent to answering "Yes" to `check_for_default_json`)
6. WHEN headless configuration completes successfully, THE Config_Manager SHALL delete the Skeleton_File
7. WHEN `--headless` flag is provided, THE Config_Manager SHALL perform git pull before configuration and git commit and push after configuration without prompting the user
8. IF `--headless` and `--check-stack` flags are both provided, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the flags are mutually exclusive

### Requirement 7: Headless Parameter Validation

**User Story:** As a CI/CD pipeline, I want all parameter values validated before configuration is generated, so that invalid configurations are caught early with actionable error messages.

#### Acceptance Criteria

1. WHEN `--headless` flag is provided, THE Config_Manager SHALL validate all parameter values from the Skeleton_File against the corresponding Template_Parameters constraints before generating configuration
2. WHEN `--headless` flag is provided, THE Config_Manager SHALL validate each parameter value against AllowedPattern (regex match), AllowedValues (membership check), MinLength, MaxLength (string length bounds), and MinValue, MaxValue (numeric bounds) as defined in the template
3. IF any parameter value fails validation, THEN THE Config_Manager SHALL exit with a non-zero exit code and output an error message listing ALL validation failures including the parameter name, the provided value, and the constraint that was violated
4. WHEN `--headless` flag is provided, THE Config_Manager SHALL validate atlantis deploy parameters: s3_bucket (3-63 lowercase alphanumeric or hyphen characters, not starting or ending with hyphen), region (must be a member of the regions list in settings.json), role_arn (must match `arn:aws:iam::<account-id>:role/<role-name>` format), and confirm_changeset (must be "true" or "false")
5. IF the Skeleton_File is missing or contains malformed JSON, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the file could not be read or parsed
6. IF the template cannot be retrieved from S3 to obtain parameter constraints, THEN THE Config_Manager SHALL exit with a non-zero exit code and an error message indicating the template source and the failure reason

### Requirement 8: Headless Git Operations

**User Story:** As a CI/CD pipeline, I want git operations performed automatically, so that configuration changes are committed and pushed without manual intervention.

#### Acceptance Criteria

1. WHEN `--headless` flag is provided, THE Config_Manager SHALL perform `git pull` automatically without prompting before configuration begins
2. WHEN headless configuration completes successfully and there are staged changes, THE Config_Manager SHALL perform `git commit` with a system-generated commit message and `git push` automatically without prompting
3. WHEN headless configuration completes successfully and there are no changes to commit, THE Config_Manager SHALL skip the commit and push operations and exit with a zero exit code
4. IF a `git pull` fails in headless mode, THEN THE Config_Manager SHALL exit with a non-zero exit code and output an error message indicating the git operation that failed and the stderr output from the git command
5. IF a `git commit` or `git push` fails in headless mode, THEN THE Config_Manager SHALL exit with a non-zero exit code and output an error message indicating the git operation that failed and the stderr output from the git command

### Requirement 9: Headless Deploy Trigger

**User Story:** As a CI/CD pipeline, I want to optionally trigger deployment after configuration, so that I can automate the full configure-and-deploy workflow in a single command.

#### Acceptance Criteria

1. THE Config_Manager SHALL accept a `--deploy` flag in combination with `--headless`
2. WHEN both `--headless` and `--deploy` flags are provided and configuration completes with a successful save of the samconfig file, THE Config_Manager SHALL invoke the Deploy_Script automatically using the same infra_type, prefix, project_id, and stage_id arguments
3. WHEN `--deploy` is provided without `--headless`, THE Config_Manager SHALL ignore the `--deploy` flag (it has no effect in interactive or skeleton modes)
4. IF `--headless` and `--deploy` are provided and configuration fails before saving the samconfig file, THEN THE Config_Manager SHALL skip deployment invocation and exit with a non-zero exit code
5. IF `--headless` and `--deploy` are provided and the Deploy_Script invocation returns a non-zero exit code, THEN THE Config_Manager SHALL propagate that non-zero exit code as its own exit code

### Requirement 10: Deploy Script Headless Mode

**User Story:** As a CI/CD pipeline, I want to run deployments without prompts, so that the deploy step can execute in automated workflows.

#### Acceptance Criteria

1. THE Deploy_Script SHALL accept a `--headless` flag as an optional argument
2. WHEN `--headless` flag is provided, THE Deploy_Script SHALL perform `git pull` automatically without prompting
3. WHEN `--headless` flag is provided, THE Deploy_Script SHALL override `confirm_changeset` to `false` regardless of samconfig value
4. WHEN deployment completes successfully in headless mode, THE Deploy_Script SHALL stage all modified files in the working directory, perform `git commit` with a message containing the infra_type, prefix, project_id, and stage_id, and perform `git push` automatically without prompting
5. THE Deploy_Script SHALL NOT use the Skeleton_File; it SHALL read configuration from the samconfig file directly
6. IF a git pull operation fails in headless mode, THEN THE Deploy_Script SHALL abort execution and exit with a non-zero exit code and an error message indicating the git pull failure reason
7. IF a git commit or git push operation fails in headless mode, THEN THE Deploy_Script SHALL exit with a non-zero exit code and an error message indicating which git operation failed and the failure reason
8. WHEN the Deploy_Script completes successfully in headless mode, THE Deploy_Script SHALL exit with exit code 0
9. WHEN `--headless` flag is provided, THE Deploy_Script SHALL suppress all interactive prompts including confirmation dialogs and user input requests

### Requirement 11: CLI Help Text Updates

**User Story:** As a CLI user, I want the `--help` output to document the new skeleton, skeleton-verbose, headless, and deploy flags with usage examples, so that I can understand how to use the new modes without consulting external documentation.

#### Acceptance Criteria

1. THE Config_Manager EPILOG text SHALL include descriptions of the `--skeleton`, `--skeleton-verbose`, and `--headless` flags explaining their purpose and behavior
2. THE Config_Manager EPILOG text SHALL include usage examples demonstrating skeleton generation, headless execution, and headless with deploy
3. THE Config_Manager EPILOG text SHALL document the workflow: generate skeleton → edit skeleton → run headless
4. THE Config_Manager EPILOG text SHALL note the mutual exclusivity of `--skeleton`/`--skeleton-verbose` with `--headless`, and the incompatibility of `--check-stack` with `--headless`/`--skeleton`/`--skeleton-verbose`
5. THE Config_Manager EPILOG text SHALL document the `--deploy` flag and its requirement to be paired with `--headless`
6. THE Deploy_Script help text SHALL include a description of the `--headless` flag explaining that it suppresses prompts, auto-performs git operations, and overrides confirm_changeset

### Requirement 12: Local Init Directory Management

**User Story:** As a developer, I want the local-init directory managed as a temporary scratch area, so that skeleton files do not pollute version control.

#### Acceptance Criteria

1. THE Config_Manager SHALL use `local-init/` at the project root (same level as `cli/`, `defaults/`, `local-templates/`) for storing Skeleton_Files
2. WHEN the Config_Manager runs in skeleton mode, IF the `local-init/` directory does not exist, THEN THE Config_Manager SHALL create the `local-init/` directory before writing any Skeleton_File
3. THE `.gitignore` file SHALL contain a `local-init/*` entry to prevent version control tracking of the directory contents
4. WHEN headless mode completes configuration successfully, THE Config_Manager SHALL delete the consumed Skeleton_File from the `local-init/` directory
