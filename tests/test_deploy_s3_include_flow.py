"""Integration tests for deploy_with_temp_template() routing logic.

Tests the two-path routing: direct sam deploy vs. sam package + sam deploy.
All AWS calls, subprocess invocations, and helper methods are mocked.

Requirements: FR1, FR4, FR7 (from requirements.md)
"""

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Add cli/ to path so deploy.py can resolve its relative imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from deploy import TemplateDeployer

MINIMAL_TEMPLATE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
"""

MINIMAL_SAMCONFIG = """\
[default.deploy.parameters]
stack_name = "test-stack"
"""


def make_deployer_for_flow(tmp_path):
    """Create a TemplateDeployer with all attributes needed for deploy_with_temp_template.

    Args:
        tmp_path: pytest tmp_path fixture for creating real files.

    Returns:
        Tuple of (deployer, config_path) where config_path is the samconfig file.
    """
    config_file = tmp_path / 'samconfig.toml'
    config_file.write_text(MINIMAL_SAMCONFIG)

    with patch.object(TemplateDeployer, '__init__', return_value=None):
        deployer = TemplateDeployer.__new__(TemplateDeployer)
        deployer.stage_id = 'default'
        deployer.profile = None
        deployer.settings = {}
        deployer.override_confirm_changeset = False
        deployer.s3_client = MagicMock()
        deployer.s3_client_anonymous = MagicMock()
        deployer.get_samconfig_file_path = lambda: config_file
        deployer.get_samconfig_dir = lambda: tmp_path
        deployer.infra_type = 'pipeline'
        deployer.prefix = 'acme'
        deployer.project_id = 'myapp'

    return deployer, config_file


class TestDeployWithTempTemplateS3Routing:
    """Integration tests for deploy_with_temp_template() S3 template routing."""

    def _setup_s3_download(self, deployer, template_content=MINIMAL_TEMPLATE):
        """Configure mock S3 client to return template content on get_object.

        Args:
            deployer: The TemplateDeployer instance to configure.
            template_content: YAML string to return from the mock S3 download.
        """
        mock_body = MagicMock()
        mock_body.read.return_value = template_content.encode('utf-8')
        deployer.s3_client.get_object.return_value = {'Body': mock_body}

    def test_s3_template_without_includes_goes_direct(self, tmp_path):
        """S3 template without S3 includes calls _run_sam_deploy directly."""
        deployer, _ = make_deployer_for_flow(tmp_path)
        self._setup_s3_download(deployer)

        with patch.object(deployer, 'verify_s3_object_exists', return_value=True):
            with patch.object(deployer, 'is_bucket_public', return_value=False):
                with patch.object(deployer, '_has_s3_includes', return_value=False):
                    with patch.object(deployer, '_run_sam_deploy', return_value=0) as mock_deploy:
                        with patch.object(deployer, '_run_sam_package') as mock_package:
                            with patch('deploy.ConsoleAndLog'):
                                result = deployer.deploy_with_temp_template(
                                    's3://my-bucket/templates/pipeline.yml'
                                )

        assert result == 0
        mock_deploy.assert_called_once()
        mock_package.assert_not_called()

    def test_s3_template_with_includes_uses_package_flow(self, tmp_path):
        """S3 template with S3 includes routes through prepare+package+deploy."""
        deployer, _ = make_deployer_for_flow(tmp_path)
        self._setup_s3_download(deployer)

        rewritten_path = tmp_path / 'template-rewritten.yml'
        rewritten_path.write_text(MINIMAL_TEMPLATE)

        with patch.object(deployer, 'verify_s3_object_exists', return_value=True):
            with patch.object(deployer, 'is_bucket_public', return_value=False):
                with patch.object(deployer, '_has_s3_includes', return_value=True):
                    with patch.object(
                        deployer, '_prepare_template_with_s3_includes',
                        return_value=rewritten_path
                    ) as mock_prepare:
                        with patch.object(
                            deployer, '_read_artifact_bucket_config',
                            return_value=('artifact-bucket', 'artifact-prefix')
                        ):
                            with patch.object(deployer, '_run_sam_package', return_value=0):
                                with patch.object(
                                    deployer, '_run_sam_deploy', return_value=0
                                ) as mock_deploy:
                                    with patch('deploy.ConsoleAndLog'):
                                        result = deployer.deploy_with_temp_template(
                                            's3://my-bucket/templates/pipeline.yml'
                                        )

        assert result == 0
        mock_prepare.assert_called_once()
        mock_deploy.assert_called_once()

    def test_s3_template_package_failure_returns_nonzero(self, tmp_path):
        """When sam package fails, sam deploy is not called and non-zero code is returned."""
        deployer, _ = make_deployer_for_flow(tmp_path)
        self._setup_s3_download(deployer)

        rewritten_path = tmp_path / 'template-rewritten.yml'
        rewritten_path.write_text(MINIMAL_TEMPLATE)

        with patch.object(deployer, 'verify_s3_object_exists', return_value=True):
            with patch.object(deployer, 'is_bucket_public', return_value=False):
                with patch.object(deployer, '_has_s3_includes', return_value=True):
                    with patch.object(
                        deployer, '_prepare_template_with_s3_includes',
                        return_value=rewritten_path
                    ):
                        with patch.object(
                            deployer, '_read_artifact_bucket_config',
                            return_value=('artifact-bucket', 'artifact-prefix')
                        ):
                            with patch.object(deployer, '_run_sam_package', return_value=2):
                                with patch.object(
                                    deployer, '_run_sam_deploy'
                                ) as mock_deploy:
                                    with patch('deploy.ConsoleAndLog'):
                                        result = deployer.deploy_with_temp_template(
                                            's3://my-bucket/templates/pipeline.yml'
                                        )

        assert result == 2
        mock_deploy.assert_not_called()

    def test_s3_template_prepare_error_returns_1(self, tmp_path):
        """When _prepare_template_with_s3_includes raises ValueError, returns 1."""
        deployer, _ = make_deployer_for_flow(tmp_path)
        self._setup_s3_download(deployer)

        with patch.object(deployer, 'verify_s3_object_exists', return_value=True):
            with patch.object(deployer, 'is_bucket_public', return_value=False):
                with patch.object(deployer, '_has_s3_includes', return_value=True):
                    with patch.object(
                        deployer, '_prepare_template_with_s3_includes',
                        side_effect=ValueError('module download failed')
                    ):
                        with patch.object(deployer, '_run_sam_package') as mock_package:
                            with patch.object(deployer, '_run_sam_deploy') as mock_deploy:
                                with patch('deploy.ConsoleAndLog'):
                                    result = deployer.deploy_with_temp_template(
                                        's3://my-bucket/templates/pipeline.yml'
                                    )

        assert result == 1
        mock_package.assert_not_called()
        mock_deploy.assert_not_called()


class TestDeployWithTempTemplateLocalRouting:
    """Integration tests for deploy_with_temp_template() local template routing."""

    def test_local_template_without_includes_goes_direct(self, tmp_path):
        """Local template without S3 includes calls _run_sam_deploy directly."""
        deployer, _ = make_deployer_for_flow(tmp_path)

        # Create a real local template file in the deployer's samconfig dir
        local_template = tmp_path / 'template.yml'
        local_template.write_text(MINIMAL_TEMPLATE)

        with patch.object(deployer, '_has_s3_includes', return_value=False):
            with patch.object(deployer, '_run_sam_deploy', return_value=0) as mock_deploy:
                with patch.object(deployer, '_run_sam_package') as mock_package:
                    with patch('deploy.ConsoleAndLog'):
                        result = deployer.deploy_with_temp_template('template.yml')

        assert result == 0
        mock_deploy.assert_called_once()
        mock_package.assert_not_called()

    def test_local_template_with_includes_uses_package_flow(self, tmp_path):
        """Local template with S3 includes opens temp dir and runs package+deploy."""
        deployer, _ = make_deployer_for_flow(tmp_path)

        # Create a real local template file in the deployer's samconfig dir
        local_template = tmp_path / 'template.yml'
        local_template.write_text(MINIMAL_TEMPLATE)

        # Use a side_effect to create the rewritten file dynamically inside
        # whatever temp dir the method creates at runtime.
        def fake_prepare(template_path, temp_dir):
            """Write a rewritten template to temp_dir and return its path."""
            rewritten = temp_dir / 'template-rewritten.yml'
            rewritten.write_text(MINIMAL_TEMPLATE)
            return rewritten

        with patch.object(deployer, '_has_s3_includes', return_value=True):
            with patch.object(
                deployer, '_prepare_template_with_s3_includes',
                side_effect=fake_prepare
            ) as mock_prepare:
                with patch.object(
                    deployer, '_read_artifact_bucket_config',
                    return_value=('artifact-bucket', 'artifact-prefix')
                ):
                    with patch.object(
                        deployer, '_run_sam_package', return_value=0
                    ) as mock_package:
                        with patch.object(
                            deployer, '_run_sam_deploy', return_value=0
                        ) as mock_deploy:
                            with patch('deploy.ConsoleAndLog'):
                                result = deployer.deploy_with_temp_template('template.yml')

        assert result == 0
        mock_prepare.assert_called_once()
        mock_package.assert_called_once()
        mock_deploy.assert_called_once()
