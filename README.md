# Atlantis Configuration Repository for Serverless Deployments using AWS SAM

Atlantis provides a central repository structure and CLI to store, manage, and deploy supporting SAM configuration files for serverless infrastructure (such as pipelines, application storage, and CDN) across one or multiple AWS Accounts.

Various scripts allow for easily importing existing stack configurations (`import.py`), creating and seeding application repositories (`create_repo.py`), and creating (`config.py`) and deploying (`deploy.py`) pipelines and other stacks to support your application.

The scripts also assist in managing tags and updating multi-stage deployments all while using standard CloudFormation templates and `samconfig` files. There is no proprietary format or "lock-in" as the scripts just automate and execute standard AWS CLI and AWS SAM CLI commands.

Anyone who has tried to go beyond the development stage using `samconfig` files have come across a few lacking features which Atlantis solves:

1. Atlantis allows you to store and use common templates for stacks such as CodePipeline in S3. Whereas `samconfig` does not natively support referencing templates stored in S3.
2. Atlantis provides a structured way to manage multiple stages (dev, test, prod). Whereas `samconfig` requires all parameters to be copied to each stage environment.
3. Atlantis helps manage stack parameter and tags. Whereas `samconfig` requires you to carefully edit long strings of `"\"Prefix\"=\"acme\" \"ProjectId\"=\"checkers\" \"StageId\"=\"test\" \"S3BucketNameOrgPrefix\"=\"finops\" \"RolePath\"=\"/app-role/\""`
   which is error-prone and difficult to maintain.
4. Atlantis provides default answers and tagging policies used across your organization and projects. Whereas `samconfig` requires manual practices. 

These scripts and templates overcome those limitations and establish a structured approach to managing deployments.

## Basic Usage

You, your team, or organization maintains a central SAM Config repository where ALL your `samconfig` files reside. Developers have access to this repository to create and maintain the infrastructure that supports their application. This separates the occasional infrastructure update (storage, deployment pipeline, DNS/CDN) from rapid application development in the developer's application repository.

A developer begins a project by either creating a repository manually or using the `create_repo.py` script to create, tag, and seed the repository with starter code:

```bash
# Works with GitHub or CodeCommit repositories. Use -h to see full list of options`
./cli/create_repo.py your-repo-name 
```

Next, the developer configures and deploys a pipeline to automate deployments to a test environment:

```bash
# This will walk the developer through setting parameters and tags.
./cli/config.py pipeline acme your-webapp test 
```

Finally, the developer deploys the pipeline infrastructure:

```bash
# This command could be skipped if 
./cli/deploy.py pipeline acme your-webapp test
```

These commands assist in establishing good habits such as prompting the developer to pull changes from the repository before proceeding, pushing changes back to the repository, and walking the developer through configuring their stack with the proper parameters and tags.

## Developer Prerequisites

1. AWS CLI installed
2. AWS SAM CLI installed
3. Git installed
4. Configured AWS profile with valid credentials
5. GitHub CLI installed if you are using GitHub as your repo provider
6. A SAM Config repository set-up by your organization

See [instructions on setting up your local environment](./docs/00-Set-Up-Local-Environment.md) to ensure you are ready to go.

These instructions assume you have an AWS account, AWS CLI, SAM, and profile configuration set up. They also assume a Linux-like environment and CLI. On Windows you can use Git Bash or Windows Subsystem for Linux (WSL). And finally, you should have a familiarity with AWS CLI, SAM, and git.

It also assumes an [account administrator](#account-admins) has already set up a copy of this repo in your organization's AWS account.

## Developer Install and Set Up

The SAM Config repository for use with the Atlantis Platform should already be set up in your organization. Look for a repository with a `sam_config` or similar name.

1. Clone your organizations SAM Config repository
2. Install and execute the scripts [Instructions here](./docs/00-Set-Up-Local-Environment.md#set-up-python)

You're all set!

From now on you can run:

```bash
# Start Python virtual env if that is the method you chose to run Python
source .ve/bin/activate # Activate the Python virtual environment

# Any Atlantis Platform script
./cli/<scriptname>.py
```

## Basic Usage Examples

```bash
# You may need to add --profile <yourprofile> if not using the default AWS CLI profile
# Python CLI will automatically check for current credentials an initiate a login if necessary.
# All scripts provide additional details using the -h option

# Create a CodeCommit repository and seed it from a list of application starters
./cli/create_repo.py your-repo-name

# Create a CodeCommit repository and seed it with a starter from a zip in S3
./cli/create_repo.py your-repo-name --source s3://bucket/path/to/file.zip

# Create a GitHub repository and choose from a list of application starters
./cli/create_repo.py your-repo-name --provider github

# Create a GitHub repository and seed it with code from another GitHub repository (requires GitHub CLI)
./cli/create_repo.py your-repo-name --source https://github.com/someacct/some-repository --provider github

# Create/Manage a pipeline infrastructure stack for your application's test branch
./cli/config.py pipeline acme your-webapp test

# Deploy a pipeline infrastructure stack for your application's test branch
./cli/deploy.py pipeline acme your-webapp test # we do this instead of sam deploy because it can handle templates in S3

# Import an existing stack
./cli/import.py stack-to-import

# Import an existing stack with template
./cli/import.py acme-blue-test-pipeline --template

# Delete a pipeline stack and it's application stack
./cli/delete.py pipeline acme your-webapp test
```

## Tutorials

This README is just a start. Complete tutorials for working with the SAM Configuration scripts, templates, and application starters are found in the [Serverless Deployments using 63K Atlantis Tutorials](https://github.com/63Klabs/atlantis-tutorials) repository.

You should, however, quickly read through the following overview before starting the tutorials.

## Overview

Below are some of the features of this repository and the scripts.

### Creating a New Repository for Your Application

Various serverless application starters are available to seed your repository depending on what type of application you wish to build.

Starting a new application using a CodeCommit or GitHub repository is as simple as:

```bash
./cli/create_repo.py your-webapp --profile yourprofile
```

Where `your-webapp` is the name of your repository and `yourprofile` is the AWS profile to use (it may be `default`).

You will then be prompted to choose an application starter followed by additional information such as tags for your repository. The CLI will then create the repository, place the application starter code in it, and provide you with the clone url.

As with all the scripts, to see additional options, run the script with the `-h` option:

```bash
./cli/create_repo.py -h
```

### Configuring a Pipeline for Automated Deployments

Assuming you used the very basic application starter, your next step will to be set up a pipeline to deploy a test application.

If you chose an application starter beyond the basic, then you may need to set up additional infrastructure as well. Check the application starter documentation.

We will be using git-based deployments, commonly referred to as GitOps. In its simplest form, your repository will have several branches. The `dev` branch for work-in-progress, the `test` branch for deploying your application remotely, and a `main` branch fro deploying your application to production. There may be additional branches for features, staging, beta, etc, but we'll start off with these three main branches first.

As you start to develop new features you will begin with a `dev` branch. You will deploy and test changes locally on your machine. When you have working code you will then merge that code into the `test` branch. The act of merging and pushing your code to the test branch will kick off an automated deployment (you will no longer do `sam deploy` for anything other than local testing in the dev branch).

We need to create a pipeline to monitor changes pushed to the test branch and then perform the deployment process. Luckily we have pipeline templates to use and a simple procedure to create that pipeline.

You can use the configure CLI script to manage your pipeline.

```bash
./cli/config.py pipeline acme your-webservice test --profile yourprofile
```

Where `pipeline` is the type of infrastructure you are creating (more on that later), `acme` is your Prefix, `your-webservice` is your application Project Identifier, `test` is the branch/deployment stage identifier, and profile is your configured profile.

The CLI will then ask you to choose a template, add application deployment information, what repository and branch to monitor, and tags.

### Deploying Pipeline infrastructure

To deploy the pipeline infrastructure stack:

```bash
./cli/deploy.py acme your-webservice test --profile yourprofile
```

This will then utilize the stored configuration and deploy the pipeline stack using `sam deploy` on your behalf. 

After the deployment is complete you should commit your configuration changes back to the central repository.

You'll notice that all the `samconfig` files are stored in the `samconfig` directory. The `deploy.py` CLI provides additional functionality that `sam deploy` doesn't provide (such as S3 urls for template source).

Remember:

- Even though we are utilizing `samconfig` files to store configurations, do not edit them directly. Utilize the `config.py` CLI as it will prevent `toml` format errors and can handle `parameter_overrides`, `tags`, and multiple deployment stages.
- Always commit and push your configuration changes back to the repository so that it remains current.

### Additional Infrastructure

To maintain CloudFormation best practices, and to avoid monolithic architecture, the infrastructure to support your application stack is divided into three additional functional and role-based infrastructure stacks.

1. storage: S3, DynamoDb, etc (developer, operations, data administrator role)
2. pipeline: Code Pipeline, Code Build, Code Deploy (developer or dev/ops role)
3. network: CloudFront, Route53, Certificate Manager (operations role)

Through the use of CLI you can manage these stacks and store their configurations in this repository. They do not change as frequently as your application, are relatively static, do not rely on Git-based pipelines, and may be handled by different roles within your organization.

#### Storage

While your application stack is capable of managing its own S3 buckets and DynamoDb resources, it may not be efficient when the same resource can be shared among various application or deployment stages. Also, if your storage needs to already exist during the build phase of a pipeline you need to manage it externally from your application stack.

Because it is managed externally of your application stack, it does not have a StageId argument.

```bash
# Storage
./cli/config.py storage your-webservice --profile yourprofile
```

#### Network

We separate out domain names (Route53) and Content Delivery Network (CloudFormation) because they do not change as frequently as appplication code does. They are more or less static and are often handled by operations or network administrators and not left in the hands of developers.

```bash
# Network
./cli/config.py network your-webservice test --profile yourprofile
```

### Templates Should Utilize the Principle of Least Privilege

Utilize the Principle of Least Privilege through the use of resource naming and tagging. Construct IAM roles so that they limit actions to related resources. 

For example, the CloudFormation pipeline templates can only create a pipeline for applications under the same Prefix, and each pipeline can only create, delete, and modify resources under the same Prefix, ProjectId, and StageId it was created. (`acme-your-webservice-test-pipeline` cannot modify any resources named or tagged `acme-your-webservice-prod-*` or `acme-jane-webservice-test-*`).

### Import SAM Config Settings or Template from an Existing Stack

If you have an existing stack that you don't have saved as a SAM Config in your repository, you can import the tags, parameter overrides, and other settings including the template.

```bash
# Import an existing stack
./cli/import.py stack-to-import

# Import an existing stack with template
./cli/import.py acme-blue-test-pipeline --template
```

This will import the settings into the `local-imports` directory where you can inspect and then generate a proper configuration file.

Note that by default the `local-imports` directory is ignored by git. Your administrator may update the `.gitignore` file if your organization wishes to include it in the repository.

### Updates

To update the CLI and documentation from the GitHub repository run the `update.py` CLI script.

The following settings may be updated in the `defaults/settings.json` file:

```json
{
	"updates": {
		"source": "https://github.com/63klabs/atlantis-sam-config-scripts",
		"ver": "release:latest",
		"target_dirs": ["docs", "cli"]
	},
}
```

The above settings will pull the latest release from the 63Klabs configuration repository and update both the "docs" and "cli" directories.

For additional update settings, run the following command:

```bash
./cli/update.py -h
```

### Delete

Permissions can be modified to restrict who can delete pipeline stacks and their associated application deployments.

For example, a developer may be able to add a tag to a pipeline stack that marks it for deletion, but is not allowed to delete.

For further protection, stack termination protection may be turned on.

Finally, the delete script has several steps where it prompts for confirmation, including requesting the user provide ARNs for the pipeline and application stack, and retype the Prefix, ProjectId, and StageId.

```bash
./cli/delete.py -h
```

## Account Admins

If you are an account admin needing to set-up and maintain this repository for your organization, see [Account Admin Documentation](./docs/admin/00-Set-Up-AWS-Account-and-Config-Repo.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Security

If you discover any security related issues, please see the [SECURITY](SECURITY) file for details.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

- [Chad Kluck](https://chadkluck.me)
