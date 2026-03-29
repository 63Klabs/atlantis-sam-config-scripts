#!/usr/bin/env python3

VERSION = "v0.1.0/2025-03-30"
# Created by Chad Kluck with AI assistance from Amazon Q Developer
# GitHub Copilot assisted in color formats of output and prompts

# Usage Information:
# import.py -h

# Full Documentation:
# https://github.com/63klabs/atlantis-sam-config-scripts/

import tomlkit
import argparse
import os
import sys
from typing import Optional, Dict
from pathlib import Path
import yaml

from lib.aws_session import AWSSessionManager
from lib.logger import ScriptLogger, ConsoleAndLog, Log
from lib.tools import Strings

if sys.version_info[0] < 3:
    sys.stderr.write("Error: Python 3 is required\n")
    sys.exit(1)

# Initialize logger for this script
ScriptLogger.setup('import')

def format_key_value_pair(key, value):
    """Format key-value pairs with escaped quotes"""
    return f'"{key}"="{value}"'

IMPORT_DIR = "local-imports"
YAML_EXT = "yml"

class ConfigImporter:
    def __init__(self, stack_name: str, region: Optional[str] = None, profile: Optional[str] = None, no_browser: Optional[bool] = False) -> None:
        self.stack_name = stack_name
        self.region = region
        self.profile = profile

        self.tags = []
        self.parameters = {}
        self.capabilities = []

        self.aws_session = AWSSessionManager(self.profile, self.region, no_browser)
        self.cfn_client = self.aws_session.get_client('cloudformation', self.region)

    # -------------------------------------------------------------------------
    # - Samconfig Import
    # -------------------------------------------------------------------------

    def get_stack_info(self) -> Dict:
        """Retrieve stack information from CloudFormation"""
        
        try:
            # Get stack details
            stack = self.cfn_client.describe_stacks(StackName=self.stack_name)['Stacks'][0]
            
            # Get stack parameters
            self.parameters = {param['ParameterKey']: param['ParameterValue'] 
                        for param in stack.get('Parameters', [])}
            
            # Get stack tags
            self.tags = {tag['Key']: tag['Value'] 
                    for tag in stack.get('Tags', [])}
            
            self.capabilities = stack.get('Capabilities', [])
            
            if self.region is None:
                self.region = stack['StackId'].split(':')[3]
                        
            return {
                'parameters': self.parameters,
                'tags': self.tags,
                'capabilities': self.capabilities,
                'region': self.region
            }
        
        except Exception as e:
            ConsoleAndLog.error(f"Error getting stack information: {str(e)}")
            raise

    def create_sam_config(self) -> bool:
        """Create SAM config file in TOML format
        
        Returns:
            bool: True if successful, False otherwise
            
        Raises:
            ValueError: If required stack information is missing
            OSError: If there are file system related errors
            Exception: For other unexpected errors
        """
        try:

            config = tomlkit.document()
            
            # Create version
            config["version"] = 0.1
            
            # Create default config
            default = tomlkit.table()
            
            # Deploy configuration
            deploy = tomlkit.table()
            deploy["parameters"] = tomlkit.table()
                
            try:
                deploy["parameters"]["stack_name"] = self.stack_name
                deploy["parameters"]["region"] = self.region
                deploy["parameters"]["confirm_changeset"] = True
                deploy["parameters"]["capabilities"] = self.capabilities
            except KeyError as e:
                raise ValueError(f"Failed to set required parameter: {str(e)}")
                    
            # Add stack parameters
            try:
                parameter_overrides = []
                for key, value in self.parameters.items():
                    if value is None:
                        ConsoleAndLog.warning(f"Parameter '{key}' has None value, skipping")
                        continue
                    parameter_overrides.append(format_key_value_pair(key, value))

                if parameter_overrides:
                    deploy["parameters"]["parameter_overrides"] = " ".join(parameter_overrides)
            except Exception as e:
                ConsoleAndLog.warning(f"Error processing parameters: {str(e)}")
            
            # Add tags if they exist
            try:
                if self.tags:
                    tags = []
                    for key, value in self.tags.items():
                        if value is None:
                            ConsoleAndLog.warning(f"Tag '{key}' has None value, skipping")
                            continue
                        tags.append(format_key_value_pair(key, value))
                    if tags:
                        deploy["parameters"]["tags"] = " ".join(tags)
            except Exception as e:
                ConsoleAndLog.warning(f"Error processing tags: {str(e)}")
            
            default["deploy"] = deploy
            config["default"] = default
            
            # Create import directory if it doesn't exist
            import_dir = self.get_import_dir()
            try:
                if not os.path.exists(import_dir):
                    os.makedirs(import_dir)
            except OSError as e:
                raise OSError(f"Failed to create import directory {import_dir}: {str(e)}")
                
            # Write to samconfig.toml
            file_path = self.get_import_file_path()
            try:
                with open(file_path, "w") as f:
                    tomlkit.dump(config, f)
            except OSError as e:
                raise OSError(f"Failed to write config file {file_path}: {str(e)}")
            except Exception as e:
                raise Exception(f"Failed to dump TOML configuration: {str(e)}")
                
            ConsoleAndLog.info(f"Successfully created SAM config file at: {file_path}")
            return True
        
        except ValueError as e:
            ConsoleAndLog.error(f"Validation error: {str(e)}")
            raise
        except OSError as e:
            ConsoleAndLog.error(f"File system error: {str(e)}")
            raise
        except Exception as e:
            ConsoleAndLog.error(f"Unexpected error creating SAM config: {str(e)}")
            raise

    # -------------------------------------------------------------------------
    # - Template Import
    # -------------------------------------------------------------------------

    def get_stack_template(self) -> str:
        """Download the Original stack template

        Returns:
            str: Original template in YAML format
        """
        try:
            
            response = self.cfn_client.get_template(
                StackName=self.stack_name,
                TemplateStage='Original'
            )
            
            template_body = response['TemplateBody']
            
            # Convert to requested format
            if not isinstance(template_body, str):
                # Convert JSON to YAML
                return yaml.dump(template_body)
            
            return template_body
                
        except self.cfn_client.exceptions.ClientError as e:
            ConsoleAndLog.error(f"Error getting template: {str(e)}")
            return None

    def save_template_file(self, template_content: str) -> bool:
        """Save template content to a file
        
        Args:
            template_content (str): Template content to save.

        Returns:
            bool: Success
        """
        try:
            if template_content:

                try:
                    file_path = self.get_import_template_file_path()
                    with open(file_path, 'w') as f:
                        f.write(template_content)
                except OSError as e:
                    raise OSError(f"OS Error: Failed to write template file {file_path}: {str(e)}")
                except Exception as e:
                    raise Exception(f"Failed to write template file configuration: {str(e)}")
                    
                ConsoleAndLog.info(f"Successfully created template file at: {file_path}")
                return True
            
        except OSError as e:
            ConsoleAndLog.error(f"File system error: {str(e)}")
            raise
        except Exception as e:
            ConsoleAndLog.error(f"Unexpected error creating template: {str(e)}")
            raise
    
    # -------------------------------------------------------------------------
    # - Naming and File Locations
    # -------------------------------------------------------------------------

    def get_import_dir(self) -> Path:
        """Get the import directory path"""
        # Get the script's directory in a cross-platform way
        script_dir = Path(__file__).resolve().parent
        return script_dir.parent / IMPORT_DIR
    
    def get_import_file_name(self) -> str:
        """Get the import file name"""
        return f"samconfig-{self.stack_name}_{self.region}_{Strings.get_date_stamp()}.toml"
    
    def get_import_file_path(self) -> Path:
        """Get the import file path"""
        return self.get_import_dir() / self.get_import_file_name()
    
    def get_import_template_file_path(self) -> Path:
        """Get the import template file path"""
        file = self.get_import_file_name().replace('samconfig-', 'template-').replace('.toml', f'.{YAML_EXT}')
        return self.get_import_dir() / file

# =============================================================================
# ----- Main function ---------------------------------------------------------
# =============================================================================

EPILOG = """
Supports both AWS SSO and IAM credentials.
For SSO users, credentials will be refreshed automatically.
For IAM users, please ensure your credentials are valid using 'aws configure'.

Examples:

    # Import stack acme-blue-test-pipeline
    import.py acme-blue-test-pipeline

    # Import stack acme-blue-test-pipeline from a specific region
    import.py acme-blue-test-pipeline --region us-west-1

    # With different AWS profile
    import.py acme-blue-test-pipeline --region us-west-1 --profile myprofile

    # Import template as well (YAML)
    import.py acme-blue-test-pipeline --template

    
    # Optional flags:
    --template
        Import the template as well (YAML)
    --no-browser
        For an AWS SSO login session, whether or not to set the --no-browser flag. 
"""

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description='Generate SAM config from existing CloudFormation stack',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(EPILOG)
    )

    # Positional arguments
    parser.add_argument('stack_name',
                        help='Name of the existing CloudFormation stack')
    
    # Optional Named Arguments
    parser.add_argument('--profile',
                        required=False,
                        help='AWS profile name')
    parser.add_argument('--region',
                        required=False,
                        default=None,
                        help='AWS region (default: us-east-1)')
    
    # Optional Flags
    parser.add_argument('--template',
                        action='store_true',  # This makes it a flag
                        default=False,        # Default value when flag is not used
                        help='Import template')
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

    importer = ConfigImporter(
        args.stack_name, args.region, 
        args.profile, args.no_browser
    )
    
    try:

        # Fetch stack from account
        ConsoleAndLog.info(f"Fetching information for stack: {args.stack_name}")
        stack_info = importer.get_stack_info()

        if stack_info:
            ConsoleAndLog.info("Stack information fetched successfully")
        else:
            ConsoleAndLog.error("Stack could not be fetched")
            sys.exit(1)

        # Generate SAM config file
        ConsoleAndLog.info("Generating SAM config file...")
        success = importer.create_sam_config()

        if success:
            ConsoleAndLog.info(f"SAM Config import completed successfully")
        else:
            ConsoleAndLog.error("SAM Config import could not complete")
            sys.exit(1)

        # Download template (if --template flag set)
        if args.template:
            ConsoleAndLog.info(f"Fetching template for stack: {args.stack_name}")
            template_content = importer.get_stack_template()
            success = importer.save_template_file(template_content)

            if success:
                ConsoleAndLog.info(f"Template import completed successfully")
            else:
                ConsoleAndLog.error("Template import could not complete")
                sys.exit(1)

    except ValueError as e:
        ConsoleAndLog.error(f"Configuration error: {str(e)}")
        sys.exit(1)
    except OSError as e:
        ConsoleAndLog.error(f"File system error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        ConsoleAndLog.error(f"Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
