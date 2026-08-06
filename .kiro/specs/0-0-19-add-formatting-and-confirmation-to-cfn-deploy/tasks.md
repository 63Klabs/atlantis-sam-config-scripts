# Implementation Plan: Add Formatting and Confirmation to CloudFormation Deploy

Each task is incremental and confined to the CloudFormation branch of `cli/deploy.py` (and its tests).
The SAM branch stays untouched. Complete tasks in order; run the test suite under `.ve` after coding
tasks.

- [x] 1. Add `Colorize`/`click` imports and section-heading helper
  - Add `import click` and `from lib.tools import Colorize` to `cli/deploy.py`'s import block
  - Add `TemplateDeployer._print_section_heading(self, heading)` that prints a yellow heading followed
    by a yellow `=` divider (`Colorize.output_bold(heading, fg=Colorize.WARNING)` +
    `Colorize.divider('=', fg=Colorize.WARNING)`)
  - _Requirements: R2.1, R2.2_

- [x] 2. Implement the pre-deploy values summary helper
  - Add `TemplateDeployer._print_deploy_values_summary(self, deploy_params, cfn_parameters, cfn_tags, s3_bucket_display=None)`
  - Print the `Deploying with following values` heading via `_print_section_heading`, then one
    `Colorize.output_with_value(label, value)` line per field
  - Fields: Stack name, Region, Confirm changeset, Capabilities; Role ARN only when non-empty;
    Deployment s3 bucket only when `s3_bucket_display` is provided; Parameter overrides; Tags
  - Render parameter overrides/tags as a compact `{Key: Value, ...}` string; omit Disable rollback and
    Signing Profiles
  - _Requirements: R1.1–R1.7_

- [x] 3. Implement the changeset listing helper
  - Add `TemplateDeployer._print_changeset_summary(self, changes)`
  - Print a `Changeset` heading, then one aligned line per change showing Action, LogicalResourceId,
    ResourceType, and (when present) Replacement and PhysicalResourceId
  - Loosely resemble the SAM changeset table; do not print raw JSON
  - _Requirements: R3.1–R3.4_

- [x] 4. Implement the success banner and Outputs helpers
  - Add `TemplateDeployer._print_success_banner(self)` rendering a green success banner consistent
    with other scripts (use `Colorize.success`, or `Colorize.box_output` for a boxed green banner)
  - Add `TemplateDeployer._print_stack_outputs(self, outputs)` that prints an `Outputs` heading and
    one `Colorize.output_with_value(OutputKey, OutputValue)` line per output (include Description when
    present); print nothing when `outputs` is empty
  - _Requirements: R7.1–R7.4_

- [x] 5. Implement the manual stack-operation polling loop
  - Add `TemplateDeployer._wait_for_stack_operation(self, cfn_client, stack_name, change_set_type) -> bool`
    modeled on `delete.py`'s polling loop
  - Poll `describe_stacks` every 10s (max 180 attempts / 30 min); return True on
    CREATE_COMPLETE/UPDATE_COMPLETE, False on failure statuses or timeout
  - Print current `StackStatus` in green each in-progress cycle
  - Handle `KeyboardInterrupt` with a cancellation message and `sys.exit(1)`
  - _Requirements: R6.1–R6.5_

- [x] 6. Wire the values summary into `_cfn_deploy_packaged`
  - Capture whether the template was uploaded to S3 (and the bucket) when building `template_source`
  - Call `_print_deploy_values_summary(...)` before `create_change_set`, passing the S3 bucket display
    only on the large-template path
  - Keep the brief "Creating change set..." line for the change-set creation wait (existing waiter
    unchanged)
  - _Requirements: R1.1, R1.4, R6.6_

- [x] 7. Add changeset listing + confirmation gate to `_cfn_deploy_packaged`
  - After the `change_set_create_complete` waiter succeeds, call `describe_change_set`; keep the
    existing empty-changeset no-op path (print message, delete change set, return 0, no prompt/listing)
  - When changes exist, call `_print_changeset_summary(changes)`
  - Compute `needs_confirm = bool(deploy_params.get('confirm_changeset', True)) and not self.override_confirm_changeset`
  - When `needs_confirm`, prompt with `click.confirm(Colorize.question("Deploy this change set?"), default=False)`;
    on decline, delete the change set, log/print a cancellation message, and `return 1`
  - Wrap `describe_change_set`/listing failures so they log a warning without failing a healthy deploy
  - _Requirements: R3.1, R4.1–R4.5, R5.1, R5.2_

- [x] 8. Replace the execution waiter and add banner/Outputs/failure output
  - Print the `Initiating deployment` yellow heading before `execute_change_set`
  - Replace the silent `stack_create_complete`/`stack_update_complete` waiter with
    `_wait_for_stack_operation(...)`
  - On success: call `_print_success_banner()`, read `describe_stacks(...)['Stacks'][0].get('Outputs', [])`
    and call `_print_stack_outputs(...)` when non-empty; return 0
  - On failure: keep the up-to-10 FAILED events listing, recolored with `Colorize.error`; return 1
  - Wrap the Outputs read so a failure logs a warning without changing the exit code
  - _Requirements: R6.1, R7.1–R7.4, R8.1–R8.3_

- [x] 9. Confirm the SAM branch is unchanged
  - Verify `_run_sam_deploy` and `deploy_with_temp_template` dispatch logic are untouched by the above
  - _Requirements: R9.1, R9.2_

- [x] 10. Add/update unit tests
  - In `tests/`, add tests (mocking the CloudFormation client) for: values summary field conditions;
    changeset listing rendering; confirmation gate matrix (confirm_changeset × headless, including
    decline → change set deleted + return 1); empty-changeset no-op; polling loop success/failure and
    green status output; success banner + Outputs (and no Outputs section when empty)
  - Ensure existing SAM-branch and headless tests still pass
  - Run the suite under `.ve` (`pytest`); keep any new test-only deps in `cli/requirements-test.txt`
  - _Requirements: R1–R9_

- [x] 11. Review `deploy.py` VERSION and update CHANGELOG.md
  - Review `deploy.py`'s `VERSION`: keep `v0.2.0/2026-08-06` if the work date is 2026-08-06; otherwise
    bump MINOR to `v0.3.0/<work date>`
  - Add a **Changed** entry under `v0.0.19 (unreleased)` in `CHANGELOG.md` referencing
    `[Spec: 0-0-19-add-formatting-and-confirmation-to-cfn-deploy]` and summarizing the CFN-branch
    formatting, changeset confirmation, progress output, success banner, and Outputs listing
  - _Requirements: R10.1–R10.4_
