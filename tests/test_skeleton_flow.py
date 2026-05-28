"""Unit tests for run_skeleton_mode() flow in cli/config.py.

Tests the skeleton generation orchestration logic including:
- Directory creation when local-init/ doesn't exist
- Overwrite prompt when skeleton file already exists
- Correct JSON structure written to file
- Verbose mode includes _parameter_metadata
- Non-verbose mode excludes _parameter_metadata

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import run_skeleton_mode, ConfigManager


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
    return argparse.Namespace(**defaults)


def _mock_config_manager():
    """Create a mock ConfigManager instance with necessary methods."""
    mock_cm = MagicMock(spec=ConfigManager)
    mock_cm.discover_templates.return_value = ['s3://bucket/template.yml?versionId=abc123']
    mock_cm.get_latest_version_id.return_value = 's3://bucket/template.yml?versionId=abc123'
    mock_cm.get_template_parameters.return_value = (
        [{'Parameters': ['Prefix', 'ProjectId']}],
        {
            'Prefix': {'Type': 'String', 'Default': 'acme', 'Description': 'Org prefix'},
            'ProjectId': {'Type': 'String', 'Default': '', 'MinLength': 1},
        }
    )
    mock_cm.generate_skeleton.return_value = {
        'atlantis': {
            'deploy': {
                'parameters': {
                    'template_file': 's3://bucket/template.yml?versionId=abc123',
                    's3_bucket': 'my-deploy-bucket',
                    'region': 'us-east-1',
                    'capabilities': 'CAPABILITY_NAMED_IAM',
                    'confirm_changeset': True,
                }
            }
        },
        'applyTemplateUpdateIfAvailable': 'y',
        'deployments': {
            'dev': {
                'deploy': {
                    'parameters': {
                        'stack_name': 'acme-myapp-dev-pipeline',
                        's3_prefix': 'acme-myapp-dev-pipeline',
                        'parameter_overrides': {
                            'Prefix': 'acme',
                            'ProjectId': 'myapp',
                        },
                        'tags': {
                            'Owner': '',
                            'CostCenter': '',
                        }
                    }
                }
            }
        }
    }
    mock_cm.get_skeleton_file_path.return_value = Path('/fake/project/local-init/acme-myapp-dev-pipeline.json')
    return mock_cm


class TestSkeletonModeDirectoryCreation:
    """Test that run_skeleton_mode creates local-init/ directory when it doesn't exist."""

    @patch('config.json.dump')
    @patch('builtins.open', new_callable=mock_open)
    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_creates_local_init_directory(self, mock_makedirs, MockConfigManager,
                                          mock_select, mock_click, mock_file,
                                          mock_json_dump):
        """run_skeleton_mode calls os.makedirs to create local-init/ directory."""
        args = _make_skeleton_args()

        mock_cm = _mock_config_manager()
        mock_cm.get_skeleton_file_path.return_value = Path('/fake/project/local-init/acme-myapp-dev-pipeline.json')
        # Make the path not exist so no overwrite prompt
        with patch.object(Path, 'exists', return_value=False):
            MockConfigManager.return_value = mock_cm
            mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

            run_skeleton_mode(args)

        # Verify os.makedirs was called with exist_ok=True
        mock_makedirs.assert_called_once()
        call_args = mock_makedirs.call_args
        assert call_args[1].get('exist_ok') is True or (len(call_args[0]) > 1 and call_args[0][1] is True) or call_args[1].get('exist_ok', None) is True
        # Verify the path ends with 'local-init'
        dir_path = call_args[0][0]
        assert str(dir_path).endswith('local-init')


class TestSkeletonModeOverwritePrompt:
    """Test overwrite prompt behavior when skeleton file already exists."""

    @patch('config.json.dump')
    @patch('builtins.open', new_callable=mock_open)
    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_prompts_overwrite_when_file_exists(self, mock_makedirs, MockConfigManager,
                                                 mock_select, mock_click, mock_file,
                                                 mock_json_dump):
        """When skeleton file already exists, click.confirm is called to prompt overwrite."""
        args = _make_skeleton_args()

        mock_cm = _mock_config_manager()
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        # Make the skeleton path report as existing
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_cm.get_skeleton_file_path.return_value = mock_path

        # User confirms overwrite
        mock_click.confirm.return_value = True

        run_skeleton_mode(args)

        # Verify click.confirm was called
        mock_click.confirm.assert_called_once()
        confirm_msg = mock_click.confirm.call_args[0][0]
        assert 'already exists' in confirm_msg.lower() or 'overwrite' in confirm_msg.lower() or 'Overwrite' in confirm_msg

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_exits_when_user_declines_overwrite(self, mock_makedirs, MockConfigManager,
                                                 mock_select, mock_click):
        """When user declines overwrite, sys.exit(0) is called."""
        args = _make_skeleton_args()

        mock_cm = _mock_config_manager()
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        # Make the skeleton path report as existing
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_cm.get_skeleton_file_path.return_value = mock_path

        # User declines overwrite
        mock_click.confirm.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            run_skeleton_mode(args)

        assert exc_info.value.code == 0


class TestSkeletonModeJsonStructure:
    """Test that the correct JSON structure is written to file."""

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_json_has_correct_top_level_keys(self, mock_makedirs, MockConfigManager,
                                              mock_select, mock_click):
        """The JSON written to file has atlantis, deployments, and applyTemplateUpdateIfAvailable keys."""
        args = _make_skeleton_args()

        mock_cm = _mock_config_manager()
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        # Make the skeleton path not exist (no overwrite prompt)
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_cm.get_skeleton_file_path.return_value = mock_path

        # Capture what gets written to file
        written_data = {}

        def capture_json_dump(data, f, **kwargs):
            written_data.update(data)

        with patch('builtins.open', mock_open()), \
             patch('config.json.dump', side_effect=capture_json_dump):
            run_skeleton_mode(args)

        # Verify top-level keys
        assert 'atlantis' in written_data, "Skeleton must contain 'atlantis' key"
        assert 'deployments' in written_data, "Skeleton must contain 'deployments' key"
        assert 'applyTemplateUpdateIfAvailable' in written_data, (
            "Skeleton must contain 'applyTemplateUpdateIfAvailable' key"
        )

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_json_has_atlantis_deploy_parameters(self, mock_makedirs, MockConfigManager,
                                                  mock_select, mock_click):
        """The atlantis section contains deploy.parameters with expected keys."""
        args = _make_skeleton_args()

        mock_cm = _mock_config_manager()
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_cm.get_skeleton_file_path.return_value = mock_path

        written_data = {}

        def capture_json_dump(data, f, **kwargs):
            written_data.update(data)

        with patch('builtins.open', mock_open()), \
             patch('config.json.dump', side_effect=capture_json_dump):
            run_skeleton_mode(args)

        atlantis_params = written_data['atlantis']['deploy']['parameters']
        assert 'template_file' in atlantis_params
        assert 's3_bucket' in atlantis_params
        assert 'region' in atlantis_params
        assert 'capabilities' in atlantis_params
        assert 'confirm_changeset' in atlantis_params

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_json_has_deployment_stage_structure(self, mock_makedirs, MockConfigManager,
                                                  mock_select, mock_click):
        """The deployments section contains the stage with deploy.parameters structure."""
        args = _make_skeleton_args()

        mock_cm = _mock_config_manager()
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_cm.get_skeleton_file_path.return_value = mock_path

        written_data = {}

        def capture_json_dump(data, f, **kwargs):
            written_data.update(data)

        with patch('builtins.open', mock_open()), \
             patch('config.json.dump', side_effect=capture_json_dump):
            run_skeleton_mode(args)

        # Verify deployment stage structure
        assert 'dev' in written_data['deployments']
        stage_params = written_data['deployments']['dev']['deploy']['parameters']
        assert 'stack_name' in stage_params
        assert 's3_prefix' in stage_params
        assert 'parameter_overrides' in stage_params
        assert 'tags' in stage_params


class TestSkeletonModeVerbose:
    """Test verbose mode includes _parameter_metadata and non-verbose excludes it."""

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_verbose_mode_includes_parameter_metadata(self, mock_makedirs, MockConfigManager,
                                                       mock_select, mock_click):
        """When args.skeleton_verbose=True, the output includes _parameter_metadata."""
        args = _make_skeleton_args(skeleton_verbose=True)

        mock_cm = _mock_config_manager()
        # Override generate_skeleton to return verbose output with _parameter_metadata
        mock_cm.generate_skeleton.return_value = {
            'atlantis': {
                'deploy': {
                    'parameters': {
                        'template_file': 's3://bucket/template.yml?versionId=abc123',
                        's3_bucket': 'my-deploy-bucket',
                        'region': 'us-east-1',
                        'capabilities': 'CAPABILITY_NAMED_IAM',
                        'confirm_changeset': True,
                    }
                }
            },
            'applyTemplateUpdateIfAvailable': 'y',
            'deployments': {
                'dev': {
                    'deploy': {
                        'parameters': {
                            'stack_name': 'acme-myapp-dev-pipeline',
                            's3_prefix': 'acme-myapp-dev-pipeline',
                            'parameter_overrides': {'Prefix': 'acme'},
                            'tags': {}
                        }
                    }
                }
            },
            '_parameter_metadata': {
                'Prefix': {
                    'Type': 'String',
                    'Description': 'Org prefix',
                },
                'ProjectId': {
                    'Type': 'String',
                    'MinLength': 1,
                }
            }
        }
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_cm.get_skeleton_file_path.return_value = mock_path

        written_data = {}

        def capture_json_dump(data, f, **kwargs):
            written_data.update(data)

        with patch('builtins.open', mock_open()), \
             patch('config.json.dump', side_effect=capture_json_dump):
            run_skeleton_mode(args)

        # Verify _parameter_metadata is present
        assert '_parameter_metadata' in written_data, (
            "Verbose mode should include '_parameter_metadata' in output"
        )
        # Verify generate_skeleton was called with verbose=True
        mock_cm.generate_skeleton.assert_called_once()
        call_kwargs = mock_cm.generate_skeleton.call_args
        assert call_kwargs[1].get('verbose') is True or call_kwargs[0][3] is True if len(call_kwargs[0]) > 3 else call_kwargs[1].get('verbose') is True

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_non_verbose_mode_excludes_parameter_metadata(self, mock_makedirs, MockConfigManager,
                                                           mock_select, mock_click):
        """When args.skeleton=True (non-verbose), the output does NOT include _parameter_metadata."""
        args = _make_skeleton_args(skeleton=True, skeleton_verbose=False)

        mock_cm = _mock_config_manager()
        # generate_skeleton returns without _parameter_metadata for non-verbose
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_cm.get_skeleton_file_path.return_value = mock_path

        written_data = {}

        def capture_json_dump(data, f, **kwargs):
            written_data.update(data)

        with patch('builtins.open', mock_open()), \
             patch('config.json.dump', side_effect=capture_json_dump):
            run_skeleton_mode(args)

        # Verify _parameter_metadata is NOT present
        assert '_parameter_metadata' not in written_data, (
            "Non-verbose mode should NOT include '_parameter_metadata' in output"
        )
        # Verify generate_skeleton was called with verbose=False
        mock_cm.generate_skeleton.assert_called_once()
        call_kwargs = mock_cm.generate_skeleton.call_args
        # verbose should be False
        if len(call_kwargs[0]) > 3:
            assert call_kwargs[0][3] is False
        else:
            assert call_kwargs[1].get('verbose') is False

    @patch('config.click')
    @patch('config.FileNameListUtils.select_from_file_list')
    @patch('config.ConfigManager')
    @patch('config.os.makedirs')
    def test_verbose_flag_passed_to_generate_skeleton(self, mock_makedirs, MockConfigManager,
                                                       mock_select, mock_click):
        """The verbose flag from args is correctly passed to generate_skeleton()."""
        args = _make_skeleton_args(skeleton_verbose=True)

        mock_cm = _mock_config_manager()
        MockConfigManager.return_value = mock_cm
        mock_select.return_value = 's3://bucket/template.yml?versionId=abc123'

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_cm.get_skeleton_file_path.return_value = mock_path

        with patch('builtins.open', mock_open()), \
             patch('config.json.dump'):
            run_skeleton_mode(args)

        # Verify generate_skeleton was called with verbose=True
        mock_cm.generate_skeleton.assert_called_once()
        _, kwargs = mock_cm.generate_skeleton.call_args
        assert kwargs.get('verbose') is True
