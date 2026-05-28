# CLI Script CHANGELOG

To update your local cli scripts from GitHub repository:

```bash
./cli/update.py
```

- The scripts are still in BETA and features are still being added and tested.
- There may be several versions with small fixes released every so often until reaching v0.1.0.
- After v0.1.0 all v0.0.x version change information will be removed from the Changelog.
- Refer to [TODO](./TODO.md) for upcoming BETA fixes and features.
- Report any issues not covered in TODO via the [Issues page in the GitHub repository](https://github.com/63Klabs/atlantis-sam-config-scripts/issues)

## v0.0.17 (2026-06-01)

- **config.py**: Added headless skeleton mode for AI and CI/CD automation. Two new non-interactive execution modes:
  - `--skeleton` / `--skeleton-verbose`: Generates a pre-populated JSON configuration file in `local-init/` with defaults and (optionally) parameter metadata. Only prompts for template selection.
  - `--headless`: Reads a skeleton file, validates all parameters against template constraints, generates samconfig, performs git operations, and optionally triggers deployment — all without user prompts.
  - `--deploy`: When paired with `--headless`, automatically invokes `deploy.py --headless` after successful configuration.
- **deploy.py**: Added `--headless` flag that suppresses all prompts, auto-performs git pull/commit/push, and overrides `confirm_changeset` to false.
- **Shared**: Added `headless_git_pull()` and `headless_git_commit_and_push()` to the Git class for non-interactive git operations.
- Added `local-init/*` to `.gitignore` for temporary skeleton files.

## v0.0.16 (2026-04-03)

- **config.py v0.1.7/2026-03-26**: Fixed bug where if the template's parameter regex pattern was incorrect it would kill the script. Now it will gracefully ignore the bad pattern and still accept user data. The template will instead fail to deploy, however, at least user data is saved and it will be up to the platform team to fix the template.

## v0.0.11 (2025-08-27)

- Added delete.py script to delete pipelines and associated application stack
- Added git pull and pushes to config.py and deploy.py
- Added repository tags import to config.py

## v0.0.7 (2025-06-10)

Mostly stable. Still in Beta.

I'm going to go into a little more detail than usual.

- update.py (v0.1.5/2025-06-10): Fixed issue where the downloaded release zip file does not contain the `v` in front of the version number even if the release tag in GitHub has the `v`. This irregularity lies in GitHub and is a weird quirk that according to my conversation with GitHub Copilot is "undocumented but reproducible." This is even experienced when downloading a zip directly from the release page. The link will point to `<url>/v0.0.6.zip`, but the downloaded file will be `<repo-name>-0.0.6.zip` with files extracted to `<repo-name>-0.0.6.zip`.
- For the fix, GitHub Copilot recommended that instead of constructing the path beforehand, look inside the zip file and see what the actual path is. This should hopefully fix any future issue.

Below is GitHub Copilot's explanation. (Note: it says "This is a GitHub quirk for repositories with a dash (`-`) in the tag name" but there isn't a dash in the tag name, so there is still some inconsistencies as to why this happens.) However, I provide this information because:

1. GitHub Copilot admitted I was right :)
2. "This is not documented by GitHub, but is reproducible and widely observed." (so there could still be other quirks that need to be accounted for in the future)

### From GitHub Copilot

Thank you for the detailed info and the direct observation.

You are correct: **the downloaded file is named**  

```
atlantis-sam-config-scripts-0.0.6.zip
```
**even though the tag is `v0.0.6`.**

#### Why does this happen?

This is a GitHub quirk for repositories with a dash (`-`) in the tag name.

GitHub strips the leading `v` from the zip file and folder name **if the tag is in the format `vX.Y.Z`**.

- The actual tag in the repo is still `v0.0.6`.
- The zip file and extracted folder are named as if the tag is `0.0.6`.

**This is not documented by GitHub, but is reproducible and widely observed.**

#### What does this mean for your code?

Your code currently does:

```python
zipped_dir = f"{repo}-{tag}/"
```

If `tag` is `v0.0.6`, but the extracted folder is `atlantis-sam-config-scripts-0.0.6/`, your code will not find the right directory.

#### Summary

- GitHub sometimes strips the leading `v` from zip/folder names for tags like `v0.0.6`.
- Adjust your code to check for both possibilities.

## v0.0.6 (2025-06-09)

Mostly stable. Still in Beta.

- Fixed issue in update.py where if the AWS session token required a refresh, it would skip the requested pull

## v0.0.5 (2025-06-07)

Mostly stable. Still in Beta.

- Fixed issue in update.py where it was not pulling the latest changes from the organization's SAM config repository.
- Fixed issue in config.py where CodeCommit and Repository tags are being erroneously added to the tag prompts for the user even though they are automatically managed.
