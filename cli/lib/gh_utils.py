#!/usr/bin/env python3

VERSION = "v0.2.0/2026-11-14"
# Developed by Chad Kluck with AI assistance from Amazon Q Developer and GitHub Copilot

"""
Utility functions for interacting with GitHub repositories.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time

import requests

from typing import Dict, List, Optional

from lib.logger import Log

# =============================================================================
# ----- GITHUB UTILS ----------------------------------------------------------
# =============================================================================

class GitHubUtils:

    @staticmethod
    def is_installed() -> bool:
        """
        Check if GitHub CLI (gh) is installed and available in the PATH.
        
        Returns:
            bool: True if GitHub CLI is installed, False otherwise
        """
        return shutil.which('gh') is not None

    @staticmethod
    def is_authenticated() -> bool:
        """
        Check if GitHub CLI (gh) is authenticated.
        
        Returns:
            bool: True if GitHub CLI is authenticated, False otherwise
        """
        try:
            # Run 'gh auth status' to check authentication status
            result = subprocess.run(
                ['gh', 'auth', 'status'], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                check=False
            )
            # Return True if the command was successful (exit code 0)
            return result.returncode == 0
        except Exception:
            # If any exception occurs, assume not authenticated
            return False

    @staticmethod
    def parse_repo_info_from_url(url: str) -> Dict[str, str]:
        """
        Parse GitHub repository information from a URL.
        
        Args:
            url (str): GitHub repository URL
        
        Returns:
            Dict[str, str]: Dictionary containing 'owner', 'repo', and 'tag' keys
        """
        # Remove the protocol (http/https) and split by '/'
        parts = url.split("://")[-1].split("/")

        owner = None
        repo = None
        tag = None
        
        if parts[0] == "github.com":
        # Extract owner and repo name
            if len(parts) >= 3:
                owner = parts[1]
                repo = parts[2]
                # Extract tag if present: https://github.com/63Klabs/atlantis-sam-config-scripts/releases/tag/0.0.8-beta
                if len(parts) >= 5 and parts[3] == "releases" and parts[4] == "tag":
                    tag = parts[5]
                # https://github.com/63Klabs/atlantis-sam-config-scripts/archive/refs/tags/0.0.8-beta.zip
                elif len(parts) >= 7 and parts[3] == "archive" and parts[4] == "refs" and parts[5] == "tags":
                    tag = parts[6].split(".")[0]

                return {
                    "owner": owner,
                    "repo": repo,
                    "tag": tag
                }
            else:
                raise ValueError("Invalid GitHub URL format")
        else:
            raise ValueError("Invalid GitHub URL format")


    @staticmethod
    def _format_failed_command(error: subprocess.CalledProcessError) -> str:
        """Format the command of a failed subprocess call for logging.

        Handles list commands (including non-string items such as Path
        objects), string commands, and a missing command.

        Args:
            error (subprocess.CalledProcessError): The error raised by subprocess.

        Returns:
            str: The command as a single string, or "unknown" if unavailable.

        Example:
            >>> err = subprocess.CalledProcessError(1, ["git", "push"])
            >>> GitHubUtils._format_failed_command(err)
            'git push'
        """
        cmd = getattr(error, 'cmd', None)
        if not cmd:
            return "unknown"
        if isinstance(cmd, (list, tuple)):
            return ' '.join(str(part) for part in cmd)
        return str(cmd)

    @staticmethod
    def _format_stderr(error: subprocess.CalledProcessError) -> str:
        """Get the stderr of a failed subprocess call as text for logging.

        Handles bytes or str stderr (commands run without ``text=True``
        return bytes).

        Args:
            error (subprocess.CalledProcessError): The error raised by subprocess.

        Returns:
            str: The stderr text, or "(no stderr)" if empty or missing.

        Example:
            >>> err = subprocess.CalledProcessError(1, "git", stderr=b"fatal: oops")
            >>> GitHubUtils._format_stderr(err)
            'fatal: oops'
        """
        stderr = getattr(error, 'stderr', None)
        if not stderr:
            return "(no stderr)"
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors='replace')
        return str(stderr)

    @staticmethod
    def _retry_gh_command(command: List[str], max_retries: int = 3) -> subprocess.CompletedProcess:
        """Execute a GitHub CLI command with retry logic and exponential backoff.
        
        Retries the command up to max_retries times if it fails with a
        CalledProcessError. Uses exponential backoff delays: 1s, 2s, 4s.
        
        Args:
            command: GitHub CLI command as a list (e.g., ["gh", "repo", "view", "owner/repo"])
            max_retries: Maximum number of retry attempts (default: 3)
        
        Returns:
            subprocess.CompletedProcess: The successful command result
        
        Raises:
            subprocess.CalledProcessError: If all retry attempts are exhausted
            
        Example:
            >>> result = GitHubUtils._retry_gh_command(
            ...     ["gh", "repo", "view", "owner/repo", "--json", "name"],
            ...     max_retries=3
            ... )
        """
        from lib.logger import Log
        
        # Initial attempt (not counted as a retry)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )
            return result
        except subprocess.CalledProcessError as e:
            # Log stderr from initial attempt
            stderr_text = e.stderr if e.stderr else "(no stderr)"
            Log.error(f"gh command failed (initial attempt): {' '.join(command)}")
            Log.error(f"gh command stderr: {stderr_text}")
            
            # Store the last error for re-raising after all retries
            last_error = e
            
            # Define delays array: [1, 2, 4] seconds
            delays = [1, 2, 4]
            
            # Retry loop
            for attempt in range(1, max_retries + 1):
                # Get delay from array, or use last delay if beyond array length
                delay = delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1]
                
                # Log retry attempt at INFO level
                Log.info(f"Retrying gh command (attempt {attempt} of {max_retries}) after {delay} second(s)...")
                
                # Sleep for the delay
                time.sleep(delay)
                
                # Try the command again
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    Log.info(f"gh command succeeded on retry attempt {attempt}")
                    return result
                except subprocess.CalledProcessError as e:
                    # Store the error and continue to next retry
                    last_error = e
                    stderr_text = e.stderr if e.stderr else "(no stderr)"
                    Log.error(f"gh command failed (retry attempt {attempt}): {' '.join(command)}")
                    Log.error(f"gh command stderr: {stderr_text}")
            
            # All retries exhausted
            repo_name = command[3] if len(command) > 3 else "unknown"
            Log.error(f"gh command failed after {max_retries + 1} attempts (1 initial + {max_retries} retries) for repository: {repo_name}")
            raise last_error

    @staticmethod
    def get_latest_release(owner: str, repo: str) -> str:
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
            raise Exception(f"Failed to get latest release: {str(e)}")
        
    # @staticmethod
    # def download_zip_from_url(url: str, zip_path: Optional[str] = None) -> str:
    #     """
    #     Download a ZIP file from a GitHub repository URL
    #     Args:
    #         url (str): GitHub repository URL
    #     Returns:
    #         str: Path to the downloaded ZIP file
    #     """

    #     # Create a temporary file path with .zip extension
    #     if zip_path is None:
    #         zip_path = tempfile.mktemp(suffix='.zip')
       
    #     try:
    #         response = requests.get(url, stream=True)
    #         response.raise_for_status()  # Raise an exception for HTTP errors
    #         with open(zip_path, 'wb') as f:
    #             for chunk in response.iter_content(chunk_size=8192):
    #                 f.write(chunk)
    #         return zip_path
    #     except requests.exceptions.RequestException as e:
    #         raise Exception(f"Failed to download ZIP file: {str(e)}")

    @staticmethod
    def download_zip_from_url(url: str, zip_path: Optional[str] = None) -> str:
        """
        Download a ZIP file from a GitHub repository URL
        Args:
            url (str): GitHub repository URL
            zip_path (Optional[str]): Path to save the ZIP file, if provided
        Returns:
            str: Path to the downloaded ZIP file
        """
        temp_file_created = False
        try:
            # Create a temporary file with .zip extension if zip_path is not provided
            if zip_path is None:
                with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
                    zip_path = temp_file.name
                    temp_file_created = True
            
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return zip_path
        except requests.exceptions.RequestException as e:
            # Clean up the temporary file if we created one and an error occurred
            if temp_file_created and zip_path and os.path.exists(zip_path):
                os.unlink(zip_path)
            raise Exception(f"Failed to download ZIP file: {str(e)}")


    @staticmethod
    def create_repo(repo_name: str, private: bool = True, description: str = None) -> Dict:
        """
        Create a GitHub repository using the GitHub CLI

        Args:
            repo_name (str): Repository name
            private (bool): Whether the repository should be private
            description (str): Repository description

        Returns:
            Bool: True if repository was created successfully, False otherwise
            
        Raises:
            Exception: If the repository creation fails
        """
        try:
            
            # Build the command
            cmd = ["gh", "repo", "create", repo_name]

            if private:
                cmd.append("--private")
            else:
                cmd.append("--public")
                
            if description:
                cmd.extend(["--description", description])
                            
            # Execute the command
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            stderr_text = e.stderr if e.stderr else "(no stderr)"
            Log.error(f"gh repo create stderr: {stderr_text}")
            raise Exception(f"Failed to create repository: {e.stderr}")
        except Exception as e:
            raise Exception(f"Failed to create repository: {e}")
        
    @staticmethod
    def repository_exists(repo_name: str) -> bool:
        """
        Check if a GitHub repository exists using the GitHub CLI.
        Args:
            repo_name (str): Repository name (e.g., "owner/repo")
        
        Returns:
            bool: True if repository exists, False otherwise
        """
        try:
            # Use gh CLI to check if the repository exists
            result = subprocess.run(
                ["gh", "repo", "view", repo_name],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            raise Exception(f"Failed to check repository existence: {str(e)}")
        
    @staticmethod
    def get_repository(repo_name: str) -> Dict[str, str]:
        """
        Get information about a GitHub repository using the GitHub CLI.
        
        Retries up to 3 times with exponential backoff (1s, 2s, 4s) if the
        command fails with a subprocess error. Logs stderr for failed attempts.
        
        Args:
            repo_name (str): Repository name (e.g., "owner/repo")
        
        Returns:
            Dict[str, str]: Dictionary containing 'exists' and 'repositoryMetadata' keys
        
        Raises:
            Exception: When gh repo view fails after all retry attempts
        
        Example:
            >>> info = GitHubUtils.get_repository("owner/repo")
            >>> print(info['repositoryMetadata']['url'])
        """
        try:
            # Use gh CLI to get repository information
            Log.info(f"Calling gh repo view for repository: {repo_name}")
            result = GitHubUtils._retry_gh_command([
                "gh", "repo", "view", repo_name, "--json",
                "name,nameWithOwner,owner,repositoryTopics,sshUrl,isTemplate,templateRepository,visibility,url"
            ])
            info = json.loads(result.stdout)
            info["cloneUrlHttp"] = f"{info.get('url')}.git"
            info["cloneUrlSsh"] = f"{info.get('sshUrl')}"
            Log.info(f"Successfully retrieved repository info for: {repo_name}")
            return {
                "exists": True,
                "repositoryMetadata": info
            }
        except subprocess.CalledProcessError as e:
            # stderr already logged by _retry_gh_command during retries
            raise Exception(f"Failed to get repository info: {e}")
        except Exception as e:
            Log.error(f"Unexpected error in get_repository: {e}")
            raise Exception(f"Failed to get repository info: {str(e)}")
    
    @staticmethod
    def create_branch_structure(repo_name: str, readme_content: str, author: str, email: str) -> None:
        """
        Create main, test, and dev branches in a GitHub repo using the gh CLI.
        
        Args:
            repo_name (str): Repository name (e.g., "owner/repo")
            readme_content (str): Content for the README.md file
            author (str): Author name for commits
            email (str): Author email for commits

        Raises:
            subprocess.CalledProcessError: If any git/gh command fails. The
                failed command and its stderr are logged at ERROR level
                before the error is re-raised.

        Example:
            >>> GitHubUtils.create_branch_structure(
            ...     "owner/repo", "# My Repo", "Jane Doe", "jane@example.com")
        """
        temp_dir = tempfile.mkdtemp()
        try:
            # Clone the repo
            subprocess.run(
                ["gh", "repo", "clone", repo_name, temp_dir],
                check=True, capture_output=True
            )
            os.chdir(temp_dir)

            # Configure git user for this repo
            subprocess.run(
                ["git", "config", "user.name", author],
                cwd=temp_dir, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", email],
                cwd=temp_dir, check=True, capture_output=True
            )

            # Ensure main branch exists and checkout
            subprocess.run(
                ["git", "checkout", "-B", "main"]
                , cwd=temp_dir, check=True, capture_output=True
            )

            # Create README.md
            readme_path = os.path.join(temp_dir, "README.md")
            with open(readme_path, 'w', encoding='utf-8', newline='') as f:
                f.write(readme_content)

            subprocess.run(["git", "add", "README.md"], cwd=temp_dir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial README.md commit"], cwd=temp_dir, check=True, capture_output=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=temp_dir, check=True, capture_output=True)

            # Create and push test branch from main
            subprocess.run(["git", "checkout", "-b", "test"], cwd=temp_dir, check=True, capture_output=True)
            subprocess.run(["git", "push", "-u", "origin", "test"], cwd=temp_dir, check=True, capture_output=True)

            # Create and push dev branch from test
            subprocess.run(["git", "checkout", "-b", "dev"], cwd=temp_dir, check=True, capture_output=True)
            subprocess.run(["git", "push", "-u", "origin", "dev"], cwd=temp_dir, check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            Log.error(f"create_branch_structure command failed: {GitHubUtils._format_failed_command(e)}")
            Log.error(f"stderr: {GitHubUtils._format_stderr(e)}")
            raise
        finally:
            os.chdir("/")
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def create_init_commit(all_files: List[Dict], repo_name: str, seed_branch: str, author: str, email: str, git_dir: str) -> None:
        """Create an initial commit with all files in a GitHub repository using the gh CLI.

        The repository is cloned with ``core.autocrlf=false`` and every file is
        written as bytes, so the committed files match the supplied content
        regardless of the user's git line-ending settings or locale encoding.

        Args:
            all_files: List of dictionaries containing file information. Each
                dictionary has a ``filePath`` (str, relative path) and a
                ``fileContent`` that may be ``bytes`` (written as-is) or ``str``
                (encoded as UTF-8 before writing).
            repo_name: Repository name (e.g., "owner/repo").
            seed_branch: Branch name for seeding.
            author: Author name for commits.
            email: Author email for commits.
            git_dir: Path to the directory the repository is cloned into.

        Raises:
            Exception: If any gh or git command fails. The message includes the
                failed command and its stderr.

        Example:
            >>> GitHubUtils.create_init_commit(
            ...     [{'filePath': 'logo.png', 'fileContent': b'\\x89PNG\\r\\n'}],
            ...     'owner/repo', 'dev', 'Jane Doe', 'jane@example.com',
            ...     '/tmp/clone')  # doctest: +SKIP
        """

        try:

            total_files = len(all_files)

            # core.autocrlf=false is applied at clone time so the clone's own
            # tracked files are checked out without line-ending conversion and
            # "git add ." does not restage them
            subprocess.run(
                ["gh", "repo", "clone", repo_name, git_dir, "--", "-c", "core.autocrlf=false"],
                check=True, capture_output=True
            )
            
            # Configure git user for this repo
            subprocess.run(
                ["git", "config", "user.name", author],
                cwd=git_dir, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", email],
                cwd=git_dir, check=True, capture_output=True
            )
            
            # Checkout the dev branch
            subprocess.run(
                ["git", "checkout", seed_branch],
                cwd=git_dir, check=True, capture_output=True
            )
            
            # Copy all files from temp_dir to git_dir
            for file_info in all_files:
                file_path = file_info['filePath']
                file_content = file_info['fileContent']
                
                # Create directory structure if needed
                full_path = os.path.join(git_dir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # Write file content as bytes (no encoding or newline translation)
                if isinstance(file_content, str):
                    file_content = file_content.encode('utf-8')
                with open(full_path, 'wb') as f:
                    f.write(file_content)
            
            # Add all files
            subprocess.run(
                ["git", "add", "."],
                cwd=git_dir, check=True, capture_output=True
            )
            
            # Commit changes
            commit_message = f'Seeding repository with {total_files} files'
            subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=git_dir, check=True, capture_output=True
            )
            
            # Push to remote
            subprocess.run(
                ["git", "push", "origin", seed_branch],
                cwd=git_dir, check=True, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            cmd_str = GitHubUtils._format_failed_command(e)
            stderr_text = GitHubUtils._format_stderr(e)
            Log.error(f"git command failed in create_init_commit: {cmd_str}")
            Log.error(f"stderr: {stderr_text}")
            raise Exception(f"Error in GitHub CLI command: {cmd_str}\nError: {stderr_text}")

    @staticmethod
    def merge_branches_fast_forward(git_dir: str, source_branch: str = 'dev',
                                    dest_branch: str = 'test') -> None:
        """Fast-forward merge source_branch into dest_branch in a local clone and push.

        Reuses a clone created during seeding (git user identity already
        configured). Checks out the destination branch, performs a
        fast-forward-only merge of the source branch, and pushes the
        destination branch to origin.

        Args:
            git_dir (str): Path to the existing local clone to operate in.
            source_branch (str): Branch to merge from. Defaults to 'dev'.
            dest_branch (str): Branch to merge into and push. Defaults to 'test'.

        Raises:
            Exception: If any git command fails (including a
                non-fast-forwardable merge).

        Example:
            >>> GitHubUtils.merge_branches_fast_forward('/tmp/clone',
            ...                                         source_branch='dev',
            ...                                         dest_branch='test')
        """
        try:
            subprocess.run(
                ["git", "checkout", dest_branch],
                cwd=git_dir, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "merge", "--ff-only", source_branch],
                cwd=git_dir, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "push", "origin", dest_branch],
                cwd=git_dir, check=True, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            cmd_str = GitHubUtils._format_failed_command(e)
            stderr_text = GitHubUtils._format_stderr(e)
            Log.error(f"git command failed in merge_branches_fast_forward: {cmd_str}")
            Log.error(f"git merge stderr: {stderr_text}")
            raise Exception(f"Error in GitHub CLI command: {cmd_str}\nError: {stderr_text}")
