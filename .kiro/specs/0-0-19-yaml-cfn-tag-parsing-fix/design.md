# YAML CloudFormation Tag Parsing Fix — Bugfix Design

## Overview

CloudFormation templates that use short-form YAML intrinsic functions (`!Sub`, `!Ref`, `!If`,
`!GetAtt`, etc.) cause `deploy.py` to silently misroute deployments. PyYAML's `yaml.safe_load`
raises `ConstructorError` for any unrecognised tag. The JSON fallback then also fails because the
content is valid YAML, not JSON. The outer exception handler catches both failures and returns
`False` from `_has_s3_includes()`, routing deployment through the direct `sam deploy` path even
when S3 includes are present. SAM then fails at runtime because it cannot resolve the unprocessed
`Fn::Transform: AWS::Include` reference.

The fix introduces a module-level `_CfnLoader` class — a `yaml.SafeLoader` subclass with a
catch-all multi-constructor — that treats every unrecognised YAML tag as a plain Python value
(scalar → `str`, sequence → `list`, mapping → `dict`). Both `_has_s3_includes()` and
`_prepare_template_with_s3_includes()` are updated to use
`yaml.load(content, Loader=_CfnLoader)` instead of `yaml.safe_load`.

---

## Glossary

- **Bug_Condition (C)**: A CloudFormation YAML template that (a) uses one or more short-form
  intrinsic function tags AND (b) contains at least one `Fn::Transform: AWS::Include` with an
  S3 `Location` value.
- **Property (P)**: The desired behaviour when the bug condition holds — `_has_s3_includes()`
  returns `True` and `_prepare_template_with_s3_includes()` successfully rewrites all S3
  `Location` values to local relative paths.
- **Preservation**: The existing correct behaviour for templates that do NOT satisfy the bug
  condition — including plain YAML, JSON, templates with only local includes, and templates with
  no `Fn::Transform` entries at all.
- **`_CfnLoader`**: A `yaml.SafeLoader` subclass defined at module level in `deploy.py` that
  registers a catch-all multi-constructor (`''` prefix) via `_cfn_tag_constructor`.
- **`_cfn_tag_constructor`**: A module-level function that constructs a plain Python scalar,
  list, or dict for any YAML node regardless of its tag, discarding the tag value.
- **`isBugCondition`**: The formal predicate used in this document to identify inputs that
  trigger the defect.

---

## Bug Details

### Bug Condition

The bug manifests when `_has_s3_includes()` or `_prepare_template_with_s3_includes()` is called
with a CloudFormation YAML template that contains at least one short-form intrinsic function tag
**and** at least one `Fn::Transform: AWS::Include` whose `Location` is an S3 URL. PyYAML's
`SafeLoader` raises `yaml.constructor.ConstructorError` for unknown tags, the JSON fallback also
fails, and the outer handler swallows both exceptions — producing an incorrect `False` return
from `_has_s3_includes()`.

**Formal Specification:**

```
FUNCTION isBugCondition(X)
  INPUT:  X of type TemplateFile
  OUTPUT: boolean

  RETURN containsCfShortFormTag(X)
         AND containsS3Include(X)
END FUNCTION

-- helpers (used conceptually only)

FUNCTION containsCfShortFormTag(X)
  // True when the raw YAML text of X includes any tag from the CF short-form
  // set: !Sub !Ref !If !Select !GetAtt !ImportValue !Split !Join !Equals !And
  //      !Or !Not !Condition !FindInMap !Base64 !Cidr
  RETURN X.rawText MATCHES /![A-Za-z]+/

FUNCTION containsS3Include(X)
  // True when X, if parseable, contains Fn::Transform: {Name: AWS::Include,
  // Parameters: {Location: <S3 URL>}}
  RETURN parsedTemplate(X) CONTAINS s3IncludeNode
```

### Examples

| Template content | `_has_s3_includes()` (before fix) | `_has_s3_includes()` (after fix) |
|---|---|---|
| YAML with `!Sub` + S3 include | `False` (bug) | `True` |
| YAML with `!Ref` tags, no S3 include | `False` (correct) | `False` (correct) |
| YAML, no CF tags, S3 include | `True` (correct) | `True` (correct) |
| YAML, no CF tags, no S3 include | `False` (correct) | `False` (correct) |
| Unparseable binary content | `False` + warning (correct) | `False` + warning (correct) |

**Concrete example of the defect:**

```yaml
# template.yml — triggers the bug condition
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  Env:
    Type: String
Resources:
  MyRole:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub my-bucket-${Env}   # ← this tag breaks yaml.safe_load
```

`yaml.safe_load` raises `ConstructorError: could not determine a constructor for the tag '!Sub'`.
The JSON fallback raises `json.JSONDecodeError`. The outer handler catches both, logs a warning,
and returns `False`. The deployment skips `sam package` and calls `sam deploy` directly, which
fails at runtime with an unresolved `Fn::Transform`.

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- `_has_s3_includes()` MUST continue to return `True` for templates that use S3
  `AWS::Include` but do NOT contain short-form CF tags (requirements 3.1).
- `_has_s3_includes()` MUST continue to return `False` for any template — with or
  without short-form tags — that contains no `Fn::Transform: AWS::Include` with an
  S3 `Location` (requirements 3.2).
- `_has_s3_includes()` MUST continue to log a warning and return `False` when the
  file cannot be parsed as YAML or JSON (requirement 3.3).
- `_prepare_template_with_s3_includes()` MUST continue to rewrite all S3 `Location`
  values to local relative paths and write `template-rewritten.yml` for templates
  that do NOT use short-form tags (requirement 3.4).
- `yaml.dump` output from `_prepare_template_with_s3_includes()` MUST remain a valid
  YAML file (requirement 3.5).

**Scope:**

All inputs where `isBugCondition` is `False` — templates without short-form tags, JSON
templates, templates with only local includes, and unparseable files — must be completely
unaffected by this fix.

> **Note:** The expected correct behaviour for inputs where `isBugCondition` is `True` is
> defined in the Correctness Properties section (Property 1) below.

---

## Hypothesized Root Cause

Based on the bug description and inspection of `deploy.py`, the most likely causes are:

1. **`yaml.safe_load` rejects unknown tags**: `SafeLoader` raises
   `yaml.constructor.ConstructorError` for any tag it has not been taught to handle. CF
   short-form tags (`!Sub`, `!Ref`, etc.) are not registered in PyYAML's standard loader
   set, so every CF template using short-form syntax triggers this error.

2. **Silent fallback masks the true failure**: The `except yaml.YAMLError` clause in
   `_has_s3_includes()` immediately falls through to `json.loads`. Because the content is
   YAML, `json.loads` also raises. The outer `except Exception` handler in
   `_has_s3_includes()` catches this second exception, logs a misleading warning ("Could
   not scan template for S3 includes"), and returns `False`.

3. **Same loader used in `_prepare_template_with_s3_includes()`**: The prepare function
   calls `yaml.safe_load(f)` directly, without any fallback. A template that satisfies the
   bug condition causes an unhandled `ConstructorError` here, propagating up to
   `deploy_with_temp_template()` and returning exit code `1`.

4. **No multi-constructor registered**: PyYAML supports `add_multi_constructor(prefix,
   fn)` to handle families of unknown tags. Registering `''` (empty prefix) as a catch-all
   in a `SafeLoader` subclass is the standard approach to accept arbitrary YAML tags
   without needing to enumerate them individually.

---

## Correctness Properties

Property 1: Bug Condition — CF YAML Tag Templates with S3 Includes Are Parsed Correctly

_For any_ template file `X` where `isBugCondition(X)` is `True` (i.e., the file contains at
least one CloudFormation short-form intrinsic function tag **and** at least one
`Fn::Transform: AWS::Include` with an S3 `Location`), the fixed `_has_s3_includes(X)` SHALL
return `True`, and the fixed `_prepare_template_with_s3_includes(X, temp_dir)` SHALL parse the
template successfully, download each referenced S3 module, and return a path to a rewritten
template in which all S3 `Location` values have been replaced with local relative paths.

**Validates: Requirements 2.1, 2.2, 2.3**

---

Property 2: Preservation — Non-Bug-Condition Inputs Are Unaffected

_For any_ template file `X` where `isBugCondition(X)` is `False` (i.e., the file does not
simultaneously contain both short-form CF tags and S3 includes), the fixed
`_has_s3_includes(X)` SHALL produce exactly the same return value as the original
`_has_s3_includes(X)`, and the fixed `_prepare_template_with_s3_includes(X, temp_dir)` SHALL
produce the same rewritten template as the original, preserving all existing routing and
template-rewriting behaviour for inputs that the original code already handled correctly.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

---

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct:

**File:** `cli/deploy.py`

**Specific Changes:**

1. **Add `_CfnLoader` class at module level** (immediately after `import yaml`, before
   `from pathlib import Path`):

   ```python
   class _CfnLoader(yaml.SafeLoader):
       """SafeLoader extended to accept CloudFormation short-form YAML tags.

       PyYAML's SafeLoader raises ConstructorError for unknown tags such as
       !Sub, !Ref, !If, !GetAtt, etc. This loader registers a catch-all
       multi-constructor that treats every unknown tag as a plain Python value
       (scalar → str, sequence → list, mapping → dict). This is sufficient for
       scanning template structure without needing the resolved CF values.
       """
       pass


   def _cfn_tag_constructor(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node):
       """Construct a plain Python value for any unrecognised YAML tag.

       Args:
           loader: The active YAML loader instance.
           tag_suffix: The tag string (e.g. '!Sub', '!Ref').
           node: The YAML node being constructed.

       Returns:
           A plain Python scalar, list, or dict — the tag is discarded.
       """
       if isinstance(node, yaml.ScalarNode):
           return loader.construct_scalar(node)
       elif isinstance(node, yaml.SequenceNode):
           return loader.construct_sequence(node)
       return loader.construct_mapping(node)


   _CfnLoader.add_multi_constructor('', _cfn_tag_constructor)
   ```

2. **Update `_has_s3_includes()`** — replace `yaml.safe_load(content)` with
   `yaml.load(content, Loader=_CfnLoader)`:

   ```python
   # Before
   try:
       template = yaml.safe_load(content)
   except yaml.YAMLError:
       template = json.loads(content)

   # After
   try:
       template = yaml.load(content, Loader=_CfnLoader)
   except yaml.YAMLError:
       template = json.loads(content)
   ```

3. **Update `_prepare_template_with_s3_includes()`** — replace `yaml.safe_load(f)` with
   `yaml.load(f, Loader=_CfnLoader)`:

   ```python
   # Before
   with open(template_path, 'r') as f:
       template = yaml.safe_load(f)

   # After
   with open(template_path, 'r') as f:
       template = yaml.load(f, Loader=_CfnLoader)
   ```

4. **VERSION bump** — the current `VERSION` is `"v0.2.0/2026-08-06"`. Today is
   `2026-08-06`, which matches the embedded date, so the version is **not changed**
   (same-day rule).

5. **No other changes** — `yaml.dump` in `_prepare_template_with_s3_includes()` is not
   affected because PyYAML's `Dumper` does not need to understand CF tags; it only sees the
   plain Python values that `_CfnLoader` constructed.

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate the bug on the unfixed code; then verify the fix works correctly and that all
preservation behaviour is intact.

### Exploratory Bug Condition Checking

**Goal:** Surface counterexamples that demonstrate the bug BEFORE implementing the fix.
Confirm or refute the root cause analysis. If we refute, we need to re-hypothesise.

**Test Plan:** Write tests that call `_has_s3_includes()` and
`_prepare_template_with_s3_includes()` with templates containing short-form CF tags plus S3
includes. Run these tests against the UNFIXED code to observe failures and understand the
root cause.

**Test Cases:**

1. **`_has_s3_includes` with `!Sub` and S3 include** — expects `True`; will fail on unfixed
   code (returns `False` after both YAML and JSON parse fail).
2. **`_has_s3_includes` with `!Ref` and no S3 include** — expects `False`; should return
   `False` on unfixed code but for the wrong reason (parse failure rather than no include).
3. **`_prepare_template_with_s3_includes` with `!Sub` and S3 include** — expects rewritten
   template with no S3 URLs; will fail on unfixed code with `ConstructorError`.

**Expected Counterexamples:**

- `_has_s3_includes()` returns `False` for a template that has both CF tags and S3 includes.
- Possible causes: `yaml.safe_load` raises `ConstructorError`; JSON fallback raises
  `JSONDecodeError`; outer handler swallows both and returns `False`.

### Fix Checking

**Goal:** Verify that for all inputs where the bug condition holds, the fixed function
produces the expected behaviour.

**Pseudocode:**

```
FOR ALL X WHERE isBugCondition(X) DO
  result_has     := _has_s3_includes_fixed(X)
  result_prepare := _prepare_template_with_s3_includes_fixed(X, temp_dir)
  ASSERT result_has = True
  ASSERT result_prepare is a valid Path with no S3 URLs in Location fields
END FOR
```

### Preservation Checking

**Goal:** Verify that for all inputs where the bug condition does NOT hold, the fixed
functions produce the same result as the originals.

**Pseudocode:**

```
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT _has_s3_includes_original(X) = _has_s3_includes_fixed(X)
  ASSERT _prepare_template_with_s3_includes_original(X, d)
       = _prepare_template_with_s3_includes_fixed(X, d)
END FOR
```

**Testing Approach:** Property-based testing is recommended for preservation checking
because:

- It generates many template variations automatically across the input domain.
- It catches edge cases (unusual structure, missing sections, empty resources) that manual
  tests might miss.
- It provides strong guarantees that non-bug-condition behaviour is unchanged for all
  variant inputs.

**Test Plan:** Observe behaviour on UNFIXED code for templates without CF tags, then write
property-based tests capturing that baseline.

**Test Cases:**

1. **Plain YAML S3 include preservation** — template with S3 include but no CF tags still
   returns `True`.
2. **Plain YAML no-include preservation** — template with no `Fn::Transform` but no CF tags
   still returns `False`.
3. **`!Ref` tags with no S3 include preservation** — template with only CF tags (no S3
   include) returns `False`.
4. **Rewrite preservation** — `_prepare_template_with_s3_includes` on a plain template
   (no CF tags) still rewrites S3 URLs to local paths and writes `template-rewritten.yml`.

### Unit Tests

New test cases to add to `tests/test_deploy_s3_includes.py`:

**`TestHasS3Includes`:**

- `test_cf_tags_with_s3_include_returns_true` — template using `!Sub` + S3 include → `True`
  (fix checking, Property 1).
- `test_cf_tags_without_s3_include_returns_false` — template using `!Ref` tags, no S3
  include → `False` (preservation, Property 2).

**`TestPrepareTemplateWithS3Includes`:**

- `test_cf_tags_with_s3_include_rewritten_has_no_s3_urls` — template using `!Sub` + S3
  include is processed; rewritten template contains no S3 URLs (fix checking, Property 1).

### Property-Based Tests

- Generate YAML templates with random combinations of CF short-form tags and `Fn::Transform`
  entries; verify `_has_s3_includes` returns `True` iff at least one entry has an S3
  `Location`.
- Generate YAML templates without CF tags; verify `_has_s3_includes` returns the same value
  for both original and fixed code (preservation of Property 2).
- Generate template structures with multiple `Fn::Transform: AWS::Include` entries (some S3,
  some local) and verify only S3 entries are rewritten.

### Integration Tests

- Full deployment flow test with a YAML template that uses `!Sub` in `BucketName` plus an
  S3 `AWS::Include` — verify the `sam package + sam deploy` path is taken.
- Context-switching test — verify that switching between templates with and without CF tags
  does not affect routing decisions.
- Visual/log output test — verify that the "S3 includes detected" log message is emitted
  for CF-tag templates that contain S3 includes.
