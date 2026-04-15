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
