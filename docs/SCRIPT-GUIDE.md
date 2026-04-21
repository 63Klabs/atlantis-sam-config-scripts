# In-Depth Guide to Serverless Deployments using 63K Atlantis

I bet you hate arriving to an In-Depth guide that is empty.

My apologies, but while the scripts are stable, they are still under development.

Beyond the tutorials, you can use the `-h` for any of the scripts to receive guidance on their use, arguments, options, and flags.

> NOTE: Since the SAM Configuration repository is the SOURCE of CONFIGURATION TRUTH, be sure to `pull` and `push` changes before updating or deploying, and after updating or deploying. Ensure your changes are properly recorded and saved! (Eventually the scripts will aide in this to prevent mishaps from forgetfulness--happens to the best of us!)

Let's start off with an overview of the scripts.

## create_repo.py

Create a GitHub or CodeCommit repository and seed it from an application starter, GitHub repo, or a ZIP stored S3 using the create_repo.py script

For usage info:

```bash
./cli/create_repo.py -h
```

## config.py

Create and maintain a CloudFormation stack utilizing stack options stored in a samconfig file and a central template repository managed by your organization (or 63Klabs for training and getting started).

The config script will walk you through selecting a template and filling out stack parameters, options, and tags.

For usage info:

```bash
./cli/config.py -h
```

## deploy.py

After configuring a stack, you must deploy it. Although the scripts maintain a samconfig file, it utilizes a template repository hosted in S3, which, oddly, samconfig does not support even though CloudFormation templates can easily import Lambda code and nested stacks from S3.

The deploy script runs the `sam deploy` command after obtaining the template from S3 and providing it to the command as a temporary, local file.

For usage info:

```bash
./cli/deploy.py -h
```

## import.py

You probably have some stacks that were deployed prior to using the CLI scripts to manage them.

Import current stack configurations to a samconfig file.

You can also import the template that was used (if you need a copy).

From there you can tweak the samconfig file, upload the template to a central location (or apply a different one) and after formatting and saving to the proper location for the scripts to use, utilize the CLI scrips.

For usage info:

```bash
./cli/import.py -h
```

## update.py

While stable, the scripts are still under development. Various enhancements and fixes will be released.

The update script is essential in making sure you have the most current scripts.

> Note: Refer to, or create, your organization's policy reguarding WHO should be performing the updates and WHEN the updates should be performed.

The script is very friendly as it will kindly remind, and perform a pull of the configuration repository before proceeding. It will then push all changes back after completion. This ensures that the push/pull step is not forgotten and all subsequent pulls by developers have the new files!

For usage info:

```bash
./cli/update.py -h
```

> NOTE: While the update script has pull/push built in, the other scripts do not yet have this implemented. It is on the list of future enhancements!

## report_pipelines_managed_arns_param.py

Report the ARNs of the pipeline stacks deployed in CloudFormation, which can be useful for debugging or auditing purposes.

This particular script will report back which `*-pipeline` stacks are currently using additional Managed ARNs beside what is already included in the pipeline template.

Pipeline stacks create specific, scoped down CloudFormation and CodeDeploy service roles. However, you may need to grant these roles additional permissions to access specific resources. A managed policy can be added to the pipeline to grant these permissions.

> However: Adding additional managed policies to these service roles should be carefully considered.

While this is useful in preventing many custom pipelines from being created (and therefore difficult to control and manage) it can pose security risks if the policies being added are not carefully scoped, overly permissive, or used as "duct tape" fixes just to overcome permissions errors. The existing Service Roles are there for a reason.

When might a managed service role be useful? When a micro-service needs to be invoked by another micro-service. For example, when a Lambda Authorizer needs to be invoked by another application stack's API Gateway. The Lambda Authorizer stack can publish a managed policy that allows adding and removing invocation permissions to itself by other applications. (It can even further restrict that the gateway must have certain tags or naming conventions in place as well to scope it down).

To perform a periodic audit of what pipeline stacks are currently using extra Managed policies run the script.

For usage info:

```bash
./cli/report_pipelines_managed_arns_param.py -h
```

1. Scans all CloudFormation stacks in the account/region
2. Filters for stacks with names ending in -pipeline
3. Checks each pipeline stack for the two specific parameters:
4. CloudFormationSvcRoleIncludeManagedPolicyArns
5. CodeBuildSvcRoleIncludeManagedPolicyArns
6. Reports only stacks where at least one of these parameters is not empty

## delete.py

Deleting applications and their pipelines require a specific order to be followed. The application stack must be deleted first, followed by the pipeline, SSM parameters that were created during the build process, and finally clean-up of the SAM configuration file.

Lucky, the `delete.py` script takes care of all of this.

There are 2 manual steps that need to take place prior to running the delete script. Some organizations may restrict who can perform these steps to ensure proper checks and balances.

1. Manually add a tag to the pipeline stack with the key `DeleteOnOrAfter` and value of a date in `YYYY-MM-DD` format. (Add `Z` to end for UTC. Example `2026-07-09Z`). This can be done using the AWS CLI or AWS Web Console. (Note: Adding the tag outside of the config.py script may get over written if another deployment occurs before the stack is deleted (date set further into the future). For long term dates set the date tag using the config.py and then deploy.py scripts.)
	- `aws resourcegroupstaggingapi tag-resources --resource-arn-list "arn:aws:cloudformation:region:account:stack/stack-name/stack-id" --tags DeleteOnOrAfter=YYYY-MM-DD --profile your-profile`
2. Disable termination protection on both the application and pipeline stack:
	- `aws cloudformation update-termination-protection --stack-name STACK_NAME --no-enable-termination-protection --profile your-profile`

Once these steps are completed, you can run the delete script.

For usage info: 

```bash
./cli/delete.py -h
```

The delete.py script has the following features to aid in clean-up:

- Pipeline destruction workflow:
	1. Prompts for git pull
	2. Validates pipeline and application stack ARNs
	3. Checks DeleteOnOrAfter tag with date validation (supports both local and UTC dates) and ensures termination protection is disabled.
	4. Final confirmation by entering prefix, project_id, and stage_id
	5. Deletes application stack first, then pipeline stack
	6. Deletes associated SSM parameters
	7. Updates/deletes samconfig entries
	8. Performs git commit and push
- Safety features:
	- Multiple validation steps before deletion
	- Proper error handling and logging
	- Stack deletion waiter to ensure completion
- Batch processing for SSM parameter deletion
- Future extensibility: Framework in place for storage, network, and iam types (currently shows not implemented message)
