#!/usr/bin/env python3

VERSION = "v0.0.1/2025-08-08"
# Created by Chad Kluck with AI assistance from Amazon Q Developer

# Usage Information:
# report_pipelines_managed_arns_param.py -h

# Full Documentation:
# https://github.com/63klabs/atlantis-sam-config-scripts/

import sys
import argparse
import traceback
from typing import Optional, List, Dict
from botocore.exceptions import ClientError

from lib.aws_session import AWSSessionManager, TokenRetrievalError
from lib.logger import ScriptLogger, ConsoleAndLog, Log
from lib.tools import Colorize

if sys.version_info[0] < 3:
    sys.stderr.write("Error: Python 3 is required\n")
    sys.exit(1)

# Initialize logger for this script
ScriptLogger.setup('report_pipelines_managed_arns_param')

class PipelineReporter:
    def __init__(self, profile: Optional[str] = None, region: Optional[str] = None, no_browser: Optional[bool] = False):
        self.profile = profile
        self.region = region
        
        # Set up AWS session and clients
        self.aws_session = AWSSessionManager(profile, region, no_browser)
        self.cfn_client = self.aws_session.get_client('cloudformation', region)

    def get_pipeline_stacks(self) -> List[Dict]:
        """Get all CloudFormation stacks with names ending in '-pipeline'"""
        pipeline_stacks = []
        
        try:
            paginator = self.cfn_client.get_paginator('describe_stacks')
            
            for page in paginator.paginate():
                for stack in page['Stacks']:
                    if stack['StackName'].endswith('-pipeline'):
                        pipeline_stacks.append({
                            'StackName': stack['StackName'],
                            'StackStatus': stack['StackStatus'],
                            'Parameters': {param['ParameterKey']: param['ParameterValue'] 
                                        for param in stack.get('Parameters', [])}
                        })
                        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            Log.error(f"Error listing stacks: {error_code} - {error_message}")
            
            if error_code == 'UnauthorizedException':
                ConsoleAndLog.error("Authentication Error")
                ConsoleAndLog.error("Your session token is invalid or has expired")
                ConsoleAndLog.error("Please authenticate again with AWS and ensure you have the correct permissions")
                ConsoleAndLog.error("You may need to run 'aws sso login' if using AWS SSO")
            else:
                ConsoleAndLog.error(f"Error listing stacks: {error_code} - {error_message}")
                ConsoleAndLog.error(f"Ensure you are currently logged in and using the correct profile ({self.profile})")
            
            sys.exit(1)
        except Exception as e:
            Log.error(f"Unexpected error listing stacks: {e}")
            ConsoleAndLog.error(f"Unexpected error listing stacks: {str(e)}")
            sys.exit(1)
            
        return pipeline_stacks

    def filter_stacks_with_managed_arns(self, stacks: List[Dict]) -> List[Dict]:
        """Filter stacks that have non-empty CloudFormationSvcRoleIncludeManagedPolicyArns or CodeBuildSvcRoleIncludeManagedPolicyArns parameters"""
        filtered_stacks = []
        
        for stack in stacks:
            parameters = stack['Parameters']
            cf_managed_arns = parameters.get('CloudFormationSvcRoleIncludeManagedPolicyArns', '')
            cb_managed_arns = parameters.get('CodeBuildSvcRoleIncludeManagedPolicyArns', '')
            
            if cf_managed_arns != '' or cb_managed_arns != '':
                stack['CloudFormationSvcRoleIncludeManagedPolicyArns'] = cf_managed_arns
                stack['CodeBuildSvcRoleIncludeManagedPolicyArns'] = cb_managed_arns
                filtered_stacks.append(stack)
                
        return filtered_stacks

    def generate_report(self) -> None:
        """Generate and display the report"""
        print()
        print(Colorize.divider("="))
        print(Colorize.output_bold(f"Pipeline Managed ARNs Report ({VERSION})"))
        print(Colorize.divider("="))
        print()
        
        ConsoleAndLog.info("Scanning for pipeline stacks...")
        
        # Get all pipeline stacks
        pipeline_stacks = self.get_pipeline_stacks()
        
        if not pipeline_stacks:
            print(Colorize.warning("No pipeline stacks found"))
            return
            
        ConsoleAndLog.info(f"Found {len(pipeline_stacks)} pipeline stack(s)")
        
        # Filter stacks with managed ARNs
        filtered_stacks = self.filter_stacks_with_managed_arns(pipeline_stacks)
        
        if not filtered_stacks:
            print(Colorize.success("No pipeline stacks found with managed policy ARNs configured"))
            return
            
        print(Colorize.output_bold(f"Found {len(filtered_stacks)} pipeline stack(s) with managed policy ARNs:"))
        print()
        
        for stack in filtered_stacks:
            print(Colorize.divider("-"))
            print(Colorize.output_bold(f"Stack: {stack['StackName']}"))
            print(Colorize.output_with_value("Status:", stack['StackStatus']))
            
            if stack['CloudFormationSvcRoleIncludeManagedPolicyArns']:
                print(Colorize.output_with_value("CloudFormation Managed ARNs:", 
                                                stack['CloudFormationSvcRoleIncludeManagedPolicyArns']))
            
            if stack['CodeBuildSvcRoleIncludeManagedPolicyArns']:
                print(Colorize.output_with_value("CodeBuild Managed ARNs:", 
                                                stack['CodeBuildSvcRoleIncludeManagedPolicyArns']))
            print()
        
        print(Colorize.divider("="))
        print()

# =============================================================================
# ----- Main function ---------------------------------------------------------
# =============================================================================

EPILOG = """
Supports both AWS SSO and IAM credentials.
For SSO users, credentials will be refreshed automatically.
For IAM users, please ensure your credentials are valid using 'aws configure'.

Examples:

    # Basic report
    report_pipelines_managed_arns_param.py
    
    # Use specific AWS profile
    report_pipelines_managed_arns_param.py --profile myprofile
    
    # Use specific region
    report_pipelines_managed_arns_param.py --region us-west-2

"""

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Report pipeline stacks with managed policy ARNs configured',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG
    )
    
    # Optional Named Arguments
    parser.add_argument('--profile',
                        required=False,
                        default=None,
                        help='AWS credential profile name')
    parser.add_argument('--region',
                        required=False,
                        default=None,
                        help='AWS region (e.g. us-east-1)')
    
    # Optional Flags
    parser.add_argument('--no-browser',
                        action='store_true',
                        default=False,
                        help='For an AWS SSO login session, whether or not to set the --no-browser flag.')
    
    return parser.parse_args()

def main():
    try:
        args = parse_args()
        Log.info(f"{sys.argv}")
        Log.info(f"Version: {VERSION}")
        
        try:
            reporter = PipelineReporter(args.profile, args.region, args.no_browser)
            reporter.generate_report()
            
        except TokenRetrievalError as e:
            ConsoleAndLog.error(f"AWS authentication error: {str(e)}")
            sys.exit(1)
        except Exception as e:
            ConsoleAndLog.error(f"Error initializing reporter: {str(e)}")
            sys.exit(1)
            
    except Exception as e:
        ConsoleAndLog.error(f"Unexpected error: {str(e)}")
        ConsoleAndLog.error(f"Error occurred at:\n{traceback.format_exc()}")
        sys.exit(1)

if __name__ == '__main__':
    main()