#!/usr/bin/env python3

VERSION = "v0.1.3/2025-08-26"
# Created by Chad Kluck with AI assistance from Amazon Q Developer
# GitHub Copilot assisted in color formats of output and prompts

# Usage Information:
# deploy.py -h

# Full Documentation:
# https://github.com/63klabs/atlantis-sam-config-scripts/

import sys
import os
import tempfile
import subprocess
import argparse
import traceback
import tomli  # Make sure to pip install tomli
from pathlib import Path
from typing import Optional
from botocore.exceptions import ClientError

import boto3
import botocore

from lib.aws_session import AWSSessionManager
from lib.logger import ScriptLogger, ConsoleAndLog, Log
from lib.atlantis import DefaultsLoader
from lib.gitops import Git

if sys.version_info[0] < 3:
    sys.stderr.write("Error: Python 3 is required\n")
    sys.exit(1)


# Initialize logger for this script
ScriptLogger.setup('deploy')

SAMCONFIG_DIR = "samconfigs"
SETTINGS_DIR = "defaults"

class TemplateDeployer:
    def __init__(self, infra_type: str, prefix: str, project_id: str, stage_id: Optional[str] = "default", profile: Optional[str] = None, no_browser: Optional[bool] = False) -> None:
        self.infra_type = infra_type
        self.prefix = prefix
        self.project_id = project_id
        self.stage_id = stage_id
        self.profile = profile
        self.override_confirm_changeset = False

        self.aws_session = AWSSessionManager(profile, None, no_browser)
        self.s3_client = self.aws_session.get_client('s3')
        # self.s3_client_anonymous = self.aws_session.get_client('s3', config=botocore.client.Config(signature_version=botocore.UNSIGNED))
        self.s3_client_anonymous = boto3.client('s3', config=botocore.client.Config(signature_version=botocore.UNSIGNED))

        config_loader = DefaultsLoader(
            settings_dir=self.get_settings_dir(),
            prefix=self.prefix,
            project_id=self.project_id,
            infra_type=self.infra_type
        )

        self.settings = config_loader.load_settings()

    def get_template_from_config(self) -> str:
        """
        Read template URL from samconfig.toml file.
            
        Returns:
            str: Template URL from config file
            
        Raises:
            ValueError: If template parameter is not found in config
        """

        # Log the constructed paths
        ConsoleAndLog.info(f"Config directory: {self.get_samconfig_dir()}")
        ConsoleAndLog.info(f"Config file: {self.get_samconfig_file_name()}")
        # Verify config directory exists
        config_path = self.get_samconfig_dir()
        if not config_path.exists():
            ConsoleAndLog.error(f"SAM Config directory not found: {self.get_samconfig_dir()}")
            return 1
        
        try:
            config_file = self.get_samconfig_file_path()
            with open(config_file, 'rb') as f:
                config = tomli.load(f)
            
            # Look for template parameter in stage-specific section
            template_param = config.get('default', {}).get('deploy', {}).get('parameters', {}).get('template_file')
            stage_template = config.get(self.stage_id, {}).get('deploy', {}).get('parameters', {}).get('template_file')
            
            # Use stage-specific template if available, otherwise fall back to default
            template_url = stage_template or template_param
            
            if not template_url:
                raise ValueError(f"Template parameter not found in config file for stage '{self.stage_id}'")
                
            return template_url
            
        except FileNotFoundError:
            raise ValueError(f"Config file not found: {config_path}")
        except tomli.TOMLDecodeError as e:
            raise ValueError(f"Invalid TOML format in config file: {str(e)}")

    def parse_s3_url(self, s3_url: str) -> tuple[str, str, Optional[str]]:
        """
        Parse S3 URL into bucket, key, and optional version ID.
        
        Args:
            s3_url: The S3 URL to parse (e.g., s3://bucket/key or s3://bucket/key?versionId=abc123)
            
        Returns:
            Tuple containing (bucket_name, object_key, version_id)
            
        Raises:
            ValueError: If the S3 URL format is invalid
        """
        if not s3_url.startswith('s3://'):
            raise ValueError(f"Invalid S3 URL format: {s3_url}")
        
        # Split URL and query parameters
        url_parts = s3_url.replace('s3://', '').split('?')
        path_parts = url_parts[0].split('/')
        
        if len(path_parts) < 2:
            raise ValueError(f"Invalid S3 URL format: {s3_url}")
        
        bucket = path_parts[0]
        key = '/'.join(path_parts[1:])
        version_id = None
        
        # Parse query parameters for versionId
        if len(url_parts) > 1:
            query_params = dict(param.split('=') for param in url_parts[1].split('&'))
            version_id = query_params.get('versionId')
            
        return bucket, key, version_id

    def verify_s3_object_exists(self, bucket: str, key: str, version_id: Optional[str] = None) -> bool:
        """
        Verify S3 object exists and is accessible.
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            version_id: Optional version ID
            
        Returns:
            bool: True if object exists and is accessible, False otherwise
        """

        # Switch to anonymous client if the bucket is public
        s3_client = self.s3_client_anonymous if self.is_bucket_public(bucket) else self.s3_client
        try:
            params = {'Bucket': bucket, 'Key': key}
            if version_id:
                params['VersionId'] = version_id
            
            s3_client.head_object(**params)
            return True

        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                if self.is_bucket_public(bucket):
                    error_msg = f"Access denied when using anonymous access for bucket '{bucket}'. The bucket may not be public or may require authentication."
                else:
                    error_msg = f"Access denied when using authenticated access for bucket '{bucket}'. Check your permissions or try using anonymous access."
                
                ConsoleAndLog.error(error_msg)
            elif e.response['Error']['Code'] == '404':
                ConsoleAndLog.error(f"Template file not found: s3://{bucket}/{key}" + 
                                (f"?versionId={version_id}" if version_id else ""))
            else:
                # Re-raise other client errors
                ConsoleAndLog.error(f"Error accessing S3: {str(e)}")
                raise

            return False
        
    def deploy_with_temp_template(self, template_path: str) -> int:
        """
        Deploy template from either S3 or local file.
        
        Args:
            template_path: Either S3 URL (s3://) or local file path
            
        Returns:
            int: Return code from sam deploy
        """
        try:
            # Ensure config file exists
            config_path = self.get_samconfig_file_path()
            if not config_path.exists():
                ConsoleAndLog.error(f"Config file not found: {config_path}")
                return 1

            if template_path.startswith('s3://'):
                # Handle S3 template
                bucket, key, version_id = self.parse_s3_url(template_path)

                
                # Verify template exists
                if not self.verify_s3_object_exists(bucket, key, version_id):
                    return 1

                # Create temp directory for S3 download
                with tempfile.TemporaryDirectory() as temp_dir:
                    ConsoleAndLog.info(f"Created temporary directory: {temp_dir}")
                    temp_path = Path(temp_dir) / "template.yml"
                    ConsoleAndLog.info(f"Downloading template from s3://{bucket}/{key}" +
                                (f"?versionId={version_id}" if version_id else ""))
                    
                    # Switch to anonymous client if the bucket is public
                    s3_client = self.s3_client_anonymous if self.is_bucket_public(bucket) else self.s3_client

                    try:
                        get_args = {
                            'Bucket': bucket,
                            'Key': key
                        }
                        if version_id:
                            get_args['VersionId'] = version_id

                        response = s3_client.get_object(**get_args)
                        with open(temp_path, 'wb') as f:
                            f.write(response['Body'].read())

                    except botocore.exceptions.ClientError as e:
                        if e.response['Error']['Code'] == 'AccessDenied':
                            if self.is_bucket_public(bucket):
                                error_msg = f"Access denied when using anonymous access for bucket '{bucket}'. The bucket may not be public or may require authentication."
                            else:
                                error_msg = f"Access denied when using authenticated access for bucket '{bucket}'. Check your permissions or try using anonymous access."
                            
                            ConsoleAndLog.error(error_msg)

                        else:
                            ConsoleAndLog.error(f"Failed to download template: {str(e)}")
                        
                        return 1

                    return self._run_sam_deploy(temp_path, config_path)
            else:
                # Handle local template
                local_template_path = self.config_dir / template_path
                if not local_template_path.exists():
                    ConsoleAndLog.error(f"Local template file not found: {local_template_path}")
                    return 1
                    
                ConsoleAndLog.info(f"Using local template: {local_template_path}")
                return self._run_sam_deploy(local_template_path, config_path)

        except Exception as e:
            ConsoleAndLog.error(f"Deployment failed: {str(e)}")
            raise

    def enable_stack_termination_protection(self):
        """
        Enable termination protection for the stack.
        """
        ConsoleAndLog.info("Enabling termination protection for the stack...")
        try:
            # Get the stack name from samconfig.toml
            with open(self.get_samconfig_file_path(), 'rb') as f:
                config = tomli.load(f)

            stage = self.stage_id if self.stage_id else 'default'
            stack_name = config.get(stage, {}).get('deploy', {}).get('parameters', {}).get('stack_name')

            if not stack_name:
                ConsoleAndLog.error("Stack name not found in samconfig.toml")
                return

            # Enable termination protection
            self.aws_session.get_client('cloudformation').update_termination_protection(
                EnableTerminationProtection=True,
                StackName=stack_name
            )
            ConsoleAndLog.info("Termination protection enabled.")

        except Exception as e:
            ConsoleAndLog.error(f"Failed to enable termination protection: {str(e)}")
            raise


    def _run_sam_deploy(self, template_path: Path, config_path: Path) -> int:
        """
        Execute the SAM deploy command.
        
        Args:
            template_path: Path to the template file
            config_path: Path to the config file
            
        Returns:
            int: Return code from sam deploy
        """
        sam_cmd = [
            "sam.cmd" if os.name == 'nt' else "sam",
            "deploy",
            "--config-env", self.stage_id,
            "--template-file", str(template_path),
            "--config-file", str(config_path),
            "--no-fail-on-empty-changeset"
        ]
        
        if self.override_confirm_changeset:
            sam_cmd.append("--no-confirm-changeset")

        if self.profile:
            sam_cmd.extend(["--profile", self.profile])
        
        ConsoleAndLog.info(f"Executing: {' '.join(sam_cmd)}")
        
        result = subprocess.run(
            sam_cmd,
            cwd=self.get_samconfig_dir(),
            check=False,
            stdout=None,
            stderr=None,
            shell=True if os.name == 'nt' else False,
            env={
                **os.environ,
                'FORCE_COLOR': '1',
                'TERM': 'xterm-256color' if os.name != 'nt' else os.environ.get('TERM', '')
            }
        )
        
        return result.returncode

    # -------------------------------------------------------------------------
    # - File Locations and Names
    # -------------------------------------------------------------------------

    def get_samconfig_dir(self) -> Path:
        """Get the samconfig directory path"""
        # Get the script's directory in a cross-platform way
        script_dir = Path(__file__).resolve().parent
        return script_dir.parent / SAMCONFIG_DIR / self.prefix / self.project_id 
    
    def get_samconfig_file_name(self) -> str:
        """Get the samconfig file name"""
        return f"samconfig-{self.prefix}-{self.project_id}-{self.infra_type}.toml"
    
    def get_samconfig_file_path(self) -> Path:
        """Get the samconfig file path"""
        return self.get_samconfig_dir() / self.get_samconfig_file_name()
        
    def get_settings_dir(self) -> Path:
        """Get the settings directory path"""
        # Get the script's directory in a cross-platform way
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
        for s3_file_list_location in self.settings.get('templates', []):
            if s3_file_list_location['bucket'] == bucket:
                return s3_file_list_location.get('anonymous', False)
        return False
    
# =============================================================================
# ----- Main function ---------------------------------------------------------
# =============================================================================

EPILOG = """
Supports both AWS SSO and IAM credentials.
For SSO users, credentials will be refreshed automatically.
For IAM users, please ensure your credentials are valid using 'aws configure'.

Examples:

    # Deploy service-role for acme prefix and project
    deploy.py service-role acme project123

    # Deploy pipeline for specific project and stage
    deploy.py pipeline acme project123 dev

    # With different AWS profile
    deploy.py service-role acme project123 --profile myprofile

    # Headless mode (no prompts, auto git ops, force confirm_changeset=false)
    deploy.py pipeline acme project123 dev --headless

    # Optional flags:
    --no-browser
        For an AWS SSO login session, whether or not to set the --no-browser flag.

    --headless
        Run in headless mode for CI/CD pipelines and automation. Suppresses all
        interactive prompts, automatically performs git pull before deployment and
        git commit and push after successful deployment, and overrides
        confirm_changeset to false regardless of samconfig value.
"""
        
def parse_args() -> argparse.Namespace:
    # Get the script's directory in a cross-platform way
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description='Deploy CloudFormation template from S3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(EPILOG)
    )
    
    # Positional arguments
    parser.add_argument('infra_type',
                        help='Type of infrastructure to deploy (e.g., pipeline)')
    parser.add_argument('prefix',
                        help='Prefix/org unit (e.g., acme)')
    parser.add_argument('project_id',
                        help='Project ID')
    parser.add_argument('stage_id',
                        nargs='?',  # Makes it optional
                        default='default',
                        help='Stage ID (optional, defaults to "default")')
    
    # Optional Named Arguments
    parser.add_argument('--profile', 
                        help='AWS profile name to use',
                        default=None)
    
    # Optional Flags
    parser.add_argument('--no-browser',
                        action='store_true',  # This makes it a flag
                        default=False,        # Default value when flag is not used
                        help='For an AWS SSO login session, whether or not to set the --no-browser flag.')
    parser.add_argument('--headless',
                        action='store_true',
                        default=False,
                        help='Run in headless mode: suppress prompts, auto git ops, force confirm_changeset=false')

    args = parser.parse_args()
    
    return args

def main() -> int:
    
    args = parse_args()
    Log.info(f"{sys.argv}")
    Log.info(f"Version: {VERSION}")

    # Git pull — headless performs automatically, interactive prompts
    if args.headless:
        Git.headless_git_pull()
    else:
        Git.prompt_git_pull()

    # Initialize deployer with profile if specified
    deployer = TemplateDeployer(
        args.infra_type, args.prefix, 
        args.project_id, args.stage_id, 
        args.profile, args.no_browser
    )
    
    # Run deployment
    try:
        # Get template URL from config file
        template_url = deployer.get_template_from_config()
        ConsoleAndLog.info(f"Template URL from config: {template_url}")

        # In headless mode, override confirm_changeset to suppress prompts
        if args.headless:
            deployer.override_confirm_changeset = True
        
        exit_code = deployer.deploy_with_temp_template(template_url)

        if exit_code == 0:
            # enable stack termination protection
            deployer.enable_stack_termination_protection()

            ConsoleAndLog.info("Deployment script completed without errors.")
            # Git commit and push
            commit_message = f"Deployed {args.infra_type} {args.prefix}-{args.project_id}"
            if args.stage_id:
                commit_message += f"-{args.stage_id}"

            if args.headless:
                Git.headless_git_commit_and_push(commit_message)
            else:
                print()
                Git.git_commit_and_push(commit_message)
        else:
            ConsoleAndLog.error(f"Deployment script failed with exit code {exit_code}")
        return exit_code
    except ValueError as e:
        ConsoleAndLog.error(str(e))
        return 1
    except Exception as e:
        ConsoleAndLog.error(f"Deployment script failed: {str(e)}")
        ConsoleAndLog.error(f"Error occurred at:\n{traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    exit(main())