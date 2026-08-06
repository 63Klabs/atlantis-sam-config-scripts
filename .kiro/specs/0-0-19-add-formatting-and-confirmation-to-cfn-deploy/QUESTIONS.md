# Clarifying Questions & Recommendations

Spec: **Add Formatting and Confirmation to CloudFormation Deploy**

Please answer inline under each question (add your answer after the `**Answer:**` marker). Once answered, I'll turn this into `requirements.md` and continue the spec workflow.

---

## Context I gathered (for reference)

- `deploy.py` has two branches in `deploy_with_temp_template()`:
  - **SAM branch** (`_run_sam_deploy`) — used when the template has **no** S3 `AWS::Include`. It shells out to `sam deploy`, and the "Deploying with following values" table plus changeset confirmation are **printed by the SAM CLI itself**, not by our script.
  - **CloudFormation branch** (`_cfn_deploy_packaged`) — used when the template **has** S3 includes. It drives a boto3 change set directly. Today it:
    - prints only `ConsoleAndLog.info/error` lines (no color, no values table),
    - **never** lists the changeset changes,
    - **never** honors `confirm_changeset` (it always auto-executes; even though `_read_deploy_params_for_packaged` reads the value, `_cfn_deploy_packaged` ignores it),
    - waits **silently** on boto3 waiters (`change_set_create_complete`, then `stack_create/update_complete`) with no periodic progress output.
- `deploy.py` currently uses `ConsoleAndLog` (from `lib.logger`) and does **not** import `Colorize`. `delete.py` and `config.py` do use `Colorize` (from `lib.tools`), which reads color constants from `tools_colors.py` (yellow = `OUTPUT_VALUE`, green = `OUTPUT`/`SUCCESS`).
- `delete.py`'s `delete_stack()` is the reference "interval progress" pattern: a manual `describe_stacks` polling loop with `time.sleep(10)` that echoes status each cycle and handles `KeyboardInterrupt`.

---

## Deploy Values summary

**Q1.** The SAM branch's values table is emitted by the SAM CLI. For the CFN branch I'll generate an equivalent table myself. Which fields do you want listed? SAM's native list shows: Stack name, Region, Confirm changeset, Disable rollback, Deployment s3 bucket, Capabilities, Parameter overrides, Signing Profiles. My recommendation is to mirror the ones we actually have values for and drop ones that don't apply to our boto3 path.

- **Recommendation:** Show `Stack name`, `Region`, `Confirm changeset`, `Capabilities`, `Role ARN` (only if set), `Parameter overrides`, and `Tags`. Omit `Disable rollback` and `Signing Profiles` (we don't set them), and show `Deployment s3 bucket` only when we actually upload the template to S3 (large-template path).
- **Answer:** Yes, use recommendation

**Q2.** For color, do you want me to introduce `Colorize` into `deploy.py` (matching `delete.py`/`config.py`) for the headings/dividers/values? The spec says headings and `=====` dividers should be yellow.

- **Recommendation:** Use `Colorize`. Render the `Deploying with following values` / `Initiating deployment` headings and the `=====` dividers with a yellow style, and render each value line with `Colorize.output_with_value()` (green label + yellow value). This matches the rest of the CLI. Note: SAM uses `=` dividers under yellow headings; I'll replicate that look rather than the CLI's usual `-` divider. Is that acceptable?
- **Answer:** Yes, go with the recommendation including the divider

**Q3.** Should this values summary print **only** in the CFN branch (leaving the SAM branch's native SAM output untouched, per "SAM Branch should remain the same"), or would you also like our own summary in the SAM branch?

- **Recommendation:** CFN branch only. Leave the SAM branch completely unchanged.
- **Answer:** Use recommendation.

---

## Changeset listing & confirmation

**Q4.** After the change set is created, I'll call `describe_change_set` and list the changes. How much detail do you want per change?

- **Recommendation:** For each entry in `Changes[]`, show Action (Add/Modify/Remove), Logical ID, Resource Type, and (when present) the Replacement flag and Physical ID. Group/format to loosely resemble SAM's changeset table. Full raw JSON only if you want it.
- **Answer:** Use recommendation, but we don't need full JSON output. Just loosely resemble SAM's changeset

**Q5.** Confirmation gating. The spec says prompt the user when `confirm_changeset = true` and not headless. Today headless sets `override_confirm_changeset = True`.

- **Recommendation:** Prompt for `[y/N]` confirmation when `confirm_changeset` is true AND `override_confirm_changeset` is false (i.e. not headless). If the user declines, delete the (unexecuted) change set and exit without deploying (return non-zero? or zero?). See Q6. When `confirm_changeset` is false OR headless, skip the prompt and auto-execute — matching the SAM branch semantics.
- **Answer:** Yes, follow recommendation. Exit with non zero so as to skip any future branching we may add. Yes, when confirm_changeset is false or headless, skip prompt

**Q6.** When the user declines the changeset, what exit code should the script return? This affects whether `main()` then runs the git commit/push and termination-protection steps.

- **Recommendation:** Treat a decline as a user-cancelled, non-error outcome: delete the pending change set, print a cancellation message, and return a non-zero code so the post-deploy git commit/push is skipped. (Alternatively return 0 but explicitly skip the commit — I lean toward non-zero to keep `main()` simple.)
- **Answer:** yes, use recommendation

**Q7.** If the changeset is empty (no changes), current behavior logs "No changes to deploy" and returns 0. Keep that as-is (skip the confirmation prompt entirely for empty changesets)?

- **Recommendation:** Yes. If there are no changes, print the no-op message and return 0 without prompting.
- **Answer:** yes, follow recommendation

---

## Progress output

**Q8.** The spec suggests CloudFormation events on ~10s intervals, or tail, or fallback to "Waiting for stack update to complete..." lines in green. How much progress detail do you want during the stack execution wait?

- **Recommendation:** Replace the silent boto3 waiter with a `delete.py`-style manual polling loop (`describe_stacks` every ~10s). Each cycle, print the current `StackStatus` in green (more useful than a static "waiting" line, and low effort). Optionally, also surface newly-seen `describe_stack_events` resource statuses since the last poll for a near-"tail" experience.
- **Answer (pick one):**
  - [ ] A. Simple: print a green "Waiting for stack update to complete..." line each interval.
  - [x] B. Status: print the current `StackStatus` each interval (my recommendation).
  - [ ] C. Tail: print new stack resource events each interval (closest to SAM, more code).

**Q9.** Poll interval and timeout. `delete.py` uses 10s over 180 attempts (30 min). The current deploy waiter effectively allows 30 min (15s × 120). What do you want?

- **Recommendation:** 10s interval, 30-minute cap, consistent with `delete.py`. Handle `KeyboardInterrupt` the same way `delete.py` does (message + `sys.exit(1)`).
- **Answer:** yes, use recommendation

**Q10.** Should the change-set *creation* wait (currently a silent `change_set_create_complete` waiter, ~5 min cap) also get progress output, or is only the stack-execution wait in scope?

- **Recommendation:** Keep changeset creation on the existing waiter (it's usually quick); add progress output only to the stack execution wait. A brief "Creating change set..." line is enough.
- **Answer:** yes, use recommendation

---

## Scope, versioning, and edge cases

**Q11.** On stack-operation failure, current code prints up to 10 FAILED events via `ConsoleAndLog.error`. Keep that behavior (just recolored), or expand it?

- **Recommendation:** Keep it, styled with `Colorize.error`. No expansion unless you want it.
- **Answer:** Yes, keep that behavior, no need to expand

**Q12.** Versioning: this change adds behavior to `deploy.py` (backward-compatible), so per the versioning rule it's a MINOR bump. `deploy.py` is currently `v0.2.0/2026-08-06` — today's date. The rule says if the embedded date already matches today, leave it unchanged.

- **Recommendation:** Since the current date shown to me is 2026-08-06 and the file already reads `v0.2.0/2026-08-06`, I'd leave `deploy.py` at `v0.2.0/2026-08-06` (already bumped today). If you're actually working on a later date, I'll bump to `v0.3.0/<that date>`. Please confirm the effective work date / desired version.
- **Answer:** keep it at today's date

**Q13.** Any interest in factoring the shared "poll a stack operation and print progress" logic into a reusable helper (e.g. in `cli/lib/`) so `deploy.py` and `delete.py` share it, or keep it inline in `deploy.py` for this spec?

- **Recommendation:** Keep it inline in `deploy.py` for this spec to limit blast radius; note a possible future refactor. (`delete.py` stays untouched.)
- **Answer:** use recommendation

---

## Anything else?

**Q14.** Any other formatting/UX parity goals with the SAM branch I haven't captured (e.g. an "Initiating deployment" banner before execution, a final success banner, elapsed-time display)?

- **Answer:** Yes, we can have a final success banner in Green, similar to other scripts. Also we should list any Outputs, similar to what SAM deploy does.
