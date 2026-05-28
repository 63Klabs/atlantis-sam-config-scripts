"""Unit tests for run_headless_mode() in cli/config.py.

Tests the headless execution flow including:
- File not found error with correct path in message
- Malformed JSON error
- Validation failure output lists all errors
- Successful end-to-end flow (mock git, file I/O)
- --deploy invokes deploy.py with correct arguments
- --deploy without --headless is no-op

Requirements: 6.1, 6.2, 6.4, 6.6, 9.1, 9.2, 9.3, 9.4, 9.5
"""

import json
import sys
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import run_headless_mode, ConfigManager, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _valid_skeleton():
    """Return a valid skeleton dict for testing."""
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
                        "parameter_overrides": {
                            "Prefix": "acme",
                            "ProjectId": "myapp",
                            "StageId": "dev"
                        },
                        "tags": {
                            "Owner": "team-a",
                            "CostCenter": "12345"
                        }
                    }
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# Test: File not found error with correct path in message (Req 6.1, 6.2)
# ---------------------------------------------------------------------------

class TestHeadlessFileNotFound:
    """Test that when skeleton file doesn't exist, sys.exit is called with path."""

    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_file_not_found_exits_with_path(self, mock_git):
        """When skeleton file doesn't exist, sys.exit includes 'skeleton file not found' and the path."""
        args = _make_headless_args()

        # Mock get_skeleton_file_path to return a non-existent path
        fake_path = Path('/tmp/nonexistent/acme-myapp-dev-pipeline.json')

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with pytest.raises(SystemExit) as exc_info:
                                run_headless_mode(args)

        error_msg = str(exc_info.value)
        assert "skeleton file not found" in error_msg
        assert str(fake_path) in error_msg


# ---------------------------------------------------------------------------
# Test: Malformed JSON error (Req 6.2, 7.5)
# ---------------------------------------------------------------------------

class TestHeadlessMalformedJson:
    """Test that when skeleton file contains malformed JSON, sys.exit is called."""

    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_malformed_json_exits_with_error(self, mock_git):
        """When skeleton file has invalid JSON, sys.exit includes 'malformed JSON'."""
        args = _make_headless_args()

        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True
        fake_path.__str__ = lambda self: '/tmp/acme-myapp-dev-pipeline.json'

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch('builtins.open', mock_open(read_data='{ invalid json !!!')):
                                with pytest.raises(SystemExit) as exc_info:
                                    run_headless_mode(args)

        error_msg = str(exc_info.value)
        assert "malformed JSON" in error_msg


# ---------------------------------------------------------------------------
# Test: Validation failure output lists all errors (Req 6.4)
# ---------------------------------------------------------------------------

class TestHeadlessValidationFailures:
    """Test that when validation fails, sys.exit lists all error messages."""

    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_validation_failures_lists_all_errors(self, mock_git):
        """When validation fails, exit message lists ALL failures."""
        args = _make_headless_args()

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        # Simulate validation failures
        param_failures = [
            {'parameter': 'Prefix', 'value': 'ACME', 'reason': "Value must match pattern: ^[a-z]+$"},
            {'parameter': 'StageId', 'value': 'invalid', 'reason': "Value must be one of: dev, test, beta, stage, prod"},
        ]
        deploy_failures = [
            {'parameter': 's3_bucket', 'value': 'BAD', 'reason': "S3 bucket name must be lowercase"},
        ]

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Prefix': {'Type': 'String'}, 'ProjectId': {'Type': 'String'}, 'StageId': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=param_failures):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=deploy_failures):
                                                    with pytest.raises(SystemExit) as exc_info:
                                                        run_headless_mode(args)

        error_msg = str(exc_info.value)
        assert "validation failed" in error_msg
        assert "Prefix" in error_msg
        assert "ACME" in error_msg
        assert "StageId" in error_msg
        assert "invalid" in error_msg
        assert "s3_bucket" in error_msg
        assert "BAD" in error_msg

    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_validation_failure_count_matches_all_errors(self, mock_git):
        """All validation errors are listed, not just the first one."""
        args = _make_headless_args()

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        # 3 parameter failures
        param_failures = [
            {'parameter': 'Param1', 'value': 'bad1', 'reason': 'reason1'},
            {'parameter': 'Param2', 'value': 'bad2', 'reason': 'reason2'},
            {'parameter': 'Param3', 'value': 'bad3', 'reason': 'reason3'},
        ]

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Param1': {'Type': 'String'}, 'Param2': {'Type': 'String'}, 'Param3': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=param_failures):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with pytest.raises(SystemExit) as exc_info:
                                                        run_headless_mode(args)

        error_msg = str(exc_info.value)
        # All 3 failures should be listed
        assert "Param1" in error_msg
        assert "Param2" in error_msg
        assert "Param3" in error_msg


# ---------------------------------------------------------------------------
# Test: Successful end-to-end flow (Req 6.5, 6.6)
# ---------------------------------------------------------------------------

class TestHeadlessSuccessfulFlow:
    """Test successful end-to-end headless flow with mocked dependencies."""

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_successful_flow_saves_config_and_deletes_skeleton(self, mock_git, mock_subprocess):
        """Successful headless flow calls save_config and deletes skeleton file."""
        args = _make_headless_args()

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Prefix': {'Type': 'String'}, 'ProjectId': {'Type': 'String'}, 'StageId': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={'deployments': {'dev': {'deploy': {'parameters': {}}}}}) as mock_build:
                                                            with patch.object(ConfigManager, 'save_config') as mock_save:
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

        # save_config was called
        mock_save.assert_called_once()
        # skeleton file was deleted
        fake_path.unlink.assert_called_once()
        # git commit and push was called
        mock_git.headless_git_commit_and_push.assert_called_once()

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_successful_flow_calls_git_pull_first(self, mock_git, mock_subprocess):
        """Headless flow calls Git.headless_git_pull() at the start."""
        args = _make_headless_args()

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Prefix': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={'deployments': {'dev': {'deploy': {'parameters': {}}}}}):
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

        mock_git.headless_git_pull.assert_called_once()


# ---------------------------------------------------------------------------
# Test: --deploy invokes deploy.py with correct arguments (Req 9.1, 9.2, 9.5)
# ---------------------------------------------------------------------------

class TestHeadlessDeployInvocation:
    """Test that --deploy flag invokes deploy.py with correct arguments."""

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_deploy_invokes_deploy_script_with_correct_args(self, mock_git, mock_subprocess):
        """--deploy invokes deploy.py with infra_type, prefix, project_id, stage_id, --headless."""
        args = _make_headless_args(deploy=True)

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        mock_subprocess.return_value = MagicMock(returncode=0)

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Prefix': {'Type': 'String'}, 'ProjectId': {'Type': 'String'}, 'StageId': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={'deployments': {'dev': {'deploy': {'parameters': {}}}}}):
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

        # Verify subprocess.run was called with deploy script
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args[0][0]

        # Should contain python executable, deploy.py path, positional args, and --headless
        assert 'pipeline' in call_args
        assert 'acme' in call_args
        assert 'myapp' in call_args
        assert 'dev' in call_args
        assert '--headless' in call_args

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_deploy_propagates_nonzero_exit_code(self, mock_git, mock_subprocess):
        """--deploy propagates non-zero exit code from deploy.py (Req 9.5)."""
        args = _make_headless_args(deploy=True)

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        mock_subprocess.return_value = MagicMock(returncode=2)

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Prefix': {'Type': 'String'}, 'ProjectId': {'Type': 'String'}, 'StageId': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={'deployments': {'dev': {'deploy': {'parameters': {}}}}}):
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    with pytest.raises(SystemExit) as exc_info:
                                                                        run_headless_mode(args)

        assert exc_info.value.code == 2

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_deploy_includes_profile_and_region_when_provided(self, mock_git, mock_subprocess):
        """--deploy passes --profile and --region to deploy.py when provided."""
        args = _make_headless_args(deploy=True, profile='my-profile', region='us-west-2')

        skeleton = _valid_skeleton()
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True

        mock_subprocess.return_value = MagicMock(returncode=0)

        with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=fake_path):
            with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                    with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                        with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                            with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2', 'us-west-2']}, create=True):
                                with patch('builtins.open', mock_open(read_data=json.dumps(skeleton))):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://bucket/template.yml?versionId=new123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=([{}], {'Prefix': {'Type': 'String'}, 'ProjectId': {'Type': 'String'}, 'StageId': {'Type': 'String'}})):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={'deployments': {'dev': {'deploy': {'parameters': {}}}}}):
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

        call_args = mock_subprocess.call_args[0][0]
        assert '--profile' in call_args
        assert 'my-profile' in call_args
        assert '--region' in call_args
        assert 'us-west-2' in call_args


# ---------------------------------------------------------------------------
# Test: --deploy without --headless is no-op (Req 9.3)
# ---------------------------------------------------------------------------

class TestDeployWithoutHeadlessIsNoop:
    """Test that --deploy without --headless has no effect."""

    @patch('config.run_headless_mode')
    @patch('config.run_skeleton_mode')
    def test_deploy_without_headless_does_not_invoke_deploy(self, mock_skeleton, mock_headless):
        """--deploy without --headless goes to interactive flow, deploy is ignored."""
        # When --deploy is provided without --headless, main() should go to the
        # interactive flow (not headless), so run_headless_mode is never called.
        test_argv = [
            'config.py', 'pipeline', 'acme', 'myapp', 'dev', '--deploy'
        ]

        with patch('sys.argv', test_argv):
            with patch('config.ConfigManager') as mock_cm_cls:
                with patch('config.Git'):
                    # Make ConfigManager raise to short-circuit the interactive flow
                    # (we just need to verify headless is NOT called)
                    mock_cm_cls.side_effect = SystemExit("interactive flow reached")
                    with pytest.raises(SystemExit) as exc_info:
                        main()

        # run_headless_mode should NOT have been called
        mock_headless.assert_not_called()
        # The error should be from the interactive flow, not from deploy
        assert "interactive flow reached" in str(exc_info.value)

    def test_deploy_flag_only_effective_with_headless(self):
        """Verify that --deploy flag is parsed but only acts when --headless is set."""
        test_argv = [
            'config.py', 'pipeline', 'acme', 'myapp', 'dev', '--deploy'
        ]

        with patch('sys.argv', test_argv):
            from config import parse_args, validate_mode_flags
            args = parse_args()

        # Flag is parsed
        assert args.deploy is True
        # But headless is not set
        assert args.headless is False

        # validate_mode_flags should NOT exit (--deploy alone is valid)
        validate_mode_flags(args)  # Should not raise
