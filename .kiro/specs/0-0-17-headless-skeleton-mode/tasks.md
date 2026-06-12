# Implementation Plan: Headless Skeleton Mode

## Overview

This plan implements two non-interactive execution modes for `cli/config.py` (skeleton generation and headless execution) and a headless mode for `cli/deploy.py`. The implementation proceeds incrementally: first the shared infrastructure (flags, validation, git methods, path logic), then skeleton generation, then headless execution, and finally deploy.py modifications.

## Tasks

- [x] 1. Add CLI flags and mode validation
  - [x] 1.1 Add new flags to `parse_args()` in `cli/config.py`
    - Add `--skeleton`, `--skeleton-verbose`, `--headless`, and `--deploy` flags as boolean optional arguments defaulting to False
    - Update EPILOG constant with new mode descriptions, usage examples, and workflow documentation
    - _Requirements: 1.1, 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 1.2 Implement `validate_mode_flags()` function in `cli/config.py`
    - Create function that checks mutual exclusivity: skeleton/skeleton-verbose vs headless, check-stack vs skeleton/headless
    - Exit with non-zero code and descriptive error message on invalid combinations
    - Treat `--skeleton` + `--skeleton-verbose` as `--skeleton-verbose`
    - Call `validate_mode_flags()` immediately after `parse_args()` in `main()`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.9_

  - [x] 1.3 Write unit tests for flag validation
    - Test all invalid flag combinations exit with correct error messages
    - Test that `--skeleton` + `--skeleton-verbose` resolves to skeleton-verbose
    - Test that no flags triggers interactive flow
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 2. Implement shared infrastructure
  - [x] 2.1 Add `headless_git_pull()` and `headless_git_commit_and_push()` to `Git` class in `cli/lib/gitops.py`
    - `headless_git_pull()`: run `git pull` without prompting, call `sys.exit()` with error message on failure
    - `headless_git_commit_and_push(commit_message)`: run `git add .`, check for changes, commit, push — all without prompting, `sys.exit()` on failure
    - Log operations via `Log.info()` and `Log.error()`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 2.2 Write unit tests for headless git operations
    - Test `headless_git_pull` success and failure paths
    - Test `headless_git_commit_and_push` success, failure, and no-changes paths
    - Mock subprocess.run to verify correct git commands
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 2.3 Add `get_skeleton_file_path()` method to `ConfigManager` in `cli/config.py`
    - Return `local-init/{prefix}-{project_id}-{stage_id}-{infra_type}.json` for pipeline/network
    - Return `local-init/{prefix}-{project_id}-{infra_type}.json` for storage/service-role
    - Path is relative to project root (parent of `cli/`)
    - _Requirements: 2.3, 6.1_

  - [x] 2.4 Write property test for skeleton file path naming (Property 1)
    - **Property 1: Skeleton file path follows infra_type naming rules**
    - Generate random prefix (lowercase alpha 2-8), project_id (alnum 1-32), stage_id, infra_type
    - Assert stage_id is in filename iff infra_type is pipeline or network
    - **Validates: Requirements 2.3, 6.1**

  - [x] 2.5 Add `get_user_editable_tags()` method to `ConfigManager` in `cli/config.py`
    - Filter tags using `TagUtils.is_atlantis_reserved_tag()` to exclude reserved tags
    - Return flat `{"Key": "Value"}` dict format for skeleton file
    - _Requirements: 2.9, 5.1, 5.2_

  - [x] 2.6 Write property test for tag filtering (Property 5)
    - **Property 5: Tag filtering excludes all reserved tags**
    - Generate random tag lists mixing reserved and non-reserved keys
    - Assert no reserved tag keys appear in output
    - **Validates: Requirements 2.9, 5.1, 5.2**

- [x] 3. Implement skeleton generation
  - [x] 3.1 Add `generate_skeleton()` method to `ConfigManager` in `cli/config.py`
    - Load existing samconfig via `read_samconfig()` if available
    - Merge defaults hierarchy via `DefaultsLoader.load_defaults()`
    - Apply `calculate_stage_defaults()` for stage-derived values
    - Store full S3 URI with versionId for S3 templates, filename only for local templates
    - Include `applyTemplateUpdateIfAvailable` field with default `"y"`
    - Filter tags to user-editable only via `get_user_editable_tags()`
    - If verbose=True, build `_parameter_metadata` section from template parameter definitions
    - Structure output with `atlantis.deploy.parameters`, `deployments.{stage_id}.deploy.parameters`
    - _Requirements: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 3.2 Write property test for single stage in skeleton (Property 2)
    - **Property 2: Skeleton structure contains exactly one stage**
    - Generate random stage_id strings
    - Assert `deployments` has exactly one key equal to stage_id
    - **Validates: Requirements 2.10, 3.4**

  - [x] 3.3 Write property test for template reference (Property 3)
    - **Property 3: Template reference includes versionId for S3 URIs**
    - Generate random S3 URIs with versionId and random local filenames
    - Assert S3 URIs preserve full URI with versionId; local templates are filename only
    - **Validates: Requirements 2.6**

  - [x] 3.4 Write property test for merge precedence (Property 4)
    - **Property 4: Pre-population merge precedence**
    - Generate random dicts for samconfig and defaults with overlapping keys
    - Assert samconfig values take precedence over defaults
    - **Validates: Requirements 2.8, 3.1, 3.2, 5.3, 5.4, 5.5**

  - [x] 3.5 Write property test for stage calculated defaults (Property 6)
    - **Property 6: Stage calculated defaults follow derivation rules**
    - Generate random stage_id strings
    - Assert DeployEnvironment is "DEV" if starts with "d", "TEST" if starts with "t", "PROD" otherwise
    - Assert RepositoryBranch/CodeCommitBranch is "main" if stage_id=="prod", else stage_id
    - **Validates: Requirements 3.3**

  - [x] 3.6 Write property test for verbose metadata (Property 7)
    - **Property 7: Verbose metadata includes all defined constraint fields**
    - Generate random parameter definitions with varying fields present/absent
    - Assert Type is always present, other fields present iff defined in input
    - **Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10**

  - [x] 3.7 Implement `run_skeleton_mode(args)` top-level function in `cli/config.py`
    - Create `local-init/` directory if it doesn't exist
    - Initialize ConfigManager
    - Discover templates and prompt user for selection (only interactive step)
    - Get template parameters via `get_template_parameters()`
    - Call `generate_skeleton()` to build skeleton dict
    - Check for existing file at target path, prompt overwrite if exists
    - Write JSON to `local-init/` with indentation for readability
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 12.1, 12.2_

  - [x] 3.8 Write unit tests for skeleton generation flow
    - Test directory creation when `local-init/` doesn't exist
    - Test overwrite prompt when file already exists
    - Test correct JSON structure written to file
    - Test verbose mode includes `_parameter_metadata`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement headless execution
  - [x] 5.1 Add `validate_all_parameters()` method to `ConfigManager` in `cli/config.py`
    - Iterate over all `parameter_overrides` in skeleton
    - Call existing `validate_parameter()` for each
    - Collect ALL failures (parameter name, value, violated constraint) rather than stopping at first
    - Return list of failure dicts
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 5.2 Add `validate_atlantis_deploy_params()` method to `ConfigManager` in `cli/config.py`
    - Validate s3_bucket (3-63 lowercase alphanumeric/hyphen, not starting/ending with hyphen)
    - Validate region (member of regions list in settings.json)
    - Validate role_arn (matches `arn:aws:iam::<account-id>:role/<role-name>` format)
    - Validate confirm_changeset (must be "true" or "false")
    - Return list of failure dicts
    - _Requirements: 7.4_

  - [x] 5.3 Write property test for validation reporting all failures (Property 8)
    - **Property 8: Headless validation reports all failures**
    - Generate random parameter sets with known-invalid values injected
    - Assert number of failures equals number of invalid parameters
    - **Validates: Requirements 6.4, 7.2, 7.3**

  - [x] 5.4 Write property test for parameter validation correctness (Property 9)
    - **Property 9: Parameter validation correctness**
    - Generate random values and constraint definitions (AllowedPattern, AllowedValues, MinLength/MaxLength)
    - Assert validation returns valid=True iff value satisfies all constraints
    - **Validates: Requirements 7.2, 7.4**

  - [x] 5.5 Add `build_config_headless()` method to `ConfigManager` in `cli/config.py`
    - Mirror `build_config()` logic but skip `gather_atlantis_deploy_parameters()` prompts
    - Accept pre-validated atlantis params, parameter values, and tags as inputs
    - Reuse same config assembly logic (stack_name generation, tag merging, deployment structure)
    - _Requirements: 6.3, 6.5_

  - [x] 5.6 Implement `run_headless_mode(args)` top-level function in `cli/config.py`
    - Call `Git.headless_git_pull()` — exits on failure
    - Initialize ConfigManager
    - Read and parse skeleton file from `local-init/` (exit with error if not found or malformed JSON)
    - Resolve template (check for update if `applyTemplateUpdateIfAvailable == "y"`)
    - Get template parameters via `get_template_parameters()`
    - Call `validate_all_parameters()` and `validate_atlantis_deploy_params()` — exit listing all errors if any
    - Call `build_config_headless()` with pre-validated values
    - Call `save_config()`
    - Auto-save defaults (equivalent to `check_for_default_json` with "yes")
    - Delete skeleton file from `local-init/`
    - Call `Git.headless_git_commit_and_push()` — exits on failure
    - If `--deploy`: invoke `deploy.py --headless` via subprocess with same positional args
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.5, 7.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 5.7 Write unit tests for headless execution flow
    - Test file not found error with correct path in message
    - Test malformed JSON error
    - Test validation failure output lists all errors
    - Test successful end-to-end flow (mock git, file I/O)
    - Test `--deploy` invokes deploy.py with correct arguments
    - Test `--deploy` without `--headless` is no-op
    - _Requirements: 6.1, 6.2, 6.4, 6.6, 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 6. Implement deploy.py headless mode
  - [x] 6.1 Add `--headless` flag to `parse_args()` in `cli/deploy.py`
    - Add `--headless` flag as boolean optional argument defaulting to False
    - Update EPILOG with description of headless flag behavior
    - _Requirements: 10.1, 11.6_

  - [x] 6.2 Modify `main()` in `cli/deploy.py` for headless branching
    - Use `Git.headless_git_pull()` when `--headless`, else `Git.prompt_git_pull()`
    - Use `Git.headless_git_commit_and_push()` when `--headless`, else `Git.git_commit_and_push()`
    - Set `override_confirm_changeset` attribute on deployer when headless
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9_

  - [x] 6.3 Modify `_run_sam_deploy()` in `cli/deploy.py` to support `--no-confirm-changeset`
    - When `self.override_confirm_changeset` is True, append `--no-confirm-changeset` to SAM CLI command
    - Initialize `override_confirm_changeset = False` in `TemplateDeployer.__init__()`
    - _Requirements: 10.3_

  - [x] 6.4 Write unit tests for deploy.py headless mode
    - Test `--headless` suppresses prompts and forces confirm_changeset=false
    - Test git operations are called correctly in headless mode
    - Test exit code propagation on failure
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 10.7, 10.8, 10.9_

- [x] 7. Wire main() branching and update .gitignore
  - [x] 7.1 Update `main()` in `cli/config.py` with three-way branch
    - After `validate_mode_flags(args)`, branch to `run_skeleton_mode(args)`, `run_headless_mode(args)`, or existing interactive flow
    - Ensure flag validation happens before any AWS session initialization
    - _Requirements: 1.8, 1.9_

  - [x] 7.2 Add `local-init/*` entry to `.gitignore`
    - Append `local-init/*` to the project root `.gitignore` file
    - _Requirements: 12.3_

  - [x] 7.3 Write integration tests for full skeleton → headless round trip
    - Generate skeleton, modify a value, run headless, verify samconfig output
    - Verify skeleton file is deleted after successful headless run
    - _Requirements: 6.6, 12.4_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python throughout, so all implementation is in Python
- Hypothesis is the PBT library specified in the design

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.3", "2.5", "6.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "2.4", "2.6", "6.3"] },
    { "id": 3, "tasks": ["3.1", "5.1", "5.2", "6.2"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "5.3", "5.4", "5.5", "6.4"] },
    { "id": 5, "tasks": ["3.7", "5.6"] },
    { "id": 6, "tasks": ["3.8", "5.7", "7.1", "7.2"] },
    { "id": 7, "tasks": ["7.3"] }
  ]
}
```
