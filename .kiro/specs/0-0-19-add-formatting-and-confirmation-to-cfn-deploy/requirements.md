# Requirements: Add Formatting and Confirmation to CloudFormation Deploy

## Introduction

`deploy.py` deploys infrastructure through one of two internal branches, chosen automatically by
`deploy_with_temp_template()`:

- **SAM branch** (`_run_sam_deploy`) — used when the resolved template has **no** S3 `AWS::Include`
  transforms. It shells out to `sam deploy`, which prints its own "Deploying with following values"
  table, changeset listing, confirmation prompt, event progress, and Outputs.
- **CloudFormation branch** (`_cfn_deploy_packaged`) — used when the template **has** S3 includes.
  It drives a boto3 CloudFormation change set directly. Today it prints only uncolored
  `ConsoleAndLog` lines, never lists changeset changes, never honors `confirm_changeset`, waits
  silently on boto3 waiters, and does not report Outputs.

This creates an inconsistent user experience: the same command produces a rich, interactive display
for SAM-style templates but a sparse, silent, non-interactive display for include-based templates.

The goal of this feature is to bring the CloudFormation branch to visual and behavioral parity with
the SAM branch — a pre-deploy values summary, a changeset listing, a confirmation gate honoring
`confirm_changeset`, periodic progress output, a success banner, and a listing of stack Outputs —
while leaving the SAM branch completely unchanged. We are constrained by what the boto3
CloudFormation API exposes, so parity is "close as practical," not identical.

## Terminology

- **CFN branch** — the `_cfn_deploy_packaged` code path in `deploy.py`.
- **SAM branch** — the `_run_sam_deploy` code path in `deploy.py`.
- **Headless mode** — invocation with `--headless`; sets `deployer.override_confirm_changeset = True`
  and suppresses interactive prompts.
- **`Colorize`** — the formatting API in `cli/lib/tools.py` (color constants from
  `cli/lib/tools_colors.py`): yellow = `OUTPUT_VALUE`, green = `OUTPUT`/`SUCCESS`.

## Scope

### In scope

- Formatting, confirmation, progress, success banner, and Outputs listing for the **CFN branch only**.
- Introducing `Colorize` into `deploy.py` for the new output.
- Inline implementation within `deploy.py` (no shared library refactor).

### Out of scope

- Any change to the SAM branch (`_run_sam_deploy`) or its output.
- Refactoring the wait/progress logic into a reusable `cli/lib/` helper (noted as possible future work).
- Changes to `delete.py`.
- Changes to the include-resolution / change set creation logic beyond what is needed to display,
  confirm, and report progress.

## Requirements

### Requirement 1: Pre-deploy values summary (CFN branch)

**User Story:** As an operator deploying an include-based template, I want to see the values that
will be used for deployment before the change set is executed, so that I have the same visibility I
get from the SAM branch.

#### Acceptance Criteria

1. WHEN the CFN branch is entered THEN `deploy.py` SHALL print a "Deploying with following values"
   summary before creating/executing the change set.
2. The summary SHALL list, at minimum: `Stack name`, `Region`, `Confirm changeset`, `Capabilities`,
   `Parameter overrides`, and `Tags`.
3. WHEN a `role_arn` is configured (non-empty) THEN the summary SHALL include a `Role ARN` line;
   WHEN no `role_arn` is configured THEN the summary SHALL omit that line.
4. WHEN the template is uploaded to S3 because it exceeds the inline `TemplateBody` size limit THEN
   the summary SHALL include a `Deployment s3 bucket` line; otherwise it SHALL omit that line.
5. The summary SHALL NOT include `Disable rollback` or `Signing Profiles` (not set by this path).
6. Each value line SHALL be rendered with `Colorize.output_with_value()` (green label, yellow value).
7. The `Deploying with following values` heading and its `=` divider SHALL be rendered in yellow.

### Requirement 2: Colorized headings and dividers

**User Story:** As a user, I want the CFN branch output to look consistent with the rest of the CLI,
so that the experience feels connected across scripts.

#### Acceptance Criteria

1. `deploy.py` SHALL use `Colorize` (from `lib.tools`) for the new headings, dividers, values, prompts,
   progress lines, success banner, and error listings described in this document.
2. Section headings (e.g. `Deploying with following values`, `Initiating deployment`) and their
   dividers SHALL be rendered using `=` characters in yellow, replicating the SAM CLI look.
3. Existing `ConsoleAndLog` logging behavior SHALL be preserved so that log-file output is unaffected
   (colorized console output is additive, not a replacement for logging).

### Requirement 3: Changeset listing

**User Story:** As an operator, I want to see what the change set will change before it is executed,
so that I can review the impact.

#### Acceptance Criteria

1. WHEN a change set is created successfully AND it contains changes THEN `deploy.py` SHALL call
   `describe_change_set` and print a listing of the changes.
2. For each change, the listing SHALL show: Action (Add/Modify/Remove), Logical ID, Resource Type,
   and — when present — the Replacement flag and Physical ID.
3. The listing SHALL loosely resemble the SAM changeset table format.
4. The listing SHALL NOT print full raw change set JSON.

### Requirement 4: Confirmation gate honoring `confirm_changeset`

**User Story:** As an operator, I want to confirm a change set before it executes when I have
`confirm_changeset` enabled, matching the SAM branch behavior.

#### Acceptance Criteria

1. WHEN `confirm_changeset` is true AND `override_confirm_changeset` is false (not headless) THEN
   after listing the changes `deploy.py` SHALL prompt the user for `[y/N]` confirmation before
   executing the change set.
2. WHEN `confirm_changeset` is false OR `override_confirm_changeset` is true (headless) THEN
   `deploy.py` SHALL skip the prompt and execute the change set automatically.
3. WHEN the user declines the confirmation prompt THEN `deploy.py` SHALL delete the pending
   (unexecuted) change set, print a cancellation message, and return a non-zero exit code.
4. WHEN the CFN branch returns a non-zero exit code due to a declined confirmation THEN `main()`
   SHALL NOT perform the post-deploy git commit/push or enable termination protection (existing
   behavior for non-zero exit codes).
5. The confirmation gate SHALL use the `Colorize`-styled prompt helpers consistent with other scripts.

### Requirement 5: Empty changeset no-op

**User Story:** As an operator, I want a clean no-op when there is nothing to deploy, without being
asked to confirm an empty change set.

#### Acceptance Criteria

1. WHEN the change set contains no changes THEN `deploy.py` SHALL print a "no changes to deploy"
   message, delete the empty change set, and return exit code 0.
2. WHEN the change set contains no changes THEN `deploy.py` SHALL NOT prompt for confirmation and
   SHALL NOT print a changeset listing.

### Requirement 6: Progress output during stack execution

**User Story:** As an operator, I want periodic feedback while the stack operation runs, so that I
know the deployment is progressing rather than hung.

#### Acceptance Criteria

1. WHEN the change set is executed THEN `deploy.py` SHALL wait for completion using a manual polling
   loop (modeled on `delete.py`'s `delete_stack`) rather than a silent boto3 waiter.
2. On each polling cycle, `deploy.py` SHALL print the current `StackStatus` in green.
3. The polling loop SHALL use a 10-second interval and a 30-minute cap (consistent with `delete.py`).
4. WHEN the wait exceeds the 30-minute cap THEN `deploy.py` SHALL report a timeout and return a
   non-zero exit code.
5. WHEN the user interrupts the wait (`KeyboardInterrupt`) THEN `deploy.py` SHALL print a cancellation
   message and exit with a non-zero status, matching `delete.py`'s handling.
6. The change set **creation** wait SHALL remain on the existing `change_set_create_complete` waiter;
   only a brief "Creating change set..." style line is required for that phase (no per-interval
   progress output).

### Requirement 7: Success banner and Outputs listing

**User Story:** As an operator, I want a clear success indication and the stack Outputs at the end of
a deployment, matching what SAM deploy shows.

#### Acceptance Criteria

1. WHEN the stack operation completes successfully THEN `deploy.py` SHALL display a final success
   banner in green, consistent with the banner/success style used by the other CLI scripts.
2. WHEN the stack operation completes successfully AND the stack has Outputs THEN `deploy.py` SHALL
   list the stack Outputs (loosely resembling SAM deploy's Outputs display).
3. WHEN the stack has no Outputs THEN `deploy.py` SHALL omit the Outputs listing (no empty section).
4. The success banner and Outputs listing SHALL only appear on a successful (exit code 0) deployment.

### Requirement 8: Failure event reporting

**User Story:** As an operator, I want to see why a deployment failed, so that I can diagnose it.

#### Acceptance Criteria

1. WHEN the stack operation fails THEN `deploy.py` SHALL print up to 10 FAILED stack events (existing
   behavior), styled with `Colorize.error`.
2. WHEN the stack operation fails THEN `deploy.py` SHALL return a non-zero exit code.
3. The failure reporting behavior SHALL NOT be expanded beyond the current up-to-10-events listing.

### Requirement 9: SAM branch preservation

**User Story:** As a maintainer, I want the SAM deployment path to remain exactly as it is, so that
existing SAM-based deployments are unaffected.

#### Acceptance Criteria

1. The SAM branch (`_run_sam_deploy`) and its output SHALL remain unchanged by this feature.
2. All new formatting, confirmation, progress, banner, and Outputs behavior SHALL be confined to the
   CFN branch (`_cfn_deploy_packaged`) and its direct helpers.

### Requirement 10: Versioning

**User Story:** As a maintainer, I want the script version to reflect this change per the repo's
versioning rule.

#### Acceptance Criteria

1. `deploy.py`'s `VERSION` marker SHALL be reviewed as part of this change.
2. GIVEN `deploy.py` currently reads `v0.2.0/2026-08-06` AND the effective work date is 2026-08-06
   THEN the version SHALL remain `v0.2.0/2026-08-06` (already bumped today per the versioning rule).
3. IF the effective work date differs from `2026-08-06` THEN the version SHALL be bumped MINOR to
   `v0.3.0/<work date>` (this feature adds backward-compatible behavior).
4. WHEN this spec's task list is completed THEN `CHANGELOG.md` SHALL be updated under the
   `v0.0.19 (unreleased)` section referencing this spec.
