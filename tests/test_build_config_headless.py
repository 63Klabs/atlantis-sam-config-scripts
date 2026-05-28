"""Unit tests for ConfigManager.build_config_headless() in cli/config.py.

Tests that build_config_headless() mirrors build_config() logic but skips
gather_atlantis_deploy_parameters() prompts, accepting pre-validated inputs.

Validates: Requirements 6.3, 6.5
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, PropertyMock

import pytest

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_config_manager(prefix='acme', project_id='myapp', stage_id='dev', infra_type='pipeline'):
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        cm.prefix = prefix
        cm.project_id = project_id
        cm.stage_id = stage_id
        cm.infra_type = infra_type
        cm.template_file = 's3://bucket/templates/pipeline.yml?versionId=abc123'
        cm.template_version = 'v1.0.0'
        cm.template_hash_id = 'hash123'
        return cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildConfigHeadless:
    """Tests for build_config_headless() method."""

    def test_returns_config_with_atlantis_and_deployments_keys(self):
        """Config dict has 'atlantis' and 'deployments' top-level keys."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'my-deploy-bucket',
            'region': 'us-east-1',
            'capabilities': 'CAPABILITY_NAMED_IAM',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/deploy-role'
        }
        parameter_values = {
            'Prefix': 'acme',
            'ProjectId': 'myapp',
            'StageId': 'dev',
        }
        tags = [{'Key': 'Owner', 'Value': 'team-a'}]

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, tags, {})

        assert 'atlantis' in config
        assert 'deployments' in config
        assert 'deploy' in config['atlantis']
        assert 'parameters' in config['atlantis']['deploy']

    def test_atlantis_deploy_parameters_match_input(self):
        """Atlantis deploy parameters are correctly set from input."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'my-deploy-bucket',
            'region': 'us-east-2',
            'capabilities': 'CAPABILITY_NAMED_IAM',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/deploy-role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}
        tags = []

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, tags, {})

        params = config['atlantis']['deploy']['parameters']
        assert params['s3_bucket'] == 'my-deploy-bucket'
        assert params['region'] == 'us-east-2'
        assert params['capabilities'] == 'CAPABILITY_NAMED_IAM'
        assert params['confirm_changeset'] is True

    def test_confirm_changeset_false_string(self):
        """confirm_changeset 'false' string is converted to boolean False."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'false',
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        config = cm.build_config_headless('network', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert config['atlantis']['deploy']['parameters']['confirm_changeset'] is False

    def test_confirm_changeset_boolean_input(self):
        """confirm_changeset as boolean True is preserved."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': True,
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        config = cm.build_config_headless('network', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert config['atlantis']['deploy']['parameters']['confirm_changeset'] is True

    def test_role_arn_included_for_pipeline(self):
        """role_arn is included in atlantis params for pipeline infra_type."""
        cm = _create_config_manager(infra_type='pipeline')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/my-role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert config['atlantis']['deploy']['parameters']['role_arn'] == 'arn:aws:iam::123456789012:role/my-role'

    def test_role_arn_included_for_storage(self):
        """role_arn is included in atlantis params for storage infra_type."""
        cm = _create_config_manager(infra_type='storage')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/storage-role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': ''}

        config = cm.build_config_headless('storage', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert config['atlantis']['deploy']['parameters']['role_arn'] == 'arn:aws:iam::123456789012:role/storage-role'

    def test_role_arn_not_included_for_network(self):
        """role_arn is NOT included in atlantis params for network infra_type."""
        cm = _create_config_manager(infra_type='network')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        config = cm.build_config_headless('network', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert 'role_arn' not in config['atlantis']['deploy']['parameters']

    def test_stack_name_generation(self):
        """Stack name is generated using get_stack_name() logic (prefix-project-stage-infra)."""
        cm = _create_config_manager(prefix='acme', project_id='myapp', stage_id='dev', infra_type='pipeline')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        deployment = config['deployments']['dev']['deploy']['parameters']
        assert deployment['stack_name'] == 'acme-myapp-dev-pipeline'
        assert deployment['s3_prefix'] == 'acme-myapp-dev-pipeline'

    def test_stack_name_without_stage_id(self):
        """Stack name omits stage_id when it is 'default'."""
        cm = _create_config_manager(prefix='acme', project_id='myapp', stage_id='default', infra_type='storage')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': ''}

        config = cm.build_config_headless('storage', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        deployment = config['deployments']['default']['deploy']['parameters']
        assert deployment['stack_name'] == 'acme-myapp-storage'

    def test_deployment_contains_parameter_overrides(self):
        """Deployment parameters include the parameter_overrides dict."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        parameter_values = {
            'Prefix': 'acme',
            'ProjectId': 'myapp',
            'StageId': 'dev',
            'DeployEnvironment': 'DEV',
        }

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        deployment = config['deployments']['dev']['deploy']['parameters']
        assert deployment['parameter_overrides'] == parameter_values

    def test_tags_are_merged_with_automated_tags(self):
        """User-provided tags are merged with automated tags via generate_tags()."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        parameter_values = {
            'Prefix': 'acme',
            'ProjectId': 'myapp',
            'StageId': 'dev',
        }
        custom_tags = [{'Key': 'Owner', 'Value': 'team-a'}, {'Key': 'CostCenter', 'Value': '12345'}]

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, custom_tags, {})

        deployment = config['deployments']['dev']['deploy']['parameters']
        tag_keys = [t['Key'] for t in deployment['tags']]

        # Automated tags should be present
        assert 'Atlantis' in tag_keys
        assert 'Provisioner' in tag_keys
        # Custom tags should be present
        assert 'Owner' in tag_keys
        assert 'CostCenter' in tag_keys

    def test_s3_template_preserved_as_is(self):
        """S3 template URI is preserved in the config."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}
        s3_uri = 's3://mybucket/templates/pipeline.yml?versionId=abc123'

        config = cm.build_config_headless('pipeline', s3_uri, atlantis_params, parameter_values, [], {})

        assert config['atlantis']['deploy']['parameters']['template_file'] == s3_uri

    def test_deployments_uses_stage_id_from_parameter_values(self):
        """Deployment key uses StageId from parameter_values when provided."""
        cm = _create_config_manager(stage_id='default')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'prod'}

        config = cm.build_config_headless('network', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert 'prod' in config['deployments']

    def test_deployments_uses_instance_stage_id_when_not_in_params(self):
        """Deployment key uses self.stage_id when StageId is empty in parameter_values."""
        cm = _create_config_manager(stage_id='beta')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': ''}

        config = cm.build_config_headless('network', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert 'beta' in config['deployments']

    def test_preserves_other_deployments_from_local_config(self):
        """Other deployments from local_config are preserved when prefix/project match."""
        cm = _create_config_manager(prefix='acme', project_id='myapp', stage_id='dev')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}
        local_config = {
            'deployments': {
                'prod': {
                    'deploy': {
                        'parameters': {'stack_name': 'acme-myapp-prod-pipeline'}
                    }
                }
            }
        }

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, [], local_config)

        # Both dev (new) and prod (preserved) should be present
        assert 'dev' in config['deployments']
        assert 'prod' in config['deployments']

    def test_discards_other_deployments_when_prefix_mismatch(self):
        """Other deployments from local_config are discarded when prefix doesn't match."""
        cm = _create_config_manager(prefix='acme', project_id='myapp', stage_id='dev')

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
        }
        # Parameter values have a different prefix than cm.prefix
        parameter_values = {'Prefix': 'other', 'ProjectId': 'myapp', 'StageId': 'dev'}
        local_config = {
            'deployments': {
                'prod': {
                    'deploy': {
                        'parameters': {'stack_name': 'acme-myapp-prod-pipeline'}
                    }
                }
            }
        }

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, [], local_config)

        # Only dev should be present (prod discarded due to prefix mismatch)
        assert 'dev' in config['deployments']
        assert 'prod' not in config['deployments']

    def test_default_capabilities_when_not_provided(self):
        """Capabilities defaults to CAPABILITY_NAMED_IAM when not in atlantis_params."""
        cm = _create_config_manager()

        atlantis_params = {
            's3_bucket': 'bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:role/role'
            # No 'capabilities' key
        }
        parameter_values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}

        config = cm.build_config_headless('pipeline', 's3://bucket/template.yml', atlantis_params, parameter_values, [], {})

        assert config['atlantis']['deploy']['parameters']['capabilities'] == 'CAPABILITY_NAMED_IAM'
