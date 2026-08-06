# Implementation Tasks

**Spec:** 0-0-19 — Pre-resolve AWS::Include S3 Locations Before SAM Deploy  
**Design:** `design.md`  
**Requirements:** `requirements.md`

---

## Task List

### 1. Add PyYAML to `cli/requirements.txt`

Add `PyYAML>=6.0` to `cli/requirements.txt` under the "Configuration and formatting" section.

**File:** `cli/requirements.txt`

**Acceptance criteria:**
- `PyYAML>=6.0` is present in `cli/requirements.txt`
- It is placed in the appropriate section with a brief inline comment if helpful
- No other packages are added or removed

---

### 2. Add `_is_s3_url()` helper to `TemplateDeployer`

Add a private method `_is_s3_url(self, url: str) -> bool` that returns `True` when the input matches any S3 URL pattern.

**File:** `cli/deploy.py`

**Recognized patterns:**
- `s3://bucket/key`
- `https://s3.amazonaws.com/bucket/key`
- `https://bucket.s3.region.amazonaws.com/key`

**Acceptance criteria:**
- Method signature matches the design
- All three URL patterns are recognized (case-insensitive)
- Non-string inputs return `False`
- Local paths, relative paths, and `http://` URLs return `False`
- Google-style docstring with Args, Returns, and Example sections

---

### 3. Add `_has_s3_includes()` to `TemplateDeployer`

Add a private method `_has_s3_includes(self, template_path: Path) -> bool` that parses a YAML or JSON template and returns `True` if any `Fn::Transform: AWS::Include` entry has an S3 `Location`.

**File:** `cli/deploy.py`

**Behavior:**
- Imports `yaml` locally within the method (or at the top of the file alongside other imports)
- Tries YAML parse first, falls back to JSON
- Recursively walks dicts and lists searching for the `Fn::Transform` / `Fn::transform` pattern
- On any parse or scan exception: logs a `ConsoleAndLog.warning` and returns `False` (fail-open)

**Acceptance criteria:**
- Returns `True` for a template with at least one S3-based `AWS::Include`
- Returns `False` for templates with only local/relative includes or no includes at all
- Returns `False` (and logs warning) when the template cannot be parsed
- Calls `_is_s3_url()` for the URL check — no duplicated pattern matching
- Google-style docstring with Args, Returns, and Example sections

---

### 4. Add `_resolve_parameter_references()` to `TemplateDeployer`

Add a private method `_resolve_parameter_references(self, location, parameter_overrides: dict) -> str` that resolves CloudFormation intrinsic references in a `Location` value to a concrete string.

**File:** `cli/deploy.py`

**Supported patterns (per design):**
- Plain string — pass through unchanged
- `{'Ref': 'ParamName'}` — look up in `parameter_overrides`
- `{'Fn::Sub': '${Param}/path'}` — substitute each `${Param}` from `parameter_overrides`
- `{'Fn::Sub': ['${Param}/path', {'Param': 'value'}]}` — substitute from the inline map
- `{'Fn::Join': ['/', [...]]}` — join parts, recursing for nested intrinsics

**Error handling:**
- Raises `ValueError` when a referenced parameter is absent from `parameter_overrides`
- Raises `ValueError` for unsupported location formats

**Acceptance criteria:**
- All six supported patterns produce correct output
- Missing parameter raises `ValueError` with the parameter name in the message
- Unsupported format raises `ValueError` describing the format
- Google-style docstring with Args, Returns, Raises, and Example sections

---

### 5. Add `_read_parameter_overrides()` to `TemplateDeployer`

Add a private method `_read_parameter_overrides(self) -> dict` that reads and parses the `parameter_overrides` string from the active samconfig TOML stage.

**File:** `cli/deploy.py`

**Logic:**
- Opens the samconfig TOML using `tomli`
- Reads `parameter_overrides` from `default.deploy.parameters`, then the active stage
- Stage values take precedence over `default` (merge: `{**default_params, **stage_params}`)
- Parses the `"Key1=Value1 Key2=Value2"` format into a `dict`
- Returns `{}` when `parameter_overrides` is absent or empty

**Error handling:**
- Raises `ValueError` wrapping any exception (file not found, TOML decode error, etc.)

**Acceptance criteria:**
- Returns correct merged dict with stage overriding default
- Handles empty or absent `parameter_overrides` gracefully (returns `{}`)
- Raises `ValueError` on unreadable or malformed samconfig
- Google-style docstring with Args, Returns, Raises, and Example sections

---

### 6. Add `_download_s3_module()` to `TemplateDeployer`

Add a private method `_download_s3_module(self, s3_url: str, temp_dir: Path, index: int) -> str` that downloads one S3 module file into the temp directory and returns its relative path.

**File:** `cli/deploy.py`

**Logic:**
- Calls `self.parse_s3_url()` to get `(bucket, key, version_id)`
- Derives file extension from the key; defaults to `.yml` when the key has no extension
- Names the local file `module-{index}{ext}` (e.g., `module-0.yml`)
- Selects the S3 client via `self.is_bucket_public()` — anonymous for public buckets, authenticated otherwise
- Passes `VersionId` when `version_id` is not `None`
- Returns the relative path string (e.g., `"./module-0.yml"`)

**Error handling (all raise `ValueError` with actionable messages):**
- `AccessDenied` — tell user to check bucket permissions or authentication
- `404` / `NoSuchKey` — name the missing S3 URL
- Other `ClientError` — include the original error message

**Acceptance criteria:**
- File is written to `temp_dir / f"module-{index}{ext}"`
- Returns `"./module-{index}{ext}"`
- `VersionId` is forwarded when present
- Anonymous client used for public buckets
- All three error cases raise `ValueError` with the documented messages
- Google-style docstring with Args, Returns, Raises, and Example sections

---

### 7. Add `_read_artifact_bucket_config()` to `TemplateDeployer`

Add a private method `_read_artifact_bucket_config(self) -> tuple[str, str]` that returns `(s3_bucket, s3_prefix)` from the samconfig TOML.

**File:** `cli/deploy.py`

**Logic:**
- Opens the samconfig using `tomli`
- Reads from `atlantis.deploy.parameters` (shared) and the active stage's `deploy.parameters`
- Stage value takes precedence over `atlantis` value for both `s3_bucket` and `s3_prefix`
- `s3_prefix` defaults to `""` when absent

**Error handling:**
- Raises `ValueError` when `s3_bucket` is not found anywhere, directing the user to run `config.py`
- Raises `ValueError` on `TOMLDecodeError` (malformed file)
- Raises `ValueError` on `FileNotFoundError` (missing samconfig)

**Acceptance criteria:**
- Returns correct `(bucket, prefix)` from `atlantis` section
- Stage override takes precedence over `atlantis` value
- Empty prefix is `""` not `None`
- All three error cases raise `ValueError` with actionable messages
- Google-style docstring with Args, Returns, Raises, and Example sections

---

### 8. Add `_run_sam_package()` to `TemplateDeployer`

Add a private method `_run_sam_package(self, template_path: Path, output_path: Path, s3_bucket: str, s3_prefix: str) -> int` that runs `sam package` as a subprocess.

**File:** `cli/deploy.py`

**Command construction (mirrors `_run_sam_deploy`):**
```
sam package
  --template-file <template_path>
  --output-template-file <output_path>
  --s3-bucket <s3_bucket>
  [--s3-prefix <s3_prefix>]   # omit when s3_prefix is empty
  [--profile <profile>]        # omit when self.profile is None
```

**Execution:**
- `cwd` is set to `template_path.parent` (the temp directory)
- `shell=True` on Windows (`os.name == 'nt'`), `shell=False` otherwise
- Inherits `os.environ` with `FORCE_COLOR=1` and `TERM` set (same pattern as `_run_sam_deploy`)
- Logs the full command with `ConsoleAndLog.info` before running
- Returns the subprocess exit code
- Logs an error with `ConsoleAndLog.error` on non-zero exit; does not raise

**Acceptance criteria:**
- Command includes `--s3-prefix` only when `s3_prefix` is non-empty
- Command includes `--profile` only when `self.profile` is not `None`
- Returns the subprocess exit code unchanged
- Logs error message on non-zero exit
- Google-style docstring with Args, Returns, and Example sections

---

### 9. Add `_prepare_template_with_s3_includes()` to `TemplateDeployer`

Add a private method `_prepare_template_with_s3_includes(self, template_path: Path, temp_dir: Path) -> Path` that orchestrates the full module-download-and-rewrite step.

**File:** `cli/deploy.py`

**Logic:**
1. Load and YAML-parse the template at `template_path`
2. Call `self._read_parameter_overrides()` to get the parameter map
3. Walk the parsed template recursively (dicts and lists)
4. For each `Fn::Transform: AWS::Include` with an S3 `Location`:
   - Call `self._resolve_parameter_references(location, parameter_overrides)` to get the concrete URL
   - If the URL is already in `module_map`, reuse its local path (deduplication)
   - Otherwise call `self._download_s3_module(url, temp_dir, len(module_map))`, add to `module_map`, log the download
   - Rewrite `transform['Parameters']['Location']` to the local relative path
5. Write the rewritten template to `temp_dir / "template-rewritten.yml"` using `yaml.dump`
6. Log the count of downloaded modules
7. Return the path to the rewritten template

**Error handling:**
- Propagates `ValueError` from `_resolve_parameter_references` or `_download_s3_module`

**Acceptance criteria:**
- Each distinct S3 URL is downloaded exactly once (module map deduplication)
- All S3 `Location` values in the rewritten template are replaced with relative local paths
- Non-S3 `Location` values are left unchanged
- `template-rewritten.yml` exists in `temp_dir` after the call
- Logs each download and the total module count
- Google-style docstring with Args, Returns, Raises, and Example sections

---

### 10. Update `deploy_with_temp_template()` to route through the package step

Modify the existing `deploy_with_temp_template()` method in `TemplateDeployer` to detect S3 includes after downloading the main template and, when found, run the prepare → package → deploy flow instead of the direct deploy.

**File:** `cli/deploy.py`

**S3 template path changes (inside the `with tempfile.TemporaryDirectory()` block):**

After the template is successfully written to `temp_path`:
1. Call `self._has_s3_includes(temp_path)`
2. If `True`:
   - Log `"S3 includes detected - using sam package + deploy flow"`
   - Wrap in `try/except ValueError` → on error, log and `return 1`
   - Call `self._prepare_template_with_s3_includes(temp_path, temp_dir_path)`
   - Call `self._read_artifact_bucket_config()` → `(s3_bucket, s3_prefix)`
   - Call `self._run_sam_package(rewritten_template, packaged_template, s3_bucket, s3_prefix)`
   - If package exit code != 0, return that exit code
   - Call `self._run_sam_deploy(packaged_template, config_path)` and return its result
3. If `False`:
   - Log `"No S3 includes detected - using direct sam deploy"`
   - Call `self._run_sam_deploy(temp_path, config_path)` as before

**Local template path changes (the `else` branch):**

After confirming the local template exists:
1. Call `self._has_s3_includes(local_template_path)`
2. If `True`:
   - Open a new `with tempfile.TemporaryDirectory()` block
   - Follow the same prepare → package → deploy logic as the S3 path above
3. If `False`:
   - Call `self._run_sam_deploy(local_template_path, config_path)` as before

**Naming inside the temp block:** rename `temp_path` to `temp_template_path` for the main downloaded template to align with the design doc variable names (improves readability; no behavior change).

**Acceptance criteria:**
- S3 templates with includes go through `_prepare_template_with_s3_includes` → `_run_sam_package` → `_run_sam_deploy`
- S3 templates without includes go directly to `_run_sam_deploy`
- Local templates with includes open a fresh temp dir and go through the same package flow
- Local templates without includes go directly to `_run_sam_deploy`
- A non-zero `sam package` exit code is returned immediately; `sam deploy` is never called
- A `ValueError` from the prepare step is caught, logged, and returns `1`
- All existing behavior for templates without S3 includes is preserved

---

### 11. Update `VERSION` in `cli/deploy.py`

Review and increment the `VERSION` constant in `cli/deploy.py` per the CLI script versioning rules.

**File:** `cli/deploy.py`

**Current value:** `VERSION = "v0.1.3/2025-08-26"`  
**Change type:** MINOR — new functionality added (`_has_s3_includes`, `_prepare_template_with_s3_includes`, `_run_sam_package`, etc.) without breaking existing interface.  
**Today's date:** 2026-08-06

**New value:** `VERSION = "v0.2.0/2026-08-06"`

**Acceptance criteria:**
- `VERSION` is updated to `"v0.2.0/2026-08-06"`

---

### 12. Write unit tests for `_is_s3_url()` and `_has_s3_includes()`

Create `tests/test_deploy_s3_includes.py` with unit tests covering the detection helpers.

**File:** `tests/test_deploy_s3_includes.py` (new file)

**Test cases for `_is_s3_url()`:**
- `s3://bucket/key` → `True`
- `https://s3.amazonaws.com/bucket/key` → `True`
- `https://mybucket.s3.us-east-1.amazonaws.com/key.yml` → `True`
- `./local/file.yml` → `False`
- `../relative/path.yml` → `False`
- `http://example.com/file.yml` → `False`
- `None` (non-string) → `False`
- `123` (non-string) → `False`

**Test cases for `_has_s3_includes()`:**
- Template with one S3 `AWS::Include` → `True`
- Template with multiple S3 `AWS::Include` entries → `True`
- Template with nested S3 `AWS::Include` (inside a resource) → `True`
- Template with a local/relative `AWS::Include` only → `False`
- Template with no `Fn::Transform` at all → `False`
- Template with a different transform (`AWS::Serverless-2016-10-31`) but no include → `False`
- Unparseable file content → `False` (and a warning is logged)

**Acceptance criteria:**
- All test cases are present and pass
- Uses `tmp_path` fixture for files written to disk
- Mocks or stubs for `TemplateDeployer.__init__` are used so no real AWS calls are made

---

### 13. Write unit tests for `_resolve_parameter_references()` and `_read_parameter_overrides()`

Add test cases to `tests/test_deploy_s3_includes.py`.

**Test cases for `_resolve_parameter_references()`:**
- Plain string → returned unchanged
- `{'Ref': 'S3ModuleLocation'}` with matching param → correct URL
- `{'Ref': 'MissingParam'}` → raises `ValueError`
- `{'Fn::Sub': '${S3ModuleLocation}/modules/file.yml'}` → correct substitution
- `{'Fn::Sub': ['${Param}/path', {'Param': 's3://bucket'}]}` → correct substitution
- `{'Fn::Join': ['/', [{'Ref': 'S3ModuleLocation'}, 'modules', 'file.yml']]}` → correct join
- Unsupported format (e.g., `{'Fn::Select': [0, []]}`) → raises `ValueError`
- `{'Fn::Sub': '${MissingParam}/path'}` with no matching param → raises `ValueError`

**Test cases for `_read_parameter_overrides()`:**
- Samconfig with stage-specific `parameter_overrides` → returns correct dict
- Samconfig with only `default` `parameter_overrides` → returns default dict
- Samconfig where stage overrides default → stage value wins
- Samconfig with no `parameter_overrides` key → returns `{}`
- Missing samconfig file → raises `ValueError`
- Malformed TOML → raises `ValueError`

**Acceptance criteria:**
- All test cases pass
- Uses `tmp_path` for temporary samconfig TOML files
- No real AWS or filesystem side effects

---

### 14. Write unit tests for `_download_s3_module()`, `_read_artifact_bucket_config()`, and `_run_sam_package()`

Add test cases to `tests/test_deploy_s3_includes.py`.

**Test cases for `_download_s3_module()`:**
- Successful download writes file and returns `"./module-0.yml"`
- Key with `.json` extension → file named `module-0.json`
- Key with no extension → file named `module-0.yml` (default)
- `VersionId` is forwarded to `get_object` when present
- Anonymous client used when `is_bucket_public()` returns `True`
- Authenticated client used when `is_bucket_public()` returns `False`
- `AccessDenied` ClientError → raises `ValueError` with "Access denied" in message
- `NoSuchKey` ClientError → raises `ValueError` with the S3 URL in message
- Generic ClientError → raises `ValueError`

**Test cases for `_read_artifact_bucket_config()`:**
- `s3_bucket` in `atlantis` section → returned correctly
- Stage override for `s3_bucket` takes precedence
- `s3_prefix` absent → returned as `""`
- `s3_bucket` missing everywhere → raises `ValueError` with "s3_bucket" and "config.py" in message
- Malformed TOML → raises `ValueError`
- Missing samconfig → raises `ValueError`

**Test cases for `_run_sam_package()`:**
- Successful run (exit code 0) returns `0`
- Non-zero exit (exit code 1) returns `1` and logs an error
- `--s3-prefix` included when `s3_prefix` is non-empty
- `--s3-prefix` omitted when `s3_prefix` is `""`
- `--profile` included when `self.profile` is set
- `--profile` omitted when `self.profile` is `None`

**Acceptance criteria:**
- S3 calls are mocked (no real network requests)
- `subprocess.run` is patched for `_run_sam_package` tests
- All test cases pass

---

### 15. Write unit tests for `_prepare_template_with_s3_includes()`

Add test cases to `tests/test_deploy_s3_includes.py`.

**Test cases:**
- Template with two S3 includes → both modules downloaded, both `Location` values rewritten
- Template referencing the same S3 URL twice → only one download (deduplication)
- Template with a mix of S3 and local includes → only S3 `Location` values are rewritten
- `ValueError` from `_resolve_parameter_references` propagates out
- `ValueError` from `_download_s3_module` propagates out
- Written `template-rewritten.yml` contains no S3 URLs in any `Location` field

**Acceptance criteria:**
- S3 client is mocked (no real downloads)
- `tmp_path` fixture used for temp directory
- All test cases pass

---

### 16. Write integration tests for the two-path `deploy_with_temp_template()` flow

Add a new test file `tests/test_deploy_s3_include_flow.py` that tests the complete routing logic.

**File:** `tests/test_deploy_s3_include_flow.py` (new file)

**Test cases:**

1. **S3 template without includes** — `_has_s3_includes` returns `False`:
   - `_run_sam_package` is never called
   - `_run_sam_deploy` is called once with the downloaded template path
   - Returns the `_run_sam_deploy` exit code

2. **S3 template with includes** — full package + deploy path:
   - `_prepare_template_with_s3_includes` is called
   - `_run_sam_package` is called with the rewritten template
   - `_run_sam_deploy` is called with the packaged template
   - Returns the `_run_sam_deploy` exit code

3. **S3 template with includes, `sam package` fails** (returns non-zero):
   - `_run_sam_deploy` is never called
   - Returns the non-zero `sam package` exit code

4. **S3 template with includes, `_prepare_template_with_s3_includes` raises `ValueError`**:
   - `_run_sam_package` is never called
   - Returns `1`

5. **Local template without includes**:
   - `_run_sam_package` is never called
   - `_run_sam_deploy` is called with the local template path

6. **Local template with includes**:
   - A `TemporaryDirectory` is created for the package step
   - `_run_sam_package` is called
   - `_run_sam_deploy` is called with the packaged template

**Mocking approach:**
- All `TemplateDeployer` helper methods called inside `deploy_with_temp_template` are patched to isolate routing logic
- `verify_s3_object_exists` returns `True`
- `get_object` (S3 download) writes a minimal YAML template to the temp path
- `_run_sam_deploy` and `_run_sam_package` return configurable exit codes

**Acceptance criteria:**
- All six test cases pass
- No real AWS calls or subprocess invocations
- Correctness properties 1, 7 from the design doc are verified

---
