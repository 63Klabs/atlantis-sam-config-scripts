#!/usr/bin/env python3

VERSION = "v0.2.0/2026-08-06"
# Developed by Chad Kluck with AI assistance from Amazon Q Developer

"""
Tools specific to Atlantis cli
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
import sys

import click

from .logger import Log, ConsoleAndLog
from .tools import Colorize, Strings

# -------------------------------------------------------------------------
# - Tag Utilities
# -------------------------------------------------------------------------


class TagUtils:

    def is_valid_aws_tag(key: str, value: str) -> tuple[bool, str]:
        """Validate AWS tag key and value according to AWS requirements
        
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        # Key validation
        if len(key) > 128:
            return False, "Tag key cannot be longer than 128 characters"
        
        if not key.strip():
            return False, "Tag key cannot be empty"
        
        if key.lower().startswith("aws:"):
            return False, "Tag keys cannot start with 'aws:'"
        
        if key.startswith(" ") or key.endswith(" "):
            return False, "Tag keys cannot start or end with spaces"
            
        if value.startswith(" ") or value.endswith(" "):
            return False, "Tag values cannot start or end with spaces"
        
        if key.startswith('Atlantis') or key.startswith('atlantis:'):
            return False, "Tag key cannot start with 'Atlantis' or 'atlantis:'"
        
        if TagUtils.is_atlantis_reserved_tag(key):
            return False, f"Tag key '{key}' is a reserved Atlantis tag"
        
        # AWS allows letters, numbers, spaces, and the following special characters: + - = . _ : / @
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 +-=._:/@")
        invalid_chars = set(key) - allowed_chars
        if invalid_chars:
            return False, f"Tag key contains invalid characters: {', '.join(invalid_chars)}"
        
        # Value validation
        if len(value) > 256:
            return False, "Tag value cannot be longer than 256 characters"
        if not value.strip():
            return False, "Tag value cannot be empty"
        
        # AWS allows letters, numbers, spaces, and the following special characters: + - = . _ : / @
        invalid_chars = set(value) - allowed_chars
        if invalid_chars:
            return False, f"Tag value contains invalid characters: {', '.join(invalid_chars)}"
        
        return True, ""

    @staticmethod
    def is_atlantis_reserved_tag(key: str) -> bool:
        """Check if the tag key is not a reserved Atlantis tag

        Args:
            key (str): Tag key

        Returns:
            bool: True if the tag key is not a reserved Atlantis tag
        """
        return (key.startswith('Atlantis') or key.startswith('atlantis:') or key in ['Provisioner', 'DeployedUsing', 'Name', 'Stage', 'Environment', 'AlarmNotificationEmail', 'Repository', 'RepositoryBranch', 'CodeCommitRepository', 'CodeCommitBranch'])

    @staticmethod
    def prompt_for_tags(tags: Dict) -> Dict:
        """Prompt the user to enter tags for the repository

        Args:
            tags (Dict): Default tags for the repository

        Returns:
            Dict: Tags for the repository
        """

        user_tags = {}

        try:

            # If there are tags then prompt the user to enter values for each tag
            if tags:
                print()
                click.echo(Colorize.divider())
                click.echo(Colorize.output_bold("Enter values for the following tags:"))
                print()

                # First, iterate through the default tags and prompt the user to enter values
                # Some may already have default values. Allow the user to just hit enter to accept default
                for key, value in tags.items():
                    # skip any that begin with 'Atlantis' or 'atlantis'
                    if TagUtils.is_atlantis_reserved_tag(key):
                        continue

                    if value is None:
                        value = ''
                    
                    while True:
                        user_input = Colorize.prompt(f"{key}", value, str)
                        is_valid, error_msg = TagUtils.is_valid_aws_tag(key, user_input)
                        if is_valid:
                            user_tags[key] = user_input
                            break
                        click.echo(Colorize.error(f"Error: {error_msg}"))


            # Now, ask the user to add any additional tags using key=value. 
            # After the user enters a key=value pair, place it in the tags Dict and prompt again
            # If the user enters an empty string, stop prompting and return the tags

            print()
            click.echo(Colorize.divider())
            click.echo(Colorize.output_bold("Enter additional tags in key=value format. Hit enter to finish:"))
            print()

            while True:
                tag_input = Colorize.prompt("New tag", "", str)
                if tag_input == "":
                    break
                
                # Split and validate the input
                if '=' not in tag_input:
                    click.echo(Colorize.error("Invalid tag format. Please use key=value format."))
                    continue
                    
                parts = tag_input.split('=', 1)
                key, value = parts[0].strip(), parts[1].strip()
                
                # Validate both key and value
                is_valid_key, key_error = TagUtils.is_valid_aws_tag(key, "dummy")  # Validate key format
                is_valid_value, value_error = TagUtils.is_valid_aws_tag("dummy", value)  # Validate value format
                
                if not is_valid_key:
                    click.echo(Colorize.error(f"Invalid tag key: {key_error}"))
                    continue
                    
                if not is_valid_value:
                    click.echo(Colorize.error(f"Invalid tag value: {value_error}"))
                    continue
                
                # If we get here, both key and value are valid
                user_tags[key] = value

        except Exception as e:
            Log.error(f"Error prompting for tags: {e}")
            raise

        return user_tags
    
    @staticmethod
    def tags_as_list(tags: Dict) -> List[Dict]:
        """Convert tags from dictionary to list of dictionaries

        Args:
            tags (Dict): Tags for the repository

        Returns:
            List[Dict]: List of tags for the repository
        """
        tag_list = []
        for key, value in tags.items():
            tag_list.append({"Key": key, "Value": value})
        return tag_list

    @staticmethod
    def tags_as_dict(tags: List[Dict]) -> Dict:
        """Convert tags from list of dictionaries to dictionary

        Args:
            tags (List[Dict]): List of tags for the repository

        Returns:
            Dict: Tags for the repository
        """
        tag_dict = {}
        for tag in tags:
            tag_dict[tag['Key']] = tag['Value']

        return tag_dict
    
    @staticmethod
    def get_default_tags(settings: Dict, defaults: Dict) -> Dict:
        """Get the default tags for the repository

        Returns:
            Dict: Default tags for the repository
        """
        tags = {}

        try:

            # Get the default tag keys from self.settings.tag_keys
            tag_keys = settings.get('tag_keys', [])
            # place each key as an entry in tags where it's value is None
            for key in tag_keys:
                tags[key] = None

            # Get the default tags from self.defaults.tags and merge with tags. Overwrite existing keys in tags with the value from default. Add in any new tags.
            default_tags = defaults.get('tags', {})
            for item in default_tags:
                tags[item['Key']] = item['Value']

        except Exception as e:
            ConsoleAndLog.error(f"Error getting default tags: {e}")
            raise

        return tags


# -------------------------------------------------------------------------
# - Utilities
# -------------------------------------------------------------------------

class Utils:

    @staticmethod
    def make_selection_from_list(options: List[str],
                                allow_none: Optional[bool] = False,
                                *, 
                                heading_text="Select from options",
                                prompt_text="Enter a selection number") -> str:
        """
        Presents a numbered list of options to the user and prompts for a selection.

        Args:
            options (List[str]): List of options to present to the user
            allow_none (Optional[bool]): If True, allows user to make no selection. Defaults to False
            heading_text (str): Text to display as heading above the options. Defaults to "Select from options"
            prompt_text (str): Text to display when prompting for input. Defaults to "Enter a selection number"

        Returns:
            str: The selected option from the list. If allow_none is True and no selection is made, returns empty string

        Raises:
            ValueError: If the user enters an invalid selection number
            
        Example:
            >>> options = ["dev", "prod", "stage"]
            >>> selected = make_selection_from_list(
            ...     options,
            ...     allow_none=True,
            ...     heading_text="Select environment",
            ...     prompt_text="Choose environment number"
            ... )
            Select environment
            1. dev
            2. prod
            3. stage
            Choose environment number: 1
            >>> print(selected)
            'dev'
        """
        print(options)
        # Display numbered list
        click.echo(Colorize.question(f"{heading_text}:"))
        if allow_none: click.echo(Colorize.option("0. New"))
        for idx, option in enumerate(options, 1):
            line = f"{idx}. {option}"
            click.echo(Colorize.option(line))
        
        print()

        while True:
            try:
                default = ''

                choice = Colorize.prompt(prompt_text, default, str)
                # Check if input is a number
                sel_idx = int(choice) - 1

                min = -1 if allow_none else 0
                
                # Validate the index is within range
                if min <= sel_idx < len(options):

                    selected = None

                    if(sel_idx >= 0):
                        selected = options[sel_idx]
                                                
                    return selected
                else:
                    click.echo(Colorize.error(f"Please enter a number between {min} and {len(options)}"))
            except ValueError:
                click.echo(Colorize.error("Please enter a valid number"))
            except KeyboardInterrupt:
                click.echo(Colorize.info("Selection cancelled"))
                sys.exit(1)

# -------------------------------------------------------------------------
# - File Name List Utilities
# -------------------------------------------------------------------------

class FileNameListUtils:

    @staticmethod
    def select_from_file_list(file_list: List[str], 
                                allow_none: Optional[bool] = False, 
                              *, 
                                heading_text="Available files",
                                prompt_text="Enter file number") -> str:
        """List available files and prompt the user to choose one.

        Args:
            file_list (List[str]): List of files to use
            allow_none (Optional[bool]): List 0. None as an option
            
        Returns:
            str: Selected file
        """

        if not file_list:
            Log.error("No files found")
            click.echo(Colorize.error("No files found"))
            if not allow_none:
                sys.exit(1)
        
        # Sort file_list for consistent ordering
        file_list.sort()

        # We want to put the filename first and pad out to make it easy to view
        selection_list = FileNameListUtils.extract_filenames_from_paths(file_list)
        max_filename = Strings.find_longest_string_length_in_column(selection_list, 0)
        max_filepath = Strings.find_longest_string_length_in_column(selection_list, 1)
        terminal_width = Strings.get_terminal_width(900)
        two_line = max_filename + max_filepath + 7 > terminal_width
        
        # Display numbered list
        click.echo(Colorize.question(f"{heading_text}:"))
        if (allow_none): click.echo(Colorize.option("0. None"))
        for idx, line_item in enumerate(selection_list, 1):
            line = ""
            if two_line:
                line = f"{idx}. {line_item[0]}\n    {line_item[1]}"
            else:
                line = f"{idx}. {Strings.pad_string(line_item[0], max_filename)} | {line_item[1]}"
            click.echo(Colorize.option(line))
        
        print()

        while True:
            try:
                default = ''

                choice = Colorize.prompt(prompt_text, default, str)
                # Check if input is a number
                sel_idx = int(choice) - 1

                min = -1 if allow_none else 0
                
                # Validate the index is within range
                if min <= sel_idx < len(selection_list):

                    selected = None

                    if(sel_idx >= 0):
                        selected = selection_list[sel_idx][1]
                                                
                    return selected
                else:
                    click.echo(Colorize.error(f"Please enter a number between {min} and {len(selection_list)}"))
            except ValueError:
                click.echo(Colorize.error("Please enter a valid number"))
            except KeyboardInterrupt:
                click.echo(Colorize.info("File selection cancelled"))
                sys.exit(1)

        
    @staticmethod
    def extract_filenames_from_paths(paths: List[str]) -> List[List[str]]:
        """Takes a list of S3 URLs and returns a list of [filename, full_path] pairs.

        Args:
            paths (List[str]): List of S3 URLs (e.g., ['s3://bucket/path/file.zip', ...])

        Returns:
            List[List[str]]: List of [filename, full_path] pairs maintaining original order

        Example:
            Input: ['s3://bucket/path/file.zip', 's3://bucket/other/doc.pdf']
            Output: [['file.zip', 's3://bucket/path/file.zip'], 
                    ['doc.pdf', 's3://bucket/other/doc.pdf']]
        """
        try:
            result = []
            for path in paths:
                # Extract the filename from the full path
                filename = path.split('/')[-1]
                # Create pair and append to result
                result.append([filename, path])
            return result
        except Exception as e:
            Log.error(f"Error processing S3 URLs: {str(e)}")
            raise

# -------------------------------------------------------------------------
# - Configuration Loader
# -------------------------------------------------------------------------

class DefaultsLoader:
    def __init__(self, settings_dir: Path, prefix: str = "", project_id: str = "", infra_type: str = ""):
        """Initialize the DefaultsLoader
        
        Args:
            settings_dir (Path): Base directory for configuration files
            prefix (str, optional): Configuration prefix. Defaults to "".
            project_id (str, optional): Project identifier. Defaults to "".
            infra_type (str, optional): Infrastructure type. Defaults to "".
        """
        self.settings_dir = settings_dir
        self.prefix = prefix
        self.project_id = project_id
        self.infra_type = infra_type

    def get_settings_dir(self) -> Path:
        """Get the settings directory path
        
        Returns:
            Path: Path to settings directory
        """
        return self.settings_dir

    def _deep_update(self, base_dict: Dict, update_dict: Dict) -> None:
        """Recursively update a dictionary
        
        Args:
            base_dict (Dict): Base dictionary to update
            update_dict (Dict): Dictionary with updates to apply
        """
        for key, value in update_dict.items():
            if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
                self._deep_update(base_dict[key], value)
            elif isinstance(value, list) and key in base_dict and isinstance(base_dict[key], list):
                base_dict[key] = base_dict[key] + value
            else:
                base_dict[key] = value

    def load_settings(self) -> Dict:
        """Load settings.json
        
        Returns:
            Dict: Settings dictionary from the JSON file or empty dict if file doesn't exist
            
        Raises:
            JSONDecodeError: If the settings file contains invalid JSON
            PermissionError: If the settings file cannot be accessed due to permissions
        """
        settings_file = self.get_settings_dir() / "settings.json"
        
        try:
            if settings_file.exists():
                with open(settings_file) as f:
                    try:
                        settings = json.load(f)
                        if not isinstance(settings, dict):
                            raise ValueError("Settings must be a JSON object")
                        return settings
                    except json.JSONDecodeError as e:
                        raise json.JSONDecodeError(
                            f"Invalid JSON in settings file: {str(e)}", 
                            e.doc, 
                            e.pos
                        )
            else:
                return {}
                
        except PermissionError:
            raise PermissionError(f"Unable to access settings file: {settings_file}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error loading settings: {str(e)}")

    def load_defaults(self) -> Dict:
        """Load and merge configuration files in sequence
        
        Order:
        1. defaults.json
        2. {prefix}-defaults.json
        3. {prefix}-{project_id}-defaults.json
        4. {infra_type}/defaults.json
        5. {infra_type}/{prefix}-defaults.json
        6. {infra_type}/{prefix}-{project_id}-defaults.json
        
        Returns:
            Dict: Merged configuration dictionary
        """
        defaults = {}
        
        # Define the sequence of potential config files
        config_files = [
            self.get_settings_dir() / "defaults.json",
            self.get_settings_dir() / f"{self.prefix}-defaults.json"
        ]
        
        # Add project_id specific files only if project_id exists
        if self.project_id:
            config_files.extend([
                self.get_settings_dir() / f"{self.prefix}-{self.project_id}-defaults.json",
            ])
        
        # Add infra_type specific files
        config_files.append(self.get_settings_dir() / f"{self.infra_type}" / "defaults.json")
        config_files.append(self.get_settings_dir() / f"{self.infra_type}" / f"{self.prefix}-defaults.json")
        
        # Add project_id specific files in infra_type directory
        if self.project_id:
            config_files.append(
                self.get_settings_dir() / f"{self.infra_type}" / f"{self.prefix}-{self.project_id}-defaults.json"
            )
        
        # Load each config file in sequence if it exists
        for config_file in config_files:
            try:
                if config_file.exists():
                    with open(config_file) as f:
                        # Deep update defaults with new values
                        new_config = json.load(f)
                        self._deep_update(defaults, new_config)
                        Log.info(f"Loaded config from '{config_file}'")
            except json.JSONDecodeError as e:
                Log.error(f"Error parsing JSON from {config_file}: {e}")
            except Exception as e:
                Log.error(f"Error loading config file {config_file}: {e}")
        
        return defaults


# -------------------------------------------------------------------------
# - Samconfig Reader
# -------------------------------------------------------------------------


class SamconfigReader:
    """Read and parse SAM configuration (samconfig.toml) files.

    Provides low-level helpers for loading raw TOML deploy parameters and
    parsing the ``parameter_overrides`` string format used by SAM CLI.
    This class is intentionally dependency-free (no AWS clients, no UI)
    so it can be used from any script without side effects.

    The ``parameter_overrides`` string in samconfig files is written by
    ``config.py`` in the SAM CLI quoted format::

        "Key1"="Value1" "Key2"="Value2"

    Plain (unquoted) ``Key=Value`` pairs are also supported.
    ``shlex.split`` handles both formats correctly: it strips outer quotes
    during shell-style tokenisation, which is identical to the approach
    used in ``config.py``.

    Example:
        >>> reader = SamconfigReader(Path('samconfigs/acme/myapp/samconfig-acme-myapp-pipeline.toml'))
        >>> overrides = reader.read_parameter_overrides('test')
        >>> overrides['S3ModuleLocation']
        '63klabz'

        >>> params = reader.read_deploy_params('test')
        >>> params['s3_bucket']
        'cf-artifacts-123456789012-us-east-1'
    """

    def __init__(self, config_file: Path) -> None:
        """Initialise the reader with a path to a samconfig TOML file.

        Args:
            config_file: Absolute or relative path to the samconfig TOML file.
        """
        self._config_file = config_file

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def read_parameter_overrides(self, stage_id: str) -> Dict[str, str]:
        """Return the merged parameter_overrides for *stage_id*.

        Reads ``parameter_overrides`` from ``default.deploy.parameters`` and
        from ``{stage_id}.deploy.parameters``, merges them (stage wins), then
        parses the combined string into a ``{name: value}`` dict.

        Args:
            stage_id: SAM stage name (e.g. ``'test'``, ``'prod'``,
                ``'default'``).

        Returns:
            Dict mapping parameter names to their string values. Returns an
            empty dict when ``parameter_overrides`` is absent or empty.

        Raises:
            ValueError: When the samconfig file cannot be read or is not
                valid TOML, wrapping the underlying error message.

        Example:
            >>> reader = SamconfigReader(Path('samconfig.toml'))
            >>> reader.read_parameter_overrides('test')
            {'Prefix': 'acme', 'S3ModuleLocation': '63klabz', 'S3ModuleNamespace': 'atlantis'}
        """
        raw = self._load_toml()
        merged = self._merge_stage_params(raw, stage_id)
        param_str = merged.get('parameter_overrides', '')
        return self.parse_parameter_overrides(param_str)

    def read_deploy_params(self, stage_id: str) -> Dict:
        """Return the merged raw deploy parameters for *stage_id*.

        Merges ``default.deploy.parameters`` with
        ``{stage_id}.deploy.parameters`` (stage wins). Values are returned
        as-is (strings, booleans, etc.) without further parsing.

        This is a lower-level helper used to read fields like ``s3_bucket``,
        ``s3_prefix``, ``region``, and ``role_arn``.

        Args:
            stage_id: SAM stage name.

        Returns:
            Dict of raw deploy parameter key/value pairs.

        Raises:
            ValueError: When the samconfig file cannot be read or is not
                valid TOML.

        Example:
            >>> reader = SamconfigReader(Path('samconfig.toml'))
            >>> params = reader.read_deploy_params('test')
            >>> params['s3_bucket']
            'cf-artifacts-123456789012-us-east-1'
        """
        raw = self._load_toml()
        return self._merge_stage_params(raw, stage_id)

    def read_atlantis_params(self) -> Dict:
        """Return the raw deploy parameters from the ``atlantis`` section.

        The ``atlantis`` section holds shared deployment settings that apply
        across all stages (e.g. ``s3_bucket``, ``region``).

        Returns:
            Dict of raw deploy parameter key/value pairs from
            ``atlantis.deploy.parameters``, or an empty dict if the section
            does not exist.

        Raises:
            ValueError: When the samconfig file cannot be read or is not
                valid TOML.

        Example:
            >>> reader = SamconfigReader(Path('samconfig.toml'))
            >>> reader.read_atlantis_params()
            {'s3_bucket': 'cf-artifacts-123456789012-us-east-1', 'region': 'us-east-1'}
        """
        raw = self._load_toml()
        return (
            raw.get('atlantis', {})
               .get('deploy', {})
               .get('parameters', {})
        )

    @staticmethod
    def parse_parameter_overrides(parameter_string: str) -> Dict[str, str]:
        """Parse a SAM CLI ``parameter_overrides`` string into a dict.

        Uses ``shlex.split`` to handle both the plain ``Key=Value`` format
        and the quoted ``"Key"="Value"`` format generated by ``config.py``.
        Shell tokenisation strips outer quotes, so values with embedded
        spaces (e.g. ``"Department"="Web Services"``) are handled correctly.

        This is a static method so it can be called without constructing a
        ``SamconfigReader`` instance when only the parsing step is needed.

        Args:
            parameter_string: Raw ``parameter_overrides`` string from a
                samconfig TOML, e.g.::

                    '"Prefix"="acme" "S3ModuleLocation"="63klabz"'

        Returns:
            Dict mapping parameter names to their string values. Returns an
            empty dict when *parameter_string* is empty or ``None``.

        Example:
            >>> SamconfigReader.parse_parameter_overrides(
            ...     '"Prefix"="acme" "S3ModuleLocation"="63klabz"'
            ... )
            {'Prefix': 'acme', 'S3ModuleLocation': '63klabz'}

            >>> SamconfigReader.parse_parameter_overrides(
            ...     'Env=prod Bucket=my-bucket'
            ... )
            {'Env': 'prod', 'Bucket': 'my-bucket'}
        """
        import shlex

        parameters: Dict[str, str] = {}
        if not parameter_string:
            return parameters

        try:
            parts = shlex.split(parameter_string)
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    parameters[key.strip()] = value.strip()
                else:
                    Log.warning(f"Skipping invalid parameter_overrides token: {part!r}")
        except Exception as e:
            Log.error(f"Error parsing parameter_overrides: {str(e)}")

        return parameters

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_toml(self) -> Dict:
        """Load and return the raw TOML dict.

        Raises:
            ValueError: Wrapping any I/O or parse error.
        """
        import tomli

        try:
            with open(self._config_file, 'rb') as f:
                return tomli.load(f)
        except FileNotFoundError:
            raise ValueError(f"Samconfig file not found: {self._config_file}")
        except tomli.TOMLDecodeError as e:
            raise ValueError(f"Invalid samconfig TOML: {str(e)}")
        except Exception as e:
            raise ValueError(f"Failed to read samconfig: {str(e)}")

    @staticmethod
    def _merge_stage_params(raw: Dict, stage_id: str) -> Dict:
        """Merge default and stage deploy.parameters (stage wins).

        Args:
            raw: The full parsed TOML dict.
            stage_id: Stage name to overlay on top of ``default``.

        Returns:
            Merged dict of deploy parameter key/value pairs.
        """
        default_params = (
            raw.get('default', {})
               .get('deploy', {})
               .get('parameters', {})
        )
        stage_params = (
            raw.get(stage_id, {})
               .get('deploy', {})
               .get('parameters', {})
        )
        return {**default_params, **stage_params}
