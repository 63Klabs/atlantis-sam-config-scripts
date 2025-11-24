# Local Environment Requirements

The commands and cli used in these tutorials assume a Linux-like environment and some familiarity with Command Line Interface (CLI) via the terminal. On Windows, [Git for Windows](https://gitforwindows.org/) or [Windows Subsystem for Linux (WSL)](https://learn.microsoft.com/en-us/windows/wsl/about) can be used.

## GitHub CLI

> If you will not be using GitHub repositories, or if you already have GitHub CLI installed, you can skip to [AWS CLI and SAM Installation](#aws-cli-and-sam)

If you are using GitHub for your repositories, in order to use the GitHub cli provided you must have GitHub CLI installed.

```bash
# Check GitHub CLI version
gh --version
```

If it wasn't found (or it needs updating), [Install the GitHub CLI](https://cli.github.com).

> Note: GitHub desktop can interfere with Git credentials and cause issues. Unless you REALLY need GitHub desktop it is recommended you just [Install GitHub CLI](https://cli.github.com). You'll be a command line pro by the end of this.

## AWS CLI and SAM

> If you already have AWS CLI and SAM installed, skip to the [Python section](#python-virtual-environment) section.

### AWS CLI Installation:

The AWS Command Line Interface (AWS CLI) is a unified tool to manage your AWS services from the command line. You'll need version 2, which is the current major version.

Installation steps vary by operating system:

- For Linux/macOS: Install via package managers (apt) or the bundled installer
- For Windows: Use the MSI installer
- For Docker: Official Docker images are available

```bash
# Check AWS CLI version
aws --version
```

After installation, configure AWS CLI with your credentials:

```bash
aws configure
```

You'll need to provide:

- AWS Access Key ID
- AWS Secret Access Key
- Default region name (e.g., us-east-1)
- Default output format (json recommended)

### AWS SAM CLI Installation:

AWS SAM (Serverless Application Model) CLI is a tool for building and testing serverless applications. It requires Docker and AWS CLI as prerequisites.

Installation steps:

- For Linux/macOS: Use package managers (pip)
- For Windows: Use the MSI installer

Verify installations with:

```bash
# Check SAM CLI version
sam --version
```

### Detailed AWS CLI and AWS SAM CLI Instructions and Troubleshooting

For detailed installation instructions and troubleshooting, you can refer to the official AWS documentation for AWS CLI and AWS SAM CLI.

Both tools are essential for serverless development as they provide direct access to AWS services.

Make sure you have appropriate AWS credentials and permissions set up to use these tools effectively.

## Python Virtual Environment

It is highly recommended you use a Python Virtual Environment for installing and executing the scripts. This keeps your project dependencies isolated from your system Python installation, preventing potential conflicts.

The project includes a `requirements.txt` file located in the `cli` directory that lists all the Python dependencies needed for the project.

Create and activate a virtual environment in your repository directory:

```bash
# Navigate to your local copy of the repository
cd /path/to/your/repo

# Create the virtual environment
python3 -m venv .ve

# Activate the virtual environment
# On Linux/macOS:
source .ve/bin/activate

# On Windows:
# .ve\Scripts\activate

# Now you can safely install the requirements
pip install -r ./cli/requirements.txt

# You can deactivate the virtual environment (we'll go through activating it before running scripts in the next section)
deactivate
```

### Using the virtual environment

Once you have the virtual environment and packages installed, any time you wish to begin a session to run the scripts, you will need to activate the virtual environment first:

```bash
source .ve/bin/activate
```

Once activated, you'll see `(.ve)` at the beginning of your command prompt. This indicates that you're working within the virtual environment. Any Python packages you install will be isolated to this environment.

To run Python scripts using this environment:

```bash
# Example: Running a script from the cli directory
./cli/deploy.py -h
```

Some important notes:

- The virtual environment (.ve) should be created in your local copy of the repository (it is Git ignored)
- Each time you open a new terminal and want to work on the project, you'll need to activate the virtual environment again for that terminal (terminals are isolated)
- The virtual environment keeps your project dependencies isolated from your system Python
- Make sure to add .ve to your .gitignore file if you haven't already

This is the recommended way to manage Python packages as it prevents conflicts with system packages and allows you to have different versions of packages for different projects.
