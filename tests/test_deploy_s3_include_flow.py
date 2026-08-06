"""Integration tests for deploy_with_temp_template() routing logic.

Tests the two-path routing: direct sam deploy vs. resolve S3 includes +
CloudFormation deploy. All AWS calls, subprocess invocations, and helper
methods are mocked.

Also contains property-based preservation tests (Property 2) that verify
_has_s3_includes() returns True for all plain YAML templates (no CF short-form
tags) that contain at least one Fn::Transform: AWS::Include with an S3 Location.

Requirements: FR1, FR4, FR7 (from requirements.md)
"""

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
                        with patch.object(deployer, '_resolve_template_includes') as mock_resolve:
                            with patch('deploy.ConsoleAndLog'):
                                result = deployer.deploy_with_temp_template(
                                    's3://my-bucket/templates/pipeline.yml'
                                )

        assert result == 0
        mock_deploy.assert_called_once()
        mock_resolve.assert_not_called()

    def test_s3_template_with_includes_uses_resolve_flow(self, tmp_path):
        """S3 template with S3 includes routes through resolve + CloudFormation deploy."""
        deployer, _ = make_deployer_for_flow(tmp_path)
        self._setup_s3_download(deployer)

        default_deploy_params = {
            'stack_name': 'test-stack',
            'capabilities': 'CAPABILITY_NAMED_IAM',
            'region': 'us-east-1',
            'role_arn': '',
            'confirm_changeset': True,
            'parameter_overrides': '',
            'tags': '',
        }

        with patch.object(deployer, 'verify_s3_object_exists', return_value=True):
            with patch.object(deployer, 'is_bucket_public', return_value=False):
                with patch.object(deployer, '_has_s3_includes', return_value=True):
                    with patch.object(
                        deployer, '_resolve_template_includes',
                        return_value=Path('/tmp/resolved/template-resolved.yml'),
                    ) as mock_resolve:
                        with patch.object(
                            deployer,
                            '_read_deploy_params_for_packaged',
                            return_value=default_deploy_params,
                        ):
                            with patch.object(
                                deployer,
                                '_cfn_deploy_packaged',
                                return_value=0,
                            ) as mock_deploy_packaged:
                                with patch('deploy.ConsoleAndLog'):
                                    result = deployer.deploy_with_temp_template(
                                        's3://my-bucket/templates/pipeline.yml'
                                    )

        assert result == 0
        mock_resolve.assert_called_once()
        mock_deploy_packaged.assert_called_once()

    def test_s3_template_resolve_error_returns_1(self, tmp_path):
        """When _resolve_template_includes raises ValueError, CloudFormation deploy is not called and 1 is returned."""
        deployer, _ = make_deployer_for_flow(tmp_path)
        self._setup_s3_download(deployer)

        with patch.object(deployer, 'verify_s3_object_exists', return_value=True):
            with patch.object(deployer, 'is_bucket_public', return_value=False):
                with patch.object(deployer, '_has_s3_includes', return_value=True):
                    with patch.object(
                        deployer, '_resolve_template_includes',
                        side_effect=ValueError('missing param')
                    ):
                        with patch.object(
                            deployer, '_cfn_deploy_packaged'
                        ) as mock_deploy_packaged:
                            with patch('deploy.ConsoleAndLog'):
                                result = deployer.deploy_with_temp_template(
                                    's3://my-bucket/templates/pipeline.yml'
                                )

        assert result == 1
        mock_deploy_packaged.assert_not_called()


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
                with patch.object(deployer, '_resolve_template_includes') as mock_resolve:
                    with patch('deploy.ConsoleAndLog'):
                        result = deployer.deploy_with_temp_template('template.yml')

        assert result == 0
        mock_deploy.assert_called_once()
        mock_resolve.assert_not_called()

    def test_local_template_with_includes_uses_resolve_flow(self, tmp_path):
        """Local template with S3 includes opens temp dir and runs resolve+deploy."""
        deployer, _ = make_deployer_for_flow(tmp_path)

        # Create a real local template file in the deployer's samconfig dir
        local_template = tmp_path / 'template.yml'
        local_template.write_text(MINIMAL_TEMPLATE)

        default_deploy_params = {
            'stack_name': 'test-stack',
            'capabilities': 'CAPABILITY_NAMED_IAM',
            'region': 'us-east-1',
            'role_arn': '',
            'confirm_changeset': True,
            'parameter_overrides': '',
            'tags': '',
        }

        with patch.object(deployer, '_has_s3_includes', return_value=True):
            with patch.object(
                deployer, '_resolve_template_includes',
                return_value=Path('/tmp/resolved/template-resolved.yml'),
            ) as mock_resolve:
                with patch.object(
                    deployer,
                    '_read_deploy_params_for_packaged',
                    return_value=default_deploy_params,
                ):
                    with patch.object(
                        deployer,
                        '_cfn_deploy_packaged',
                        return_value=0,
                    ) as mock_deploy_packaged:
                        with patch('deploy.ConsoleAndLog'):
                            result = deployer.deploy_with_temp_template('template.yml')

        assert result == 0
        mock_resolve.assert_called_once()
        mock_deploy_packaged.assert_called_once()


# =============================================================================
# Property-based preservation tests for _has_s3_includes()
# =============================================================================

# Strategy helpers: build safe YAML resource names and S3 URLs.
# These generators deliberately exclude any character that would introduce
# a CF short-form tag (the '!' sigil) so that the generated templates are
# valid plain YAML parseable by yaml.safe_load as well as _CfnLoader.

_safe_resource_name = st.from_regex(r'[A-Z][A-Za-z0-9]{3,15}', fullmatch=True)
_safe_bucket_name = st.from_regex(r'[a-z][a-z0-9\-]{4,20}[a-z0-9]', fullmatch=True)
_safe_key_path = st.from_regex(r'[a-z][a-z0-9/\-]{4,30}\.yml', fullmatch=True)


def _make_s3_include_template(resource_names: list, s3_urls: list) -> str:
    """Build a plain YAML CloudFormation template with Fn::Transform AWS::Include entries.

    The generated template contains no CloudFormation short-form YAML tags
    (no !Sub, !Ref, etc.) so it is parseable by both yaml.safe_load and
    _CfnLoader. Each resource in resource_names is paired with an S3 URL
    from s3_urls and rendered as an Fn::Transform: AWS::Include block.

    Args:
        resource_names: List of CloudFormation logical resource name strings.
        s3_urls: List of S3 URL strings, one per resource.

    Returns:
        A YAML string for a CloudFormation template with S3 includes.
    """
    lines = ["AWSTemplateFormatVersion: '2010-09-09'", "Resources:"]
    for name, url in zip(resource_names, s3_urls):
        lines += [
            f"  {name}:",
            "    Fn::Transform:",
            "      Name: AWS::Include",
            "      Parameters:",
            f"        Location: {url}",
        ]
    return "\n".join(lines) + "\n"


@st.composite
def _s3_include_template_strategy(draw) -> tuple:
    """Hypothesis strategy that produces (template_str, s3_url_count) pairs.

    Generates plain YAML templates (no CF short-form tags) that contain
    between 1 and 4 Fn::Transform: AWS::Include entries with S3 Locations.
    This exercises the preservation property: _has_s3_includes() must return
    True for all such inputs, both before and after the fix.

    Args:
        draw: Hypothesis draw function for sampling from strategies.

    Returns:
        Tuple of (yaml_template_str, number_of_s3_includes).
    """
    count = draw(st.integers(min_value=1, max_value=4))
    resource_names = draw(
        st.lists(_safe_resource_name, min_size=count, max_size=count, unique=True)
    )
    bucket_names = draw(st.lists(_safe_bucket_name, min_size=count, max_size=count))
    key_paths = draw(st.lists(_safe_key_path, min_size=count, max_size=count))
    s3_urls = [
        f"s3://{bucket}/{key}"
        for bucket, key in zip(bucket_names, key_paths)
    ]
    template_str = _make_s3_include_template(resource_names, s3_urls)
    return template_str, count


class TestHasS3IncludesPreservationProperty:
    """Property-based preservation tests for _has_s3_includes().

    These tests establish the baseline behaviour on non-bug-condition inputs:
    plain YAML templates (no CF short-form tags) with S3 AWS::Include entries
    must continue to return True after the fix is applied.

    Validates: Requirements 3.1
    """

    @given(template_and_count=_s3_include_template_strategy())
    @settings(max_examples=50)
    def test_plain_yaml_with_s3_includes_always_returns_true(
        self, template_and_count: tuple
    ):
        """Plain YAML templates with S3 includes return True for all generated inputs.

        Property 2: Preservation — for all X where isBugCondition(X) is False
        (no CF short-form tags) and X contains at least one S3 AWS::Include,
        _has_s3_includes(X) must return True.

        This test runs on UNFIXED code to confirm the baseline behaviour is
        correct and will remain correct after the fix.

        A temporary directory context manager is used instead of the tmp_path
        fixture to avoid Hypothesis FailedHealthCheck for function-scoped
        fixtures shared across generated inputs.

        Validates: Requirements 3.1

        Args:
            template_and_count: Tuple of (yaml_str, include_count) from strategy.
        """
        template_str, _count = template_and_count

        with patch.object(TemplateDeployer, '__init__', return_value=None):
            deployer = TemplateDeployer.__new__(TemplateDeployer)
            deployer.stage_id = 'default'
            deployer.profile = None
            deployer.settings = {}
            deployer.s3_client = MagicMock()
            deployer.s3_client_anonymous = MagicMock()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmpl = Path(tmp_dir) / 'template.yml'
            tmpl.write_text(template_str)

            result = deployer._has_s3_includes(tmpl)

        assert result is True, (
            f"_has_s3_includes() returned {result!r} for a plain YAML template "
            f"(no CF tags) with {_count} S3 include(s).\n"
            f"Template:\n{template_str}"
        )


# =============================================================================
# End-to-end routing integration test — CF tags + S3 includes
# =============================================================================

S3_INCLUDE_TEMPLATE_WITH_CF_TAGS = """\
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  Env:
    Type: String
Resources:
  MyRole:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub my-bucket-${Env}
"""


class TestDeployS3IncludeFlow:
    """End-to-end routing integration tests for CF-tag templates with S3 includes.

    Validates that a CloudFormation template containing short-form CF tags
    (e.g. ``!Sub``) alongside ``Fn::Transform: AWS::Include`` with an S3
    ``Location`` is correctly detected by ``_has_s3_includes()`` and would
    therefore be routed through the resolve + CloudFormation deploy path.

    Requirements: 2.1, 2.2
    """

    def test_cf_tags_with_s3_include_routes_to_resolve_and_deploy(
        self, tmp_path
    ):
        """CF-tag template with S3 include is detected and routed via resolve + CloudFormation deploy.

        Writes ``S3_INCLUDE_TEMPLATE_WITH_CF_TAGS`` to a tmp file, then:

        1. Asserts that ``_has_s3_includes()`` returns ``True`` — confirming
           the fix is in place and the routing condition evaluates correctly.
        2. Validates (via patched helpers) that calling
           ``deploy_with_temp_template()`` with this template exercises the
           resolve + CloudFormation deploy route, not the direct
           ``_run_sam_deploy`` short-circuit.

        All AWS calls, subprocess invocations, and I/O helpers are mocked so
        the test is fully self-contained.

        Args:
            tmp_path: pytest tmp_path fixture providing a temporary directory.
        """
        deployer, _ = make_deployer_for_flow(tmp_path)

        # Write the CF-tag template to a real file so _has_s3_includes() can
        # open and parse it.
        tmp_template = tmp_path / 'template-cf-tags.yml'
        tmp_template.write_text(S3_INCLUDE_TEMPLATE_WITH_CF_TAGS)

        # --- Step 1: confirm _has_s3_includes() returns True for the fixed code ---
        assert deployer._has_s3_includes(tmp_template) is True, (
            "_has_s3_includes() returned False for a template with !Sub + "
            "Fn::Transform AWS::Include — the fix may not be active."
        )

        # --- Step 2: validate routing logic via deploy_with_temp_template() ---
        default_deploy_params = {
            'stack_name': 'test-stack',
            'capabilities': 'CAPABILITY_NAMED_IAM',
            'region': 'us-east-1',
            'role_arn': '',
            'confirm_changeset': True,
            'parameter_overrides': '',
            'tags': '',
        }

        with patch.object(
            deployer,
            '_resolve_template_includes',
            return_value=Path('/tmp/resolved/template-resolved.yml'),
        ) as mock_resolve:
            with patch.object(
                deployer,
                '_read_deploy_params_for_packaged',
                return_value=default_deploy_params,
            ):
                with patch.object(
                    deployer,
                    '_cfn_deploy_packaged',
                    return_value=0,
                ):
                    with patch('deploy.ConsoleAndLog'):
                        # Patch _has_s3_includes to return True (routing
                        # check) so the routing branch is taken regardless
                        # of the working directory context inside
                        # deploy_with_temp_template().
                        with patch.object(
                            deployer,
                            '_has_s3_includes',
                            return_value=True,
                        ) as mock_has_includes:
                            result = deployer.deploy_with_temp_template(
                                str(tmp_template)
                            )

        # _has_s3_includes was consulted by the routing logic
        mock_has_includes.assert_called_once()
        # _resolve_template_includes was invoked by the resolve flow
        mock_resolve.assert_called_once()
        assert result == 0
