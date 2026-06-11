# AI Guidelines for End Users

This document is for end-user installs within an organization and will be named AGENTS.md in the organization's repository when installed.

This repository is a live repository holding utility scripts and configuration files for workloads in AWS. Since this is a shared repository used across a team, care must be taken to not modify critical infrastructure. It uses templates centrally managed by the organization and 63Klabs Atlantis Templates and Scripts Platform for Serverless Application Development and Deployment on AWS.

The purpose of this repository is to provide automated structure, tagging, and processes for maintaining samconfig files for SAM deployments. It overcomes certain limitations of the AWS provided SAM deployment commands, such as pulling templates in from a centrally managed S3 repository, automating of tagging, and ensuring the integrity of the repetitive data stored in samconfig files.

Users utilize utility scripts such as `config.py` and `deploy.py` to configure and deploy serverless applications and infrastructure. They do not apply SAM CLI commands directly.

AI **SHOULD NOT**:

* Modify any file in the `cli` directory
* Modify any file in the `defaults` directory
* Modify any file in the `docs` directory
* Modify any file in the `samconfigs` directory
* Circumvent the SAM Deployment, SAM Configuration, or other processes enforced by the scripts.

AI **MAY**:

* Provide a wrapper to gather user information for the purpose of using the provided scripts
* Utilize `--skeleton` mode on supported scripts to generate a JSON skeleton, and then submit the modified skeleton using `--headless` mode.
* Store any temporary files in a `local-init` directory that is git-ignored
* Review script logic to assist users
* Answer questions from the user on how to use the scripts (Atlantis MCP server may be helpful)

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
