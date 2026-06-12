---
inclusion: always
---

# Spec Directory Naming Convention

When creating new specification directories in `.kiro/specs/`, you MUST follow this naming convention:

## Format

```
{version}-{feature-name}
```

Where:
- `{version}` is the `(unreleased)` version from `CHANGELOG.md` without the leading v and dots replaced with dashes
- `{feature-name}` is a kebab-case description of the feature

## Examples

For CHANGELOG.md version `v0-9-8 (unreleased)`:
- `.kiro/specs/0-9-8-in-memory-cache/`
- `.kiro/specs/0-9-8-documentation-enhancement/`
- `.kiro/specs/0-9-8-reduce-json-stringify/`

## Process

1. Read the most recent version from `CHANGELOG.md`
2. If the version is marked as `(unreleased)` then it is the version we will work with
3. If the latest version has a date following `(YYYY-MM-DD)` then it is released and the developer hasn't yet updated.
   1. Add a new version header to CHANGELOG.md in the `vX.X.X (unreleased)` format. Use the previous version and increment patch by 1
2. For spec naming, convert the version to the hyphenated format (replace `.` with `-`)
3. Append the feature name in kebab-case
4. Create the directory: `.kiro/specs/{version}-{feature-name}/`

## Important Notes

- The version in `CHANGELOG.md` SHOULD have already been updated for the next release, but is not guaranteed. Only use version followed by `(unreleased)` or create the next version.
- Always use the CURRENT, UNRELEASED version from `CHANGELOG.md`, not a future or past version
- Feature names should be descriptive but concise
- Use kebab-case (lowercase with hyphens) for feature names
- Do NOT create spec directories without the version prefix

## Spec Document Names

Inside each spec directory, use these standard filenames:
- `requirements.md` — Requirements document
- `design.md` — Design document
- `tasks.md` — Implementation task list

## Changelog Reference

#[[file:CHANGELOG.md]]
