# Requirements: YAML CloudFormation Tag Parsing Fix

## Introduction

`deploy.py` silently misroutes deployments when a CloudFormation YAML template uses
short-form intrinsic function tags (`!Sub`, `!Ref`, `!If`, etc.) together with an
`Fn::Transform: AWS::Include` whose `Location` is an S3 URL.

PyYAML's `yaml.safe_load` raises `yaml.constructor.ConstructorError` for any tag it
does not recognise. The JSON fallback also fails because the content is YAML, not
JSON. The outer exception handler swallows both failures, logs a misleading warning,
and returns `False` from `_has_s3_includes()`. Deployment then proceeds down the
direct `sam deploy` path instead of the required `sam package + sam deploy` path, and
SAM fails at runtime because it cannot resolve the unprocessed `Fn::Transform:
AWS::Include` reference.

**Bug condition C(X):** A valid CloudFormation YAML template that (a) uses one or
more short-form intrinsic function tags (`!Sub`, `!Ref`, `!If`, `!Select`, `!GetAtt`,
`!ImportValue`, `!Split`, `!Join`, `!Equals`, `!And`, `!Or`, `!Not`, `!Condition`,
`!FindInMap`, `!Base64`, `!Cidr`) AND (b) contains at least one
`Fn::Transform: AWS::Include` with an S3 `Location` value.

The fix introduces a module-level `_CfnLoader` — a `yaml.SafeLoader` subclass with a
catch-all multi-constructor — so that both `_has_s3_includes()` and
`_prepare_template_with_s3_includes()` can parse CF YAML templates successfully
without enumerating every possible tag.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `_has_s3_includes()` is called with a CloudFormation YAML template that uses
any short-form intrinsic function tag (`!Sub`, `!Ref`, `!If`, `!Select`, `!GetAtt`,
`!ImportValue`, `!Split`, `!Join`, `!Equals`, `!And`, `!Or`, `!Not`, `!Condition`,
`!FindInMap`, `!Base64`, `!Cidr`) AND the template contains at least one
`Fn::Transform: AWS::Include` with an S3 `Location`, THEN the system raises
`yaml.constructor.ConstructorError` during `yaml.safe_load`, falls through to the
`json.loads` fallback (which also fails), and returns `False`

1.2 WHEN `_has_s3_includes()` returns `False` for a template that actually contains
S3 includes (due to the parse failure described in 1.1), THEN the system routes
deployment through the direct `sam deploy` path instead of the required
`sam package + sam deploy` path

1.3 WHEN `_prepare_template_with_s3_includes()` is called with a CloudFormation YAML
template that uses short-form intrinsic function tags, THEN the system raises
`yaml.constructor.ConstructorError` during `yaml.safe_load`, causing the prepare step
to fail with an unhandled exception

### Expected Behavior (Correct)

2.1 WHEN `_has_s3_includes()` is called with a CloudFormation YAML template that uses
short-form intrinsic function tags AND the template contains at least one
`Fn::Transform: AWS::Include` with an S3 `Location`, THEN the system SHALL parse the
template successfully — treating unknown YAML tags as plain Python values via a
module-level `_CfnLoader` (`yaml.SafeLoader` subclass with catch-all
multi-constructor) — and return `True`

2.2 WHEN `_has_s3_includes()` returns `True` for a template with S3 includes
(including templates that use short-form CF tags), THEN the system SHALL route
deployment through the `sam package + sam deploy` path

2.3 WHEN `_prepare_template_with_s3_includes()` is called with a CloudFormation YAML
template that uses short-form intrinsic function tags AND contains S3 include
references, THEN the system SHALL parse the template successfully using `_CfnLoader`,
resolve all S3 `Location` values to local relative paths, and write the rewritten
template to `temp_dir/template-rewritten.yml`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `_has_s3_includes()` is called with a valid CloudFormation YAML template
that does NOT use short-form intrinsic function tags AND the template contains at
least one `Fn::Transform: AWS::Include` with an S3 `Location`, THEN the system SHALL
CONTINUE TO parse the template successfully and return `True`

3.2 WHEN `_has_s3_includes()` is called with a CloudFormation YAML template that
contains no `Fn::Transform: AWS::Include` entries with S3 locations (regardless of
whether short-form tags are present), THEN the system SHALL CONTINUE TO return `False`

3.3 WHEN `_has_s3_includes()` is called with a file that cannot be parsed as either
YAML or JSON (e.g., binary garbage, invalid UTF-8), THEN the system SHALL CONTINUE TO
log a warning and return `False` (fail-open behaviour)

3.4 WHEN `_prepare_template_with_s3_includes()` is called with a valid CloudFormation
YAML template that does NOT use short-form intrinsic function tags, THEN the system
SHALL CONTINUE TO rewrite all S3 `Location` values to local relative paths and write
the rewritten template to `temp_dir/template-rewritten.yml`

3.5 WHEN `_prepare_template_with_s3_includes()` writes the output template using
`yaml.dump`, THEN the system SHALL CONTINUE TO produce a valid YAML file (the dump
path is not changed by this fix)

---

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT:  X of type TemplateFile
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
  result_has     ← _has_s3_includes'(X)
  result_prepare ← _prepare_template_with_s3_includes'(X, temp_dir)
  ASSERT result_has = True
  ASSERT result_prepare is a valid rewritten template path
         with all S3 Location values replaced by local relative paths
END FOR
```

### Preservation Property

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT _has_s3_includes(X) = _has_s3_includes'(X)
  ASSERT _prepare_template_with_s3_includes(X, d)
       = _prepare_template_with_s3_includes'(X, d)
END FOR
```
