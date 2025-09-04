#!/usr/bin/env python3

VERSION = "v0.0.3/2025-08-26"
# Created by Chad Kluck with AI assistance from Amazon Q Developer

# Usage Information:
# delete.py -h

# Full Documentation:
# https://github.com/chadkluck/atlantis-cfn-configuration-repo-for-serverless-deployments/

import toml
import sys
import argparse
import click
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import random
import string

from lib.aws_session import AWSSessionManager
from lib.logger import ScriptLogger, Log
from lib.tools import Colorize
from lib.atlantis import DefaultsLoader
from lib.gitops import Git

if sys.version_info[0] < 3:
    sys.stderr.write("Error: Python 3 is required\n")
    sys.exit(1)

# Initialize logger for this script
ScriptLogger.setup('delete')

SAMCONFIG_DIR = "samconfigs"
SETTINGS_DIR = "defaults"
VALID_INFRA_TYPES = ['pipeline', 'storage', 'network', 'iam']

class StackDestroyer:
    """
    Manages destruction of AWS CloudFormation/SAM stacks.
    """
    
    def __init__(self, infra_type: str, prefix: str, project_id: str, stage_id: str, 
                    profile: Optional[str] = None, region: Optional[str] = None, 
                    no_browser: Optional[bool] = False):
        self.infra_type = infra_type
        self.prefix = prefix
        self.project_id = project_id
        self.stage_id = stage_id
        self.profile = profile
        self.region = region
        
        self._validate_args()
        
        # Set up AWS session and clients
        self.aws_session = AWSSessionManager(profile, region, no_browser)
        self.cfn_client = self.aws_session.get_client('cloudformation', region)
        self.ssm_client = self.aws_session.get_client('ssm', region)
        
        config_loader = DefaultsLoader(
            settings_dir=self.get_settings_dir(),
            prefix=self.prefix,
            project_id=self.project_id,
            infra_type=self.infra_type
        )
        
        self.settings = config_loader.load_settings()

        self.skipped_resources = []

    def _validate_args(self) -> None:
        """Validate arguments"""
        if self.infra_type not in VALID_INFRA_TYPES:
            raise click.UsageError(f"Invalid infra_type. Must be one of {VALID_INFRA_TYPES}")

    def get_settings_dir(self) -> Path:
        """Get the settings directory path"""
        script_dir = Path(__file__).resolve().parent
        return script_dir.parent / SETTINGS_DIR

    def get_samconfig_dir(self) -> Path:
        """Get the samconfig directory path"""
        script_dir = Path(__file__).resolve().parent
        return script_dir.parent / SAMCONFIG_DIR / self.prefix / self.project_id

    def get_samconfig_file_name(self) -> str:
        """Get the samconfig file name"""
        return f"samconfig-{self.prefix}-{self.project_id}-{self.infra_type}.toml"

    def get_samconfig_file_path(self) -> Path:
        """Get the samconfig file path"""
        return self.get_samconfig_dir() / self.get_samconfig_file_name()

    def get_pipeline_stack_name(self) -> str:
        """Get the pipeline stack name"""
        return f"{self.prefix}-{self.project_id}-{self.stage_id}-pipeline"

    def get_application_stack_name(self) -> str:
        """Get the application stack name"""
        return f"{self.prefix}-{self.project_id}-{self.stage_id}-application"

    def validate_stack_arn(self, stack_name: str, expected_name: str) -> bool:
        """Validate that the provided ARN matches the expected stack name"""

        try:
            arn = ""
            while arn == "":
                arn = Colorize.prompt(f"Enter the ARN of the {stack_name} stack", "", str)
                arn = arn.strip()
                if arn == "":
                    click.echo(Colorize.error("ARN cannot be empty"))
            
            # Extract stack name from ARN
            try:
                # ARN format: arn:aws:cloudformation:region:account:stack/stack-name/stack-id
                arn_parts = arn.split('/')
                if len(arn_parts) >= 2:
                    actual_stack_name = arn_parts[1]
                    if actual_stack_name == expected_name:
                        return True
                    else:
                        message = f"Stack name mismatch. Expected: {expected_name}, Got: {actual_stack_name}"
                        click.echo(Colorize.error(message))
                        Log.error(message)
                        return False
                else:
                    message = "Invalid ARN format"
                    click.echo(Colorize.error(message))
                    Log.error(f"{message}:  {arn}")
                    return False
            except Exception as e:
                message = f"Error parsing ARN: {str(e)}"
                click.echo(Colorize.error(message))
                Log.error(f"{message} {arn}")
                return False
        
        except KeyboardInterrupt:
            click.echo(Colorize.error("\nOperation cancelled by user"))
            Log.info("Operation cancelled by user")
            sys.exit(1)

    def check_delete_tag(self, stack_name: str) -> bool:
        """Check if stack has DeleteOnOrAfter tag with valid date"""
        try:
            response = self.cfn_client.describe_stacks(StackName=stack_name)
            stack = response['Stacks'][0]
            tags = {tag['Key']: tag['Value'] for tag in stack.get('Tags', [])}
            
            delete_date_str = tags.get('DeleteOnOrAfter')
            if not delete_date_str:
                click.echo(Colorize.error(f"Stack {stack_name} does not have DeleteOnOrAfter tag"))
                return False
            
            # Parse date
            try:
                if delete_date_str.endswith('Z'):
                    delete_date = datetime.fromisoformat(delete_date_str[:-1]).replace(tzinfo=timezone.utc)
                    current_date = datetime.now(timezone.utc)
                else:
                    delete_date = datetime.fromisoformat(delete_date_str).date()
                    current_date = datetime.now().date()
                
                if current_date >= delete_date:
                    message = f"DeleteOnOrAfter tag validation passed: {delete_date_str}"
                    click.echo(Colorize.success(message))
                    Log.info(message)
                    return True
                else:
                    message = f"Current date ({current_date}) is before DeleteOnOrAfter date ({delete_date})"
                    click.echo(Colorize.error(message))
                    Log.error(message)
                    return False
            except ValueError as e:
                message = f"Invalid date format in DeleteOnOrAfter tag: {delete_date_str}"
                click.echo(Colorize.error(message))
                Log.error(message)
                return False
                
        except Exception as e:
            message = f"Error checking DeleteOnOrAfter tag: {str(e)}"
            click.echo(Colorize.error(message))
            Log.error(message)
            return False

    def check_stack_termination_protection(self, stack_name: str) -> bool:
        """Check if stack termination protection is disabled"""
        try:
            response = self.cfn_client.describe_stacks(StackName=stack_name)
            stack = response['Stacks'][0]
            
            termination_protection = stack.get('EnableTerminationProtection', False)
            
            if not termination_protection:
                message = f"Stack termination protection validation passed: Stack {stack_name} has termination protection disabled"
                click.echo(Colorize.success(message))
                Log.info(message)
                return True
            else:
                message = f"Stack termination protection validation failed: Stack {stack_name} has termination protection enabled"
                click.echo(Colorize.error(message))
                Log.error(message)
                return False
                
        except Exception as e:
            message = f"Error checking stack termination protection for {stack_name}: {str(e)}"
            click.echo(Colorize.error(message))
            Log.error(message)
            return False

    def final_confirmation(self) -> bool:
        """Final confirmation by entering prefix, project_id, and stage_id"""
        click.echo(Colorize.warning("For final confirmation, please enter the Prefix, ProjectId, and StageId of the pipeline and application to delete."))
        
        entered_prefix = Colorize.prompt("Prefix", "", str)
        entered_project_id = Colorize.prompt("ProjectId", "", str)
        entered_stage_id = Colorize.prompt("StageId", "", str)
        
        if (entered_prefix == self.prefix and 
            entered_project_id == self.project_id and 
            entered_stage_id == self.stage_id):
            return True
        else:
            click.echo(Colorize.error("Confirmation failed. Values do not match."))
            Log.error("Confirmation failed. Values from user do not match.")
            return False

    def delete_stack(self, stack_name: str) -> bool:
        """Delete a CloudFormation stack"""
        import time
        
        try:
            click.echo(Colorize.output(f"Deleting stack: {stack_name}"))
            Log.info(f"Deleting stack: {stack_name}")
            
            self.cfn_client.delete_stack(StackName=stack_name)
            
            # Custom polling loop with progress updates
            max_attempts = 180  # 30 minutes max
            attempt = 0
            
            while attempt < max_attempts:
                try:
                    response = self.cfn_client.describe_stacks(StackName=stack_name)
                    stack_status = response['Stacks'][0]['StackStatus']
                    
                    if stack_status == 'DELETE_COMPLETE':
                        click.echo(Colorize.success(f"Stack {stack_name} deleted successfully"))
                        Log.info(f"Stack {stack_name} deleted successfully")
                        return True
                    elif stack_status in ['DELETE_FAILED', 'ROLLBACK_COMPLETE']:
                        click.echo(Colorize.error(f"Stack deletion failed with status: {stack_status}"))
                        Log.error(f"Stack deletion failed with status: {stack_status}")
                        return False
                    else:
                        click.echo(Colorize.output(f"Stack deletion in progress... Status: {stack_status}"))
                        
                except self.cfn_client.exceptions.ClientError as e:
                    if 'does not exist' in str(e):
                        click.echo(Colorize.success(f"Stack {stack_name} deleted successfully"))
                        Log.info(f"Stack {stack_name} deleted successfully")
                        return True
                    else:
                        raise
                
                time.sleep(10)
                attempt += 1
            
            click.echo(Colorize.error(f"Stack deletion timed out after 30 minutes"))
            Log.error(f"Stack deletion timed out after 30 minutes")
            return False
        
        except KeyboardInterrupt:
            click.echo(Colorize.error("\nOperation cancelled by user"))
            Log.info("Operation cancelled by user")
            sys.exit(1)
        except Exception as e:
            click.echo(Colorize.error(f"Error deleting stack {stack_name}: {str(e)}"))
            Log.error(f"Error deleting stack {stack_name}: {str(e)}")
            return False

    def delete_ssm_parameters(self) -> None:
        """Delete SSM parameters associated with the application"""
        try:
            # Check for ParameterStoreHierarchy in application stack
            application_stack_name = self.get_application_stack_name()
            parameter_store_hierarchy = ""
            
            try:
                response = self.cfn_client.describe_stacks(StackName=application_stack_name)
                stack = response['Stacks'][0]
                parameters = {param['ParameterKey']: param['ParameterValue'] for param in stack.get('Parameters', [])}
                parameter_store_hierarchy = parameters.get('ParameterStoreHierarchy', '')
            except Exception as e:
                Log.warning(f"Could not get ParameterStoreHierarchy from stack {application_stack_name}: {str(e)}")
            
            application_suffix = f"/{self.prefix}-{self.project_id}-{self.stage_id}/"

            # if parameter_store_hierarchy and ends with application_suffix
            if parameter_store_hierarchy and parameter_store_hierarchy.endswith(application_suffix):
                parameter_prefix = parameter_store_hierarchy
            else:
                parameter_prefix = application_suffix
            
            # List parameters with the prefix
            paginator = self.ssm_client.get_paginator('describe_parameters')
            parameters_to_delete = []
            
            for page in paginator.paginate():
                for param in page['Parameters']:
                    if param['Name'].startswith(parameter_prefix):
                        parameters_to_delete.append(param['Name'])
            
            if parameters_to_delete:
                click.echo(Colorize.output(f"Found {len(parameters_to_delete)} SSM parameters to delete"))
                Log.info(f"Found {len(parameters_to_delete)} SSM parameters to delete: {parameters_to_delete}")
                
                # List the parameters
                for param in parameters_to_delete:
                    click.echo(Colorize.output(f" - {param}"))

                # confirm deletion of parameters
                print()
                if not click.confirm(Colorize.question("Proceed with deletion of these SSM parameters?"), default=True):
                    click.echo(Colorize.error("SSM parameter deletion cancelled by user"))
                    Log.info("SSM parameter deletion cancelled by user")
                    self.skipped_resources += parameters_to_delete
                    return
                
                # Delete parameters in batches of 10 (AWS limit)
                for i in range(0, len(parameters_to_delete), 10):
                    batch = parameters_to_delete[i:i+10]
                    self.ssm_client.delete_parameters(Names=batch)
                    
                click.echo(Colorize.success(f"Deleted {len(parameters_to_delete)} SSM parameters"))
                Log.info(f"Deleted {len(parameters_to_delete)} SSM parameters")
            else:
                click.echo(Colorize.output("No SSM parameters found to delete"))
                Log.info("No SSM parameters found to delete")

        except KeyboardInterrupt:
            click.echo(Colorize.error("\nOperation cancelled by user"))
            Log.info("Operation cancelled by user")
            sys.exit(1)                
        except Exception as e:
            click.echo(Colorize.error(f"Error deleting SSM parameters: {str(e)}"))
            Log.error(f"Error deleting SSM parameters: {str(e)}")


    def delete_resources_by_tag(self) -> None:
        """Discover and delete resources by atlantis:ApplicationDeploymentId tag"""

        tag_key = "atlantis:ApplicationDeploymentId"
        tag_value = f"{self.prefix}-{self.project_id}"
        if self.stage_id:
            tag_value += f"-{self.stage_id}"

        # find resources in AWS with tag
        try:
            click.echo(Colorize.output(f"Searching for resources with tag {tag_key}={tag_value}"))
            Log.info(f"Searching for resources with tag {tag_key}={tag_value}")

            # Common resources with retention policies
            resource_types = [
                's3',
                'dynamodb:table',
                'logs:log-group',
                'ssm:parameter'
            ]

            resources_to_delete = []

            for resource_type in resource_types:
                paginator = self.aws_session.get_client('resourcegroupstaggingapi', self.region).get_paginator('get_resources')
                for page in paginator.paginate(ResourceTypeFilters=[resource_type], TagFilters=[{'Key': tag_key, 'Values': [tag_value]}]):
                    for resource in page['ResourceTagMappingList']:
                        resources_to_delete.append(resource['ResourceARN'])

            if resources_to_delete:
                click.echo(Colorize.output(f"Found {len(resources_to_delete)} additional resource(s) to delete"))
                print()
                Colorize.box_warning([{"header": "Check Retention Policies", "text": "This may include resources not managed by this pipeline or resources with extended retention policies. Proceed with caution and only delete according to your organization's data retention policy."}])
                print()
                Log.info(f"Found {len(resources_to_delete)} resources to delete: {resources_to_delete}")

                # List the resources
                for res in resources_to_delete:
                    click.echo(Colorize.output(f" - {res}"))

                # confirm deletion of resources
                print()
                if not click.confirm(Colorize.question("Proceed with deletion of some or all of these resources? (you will confirm/skip each one)")):
                    click.echo(Colorize.error("Resource deletion cancelled by user"))
                    Log.info("Resource deletion cancelled by user")
                    self.skipped_resources += resources_to_delete
                    return

                # Delete resources one by one with confirmation, list the resource and have user confirm y/N and if yes further confirm with a random 5 character code
                for res in resources_to_delete:
                    print()
                    click.echo(Colorize.output(f"Preparing to delete resource: {res}"))
                    if click.confirm(Colorize.question(f"Are you sure you want to delete resource: {res}?"), default=False):

                        # Generate a random 5 character code
                        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
                        # replace 0 and O with Z and X
                        code = code.replace('0', 'Z').replace('O', 'X')
                        # display code to user with spaces so they don't copy/paste
                        display_code = ' '.join(code)
                        entered_code = Colorize.prompt(f"Type the code '{display_code}' (without spaces) to confirm deletion", "", str)
                        if entered_code == code:
                            try:
                                if res.startswith("arn:aws:s3:::"):
                                    s3_client = self.aws_session.get_client('s3', self.region)
                                    bucket_name = res.split(":::")[1]
                                    
                                    # Use batch delete for better performance
                                    paginator = s3_client.get_paginator('list_object_versions')
                                    for page in paginator.paginate(Bucket=bucket_name):
                                        objects_to_delete = []
                                        
                                        # Collect versions and delete markers
                                        for version in page.get('Versions', []):
                                            objects_to_delete.append({'Key': version['Key'], 'VersionId': version['VersionId']})
                                        for marker in page.get('DeleteMarkers', []):
                                            objects_to_delete.append({'Key': marker['Key'], 'VersionId': marker['VersionId']})
                                        
                                        # Delete in batches of 1000 (AWS limit)
                                        if objects_to_delete:
                                            s3_client.delete_objects(
                                                Bucket=bucket_name,
                                                Delete={'Objects': objects_to_delete}
                                            )
                                    
                                    # Delete the bucket
                                    s3_client.delete_bucket(Bucket=bucket_name)
                                    click.echo(Colorize.success(f"Deleted S3 bucket: {bucket_name}"))
                                    Log.info(f"Deleted S3 bucket: {bucket_name}")
                                elif ":dynamodb:" in res:
                                    dynamodb_client = self.aws_session.get_client('dynamodb', self.region)
                                    table_name = res.split("/")[-1]
                                    dynamodb_client.delete_table(TableName=table_name)
                                    click.echo(Colorize.success(f"Deleted DynamoDB table: {table_name}"))
                                    Log.info(f"Deleted DynamoDB table: {table_name}")
                                elif ":logs:" in res:
                                    logs_client = self.aws_session.get_client('logs', self.region)
                                    log_group_name = res.split(":log-group:")[-1]
                                    logs_client.delete_log_group(logGroupName=log_group_name)
                                    click.echo(Colorize.success(f"Deleted CloudWatch log group: {log_group_name}"))
                                    Log.info(f"Deleted CloudWatch log group: {log_group_name}")
                                elif ":ssm:" in res:
                                    ssm_client = self.aws_session.get_client('ssm', self.region)
                                    parameter_name = res.split(":parameter/")[-1]
                                    ssm_client.delete_parameter(Name=parameter_name)
                                    click.echo(Colorize.success(f"Deleted SSM parameter: {parameter_name}"))
                                    Log.info(f"Deleted SSM parameter: {parameter_name}")
                                else:
                                    click.echo(Colorize.warning(f"Unsupported resource type for deletion: {res}"))
                                    Log.warning(f"Unsupported resource type for deletion: {res}")
                                    self.skipped_resources.append(res)

                            except KeyboardInterrupt:
                                click.echo(Colorize.error("\nOperation cancelled by user"))
                                Log.info("Operation cancelled by user")
                                sys.exit(1)
                            except Exception as e:
                                click.echo(Colorize.error(f"Error deleting resource {res}: {str(e)}"))
                                Log.error(f"Error deleting resource {res}: {str(e)}")
                                self.skipped_resources.append(res)

                        else:
                            click.echo(Colorize.error("Confirmation code mismatch. Skipping deletion."))
                            Log.info(f"Confirmation code mismatch for resource: {res}. Skipping deletion.")
                            self.skipped_resources.append(res)

                    else:
                        click.echo(Colorize.warning(f"Skipping deletion of resource: {res}"))
                        Log.info(f"Skipping deletion of resource: {res}")
                        self.skipped_resources.append(res)

            else:
                click.echo(Colorize.output("No additional resources found to delete"))
                Log.info("No additional resources found to delete")

        except KeyboardInterrupt:
            click.echo(Colorize.error("\nOperation cancelled by user"))
            Log.info("Operation cancelled by user")
            sys.exit(1)
        except Exception as e:
            click.echo(Colorize.error(f"Error deleting resources: {str(e)}"))
            Log.error(f"Error deleting resources: {str(e)}")     


    def update_samconfig(self) -> None:
        """Update or delete samconfig file"""
        samconfig_path = self.get_samconfig_file_path()
        
        if not samconfig_path.exists():
            click.echo(Colorize.warning("Samconfig file not found"))
            return
        
        if click.confirm(Colorize.question("Delete samconfig entry for this deployment?")):
            try:
                # Load current config
                with open(samconfig_path, 'r') as f:
                    config = toml.load(f)
                
                # Remove the environment section (e.g., test.deploy.parameters)
                if self.stage_id in config:
                    del config[self.stage_id]
                    click.echo(Colorize.success(f"Removed {self.stage_id} environment from samconfig"))
                    Log.info(f"Removed {self.stage_id} environment from samconfig")
                
                # Count remaining environments (exclude 'atlantis' and 'version')
                remaining_envs = [key for key in config.keys() if key not in ['atlantis', 'version']]
                
                # If no environments left, delete the file
                if not remaining_envs:
                    samconfig_path.unlink()
                    click.echo(Colorize.success("Deleted samconfig file (no environments remaining)"))
                    Log.info("Deleted samconfig file (no environments remaining)")
                    
                    # Delete parent directory if empty
                    parent_dir = samconfig_path.parent
                    try:
                        parent_dir.rmdir()  # Only removes if empty
                        click.echo(Colorize.success(f"Deleted empty directory: {parent_dir}"))
                        Log.info(f"Deleted empty directory: {parent_dir}")
                    except OSError:
                        # Directory not empty or other error, ignore
                        pass
                else:
                    # Save updated config
                    with open(samconfig_path, 'w') as f:
                        toml.dump(config, f)
                    click.echo(Colorize.success("Updated samconfig file"))
                    Log.info("Updated samconfig file")
            
            except KeyboardInterrupt:
                click.echo(Colorize.error("\nOperation cancelled by user"))
                Log.info("Operation cancelled by user")
                sys.exit(1)
            except Exception as e:
                click.echo(Colorize.error(f"Error updating samconfig: {str(e)}"))
                Log.error(f"Error updating samconfig: {str(e)}")

        else:
            click.echo(Colorize.warning("Samconfig file not deleted"))
            Log.info("Samconfig file not deleted")
            self.skipped_resources.append(f"{self.stage_id} in {samconfig_path}")

    def destroy_pipeline(self) -> None:
        """Destroy pipeline infrastructure"""
        click.echo(Colorize.output_bold(f"Starting destruction of pipeline: {self.prefix}-{self.project_id}-{self.stage_id}"))
        
        # 1. Git pull prompt
        print()
        Git.prompt_git_pull()
        
        # 2. Validate pipeline stack ARN
        print()
        pipeline_stack_name = self.get_pipeline_stack_name()
        click.echo(Colorize.output_bold("Step 1: Validate Pipeline Stack ARN"))
        if not self.validate_stack_arn("pipeline", pipeline_stack_name):
            click.echo(Colorize.error("Pipeline stack validation failed"))
            sys.exit(1)
        
        # 3. Validate application stack ARN
        print()
        application_stack_name = self.get_application_stack_name()
        click.echo(Colorize.output_bold("Step 2: Validate Application Stack ARN"))
        if not self.validate_stack_arn("application", application_stack_name):
            click.echo(Colorize.error("Application stack validation failed"))
            sys.exit(1)
        
        # 4. Check DeleteOnOrAfter tag
        print()
        click.echo(Colorize.output_bold("Step 3a: Validate DeleteOnOrAfter Tag"))
        if not self.check_delete_tag(pipeline_stack_name):
            click.echo(Colorize.error("DeleteOnOrAfter tag validation failed"))
            sys.exit(1)

        # 5. Check Stack Termination Protection tag for Pipeline
        print()
        click.echo(Colorize.output_bold("Step 3b: Validate Stack Termination Protection is Disabled for Pipeline"))
        if not self.check_stack_termination_protection(pipeline_stack_name):
            click.echo(Colorize.error("Stack Termination Protection must be disabled first."))
            sys.exit(1)

        # 6. Check Stack Termination Protection tag for Application
        print()
        click.echo(Colorize.output_bold("Step 3c: Validate Stack Termination Protection is Disabled for Application"))
        if not self.check_stack_termination_protection(application_stack_name):
            click.echo(Colorize.error("Stack Termination Protection must be disabled first."))
            sys.exit(1)
        
        # 7. Final confirmation
        print()
        click.echo(Colorize.output_bold("Step 4: Final Confirmation"))
        if not self.final_confirmation():
            click.echo(Colorize.error("Final confirmation failed"))
            sys.exit(1)
        
        # 8. Begin deletion
        print()
        click.echo(Colorize.output_bold("Step 5: Beginning Deletion Process"))

        # Delete SSM parameters
        print()
        self.delete_ssm_parameters()

        # Delete application stack first
        print()
        if not self.delete_stack(application_stack_name):
            click.echo(Colorize.error("Failed to delete application stack"))
            sys.exit(1)

        # Delete pipeline stack
        print()
        if not self.delete_stack(pipeline_stack_name):
            click.echo(Colorize.error("Failed to delete pipeline stack"))
            sys.exit(1)
        
        # Delete retained resources
        print()
        self.delete_resources_by_tag()
        
        # Update samconfig
        print()
        self.update_samconfig()
        
        # 7. Git commit and push
        commit_message = f"Destroyed {self.infra_type} {self.prefix}-{self.project_id}"
        if self.stage_id:
            commit_message += f"-{self.stage_id}"
        print()
        Git.git_commit_and_push(commit_message)
        
        print()
        click.echo(Colorize.success("Pipeline destruction completed successfully!"))

        print()
        if self.skipped_resources:
            Log.info(f"The following resources were skipped by user: {self.skipped_resources}")
            click.echo(Colorize.warning("You chose to skip deleting the following resources:"))
            for res in self.skipped_resources:
                click.echo(Colorize.warning(f" - {res}"))
            click.echo(Colorize.warning("Please review and delete them manually if needed. This information was also saved to the local delete log file."))

    def destroy(self) -> None:
        """Main destroy method"""
        if self.infra_type == 'pipeline':
            self.destroy_pipeline()
        else:
            click.echo(Colorize.error(f"Destruction for {self.infra_type} is not implemented yet"))
            click.echo(Colorize.info("For storage, network, and iam: cleanup can be done by deleting the stack manually"))
            click.echo(Colorize.info("(Ensure S3 buckets are empty first)"))
            sys.exit(1)

# =============================================================================
# ----- Main function ---------------------------------------------------------
# =============================================================================

EPILOG = """
Examples:
    delete.py pipeline acme mywebapp test --profile ACME_DEV
    delete.py storage acme static-assets --profile ACME_DEV --region us-west-2
"""

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description='Destroy AWS SAM stacks created by Atlantis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(EPILOG)
    )
    parser.add_argument('infra_type', choices=VALID_INFRA_TYPES,
                        help='Type of infrastructure to destroy')
    parser.add_argument('prefix', help='Prefix for stack names')
    parser.add_argument('project_id', help='Project identifier')
    parser.add_argument('stage_id', help='Stage identifier')
    parser.add_argument('--profile', help='AWS profile to use')
    parser.add_argument('--region', help='AWS region')
    parser.add_argument('--no-browser', action='store_true',
                        help='Disable browser-based authentication')
    
    args = parser.parse_args()

    return args

def main():
    
    args = parse_args()
    Log.info(f"{sys.argv}")
    Log.info(f"Version: {VERSION}")
    
    print()
    click.echo(Colorize.divider("X", fg=Colorize.ERROR))
    click.echo(Colorize.output_bold(f"Destroyer ({VERSION})", fg=Colorize.ERROR))
    click.echo(Colorize.divider("X", fg=Colorize.ERROR))
    print()

    Colorize.box_error([{"header": "!!! CAUTION !!!", "text": "You are about to delete a CloudFormation stack. This action is irreversible and will remove all resources associated with the stack."}])
    print()

    try:
        destroyer = StackDestroyer(
            infra_type=args.infra_type,
            prefix=args.prefix,
            project_id=args.project_id,
            stage_id=args.stage_id,
            profile=args.profile,
            region=args.region,
            no_browser=args.no_browser
        )
        
        destroyer.destroy()

        print()
        
    except KeyboardInterrupt:
        click.echo(Colorize.error("\nOperation cancelled by user"))
        sys.exit(1)
    except Exception as e:
        click.echo(Colorize.error(f"Unexpected error: {str(e)}"))
        Log.error(f"Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()