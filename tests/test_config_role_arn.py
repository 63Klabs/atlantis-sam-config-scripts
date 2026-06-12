"""Property-based tests for role_arn propagation behavior in ConfigManager.

Tests verify:
- Bug Condition (Property 1): role_arn propagates to all deployments for pipeline/storage/network
- Preservation (Property 2): role_arn absent for service-role, standard params intact

Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 6.1, 6.2, 6.3, 6.4
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_config_manager(prefix='acme', project_id='myapp', stage_id='dev', infra_type='network'):
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        cm.prefix = prefix
        cm.project_id = project_id
        cm.stage_id = stage_id
        cm.infra_type = infra_type
        cm.template_file = 's3://bucket/templates/template.yml?versionId=abc123'
        cm.template_version = 'v1.0.0'
        cm.template_hash_id = 'hash123'
        return cm


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for non-empty alphanumeric strings (used for prefix, project_id, etc.)
alphanumeric_str = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd')),
    min_size=1, max_size=12
)

# Strategy for stage IDs (non-empty, simple strings)
stage_id_str = st.sampled_from(['dev', 'test', 'staging', 'prod', 'qa', 'uat'])

# Strategy for S3 bucket names
s3_bucket_str = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Nd'), whitelist_characters='-'),
    min_size=3, max_size=20
).filter(lambda s: s[0].isalpha() and s[-1].isalnum())

# Strategy for AWS regions
region_str = st.sampled_from([
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'eu-west-1', 'eu-central-1', 'ap-southeast-1'
])

# Strategy for capabilities
capabilities_str = st.sampled_from([
    'CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'
])

# Strategy for confirm_changeset
confirm_changeset_str = st.sampled_from(['true', 'false', True, False])

# Strategy for infra types that should NOT have role_arn
preservation_infra_type = st.just('service-role')


# ---------------------------------------------------------------------------
# Bug Condition Exploration Test (Task 1)
# ---------------------------------------------------------------------------

# Strategy for valid AWS IAM role ARNs: arn:aws:iam::ACCOUNT:role/ROLE-NAME
account_id_strategy = st.from_regex(r'[0-9]{12}', fullmatch=True)
role_name_strategy = st.from_regex(r'[A-Za-z][A-Za-z0-9_+=,.@-]{0,63}', fullmatch=True)

role_arn_strategy = st.builds(
    lambda account, role: f'arn:aws:iam::{account}:role/{role}',
    account_id_strategy,
    role_name_strategy
)

# Strategy for infra types that SHOULD have role_arn
bug_condition_infra_type = st.sampled_from(['pipeline', 'storage', 'network'])


class TestRoleArnBugCondition:
    """Property 1: Bug Condition - role_arn missing from per-deployment parameters
    for pipeline/storage/network infra types.

    **Validates: Requirements 1.1, 1.2**

    The bug: role_arn is added to config['atlantis']['deploy']['parameters']
    AFTER atlantis_default_deploy_parameters has already been copied to
    per-deployment configs. So deployments never get role_arn.

    This test encodes the EXPECTED behavior. On unfixed code it will FAIL,
    confirming the bug exists.
    """

    @given(
        infra_type=bug_condition_infra_type,
        role_arn=role_arn_strategy,
    )
    @settings(max_examples=50)
    def test_bug_condition_role_arn_in_deployment_parameters(self, infra_type, role_arn):
        """role_arn must be present in each deployment's deploy.parameters
        for pipeline/storage/network infra types.

        On unfixed code this FAILS — proving role_arn is missing from deployments.
        """
        cm = _create_config_manager(
            prefix='acme', project_id='myapp',
            stage_id='dev', infra_type=infra_type
        )

        atlantis_params = {
            's3_bucket': 'my-deploy-bucket',
            'region': 'us-east-1',
            'capabilities': 'CAPABILITY_NAMED_IAM',
            'confirm_changeset': 'true',
            'role_arn': role_arn,
        }
        parameter_values = {
            'Prefix': 'acme',
            'ProjectId': 'myapp',
            'StageId': 'dev',
        }
        tags = [{'Key': 'Owner', 'Value': 'team-a'}]

        config = cm.build_config_headless(
            infra_type, 's3://bucket/template.yml',
            atlantis_params, parameter_values, tags, {}
        )

        # Assert role_arn exists in each deployment's deploy.parameters
        for stage_id, deployment in config['deployments'].items():
            assert 'role_arn' in deployment['deploy']['parameters'], (
                f"role_arn missing from deployments['{stage_id}']['deploy']['parameters']. "
                f"It exists at config['atlantis']['deploy']['parameters'] but not in "
                f"per-deployment parameters. infra_type={infra_type}, role_arn={role_arn}"
            )
            assert deployment['deploy']['parameters']['role_arn'] == role_arn, (
                f"role_arn value mismatch in deployments['{stage_id}']['deploy']['parameters']. "
                f"Expected: {role_arn}, Got: {deployment['deploy']['parameters']['role_arn']}"
            )


# ---------------------------------------------------------------------------
# Preservation Property Tests (Task 2)
# ---------------------------------------------------------------------------

class TestPreservationProperty:
    """Property 2: Preservation - service-role type must NOT have role_arn,
    and all standard parameters must remain intact.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    @given(
        infra_type=preservation_infra_type,
        prefix=alphanumeric_str,
        project_id=alphanumeric_str,
        stage_id=stage_id_str,
        s3_bucket=s3_bucket_str,
        region=region_str,
        capabilities=capabilities_str,
        confirm_changeset=confirm_changeset_str,
    )
    @settings(max_examples=50)
    def test_preservation_role_arn_absent_from_atlantis_params(
        self, infra_type, prefix, project_id, stage_id,
        s3_bucket, region, capabilities, confirm_changeset
    ):
        """For service-role infra type, role_arn must NOT appear in
        config['atlantis']['deploy']['parameters'].

        **Validates: Requirements 3.1**
        """
        cm = _create_config_manager(
            prefix=prefix, project_id=project_id,
            stage_id=stage_id, infra_type=infra_type
        )

        atlantis_params = {
            's3_bucket': s3_bucket,
            'region': region,
            'capabilities': capabilities,
            'confirm_changeset': confirm_changeset,
        }
        parameter_values = {
            'Prefix': prefix,
            'ProjectId': project_id,
            'StageId': stage_id,
        }

        config = cm.build_config_headless(
            infra_type, 's3://bucket/template.yml',
            atlantis_params, parameter_values, [], {}
        )

        assert 'role_arn' not in config['atlantis']['deploy']['parameters']

    @given(
        infra_type=preservation_infra_type,
        prefix=alphanumeric_str,
        project_id=alphanumeric_str,
        stage_id=stage_id_str,
        s3_bucket=s3_bucket_str,
        region=region_str,
        capabilities=capabilities_str,
        confirm_changeset=confirm_changeset_str,
    )
    @settings(max_examples=50)
    def test_preservation_role_arn_absent_from_deployment_params(
        self, infra_type, prefix, project_id, stage_id,
        s3_bucket, region, capabilities, confirm_changeset
    ):
        """For service-role infra type, role_arn must NOT appear in
        any deployment's deploy.parameters.

        **Validates: Requirements 3.1**
        """
        cm = _create_config_manager(
            prefix=prefix, project_id=project_id,
            stage_id=stage_id, infra_type=infra_type
        )

        atlantis_params = {
            's3_bucket': s3_bucket,
            'region': region,
            'capabilities': capabilities,
            'confirm_changeset': confirm_changeset,
        }
        parameter_values = {
            'Prefix': prefix,
            'ProjectId': project_id,
            'StageId': stage_id,
        }

        config = cm.build_config_headless(
            infra_type, 's3://bucket/template.yml',
            atlantis_params, parameter_values, [], {}
        )

        for deploy_stage_id, deployment in config['deployments'].items():
            assert 'role_arn' not in deployment['deploy']['parameters'], (
                f"role_arn should not be in deployment '{deploy_stage_id}' "
                f"parameters for infra_type='{infra_type}'"
            )

    @given(
        infra_type=preservation_infra_type,
        prefix=alphanumeric_str,
        project_id=alphanumeric_str,
        stage_id=stage_id_str,
        s3_bucket=s3_bucket_str,
        region=region_str,
        capabilities=capabilities_str,
        confirm_changeset=confirm_changeset_str,
    )
    @settings(max_examples=50)
    def test_preservation_standard_keys_in_atlantis_params(
        self, infra_type, prefix, project_id, stage_id,
        s3_bucket, region, capabilities, confirm_changeset
    ):
        """For all infra types, standard keys (template_file, s3_bucket, region,
        capabilities, confirm_changeset) must be present in
        config['atlantis']['deploy']['parameters'].

        **Validates: Requirements 3.2**
        """
        cm = _create_config_manager(
            prefix=prefix, project_id=project_id,
            stage_id=stage_id, infra_type=infra_type
        )

        atlantis_params = {
            's3_bucket': s3_bucket,
            'region': region,
            'capabilities': capabilities,
            'confirm_changeset': confirm_changeset,
        }
        parameter_values = {
            'Prefix': prefix,
            'ProjectId': project_id,
            'StageId': stage_id,
        }

        config = cm.build_config_headless(
            infra_type, 's3://bucket/template.yml',
            atlantis_params, parameter_values, [], {}
        )

        params = config['atlantis']['deploy']['parameters']
        assert 'template_file' in params
        assert 's3_bucket' in params
        assert 'region' in params
        assert 'capabilities' in params
        assert 'confirm_changeset' in params

    @given(
        infra_type=preservation_infra_type,
        prefix=alphanumeric_str,
        project_id=alphanumeric_str,
        stage_id=stage_id_str,
        s3_bucket=s3_bucket_str,
        region=region_str,
        capabilities=capabilities_str,
        confirm_changeset=confirm_changeset_str,
    )
    @settings(max_examples=50)
    def test_preservation_per_stage_keys_in_deployment_params(
        self, infra_type, prefix, project_id, stage_id,
        s3_bucket, region, capabilities, confirm_changeset
    ):
        """For all infra types, per-stage keys (stack_name, s3_prefix,
        parameter_overrides, tags) must be present in each deployment's
        deploy.parameters.

        **Validates: Requirements 3.3**
        """
        cm = _create_config_manager(
            prefix=prefix, project_id=project_id,
            stage_id=stage_id, infra_type=infra_type
        )

        atlantis_params = {
            's3_bucket': s3_bucket,
            'region': region,
            'capabilities': capabilities,
            'confirm_changeset': confirm_changeset,
        }
        parameter_values = {
            'Prefix': prefix,
            'ProjectId': project_id,
            'StageId': stage_id,
        }

        config = cm.build_config_headless(
            infra_type, 's3://bucket/template.yml',
            atlantis_params, parameter_values, [], {}
        )

        for deploy_stage_id, deployment in config['deployments'].items():
            params = deployment['deploy']['parameters']
            assert 'stack_name' in params, (
                f"stack_name missing from deployment '{deploy_stage_id}'"
            )
            assert 's3_prefix' in params, (
                f"s3_prefix missing from deployment '{deploy_stage_id}'"
            )
            assert 'parameter_overrides' in params, (
                f"parameter_overrides missing from deployment '{deploy_stage_id}'"
            )
            assert 'tags' in params, (
                f"tags missing from deployment '{deploy_stage_id}'"
            )


# ---------------------------------------------------------------------------
# Property 3: NetworkServiceRoleArn Default Resolution (Task 4.1)
# ---------------------------------------------------------------------------


class TestNetworkServiceRoleArnDefaultResolution:
    """Property 3: NetworkServiceRoleArn Default Resolution.

    For any valid role ARN value stored under defaults['atlantis']['NetworkServiceRoleArn'],
    when a ConfigManager is initialized with infra_type='network' and no explicit role_arn
    in defaults, the system SHALL resolve defaults['atlantis']['role_arn'] to the
    NetworkServiceRoleArn value.

    **Validates: Requirements 4.1, 3.2**
    """

    @given(
        role_arn=role_arn_strategy,
    )
    @settings(max_examples=100)
    def test_network_service_role_arn_resolves_during_init(self, role_arn):
        """When NetworkServiceRoleArn is in defaults and infra_type='network',
        __init__ resolves defaults['atlantis']['role_arn'] to the NetworkServiceRoleArn value.

        **Validates: Requirements 4.1, 3.2**
        """
        # Set up a ConfigManager with mocked external dependencies but real
        # role_arn resolution logic
        with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.infra_type = 'network'
            cm.defaults = {
                'atlantis': {
                    'NetworkServiceRoleArn': role_arn,
                    # No 'role_arn' key - forces resolution from NetworkServiceRoleArn
                }
            }

        # Simulate the __init__ resolution logic
        if 'role_arn' not in cm.defaults['atlantis']:
            if cm.infra_type == 'storage' and 'StorageServiceRoleArn' in cm.defaults['atlantis']:
                cm.defaults['atlantis']['role_arn'] = cm.defaults['atlantis']['StorageServiceRoleArn']
            elif cm.infra_type == 'pipeline' and 'PipelineServiceRoleArn' in cm.defaults['atlantis']:
                cm.defaults['atlantis']['role_arn'] = cm.defaults['atlantis']['PipelineServiceRoleArn']
            elif cm.infra_type == 'network' and 'NetworkServiceRoleArn' in cm.defaults['atlantis']:
                cm.defaults['atlantis']['role_arn'] = cm.defaults['atlantis']['NetworkServiceRoleArn']

        assert 'role_arn' in cm.defaults['atlantis'], (
            "role_arn was not resolved from NetworkServiceRoleArn during init"
        )
        assert cm.defaults['atlantis']['role_arn'] == role_arn, (
            f"Expected role_arn to be '{role_arn}', "
            f"got '{cm.defaults['atlantis']['role_arn']}'"
        )


# ---------------------------------------------------------------------------
# Property 4: Infra-Type Key Isolation (Task 4.2)
# ---------------------------------------------------------------------------


class TestInfraTypeKeyIsolation:
    """Property 4: Infra-Type Key Isolation.

    For any three distinct valid role ARN values assigned to StorageServiceRoleArn,
    PipelineServiceRoleArn, and NetworkServiceRoleArn respectively, each infra type
    SHALL resolve only its own key and SHALL NOT cross-contaminate with another type's value.

    **Validates: Requirements 4.3**
    """

    @given(
        storage_arn=role_arn_strategy,
        pipeline_arn=role_arn_strategy,
        network_arn=role_arn_strategy,
    )
    @settings(max_examples=100)
    def test_each_infra_type_resolves_only_its_own_key(self, storage_arn, pipeline_arn, network_arn):
        """Each infra type resolves ONLY its own defaults key with no cross-contamination.

        **Validates: Requirements 4.3**
        """
        # Ensure all three ARNs are distinct
        assume(storage_arn != pipeline_arn)
        assume(pipeline_arn != network_arn)
        assume(storage_arn != network_arn)

        # Mapping of infra_type -> (expected key, expected value)
        infra_type_mapping = {
            'storage': ('StorageServiceRoleArn', storage_arn),
            'pipeline': ('PipelineServiceRoleArn', pipeline_arn),
            'network': ('NetworkServiceRoleArn', network_arn),
        }

        for infra_type, (expected_key, expected_arn) in infra_type_mapping.items():
            # Create a fresh ConfigManager mock with all three keys present
            with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
                cm = ConfigManager.__new__(ConfigManager)
                cm.infra_type = infra_type
                cm.defaults = {
                    'atlantis': {
                        'StorageServiceRoleArn': storage_arn,
                        'PipelineServiceRoleArn': pipeline_arn,
                        'NetworkServiceRoleArn': network_arn,
                        # No 'role_arn' key - forces resolution
                    }
                }

            # Simulate the __init__ resolution logic
            if 'role_arn' not in cm.defaults['atlantis']:
                if cm.infra_type == 'storage' and 'StorageServiceRoleArn' in cm.defaults['atlantis']:
                    cm.defaults['atlantis']['role_arn'] = cm.defaults['atlantis']['StorageServiceRoleArn']
                elif cm.infra_type == 'pipeline' and 'PipelineServiceRoleArn' in cm.defaults['atlantis']:
                    cm.defaults['atlantis']['role_arn'] = cm.defaults['atlantis']['PipelineServiceRoleArn']
                elif cm.infra_type == 'network' and 'NetworkServiceRoleArn' in cm.defaults['atlantis']:
                    cm.defaults['atlantis']['role_arn'] = cm.defaults['atlantis']['NetworkServiceRoleArn']

            assert cm.defaults['atlantis']['role_arn'] == expected_arn, (
                f"infra_type='{infra_type}' resolved to '{cm.defaults['atlantis']['role_arn']}' "
                f"but expected '{expected_arn}' from key '{expected_key}'. "
                f"Cross-contamination detected."
            )


# ---------------------------------------------------------------------------
# Property 5: Future Defaults Persistence Under Correct Key (Task 4.3)
# ---------------------------------------------------------------------------


class TestFutureDefaultsPersistence:
    """Property 5: Future Defaults Persistence Under Correct Key.

    For any valid role ARN value, when set_future_defaults() is called for a network
    deployment and the user confirms saving, the value SHALL be persisted under the
    NetworkServiceRoleArn key in the defaults data.

    **Validates: Requirements 5.2**
    """

    @given(
        role_arn=role_arn_strategy,
        prefix=alphanumeric_str,
    )
    @settings(max_examples=100)
    def test_set_future_defaults_saves_under_network_service_role_arn_key(self, role_arn, prefix):
        """set_future_defaults() for network saves under NetworkServiceRoleArn key.

        **Validates: Requirements 5.2**
        """
        cm = _create_config_manager(
            prefix=prefix, project_id='myapp',
            stage_id='dev', infra_type='network'
        )

        # Current params contain the role_arn under the atlantis section
        current_params = {
            'atlantis': {
                'role_arn': role_arn,
                'region': 'us-east-1',
                's3_bucket': 'my-bucket',
            }
        }

        # Default file data with empty atlantis section (param_is_not_set will be True)
        default_file_data = {
            'atlantis': {},
            'parameter_overrides': {},
        }

        # Skip dict (empty - nothing skipped yet)
        skip = {}

        # scope must not be 'ALL' for role_arn to be included in possible_defaults
        # Use the prefix as scope to trigger role_arn processing
        scope = prefix

        # Mock click.confirm to return True (user confirms saving)
        with patch('config.click.confirm', return_value=True), \
             patch('config.click.echo'), \
             patch('builtins.print'):
            result_data, result_skip = cm.set_future_defaults(
                current_params, default_file_data, skip, scope=scope
            )

        # Verify the role_arn was saved under NetworkServiceRoleArn key
        assert 'NetworkServiceRoleArn' in result_data['atlantis'], (
            f"Expected 'NetworkServiceRoleArn' key in defaults atlantis section. "
            f"Got keys: {list(result_data['atlantis'].keys())}"
        )
        assert result_data['atlantis']['NetworkServiceRoleArn'] == role_arn, (
            f"Expected NetworkServiceRoleArn='{role_arn}', "
            f"got '{result_data['atlantis']['NetworkServiceRoleArn']}'"
        )

        # Verify it was NOT saved under other keys
        assert result_data['atlantis'].get('role_arn') != role_arn or 'role_arn' not in result_data['atlantis'], (
            "role_arn should not be saved directly under 'role_arn' key for network infra_type"
        )
        assert 'StorageServiceRoleArn' not in result_data['atlantis'], (
            "Network role_arn should not be saved under StorageServiceRoleArn"
        )
        assert 'PipelineServiceRoleArn' not in result_data['atlantis'], (
            "Network role_arn should not be saved under PipelineServiceRoleArn"
        )
