#!/usr/bin/env python3

VERSION = "v0.1.4/2025-06-04"
# Created by Chad Kluck with AI assistance from Amazon Q Developer
# GitHub Copilot assisted with GitHub operations and color formats of output and prompts

# Usage Information:
# create_repo.py -h

# Full Documentation:
# https://github.com/63klabs/atlantis-sam-config-scripts/

import re
import tempfile
import zipfile
import base64
import os
import argparse
import sys
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Union
from urllib.parse import urlparse

import boto3
import botocore
import click

from lib.aws_session import AWSSessionManager, TokenRetrievalError
from lib.logger import ScriptLogger, Log, ConsoleAndLog
from lib.tools import Colorize
from lib.atlantis import FileNameListUtils, DefaultsLoader, TagUtils
from lib.gh_utils import GitHubUtils

if sys.version_info[0] < 3:
    sys.stderr.write("Error: Python 3 is required\n")
    sys.exit(1)

# Initialize logger for this script
ScriptLogger.setup('create_repo')

SETTINGS_DIR = "defaults"
VALID_PROVIDERS = ['codecommit', 'github']

class RepositoryCreator:

    def __init__(self, repo_name: str, source: Optional[str] = None, region:  Optional[str] = None, profile: Optional[str] = None, prefix: Optional[str] = None, provider: Optional[str] = None, no_browser: Optional[bool] = False) -> None:
        self.repo_name = repo_name
        self.region = region
        self.profile = profile
        self.prefix = prefix
        self.provider = provider
        self.tags = {}

        self.source_type = None
        self.source = None
        self.set_source(source)
        
        self.aws_session = AWSSessionManager(self.profile, self.region, no_browser)
        self.s3_client = self.aws_session.get_client('s3', self.region)
        self.codecommit_client = self.aws_session.get_client('codecommit', self.region)
        # self.s3_client_anonymous = self.aws_session.get_client('s3', config=botocore.client.Config(signature_version=botocore.UNSIGNED))
        self.s3_client_anonymous = boto3.client('s3', config=botocore.client.Config(signature_version=botocore.UNSIGNED))


        config_loader = DefaultsLoader(
            settings_dir=self.get_settings_dir(),
            prefix=self.prefix,
            project_id=None,
            infra_type=None
        )

        self.clone_url_ssh = None
        self.clone_url_https = None

        self.settings = config_loader.load_settings()
        self.defaults = config_loader.load_defaults()

        self.provider = provider if provider else self.settings.get('repositories', {}).get('provider', 'codecommit')
        if self.provider not in VALID_PROVIDERS:
            click.echo(Colorize.error(f"Invalid provider: {self.provider}. Valid providers are: {', '.join(VALID_PROVIDERS)}"))
            Log.error(f"Error: Invalid provider: {self.provider}. Valid providers are: {', '.join(VALID_PROVIDERS)}")
            sys.exit(1)

        if self.provider == 'github':
            # Make sure GitHub CLI is installed
            if not GitHubUtils.is_installed():
                msg = "GitHub CLI is not installed. Please install it and try again."
                click.echo(Colorize.error(msg))
                Log.error(msg)
                sys.exit(1)
            # Make sure GitHub CLI is authenticated
            if not GitHubUtils.is_authenticated():
                msg = "GitHub CLI is not authenticated. Please authenticate using 'gh auth login' and try again."
                click.echo(Colorize.error(msg))
                Log.error(msg)
                sys.exit(1)
            # Make sure repository name is valid for GitHub owner/repo format
            if not re.match(r'^[a-zA-Z0-9](?:-?[a-zA-Z0-9]){0,38}/[a-zA-Z0-9._-]{1,100}$', self.repo_name):
                msg = "Invalid repository name for GitHub. Must be in owner/repo format: owner (1-39 chars), repo (1-100 chars), allowed: a-z, A-Z, 0-9, -, _, ."
                click.echo(Colorize.error(msg))
                Log.error(msg)
                sys.exit(1)

    # -------------------------------------------------------------------------
    # - Utility
    # -------------------------------------------------------------------------

    def parse_s3_url(self, s3_uri: str) -> List[str]:
        """Parse an S3 URL into bucket and key."""
        try:
            parsed = urlparse(s3_uri)
            if parsed.scheme != 's3':
                raise ValueError("URL must be an S3 URL starting with 's3://'")
            return parsed.netloc, parsed.path.lstrip('/')
        except ValueError as e:
            click.echo(Colorize.error(f"Error parsing S3 URL: {str(e)}"))
            Log.error(f"Error: {str(e)}")
            sys.exit(1)

    def _determine_source(self, source: Optional[str]) -> tuple[str, str]:
        """Determine the source type and return the source URL and type"""
        if source is None:
            return None, None

        # Check if the source is a valid S3 URL, ends with .zip or ?versionId=
        if source.startswith('s3://'):

            if re.match(r's3:\/\/.+\/.+\.zip(\?versionId=.+)?', source):
                return source, 's3'
            else:
                click.echo(Colorize.error(f"Invalid S3 URL: {source}"))
                Log.error(f"Error: Invalid S3 URL: {source}")
                sys.exit(1)
        
        # If it is from GitHub and it ends with .zip, we assume it's a zip file
        elif re.match(r'https?:\/\/(www\.)?github\.com\/.+\/.+\.zip', source):
            # We need to determine the zip URL
            return source, 'github'

        # Check if the source is a valid GitHub release URL
        elif re.match(r'https?:\/\/(www\.)?github\.com\/.+\/.+\/(releases(\/tag)?|tags)(\/.*)?', source):
            # We need to determine the zip URL
            # To clean the URL we will break down to the base repository URL and then add the release path (either latest or specific tag)
            result = GitHubUtils.parse_repo_info_from_url(source)
            owner = result['owner']
            repo = result['repo']
            tag = result['tag']
            
            if tag == None:
                tag = GitHubUtils.get_latest_release(owner, repo)

            source = f"https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip"

            return source, 'github'
        
        # Check if the source is a valid GitHub Repository URL
        elif re.match(r'https?:\/\/(www\.)?github\.com\/.+\/.+(\/\.*)*?', source):
            # Convert URL from https://github.com/owner/repo to https://github.com/owner/repo/archive/refs/heads/main.zip

            result = GitHubUtils.parse_repo_info_from_url(source)
            owner = result['owner']
            repo = result['repo']

            source = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"

            return source, 'github'

        else:
            click.echo(Colorize.error(f"Invalid source URL: {source}"))
            Log.error(f"Error: Invalid source URL: {source}")
            sys.exit(1)

    # -------------------------------------------------------------------------
    # - Create and Seed Repository
    # -------------------------------------------------------------------------

    def create_and_seed_repository(self):
        # Create repository
        self._create_repository()
        
        # Create branch structure
        self._create_dev_test_branches()
        
        if (self.source):
            # Download and extract files
            temp_dir = self._download_and_extract()
            
            # Seed repository with initial commit
            self._seed_repository(temp_dir)


    def _create_repository(self):
        # Create the repository based on the provider
        if self.provider == 'codecommit':
            self._create_repository_codecommit()
        elif self.provider == 'github':
            self._create_repository_github()

    def _create_dev_test_branches(self):
        if self.provider == 'codecommit':
            self._create_dev_test_branches_codecommit()
        elif self.provider == 'github':
            self._create_dev_test_branches_github()

    def _seed_repository(self, temp_dir: str):
        if self.provider == 'codecommit':
            self._seed_repository_codecommit(temp_dir)
        elif self.provider == 'github':
            self._seed_repository_github(temp_dir)

    def _create_repository_codecommit(self):
        try:
            click.echo(Colorize.output_with_value("Creating CodeCommit repository:", self.repo_name))
            Log.info(f"Creating CodeCommit repository: {self.repo_name}")
            response = self.codecommit_client.create_repository(
                repositoryName=self.repo_name,
                repositoryDescription=f'Repository seeded from {self.source}',
                tags=self.tags
            )
            click.echo(Colorize.output_with_value("CodeCommit Repository created:", response['repositoryMetadata']['cloneUrlHttp']))
            Log.info(f"CodeCommit Repository created: {response['repositoryMetadata']['cloneUrlHttp']}")
        except self.codecommit_client.exceptions.RepositoryNameExistsException:
            click.echo(Colorize.error(f"CodeCommit Repository {self.repo_name} already exists"))
            Log.error(f"Error: CodeCommit Repository {self.repo_name} already exists")
            sys.exit(1)
        except Exception as e:
            click.echo(Colorize.error(f"Error creating CodeCommit repository: {str(e)}"))
            Log.error(f"Error creating CodeCommit repository: {str(e)}")
            sys.exit(1)

    def _create_repository_github(self):
        try:
            click.echo(Colorize.output_with_value("Creating GitHub repository:", self.repo_name))
            Log.info(f"Creating GitHub repository: {self.repo_name}")

            # Create repository
            success = GitHubUtils.create_repo(self.repo_name, True, "asdf")

            response = {}

            if success:
                response = self.get_repository()
                click.echo(Colorize.output_with_value("GitHub Repository created:", response['repositoryMetadata']['url']))
                Log.info(f"GitHub Repository created: {response['repositoryMetadata']['url']}")
            else:
                click.echo(Colorize.error(f"Error creating GitHub repository: {str(e)}"))
                Log.error(f"Error creating GitHub repository: {str(e)}")
                sys.exit(1)
            
            return response
        
        except Exception as e:
            click.echo(Colorize.error(f"Error creating GitHub repository: {str(e)}"))
            Log.error(f"Error creating GitHub repository: {str(e)}")
            sys.exit(1)
    
    def _create_init_readme(self):
                    # Create README.md content for main branch
        readme_content = "# Hello, World\n"
        readme_content += "\nThe main and test branches are intentionally left blank except for this file.\n\nCheck out the dev branch to get started.\n"

        if self.source:
            readme_content += "\nThe dev branch of this repository was seeded from the following S3 location:\n"
            readme_content += f"{self.source}\n"
        
        # Add clone info
        try:
            clone_urls = self.get_clone_urls()
            readme_content += f"\nClone URL (HTTPS): {clone_urls.get('https', '')}\n"
            readme_content += f"\nClone URL (SSH): {clone_urls.get('ssh', '')}\n"
        except Exception as e:
            Log.error(f"Error getting repository clone urls: {str(e)}")

        # Create initial commit on main branch with README
        click.echo(Colorize.output("Creating initial README.md on main branch"))
        Log.info("Creating initial README.md on main branch")

        return readme_content


    def _create_dev_test_branches_codecommit(self):
        try:

            readme_content = self._create_init_readme()

            try:
                # Try to get main branch info
                branch_info = self.codecommit_client.get_branch(
                    repositoryName=self.repo_name,
                    branchName='main'
                )
                parent_commit_id = branch_info['branch']['commitId']

                # Create commit with README on existing main branch
                main_commit = self.codecommit_client.create_commit(
                    repositoryName=self.repo_name,
                    branchName='main',
                    parentCommitId=parent_commit_id,
                    putFiles=[{
                        'filePath': 'README.md',
                        'fileContent': readme_content,
                        'fileMode': 'NORMAL'
                    }],
                    authorName=self.get_init_commit_author(),
                    email=self.get_init_commit_email(),
                    commitMessage='Initial README.md commit'
                )
            except self.codecommit_client.exceptions.BranchDoesNotExistException:
                Log.warning("Using secondary option to crate initial commit")
                # Create initial commit with README if main branch doesn't exist
                main_commit = self.codecommit_client.create_commit(
                    repositoryName=self.repo_name,
                    branchName='main',
                    putFiles=[{
                        'filePath': 'README.md',
                        'fileContent': readme_content,
                        'fileMode': 'NORMAL'
                    }],
                    authorName=self.get_init_commit_author(),
                    email=self.get_init_commit_email(),
                    commitMessage='Initial README.md commit'
                )
            
            main_commit_id = main_commit['commitId']
            
            # Create test branch from main
            click.echo(Colorize.output("Creating test branch from main"))
            Log.info("Creating test branch from main")
            self.codecommit_client.create_branch(
                repositoryName=self.repo_name,
                branchName='test',
                commitId=main_commit_id
            )
            
            # Create dev branch from test
            click.echo(Colorize.output("Creating dev branch from test"))
            Log.info("Creating dev branch from test")
            self.codecommit_client.create_branch(
                repositoryName=self.repo_name,
                branchName='dev',
                commitId=main_commit_id
            )
            
            click.echo(Colorize.output("Successfully created branch structure"))
            Log.info("Successfully created branch structure")
            
        except Exception as e:
            click.echo(Colorize.error(f"Error creating branch structure. Check logs for more information."))
            Log.error(f"Error creating branch structure: {str(e)}")
            self.codecommit_client.delete_repository(repositoryName=self.repo_name)
            sys.exit(1)

    def _create_dev_test_branches_github(self):
        try:
            readme_content = self._create_init_readme()
            author = self.get_init_commit_author()
            email = self.get_init_commit_email()
            click.echo(Colorize.output("Creating main, test, and dev branches on GitHub"))
            Log.info("Creating main, test, and dev branches on GitHub")
            GitHubUtils.create_branch_structure(self.repo_name, readme_content, author, email)
            click.echo(Colorize.output("Successfully created branch structure"))
            Log.info("Successfully created branch structure")
        except Exception as e:
            click.echo(Colorize.error("Error creating branch structure. Check logs for more information."))
            Log.error(f"Error creating branch structure: {str(e)}")
            # Optionally: delete the repo using gh CLI if you want to clean up
            sys.exit(1)


    def _download_and_extract(self):
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, 'source.zip')

        if self.source_type == 's3':

            s3_bucket, s3_key = self.parse_s3_url(self.source)

            click.echo(Colorize.output_with_value("Downloading zip from S3:", self.source))
            Log.info(f"Downloading zip from S3: {self.source}")

            # Switch to anonymous client if the bucket is public
            s3_client = self.s3_client_anonymous if self.is_bucket_public(s3_bucket) else self.s3_client
            try:
                s3_client.download_file(s3_bucket, s3_key, zip_path)
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'AccessDenied':
                    if self.is_bucket_public(s3_bucket):
                        error_msg = f"Access denied when using anonymous access for bucket '{s3_bucket}'. The bucket may not be public or may require authentication."
                    else:
                        error_msg = f"Access denied when using authenticated access for bucket '{s3_bucket}'. Check your permissions or try using anonymous access."
                    
                    Log.error(error_msg)
                    click.echo(Colorize.error(error_msg))
                else:
                    # Re-raise other client errors
                    raise

        elif self.source_type == 'github':

            click.echo(Colorize.output_with_value("Downloading zip from GitHub:", self.source))
            Log.info(f"Downloading zip from GitHub: {self.source}")
            # Download the zip file from GitHub
            GitHubUtils.download_zip_from_url(self.source, zip_path)

        else:
            
            click.echo(Colorize.error(f"Invalid source type: {self.source_type}"))
            Log.error(f"Error: Invalid source type: {self.source_type}")
            sys.exit(1)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # For GitHub sources, identify the common prefix (outer directory)
                common_prefix = None
                if self.source_type == 'github':
                    for zip_info in zip_ref.filelist:
                        if zip_info.filename.endswith('/'):
                            # Skip directories for prefix detection
                            continue
                        
                        # Get the top-level directory
                        parts = zip_info.filename.split('/', 1)
                        if len(parts) > 1:
                            prefix = parts[0] + '/'
                            if common_prefix is None:
                                common_prefix = prefix
                            elif common_prefix != prefix:
                                common_prefix = None
                                break
                
                # Extract all files
                for zip_info in zip_ref.filelist:
                    # For GitHub sources, handle the outer directory
                    if self.source_type == 'github':
                        # Skip the root directory entry itself
                        if common_prefix and zip_info.filename == common_prefix:
                            continue
                            
                        # Remove the common prefix if it exists
                        if common_prefix and zip_info.filename.startswith(common_prefix):
                            rel_path = zip_info.filename[len(common_prefix):]
                            output_path = Path(temp_dir) / rel_path
                        else:
                            output_path = Path(temp_dir) / zip_info.filename
                    else:
                        # Standard path for non-GitHub sources
                        output_path = Path(temp_dir) / zip_info.filename
                    
                    if zip_info.filename.endswith('/'):
                        output_path.mkdir(parents=True, exist_ok=True)
                        continue
                        
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with zip_ref.open(zip_info) as source:
                        content = source.read()
                        
                        text_extensions = {
                            # Documentation and Markup
                            '.txt', '.md', '.markdown', '.rst', '.adoc', '.asciidoc', '.wiki',
                            
                            # Web and Styling
                            '.html', '.htm', '.xhtml', '.css', '.scss', '.sass', '.less',
                            '.svg', '.xml', '.xsl', '.xslt', '.wsdl', '.dtd',
                            
                            # Programming Languages
                            '.py', '.pyw', '.py3', '.pyi', '.pyx',  # Python
                            '.js', '.jsx', '.ts', '.tsx', '.mjs',    # JavaScript/TypeScript
                            '.java', '.kt', '.kts', '.groovy',       # JVM
                            '.c', '.h', '.cpp', '.hpp', '.cc',       # C/C++
                            '.cs', '.csx',                           # C#
                            '.rb', '.rbw', '.rake', '.gemspec',      # Ruby
                            '.php', '.phtml', '.php3', '.php4',      # PHP
                            '.go', '.rs', '.r', '.pl', '.pm',        # Go, Rust, R, Perl
                            
                            # Shell and cli
                            '.sh', '.bash', '.zsh', '.fish',
                            '.bat', '.cmd', '.ps1', '.psm1',
                            
                            # Configuration
                            '.json', '.yaml', '.yml', '.toml', '.tml',
                            '.ini', '.cfg', '.conf', '.config',
                            '.env', '.properties', '.prop',
                            '.xml', '.plist',
                            
                            # Build and Project
                            '.gradle', '.maven', '.pom',
                            '.project', '.classpath',
                            '.editorconfig', '.gitignore', '.gitattributes',
                            'Dockerfile', 'Makefile', 'Jenkinsfile',
                            
                            # Data Formats
                            '.csv', '.tsv', '.sql', '.graphql', '.gql',
                            
                            # Lock Files
                            '.lock', '.lockfile',
                            
                            # Template Files
                            '.template', '.tmpl', '.j2', '.jinja', '.jinja2',
                            
                            # AWS and Cloud
                            '.tf', '.tfvars',              # Terraform
                            '.template-config',            # AWS CloudFormation
                            '.cfn.yaml', '.cfn.json',     # AWS CloudFormation
                            '.sam.yaml', '.sam.json',      # AWS SAM
                            
                            # Misc
                            '.log', '.diff', '.patch',
                            '.lst', '.tex', '.bib',
                            '.manifest', '.pdl', '.po'
                        }

                        is_text_file = (output_path.suffix.lower() in text_extensions and 
                                        not self._is_binary_string(content))

                        if output_path.exists():
                            output_path.unlink()
                        
                        if is_text_file:
                            try:
                                decoded_content = content.decode('utf-8')
                                output_path.write_text(decoded_content, encoding='utf-8')
                            except UnicodeDecodeError:
                                output_path.write_bytes(content)
                        else:
                            output_path.write_bytes(content)
                            
            os.remove(zip_path)
            
            # Log the number of extracted files
            file_count = 0
            for _, _, files in os.walk(temp_dir):
                file_count += len(files)
            Log.info(f"Extracted {file_count} files to {temp_dir}")
            click.echo(Colorize.output_with_value("Extracted files:", str(file_count)))
            
            return temp_dir
            
        except Exception as e:
            click.echo(Colorize.error(f"Error in download and extract process. Check logs for more information."))
            Log.error(f"Error in download and extract process: {str(e)}")
            self.codecommit_client.delete_repository(repositoryName=self.repo_name)
            shutil.rmtree(temp_dir, ignore_errors=True)
            sys.exit(1)

    def _seed_collect_files(self, temp_dir: str) -> List[Dict]:
        """Collect all files in the temp directory and return a list of file dictionaries"""
        all_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, temp_dir)
                
                try:
                    with open(full_path, 'rb') as f:
                        content = f.read()
                        
                    try:
                        file_content = content.decode('utf-8')
                    except UnicodeDecodeError:
                        file_content = base64.b64encode(content).decode('utf-8')
                        
                    all_files.append({
                        'filePath': relative_path,
                        'fileContent': file_content,
                        'fileMode': 'NORMAL'
                    })
                except Exception as e:
                    click.echo(Colorize.error(f"Error processing file {relative_path}"))
                    Log.error(f"Error processing file {relative_path}: {str(e)}")
                    self.codecommit_client.delete_repository(repositoryName=self.repo_name)
                    sys.exit(1)

        return all_files

    def _seed_repository_codecommit(self, temp_dir):
        try:
            # Collect all files to be processed
            all_files = self._seed_collect_files(temp_dir)

            # Process files in batches of 100
            batch_size = 100
            total_files = len(all_files)
            processed_files = 0
            seed_branch = "dev"

            click.echo(Colorize.output(f"Seeding repository with {total_files} files"))
            Log.info(f"Creating initial commit with {total_files} files")

            # Get the initial parent commit ID
            try:
                branch_info = self.codecommit_client.get_branch(
                    repositoryName=self.repo_name,
                    branchName=seed_branch
                )
                parent_commit_id = branch_info['branch']['commitId']
            except self.codecommit_client.exceptions.BranchDoesNotExistException:
                parent_commit_id = None

            # Process files in batches
            while processed_files < total_files:
                start_idx = processed_files
                end_idx = min(processed_files + batch_size, total_files)
                current_batch = all_files[start_idx:end_idx]
                
                click.echo(Colorize.output(f"Processing files {start_idx + 1} to {end_idx} of {total_files}"))
                Log.info(f"Processing batch of {len(current_batch)} files")

                try:
                    commit_response = self.codecommit_client.create_commit(
                        repositoryName=self.repo_name,
                        branchName=seed_branch,
                        parentCommitId=parent_commit_id if parent_commit_id else None,
                        putFiles=current_batch,
                        authorName=self.get_init_commit_author(),
                        email=self.get_init_commit_email(),
                        commitMessage=f'Seeding repository (batch {start_idx + 1}-{end_idx} of {total_files} files)'
                    )
                    
                    # Update parent commit ID for the next batch
                    parent_commit_id = commit_response['commitId']
                    processed_files = end_idx
                    
                    click.echo(Colorize.success(f"Successfully committed batch {start_idx + 1}-{end_idx}"))
                    Log.info(f"Successfully committed batch {start_idx + 1}-{end_idx}")
                    
                except Exception as e:
                    click.echo(Colorize.error(f"Error creating commit for batch {start_idx + 1}-{end_idx}"))
                    Log.error(f"Error creating commit: {str(e)}")
                    self.codecommit_client.delete_repository(repositoryName=self.repo_name)
                    sys.exit(1)

            Log.info(f"Repository {self.repo_name} seeded successfully!")
            Log.info(f"Total files processed: {processed_files}")
            click.echo(Colorize.success(f"Repository {self.repo_name} seeded successfully!"))
            click.echo(Colorize.output_with_value("Total files processed:", str(processed_files)))
            
        except Exception as e:
            click.echo(Colorize.error(f"Error in seeding process. Check logs for more information."))
            Log.error(f"Error in seeding process: {str(e)}")
            self.codecommit_client.delete_repository(repositoryName=self.repo_name)
            sys.exit(1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _seed_repository_github(self, temp_dir):
        try:
            # Collect all files to be processed
            all_files = self._seed_collect_files(temp_dir)

            total_files = len(all_files)
            seed_branch = "dev"

            click.echo(Colorize.output(f"Seeding repository with {total_files} files"))
            Log.info(f"Creating initial commit with {total_files} files")

            # Create a temporary directory for git operations
            git_dir = tempfile.mkdtemp()

            GitHubUtils.create_init_commit(all_files, self.repo_name, seed_branch, self.get_init_commit_author(), self.get_init_commit_email(), git_dir)

            Log.info(f"Repository {self.repo_name} seeded successfully!")
            Log.info(f"Total files processed: {total_files}")
            click.echo(Colorize.success(f"Repository {self.repo_name} seeded successfully!"))
            click.echo(Colorize.output_with_value("Total files processed:", str(total_files)))
            
        except Exception as e:
            click.echo(Colorize.error(f"Error in seeding process. Check logs for more information."))
            Log.error(f"Error in seeding process: {str(e)}")
            sys.exit(1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)



    def _is_binary_string(self, bytes_data, sample_size=1024):
        """Returns true if the bytes_data appears to be binary rather than text."""
        if not bytes_data:
            return False
        
        # Take a sample of the file to reduce processing time for large files
        sample = bytes_data[:sample_size]
        text_characters = bytes(b'').join(bytes([i]) for i in range(32, 127)) + b'\n\r\t\f\b'
        
        # If more than 30% non-text characters, assume binary
        non_text = bytes_data.translate(None, text_characters)
        return len(non_text) / len(sample) > 0.30

    # -------------------------------------------------------------------------
    # - Prompts: Application Starter
    # -------------------------------------------------------------------------

    def discover_s3_file_list(self) -> List[str]:
        """Discover available app starters in the app starter directory"""
        file_list = []
        # loop through self.settings.get('app_starters', []), access the bucket, and append to file_list
        for s3_file_list_location in self.settings.get('app_starters', []):
            try:
                bucket = s3_file_list_location['bucket']
                prefix = s3_file_list_location['prefix'].strip('/')
                anonymous = s3_file_list_location.get('anonymous', False)
                response = None

                Log.info(f"Discovering app starters from s3://{bucket}/{prefix}")

                # Switch to anonymous client if the bucket is public
                s3_client = self.s3_client_anonymous if anonymous else self.s3_client
                try:
                    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}")
                except botocore.exceptions.ClientError as e:
                    if e.response['Error']['Code'] == 'AccessDenied':
                        if anonymous:
                            error_msg = f"Access denied when using anonymous access for bucket '{bucket}'. The bucket may not be public or may require authentication."
                        else:
                            error_msg = f"Access denied when using authenticated access for bucket '{bucket}'. Check your permissions or try using anonymous access."
                        
                        Log.error(error_msg)
                        click.echo(Colorize.error(error_msg))
                        continue
                    else:
                        # Re-raise other client errors
                        raise

                for obj in response.get('Contents', []):
                    if obj['Key'].endswith('.zip'):
                        #Log.info(f"Found app starter: {obj}")
                        s3_uri = f"s3://{bucket}/{obj['Key']}"
                        file_list.append(s3_uri)

            except Exception as e:
                Log.error(f"Error discovering application starters from S3: {e}")
                click.echo(Colorize.error("Error discovering application starters from S3. Check logs for more info."))
                raise

        return file_list
    
    # -------------------------------------------------------------------------
    # - Prompts: Tags
    # -------------------------------------------------------------------------
    
    def get_default_tags(self) -> Dict:
        """Get the default tags for the repository

        Returns:
            Dict: Default tags for the repository
        """
        try:
            default_tags = TagUtils.get_default_tags(self.settings, self.defaults)
            return default_tags
        except Exception as e:
            Log.error(f"Error getting default tags: {e}")
            raise

    # -------------------------------------------------------------------------
    # - Getters, Naming, and File Locations
    # -------------------------------------------------------------------------

    def get_settings_dir(self) -> Path:
        """Get the settings directory path"""
        # Get the cli directory in a cross-platform way
        script_dir = Path(__file__).resolve().parent
        return script_dir.parent / SETTINGS_DIR
    
    def is_bucket_public(self, bucket: str) -> bool:
        """Buckets are presumed to be private unless otherwise specified
        with a "anonymous" tag in the settings.json file.
        Given a bucket name, check the settings to see if it is public.
        
        Args:
            bucket (str): The S3 bucket name
        Returns:
            bool: True if the bucket is public, False otherwise
        """
        # Check if the bucket is public
        for s3_file_list_location in self.settings.get('app_starters', []):
            if s3_file_list_location['bucket'] == bucket:
                return s3_file_list_location.get('anonymous', False)
        return False
    
    def get_repository(self) -> Dict:
        # get repository information
        try:
            if self.provider == "codecommit":
                return self.codecommit_client.get_repository(repositoryName=self.repo_name)
            elif self.provider == "github":
                return GitHubUtils.get_repository(self.repo_name)
            else:
                raise ValueError(f"Invalid provider: {self.provider}")
        except Exception as e:
            Log.error(f"Error getting repository information: {e}")
            raise

    def get_clone_urls(self) -> Dict:
        """Get the clone URLs for the repository

        Returns:
            Dict: Clone URLs for the repository
        """
        try:
            if (self.clone_url_https == None and self.clone_url_ssh == None):
                repo_info = self.get_repository()
                repo_meta = repo_info.get('repositoryMetadata', {})
                self.clone_url_https = repo_meta.get('cloneUrlHttp', None)
                self.clone_url_ssh = repo_meta.get('cloneUrlSsh', None)

            return {
                'https': self.clone_url_https,
                'ssh': self.clone_url_ssh
            }

        except Exception as e:
            Log.error(f"Error getting clone URLs: {e}")
            raise
    
    def repository_exists(self) -> bool:
        """Check if the repository already exists in CodeCommit.

        Returns:
            bool: True if repository exists, False otherwise
        """
        if self.provider == "codecommit":
            try:
                self.codecommit_client.get_repository(repositoryName=self.repo_name)
                return True
            except self.codecommit_client.exceptions.RepositoryDoesNotExistException:
                return False
            except Exception as e:
                Log.error(f"Error checking CodeCommit repository existence: {str(e)}")
                raise
        elif self.provider == "github":
            try:
                return GitHubUtils.repository_exists(self.repo_name)
            except Exception as e:
                Log.error(f"Error checking GitHub repository existence: {e}")
                raise

    def get_creator_tag(self) -> str:
        """Access the Creator tag if there is one. Can be used for the initial commit
        
        Returns:
            str: The value of the Creator or Owner tag if present
        """
        
        creator = ''

        try:
            if self.tags.get('Creator'):
                creator = self.tags.get('Creator')
            elif self.tags.get('Owner'):
                creator = self.tags.get('Owner')

            return creator
        except Exception as e:
            Log.error(f"Error getting creator tag: {e}")
            raise

    def get_init_commit_author(self) -> str:
        """Get the author for the initial commit

        Returns:
            str: The author for the initial commit
        """

        author_name = "Repository Creator (via CLI)"
        creator = self.get_creator_tag()
        if creator:
            author_name += f" ({creator})"

        return author_name
        
    def get_init_commit_email(self) -> str:
        """Get the author email for the initial commit"""

        author_email = "repo.creator@example.com"
        creator = self.get_creator_tag()
        contact = self.tags.get('Contact', None)

        regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

        if(contact and re.fullmatch(regex, contact)):
            author_email = contact
        elif (creator and re.fullmatch(regex, creator)):
            author_email = creator
        elif (contact):
            # remove all spaces and special characters from contact
            contact = re.sub(r'[^A-Za-z0-9._-]', '', contact)
            author_email = f"{contact}@example.com"
        elif (creator):
            # remove all spaces and special characters from creator
            creator = re.sub(r'[^A-Za-z0-9._-]', '', creator)
            author_email = f"{creator}@example.com"

        return author_email


    # -------------------------------------------------------------------------
    # - Setters
    # -------------------------------------------------------------------------

    def set_source(self, source: str) -> None:
        """Set the zip source for the repository"""
        self.source, self.source_type = self._determine_source(source)

    def set_tags(self, tags: Union[Dict, List]) -> Dict:
        """Set the tags for the repository
        
        Args:
            Union[Dict, List] tags: Either a dictionary of tags {"key": "value"} or 
                a list of tag dictionaries [{"Key": "key", "Value": "value"}]
        
        Returns:
            Dict: Normalized dictionary of tags
        
        Raises:
            TypeError: If tags is neither a dict nor a list
            ValueError: If list items don't contain required Key/Value pairs
        """
        if isinstance(tags, list):
            # Convert AWS-style tag list to dictionary
            normalized_tags = {}
            for tag in tags:
                if not isinstance(tag, dict) or 'Key' not in tag or 'Value' not in tag:
                    raise ValueError("List items must be dictionaries with 'Key' and 'Value' fields")
                normalized_tags[tag['Key']] = tag['Value']
            self.tags = normalized_tags
        elif isinstance(tags, dict):
            self.tags = tags.copy()  # Make a copy to avoid modifying the original
        else:
            Log.error(f"Tags must be either a dictionary or a list of key-value pairs. Got {type(tags)} instead.")
            raise TypeError("Tags must be either a dictionary or a list of key-value pairs")
        
        return self.tags
    


    
# =============================================================================
# ----- Main function ---------------------------------------------------------
# =============================================================================

EPILOG = """
Supports both AWS SSO and IAM credentials.
For SSO users, credentials will be refreshed automatically.
For IAM users, please ensure your credentials are valid using 'aws configure'.

For default parameter and tag values, add default.json files to the defaults directory.
For settings, update settings.json in the defaults directory.

Examples:

    # Create repository and choose from provided application starters
    create_repo.py your-webapp

    # Create repository using GitHub as the provider (override default specified in settings.json)
    # Note use of <owner>/<repo-name> format for GitHub
    create_repo.py <owner>/your-webapp --provider github

    # Create repository using GitHub as the provider (override default specified in settings.json)
    create_repo.py your-webapp --provider codecommit

    # Create repository and load code from zip on S3
    create_repo.py <repo-name> --source <s3://bucket/path/to/file.zip>

    # Create repository and load code from GitHub repo
    create_repo.py <repo-name> --source https://github.com/<user>/<repo>

    # Create repository and load code from GitHub latest release
    create_repo.py <repo-name> --source https://github.com/<user>/<repo>/releases/

    # Create repository and load code from GitHub specific release
    create_repo.py <repo-name> --source https://github.com/<user>/<repo>/releases/tag/<tag>
"""

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description='Create and seed a CodeCommit repository from an S3 zip file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(EPILOG)
    )

    # Positional arguments
    parser.add_argument('repository_name',
                        type=str,
                        help='Name of the CodeCommit repository to create')
    
    # Optional Named Arguments
    parser.add_argument('--source',
                        type=str,
                        required=False,
                        help='S3 URL of the zip file, GitHub repository URL, or GitHub release URL')

    parser.add_argument('--profile',
                        type=str,
                        required=False,
                        default=None,
                        help='AWS profile name (default: default profile)')
    parser.add_argument('--region',
                        type=str,
                        required=False,
                        default=None,
                        help='AWS region (default: default region from profile)')
    parser.add_argument('--prefix',
                        type=str,
                        required=False,
                        default=None,
                        help='Prefix to use for default tags. The repository name DOES NOT need the prefix.')
    parser.add_argument('--provider',
                        type=str,
                        required=False,
                        choices=VALID_PROVIDERS,
                        default=None,
                        help=f'Type of repository to create. {VALID_PROVIDERS}.')
    
    # Optional Flags
    parser.add_argument('--no-browser',
                        action='store_true',  # This makes it a flag
                        default=False,        # Default value when flag is not used
                        help='For an AWS SSO login session, whether or not to set the --no-browser flag.')
    
    args = parser.parse_args()
        
    return args

def main():
    
    args = parse_args()
    Log.info(f"{sys.argv}")
    Log.info(f"Version: {VERSION}")

    print()
    click.echo(Colorize.divider("="))
    click.echo(Colorize.output_bold(f"Repository Creator ({VERSION})"))
    click.echo(Colorize.divider("="))
    print()

    try:
        repo_creator = RepositoryCreator(
            args.repository_name, args.source, 
            args.region, args.profile, 
            args.prefix, args.provider,
            args.no_browser
        )
        
    except TokenRetrievalError as e:
        ConsoleAndLog.error(f"AWS authentication error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        ConsoleAndLog.error(f"Error initializing repository creator: {str(e)}")
        sys.exit(1)

    # check if repo already exists
    if repo_creator.repository_exists():
        Log.error(f"Repository {args.repository_name} already exists")
        click.echo(Colorize.error(f"Repository {args.repository_name} already exists"))
        sys.exit(1)
    
    # prompt for starter app if no args.source
    try:
        if args.source is None:
            file_list = repo_creator.discover_s3_file_list()
            app_starter_file = FileNameListUtils.select_from_file_list(file_list, True, heading_text="Available application starters", prompt_text="Enter an app starter number")
            repo_creator.set_source(app_starter_file)
    except KeyboardInterrupt:
        ConsoleAndLog.info("Repository creation cancelled")
        sys.exit(1)
    except Exception as e:
        ConsoleAndLog.error(f"Error selecting application starter: {str(e)}")
        sys.exit(1)

    # prompt for tags
    try:
        repo_creator.set_tags(TagUtils.prompt_for_tags(repo_creator.get_default_tags()))
    except KeyboardInterrupt:
        ConsoleAndLog.info("Repository creation cancelled")
        sys.exit(1)
    except Exception as e:
        ConsoleAndLog.error(f"Error setting tags: {str(e)}")
        sys.exit(1)

    # create repo and seed with code
    try:
        print()
        repo_creator.create_and_seed_repository()
        print()
        click.echo(Colorize.divider())
        print()
    except Exception as e:
        ConsoleAndLog.error(f"Error creating and seeding repository: {str(e)}")
        sys.exit(1)

    clone_urls = repo_creator.get_clone_urls()

    click.echo(Colorize.output_with_value("Clone URL (HTTPS):", clone_urls.get('https', '')))
    click.echo(Colorize.output_with_value("Clone URL (SSH):", clone_urls.get('ssh', '')))
    print()
    click.echo(Colorize.divider("="))
    print()

if __name__ == "__main__":
    main()
