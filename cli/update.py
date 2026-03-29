#!/usr/bin/env python3

VERSION = "v0.1.5/2025-06-10"
# Created by Chad Kluck with AI assistance from Amazon Q Developer

import os
import sys
import requests
import tempfile
import zipfile
import click
import argparse
import subprocess
import traceback

from typing import Dict, Optional
from pathlib import Path

from lib.aws_session import AWSSessionManager, TokenRetrievalError
from lib.logger import ScriptLogger, Log, ConsoleAndLog
from lib.tools import Colorize
from lib.atlantis import DefaultsLoader

if sys.version_info[0] < 3:
    sys.stderr.write("Error: Python 3 is required\n")
    sys.exit(1)

# Initialize logger for this script
ScriptLogger.setup('update')

# Directories to update
DEFAULT_GITHUB_REPO = "63klabs/atlantis-sam-config-scripts"
DEFAULT_S3_BUCKET = "63klabs"
DEFAULT_S3_PATH = "/atlantis/utilities/v2/"

TARGET_DIRS = ['docs', 'cli']
DEFAULT_SRC = f"https://github.com/{DEFAULT_GITHUB_REPO}"
DEFAULT_SRC_VER = "release:latest"
SETTINGS_DIR = "defaults"

class UpdateManager:

    def __init__(self, profile: Optional[str] = None, dryrun: Optional[bool] = False, no_browser: Optional[bool] = False):

        self.profile = "default" if profile == None else profile
        self.dryrun = dryrun

        config_loader = DefaultsLoader(
            settings_dir=self.get_settings_dir()
        )

        self.settings = config_loader.load_settings()

        # Assemble the source info
        update_settings = self.settings.get('updates', {})
        self.target_dirs = update_settings.get('target_dirs', TARGET_DIRS)
        self.source = update_settings.get('source', DEFAULT_SRC)
        ver = DEFAULT_SRC_VER if self.source == DEFAULT_SRC else ""
        self.src_type = self.get_type(self.source)
        self.src_ver = self.get_version(self.source, self.src_type, update_settings.get('ver', ver))
        self.source = self.update_source(self.source, self.src_type, self.src_ver)

        # Check the arguments before moving on
        self._validate_args()

        # Set up AWS session and clients
        self.aws_session = AWSSessionManager(self.profile, None, no_browser)
        self.s3_client = self.aws_session.get_client('s3')

    def _validate_args(self) -> None:
        """Validate arguments"""
        
        # validate target dirs
        # Target directories must be a list and can only include strings defined in TARGET_DIRS
        if not isinstance(self.target_dirs, list):
            raise click.UsageError(f"target_dirs must be a list")
        if not all(isinstance(item, str) for item in self.target_dirs):
            raise click.UsageError(f"target_dirs must be a list of strings")
        if not all(item in TARGET_DIRS for item in self.target_dirs):
            raise click.UsageError(f"target_dirs must be a subset of {TARGET_DIRS}")
        
        # validate source
        # Source must be a string and must be either a GitHub URL, S3 location, or local file path
        if not isinstance(self.source, str):
            raise click.UsageError(f"source must be a string")
        if not self.source.lower().startswith(('https://github.com/', 's3://', '/')):
            raise click.UsageError(f"source must be a valid URL, S3 location, or local file path")
        
        # validate profile
        if self.profile and not isinstance(self.profile, str):
            raise click.UsageError(f"profile must be a string")

    def get_settings_dir(self) -> Path:
        """Get the settings directory path"""
        # Get the script's directory in a cross-platform way
        script_dir = Path(__file__).resolve().parent
        return script_dir.parent / SETTINGS_DIR
    
    def get_type(self, source: str) -> str:
        """Determine the type of the source
        From the source string, determine if we are going to use a local zip file,
        download a zip from S3, the GitHub repository main branch, or the GitHub repository release
        """
        # Source may be
        # - a local zip file
        # - a S3 location
        # - a GitHub repository main branch
        # - a GitHub repository release (either latest or a specific release)
        
        # if source is http/https and ends with .zip, then we can just use it
        if source.startswith("https://github.com/"):
            return "github"

        # If source is an S3 location, then we can just use it
        if source.startswith("s3://"):
            return "s3"

        # If source is a local zip file, then we can just use it
        if source.endswith(".zip"):
            return "local"

    def get_version(self, source: str, src_type: str, ver: str) -> str:
        """Get the version of the source
        For GitHub, this is either "latest", "commit:latest", "release:latest", or "release:<tag>"
        For S3, this is "latest" or the version_id
        For local, this is always "latest"
        """

        if src_type == "":
            src_type = self.get_type(source)

        if src_type == "github":
            if '/archive/refs/heads/' in source:
                return "commit:latest"
            elif source.endswith('.zip') and '/archive/refs/tags/' in source:
                # get release tag from source
                tag = source.split('/')[-1].split('-')[-1].split('.')[0]
                return f"release:{tag}"
            elif '/archive/refs/tags/' in source:
                return "release:latest"
            elif ver.startswith("release:"):
                return ver
            elif ver == "release:latest":
                return "release:latest"
            elif ver == "commit:latest":
                return "commit:latest"
            elif ver == "":
                return "release:latest"
            elif ver == "latest":
                return "release:latest"
            else:
                raise click.UsageError(f"Invalid GitHub source/ver combo: {ver} from {source}")
        elif src_type == "s3":
            # valid source is:
            # s3://bucket/path/to/file.zip
            # s3://bucket/path/to/file.zip?versionId=version_id
            # s3://bucket
            if '?versionId=' in source:
                return source.split('?versionId=')[-1]
            elif ver != "latest" and ver != "":
                return ver
            else:
                return "latest"
        elif src_type == "local":
            return "latest"
        else:
            raise click.UsageError(f"Invalid source/ver combo: {ver} from {source}")
    
    def update_source(self, source: str, src_type: str, ver: str) -> str:
        """Using the source, src_type, and ver, generate the full urls needed"""

        # https://github.com/63klabs/atlantis-sam-config-scripts/archive/refs/heads/main.zip
        # https://github.com/63klabs/atlantis-sam-config-scripts/archive/refs/tags/v1.1.4.zip
        # s3://63klabs/atlantis/utilities/v2/config_cli.zip

        if src_type == "github":
            # Get owner and repo from source
            result = self.get_github_repo_info(self.source)
            owner = result['owner']
            repo = result['repo']

            if ver == "commit:latest":
                return f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"
            elif ver.startswith("release:"):
                if ver == "release:latest":
                    try:
                        tag = self.get_latest_github_release(owner, repo)
                        ConsoleAndLog.info(f"Latest release tag: {tag}")
                    except Exception as e:
                        ConsoleAndLog.error(f"Error getting latest release tag: {e}")
                        Log.error(f"Error occurred at:\n{traceback.format_exc()}")
                        return ""
                else:
                    tag = ver.split(':')[1]

                return f"https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip"

        elif src_type == "s3":
            if '?versionId=' in source:
                t_split = source.split('?versionId=')
                source = t_split[0]
                ver = source.split('?versionId=')[-1]

            # Get bucket and path from source
            bucket = source.split('/')[2]
            path = '/'.join(source.split('/')[3:])

            # if path is blank or / then use default
            if path == "" or path == "/":
                path = f"{DEFAULT_S3_PATH}config_cli.zip"

            if ver == "latest":
                return f"s3://{bucket}{path}"
            else:
                return f"s3://{bucket}{path}?versionId={ver}"

        elif src_type == "local":
            # if local path exists and ends with zip then return source
            if os.path.exists(source) and source.endswith('.zip'):
                return source
            else:
                raise click.UsageError(f"Invalid local path: {source}")
        else:
            raise click.UsageError(f"Invalid source/ver combo: {ver} from {source}")

    def get_github_repo_info(self, source: str) -> Dict:
        """
        Get the owner and repo from a GitHub repository URL

        Args:
            source (str): GitHub repository URL

        Returns:
            Dict: Dictionary containing owner and repo
        """
        try:
            # Split the URL into parts
            parts = source.split('/')

            # Get the owner and repo from the URL
            owner = parts[3]
            repo = parts[4]
            tag = ""

            # if source ends with .zip then it is a release
            if source.endswith('.zip'):
                tag = Path(source).stem
                #tag = source.split('/')[-1].split('-')[-1].split('.')[0]

            return {
                'owner': owner,
                'repo': repo,
                'tag': tag
            }

        except IndexError:
            ConsoleAndLog.error(f"Invalid GitHub repository URL {source}")
            raise Exception("Invalid GitHub repository URL")
        
    def get_latest_github_release(self, owner: str, repo: str) -> str:
        """
        Get the latest release tag from a GitHub repository
        
        Args:
            owner (str): GitHub repository owner
            repo (str): GitHub repository name
        
        Returns:
            str: Latest release tag (e.g. 'v1.0.0')
        """
        try:
            # Query the GitHub API for latest release
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                headers={
                    'Accept': 'application/vnd.github.v3+json'
                }
            )
            response.raise_for_status()
            
            # Extract the tag name from the response
            return response.json()['tag_name']
            
        except requests.exceptions.RequestException as e:
            ConsoleAndLog.error(f"Failed to get latest release {str(e)}");
            raise Exception(f"Failed to get latest release: {str(e)}")
        
    def download_zip(self) -> None:
        # Create a temporary file with .zip extension
        click.echo(Colorize.output_with_value("Downloading zip file from ", self.source))
        Log.info(f"Downloading zip file from {self.source}")
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            if self.src_type == "github":
                try:
                    response = requests.get(self.source)
                    response.raise_for_status()
                    temp_zip.write(response.content)
                    return temp_zip.name
                except Exception as e:
                    click.echo(Colorize.error(f"Error downloading zip file: {str(e)}"))
                    Log.error(f"Error downloading zip file: {str(e)}")
                    Log.error(f"Error occurred at:\n{traceback.format_exc()}")
                    return False
                    
            elif self.src_type == "s3":
                try:
                    # Get bucket and path from source
                    t_source = self.source.split('?versionId=')
                    ver = ver = t_source[1] if '?versionId=' in self.source else None
                    bucket = t_source[0].split('/')[2]
                    path = '/'.join(t_source[0].split('/')[3:])

                    # Get the object from S3
                    params = {
                        'Bucket': bucket,
                        'Key': path
                    }
                    if ver:
                        params['VersionId'] = ver
                        
                    response = self.s3_client.get_object(**params)
                    temp_zip.write(response['Body'].read())
                    return temp_zip.name
                except Exception as e:
                    ConsoleAndLog.error(f"Error downloading zip file: {str(e)}")
                    Log.error(f"Error occurred at:\n{traceback.format_exc()}")
                    return False
            elif self.src_type == "local":
                # if local path exists and ends with zip then return source
                if os.path.exists(self.source) and self.source.endswith('.zip'):
                    return self.source
                else:
                    raise click.UsageError(f"Invalid local path: {self.source}")
            else:
                raise click.UsageError(f"Invalid source/ver combo: {self.src_ver} from {self.source}")

    def update_from_zip(self, zip_location: str ) -> bool:
        """Update specified directories from zip file that was downloaded to temp"""
        click.echo(Colorize.output_with_value("Updating from zip file:", zip_location))
        Log.info(f"Updating from zip file: {zip_location}")
        try:

            # If the zip file is from github, then the extracted base path will be <repo>-<tag>
            zipped_dir = ""
            # if self.src_type == "github":
            #     result = self.get_github_repo_info(self.source)
            #     repo = result['repo']
            #     tag = result['tag']

            #     if tag == "":
            #         tag = "main"

            #     print(f"Repo: {repo} Tag: {tag}")
            #     zipped_dir = f"{repo}-{tag}/"

            # print(f"Zipped dir: {zipped_dir}")

            # ConsoleAndLog.info(f"Extracted directory: {zipped_dir}")
            # ConsoleAndLog.info(f"Target directories: {self.target_dirs}")

            with zipfile.ZipFile(zip_location, 'r') as zip_ref:

                # Dynamically detect the top-level directory in the zip
                top_level_dirs = set(
                    file_info.filename.split('/')[0]
                    for file_info in zip_ref.filelist
                    if '/' in file_info.filename
                )
                if self.src_type == "github" and top_level_dirs:
                    # There should be only one top-level directory in a GitHub zip
                    zipped_dir = list(top_level_dirs)[0] + "/"

                print(f"Zipped dir: {zipped_dir}")

                ConsoleAndLog.info(f"Extracted directory: {zipped_dir}")
                ConsoleAndLog.info(f"Target directories: {self.target_dirs}")

                # Extract only the directories we want
                for file_info in zip_ref.filelist:
                    for target_dir in self.target_dirs:
                        src_dir = zipped_dir + target_dir + '/'
                        if file_info.filename.startswith(src_dir):
                            try:
                                # Get the relative path by removing the source directory prefix
                                relative_path = file_info.filename[len(src_dir):]
                                
                                # Create the full destination path
                                dest_path = os.path.join(target_dir, relative_path)

                                # Ensure the destination path is safe
                                dest = os.path.abspath(dest_path)
                                if not dest.startswith(os.path.abspath(target_dir)):
                                    raise ValueError("Attempted path traversal in zip file")
                                
                                # Create parent directories if they don't exist
                                os.makedirs(os.path.dirname(dest), exist_ok=True)

                                shortened_path = str(Path(*Path(file_info.filename).parts[-2:]))
                                dest_shortend_path = str(Path(*Path(dest).parts[-2:]))
                                
                                # Check if we care about the file
                                if not self.is_allowed_file(file_info.filename):
                                    ConsoleAndLog.info(f"Skipping file based on extension: {shortened_path}")
                                    continue


                                if not self.dryrun:

                                    ConsoleAndLog.info(f"Extracting {shortened_path} to {dest_shortend_path}")

                                    # Extract the file content and write it to the correct location
                                    with zip_ref.open(file_info) as source, open(dest, 'wb') as target:
                                        target.write(source.read())
                                else:
                                    ConsoleAndLog.info(f"Would extract {shortened_path} to {dest_shortend_path} (DRYRUN)")

                            except Exception as e:
                                ConsoleAndLog.error(f"Failed to extract {file_info.filename}: {str(e)}")
                                Log.error(f"Error occurred at:\n{traceback.format_exc()}")
                            
        except Exception as e:
            ConsoleAndLog.error(f"Error updating from zip: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            return False
        
        return True
    
    def is_allowed_file(self, filename: str) -> bool:
        # Define allowed files
        allowed_extensions = {'.py', '.sh', '.md', '.txt', '.json', '.toml'}
        allowed_filenames = {'.gitignore'}
        
        # Get just the base filename without the path
        base_filename = os.path.basename(filename)
        
        # Check if it's a special filename first
        if base_filename in allowed_filenames:
            return True
            
        # Check extensions
        file_extension = os.path.splitext(filename)[1].lower()
        return file_extension in allowed_extensions

    
# =============================================================================
# ----- GitOperations Class ---------------------------------------------------
# =============================================================================

class GitOperationsManager:
    def __init__(self, headless: Optional[bool] = False):
        self.original_branch = None
        self.target_branch = None
        self.headless = headless

    def confirm_update(self) -> bool:
        """Prompt user to confirm the update"""

        if self.headless:
            return True
        
        click.echo(Colorize.error("WARNING: This will update files in your repository."))
        choice = Colorize.prompt("Type 'UPDATE' to continue", "", str, False)
        return choice == "UPDATE"

    def get_current_branch(self) -> str:
        """Get the name of the current branch"""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            click.echo(Colorize.error(f"Failed to get current branch: {str(e)}"))
            Log.error(f"Failed to get current branch: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            raise

    def confirm_branch(self) -> bool:
        """Confirm branch selection and handle branch switching"""

        try:
            self.original_branch = self.get_current_branch()
            click.echo(Colorize.output_with_value("Currently on branch:", self.original_branch))

            # prompt until choice is either YES or NO
            choice = "YES" if self.headless else ""
            while choice not in ['YES', 'NO']:
                choice = Colorize.prompt("Continue with current branch? (YES/NO)", "", str, False)
                if choice not in ['YES', 'NO']:
                    click.echo(Colorize.error("Please enter 'YES' or 'NO'"))
            
            if choice.strip() != 'YES':
                new_branch = Colorize.prompt("Enter branch name to checkout", "", str, False)
                
                # Verify branch exists
                result = subprocess.run(
                    ["git", "branch", "--list", new_branch],
                    check=True,
                    capture_output=True,
                    text=True
                )
                        
                if not result.stdout.strip():

                    # prompt until choice is either YES or NO
                    branch_choice = ""
                    while branch_choice not in ['YES', 'NO']:
                        branch_choice = Colorize.prompt(f"Branch '{new_branch}' does not exist. Create it? (YES/NO)", "", str, False)
                        if branch_choice not in ['YES', 'NO']:
                            click.echo(Colorize.error("Please enter 'YES' or 'NO'"))

                    if branch_choice.strip() == 'YES':
                        subprocess.run(
                            ["git", "checkout", "-b", new_branch],
                            check=True
                        )
                        Log.info(f"Created and checked out new branch: {new_branch}")
                        click.echo(Colorize.output_with_value(f"Created and checked out new branch:", new_branch))
                    else:
                        return False
                else:
                    subprocess.run(
                        ["git", "checkout", new_branch],
                        check=True
                    )
                    Log.info(f"Checked out existing branch: {new_branch}")
                    click.echo(Colorize.output_with_value(f"Checked out existing branch:", new_branch))
                
                self.target_branch = new_branch
            else:
                self.target_branch = self.original_branch
            
            return True
            
        except subprocess.CalledProcessError as e:
            click.echo(Colorize.error(f"Git operation failed: {str(e)}"))
            Log.error(f"Git operation failed: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            return False

    def pull_changes(self) -> bool:
        """Pull latest changes from remote"""

        try:
            # prompt until choice is either YES or NO
            choice = "YES" if self.headless else ""
            while choice not in ['YES', 'NO']:
                choice = Colorize.prompt("Would you like to pull latest changes from this repository before updating? (YES/NO)", "YES", str)
                if choice not in ['YES', 'NO']:
                    click.echo(Colorize.error("Please enter 'YES' or 'NO'"))

            if choice.strip().upper() == 'YES':
                ConsoleAndLog.info("Pulling latest changes...")
                subprocess.run(
                    ["git", "pull"],
                    check=True
                )
                return True
            return False
        except subprocess.CalledProcessError as e:
            click.echo(Colorize.error(f"Failed to pull changes: {str(e)}"))
            Log.error(f"Failed to pull changes: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            return False

    def push_changes(self) -> bool:
        """Push changes to remote repository after user confirmation"""
        
        try:
            # Check if there are any changes to commit
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True
            )
            
            if not status.stdout.strip():
                ConsoleAndLog.info("No changes to commit")
                return False

            # Parse status output
            modified_files = []
            deleted_files = []
            new_files = []
            
            for line in status.stdout.splitlines():
                if len(line) >= 2:
                    status_code = line[:2]
                    file_path = line[3:]
                    
                    if status_code == ' M' or status_code == 'M ':
                        modified_files.append(file_path)
                    elif status_code == ' D' or status_code == 'D ':
                        deleted_files.append(file_path)
                    elif status_code == '??':
                        new_files.append(file_path)

            # Show organized status to user
            click.echo(Colorize.output_bold("\nChanges to be committed:"))
            
            if modified_files:
                click.echo(Colorize.output_bold("\nModified files:"))
                for file in modified_files:
                    click.echo(Colorize.output_with_value("  ", file))
                    
            if deleted_files:
                click.echo(Colorize.output_bold("\nDeleted files:"))
                for file in deleted_files:
                    click.echo(Colorize.output_with_value("  ", file))
                    
            if new_files:
                click.echo(Colorize.output_bold("\nNew files:"))
                for file in new_files:
                    click.echo(Colorize.output_with_value("  ", file))

            print()
            
            # Prompt until choice is either YES or NO
            choice = "YES" if self.headless else ""
            while choice not in ['YES', 'NO']:
                choice = Colorize.prompt("Would you like to commit and push these changes? (YES/NO)", "YES", str)
                if choice not in ['YES', 'NO']:
                    click.echo(Colorize.error("Please enter 'YES' or 'NO'"))

            if choice.strip() == 'YES':
                default_commit_msg = "chore: Updated cli with latest release"
                commit_msg = default_commit_msg if self.headless else ""
                # Get commit message from user
                while commit_msg == "":
                    commit_msg = Colorize.prompt("Enter commit message", default_commit_msg, str)
                    if not commit_msg.strip():
                        click.echo(Colorize.error("Commit message cannot be empty"))

                ConsoleAndLog.info("Committing changes...")
                subprocess.run(
                    ["git", "add", "."],
                    check=True
                )
                subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    check=True
                )

                ConsoleAndLog.info("Pushing changes...")
                subprocess.run(
                    ["git", "push", "origin", self.target_branch],
                    check=True
                )
                
                click.echo(Colorize.success("Changes successfully pushed to repository"))
                return True
            
            ConsoleAndLog.info("Push cancelled by user")
            return False

        except subprocess.CalledProcessError as e:
            click.echo(Colorize.error(f"Failed to push changes: {str(e)}"))
            Log.error(f"Failed to push changes: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            return False

    def cleanup(self) -> None:
        """Cleanup and restore original branch if needed"""
        if (self.original_branch and 
            self.target_branch and 
            self.original_branch != self.target_branch):
            try:
                ConsoleAndLog.info(f"\nSwitching back to original branch: {self.original_branch}")
                subprocess.run(
                    ["git", "checkout", self.original_branch],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                click.echo(Colorize.error(f"Failed to restore original branch: {str(e)}"))
                Log.error(f"Failed to restore original branch: {str(e)}")
                Log.error(f"Error occurred at:\n{traceback.format_exc()}")

    def final_confirm_update(self) -> bool:
        """
        Prompt user for final confirmation before proceeding with update.
        Returns True if user confirms, False otherwise.
        """

        if self.headless:
            return True
        
        try:
            click.echo(Colorize.output_bold("\nFinal Confirmation"))
            click.echo(Colorize.warning("You are about to update the configuration script files."))
            click.echo(Colorize.warning("Type 'CONTINUE' to proceed with the update or 'CANCEL' to exit."))
            
            # Prompt until valid input is received
            choice = ""
            while choice not in ['CONTINUE', 'CANCEL']:
                choice = Colorize.prompt("Enter your choice (CONTINUE/CANCEL)", "", str, False)
                if choice not in ['CONTINUE', 'CANCEL']:
                    click.echo(Colorize.error("Please type either 'CONTINUE' or 'CANCEL'"))
            
            if choice == 'CONTINUE':
                Log.info("Update confirmed by user")
                click.echo(Colorize.output("Update confirmed. Proceeding with the update..."))
                return True
            
            Log.info("Update cancelled by user")
            click.echo(Colorize.warning("Update cancelled."))
            return False
                
        except Exception as e:
            click.echo(Colorize.error(f"Error during confirmation prompt: {str(e)}"))
            Log.error(f"Error during confirmation prompt: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            return False


# =============================================================================
# ----- Main function ---------------------------------------------------------
# =============================================================================

EPILOG = """
Supports both AWS SSO and IAM credentials.
For SSO users, credentials will be refreshed automatically.
For IAM users, please ensure your credentials are valid using 'aws configure'.

Update from a zip stored locally or downloaded from s3 or GitHub (commit or release)

For settings, update settings.json in the defaults directory (see below for samples).

Examples:

    # Basic
    update.py 
    
    # Use specific AWS profile
    update.py --profile <yourprofile>

    # Optional flags:
    --headless
        Run with no user interaction for automated tasks.
    --dryrun
        Perform all actions (including git) but do not update files from zip.
    --no-browser
        For an AWS SSO login session, whether or not to set the --no-browser flag.

-----------------
Settings (defaults/settings.json):

The latest release from the GitHub repository will be used by default if no "updates" property is specified in settings.json 

Otherwise, you can customize where updates are downloaded from:

-- Update using a latest release from GitHub --

{
	"updates": {
		"source": "https://github.com/63klabs/atlantis-sam-config-scripts",
		"ver": "release:latest",
		"target_dirs": [ "docs", "cli" ]
}


}-- Update using latest commit from GitHub: --

{
	"updates": {
		"source": "https://github.com/63klabs/atlantis-sam-config-scripts",
		"ver": "commit:latest",
		"target_dirs": [ "docs", "cli" ]
	}
}

-- Update using a zip from local or S3 (version_id is only available for S3) --

{
	"updates": {
		"source": "s3://63klabs/atlantis/utilities/v2/config_cli.zip",
        "ver": "latest",
		"target_dirs": [ "docs", "cli" ]
	}
}

{
	"updates": {
		"source": "s3://63klabs/atlantis/utilities/v2/config_cli.zip",
        "ver": "74ssh_some-version-12345",
		"target_dirs": [ "docs", "cli" ]
	}
}

{
	"updates": {
		"source": "~/downloaded.zip",
		"target_dirs": [ "docs", "cli" ]
	}
}

https://github.com/63klabs/atlantis-sam-config-scripts
https://github.com/63klabs/atlantis-sam-config-scripts/archive/refs/heads/main.zip
https://github.com/63klabs/atlantis-sam-config-scripts/archive/refs/tags/v0.0.1.zip
s3://63klabs/atlantis/utilities/v2/config_cli.zip
s3://63klabs # since this is known, the script will fill in the path itself

------------------
Version:

GitHub Commit (archive/refs/head): if using latest commit as source, "commit:latest" 
GitHub Release (archive/refs/tags): "release:latest" or "release:<version>"
S3: "latest" or S3 Object Version ID

If a GitHub repo url is used and "ver" is not provided, "release:latest" is default.
If a S3 location is used and "ver" is not provided, "latest" is default.

ONLY USE TRUSTED SOURCES - You can host your own s3 bucket or GitHub repository or use the ones offered by 63klabs and chadkluck 

-----------------
Target Directories:

"docs" and "cli" are the only valid target_dirs. You can include one, both, or leave target_dirs as [] (never update even when script is run)

    - docs : overwrites docs/*
    - cli : overwrites cli/*

It is recommended you store custom docs and cli OUTSIDE the provided directories. While update.py does not currently delete files, it will replace any with conflicting names.

-----------------
Self-Hosted ZIPs

The update script will automatically extract files from the "<repository-name>-main" directory within the ZIP when GitHub is the source.

ALL OTHER ZIPS (s3 and locally downloaded) MUST have all files in the base directory of the zip file.

"""

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description='Update cli and Documentation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(EPILOG)
    )

    # Positional arguments
    # - there are no positional arguments for this script

    # Optional Named Arguments
    parser.add_argument('--profile',
                        required=False,
                        default=None,
                        help='AWS credential profile name')
    
    # Optional Flags
    parser.add_argument('--headless',
                        action='store_true',  # This makes it a flag
                        default=False,        # Default value when flag is not used
                        help='Run with no user interaction for automated tasks.')
    parser.add_argument('--dryrun',
                        action='store_true',  # This makes it a flag
                        default=False,        # Default value when flag is not used
                        help='Perform all actions (including git) but do not update files from zip.')
    parser.add_argument('--no-browser',
                        action='store_true',  # This makes it a flag
                        default=False,        # Default value when flag is not used
                        help='For an AWS SSO login session, whether or not to set the --no-browser flag.')
        
    args = parser.parse_args()
        
    return args

def main():

    args = parse_args()
    success = False
    zip_loc = None
    git_manager = GitOperationsManager(args.headless)
    update_manager = UpdateManager(
        args.profile, args.dryrun,
        args.no_browser
    )

    try:
        Log.info(f"{sys.argv}")
        Log.info(f"Version: {VERSION}")
        
        print()
        click.echo(Colorize.divider("="))
        click.echo(Colorize.output_bold(f"Update Manager ({VERSION})"))
        click.echo(Colorize.divider("="))
        print()

        # Get confirmation to proceed
        if not git_manager.confirm_update():
            ConsoleAndLog.info("Update cancelled by user.")
            return False

        # Handle branch selection and switching
        if not git_manager.confirm_branch():
            ConsoleAndLog.info("Branch operation cancelled by user.")
            return False

        # Pull changes if requested
        git_manager.pull_changes()

        # Perform Update
        try:

            zip_loc = update_manager.download_zip()

            # After downloading the zip file but before updating
            if git_manager.final_confirm_update():
                success = update_manager.update_from_zip(zip_loc)
            else:
                return False
        except TokenRetrievalError as e:
            click.echo(Colorize.error(f"AWS authentication error: {str(e)}"))
            Log.error(f"AWS authentication error: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            sys.exit(1)
        except Exception as e:
            click.echo(Colorize.error(f"Error initializing update manager: {str(e)}"))
            Log.error(f"Error initializing update manager: {str(e)}")
            Log.error(f"Error occurred at:\n{traceback.format_exc()}")
            sys.exit(1)
        finally:
            if zip_loc and os.path.exists(zip_loc):
                os.remove(zip_loc)
                click.echo(Colorize.output_with_value("Temporary zip file removed:", zip_loc))
                Log.info(f"Temporary zip file {zip_loc} removed")

        if success:
            click.echo(Colorize.success("\nUpdate completed successfully!"))
            Log.info("Update completed successfully!")
            
            if git_manager.push_changes():
                Log.info("Changes pushed to repository")
            else:
                click.echo(Colorize.warning("No changes pushed to repository."))
                Log.info("No changes pushed to repository")
        else:
            click.echo(Colorize.error("Update failed!"))
            Log.error("Update failed!")

    except Exception as e:
        click.echo(Colorize.error(f"Unexpected error: {str(e)}"))
        Log.error(f"Unexpected error: {str(e)}")
        Log.error(f"Error occurred at:\n{traceback.format_exc()}")
        sys.exit(1)
    finally:
        # Always try to restore original branch
        git_manager.cleanup()
        print()
        return success

if __name__ == '__main__':
    main()
