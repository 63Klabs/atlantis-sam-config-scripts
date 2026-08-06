# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - CF Short-Form Tags with S3 Include Misrouting
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate `yaml.safe_load` raises `ConstructorError` for short-form CF tags, causing `_has_s3_includes()` to incorrectly return `False`
  - **Scoped PBT Approach**: Scope to the concrete failing case — a template with `!Sub` + `Fn::Transform: AWS::Include` with an S3 `Location`
  - Add `S3_INCLUDE_TEMPLATE_WITH_CF_TAGS` and `NO_INCLUDE_TEMPLATE_WITH_CF_TAGS` template string constants to `tests/test_deploy_s3_includes.py` (see sample strings in spec prompt)
  - Add integration test file `tests/test_deploy_s3_include_flow.py` (scaffold only — test body written in this step)
  - In `TestHasS3Includes`, add `test_cf_tags_with_s3_include_returns_true`: write a tmp file from `S3_INCLUDE_TEMPLATE_WITH_CF_TAGS` and assert `_has_s3_includes()` returns `True`
  - Run the new test on the UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_deploy_s3_includes.py::TestHasS3Includes::test_cf_tags_with_s3_include_returns_true -v`
  - **EXPECTED OUTCOME**: Test FAILS (confirms bug — `_has_s3_includes()` returns `False` because `yaml.safe_load` raises `ConstructorError` for `!Sub`)
  - Document the counterexample: `_has_s3_includes(<template with !Sub + S3 include>)` returns `False` instead of `True`
  - Mark task complete when test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Bug-Condition Inputs Produce Identical Results
  - **IMPORTANT**: Follow observation-first methodology — run the UNFIXED code first
  - Observe on UNFIXED code: `_has_s3_includes(<plain S3 include, no CF tags>)` returns `True` (requirement 3.1)
  - Observe on UNFIXED code: `_has_s3_includes(<no Fn::Transform>)` returns `False` (requirement 3.2)
  - Observe on UNFIXED code: `_has_s3_includes(<binary garbage>)` returns `False` with warning (requirement 3.3)
  - Observe on UNFIXED code: `_prepare_template_with_s3_includes(<plain YAML, no CF tags>)` rewrites S3 URLs correctly (requirement 3.4)
  - In `TestHasS3Includes`, add `test_cf_tags_without_s3_include_returns_false`: write a tmp file from `NO_INCLUDE_TEMPLATE_WITH_CF_TAGS` (has `!Sub`/`!Ref`, no S3 include) and assert `_has_s3_includes()` returns `False` — this case is handled by the outer exception handler on unfixed code (fail-open), so it incidentally returns `False` (matching the expected result, but for wrong reasons)
  - Write property-based test in `tests/test_deploy_s3_include_flow.py` using Hypothesis: generate YAML templates without CF short-form tags but with S3 `AWS::Include` entries and assert `_has_s3_includes()` returns `True` for all such inputs
  - Run preservation tests on UNFIXED code: `source .ve/bin/activate && python -m pytest tests/test_deploy_s3_includes.py::TestHasS3Includes::test_cf_tags_without_s3_include_returns_false -v`
  - **EXPECTED OUTCOME**: Preservation tests PASS on unfixed code (establishes baseline for non-bug-condition inputs)
  - Mark task complete when tests are written, run, and confirmed passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix: add `_CfnLoader` and update call sites in `deploy.py`

  - [x] 3.1 Add `_CfnLoader` class and `_cfn_tag_constructor` function at module level
    - Open `cli/deploy.py`
    - Immediately after the `import yaml` line, add the `_CfnLoader` class (a `yaml.SafeLoader` subclass — see design.md "Fix Implementation" section for exact code)
    - Add the `_cfn_tag_constructor` module-level function that dispatches on `yaml.ScalarNode`, `yaml.SequenceNode`, and `yaml.MappingNode`
    - Add the registration line: `_CfnLoader.add_multi_constructor('', _cfn_tag_constructor)`
    - Verify placement: `_CfnLoader` class → `_cfn_tag_constructor` function → `_CfnLoader.add_multi_constructor(...)` call — all three appear before `from pathlib import Path`
    - _Bug_Condition: isBugCondition(X) — X contains CF short-form tags (e.g., `!Sub`) AND S3 `Fn::Transform: AWS::Include`_
    - _Expected_Behavior: `_CfnLoader` treats every unknown YAML tag as a plain Python scalar/list/dict so parsing succeeds_
    - _Requirements: 2.1, 2.3_

  - [x] 3.2 Update `_has_s3_includes()` to use `_CfnLoader`
    - In `TemplateDeployer._has_s3_includes()`, replace `yaml.safe_load(content)` with `yaml.load(content, Loader=_CfnLoader)` inside the existing `try` block (see design.md "Specific Changes" item 2)
    - The `except yaml.YAMLError` fallback to `json.loads(content)` remains — this preserves JSON template support and the fail-open behaviour for truly unparseable files (requirement 3.3)
    - Confirm no other changes are made to `_has_s3_includes()`
    - _Bug_Condition: isBugCondition(X) — yaml.safe_load raises ConstructorError for CF tags_
    - _Expected_Behavior: yaml.load with _CfnLoader parses successfully; find_s3_includes() returns True_
    - _Preservation: plain YAML/JSON templates continue to work; binary garbage still returns False + warning_
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3_

  - [x] 3.3 Update `_prepare_template_with_s3_includes()` to use `_CfnLoader`
    - In `TemplateDeployer._prepare_template_with_s3_includes()`, replace `yaml.safe_load(f)` with `yaml.load(f, Loader=_CfnLoader)` inside the `with open(template_path, 'r') as f:` block (see design.md "Specific Changes" item 3)
    - Confirm `yaml.dump` at the end of the method is NOT changed — it sees only plain Python values constructed by `_CfnLoader` and remains valid (requirement 3.5)
    - _Bug_Condition: isBugCondition(X) — yaml.safe_load raises ConstructorError before process_includes() is reached_
    - _Expected_Behavior: yaml.load with _CfnLoader parses the template; process_includes() rewrites all S3 Location values to local relative paths; template-rewritten.yml is written_
    - _Preservation: plain YAML templates (no CF tags) still rewritten identically; yaml.dump output still valid YAML_
    - _Requirements: 2.3, 3.4, 3.5_

  - [x] 3.4 Verify bug condition exploration test (Property 1) now passes
    - **Property 1: Expected Behavior** - CF Short-Form Tags with S3 Include Correctly Detected
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - Run: `source .ve/bin/activate && python -m pytest tests/test_deploy_s3_includes.py::TestHasS3Includes::test_cf_tags_with_s3_include_returns_true -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms `_has_s3_includes()` now returns `True` for CF-tag templates with S3 includes)
    - _Requirements: 2.1, 2.2_

  - [x] 3.5 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Bug-Condition Inputs Unaffected
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run: `source .ve/bin/activate && python -m pytest tests/test_deploy_s3_includes.py -v`
    - **EXPECTED OUTCOME**: All previously-passing tests still PASS (no regressions in plain YAML, JSON, local-only, or binary-garbage handling)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Add fix-checking and preservation unit tests (post-fix)

  - [x] 4.1 Add `test_cf_tags_with_s3_include_returns_true` to `TestHasS3Includes`
    - This test should already exist from task 1; confirm it is in `tests/test_deploy_s3_includes.py` under `TestHasS3Includes`
    - Template string used: `S3_INCLUDE_TEMPLATE_WITH_CF_TAGS` (has `!Sub` in `BucketName` + `Fn::Transform: AWS::Include` with S3 Location)
    - Assert `self.deployer._has_s3_includes(tmpl) is True`
    - _Requirements: 2.1_

  - [x] 4.2 Add `test_cf_tags_without_s3_include_returns_false` to `TestHasS3Includes`
    - This test should already exist from task 2; confirm it is in `tests/test_deploy_s3_includes.py` under `TestHasS3Includes`
    - Template string used: `NO_INCLUDE_TEMPLATE_WITH_CF_TAGS` (has `!Sub`/`!Ref` tags, no S3 `AWS::Include`)
    - Assert `self.deployer._has_s3_includes(tmpl) is False`
    - _Requirements: 3.2_

  - [x] 4.3 Add `test_cf_tags_with_s3_include_rewritten_has_no_s3_urls` to `TestPrepareTemplateWithS3Includes`
    - Add the test to `TestPrepareTemplateWithS3Includes` in `tests/test_deploy_s3_includes.py`
    - Write a tmp file from `S3_INCLUDE_TEMPLATE_WITH_CF_TAGS`
    - Patch `_download_s3_module` with `fake_download` (same helper pattern as existing tests in the class)
    - Patch `_read_parameter_overrides` to return `{}`
    - Patch `deploy.ConsoleAndLog`
    - Call `self.deployer._prepare_template_with_s3_includes(tmpl, tmp_path)`
    - Assert the rewritten template exists and its content contains no `s3://` URLs
    - _Requirements: 2.3_

  - [x] 4.4 Add end-to-end routing integration test to `tests/test_deploy_s3_include_flow.py`
    - Create `tests/test_deploy_s3_include_flow.py` (if not already created in task 1)
    - Add `TestDeployS3IncludeFlow` class
    - Add `test_cf_tags_with_s3_include_routes_to_sam_package_and_deploy`:
      - Write `S3_INCLUDE_TEMPLATE_WITH_CF_TAGS` to a tmp file
      - Patch `TemplateDeployer._prepare_template_with_s3_includes` to return a mock rewritten path
      - Patch `TemplateDeployer._read_artifact_bucket_config` to return `('test-bucket', 'test-prefix')`
      - Patch `TemplateDeployer._run_sam_package` to return `0`
      - Patch `TemplateDeployer._run_sam_deploy` to return `0`
      - Patch `deploy.ConsoleAndLog`
      - Call `deployer._has_s3_includes(tmp_template)` directly — assert it returns `True`
      - Confirm that `_prepare_template_with_s3_includes` would be the path taken (routing logic validated via `_has_s3_includes` returning `True`)
    - _Requirements: 2.1, 2.2_

  - [x] 4.5 Run the full test suite to confirm all new and existing tests pass
    - Run: `source .ve/bin/activate && python -m pytest tests/ -v`
    - **EXPECTED OUTCOME**: All tests pass, including the four new tests and all pre-existing tests
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 5. Update CHANGELOG.md
  - Open `CHANGELOG.md`
  - Locate the `## v0.0.19 (unreleased)` section
  - Add the following entry (create the section if it does not already exist):

    ```markdown
    ### Fixed
    - **Script: deploy.py v0.2.0** - Fixed YAML parsing failure for CloudFormation templates using short-form intrinsic tags [Spec: 0-0-19-yaml-cfn-tag-parsing-fix](.kiro/specs/0-0-19-yaml-cfn-tag-parsing-fix/)
      - Added module-level `_CfnLoader` (PyYAML `SafeLoader` subclass with catch-all multi-constructor) to handle `!Sub`, `!Ref`, `!If`, `!GetAtt`, and all other CloudFormation short-form YAML tags
      - `_has_s3_includes()` now correctly detects S3 includes in templates that mix short-form tags with `Fn::Transform: AWS::Include`
      - `_prepare_template_with_s3_includes()` now parses CF templates with short-form tags without raising `ConstructorError`
      - Templates with S3 includes now correctly route through `sam package + sam deploy` instead of failing silently on direct `sam deploy`
    ```

  - _Requirements: 2.1, 2.2, 2.3_

- [x] 6. Checkpoint — ensure all tests pass
  - Run the full test suite one final time: `source .ve/bin/activate && python -m pytest tests/ -v`
  - Confirm all tests pass with no failures or errors
  - Confirm `cli/deploy.py` has no syntax errors: `source .ve/bin/activate && python -c "import sys; sys.path.insert(0, 'cli'); import deploy"`
  - Confirm `CHANGELOG.md` contains the `v0.0.19` Fixed entry
  - Ask the user if any questions arise before marking complete
