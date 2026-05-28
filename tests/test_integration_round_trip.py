"""Integration tests for full skeleton → headless round trip.

Tests the end-to-end pipeline:
1. Generate skeleton (via generate_skeleton or run_skeleton_mode)
2. Modify a parameter value in the skeleton
3. Run headless mode with the modified skeleton
4. Verify save_config is called with the modified value
5. Verify skeleton file is deleted after successful headless run

Requirements: 6.6, 12.4
"""

import json
import os
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import run_headless_mode, run_skeleton_mode, ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skeleton_args(**kwargs):
    """Create argparse.Namespace with default skeleton mode args."""
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
    """Create argparse.Namespace with default headless mode args."""
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


def _sample_skeleton(prefix='acme', project_id='myapp', stage_id='dev'):
    """Return a valid skeleton dict for round-trip testing."""
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
            stage_id: {
                "deploy": {
                    "parameters": {
                        "stack_name": f"{prefix}-{project_id}-{stage_id}-pipeline",
                        "s3_prefix": f"{prefix}-{project_id}-{stage_id}-pipeline",
                        "parameter_overrides": {
                            "Prefix": prefix,
                            "ProjectId": project_id,
                            "StageId": stage_id,
                            "DeployEnvironment": "DEV",
                            "RepositoryBranch": stage_id
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
# Test: Full round trip — skeleton → modify → headless → verify output
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    """Integration test: generate skeleton, modify value, run headless, verify output."""

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_modified_prefix_propagates_to_save_config(self, mock_git, mock_subprocess):
        """
        Full round trip:
        1. Start with a skeleton containing Prefix='acme'
        2. Modify Prefix to 'newprefix'
        3. Run headless mode
        4. Verify save_config receives the modified 'newprefix' value
        """
        # Step 1 & 2: Create skeleton and modify Prefix
        skeleton = _sample_skeleton()
        skeleton['deployments']['dev']['deploy']['parameters']['parameter_overrides']['Prefix'] = 'newprefix'

        args = _make_headless_args()

        # Write skeleton to a real temp file so the round trip uses actual file I/O
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        try:
            saved_config = {}

            def capture_save_config(config):
                saved_config.update(config)

            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/atlantis/templates/v2/pipeline/cfn-pipeline.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{'Parameters': ['Prefix', 'ProjectId', 'StageId', 'DeployEnvironment', 'RepositoryBranch']}],
                                            {
                                                'Prefix': {'Type': 'String', 'AllowedPattern': '^[a-z][a-z0-9]{1,7}$'},
                                                'ProjectId': {'Type': 'String'},
                                                'StageId': {'Type': 'String'},
                                                'DeployEnvironment': {'Type': 'String', 'AllowedValues': ['DEV', 'TEST', 'PROD']},
                                                'RepositoryBranch': {'Type': 'String'}
                                            }
                                        )):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={
                                                            'atlantis': {'deploy': {'parameters': {}}},
                                                            'deployments': {'dev': {'deploy': {'parameters': {'parameter_overrides': {'Prefix': 'newprefix'}}}}}
                                                        }) as mock_build:
                                                            with patch.object(ConfigManager, 'save_config', side_effect=capture_save_config) as mock_save:
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

            # Verify save_config was called
            mock_save.assert_called_once()

            # Verify build_config_headless received the modified Prefix value
            build_call_args = mock_build.call_args
            parameter_values = build_call_args[0][3]  # 4th positional arg is parameter_values
            assert parameter_values['Prefix'] == 'newprefix', (
                f"Expected Prefix='newprefix' in build_config_headless call, got '{parameter_values.get('Prefix')}'"
            )

        finally:
            # Clean up temp file if it still exists (headless should delete it)
            if tmp_path.exists():
                tmp_path.unlink()

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_modified_deploy_environment_propagates(self, mock_git, mock_subprocess):
        """
        Modify DeployEnvironment from 'DEV' to 'TEST' in skeleton,
        verify it propagates through headless mode to build_config_headless.
        """
        skeleton = _sample_skeleton()
        skeleton['deployments']['dev']['deploy']['parameters']['parameter_overrides']['DeployEnvironment'] = 'TEST'

        args = _make_headless_args()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        try:
            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/template.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{}],
                                            {
                                                'Prefix': {'Type': 'String'},
                                                'ProjectId': {'Type': 'String'},
                                                'StageId': {'Type': 'String'},
                                                'DeployEnvironment': {'Type': 'String', 'AllowedValues': ['DEV', 'TEST', 'PROD']},
                                                'RepositoryBranch': {'Type': 'String'}
                                            }
                                        )):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={
                                                            'atlantis': {'deploy': {'parameters': {}}},
                                                            'deployments': {'dev': {'deploy': {'parameters': {}}}}
                                                        }) as mock_build:
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

            # Verify the modified DeployEnvironment was passed to build_config_headless
            build_call_args = mock_build.call_args
            parameter_values = build_call_args[0][3]
            assert parameter_values['DeployEnvironment'] == 'TEST', (
                f"Expected DeployEnvironment='TEST', got '{parameter_values.get('DeployEnvironment')}'"
            )

        finally:
            if tmp_path.exists():
                tmp_path.unlink()


# ---------------------------------------------------------------------------
# Test: Skeleton file deletion after successful headless run (Req 6.6, 12.4)
# ---------------------------------------------------------------------------

class TestSkeletonFileDeletion:
    """Verify skeleton file is deleted after successful headless execution."""

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_skeleton_file_deleted_after_successful_headless(self, mock_git, mock_subprocess):
        """
        After successful headless execution, the skeleton file no longer exists.
        Uses a real temp file to verify actual deletion.
        """
        skeleton = _sample_skeleton()
        args = _make_headless_args()

        # Write skeleton to a real temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        # Confirm the file exists before headless run
        assert tmp_path.exists(), "Skeleton file should exist before headless run"

        try:
            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/template.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{}],
                                            {
                                                'Prefix': {'Type': 'String'},
                                                'ProjectId': {'Type': 'String'},
                                                'StageId': {'Type': 'String'},
                                                'DeployEnvironment': {'Type': 'String'},
                                                'RepositoryBranch': {'Type': 'String'}
                                            }
                                        )):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={
                                                            'atlantis': {'deploy': {'parameters': {}}},
                                                            'deployments': {'dev': {'deploy': {'parameters': {}}}}
                                                        }):
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

            # Verify the skeleton file was deleted
            assert not tmp_path.exists(), (
                f"Skeleton file should be deleted after successful headless run, "
                f"but still exists at {tmp_path}"
            )

        finally:
            # Safety cleanup in case test fails before deletion
            if tmp_path.exists():
                tmp_path.unlink()

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_skeleton_file_not_deleted_on_validation_failure(self, mock_git, mock_subprocess):
        """
        When validation fails, the skeleton file should NOT be deleted
        (user needs to fix and retry).
        """
        skeleton = _sample_skeleton()
        args = _make_headless_args()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        assert tmp_path.exists(), "Skeleton file should exist before headless run"

        try:
            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/template.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{}],
                                            {'Prefix': {'Type': 'String'}, 'ProjectId': {'Type': 'String'}, 'StageId': {'Type': 'String'}}
                                        )):
                                            # Simulate validation failure
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[
                                                {'parameter': 'Prefix', 'value': 'BAD', 'reason': 'Invalid'}
                                            ]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with pytest.raises(SystemExit):
                                                        run_headless_mode(args)

            # Skeleton file should still exist after validation failure
            assert tmp_path.exists(), (
                "Skeleton file should NOT be deleted when validation fails"
            )

        finally:
            if tmp_path.exists():
                tmp_path.unlink()


# ---------------------------------------------------------------------------
# Test: Modified value propagation through the full pipeline
# ---------------------------------------------------------------------------

class TestModifiedValuePropagation:
    """Test that modified values in skeleton correctly propagate to save_config."""

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_changed_prefix_reaches_build_config_headless(self, mock_git, mock_subprocess):
        """
        Generate skeleton with default Prefix='acme', change to 'newprefix',
        run headless, verify 'newprefix' is passed to build_config_headless.
        """
        skeleton = _sample_skeleton(prefix='acme')
        # Modify the prefix in the skeleton
        skeleton['deployments']['dev']['deploy']['parameters']['parameter_overrides']['Prefix'] = 'newprefix'

        args = _make_headless_args()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        try:
            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/template.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{}],
                                            {
                                                'Prefix': {'Type': 'String'},
                                                'ProjectId': {'Type': 'String'},
                                                'StageId': {'Type': 'String'},
                                                'DeployEnvironment': {'Type': 'String'},
                                                'RepositoryBranch': {'Type': 'String'}
                                            }
                                        )):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={
                                                            'atlantis': {'deploy': {'parameters': {}}},
                                                            'deployments': {'dev': {'deploy': {'parameters': {'parameter_overrides': {'Prefix': 'newprefix'}}}}}
                                                        }) as mock_build:
                                                            with patch.object(ConfigManager, 'save_config') as mock_save:
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

            # Verify build_config_headless was called with modified Prefix
            mock_build.assert_called_once()
            call_args = mock_build.call_args[0]
            parameter_values = call_args[3]  # 4th positional arg
            assert parameter_values['Prefix'] == 'newprefix'

            # Verify save_config was called (config was saved)
            mock_save.assert_called_once()

        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_modified_tags_propagate_to_build_config_headless(self, mock_git, mock_subprocess):
        """
        Modify a tag value in the skeleton and verify it propagates
        to build_config_headless as a tag list.
        """
        skeleton = _sample_skeleton()
        skeleton['deployments']['dev']['deploy']['parameters']['tags']['Owner'] = 'new-team'

        args = _make_headless_args()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        try:
            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/template.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{}],
                                            {
                                                'Prefix': {'Type': 'String'},
                                                'ProjectId': {'Type': 'String'},
                                                'StageId': {'Type': 'String'},
                                                'DeployEnvironment': {'Type': 'String'},
                                                'RepositoryBranch': {'Type': 'String'}
                                            }
                                        )):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={
                                                            'atlantis': {'deploy': {'parameters': {}}},
                                                            'deployments': {'dev': {'deploy': {'parameters': {}}}}
                                                        }) as mock_build:
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

            # Verify tags were passed to build_config_headless
            mock_build.assert_called_once()
            call_args = mock_build.call_args[0]
            tags = call_args[4]  # 5th positional arg is tags (List[Dict])

            # Tags should be in CloudFormation list format
            tag_dict = {t['Key']: t['Value'] for t in tags}
            assert tag_dict.get('Owner') == 'new-team', (
                f"Expected Owner='new-team' in tags, got '{tag_dict.get('Owner')}'"
            )

        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @patch('config.subprocess.run')
    @patch('config.Git')
    @patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None)
    def test_atlantis_deploy_params_propagate(self, mock_git, mock_subprocess):
        """
        Modify s3_bucket in skeleton's atlantis section and verify it
        propagates to build_config_headless.
        """
        skeleton = _sample_skeleton()
        skeleton['atlantis']['deploy']['parameters']['s3_bucket'] = 'new-deploy-bucket'

        args = _make_headless_args()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(skeleton, tmp)
            tmp_path = Path(tmp.name)

        try:
            with patch.object(ConfigManager, 'get_skeleton_file_path', return_value=tmp_path):
                with patch.object(ConfigManager, 'infra_type', 'pipeline', create=True):
                    with patch.object(ConfigManager, 'prefix', 'acme', create=True):
                        with patch.object(ConfigManager, 'project_id', 'myapp', create=True):
                            with patch.object(ConfigManager, 'stage_id', 'dev', create=True):
                                with patch.object(ConfigManager, 'settings', {'regions': ['us-east-2']}, create=True):
                                    with patch.object(ConfigManager, 'get_latest_version_id', return_value='s3://63klabs/template.yml?versionId=abc123'):
                                        with patch.object(ConfigManager, 'get_template_parameters', return_value=(
                                            [{}],
                                            {
                                                'Prefix': {'Type': 'String'},
                                                'ProjectId': {'Type': 'String'},
                                                'StageId': {'Type': 'String'},
                                                'DeployEnvironment': {'Type': 'String'},
                                                'RepositoryBranch': {'Type': 'String'}
                                            }
                                        )):
                                            with patch.object(ConfigManager, 'validate_all_parameters', return_value=[]):
                                                with patch.object(ConfigManager, 'validate_atlantis_deploy_params', return_value=[]):
                                                    with patch.object(ConfigManager, 'read_samconfig', return_value={}):
                                                        with patch.object(ConfigManager, 'build_config_headless', return_value={
                                                            'atlantis': {'deploy': {'parameters': {}}},
                                                            'deployments': {'dev': {'deploy': {'parameters': {}}}}
                                                        }) as mock_build:
                                                            with patch.object(ConfigManager, 'save_config'):
                                                                with patch('config._headless_auto_save_defaults'):
                                                                    run_headless_mode(args)

            # Verify atlantis_params passed to build_config_headless has the new bucket
            mock_build.assert_called_once()
            call_args = mock_build.call_args[0]
            atlantis_params = call_args[2]  # 3rd positional arg is atlantis_params
            assert atlantis_params['s3_bucket'] == 'new-deploy-bucket', (
                f"Expected s3_bucket='new-deploy-bucket', got '{atlantis_params.get('s3_bucket')}'"
            )

        finally:
            if tmp_path.exists():
                tmp_path.unlink()
