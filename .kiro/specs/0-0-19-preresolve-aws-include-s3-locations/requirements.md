# Requirements Document

## Introduction

This document defines the requirements for pre-resolving `Fn::Transform: AWS::Include` S3 locations in CloudFormation templates before invoking `sam deploy`. The feature addresses a SAM CLI limitation where its intrinsic resolver cannot fetch template fragments from S3 URLs, causing deployments to fail for templates that use centralized S3-based module composition (introduced in `template-pipeline` v2.0.22).

**Spec Version:** 0-0-19  
**Feature:** preresolve-aws-include-s3-locations  
**GitHub Issue:** [#4](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/4)  
**Status:** Draft  
**Created:** 2026-08-05

## Overview

The `deploy.py` script currently downloads CloudFormation templates from S3 and passes them to `sam deploy --template-file`. However, when templates use `Fn::Transform: AWS::Include` with S3 `Location` URLs (introduced in `template-pipeline` v2.0.22), SAM CLI fails immediately because its intrinsic resolver cannot fetch from S3.

This requirement addresses the fundamental limitation in SAM CLI's `IntrinsicResolver` by introducing a `sam package` step that downloads S3 modules to local temp files, resolves all `Fn::Transform: AWS::Include` entries natively, and produces a fully packaged template before invoking `sam deploy`.

## Problem Statement

### Current Behavior

When `deploy.py` attempts to deploy a template containing:

```yaml
SourceEventServiceRole:
  Fn::Transform:
    Name: AWS::Include
    Parameters:
      Location: s3://bucket/namespace/templates/v2/modules/pipeline/source-event-service-role.yml
```

SAM CLI fails with:

```
Error: Template file not found at s3://<bucket>/<namespace>/templates/v2/modules/pipeline/source-event-service-role.yml
```

### Root Cause

SAM CLI's `deploy` command reads the template as a raw string and passes it directly to CloudFormation — it performs no `AWS::Include` resolution of any kind. The `AWS::Include` resolution that does exist in SAM CLI lives in `sam package` (`samcli/lib/package/artifact_exporter.py`, `_export_global_artifacts_pass()`), which walks the template recursively, resolves local includes, uploads them to S3, and rewrites `Location` to `s3://` URIs. This step is never invoked by `deploy.py`, which goes straight to `sam deploy --template-file`.

Replacing `Location: s3://...` with a local temp file path is not a viable workaround because `sam deploy` still passes the template to CloudFormation unmodified — CloudFormation would then receive a `Location` pointing at a machine-local path it cannot reach.

### Impact

- Templates using centralized S3-based module composition (v2.0.22+) cannot be deployed using `deploy.py`
- The new `S3ModuleLocation` and `S3ModuleNamespace` parameters are unusable via the standard deployment workflow
- Users must either:
  - Manually fetch and compose templates before deployment
  - Use `aws cloudformation deploy` directly (bypassing Atlantis automation)
  - Downgrade to older template versions without S3 includes

## Requirements

### Functional Requirements

#### FR1: Detect S3 Include Transforms and Trigger Package Step
**Priority:** MUST HAVE

The system MUST detect whether a downloaded template contains any `Fn::Transform: AWS::Include` entries with S3 `Location` URLs and, when found, route the deployment through a `sam package` + `sam deploy` flow instead of `sam deploy` alone.

**Acceptance Criteria:**
- Scan the downloaded template YAML/JSON for `Fn::Transform` entries with `Name: AWS::Include`
- Detect S3 URLs in `Parameters.Location` (patterns: `s3://`, `https://s3.amazonaws.com/`, `https://<bucket>.s3.<region>.amazonaws.com/`)
- If no S3 includes are found, proceed with the existing `sam deploy` flow unchanged
- If S3 includes are found, proceed with the `sam package` → `sam deploy` flow (FR4)

#### FR2: Parameter Substitution in S3 URLs
**Priority:** MUST HAVE

The system MUST substitute CloudFormation parameters in S3 `Location` URLs before downloading modules to local temp files.

**Acceptance Criteria:**
- Parse `Location` value to identify parameter references (e.g., `!Sub`, `!Ref`, `Fn::Sub`, `Fn::Join`)
- Extract parameter values from `parameter_overrides` in the samconfig TOML (already read by `deploy_with_temp_template()`)
- Support common patterns:
  - Direct references: `!Ref S3ModuleLocation`
  - String substitution: `!Sub '${S3ModuleLocation}/path/to/module.yml'`
  - Complex joins: `!Join ['/', [!Ref S3ModuleLocation, 'modules', 'file.yml']]`
- Resolve to a concrete S3 URL before downloading the module file

#### FR3: S3 Authentication for Module Downloads
**Priority:** MUST HAVE

The system MUST use appropriate S3 client based on bucket access configuration when downloading module files to local temp files.

**Acceptance Criteria:**
- Check if bucket is public using existing `is_bucket_public()` method
- Use anonymous S3 client for public buckets (no credentials required)
- Use authenticated `s3_client` for private buckets
- Handle authentication errors gracefully with informative messages

#### FR4: Package Step Using Artifact Bucket
**Priority:** MUST HAVE

When S3 includes are detected, the system MUST download each referenced module to a local temp file, rewrite `Location` values to relative local paths, run `sam package` to resolve the includes natively, and then pass the packaged output to `sam deploy`.

**Acceptance Criteria:**
- For each S3 `Location` URL (after parameter substitution per FR2):
  - Download the module file from S3 to a local temp file in the same temp directory as the main template
  - Rewrite the `Location` value in the template to a relative path (e.g., `./module-name.yml`)
- Write the rewritten template to the temp directory
- Read `s3_bucket` and `s3_prefix` from the samconfig TOML (under the active stage's `deploy.parameters`, falling back to `atlantis.deploy.parameters`)
- Run `sam package --template-file <rewritten-template> --output-template-file <packaged-template> --s3-bucket <artifact-bucket> --s3-prefix <prefix>`, passing `--profile` if set
- Verify `sam package` exits with code 0; surface errors and abort if not
- Pass the packaged output template to `sam deploy` in place of the original temp template
- All temp files reside within the existing `TemporaryDirectory` created by `deploy_with_temp_template()` so cleanup is automatic

#### FR5: Recursive Resolution via SAM Package
**Priority:** MUST HAVE

The system MUST support nested includes (modules that themselves contain `Fn::Transform: AWS::Include`) by delegating full recursive resolution to `sam package`.

**Acceptance Criteria:**
- `sam package`'s `_export_global_artifacts_pass()` recursively walks the template and all included fragments, so no custom recursion logic is required
- The implementation relies on SAM CLI's native behavior for nested include resolution
- Circular reference detection is handled by SAM CLI; any error from `sam package` is surfaced to the user with the original stderr output

#### FR6: Error Handling
**Priority:** MUST HAVE

The system MUST handle errors gracefully and provide actionable error messages.

**Acceptance Criteria:**
- Handle S3 access denied errors when downloading modules (permission issues)
- Handle S3 not found errors when downloading modules (incorrect URL or missing file)
- Handle network errors (timeouts, connection failures) during module downloads
- Surface `sam package` failures with the original stderr output and a clear message that the packaging step failed
- Provide context: which module download failed or which step (`sam package` vs `sam deploy`) failed, and what action to take

#### FR7: Backward Compatibility
**Priority:** MUST HAVE

The system MUST continue to work correctly with templates that don't use S3 includes.

**Acceptance Criteria:**
- Templates without `Fn::Transform` deploy unchanged
- Templates with local file includes continue to work
- Templates with non-S3 transforms (e.g., `AWS::Serverless` transform) remain unaffected
- No performance degradation for templates without S3 includes

### Non-Functional Requirements

#### NFR1: Performance
**Priority:** SHOULD HAVE

The resolution process SHOULD complete efficiently without significant deployment delays.

**Acceptance Criteria:**
- S3 module downloads use existing authenticated sessions (no extra authentication overhead)
- Module downloads occur in the same temp directory as the main template, so no extra I/O paths are introduced
- `sam package` runs once as a single subprocess call; overhead is proportional to the number of modules
- Total pre-processing time (downloads + `sam package`) < 10 seconds for a typical template with 3-5 modules

#### NFR2: Maintainability
**Priority:** SHOULD HAVE

The implementation SHOULD be maintainable and testable.

**Acceptance Criteria:**
- S3 include detection isolated in a helper method (e.g., `_has_s3_includes()`)
- Module download and `Location` rewriting isolated in a helper method (e.g., `_download_s3_includes()`)
- `sam package` invocation isolated in a helper method (e.g., `_run_sam_package()`) mirroring the existing `_run_sam_deploy()` pattern
- Minimal changes to the existing `deploy_with_temp_template()` flow — the package step slots in between the template download and the deploy call
- Unit testable (mock S3 calls, test parameter substitution, test `Location` rewriting)
- Clear documentation of the two-step flow and when each path is taken

#### NFR3: Logging and Debugging
**Priority:** SHOULD HAVE

The system SHOULD provide visibility into the resolution process.

**Acceptance Criteria:**
- Log each S3 include detected (resolved URL after parameter substitution)
- Log each module download (bucket, key, local temp file path)
- Log the `sam package` command being executed
- Log the path to the packaged output template passed to `sam deploy`
- Use existing `ConsoleAndLog` / `Log` infrastructure

## Constraints

### Technical Constraints

1. **SAM CLI Behavior**: `sam deploy` passes the template to CloudFormation as-is with no `AWS::Include` resolution. The `sam package` command is the correct SAM CLI mechanism for resolving local `AWS::Include` entries and must be invoked as a pre-step when S3 includes are present.
2. **Artifact Bucket Required**: The `sam package` step requires an S3 bucket to upload resolved module content. The artifact bucket (`s3_bucket`) is already configured in every samconfig TOML under `atlantis.deploy.parameters` and must be read by `deploy.py` for this step.
3. **Existing Infrastructure**: Must use existing `TemplateDeployer` class methods:
   - `s3_client` / `s3_client_anonymous` (authenticated and anonymous S3 clients)
   - `is_bucket_public()` (public bucket detection for module downloads)
   - `parse_s3_url()` (URL parsing)
   - `parameter_overrides` read from samconfig TOML (for `Location` URL substitution)
4. **Temp File Management**: All temp files (rewritten template, downloaded modules, packaged output) must reside within the `TemporaryDirectory` already created by `deploy_with_temp_template()` so that cleanup is automatic.

### Scope Constraints

#### In Scope
- Detecting `Fn::Transform: AWS::Include` entries with S3 locations
- Parameter substitution in `Location` URLs
- Downloading S3 modules to local temp files
- Rewriting `Location` values to relative local paths
- Running `sam package` to resolve includes and upload artifacts to the artifact bucket
- Passing the packaged template to `sam deploy`
- Error handling and logging

#### Out of Scope
- Modifying SAM CLI source code
- Supporting non-S3 remote includes (HTTP, Git, etc.)
- In-memory YAML merging or custom YAML tag handling
- Caching modules across deployments
- Validating module content (SAM CLI and CloudFormation handle this)
- Supporting `AWS::Include` outside of `Fn::Transform` context

## Dependencies

### Code Dependencies
- Existing `cli/deploy.py` (`TemplateDeployer` class — all changes made here)
- Existing `cli/lib/aws_session.py` (S3 client management)
- Python `tomli` library (already imported in `deploy.py` — reads `s3_bucket`/`s3_prefix` from samconfig)
- Python `yaml` library (already in `requirements.txt` — used for S3 include detection scan only)
- Python `boto3` library (already in `requirements.txt` — S3 module downloads)

### Template Dependencies
- `template-pipeline` v2.0.22+ (introduces S3 module parameters)
- S3 bucket with module library (63klabs-templates or custom namespace)
- Artifact S3 bucket (`s3_bucket` in samconfig) with write permissions for the deploying IAM principal
- Proper IAM permissions for S3 read access to the module bucket (or public bucket)

## Success Criteria

### Definition of Done

1. ✅ Templates with `Fn::Transform: AWS::Include` + S3 locations deploy successfully via `deploy.py`
2. ✅ Parameter substitution works for `S3ModuleLocation` and `S3ModuleNamespace`
3. ✅ Both public and private S3 module buckets are supported for downloads
4. ✅ Nested includes (modules including modules) work correctly via `sam package`'s native recursion
5. ✅ Error messages are clear and actionable for both download failures and `sam package` failures
6. ✅ Existing templates without S3 includes continue to use the direct `sam deploy` flow unchanged
7. ✅ Unit tests cover S3 include detection, parameter substitution, and `Location` rewriting logic
8. ✅ Integration test demonstrates end-to-end deployment with S3 modules via the package + deploy flow

### Testing Requirements

#### Unit Tests
- S3 include detection (templates with and without `Fn::Transform: AWS::Include`)
- S3 URL detection (various S3 URL formats)
- Parameter substitution in `Location` URLs (`!Ref`, `!Sub`, `!Join`)
- `Location` rewriting from S3 URL to relative local path
- `s3_bucket` / `s3_prefix` extraction from samconfig TOML (stage override vs. atlantis default)
- Error handling for module download failures (access denied, not found)

#### Integration Tests
- Deploy template with S3 includes to actual AWS account via the package + deploy flow
- Verify CloudFormation stack creates successfully with all module resources present
- Verify modules are correctly composed and resolved in the deployed stack
- Test with both public and private module buckets

#### Manual Tests
- Deploy `template-pipeline` v2.0.22 with S3 module parameters
- Verify all resources from included modules are created
- Verify CloudFormation console shows the resolved template (transforms replaced with actual resources)

## Alternative Approaches

### Chosen Approach: `sam package` + `sam deploy` via Artifact Bucket
**Decision:** Selected

Download each S3 module to a local temp file, rewrite `Location` to a relative path, run `sam package` (which natively resolves `AWS::Include` entries and uploads artifacts to the artifact bucket), then run `sam deploy` on the packaged output.

**Pros:**
- No custom YAML parsing, merging, or tag handling
- Recursive and nested includes handled natively by SAM CLI
- Artifact bucket is already configured in every samconfig TOML — no new infrastructure needed
- Packaged output is a fully self-contained template that CloudFormation can deploy directly
- Aligns with SAM CLI's intended `package` → `deploy` workflow

**Cons:**
- Requires reading `s3_bucket` / `s3_prefix` from the samconfig TOML explicitly in `deploy.py`
- Adds a `sam package` subprocess call before `sam deploy` when S3 includes are present

### Alternative 1: Replace S3 `Location` with Local Temp File Path (Rejected)
**Decision:** Not viable

Rewrite `Location: s3://...` to a local absolute temp path and pass directly to `sam deploy`.

**Why rejected:** `sam deploy` reads the template as a raw string and passes it to CloudFormation unmodified — it performs no `AWS::Include` resolution. CloudFormation would receive a `Location` pointing at a machine-local path it cannot reach, causing the same failure with a different URL.

### Alternative 2: In-Memory YAML Merging (Rejected)
**Decision:** Not recommended

Download each S3 module, parse the YAML in Python, and merge the resulting dict into the parent template in memory before writing the resolved template to the temp file.

**Why rejected:** CloudFormation's YAML dialect uses custom tags (`!Ref`, `!Sub`, `!If`, etc.) that Python's standard `yaml` library doesn't handle without a custom multi-constructor. Getting tag preservation right across arbitrary nested structures is fragile and difficult to test exhaustively. The `sam package` approach delegates this complexity to SAM CLI, which handles it correctly.

### Alternative 3: Switch to `aws cloudformation deploy`
**Decision:** Not recommended for initial implementation; keep as future option.

**Pros:**
- CloudFormation natively supports `AWS::Include` with S3 locations
- No custom resolution logic needed

**Cons:**
- Larger change to deployment pipeline
- Loses SAM CLI benefits (package transformation, guided deployments)
- May require changes to other scripts that depend on SAM CLI

### Alternative 4: File Bug with SAM CLI
**Decision:** Pursue in parallel, but implement workaround now.

**Pros:**
- Fixes root cause upstream
- Benefits entire SAM CLI community

**Cons:**
- Out of Atlantis team's control
- Uncertain timeline for fix
- Would still need workaround until fixed

### Alternative 5: Convert Templates to Local Includes
**Decision:** Not acceptable; undermines architectural goals.

**Cons:**
- Defeats purpose of centralized module library
- Increases template maintenance burden
- Loses version control benefits of S3 modules

## References

### GitHub Issue
- [#4 - deploy.py: Pre-resolve AWS::Include S3 locations before invoking sam deploy](https://github.com/63Klabs/atlantis-sam-config-scripts/issues/4)

### Related Documentation
- SAM CLI Source: `samcli/lib/intrinsic_resolver/intrinsic_property_resolver.py`
- SAM CLI Source: `samcli/commands/_utils/template.py`
- CloudFormation `AWS::Include` Documentation: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/create-reusable-transform-function-snippets-and-add-to-your-template-with-aws-include-transform.html
- Template Pipeline v2.0.22 Release Notes

### Existing Code
- `cli/deploy.py` - Entry point
- `cli/lib/template_deployer.py` - TemplateDeployer class
- `cli/lib/aws_session.py` - AWS session management

## Open Questions

1. **Q:** Should we cache fetched modules across multiple deployments in the same session?  
   **A:** Out of scope. `sam package` handles deduplication within a single deployment.

2. **Q:** Should we validate module content before the package step?  
   **A:** No. SAM CLI validates during `sam package` and CloudFormation validates during deploy. Pre-validation adds complexity without benefit.

3. **Q:** Should we support HTTP includes (non-S3)?  
   **A:** Out of scope. Only S3 includes for now.

4. **Q:** Should we preserve the original template with transforms for debugging?  
   **A:** Yes, log the path to the rewritten and packaged templates. The original downloaded template is already preserved within the temp directory until the `TemporaryDirectory` context exits.

5. **Q:** What if `s3_bucket` or `s3_prefix` is missing from samconfig?  
   **A:** Fail with a clear error explaining that an artifact bucket is required to deploy templates with S3 includes, and direct the user to run `config.py` to ensure `s3_bucket` is configured.

## Approval

- [x] Requirements reviewed by development team
- [x] Requirements approved by project maintainer
- [x] Ready for design phase

## Glossary

| Term | Definition |
|------|------------|
| Artifact bucket | The S3 bucket configured as `s3_bucket` in the samconfig TOML, used by SAM CLI to upload packaged Lambda code, nested stacks, and resolved `AWS::Include` module content. |
| `AWS::Include` | A CloudFormation transform that inserts the content of another template snippet stored in S3 or locally into a CloudFormation template at the point where the transform is declared. |
| `Fn::Transform` | A CloudFormation intrinsic function that invokes a macro or transform (such as `AWS::Include`) to process a section of a template. |
| `_export_global_artifacts_pass()` | The SAM CLI function in `samcli/lib/package/artifact_exporter.py` that recursively walks a template and resolves all `AWS::Include` entries, uploading local files to S3 and rewriting `Location` to `s3://` URIs. This is the mechanism invoked by `sam package`. |
| Parameter override | A key-value pair supplied to `sam deploy` (or `deploy.py`) that substitutes a CloudFormation parameter value at deploy time, referenced in the template as `!Ref`, `!Sub`, etc. |
| `sam package` | The SAM CLI command that resolves local artifact references (including `AWS::Include` local file paths), uploads them to an S3 artifact bucket, and produces a new template with all references rewritten to S3 URLs. |
| S3 module | A self-contained CloudFormation YAML snippet stored in S3 that can be included in a parent template via `Fn::Transform: AWS::Include`. |
| `S3ModuleLocation` | A CloudFormation parameter introduced in `template-pipeline` v2.0.22 that holds the base S3 URL for the module library (e.g., `s3://bucket/namespace/templates/v2/modules`). |
| `S3ModuleNamespace` | A CloudFormation parameter introduced in `template-pipeline` v2.0.22 that identifies the namespace or path segment within the S3 module library. |
| SAM CLI | AWS Serverless Application Model Command Line Interface; the tool used by `deploy.py` to package and deploy serverless CloudFormation stacks. |
| `TemplateDeployer` | The class in `cli/deploy.py` that orchestrates template downloading, parameter resolution, and SAM CLI invocation. |
