#!/usr/bin/env python3

VERSION = "v0.2.0/2026-08-06"
# Created by Chad Kluck with AI assistance from Amazon Q Developer and Kiro
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


# CloudFormation tags that do NOT take the "Fn::" prefix in long form.
_CFN_TAGS_WITHOUT_FN_PREFIX = {"Ref", "Condition"}


def _cfn_construct_getatt(node):
    """Construct the long-form value for a !GetAtt tag.

    ``!GetAtt Resource.Attr`` -> ``["Resource", "Attr"]``
    ``!GetAtt [Resource, Attr]`` -> ``["Resource", "Attr"]``

    Args:
        node: The YAML node carrying the !GetAtt value (scalar or sequence).

    Returns:
        A list of path components suitable for the long-form ``Fn::GetAtt``.

    Raises:
        yaml.constructor.ConstructorError: When the node value is neither a
            string nor a list.
    """
    if isinstance(node.value, str):
        return node.value.split(".", 1)
    if isinstance(node.value, list):
        return [getattr(item, "value", item) for item in node.value]
    raise yaml.constructor.ConstructorError(
        None, None, f"Unexpected node type for !GetAtt: {type(node)}", node.start_mark
    )


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that converts CloudFormation short-form tags to long form.

    PyYAML's SafeLoader raises ConstructorError for tags such as !Sub, !Ref,
    !GetAtt, !If, etc. A catch-all multi-constructor (registered below via
    ``add_multi_constructor("!", ...)``) converts each short-form tag into its
    equivalent long-form dict, e.g. ``!Sub "x"`` becomes ``{"Fn::Sub": "x"}``
    and ``!Ref X`` becomes ``{"Ref": "X"}``. Long form is valid CloudFormation,
    so a template parsed with this loader can be re-emitted with a plain
    ``yaml.dump`` without losing or corrupting any intrinsic functions.

    Nested values are constructed eagerly (``deep=True``) so that sibling
    branches of multi-branch templates (e.g. multiple Conditions or Resources)
    are fully populated rather than left null.

    Example:
        >>> import yaml
        >>> yaml.load("Loc: !Sub 's3://${B}/k'", Loader=_CfnLoader)
        {'Loc': {'Fn::Sub': 's3://${B}/k'}}
    """
    pass


def _cfn_tag_multi_constructor(loader, tag_suffix, node):
    """Convert a CloudFormation short-form tag node into a long-form dict.

    Args:
        loader: The active YAML loader instance.
        tag_suffix: The tag name without the leading '!' (e.g. 'Sub', 'GetAtt').
        node: The YAML node being constructed.

    Returns:
        A single-key dict mapping the long-form intrinsic name to its value,
        e.g. {'Fn::Sub': 's3://...'} or {'Ref': 'MyParam'}.

    Raises:
        yaml.constructor.ConstructorError: When an unexpected node type is
            encountered for a CF tag.
    """
    key = (
        tag_suffix if tag_suffix in _CFN_TAGS_WITHOUT_FN_PREFIX
        else "Fn::" + tag_suffix
    )

    if tag_suffix == "GetAtt":
        return {key: _cfn_construct_getatt(node)}
    if isinstance(node, yaml.ScalarNode):
        return {key: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {key: loader.construct_sequence(node, deep=True)}
    if isinstance(node, yaml.MappingNode):
        return {key: loader.construct_mapping(node, deep=True)}
    raise yaml.constructor.ConstructorError(
        None, None, f"Unexpected node type for tag !{tag_suffix}", node.start_mark
    )


_CfnLoader.add_multi_constructor("!", _cfn_tag_multi_constructor)

from pathlib import Path
from typing import Optional
from botocore.exceptions import ClientError

import boto3
import botocore
import click

from lib.aws_session import AWSSessionManager
from lib.logger import ScriptLogger, ConsoleAndLog, Log
from lib.atlantis import DefaultsLoader, SamconfigReader
from lib.gitops import Git
from lib.tools import Colorize

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

    def _print_section_heading(self, heading: str) -> None:
        """Print a section heading with a matching divider, both in yellow.

        Replicates the SAM CLI look for the CloudFormation branch: a bold
        yellow heading followed by a yellow ``=`` divider line.

        Args:
            heading: The heading text to display (e.g. ``"Deploying with
                following values"``).

        Example:
            >>> deployer._print_section_heading("Initiating deployment")
        """
        click.echo(Colorize.output_bold(heading, fg=Colorize.WARNING))
        click.echo(Colorize.divider('=', fg=Colorize.WARNING))

    def _print_deploy_values_summary(
        self,
        deploy_params: dict,
        cfn_parameters: list,
        cfn_tags: list,
        s3_bucket_display: Optional[str] = None,
    ) -> None:
        """Print the pre-deploy "Deploying with following values" summary.

        Renders a colorized summary of the values that will be used for the
        CloudFormation change set, replicating the visibility the SAM branch
        gets from ``sam deploy``. Each value line uses
        ``Colorize.output_with_value`` (green label, yellow value).

        Fields are printed in this order: Stack name, Region, Confirm changeset,
        Capabilities, Role ARN (only when configured), Deployment s3 bucket (only
        when the template was uploaded to S3), Parameter overrides, and Tags.
        ``Disable rollback`` and ``Signing Profiles`` are intentionally omitted
        because this path never sets them.

        Args:
            deploy_params (dict): Deploy parameters from
                ``_read_deploy_params_for_packaged`` with keys ``stack_name``,
                ``region``, ``confirm_changeset``, ``capabilities``, and
                ``role_arn``.
            cfn_parameters (list): Parameter overrides as a list of
                ``{'ParameterKey': ..., 'ParameterValue': ...}`` dicts.
            cfn_tags (list): Tags as a list of ``{'Key': ..., 'Value': ...}``
                dicts.
            s3_bucket_display (str, optional): The artifact S3 bucket to display
                when the template was uploaded to S3 because it exceeded the
                inline ``TemplateBody`` size limit. When None (default), the
                ``Deployment s3 bucket`` line is omitted.

        Example:
            >>> deployer._print_deploy_values_summary(
            ...     {'stack_name': 'my-stack', 'region': 'us-east-1',
            ...      'confirm_changeset': True,
            ...      'capabilities': 'CAPABILITY_NAMED_IAM', 'role_arn': ''},
            ...     [{'ParameterKey': 'Env', 'ParameterValue': 'test'}],
            ...     [{'Key': 'Project', 'Value': 'acme'}],
            ... )
        """
        capabilities = ', '.join(
            c.strip()
            for c in str(deploy_params.get('capabilities', '')).split(',')
            if c.strip()
        )

        self._print_section_heading("Deploying with following values")
        click.echo(Colorize.output_with_value(
            "Stack name", str(deploy_params.get('stack_name', ''))))
        click.echo(Colorize.output_with_value(
            "Region", str(deploy_params.get('region', ''))))
        click.echo(Colorize.output_with_value(
            "Confirm changeset", str(deploy_params.get('confirm_changeset', ''))))
        click.echo(Colorize.output_with_value("Capabilities", capabilities))

        role_arn = deploy_params.get('role_arn', '')
        if role_arn:
            click.echo(Colorize.output_with_value("Role ARN", str(role_arn)))

        if s3_bucket_display:
            click.echo(Colorize.output_with_value(
                "Deployment s3 bucket", str(s3_bucket_display)))

        click.echo(Colorize.output_with_value(
            "Parameter overrides",
            self._format_key_value_pairs(
                cfn_parameters, 'ParameterKey', 'ParameterValue')))
        click.echo(Colorize.output_with_value(
            "Tags",
            self._format_key_value_pairs(cfn_tags, 'Key', 'Value')))

    def _format_key_value_pairs(
        self, pairs: list, key_field: str, value_field: str
    ) -> str:
        """Render a list of key/value dicts as a compact ``{Key: Value, ...}`` string.

        Produces a compact, SAM-table-like representation of parameter overrides
        or tags without dumping raw API structures.

        Args:
            pairs (list): List of dicts, each holding a key and a value under
                ``key_field`` and ``value_field``.
            key_field (str): The dict key that holds the pair's name
                (e.g. ``'ParameterKey'`` or ``'Key'``).
            value_field (str): The dict key that holds the pair's value
                (e.g. ``'ParameterValue'`` or ``'Value'``).

        Returns:
            str: A string like ``{Env: test, Region: us-east-1}``. Returns
            ``{}`` when ``pairs`` is empty.

        Example:
            >>> deployer._format_key_value_pairs(
            ...     [{'Key': 'Project', 'Value': 'acme'}], 'Key', 'Value')
            '{Project: acme}'
        """
        rendered = ', '.join(
            f"{pair.get(key_field, '')}: {pair.get(value_field, '')}"
            for pair in pairs
        )
        return f"{{{rendered}}}"

    def _print_changeset_summary(self, changes: list) -> None:
        """Print an aligned listing of the pending change set changes.

        Renders a ``Changeset`` heading followed by one aligned line per change,
        loosely resembling the SAM CLI changeset table. Each line shows the
        Action, Logical ID, and Resource Type, plus the Replacement flag and
        Physical ID when those fields are present. Raw change set JSON is never
        printed.

        Args:
            changes (list): The ``Changes`` list returned by
                ``describe_change_set``. Each element is expected to hold a
                ``ResourceChange`` dict with keys such as ``Action``,
                ``LogicalResourceId``, ``ResourceType``, ``Replacement``, and
                ``PhysicalResourceId``.

        Example:
            >>> deployer._print_changeset_summary([
            ...     {'ResourceChange': {
            ...         'Action': 'Modify',
            ...         'LogicalResourceId': 'MyFunction',
            ...         'ResourceType': 'AWS::Lambda::Function',
            ...         'Replacement': 'False',
            ...         'PhysicalResourceId': 'my-function'}},
            ... ])
        """
        self._print_section_heading("Changeset")

        rows = []
        show_replacement = False
        show_physical_id = False
        for change in changes:
            resource_change = change.get('ResourceChange', {}) or {}
            action = str(resource_change.get('Action', ''))
            logical_id = str(resource_change.get('LogicalResourceId', ''))
            resource_type = str(resource_change.get('ResourceType', ''))
            replacement = resource_change.get('Replacement')
            physical_id = resource_change.get('PhysicalResourceId')

            replacement_text = '' if replacement is None else str(replacement)
            physical_id_text = '' if physical_id is None else str(physical_id)

            if replacement_text:
                show_replacement = True
            if physical_id_text:
                show_physical_id = True

            rows.append({
                'Action': action,
                'LogicalResourceId': logical_id,
                'ResourceType': resource_type,
                'Replacement': replacement_text,
                'PhysicalResourceId': physical_id_text,
            })

        columns = ['Action', 'LogicalResourceId', 'ResourceType']
        if show_replacement:
            columns.append('Replacement')
        if show_physical_id:
            columns.append('PhysicalResourceId')

        widths = {
            column: max(
                len(column),
                max((len(row[column]) for row in rows), default=0),
            )
            for column in columns
        }

        header = '  '.join(column.ljust(widths[column]) for column in columns)
        click.echo(Colorize.output_bold(header, fg=Colorize.OUTPUT))
        for row in rows:
            line = '  '.join(row[column].ljust(widths[column]) for column in columns)
            click.echo(Colorize.output(line, fg=Colorize.OUTPUT_VALUE))

    def _print_success_banner(self) -> None:
        """Print a green success banner marking a completed deployment.

        Renders a green heading and divider followed by a green success
        message, matching the completion styling used by the other CLI
        scripts (e.g. ``delete.py``'s ``Colorize.success`` output). This
        banner is only shown on a successful (exit code 0) deployment.

        Example:
            >>> deployer._print_success_banner()
        """
        click.echo(Colorize.output_bold(
            "Successfully deployed stack", fg=Colorize.SUCCESS))
        click.echo(Colorize.divider('=', fg=Colorize.SUCCESS))
        click.echo(Colorize.success("Deployment complete."))

    def _print_stack_outputs(self, outputs: list) -> None:
        """Print the stack Outputs, loosely resembling SAM deploy's display.

        When ``outputs`` contains entries, prints an ``Outputs`` section
        heading followed by one ``Colorize.output_with_value`` line per
        output (``OutputKey`` / ``OutputValue``), appending the description
        when one is present. When ``outputs`` is empty, nothing is printed so
        that no empty section appears.

        Args:
            outputs (list): The ``Outputs`` list from
                ``describe_stacks``. Each element is expected to hold an
                ``OutputKey`` and ``OutputValue``, and optionally a
                ``Description``.

        Example:
            >>> deployer._print_stack_outputs([
            ...     {'OutputKey': 'ApiUrl',
            ...      'OutputValue': 'https://example.execute-api.amazonaws.com',
            ...      'Description': 'Base URL of the deployed API'},
            ... ])
        """
        if not outputs:
            return

        self._print_section_heading("Outputs")
        for output in outputs:
            output_key = str(output.get('OutputKey', ''))
            output_value = str(output.get('OutputValue', ''))
            description = output.get('Description')

            if description:
                output_value = f"{output_value} ({description})"

            click.echo(Colorize.output_with_value(output_key, output_value))

    def _wait_for_stack_operation(
        self, cfn_client, stack_name: str, change_set_type: str
    ) -> bool:
        """Poll a CloudFormation stack until its operation completes.

        Replaces the silent boto3 ``stack_create_complete`` /
        ``stack_update_complete`` waiter with a manual polling loop modeled on
        ``delete.py``'s ``delete_stack``. On each in-progress cycle the current
        ``StackStatus`` is printed in green so the operator can see progress
        rather than waiting on a silent waiter. The loop polls
        ``describe_stacks`` every 10 seconds for up to 180 attempts (30
        minutes), matching ``delete.py``'s cadence and cap.

        Args:
            cfn_client: A boto3 CloudFormation client used to call
                ``describe_stacks``.
            stack_name (str): The name of the stack whose operation is being
                awaited.
            change_set_type (str): The change set type driving the operation
                (``'CREATE'`` or ``'UPDATE'``). Retained for logging/context;
                success and failure are determined from the live
                ``StackStatus``.

        Returns:
            bool: ``True`` when the stack reaches ``CREATE_COMPLETE`` or
            ``UPDATE_COMPLETE``; ``False`` when it reaches a failure status or
            the 30-minute cap is exceeded.

        Example:
            >>> succeeded = deployer._wait_for_stack_operation(
            ...     cfn_client, 'my-stack', 'UPDATE')
            >>> if succeeded:
            ...     print("Stack operation complete")
        """
        import time

        max_attempts = 180  # 30 minutes at 10s intervals
        attempt = 0
        success_statuses = {'CREATE_COMPLETE', 'UPDATE_COMPLETE'}
        failure_statuses = {
            'CREATE_FAILED',
            'ROLLBACK_COMPLETE',
            'ROLLBACK_FAILED',
            'UPDATE_FAILED',
            'UPDATE_ROLLBACK_COMPLETE',
            'UPDATE_ROLLBACK_FAILED',
        }

        try:
            while attempt < max_attempts:
                response = cfn_client.describe_stacks(StackName=stack_name)
                stack_status = response['Stacks'][0]['StackStatus']

                if stack_status in success_statuses:
                    return True

                if stack_status in failure_statuses:
                    ConsoleAndLog.error(
                        f"Stack operation failed with status: {stack_status}")
                    return False

                click.echo(Colorize.output(
                    f"Stack update in progress... Status: {stack_status}",
                    fg=Colorize.SUCCESS))
                time.sleep(10)
                attempt += 1

            ConsoleAndLog.error("Stack operation timed out after 30 minutes")
            return False

        except KeyboardInterrupt:
            click.echo(Colorize.error("\nOperation cancelled by user"))
            Log.info("Operation cancelled by user")
            sys.exit(1)

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
        Location URLs, resolves the include locations to literal S3 URLs
        (substituting samconfig parameter values) and deploys via a
        CloudFormation change set, letting CloudFormation resolve AWS::Include
        and AWS::Serverless transforms server-side. Templates without S3
        includes proceed directly to sam deploy unchanged.

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

                    # Route: resolve S3 includes + CloudFormation deploy, or direct deploy
                    if self._has_s3_includes(temp_template_path):
                        ConsoleAndLog.info(
                            "S3 includes detected - resolving includes and deploying via CloudFormation"
                        )
                        try:
                            resolved_template = self._resolve_template_includes(
                                temp_template_path, temp_dir_path
                            )
                            deploy_params = self._read_deploy_params_for_packaged()
                            return self._cfn_deploy_packaged(
                                resolved_template, deploy_params
                            )
                        except ValueError as e:
                            ConsoleAndLog.error(f"Failed to resolve template: {str(e)}")
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
                            "S3 includes detected in local template - resolving includes and deploying via CloudFormation"
                        )
                        try:
                            resolved_template = self._resolve_template_includes(
                                local_template_path, temp_dir_path
                            )
                            deploy_params = self._read_deploy_params_for_packaged()
                            return self._cfn_deploy_packaged(
                                resolved_template, deploy_params
                            )
                        except ValueError as e:
                            ConsoleAndLog.error(f"Failed to resolve template: {str(e)}")
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


    def _run_sam_deploy(self, template_path, config_path: Path) -> int:
        """Execute the SAM deploy command.

        Args:
            template_path: Local path or filename of the template to deploy.
                Relative names are resolved against the samconfig directory
                (the subprocess ``cwd``).
            config_path: Path to the samconfig TOML file.

        Returns:
            Exit code from sam deploy (0 for success, non-zero for failure).
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

    def _location_probe_string(self, location) -> str:
        """Return a best-effort string form of an AWS::Include Location for detection.

        Handles plain strings and the long-form dict intrinsics that _CfnLoader
        produces (Fn::Sub string form, Fn::Sub list form, Fn::Join). Returns an
        empty string when no string form can be extracted.
        """
        if isinstance(location, str):
            return location
        if isinstance(location, dict):
            if 'Fn::Sub' in location:
                sub = location['Fn::Sub']
                if isinstance(sub, str):
                    return sub
                if isinstance(sub, list) and sub and isinstance(sub[0], str):
                    return sub[0]
            if 'Fn::Join' in location:
                join = location['Fn::Join']
                if isinstance(join, list) and len(join) == 2 and isinstance(join[1], list):
                    return ''.join(p for p in join[1] if isinstance(p, str))
        return ''

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
                template = yaml.load(content, Loader=_CfnLoader)
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
                            probe = self._location_probe_string(location)
                            if name == 'AWS::Include' and self._is_s3_url(probe):
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

    def _read_artifact_bucket_config(self) -> tuple[str, str]:
        """Read artifact bucket configuration from the samconfig TOML.

        Reads ``s3_bucket`` and ``s3_prefix`` from ``atlantis.deploy.parameters``
        (the shared Atlantis section) and the active stage's ``deploy.parameters``.
        Stage values take precedence over atlantis values.

        Delegates TOML loading to :class:`~lib.atlantis.SamconfigReader`.

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
        reader = SamconfigReader(self.get_samconfig_file_path())
        atlantis_params = reader.read_atlantis_params()
        stage_params = reader.read_deploy_params(self.stage_id)

        s3_bucket = stage_params.get('s3_bucket') or atlantis_params.get('s3_bucket')
        s3_prefix = stage_params.get('s3_prefix') or atlantis_params.get('s3_prefix', '')

        if not s3_bucket:
            raise ValueError(
                "s3_bucket not configured in samconfig. "
                "Templates with S3 includes require an artifact bucket. "
                "Run 'config.py' to configure s3_bucket."
            )

        return s3_bucket, (s3_prefix or '')

    def _read_parameter_overrides(self) -> dict:
        """Read and parse parameter_overrides from the active samconfig TOML stage.

        Delegates to :class:`~lib.atlantis.SamconfigReader` which merges
        ``default.deploy.parameters`` and ``{stage_id}.deploy.parameters``
        (stage wins) then parses the ``parameter_overrides`` string. Both plain
        ``Key=Value`` and SAM CLI quoted ``"Key"="Value"`` formats are supported.

        Returns:
            Dict mapping parameter names to their string values.

        Raises:
            ValueError: When the samconfig file cannot be read or parsed.
        """
        reader = SamconfigReader(self.get_samconfig_file_path())
        return reader.read_parameter_overrides(self.stage_id)

    def _resolve_parameter_references(self, location, parameter_overrides: dict) -> str:
        """Resolve CloudFormation parameter references in an AWS::Include Location.

        Supports plain strings (``${Param}`` patterns substituted), Ref, Fn::Sub
        (string and list forms), and Fn::Join. Recursively resolves nested
        intrinsics within Fn::Join parts. Returns a concrete literal string.

        Raises:
            ValueError: When a referenced parameter is absent from
                parameter_overrides, or the location format is unsupported.
        """
        import re

        if isinstance(location, str):
            if '${' not in location:
                return location
            result = location
            for param_name, param_value in parameter_overrides.items():
                result = result.replace(f'${{{param_name}}}', param_value)
            unresolved = re.findall(r'\$\{([^}]+)\}', result)
            if unresolved:
                raise ValueError(
                    f"Parameter '{unresolved[0]}' not found in parameter_overrides"
                )
            return result

        if isinstance(location, dict):
            if 'Ref' in location:
                param_name = location['Ref']
                if param_name not in parameter_overrides:
                    raise ValueError(
                        f"Parameter '{param_name}' not found in parameter_overrides"
                    )
                return parameter_overrides[param_name]

            if 'Fn::Sub' in location:
                sub_value = location['Fn::Sub']
                if isinstance(sub_value, str):
                    result = sub_value
                    for param_name, param_value in parameter_overrides.items():
                        result = result.replace(f'${{{param_name}}}', param_value)
                    unresolved = re.findall(r'\$\{([^}]+)\}', result)
                    if unresolved:
                        raise ValueError(
                            f"Parameter '{unresolved[0]}' not found in parameter_overrides"
                        )
                    return result
                if isinstance(sub_value, list) and len(sub_value) == 2:
                    template_str = sub_value[0]
                    inline_map = sub_value[1] if isinstance(sub_value[1], dict) else {}
                    result = template_str
                    for key, value in {**parameter_overrides, **inline_map}.items():
                        result = result.replace(f'${{{key}}}', str(value))
                    return result

            if 'Fn::Join' in location:
                join_value = location['Fn::Join']
                if isinstance(join_value, list) and len(join_value) == 2:
                    delimiter = join_value[0]
                    parts = []
                    for part in join_value[1]:
                        if isinstance(part, str):
                            parts.append(part)
                        else:
                            parts.append(
                                self._resolve_parameter_references(part, parameter_overrides)
                            )
                    return delimiter.join(parts)

        raise ValueError(f"Unsupported Location format: {location!r}")

    def _resolve_template_includes(self, template_path: Path, temp_dir: Path) -> Path:
        """Resolve parameterized S3 AWS::Include locations to literal S3 URLs.

        Parses the template with the tag-preserving _CfnLoader, walks it, and for
        each Fn::Transform: AWS::Include whose Location resolves to an S3 URL,
        substitutes CloudFormation parameter references (e.g. ${S3ModuleLocation})
        with values from the samconfig parameter_overrides so the Location becomes
        a literal S3 URL. All other intrinsic functions are preserved in long form.
        The resolved template is written to temp_dir/template-resolved.yml.

        CloudFormation resolves the (now literal) AWS::Include locations and any
        AWS::Serverless transform server-side at deploy time, so no sam package or
        module download is required.

        Args:
            template_path: Path to the downloaded/local template (YAML).
            temp_dir: Temporary directory for the resolved template.

        Returns:
            Path to temp_dir/template-resolved.yml.

        Raises:
            ValueError: Propagated from _resolve_parameter_references when a
                required parameter is missing or the Location format is unsupported.
        """
        ConsoleAndLog.info("Resolving S3 include locations in template")

        with open(template_path, 'r') as f:
            template = yaml.load(f, Loader=_CfnLoader)

        parameter_overrides = self._read_parameter_overrides()

        def process_includes(obj):
            if isinstance(obj, dict):
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
                        probe = self._location_probe_string(location)
                        if name == 'AWS::Include' and self._is_s3_url(probe):
                            resolved = self._resolve_parameter_references(
                                location, parameter_overrides
                            )
                            transform['Parameters']['Location'] = resolved
                            ConsoleAndLog.info(
                                f"Resolved include location: {resolved}"
                            )

                for value in obj.values():
                    process_includes(value)
            elif isinstance(obj, list):
                for item in obj:
                    process_includes(item)

        process_includes(template)

        resolved_path = temp_dir / "template-resolved.yml"
        with open(resolved_path, 'w') as f:
            yaml.dump(template, f, default_flow_style=False, sort_keys=False)

        ConsoleAndLog.info(f"Wrote resolved template: {resolved_path}")
        return resolved_path

    def _read_deploy_params_for_packaged(self) -> dict:
        """Read all deploy parameters needed to run sam deploy without --config-file.

        When deploying a packaged template that still contains Fn::Transform
        AWS::Include entries, passing --config-file to sam deploy causes it to
        pre-validate every S3 artifact reference in the template, which fails.
        This method reads all required parameters so they can be passed as
        explicit CLI flags instead, bypassing SAM's artifact pre-validation.

        Returns:
            Dict with keys: stack_name, capabilities, region, role_arn (optional),
            confirm_changeset, parameter_overrides (str), tags (str).

        Raises:
            ValueError: When required parameters (stack_name, region) are missing
                or the samconfig cannot be read.

        Example:
            >>> params = deployer._read_deploy_params_for_packaged()
            >>> params['stack_name']
            'my-stack'
        """
        reader = SamconfigReader(self.get_samconfig_file_path())
        atlantis_params = reader.read_atlantis_params()
        stage_params = reader.read_deploy_params(self.stage_id)

        # Merge: stage overrides atlantis/default
        merged = {**atlantis_params, **stage_params}

        stack_name = merged.get('stack_name', '')
        if not stack_name:
            raise ValueError(
                "stack_name not found in samconfig. Run 'config.py' to configure."
            )

        region = merged.get('region', '')
        if not region:
            raise ValueError(
                "region not found in samconfig. Run 'config.py' to configure."
            )

        return {
            'stack_name': stack_name,
            'capabilities': merged.get('capabilities', 'CAPABILITY_NAMED_IAM'),
            'region': region,
            'role_arn': merged.get('role_arn', ''),
            'confirm_changeset': merged.get('confirm_changeset', True),
            'parameter_overrides': merged.get('parameter_overrides', ''),
            'tags': merged.get('tags', ''),
        }

    def _cfn_deploy_packaged(
        self, template_path: Path, deploy_params: dict
    ) -> int:
        """Deploy a resolved template directly via CloudFormation boto3 API.

        SAM CLI's ``sam deploy`` pre-validates every ``s3://`` URI found inside
        the template body before submitting to CloudFormation, causing
        ``Template file not found`` errors for ``Fn::Transform: AWS::Include``
        artifact references even when those objects exist. Calling CloudFormation
        directly via boto3 bypasses this pre-validation — CloudFormation handles
        ``AWS::Include`` macros natively during stack execution.

        Uses a CloudFormation change set workflow:
        1. Read template body from local packaged template file
        2. Create a change set (CREATE or UPDATE depending on stack state)
        3. Wait for change set to finish creating
        4. If no changes, return 0 (no-op)
        5. Execute the change set
        6. Wait for stack operation to complete
        7. Return 0 on success, 1 on failure

        Args:
            template_path: Local path to the packaged template file produced by
                ``sam package``.
            deploy_params: Dict from ``_read_deploy_params_for_packaged`` with
                keys: stack_name, capabilities, region, role_arn, confirm_changeset,
                parameter_overrides (raw string), tags (raw string).

        Returns:
            0 on success (including no-change deployments), 1 on failure.

        Example:
            >>> params = deployer._read_deploy_params_for_packaged()
            >>> exit_code = deployer._cfn_deploy_packaged(
            ...     Path('/tmp/work/template-packaged.yml'), params
            ... )
            >>> exit_code
            0
        """
        import time

        stack_name = deploy_params['stack_name']
        region = deploy_params['region']
        capabilities = [
            c.strip()
            for c in deploy_params.get('capabilities', 'CAPABILITY_NAMED_IAM').split(',')
            if c.strip()
        ]
        role_arn = deploy_params.get('role_arn', '')
        parameter_overrides_str = deploy_params.get('parameter_overrides', '')
        tags_str = deploy_params.get('tags', '')

        # Parse parameter_overrides string → list of {ParameterKey, ParameterValue}
        params_dict = SamconfigReader.parse_parameter_overrides(parameter_overrides_str)
        cfn_parameters = [
            {'ParameterKey': k, 'ParameterValue': v}
            for k, v in params_dict.items()
        ]

        # Parse tags string → list of {Key, Value}
        tags_dict = SamconfigReader.parse_parameter_overrides(tags_str)
        cfn_tags = [{'Key': k, 'Value': v} for k, v in tags_dict.items()]

        # Read template body
        with open(template_path, 'r') as f:
            template_body = f.read()

        cfn_client = self.aws_session.get_client('cloudformation', region)

        # CloudFormation caps inline TemplateBody at 51,200 bytes; upload to S3
        # and use TemplateURL for larger templates.
        TEMPLATE_BODY_MAX_BYTES = 51200
        template_source = {}
        # Track the artifact bucket for the values summary; remains None when
        # the template is small enough to submit inline via TemplateBody.
        s3_bucket_display = None
        if len(template_body.encode('utf-8')) > TEMPLATE_BODY_MAX_BYTES:
            s3_bucket, s3_prefix = self._read_artifact_bucket_config()
            key = (
                f"{s3_prefix}/template-resolved.yml"
                if s3_prefix else "template-resolved.yml"
            )
            ConsoleAndLog.info(
                f"Template exceeds {TEMPLATE_BODY_MAX_BYTES} bytes; "
                f"uploading to s3://{s3_bucket}/{key} for TemplateURL"
            )
            self.s3_client.upload_file(str(template_path), s3_bucket, key)
            template_source['TemplateURL'] = (
                f"https://s3.{region}.amazonaws.com/{s3_bucket}/{key}"
            )
            s3_bucket_display = s3_bucket
        else:
            template_source['TemplateBody'] = template_body

        # Pre-deploy values summary (parity with the SAM branch). The S3 bucket
        # line is shown only on the large-template/S3-upload path.
        self._print_deploy_values_summary(
            deploy_params, cfn_parameters, cfn_tags, s3_bucket_display
        )

        # Determine if stack exists (CREATE vs UPDATE change set type)
        change_set_type = 'CREATE'
        try:
            resp = cfn_client.describe_stacks(StackName=stack_name)
            stack_status = resp['Stacks'][0]['StackStatus']
            # REVIEW_IN_PROGRESS means a change set was started but never executed
            if stack_status == 'REVIEW_IN_PROGRESS':
                change_set_type = 'CREATE'
            else:
                change_set_type = 'UPDATE'
        except cfn_client.exceptions.ClientError as e:
            if 'does not exist' in str(e):
                change_set_type = 'CREATE'
            else:
                ConsoleAndLog.error(f"Error checking stack status: {str(e)}")
                return 1

        change_set_name = f"deploy-{int(time.time())}"
        ConsoleAndLog.info(
            f"Creating CloudFormation change set '{change_set_name}' "
            f"({change_set_type}) for stack '{stack_name}'"
        )

        # Build create_change_set kwargs
        cs_kwargs = {
            'StackName': stack_name,
            'ChangeSetName': change_set_name,
            'ChangeSetType': change_set_type,
            'Capabilities': capabilities,
            'Parameters': cfn_parameters,
            'Tags': cfn_tags,
            **template_source,
        }
        if role_arn:
            cs_kwargs['RoleARN'] = role_arn

        try:
            cfn_client.create_change_set(**cs_kwargs)
        except Exception as e:
            ConsoleAndLog.error(f"Failed to create change set: {str(e)}")
            return 1

        # Wait for change set to finish creating
        ConsoleAndLog.info("Waiting for change set to be created...")
        waiter = cfn_client.get_waiter('change_set_create_complete')
        try:
            waiter.wait(
                StackName=stack_name,
                ChangeSetName=change_set_name,
                WaiterConfig={'Delay': 5, 'MaxAttempts': 60}
            )
        except Exception:
            # Check if it failed because there are no changes
            try:
                cs = cfn_client.describe_change_set(
                    StackName=stack_name,
                    ChangeSetName=change_set_name
                )
                status = cs.get('Status', '')
                reason = cs.get('StatusReason', '')
                if "didn't contain changes" in reason:
                    ConsoleAndLog.info(f"No changes to deploy: {reason}")
                    # Clean up the empty change set
                    try:
                        cfn_client.delete_change_set(
                            StackName=stack_name,
                            ChangeSetName=change_set_name
                        )
                    except Exception:
                        pass
                    return 0
                else:
                    # Real failure (e.g. transform error, permissions issue)
                    ConsoleAndLog.error(
                        f"Change set creation failed ({status}): {reason}"
                    )
                    try:
                        cfn_client.delete_change_set(
                            StackName=stack_name,
                            ChangeSetName=change_set_name
                        )
                    except Exception:
                        pass
                    return 1
            except Exception as inner_e:
                ConsoleAndLog.error(f"Failed to describe change set: {str(inner_e)}")
            ConsoleAndLog.error("Change set creation failed")
            return 1

        # Change set was created successfully and contains changes. Describe it
        # to list the pending changes. A failure to describe/list the changes is
        # treated as non-fatal: it is logged as a warning so it does not fail an
        # otherwise healthy deploy.
        try:
            cs = cfn_client.describe_change_set(
                StackName=stack_name,
                ChangeSetName=change_set_name
            )
            self._print_changeset_summary(cs.get('Changes', []))
        except Exception as e:
            ConsoleAndLog.warning(
                "Could not list change set changes; continuing with deploy", e
            )

        # Confirmation gate: honor confirm_changeset unless running headless
        # (override_confirm_changeset). On decline, delete the pending change
        # set and return non-zero so main() skips the post-deploy git commit/push
        # and termination protection.
        needs_confirm = bool(deploy_params.get('confirm_changeset', True)) \
            and not self.override_confirm_changeset
        if needs_confirm:
            if not click.confirm(
                Colorize.question("Deploy this change set?"), default=False
            ):
                ConsoleAndLog.info("Deployment cancelled by user.")
                try:
                    cfn_client.delete_change_set(
                        StackName=stack_name,
                        ChangeSetName=change_set_name
                    )
                except Exception:
                    pass
                return 1

        # Initiating deployment (yellow heading, parity with the SAM branch)
        self._print_section_heading("Initiating deployment")

        # Execute the change set
        ConsoleAndLog.info(f"Executing change set '{change_set_name}'...")
        try:
            cfn_client.execute_change_set(
                StackName=stack_name,
                ChangeSetName=change_set_name
            )
        except Exception as e:
            ConsoleAndLog.error(f"Failed to execute change set: {str(e)}")
            return 1

        # Wait for the stack operation to complete using a manual polling loop
        # (green per-interval StackStatus) rather than a silent boto3 waiter.
        ConsoleAndLog.info("Waiting for stack update to complete...")
        succeeded = self._wait_for_stack_operation(
            cfn_client, stack_name, change_set_type
        )

        if succeeded:
            ConsoleAndLog.info(f"Stack '{stack_name}' deployed successfully.")
            self._print_success_banner()
            # Read and display the stack Outputs. A failure to read/print the
            # Outputs is non-fatal: it is logged as a warning and does not
            # change the (successful) exit code.
            try:
                describe = cfn_client.describe_stacks(StackName=stack_name)
                outputs = describe['Stacks'][0].get('Outputs', [])
                if outputs:
                    self._print_stack_outputs(outputs)
            except Exception as e:
                ConsoleAndLog.warning(
                    "Could not read stack Outputs; deployment succeeded", e
                )
            return 0

        # Failure path: print up to 10 FAILED stack events for diagnosis,
        # colorized with Colorize.error while preserving log-file continuity.
        ConsoleAndLog.error("Stack operation failed.")
        try:
            events = cfn_client.describe_stack_events(StackName=stack_name)
            for event in events['StackEvents'][:10]:
                if event.get('ResourceStatus', '').endswith('FAILED'):
                    message = (
                        f"  {event['LogicalResourceId']}: "
                        f"{event.get('ResourceStatusReason', 'no reason')}"
                    )
                    Log.error(message)
                    click.echo(Colorize.error(message))
        except Exception:
            pass
        return 1

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