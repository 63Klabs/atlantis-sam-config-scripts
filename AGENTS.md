# AI Guidelines for Atlantis SAM Config Scripts Development

This document is for feature development of Atlantis SAM Config Scripts and will not be provided to End Users.

This repository is a **TEMPLATE** holding utility scripts and configuration files for workloads in AWS. When installed at an organization, it will provide easy managment of critical infrastructure using samconfig files. It uses templates centrally managed by the 63Klabs Atlantis Templates and Scripts Platform for Serverless Application Development and Deployment on AWS. Organizations may extend the template library by supplying their own central library of templates within a custom namespace.

The purpose of these utilities is to provide automated structure, tagging, and processes for maintaining samconfig files for SAM deployments. It overcomes certain limitations of the AWS provided SAM deployment commands, such as pulling templates in from a centrally managed S3 repository, automating of tagging, and ensuring the integrity of the repetitive data stored in samconfig files.

Users utilize utility scripts such as `config.py` and `deploy.py` to configure and deploy serverless applications and infrastructure. They do not apply SAM CLI commands directly.

## Executing Scripts

Each script has a `-h` option that will display helpful information on using the script including proper parameters and settings.

A Python virtual environment local to this project directory named `.ve` is used to install the necessary Python libraries and execute the Python scripts. If the user does not have a Python virtual environment, one must be created first.

```bash
# Create the virtual environment
python3 -m venv .ve

# Activate the virtual environment
# On Linux/macOS:
source .ve/bin/activate

# On Windows:
# .ve\Scripts\activate

# Now you can safely install the requirements
pip install -r ./cli/requirements.txt
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

For guidance on the templates, starter code, and more relating to the Atlantis Platform, the Atlantis MCP server will be of use if the user has it installed.

## For Development

### Script Requirements

Scripts must:

- Be ran under the `.ve` environment
- Include a `-h` flag
- Include the `--profile` option
- Facilitate the login process if the user is not logged in (utilize cli/lib/aws_session.py)
- Prompt the user to do a commit and push changes after running a script that updates a samconfig
- Follow similar behavior in logging, prompting, color use, formatting, etc of existing scripts to make the user experience connected

### User Files and Updates

This repository, for development purposes, includes additional files that will not be included in the downloaded copy.

Directories and files included for the user are:

- cli/*
- defaults/*
- docs/*
- AGENTS-FOR-END-USE.md (renamed to AGENTS.md and replacing the AGENTS for development when packaging)
- README.md

The AGENTS-FOR-END-USE.md is for the end user agents, and provides important guardrails to prevent modification of the utility functions and samconfig files. It is not applicable during the development process. Also, the current AGENTS.md file is not applicable for the end user. That is why these files are swapped out during release packaging and end-user downloads.

Updates only affect the cli and docs directory. Care must be taken to ensure new features are added only to these directories otherwise users will not receive the update. The user runs the script update.py to download the new files from their selected source.
