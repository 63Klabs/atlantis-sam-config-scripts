# Local Environment Requirements

The commands and cli used in these tutorials assume a Linux-like environment and some familiarity with Command Line Interface (CLI) via the terminal. On Windows, [Git for Windows](https://gitforwindows.org/) or [Windows Subsystem for Linux (WSL)](https://learn.microsoft.com/en-us/windows/wsl/about) can be used.

To keep instructions simple we will be using:

- Linux commands
- Recommended set-up by 63Klabs/Chad Kluck
- Python (we'll use the `python3` command, but use `python` if that's your system)
- Virtual Python environment using `venv` named `.ve` just to keep it brief and out of commits

If you are familiar with other tools (`uv`) and can easily translate that is up to you. Follow your organization's requirements and note that using methods other than those described here may not be supported by the Atlantis Platform.

## Prerequisites

- Python >3.14
- AWS CLI and AWS SAM
- GitHub CLI (if using GitHub repos)

## Python Virtual Environment

It is highly recommended you use a Python Virtual Environment for installing and executing the scripts. This keeps your project dependencies isolated from your system Python installation, preventing potential conflicts.

The project includes a `requirements.txt` file located in the `cli` directory that lists all the Python dependencies needed for the project.

Create and activate a virtual environment in your repository directory:

```bash
# Clone your organization's SAM Config repository
git clone your-org-repo

# Navigate to your local copy of the repository
cd /path/to/cloned/repo

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

Once activated, you'll see `(.ve)` at the beginning of your command prompt. This indicates that you're working within the virtual environment. Any Python packages you install while in `(.ve)` will be isolated to this environment.

To run Python scripts using this environment:

```bash
# Example: Running a script from the cli directory
./cli/config.py -h
```

Some important notes:

- The virtual environment `(.ve)` should be created in your local copy of the repository (it is Git ignored)
- Each time you open a new terminal and want to work on the project, you'll need to activate the virtual environment again for that terminal (terminals are isolated)
- The virtual environment keeps your project dependencies isolated from your system Python
- Make sure to add .ve to your .gitignore file if you haven't already

This is the recommended way to manage Python packages as it prevents conflicts with system packages and allows you to have different versions of packages for different projects.
