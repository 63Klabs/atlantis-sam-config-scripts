"""Flow tests for the name length warnings in cli/config.py.

Feature: config-name-length-warnings

Checks that the warning is wired into each mode of config.py:
- run_skeleton_mode warns before generate_skeleton and still writes the file
- run_headless_mode warns on stderr after validation, never on stdout, and
  never exits because of the warning
- run_headless_mode does not run the check when validation fails
- run_headless_mode tolerates a skeleton without StageId
- main() (interactive) warns after the template parameters are read and before
  the prompts, then warns again only when the entered values changed

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.4, 6.6, 6.7, 6.8
"""

import json
import sys
from argparse import Namespace
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

import config
from config import (
    run_skeleton_mode,
    run_headless_mode,
    main,
    ConfigManager,
    NAME_LENGTH_HEADING_FINAL,
    NAME_LENGTH_WARNING_NOTE,
)

PREFIX_8_LINE = 'Prefix is 8 characters (recommended maximum: 6).'
ALL_THREE_PARAMETERS = {'Prefix': {}, 'ProjectId': {}, 'StageId': {}}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skeleton_args(**kwargs):
    """Create an argparse.Namespace with default skeleton mode args."""
    defaults = {
        'infra_type': 'pipeline',
        'prefix': 'acme',
        'project_id': 'myapp',
        'stage_id': 'dev',
        'profile': None,
        'region': None,
        'no_browser': False,
        'skeleton': True,
        'skeleton_verbose': False,
        'headless': False,
        'deploy': False,
        'check_stack': False,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def _make_headless_args(**kwargs):
    """Create an argparse.Namespace with default headless args, overridden by kwargs."""
    defaults = {
        'infra_type': 'pipeline',
        'prefix': 'acme',
        'project_id': 'myapp',
        'stage_id': 'dev',
        'profile': None,
        'region': None,
        'no_browser': False,
        'headless': True,
        'deploy': False,
        'skeleton': False,
        'skeleton_verbose': False,
        'check_stack': False,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def _valid_skeleton(prefix='acme', include_stage_id=True):
    """Return a valid skeleton dict for testing."""
    overrides = {
        "Prefix": prefix,
        "ProjectId": "myapp",
    }
    if include_stage_id:
        overrides["StageId"] = "dev"
    return {
        "atlantis": {
            "deploy": {
                "parameters": {
                    "template_file": "s3://63klabs/atlantis/templates/v2/pipeline/cfn-pipeline.yml?versionId=abc123",
                    "s3_bucket": "cf-deploy-bucket",
                    "region": "us-east-2",
                    "capabilities": "CAPABILITY_NAMED_IAM",
                    "confirm_changeset": "true",
                    "role_arn": "arn:aws:iam::123456789012:role/sam-pipeline-role"
                }
            }
        },
        "applyTemplateUpdateIfAvailable": "y",
        "deployments": {
            "dev": {
                "deploy": {
                    "parameters": {
                        "stack_name": "acme-myapp-dev-pipeline",
                        "s3_prefix": "acme-myapp-dev-pipeline",
                        "parameter_overrides": overrides,
                        "tags": {"Owner": "team-a"}
                    }
                }
            }
        }
    }


def _mock_skeleton_config_manager(prefix):
    """Create a mock ConfigManager instance for run_skeleton_mode."""
    mock_cm = MagicMock(spec=ConfigManager)
    # Instance attributes set in ConfigManager.__init__ are not visible to spec=
    mock_cm.prefix = prefix
    mock_cm.project_id = 'myapp'
    mock_cm.stage_id = 'dev'
    mock_cm.read_samconfig.return_value = None
    mock_cm.discover_templates.return_value = ['s3://bucket/template.yml?versionId=abc123']
    mock_cm.get_latest_version_id.return_value = 's3://bucket/template.yml?versionId=abc123'
    mock_cm.get_template_parameters.return_value = ({}, dict(ALL_THREE_PARAMETERS))
    mock_cm.generate_skeleton.return_value = {'atlantis': {}, 'deployments': {}}
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = False
    mock_cm.get_skeleton_file_path.return_value = mock_path
    return mock_cm


def _run_skeleton(prefix):
    """Run run_skeleton_mode with mocks and return what happened.

    Returns:
        Tuple of (mock_show, events, mock_dump). events is the ordered list of
        'show' and 'generate_skeleton' calls.
    """
    events = []
    mock_cm = _mock_skeleton_config_manager(prefix)
    mock_cm.generate_skeleton.side_effect = (
        lambda *a, **kw: events.append('generate_skeleton') or {'atlantis': {}, 'deployments': {}}
    )

    with ExitStack() as stack:
        mock_config_manager_cls = stack.enter_context(patch('config.ConfigManager'))
        mock_config_manager_cls.return_value = mock_cm
        stack.enter_context(patch('config.os.makedirs'))
        stack.enter_context(patch('config.click'))
        stack.enter_context(patch('config.FileNameListUtils.select_from_file_list',
                                  return_value='s3://bucket/template.yml?versionId=abc123'))
        stack.enter_context(patch('builtins.open', mock_open()))
        mock_dump = stack.enter_context(patch('config.json.dump'))
        mock_show = stack.enter_context(patch('config.show_name_length_warnings'))
        mock_show.side_effect = lambda *a, **kw: events.append('show')

        run_skeleton_mode(_make_skeleton_args(prefix=prefix))

    return mock_show, events, mock_dump


def _run_headless(skeleton, parameters, args=None, validation_failures=None,
                  extra_patches=None):
    """Run run_headless_mode with the patch stack of TestHeadlessSuccessfulFlow.

    Args:
        skeleton: Skeleton dict returned by the mocked file read.
        parameters: Template parameters dict returned by get_template_parameters.
        args: Namespace for run_headless_mode. Defaults to _make_headless_args().
        validation_failures: List returned by validate_all_parameters.
        extra_patches: Optional dict of {target: MagicMock} to patch in addition.

    Returns:
        Tuple of (mock_save, mock_git).
    """
    args = args or _make_headless_args()
    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = True

    with ExitStack() as stack:
        stack.enter_context(patch('config.subprocess.run'))
        mock_git = stack.enter_context(patch('config.Git'))
        stack.enter_context(patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None))
        stack.enter_context(patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path))
        stack.enter_context(patch.object(ConfigManager, 'infra_type', 'pipeline', create=True))
        stack.enter_context(patch.object(ConfigManager, 'prefix', 'acme', create=True))
        stack.enter_context(patch.object(ConfigManager, 'project_id', 'myapp', create=True))
        stack.enter_context(patch.object(ConfigManager, 'stage_id', 'dev', create=True))
        stack.enter_context(patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True))
        stack.enter_context(patch('builtins.open', mock_open(read_data=json.dumps(skeleton))))
        stack.enter_context(patch.object(ConfigManager, 'get_latest_version_id',
                                         return_value='s3://bucket/template.yml?versionId=new123'))
        stack.enter_context(patch.object(ConfigManager, 'get_template_parameters',
                                         return_value=([{}], parameters)))
        stack.enter_context(patch.object(ConfigManager, 'validate_all_parameters',
                                         return_value=validation_failures or []))
        stack.enter_context(patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]))
        stack.enter_context(patch.object(ConfigManager, 'read_samconfig', return_value={}))
        stack.enter_context(patch.object(
            ConfigManager, 'build_config_headless',
            return_value={'deployments': {'dev': {'deploy': {'parameters': {}}}}}))
        mock_save = stack.enter_context(patch.object(ConfigManager, 'save_config'))
        stack.enter_context(patch('config._headless_auto_save_defaults'))
        for target, replacement in (extra_patches or {}).items():
            stack.enter_context(patch(target, replacement))

        run_headless_mode(args)

    return mock_save, mock_git


# ---------------------------------------------------------------------------
# Skeleton mode (Req 3.3, 5.1, 6.7)
# ---------------------------------------------------------------------------

class TestSkeletonModeWarns:
    """run_skeleton_mode warns about the argument values before generating the skeleton."""

    def test_long_prefix_warns_once_before_generate_skeleton(self):
        """An 8-character Prefix produces one printer call, before generate_skeleton."""
        mock_show, events, mock_dump = _run_skeleton('acmecorp')

        mock_show.assert_called_once()
        lines = mock_show.call_args[0][0]
        assert lines == [PREFIX_8_LINE, NAME_LENGTH_WARNING_NOTE]
        assert events == ['show', 'generate_skeleton']

    def test_long_prefix_still_writes_skeleton_file(self):
        """The warning does not stop the skeleton from being written."""
        _, _, mock_dump = _run_skeleton('acmecorp')

        mock_dump.assert_called_once()

    def test_short_values_give_no_warning_lines(self):
        """With values within the limits the printer gets an empty list (or is not called)."""
        mock_show, _, mock_dump = _run_skeleton('acme')

        for printer_call in mock_show.call_args_list:
            assert printer_call[0][0] == []
        mock_dump.assert_called_once()


# ---------------------------------------------------------------------------
# Headless mode (Req 2.3, 3.4, 3.5, 5.4, 6.8)
# ---------------------------------------------------------------------------

class TestHeadlessWarns:
    """run_headless_mode writes the warning to stderr and carries on."""

    def test_long_prefix_warns_on_stderr_only_and_saves(self, capsys):
        """Warning text is on stderr, not stdout, and save_config is called once."""
        skeleton = _valid_skeleton(prefix='acmecorp')

        mock_save, _ = _run_headless(skeleton, dict(ALL_THREE_PARAMETERS))

        captured = capsys.readouterr()
        assert 'Warning: Prefix is 8 characters' in captured.err
        assert 'characters (recommended maximum' not in captured.out
        assert 'Warning:' not in captured.out
        mock_save.assert_called_once()

    def test_short_values_print_no_warning(self, capsys):
        """Values within the limits print nothing to stderr."""
        skeleton = _valid_skeleton(prefix='acme')

        mock_save, _ = _run_headless(skeleton, dict(ALL_THREE_PARAMETERS))

        captured = capsys.readouterr()
        assert 'Warning:' not in captured.err
        mock_save.assert_called_once()


class TestHeadlessValidationFailure:
    """A validation failure exits as before and the length check never runs."""

    def test_validation_failure_exits_without_length_check(self):
        """SystemExit is raised from validation and get_name_length_warnings is not called."""
        skeleton = _valid_skeleton(prefix='acmecorp')
        failures = [{'parameter': 'Prefix', 'value': 'acmecorp', 'reason': 'bad value'}]
        mock_get_warnings = MagicMock(return_value=[])

        with pytest.raises(SystemExit) as exc_info:
            _run_headless(
                skeleton, dict(ALL_THREE_PARAMETERS),
                validation_failures=failures,
                extra_patches={'config.get_name_length_warnings': mock_get_warnings},
            )

        assert 'validation failed' in str(exc_info.value)
        mock_get_warnings.assert_not_called()


class TestHeadlessMissingStageId:
    """A skeleton without StageId is tolerated even when the template declares it."""

    def test_missing_stage_id_completes_without_stage_id_line(self, capsys):
        """The run completes and no StageId warning line is printed."""
        skeleton = _valid_skeleton(prefix='acmecorp', include_stage_id=False)

        mock_save, _ = _run_headless(skeleton, dict(ALL_THREE_PARAMETERS))

        captured = capsys.readouterr()
        assert 'Warning: Prefix is 8 characters' in captured.err
        assert 'StageId is ' not in captured.err
        assert 'Prefix+ProjectId+StageId is ' not in captured.err
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Interactive main() (Req 3.1, 3.2, 6.6)
# ---------------------------------------------------------------------------

def _run_interactive_main(prompt_result):
    """Run main() with the interactive path mocked.

    Args:
        prompt_result: Dict returned by ConfigManager.prompt_for_parameters.

    Returns:
        Tuple of (parent, mock_show). parent records, in order, the calls to
        get_template_parameters, prompt_for_parameters, and the patched
        show_name_length_warnings.
    """
    args = Namespace(
        infra_type='pipeline', prefix='acmecorp', project_id='myapp', stage_id='dev',
        check_stack=False, skeleton=False, skeleton_verbose=False, headless=False,
        deploy=False, profile=None, region=None, no_browser=False,
    )
    params = dict(ALL_THREE_PARAMETERS)

    with ExitStack() as stack:
        stack.enter_context(patch('config.parse_args', return_value=args))
        mock_cm_cls = stack.enter_context(patch('config.ConfigManager'))
        instance = mock_cm_cls.return_value
        instance.prefix = 'acmecorp'
        instance.project_id = 'myapp'
        instance.stage_id = 'dev'
        instance.defaults = {}
        instance.read_samconfig.return_value = None
        instance.discover_templates.return_value = ['t.yml']
        instance.get_template_parameters.return_value = ([], params)
        instance.resolve_role_arn.return_value = ''
        instance.calculate_stage_defaults.return_value = {}
        instance.merge_tags.return_value = []
        instance.get_default_tags.return_value = {}
        instance.get_script_deploy_command.return_value = 'deploy-command'
        instance.prompt_for_parameters.return_value = prompt_result

        stack.enter_context(patch('config.Git'))
        mock_select = stack.enter_context(patch('config.FileNameListUtils'))
        mock_select.select_from_file_list.return_value = 't.yml'
        stack.enter_context(patch('config.TagUtils'))
        stack.enter_context(patch('config.CodeCommitUtils'))
        stack.enter_context(patch('config.click.confirm', return_value=False))
        mock_show = stack.enter_context(patch('config.show_name_length_warnings'))

        parent = MagicMock()
        parent.attach_mock(instance.get_template_parameters, 'get_template_parameters')
        parent.attach_mock(instance.prompt_for_parameters, 'prompt_for_parameters')
        parent.attach_mock(mock_show, 'show_name_length_warnings')

        main()

    return parent, mock_show


class TestInteractiveOrder:
    """The first check runs after the template parameters are read and before the prompts."""

    def test_first_warning_between_template_read_and_prompts(self):
        """Call order: get_template_parameters, show_name_length_warnings, prompt_for_parameters."""
        prompt_result = {'Prefix': 'acmecorp', 'ProjectId': 'myapp', 'StageId': 'dev'}

        parent, mock_show = _run_interactive_main(prompt_result)

        names = [
            name for name, _, _ in parent.mock_calls
            if name in ('get_template_parameters', 'show_name_length_warnings',
                        'prompt_for_parameters')
        ]
        assert names[0] == 'get_template_parameters'
        assert names[1] == 'show_name_length_warnings'
        assert names[2] == 'prompt_for_parameters'
        first_lines = mock_show.call_args_list[0][0][0]
        assert first_lines == [PREFIX_8_LINE, NAME_LENGTH_WARNING_NOTE]


class TestInteractiveSecondCheck:
    """The second check runs only when the prompted values differ from the arguments."""

    def test_changed_prefix_triggers_second_check_with_final_heading(self):
        """A changed Prefix gives a second printer call with NAME_LENGTH_HEADING_FINAL."""
        prompt_result = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        _, mock_show = _run_interactive_main(prompt_result)

        assert mock_show.call_count == 2
        assert mock_show.call_args_list[1][1].get('heading') == NAME_LENGTH_HEADING_FINAL

    def test_unchanged_values_give_only_one_check(self):
        """Values equal to the arguments give only the first printer call."""
        prompt_result = {'Prefix': 'acmecorp', 'ProjectId': 'myapp', 'StageId': 'dev'}

        _, mock_show = _run_interactive_main(prompt_result)

        assert mock_show.call_count == 1
