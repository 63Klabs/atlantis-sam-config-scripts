#!/usr/bin/env python3

VERSION = "v0.2.0/2026-08-06"
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
import yaml
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
        """Deploy template from either S3 or local file.

        If the template contains Fn::Transform: AWS::Include entries with S3
        Location URLs, downloads the referenced modules to local temp files,
        rewrites Location values to relative paths, runs sam package to resolve
        the includes natively, then passes the packaged output to sam deploy.
        Templates without S3 includes proceed directly to sam deploy unchanged.

        Args:
            template_path: Either an S3 URL (s3://) or a local file path
                relative to the samconfig directory.

        Returns:
            Exit code from sam deploy (0 for success, non-zero for failure).
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
                    temp_dir_path = Path(temp_dir)
                    ConsoleAndLog.info(f"Created temporary directory: {temp_dir}")
                    temp_template_path = temp_dir_path / "template.yml"
                    ConsoleAndLog.info(
                        f"Downloading template from s3://{bucket}/{key}"
                        + (f"?versionId={version_id}" if version_id else "")
                    )

                    # Switch to anonymous client if the bucket is public
                    s3_client = (
                        self.s3_client_anonymous
                        if self.is_bucket_public(bucket)
                        else self.s3_client
                    )

                    try:
                        get_args = {'Bucket': bucket, 'Key': key}
                        if version_id:
                            get_args['VersionId'] = version_id

                        response = s3_client.get_object(**get_args)
                        with open(temp_template_path, 'wb') as f:
                            f.write(response['Body'].read())

                    except botocore.exceptions.ClientError as e:
                        if e.response['Error']['Code'] == 'AccessDenied':
                            if self.is_bucket_public(bucket):
                                error_msg = (
                                    f"Access denied when using anonymous access for bucket "
                                    f"'{bucket}'. The bucket may not be public or may require "
                                    "authentication."
                                )
                            else:
                                error_msg = (
                                    f"Access denied when using authenticated access for bucket "
                                    f"'{bucket}'. Check your permissions or try using anonymous "
                                    "access."
                                )
                            ConsoleAndLog.error(error_msg)
                        else:
                            ConsoleAndLog.error(f"Failed to download template: {str(e)}")
                        return 1

                    # Route: package+deploy or direct deploy
                    if self._has_s3_includes(temp_template_path):
                        ConsoleAndLog.info(
                            "S3 includes detected - using sam package + deploy flow"
                        )
                        try:
                            rewritten_template = self._prepare_template_with_s3_includes(
                                temp_template_path, temp_dir_path
                            )
                            s3_bucket, s3_prefix = self._read_artifact_bucket_config()
                            packaged_template = temp_dir_path / "template-packaged.yml"
                            package_result = self._run_sam_package(
                                rewritten_template, packaged_template, s3_bucket, s3_prefix
                            )
                            if package_result != 0:
                                return package_result
                            return self._run_sam_deploy(packaged_template, config_path)
                        except ValueError as e:
                            ConsoleAndLog.error(f"Failed to prepare template: {str(e)}")
                            return 1
                    else:
                        ConsoleAndLog.info(
                            "No S3 includes detected - using direct sam deploy"
                        )
                        return self._run_sam_deploy(temp_template_path, config_path)
            else:
                # Handle local template
                local_template_path = self.get_samconfig_dir() / template_path
                if not local_template_path.exists():
                    ConsoleAndLog.error(
                        f"Local template file not found: {local_template_path}"
                    )
                    return 1

                ConsoleAndLog.info(f"Using local template: {local_template_path}")

                # Route: package+deploy or direct deploy
                if self._has_s3_includes(local_template_path):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_dir_path = Path(temp_dir)
                        ConsoleAndLog.info(
                            "S3 includes detected in local template - using sam package + deploy flow"
                        )
                        try:
                            rewritten_template = self._prepare_template_with_s3_includes(
                                local_template_path, temp_dir_path
                            )
                            s3_bucket, s3_prefix = self._read_artifact_bucket_config()
                            packaged_template = temp_dir_path / "template-packaged.yml"
                            package_result = self._run_sam_package(
                                rewritten_template, packaged_template, s3_bucket, s3_prefix
                            )
                            if package_result != 0:
                                return package_result
                            return self._run_sam_deploy(packaged_template, config_path)
                        except ValueError as e:
                            ConsoleAndLog.error(f"Failed to prepare template: {str(e)}")
                            return 1
                else:
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

    def _is_s3_url(self, url: str) -> bool:
        """Check if a string is an S3 URL.

        Args:
            url: String to check.

        Returns:
            True if url matches S3 URL patterns, False otherwise.

        Example:
            >>> deployer._is_s3_url('s3://my-bucket/path/to/file.yml')
            True
            >>> deployer._is_s3_url('./local/file.yml')
            False
        """
        if not isinstance(url, str):
            return False

        url_lower = url.lower()
        return (url_lower.startswith('s3://') or
                url_lower.startswith('https://s3.amazonaws.com/') or
                ('.s3.' in url_lower and url_lower.startswith('https://')))

    def _has_s3_includes(self, template_path: Path) -> bool:
        """Check if template contains Fn::Transform: AWS::Include with S3 locations.

        Tries YAML parse first, falls back to JSON. Recursively walks dicts and
        lists searching for the Fn::Transform / Fn::transform pattern. On any
        parse or scan exception, logs a warning and returns False (fail-open).

        Args:
            template_path: Path to the template file (YAML or JSON).

        Returns:
            True if any S3-based AWS::Include transforms are found, False otherwise.

        Example:
            >>> deployer._has_s3_includes(Path('/path/to/template.yml'))
            True
        """
        import json

        try:
            with open(template_path, 'r') as f:
                content = f.read()

            # Try YAML first (most common), fall back to JSON
            try:
                template = yaml.safe_load(content)
            except yaml.YAMLError:
                template = json.loads(content)

            # Recursively search for Fn::Transform with AWS::Include
            def find_s3_includes(obj):
                if isinstance(obj, dict):
                    # Check for Fn::Transform: AWS::Include pattern
                    if 'Fn::Transform' in obj or 'Fn::transform' in obj:
                        transform = obj.get('Fn::Transform') or obj.get('Fn::transform')
                        if isinstance(transform, dict):
                            name = transform.get('Name', '')
                            location = transform.get('Parameters', {}).get('Location', '')
                            if name == 'AWS::Include' and self._is_s3_url(location):
                                return True

                    # Recurse into dict values
                    for value in obj.values():
                        if find_s3_includes(value):
                            return True

                elif isinstance(obj, list):
                    # Recurse into list items
                    for item in obj:
                        if find_s3_includes(item):
                            return True

                return False

            return find_s3_includes(template)

        except Exception as e:
            ConsoleAndLog.warning(f"Could not scan template for S3 includes: {str(e)}")
            return False  # Fail open - proceed with direct deploy

    def _read_parameter_overrides(self) -> dict:
        """Read and parse parameter_overrides from the active samconfig TOML stage.

        Opens the samconfig TOML, reads parameter_overrides from
        default.deploy.parameters and the active stage's deploy.parameters.
        Stage values take precedence over default values. Parses the
        "Key1=Value1 Key2=Value2" format into a dict.

        Returns:
            Dict mapping parameter names to their string values. Returns an
            empty dict when parameter_overrides is absent or empty.

        Raises:
            ValueError: When the samconfig file cannot be read or parsed,
                wrapping the underlying exception message.

        Example:
            >>> # With samconfig containing: parameter_overrides = "Env=prod Bucket=my-bucket"
            >>> deployer._read_parameter_overrides()
            {'Env': 'prod', 'Bucket': 'my-bucket'}
        """
        try:
            config_file = self.get_samconfig_file_path()
            with open(config_file, 'rb') as f:
                config = tomli.load(f)

            # Read from default section
            default_params = (
                config.get('default', {})
                      .get('deploy', {})
                      .get('parameters', {})
            )
            # Read from active stage section
            stage_params = (
                config.get(self.stage_id, {})
                      .get('deploy', {})
                      .get('parameters', {})
            )

            # Merge: stage overrides default
            merged = {**default_params, **stage_params}

            # Extract and parse the parameter_overrides string
            param_overrides_str = merged.get('parameter_overrides', '')

            overrides = {}
            if param_overrides_str:
                for pair in param_overrides_str.split():
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        overrides[key] = value

            return overrides

        except Exception as e:
            raise ValueError(f"Failed to read parameter overrides: {str(e)}")

    def _resolve_parameter_references(self, location, parameter_overrides: dict) -> str:
        """Resolve CloudFormation parameter references in a Location value.

        Supports plain strings (passed through unchanged), Ref, Fn::Sub (string
        and list forms), and Fn::Join. Recursively resolves nested intrinsics
        within Fn::Join parts.

        Args:
            location: Location value from template. May be a plain string or a
                dict containing a CloudFormation intrinsic function (Ref, Fn::Sub,
                Fn::Join).
            parameter_overrides: Dict mapping parameter names to their resolved
                string values (sourced from samconfig TOML parameter_overrides).

        Returns:
            Resolved S3 URL as a concrete string.

        Raises:
            ValueError: When a referenced parameter is absent from
                parameter_overrides, with the parameter name in the message.
            ValueError: When the location format is unsupported.

        Example:
            >>> deployer._resolve_parameter_references(
            ...     's3://my-bucket/path/to/file.yml', {}
            ... )
            's3://my-bucket/path/to/file.yml'

            >>> deployer._resolve_parameter_references(
            ...     {'Ref': 'S3ModuleLocation'},
            ...     {'S3ModuleLocation': 's3://my-bucket/modules'}
            ... )
            's3://my-bucket/modules'
        """
        # Plain string — pass through unchanged
        if isinstance(location, str):
            return location

        if isinstance(location, dict):
            # Handle Ref
            if 'Ref' in location:
                param_name = location['Ref']
                if param_name not in parameter_overrides:
                    raise ValueError(
                        f"Parameter '{param_name}' not found in parameter_overrides"
                    )
                return parameter_overrides[param_name]

            # Handle Fn::Sub
            if 'Fn::Sub' in location:
                sub_value = location['Fn::Sub']

                # Simple string form: Fn::Sub: '${Param}/path'
                if isinstance(sub_value, str):
                    result = sub_value
                    for param_name, param_value in parameter_overrides.items():
                        result = result.replace(f'${{{param_name}}}', param_value)
                    # Check for any unresolved references
                    import re
                    unresolved = re.findall(r'\$\{([^}]+)\}', result)
                    if unresolved:
                        raise ValueError(
                            f"Parameter '{unresolved[0]}' not found in parameter_overrides"
                        )
                    return result

                # List form: Fn::Sub: ['${Param}/path', {Param: value}]
                if isinstance(sub_value, list) and len(sub_value) == 2:
                    template_str = sub_value[0]
                    inline_map = sub_value[1] if isinstance(sub_value[1], dict) else {}
                    result = template_str
                    for key, value in inline_map.items():
                        result = result.replace(f'${{{key}}}', str(value))
                    return result

            # Handle Fn::Join
            if 'Fn::Join' in location:
                join_value = location['Fn::Join']
                if isinstance(join_value, list) and len(join_value) == 2:
                    delimiter = join_value[0]
                    parts = []
                    for part in join_value[1]:
                        if isinstance(part, str):
                            parts.append(part)
                        else:
                            # Recursively resolve nested intrinsics
                            parts.append(
                                self._resolve_parameter_references(part, parameter_overrides)
                            )
                    return delimiter.join(parts)

        raise ValueError(f"Unsupported Location format: {location!r}")

    def _read_artifact_bucket_config(self) -> tuple[str, str]:
        """Read artifact bucket configuration from the samconfig TOML.

        Reads s3_bucket and s3_prefix from atlantis.deploy.parameters (the
        shared Atlantis section) and the active stage's deploy.parameters.
        Stage values take precedence over atlantis values.

        Returns:
            Tuple of (s3_bucket, s3_prefix). s3_prefix is an empty string
            when not configured.

        Raises:
            ValueError: When s3_bucket is not found in either the atlantis
                section or the active stage, with a message directing the
                user to run config.py.
            ValueError: When the samconfig TOML is malformed.
            ValueError: When the samconfig file does not exist.

        Example:
            >>> s3_bucket, s3_prefix = deployer._read_artifact_bucket_config()
            >>> s3_bucket
            'my-artifact-bucket'
            >>> s3_prefix
            'my-prefix'
        """
        try:
            config_file = self.get_samconfig_file_path()
            with open(config_file, 'rb') as f:
                config = tomli.load(f)

            # Shared Atlantis section
            atlantis_params = (
                config.get('atlantis', {})
                      .get('deploy', {})
                      .get('parameters', {})
            )
            # Active stage section
            stage_params = (
                config.get(self.stage_id, {})
                      .get('deploy', {})
                      .get('parameters', {})
            )

            # Stage overrides atlantis
            s3_bucket = stage_params.get('s3_bucket') or atlantis_params.get('s3_bucket')
            s3_prefix = stage_params.get('s3_prefix') or atlantis_params.get('s3_prefix', '')

            if not s3_bucket:
                raise ValueError(
                    "s3_bucket not configured in samconfig. "
                    "Templates with S3 includes require an artifact bucket. "
                    "Run 'config.py' to configure s3_bucket."
                )

            return s3_bucket, (s3_prefix or '')

        except tomli.TOMLDecodeError as e:
            raise ValueError(f"Invalid samconfig TOML: {str(e)}")
        except FileNotFoundError:
            raise ValueError(
                f"Samconfig file not found: {self.get_samconfig_file_path()}"
            )

    def _download_s3_module(self, s3_url: str, temp_dir: Path, index: int) -> str:
        """Download an S3 module file to a local temp file.

        Selects an anonymous or authenticated S3 client based on whether the
        bucket is public, then downloads the module to temp_dir. The local
        filename is derived from the S3 key's extension (defaults to .yml when
        the key has no extension).

        Args:
            s3_url: S3 URL of the module to download (s3://bucket/key or
                https:// path-style / virtual-hosted-style URLs are not
                supported here — use the s3:// form).
            temp_dir: Directory in which to write the downloaded module file.
            index: Zero-based index used to name the local file uniquely
                (module-{index}{ext}).

        Returns:
            Relative path string to the downloaded file, e.g. "./module-0.yml".

        Raises:
            ValueError: When the bucket denies access — includes a message
                directing the user to check permissions or authentication.
            ValueError: When the S3 object is not found — includes the S3 URL
                in the message.
            ValueError: When any other S3 ClientError occurs — includes the
                original error message.

        Example:
            >>> local_path = deployer._download_s3_module(
            ...     's3://my-bucket/modules/role.yml', Path('/tmp/work'), 0
            ... )
            >>> local_path
            './module-0.yml'
        """
        bucket, key, version_id = self.parse_s3_url(s3_url)

        # Derive extension from key; default to .yml
        ext = Path(key).suffix or '.yml'
        local_filename = f"module-{index}{ext}"
        local_path = temp_dir / local_filename

        # Choose client based on bucket visibility
        s3_client = (
            self.s3_client_anonymous if self.is_bucket_public(bucket)
            else self.s3_client
        )

        try:
            get_args = {'Bucket': bucket, 'Key': key}
            if version_id is not None:
                get_args['VersionId'] = version_id

            response = s3_client.get_object(**get_args)
            with open(local_path, 'wb') as f:
                f.write(response['Body'].read())

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDenied':
                raise ValueError(
                    f"Access denied downloading module from {s3_url}. "
                    "Check bucket permissions or authentication."
                )
            elif error_code in ('404', 'NoSuchKey'):
                raise ValueError(f"Module not found at {s3_url}")
            else:
                raise ValueError(
                    f"Failed to download module from {s3_url}: {str(e)}"
                )

        return f"./{local_filename}"

    def _prepare_template_with_s3_includes(
        self, template_path: Path, temp_dir: Path
    ) -> Path:
        """Prepare a template with S3 includes for sam package.

        Walks the template recursively, resolves CloudFormation parameter
        references in each S3 Location value, downloads each referenced S3
        module to a local temp file, and rewrites the Location to the local
        relative path. The modified template is written to
        temp_dir/template-rewritten.yml.

        Each distinct S3 URL is downloaded exactly once; duplicate references
        reuse the same local file (module map deduplication).

        Args:
            template_path: Path to the downloaded template (YAML).
            temp_dir: Temporary directory for module files and rewritten template.

        Returns:
            Path to the rewritten template (temp_dir / "template-rewritten.yml").

        Raises:
            ValueError: Propagated from _resolve_parameter_references when a
                required parameter is missing or the Location format is
                unsupported.
            ValueError: Propagated from _download_s3_module when an S3
                download fails.

        Example:
            >>> rewritten = deployer._prepare_template_with_s3_includes(
            ...     Path('/tmp/work/template.yml'),
            ...     Path('/tmp/work')
            ... )
            >>> rewritten.name
            'template-rewritten.yml'
        """
        ConsoleAndLog.info("Preparing template: resolving S3 includes")

        # Load template
        with open(template_path, 'r') as f:
            template = yaml.safe_load(f)

        # Load parameter overrides from samconfig
        parameter_overrides = self._read_parameter_overrides()

        # Maps resolved S3 URL -> local relative path (for deduplication)
        module_map: dict = {}

        def process_includes(obj):
            """Recursively walk template and rewrite S3 Location values."""
            if isinstance(obj, dict):
                # Check for Fn::Transform: AWS::Include
                transform_key = None
                if 'Fn::Transform' in obj:
                    transform_key = 'Fn::Transform'
                elif 'Fn::transform' in obj:
                    transform_key = 'Fn::transform'

                if transform_key:
                    transform = obj[transform_key]
                    if isinstance(transform, dict):
                        name = transform.get('Name', '')
                        params = transform.get('Parameters', {})
                        location = params.get('Location', '')

                        if name == 'AWS::Include' and self._is_s3_url(location):
                            # Resolve parameter references to a concrete URL
                            resolved_url = self._resolve_parameter_references(
                                location, parameter_overrides
                            )

                            # Download module if not already cached
                            if resolved_url not in module_map:
                                local_path = self._download_s3_module(
                                    resolved_url, temp_dir, len(module_map)
                                )
                                module_map[resolved_url] = local_path
                                ConsoleAndLog.info(
                                    f"Downloaded module: {resolved_url} -> {local_path}"
                                )

                            # Rewrite Location to relative local path
                            transform['Parameters']['Location'] = module_map[resolved_url]

                # Recurse into all dict values
                for value in obj.values():
                    process_includes(value)

            elif isinstance(obj, list):
                for item in obj:
                    process_includes(item)

        process_includes(template)

        # Write rewritten template
        rewritten_path = temp_dir / "template-rewritten.yml"
        with open(rewritten_path, 'w') as f:
            yaml.dump(template, f, default_flow_style=False, sort_keys=False)

        ConsoleAndLog.info(f"Wrote rewritten template: {rewritten_path}")
        ConsoleAndLog.info(f"Downloaded {len(module_map)} S3 module(s)")

        return rewritten_path

    def _run_sam_package(self, template_path: Path, output_path: Path,
                         s3_bucket: str, s3_prefix: str) -> int:
        """Execute sam package to resolve includes and upload artifacts.

        Constructs and runs a sam package command, mirroring the pattern of
        _run_sam_deploy. The command is run with cwd set to the template's
        parent directory so relative include paths resolve correctly.

        Args:
            template_path: Path to the rewritten template with local includes.
            output_path: Path where the packaged output template will be written.
            s3_bucket: S3 bucket name for artifact uploads.
            s3_prefix: S3 key prefix for artifact uploads. Omitted from the
                command when empty.

        Returns:
            Exit code from the sam package subprocess (0 for success, non-zero
            for failure).

        Example:
            >>> exit_code = deployer._run_sam_package(
            ...     Path('/tmp/work/template-rewritten.yml'),
            ...     Path('/tmp/work/template-packaged.yml'),
            ...     'my-artifact-bucket',
            ...     'my-prefix'
            ... )
            >>> exit_code
            0
        """
        sam_cmd = [
            "sam.cmd" if os.name == 'nt' else "sam",
            "package",
            "--template-file", str(template_path),
            "--output-template-file", str(output_path),
            "--s3-bucket", s3_bucket,
        ]

        if s3_prefix:
            sam_cmd.extend(["--s3-prefix", s3_prefix])

        if self.profile:
            sam_cmd.extend(["--profile", self.profile])

        ConsoleAndLog.info(f"Executing: {' '.join(sam_cmd)}")

        result = subprocess.run(
            sam_cmd,
            cwd=template_path.parent,
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

        if result.returncode != 0:
            ConsoleAndLog.error(
                f"sam package failed with exit code {result.returncode}"
            )
        else:
            ConsoleAndLog.info("sam package completed successfully")
            ConsoleAndLog.info(f"Packaged template written to: {output_path}")

        return result.returncode

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