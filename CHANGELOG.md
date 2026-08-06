# CLI Script CHANGELOG

To update your local cli scripts from GitHub repository:

```bash
./cli/update.py
```

- The scripts are still in BETA and features are still being added and tested.
- Report any issues or requests via the [Issues page in the GitHub repository](https://github.com/63Klabs/atlantis-sam-config-scripts/issues)

## v0.0.19 (unreleased)

### Added
- **Library: atlantis.py v0.2.0** - Added `SamconfigReader` for reading deploy configuration from samconfig TOML files [Spec: 0-0-19-yaml-cfn-tag-parsing-fix](.kiro/specs/0-0-19-yaml-cfn-tag-parsing-fix/)
  - `read_parameter_overrides()`, `read_deploy_params()`, and `read_atlantis_params()` merge the shared `atlantis`/`default` section with the active stage's `deploy.parameters` (stage values win)
  - Static `parse_parameter_overrides()` parses SAM CLI `parameter_overrides`/`tags` strings (both plain `Key=Value` and quoted `"Key"="Value"` forms, via `shlex.split`) into a dict

### Changed
- **Script: deploy.py v0.2.0** - Reworked the deploy path for S3-hosted templates that use `AWS::Include` [Spec: 0-0-19-yaml-cfn-tag-parsing-fix](.kiro/specs/0-0-19-yaml-cfn-tag-parsing-fix/)
  - Resolves CloudFormation parameter references (e.g. `${S3ModuleLocation}`) inside `AWS::Include` `Location` values to literal `s3://` URLs so CloudFormation can retrieve the included modules server-side
  - Deploys the resolved template via a boto3 CloudFormation change set (`TemplateBody`, automatically uploading to the artifact bucket and switching to `TemplateURL` when the template exceeds the 51,200-byte inline limit) instead of `sam deploy`, which previously failed to locate S3-hosted templates and their include artifacts
  - CloudFormation resolves `AWS::Include` and the `AWS::Serverless-2016-10-31` transform server-side, so no local `sam package` or module download is required
  - Templates without S3 includes are unaffected and continue to deploy through `sam deploy`

### Fixed
- **Script: deploy.py v0.2.0** - Fixed YAML parsing failure for CloudFormation templates using short-form intrinsic tags [Spec: 0-0-19-yaml-cfn-tag-parsing-fix](.kiro/specs/0-0-19-yaml-cfn-tag-parsing-fix/)
  - Added module-level `_CfnLoader`, a PyYAML `SafeLoader` subclass with a catch-all `!` multi-constructor (using `deep=True`) that converts `!Sub`, `!Ref`, `!If`, `!GetAtt`, and all other CloudFormation short-form YAML tags into their long-form dict equivalents, so templates parse without `ConstructorError` and round-trip losslessly
  - `_has_s3_includes()` correctly detects `Fn::Transform: AWS::Include` S3 locations in templates that mix short-form tags, including `Location` values expressed as `Fn::Sub` or `Fn::Join` intrinsics

## v0.0.18 (2026-07-25)

### Added
- **Automatic dev-to-test Merge on Repository Creation** [Spec: 0-0-18-create-repo-auto-merge-test-branch](.kiro/specs/0-0-18-create-repo-auto-merge-test-branch/)
  - **Script: create_repo.py v0.2.0** - When a repository is seeded (via `--source` or a selected application starter), the seeded `dev` branch is now automatically merged into `test` so a test pipeline can be created immediately
  - Added `--skip-test-merge` opt-out flag to leave `test` unchanged; the merge only occurs when the repository is seeded
  - CodeCommit uses a server-side fast-forward merge; GitHub reuses the existing seed clone (no additional clone) and cleans it up afterward
  - Merge failures are non-fatal: the repository and its `dev` branch are preserved, and manual merge instructions are printed
  - On a successful merge, prints a follow-up hint for creating the test pipeline
  - **Library: gh_utils.py v0.1.0** - Added `GitHubUtils.merge_branches_fast_forward()` for fast-forward merging branches in a local clone
- **Script: config.py** - Extended `role_arn` support to `network` infrastructure type [Spec: 0-0-18-network-role-arn-support](.kiro/specs/0-0-18-network-role-arn-support/)
  - Network deployments now prompt for Role ARN during interactive configuration
  - Role ARN propagates to all environments in both `build_config()` and `build_config_headless()`
  - Role ARN included in skeleton generation for network deployments
  - New `NetworkServiceRoleArn` defaults key for persisting network-specific role ARN values
  - `set_future_defaults()` saves network role ARN under the correct key
  - Behavior is identical to existing `pipeline` and `storage` role ARN handling

### Fixed
- **Script: config.py** - Fixed `role_arn` not propagating to per-environment deploy parameters [Spec: 0-0-18-role-arn-propagation-fix](.kiro/specs/0-0-18-role-arn-propagation-fix/)
  - `role_arn` now included in `atlantis_default_deploy_parameters` for `pipeline` and `storage` infra types
  - Propagates correctly to all deployment environments in both `build_config()` and `build_config_headless()`
  - Eliminates redundant top-level `role_arn` entry in `config['atlantis']['deploy']['parameters']`
- **Script: config.py** - Fixed `role_arn` precedence so infra-specific `*ServiceRoleArn` defaults override a generic `role_arn` fallback [Spec: 0-0-18-role_arn-further-fix](.kiro/specs/0-0-18-role_arn-further-fix/), addresses [#3](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/3)
  - infra-specific key now wins over generic `role_arn` for pipeline/storage/network
  - generic `role_arn` is a read-only fallback and is no longer injected into defaults
  - interactive and headless paths consolidated onto a single `resolve_role_arn()` helper

## v0.0.17 (2026-06-01)

- **config.py**: Added headless skeleton mode for AI and CI/CD automation. Two new non-interactive execution modes:
  - `--skeleton` / `--skeleton-verbose`: Generates a pre-populated JSON configuration file in `local-init/` with defaults and (optionally) parameter metadata. Only prompts for template selection.
  - `--headless`: Reads a skeleton file, validates all parameters against template constraints, generates samconfig, performs git operations, and optionally triggers deployment — all without user prompts.
  - `--deploy`: When paired with `--headless`, automatically invokes `deploy.py --headless` after successful configuration.
- **deploy.py**: Added `--headless` flag that suppresses all prompts, auto-performs git pull/commit/push, and overrides `confirm_changeset` to false.
- **Shared**: Added `headless_git_pull()` and `headless_git_commit_and_push()` to the Git class for non-interactive git operations.
- Added `local-init/*` to `.gitignore` for temporary skeleton files.

## v0.0.16 (2026-04-03)

- **config.py v0.1.7/2026-03-26**: Fixed bug where if the template's parameter regex pattern was incorrect it would kill the script. Now it will gracefully ignore the bad pattern and still accept user data. The template will instead fail to deploy, however, at least user data is saved and it will be up to the platform team to fix the template.

## v0.0.11 (2025-08-27)

- Added delete.py script to delete pipelines and associated application stack
- Added git pull and pushes to config.py and deploy.py
- Added repository tags import to config.py

## v0.0.7 (2025-06-10)

Mostly stable. Still in Beta.

I'm going to go into a little more detail than usual.

- update.py (v0.1.5/2025-06-10): Fixed issue where the downloaded release zip file does not contain the `v` in front of the version number even if the release tag in GitHub has the `v`. This irregularity lies in GitHub and is a weird quirk that according to my conversation with GitHub Copilot is "undocumented but reproducible." This is even experienced when downloading a zip directly from the release page. The link will point to `<url>/v0.0.6.zip`, but the downloaded file will be `<repo-name>-0.0.6.zip` with files extracted to `<repo-name>-0.0.6.zip`.
- For the fix, GitHub Copilot recommended that instead of constructing the path beforehand, look inside the zip file and see what the actual path is. This should hopefully fix any future issue.

Below is GitHub Copilot's explanation. (Note: it says "This is a GitHub quirk for repositories with a dash (`-`) in the tag name" but there isn't a dash in the tag name, so there is still some inconsistencies as to why this happens.) However, I provide this information because:

1. GitHub Copilot admitted I was right :)
2. "This is not documented by GitHub, but is reproducible and widely observed." (so there could still be other quirks that need to be accounted for in the future)

### From GitHub Copilot

Thank you for the detailed info and the direct observation.

You are correct: **the downloaded file is named**  

```
atlantis-sam-config-scripts-0.0.6.zip
```
**even though the tag is `v0.0.6`.**

#### Why does this happen?

This is a GitHub quirk for repositories with a dash (`-`) in the tag name.

GitHub strips the leading `v` from the zip file and folder name **if the tag is in the format `vX.Y.Z`**.

- The actual tag in the repo is still `v0.0.6`.
- The zip file and extracted folder are named as if the tag is `0.0.6`.

**This is not documented by GitHub, but is reproducible and widely observed.**

#### What does this mean for your code?

Your code currently does:

```python
zipped_dir = f"{repo}-{tag}/"
```

If `tag` is `v0.0.6`, but the extracted folder is `atlantis-sam-config-scripts-0.0.6/`, your code will not find the right directory.

#### Summary

- GitHub sometimes strips the leading `v` from zip/folder names for tags like `v0.0.6`.
- Adjust your code to check for both possibilities.

## v0.0.6 (2025-06-09)

Mostly stable. Still in Beta.

- Fixed issue in update.py where if the AWS session token required a refresh, it would skip the requested pull

## v0.0.5 (2025-06-07)

Mostly stable. Still in Beta.

- Fixed issue in update.py where it was not pulling the latest changes from the organization's SAM config repository.
- Fixed issue in config.py where CodeCommit and Repository tags are being erroneously added to the tag prompts for the user even though they are automatically managed.
