---
inclusion: fileMatch
fileMatchPattern: 'cli/**/*.py'
---

# CLI Script & Library Versioning

Whenever a script in `cli/` or a component in `cli/lib/` is the target of an update, its `VERSION` marker MUST be reviewed and adjusted as part of the same change. This keeps every script and library self-describing about when it last changed and at what revision.

## VERSION Marker

Each script and `lib/` component MUST declare a module-level `VERSION` constant near the top of the file, immediately after the shebang.

### Format

```
vX.X.X/YYYY-MM-DD
```

Where:
- `vX.X.X` is a [Semantic Versioning](https://semver.org/) triple (`MAJOR.MINOR.PATCH`) prefixed with a lowercase `v`
- `YYYY-MM-DD` is the date the version was last incremented (ISO 8601)
- The two parts are joined by a single forward slash `/` with no surrounding spaces

### Placement

```python
#!/usr/bin/env python3

VERSION = "v0.1.9/2026-07-24"
# Created by ...
```

- Declare `VERSION` as the first statement after the shebang line.
- Use `UPPER_SNAKE_CASE` (`VERSION`) per the global constant naming convention.
- Keep the value a single double-quoted string.

## When to Update

Any time you modify the behavior, interface, or implementation of a `cli/` script or `cli/lib/` component, evaluate the `VERSION`:

1. Read the current `VERSION` value from the file being changed.
2. Compare the embedded date to the current date.
   - **If the date does NOT match the current date:** increment the version number (see below) AND set the date to the current date.
   - **If the date already matches the current date:** leave the version number and date unchanged. The version was already bumped earlier today, so repeated edits within the same day (and within the same spec workflow) do not trigger another increment.
3. This applies per-file. Each script or component tracks its own version and date independently.

> **Note:** If a spec or prompt explicitly states a specific version to set, or explicitly states not to change the version, follow that instruction instead of the automatic rule above.

## Choosing MAJOR, MINOR, or PATCH

Follow Semantic Versioning best practices relative to the script's or component's public interface (its CLI arguments/options for scripts, and its exported functions, classes, and signatures for `lib/` components):

- **MAJOR** (`vX.0.0`) — Incompatible or breaking changes. Examples: removing or renaming a CLI option, changing a function signature in an incompatible way, removing a public function/class, or changing behavior in a way that breaks existing callers or workflows. Reset MINOR and PATCH to `0`.
- **MINOR** (`v0.X.0`) — Backward-compatible functionality. Examples: adding a new CLI option, adding a new public function/class, or extending behavior without breaking existing usage. Reset PATCH to `0`.
- **PATCH** (`v0.0.X`) — Backward-compatible fixes and internal changes. Examples: bug fixes, refactors with no interface change, logging/output tweaks, documentation, or performance improvements that don't alter the interface.

When a single change spans multiple categories, increment at the highest applicable level.

## Examples

### Bug fix on a new day (PATCH)

Current: `VERSION = "v0.1.9/2026-07-20"`, today is `2026-07-24`. A bug fix is applied.

```python
VERSION = "v0.1.10/2026-07-24"
```

### New CLI option on a new day (MINOR)

Current: `VERSION = "v0.1.10/2026-07-24"`, next work day is `2026-07-25`. A new option is added.

```python
VERSION = "v0.2.0/2026-07-25"
```

### Breaking change on a new day (MAJOR)

Current: `VERSION = "v0.2.0/2026-07-25"`, next work day is `2026-07-26`. A CLI option is removed.

```python
VERSION = "v1.0.0/2026-07-26"
```

### Second edit on the same day (no change)

Current: `VERSION = "v1.0.0/2026-07-26"`, today is still `2026-07-26`. Another edit is made to the same file.

```python
VERSION = "v1.0.0/2026-07-26"
```

The date already matches the current date, so the version and date stay as-is.

## Checklist

Before completing an update to any `cli/` script or `cli/lib/` component:

- [ ] The file has a `VERSION` constant near the top in `vX.X.X/YYYY-MM-DD` format
- [ ] The embedded date was compared to the current date
- [ ] If the date differed, the version was incremented (MAJOR/MINOR/PATCH per the change) and the date set to today
- [ ] If the date already matched today, the version was left unchanged
- [ ] Any explicit version instruction from a spec or prompt took precedence over the automatic rule
