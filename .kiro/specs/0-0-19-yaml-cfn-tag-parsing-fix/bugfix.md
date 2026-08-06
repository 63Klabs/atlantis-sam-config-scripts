# Bugfix Requirements Document

## Introduction

CloudFormation templates that use short-form YAML intrinsic functions (e.g., `!Sub`, `!Ref`, `!If`) cause
`_has_s3_includes()` and `_prepare_template_with_s3_includes()` in `deploy.py` to silently fail when
parsing. PyYAML's `yaml.safe_load` does not recognize CloudFormation-specific YAML tags and raises a
`yaml.constructor.ConstructorError`. The JSON fallback then also fails because the content is YAML, not
JSON, producing an `Expecting value: line 1 column 1 (char 0)` error caught by the outer handler. The
result is that `_has_s3_includes()` returns `False` (fail-open), deployment proceeds down the direct
`sam deploy` path instead of the required `sam package + sam deploy` path, and SAM fails at runtime when
it cannot resolve the S3 include reference.

**Bug condition C(X):** A valid CloudFormation YAML template that (a) uses one or more short-form
intrinsic function tags (`!Sub`, `!Ref`, `!If`, `!Select`, `!GetAtt`, `!ImportValue`, `!Split`, `!Join`,
`!Equals`, `!And`, `!Or`, `!Not`, `!Condition`, `!FindInMap`, `!Base64`, `!Cidr`) AND (b) contains at
least one `Fn::Transform: AWS::Include` with an S3 `Location` value.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `_has_s3_includes()` is called with a CloudFormation YAML template that uses short-form
intrinsic function tags (e.g., `!Sub`, `!Ref`) AND contains an `Fn::Transform: AWS::Include` with an S3
`Location`, THEN the system raises `yaml.constructor.ConstructorError` during `yaml.safe_load`, silently
falls through to the `json.loads` fallback, which also fails, and returns `False`

1.2 WHEN `_has_s3_includes()` returns `False` for a template that actually contains S3 includes, THEN
the system routes deployment through the direct `sam deploy` path instead of the `sam package + sam
deploy` path

1.3 WHEN `_prepare_template_with_s3_includes()` is called with a CloudFormation YAML template that uses
short-form intrinsic function tags, THEN the system raises `yaml.constructor.ConstructorError` during
`yaml.safe_load`, causing the prepare step to fail with an unhandled exception

### Expected Behavior (Correct)

2.1 WHEN `_has_s3_includes()` is called with a CloudFormation YAML template that uses short-form
intrinsic function tags AND contains an `Fn::Transform: AWS::Include` with an S3 `Location`, THEN the
system SHALL parse the template successfully by treating unknown YAML tags as plain Python values and
return `True`

2.2 WHEN `_has_s3_includes()` returns `True` for a template with S3 includes, THEN the system SHALL
route deployment through the `sam package + sam deploy` path

2.3 WHEN `_prepare_template_with_s3_includes()` is called with a CloudFormation YAML template that uses
short-form intrinsic function tags, THEN the system SHALL parse the template successfully by treating
unknown YAML tags as plain Python values and proceed to rewrite S3 `Location` values to local relative
paths

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `_has_s3_includes()` is called with a valid CloudFormation YAML template that does NOT use
short-form intrinsic function tags AND contains an `Fn::Transform: AWS::Include` with an S3 `Location`,
THEN the system SHALL CONTINUE TO return `True`

3.2 WHEN `_has_s3_includes()` is called with a CloudFormation YAML template that contains no
`Fn::Transform: AWS::Include` entries with S3 locations (regardless of whether short-form tags are
present), THEN the system SHALL CONTINUE TO return `False`

3.3 WHEN `_has_s3_includes()` is called with a file that cannot be parsed as either YAML or JSON (e.g.,
binary garbage), THEN the system SHALL CONTINUE TO log a warning and return `False`

3.4 WHEN `_prepare_template_with_s3_includes()` is called with a valid CloudFormation YAML template that
does NOT use short-form intrinsic function tags, THEN the system SHALL CONTINUE TO rewrite all S3
`Location` values to local relative paths and write the rewritten template to
`temp_dir/template-rewritten.yml`

3.5 WHEN `_prepare_template_with_s3_includes()` rewrites S3 `Location` values and writes the output
template using `yaml.dump`, THEN the system SHALL CONTINUE TO produce a valid YAML file (the dump path
does not require changes)

---

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type TemplateFile
  OUTPUT: boolean

  // Returns true when the template uses any CF short-form YAML tag
  // AND contains at least one Fn::Transform: AWS::Include with an S3 Location
  RETURN containsCfShortFormTag(X) AND containsS3Include(X)
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking - CF YAML Tag Templates with S3 Includes
FOR ALL X WHERE isBugCondition(X) DO
  result_has    ← _has_s3_includes'(X)
  result_prepare ← _prepare_template_with_s3_includes'(X, temp_dir)
  ASSERT result_has = True
  ASSERT result_prepare is a valid rewritten template path with S3 locations replaced
END FOR
```

### Preservation Property

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT _has_s3_includes(X) = _has_s3_includes'(X)
  ASSERT _prepare_template_with_s3_includes(X, d) = _prepare_template_with_s3_includes'(X, d)
END FOR
```
