#!/usr/bin/env python3

VERSION = "v0.0.1/2025-05-21"
# Developed by Chad Kluck with AI assistance from Amazon Q Developer and GitHub Copilot

"""
Utility functions for interacting with GitHub repositories.
"""

import requests
import tempfile
import os
import shutil
import subprocess
import json

from typing import Dict, List, Optional

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
        Args:
            repo_name (str): Repository name (e.g., "owner/repo")
        Returns:
            Dict[str, str]: Dictionary containing 'exists' and 'repositoryMetadata' keys
        """
        try:
            # Use gh CLI to get repository information
            result = subprocess.run(
                ["gh", "repo", "view", repo_name, "--json", "name,nameWithOwner,owner,repositoryTopics,sshUrl,isTemplate,templateRepository,visibility,url"],
                capture_output=True,
                text=True,
                check=True
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                info["cloneUrlHttp"] = f"{info.get('url')}.git"
                info["cloneUrlSsh"] = f"{info.get('sshUrl')}"
                return {
                    "exists": True,
                    "repositoryMetadata": info
                }
            else:
                raise Exception(f"Failed to get repository info: {result.stderr}")
        except Exception as e:
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
            with open(readme_path, 'w') as f:
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

        finally:
            os.chdir("/")
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def create_init_commit(all_files: List[Dict], repo_name: str, seed_branch: str, author: str, email: str, git_dir: str) -> None:
        """
        Create an initial commit with all files in a GitHub repository using the gh CLI.

        Args:
            all_files (list): List of dictionaries containing file information
            repo_name (str): Repository name (e.g., "owner/repo")
            seed_branch (str): Branch name for seeding
            author (str): Author name for commits
            email (str): Author email for commits
            git_dir (str): Path to the cloned repository directory
        """

        try:

            total_files = len(all_files)

            # Clone the repository
            subprocess.run(
                ["gh", "repo", "clone", repo_name, git_dir],
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
                
                # Write file content
                with open(full_path, 'w' if isinstance(file_content, str) else 'wb') as f:
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
            raise Exception(f"Error in GitHub CLI command: {e.cmd}\nOutput: {e.stdout.decode() if e.stdout else ''}\nError: {e.stderr.decode() if e.stderr else ''}")
