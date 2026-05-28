#!/usr/bin/env python3

VERSION = "v0.0.2/2025-08-26"
# Developed by Chad Kluck with AI assistance from Amazon Q Developer
# GitHub Copilot assisted in color formats of output and prompts

"""
Git functions for automating script based Git operations.
"""

import subprocess
import sys
import click

from .logger import Log
from .tools import Colorize

class Git:

    @staticmethod
    def prompt_git_pull() -> None:
        """Prompt user if git pull should be performed"""
        if click.confirm(Colorize.question("Perform git pull before proceeding?"), default=True):
            try:
                result = subprocess.run(['git', 'pull'], capture_output=True, text=True, check=True)
                click.echo(Colorize.success("Git pull completed successfully"))
                Log.info("Git pull completed successfully")
            except subprocess.CalledProcessError as e:
                click.echo(Colorize.error(f"Git pull failed: {e.stderr}"))
                Log.error(f"Git pull failed: {e.stderr}")
                if not click.confirm("Continue despite git pull failure?"):
                    sys.exit(1)
                    
    @staticmethod
    def git_commit_and_push(commit_message) -> None:
        """Perform git commit and push"""
        try:
            # Add changes
            subprocess.run(['git', 'add', '.'], check=True)
            
            # Check if there are changes to commit
            result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
            if result.returncode == 0:
                click.echo(Colorize.info("No changes to commit"))
                Log.info("No changes to commit")
                return
            
            # Commit
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)
            
            # Push
            subprocess.run(['git', 'push'], check=True)
            
            click.echo(Colorize.success("Git commit and push completed"))
            Log.info("Git commit and push completed")
            
        except subprocess.CalledProcessError as e:
            click.echo(Colorize.error(f"Git operation failed: {str(e)}"))
            Log.error(f"Git operation failed: {str(e)}")

    @staticmethod
    def prompt_git_commit_and_push(commit_message) -> None:
        """Prompt user for commit message and perform git commit and push"""
        if click.confirm(Colorize.question("Perform git commit and push?"), default=True):
            commit_message = click.prompt(Colorize.question("Enter commit message"), commit_message, type=str)
            Git.git_commit_and_push(commit_message)

    @staticmethod
    def headless_git_pull() -> None:
        """Perform git pull without prompting. Raises SystemExit on failure."""
        try:
            result = subprocess.run(
                ['git', 'pull'], capture_output=True, text=True, check=True
            )
            Log.info("Git pull completed successfully (headless)")
        except subprocess.CalledProcessError as e:
            Log.error(f"Git pull failed (headless): {e.stderr}")
            sys.exit(f"Error: git pull failed: {e.stderr}")

    @staticmethod
    def headless_git_commit_and_push(commit_message: str) -> None:
        """Perform git add, commit, push without prompting. Raises SystemExit on failure."""
        try:
            subprocess.run(['git', 'add', '.'], check=True, capture_output=True, text=True)

            result = subprocess.run(
                ['git', 'diff', '--cached', '--quiet'], capture_output=True
            )
            if result.returncode == 0:
                Log.info("No changes to commit (headless)")
                return

            subprocess.run(
                ['git', 'commit', '-m', commit_message],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ['git', 'push'], check=True, capture_output=True, text=True
            )
            Log.info("Git commit and push completed (headless)")
        except subprocess.CalledProcessError as e:
            Log.error(f"Git operation failed (headless): {e.stderr}")
            sys.exit(f"Error: git {e.cmd[1]} failed: {e.stderr}")
