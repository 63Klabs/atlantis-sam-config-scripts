"""Unit tests for validate_atlantis_deploy_params() in cli/config.py.

Tests that the method validates s3_bucket, region, role_arn, and confirm_changeset
using the same rules as gather_atlantis_deploy_parameters() but without prompting,
returning a list of failure dicts.

Requirements: 7.4
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import ConfigManager


def _create_config_manager(regions=None):
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        cm.settings = {
            'regions': regions or [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
                'eu-west-1', 'eu-central-1', 'ap-southeast-1',
            ]
        }
        return cm


class TestValidateAtlantisDeployParamsValid:
    """Test valid inputs return empty failure list."""

    def test_all_valid_params_no_role(self):
        """Valid s3_bucket, region, confirm_changeset with no role_arn returns empty list."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'my-deploy-bucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        assert failures == []

    def test_all_valid_params_with_role(self):
        """Valid params including role_arn returns empty list."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'cf-deployments-bucket',
            'region': 'us-west-2',
            'confirm_changeset': 'false',
            'role_arn': 'arn:aws:iam::123456789012:role/my-deploy-role',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        assert failures == []

    def test_confirm_changeset_case_insensitive(self):
        """confirm_changeset validation is case-insensitive."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'True',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        assert failures == []

    def test_s3_bucket_with_hyphens(self):
        """S3 bucket with hyphens in the middle is valid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'my-deploy-bucket-123',
            'region': 'us-east-1',
            'confirm_changeset': 'false',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        assert failures == []

    def test_s3_bucket_minimum_length(self):
        """S3 bucket with exactly 3 characters is valid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'abc',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        assert failures == []


class TestValidateAtlantisDeployParamsS3Bucket:
    """Test s3_bucket validation failures."""

    def test_empty_s3_bucket(self):
        """Empty s3_bucket is reported as failure."""
        cm = _create_config_manager()
        params = {
            's3_bucket': '',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1
        assert 'required' in s3_failures[0]['reason'].lower() or 's3' in s3_failures[0]['reason'].lower()

    def test_s3_bucket_too_short(self):
        """S3 bucket shorter than 3 chars is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'ab',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1
        assert '3' in s3_failures[0]['reason'] and '63' in s3_failures[0]['reason']

    def test_s3_bucket_too_long(self):
        """S3 bucket longer than 63 chars is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'a' * 64,
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1

    def test_s3_bucket_uppercase(self):
        """S3 bucket with uppercase chars is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'MyBucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1
        assert 'lowercase' in s3_failures[0]['reason'].lower()

    def test_s3_bucket_invalid_chars(self):
        """S3 bucket with invalid characters is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'my_bucket.name',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1

    def test_s3_bucket_starts_with_hyphen(self):
        """S3 bucket starting with hyphen is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': '-mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1
        assert 'hyphen' in s3_failures[0]['reason'].lower()

    def test_s3_bucket_ends_with_hyphen(self):
        """S3 bucket ending with hyphen is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket-',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        s3_failures = [f for f in failures if f['parameter'] == 's3_bucket']
        assert len(s3_failures) == 1
        assert 'hyphen' in s3_failures[0]['reason'].lower()


class TestValidateAtlantisDeployParamsRegion:
    """Test region validation failures."""

    def test_invalid_region(self):
        """Region not in settings list is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'invalid-region-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        region_failures = [f for f in failures if f['parameter'] == 'region']
        assert len(region_failures) == 1
        assert region_failures[0]['value'] == 'invalid-region-1'

    def test_empty_region(self):
        """Empty region is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': '',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        region_failures = [f for f in failures if f['parameter'] == 'region']
        assert len(region_failures) == 1


class TestValidateAtlantisDeployParamsRoleArn:
    """Test role_arn validation failures."""

    def test_empty_role_arn(self):
        """Empty role_arn when key is present is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': '',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        role_failures = [f for f in failures if f['parameter'] == 'role_arn']
        assert len(role_failures) == 1

    def test_invalid_role_arn_format(self):
        """role_arn not matching IAM role ARN format is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'not-an-arn',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        role_failures = [f for f in failures if f['parameter'] == 'role_arn']
        assert len(role_failures) == 1
        assert 'arn:aws:iam' in role_failures[0]['reason']

    def test_role_arn_missing_role_path(self):
        """role_arn without :role/ segment is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
            'role_arn': 'arn:aws:iam::123456789012:user/my-user',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        role_failures = [f for f in failures if f['parameter'] == 'role_arn']
        assert len(role_failures) == 1

    def test_role_arn_not_validated_when_key_absent(self):
        """When role_arn key is not in params, no role_arn validation occurs."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        role_failures = [f for f in failures if f['parameter'] == 'role_arn']
        assert len(role_failures) == 0


class TestValidateAtlantisDeployParamsConfirmChangeset:
    """Test confirm_changeset validation failures."""

    def test_invalid_confirm_changeset(self):
        """confirm_changeset not 'true' or 'false' is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': 'yes',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        cs_failures = [f for f in failures if f['parameter'] == 'confirm_changeset']
        assert len(cs_failures) == 1
        assert 'true' in cs_failures[0]['reason'] and 'false' in cs_failures[0]['reason']

    def test_empty_confirm_changeset(self):
        """Empty confirm_changeset is invalid."""
        cm = _create_config_manager()
        params = {
            's3_bucket': 'mybucket',
            'region': 'us-east-1',
            'confirm_changeset': '',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        cs_failures = [f for f in failures if f['parameter'] == 'confirm_changeset']
        assert len(cs_failures) == 1


class TestValidateAtlantisDeployParamsMultipleFailures:
    """Test that multiple failures are collected."""

    def test_all_params_invalid(self):
        """When all params are invalid, all failures are reported."""
        cm = _create_config_manager()
        params = {
            's3_bucket': '-INVALID-',
            'region': 'invalid-region',
            'confirm_changeset': 'maybe',
            'role_arn': 'bad-arn',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        failed_params = [f['parameter'] for f in failures]
        # s3_bucket fails on uppercase check (first elif hit)
        assert 's3_bucket' in failed_params
        assert 'region' in failed_params
        assert 'confirm_changeset' in failed_params
        assert 'role_arn' in failed_params

    def test_failure_dict_has_required_keys(self):
        """Each failure dict has 'parameter', 'value', and 'reason' keys."""
        cm = _create_config_manager()
        params = {
            's3_bucket': '',
            'region': 'us-east-1',
            'confirm_changeset': 'true',
        }
        failures = cm.validate_atlantis_deploy_params(params)
        assert len(failures) == 1
        failure = failures[0]
        assert 'parameter' in failure
        assert 'value' in failure
        assert 'reason' in failure
        assert isinstance(failure['reason'], str)
        assert len(failure['reason']) > 0
