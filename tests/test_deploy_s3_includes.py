"""Unit tests for deploy.py S3 include detection helpers.

Tests for:
    - TemplateDeployer._is_s3_url()
    - TemplateDeployer._has_s3_includes()
    - TemplateDeployer._resolve_parameter_references()
    - TemplateDeployer._read_parameter_overrides()

Requirements: FR1, FR2 (from requirements.md)
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add cli/ to path so deploy.py can resolve its relative imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from deploy import TemplateDeployer


def make_deployer(stage_id='default', profile=None, samconfig_path=None):
    """Create a TemplateDeployer instance without triggering __init__ AWS calls.

    Returns a deployer with the minimum attributes needed for the helper
    methods under test.

    Args:
        stage_id: Stage identifier for the deployer. Defaults to 'default'.
        profile: AWS profile name. Defaults to None.
        samconfig_path: Path to the samconfig TOML file. Defaults to None.

    Returns:
        TemplateDeployer instance with __init__ bypassed and required
        attributes set manually.
    """
    with patch.object(TemplateDeployer, '__init__', return_value=None):
        deployer = TemplateDeployer.__new__(TemplateDeployer)
        deployer.stage_id = stage_id
        deployer.profile = profile
        deployer.settings = {}
        deployer.s3_client = MagicMock()
        deployer.s3_client_anonymous = MagicMock()
        if samconfig_path:
            deployer._samconfig_path = samconfig_path

            # Patch get_samconfig_file_path to return the provided path
            deployer.get_samconfig_file_path = lambda: Path(samconfig_path)
        return deployer


# =============================================================================
# Tests for _is_s3_url()
# =============================================================================

class TestIsS3Url:
    """Unit tests for TemplateDeployer._is_s3_url()."""

    def setup_method(self):
        self.deployer = make_deployer()

    def test_s3_scheme_url_returns_true(self):
        """s3://bucket/key is recognised as an S3 URL."""
        assert self.deployer._is_s3_url('s3://bucket/key') is True

    def test_https_s3_amazonaws_url_returns_true(self):
        """https://s3.amazonaws.com/bucket/key is recognised as an S3 URL."""
        assert self.deployer._is_s3_url('https://s3.amazonaws.com/bucket/key') is True

    def test_virtual_hosted_style_url_returns_true(self):
        """https://mybucket.s3.us-east-1.amazonaws.com/key.yml is recognised."""
        assert self.deployer._is_s3_url(
            'https://mybucket.s3.us-east-1.amazonaws.com/key.yml'
        ) is True

    def test_local_relative_path_returns_false(self):
        """./local/file.yml is not an S3 URL."""
        assert self.deployer._is_s3_url('./local/file.yml') is False

    def test_parent_relative_path_returns_false(self):
        """../relative/path.yml is not an S3 URL."""
        assert self.deployer._is_s3_url('../relative/path.yml') is False

    def test_http_url_returns_false(self):
        """http:// URLs are not S3 URLs."""
        assert self.deployer._is_s3_url('http://example.com/file.yml') is False

    def test_none_returns_false(self):
        """None (non-string) returns False."""
        assert self.deployer._is_s3_url(None) is False

    def test_integer_returns_false(self):
        """An integer (non-string) returns False."""
        assert self.deployer._is_s3_url(123) is False


# =============================================================================
# Tests for _has_s3_includes()
# =============================================================================

S3_INCLUDE_TEMPLATE_SINGLE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyRole:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
"""

S3_INCLUDE_TEMPLATE_MULTIPLE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyRole:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
  MyPolicy:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/policy.yml
"""

S3_INCLUDE_TEMPLATE_NESTED = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyResource:
    Properties:
      SubResource:
        Fn::Transform:
          Name: AWS::Include
          Parameters:
            Location: s3://my-bucket/modules/sub.yml
"""

LOCAL_INCLUDE_TEMPLATE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyRole:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: ./local-module.yml
"""

NO_TRANSFORM_TEMPLATE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
"""

SERVERLESS_TRANSFORM_TEMPLATE = """\
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Resources:
  MyFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: index.handler
"""


class TestHasS3Includes:
    """Unit tests for TemplateDeployer._has_s3_includes()."""

    def setup_method(self):
        self.deployer = make_deployer()

    def test_single_s3_include_returns_true(self, tmp_path):
        """Template with one S3 AWS::Include returns True."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(S3_INCLUDE_TEMPLATE_SINGLE)
        assert self.deployer._has_s3_includes(tmpl) is True

    def test_multiple_s3_includes_returns_true(self, tmp_path):
        """Template with multiple S3 AWS::Include entries returns True."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(S3_INCLUDE_TEMPLATE_MULTIPLE)
        assert self.deployer._has_s3_includes(tmpl) is True

    def test_nested_s3_include_returns_true(self, tmp_path):
        """Template with a nested S3 AWS::Include (inside a resource) returns True."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(S3_INCLUDE_TEMPLATE_NESTED)
        assert self.deployer._has_s3_includes(tmpl) is True

    def test_local_include_only_returns_false(self, tmp_path):
        """Template with only a local/relative AWS::Include returns False."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(LOCAL_INCLUDE_TEMPLATE)
        assert self.deployer._has_s3_includes(tmpl) is False

    def test_no_transform_returns_false(self, tmp_path):
        """Template with no Fn::Transform returns False."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(NO_TRANSFORM_TEMPLATE)
        assert self.deployer._has_s3_includes(tmpl) is False

    def test_serverless_transform_no_include_returns_false(self, tmp_path):
        """Template with AWS::Serverless transform but no AWS::Include returns False."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(SERVERLESS_TRANSFORM_TEMPLATE)
        assert self.deployer._has_s3_includes(tmpl) is False

    def test_unparseable_content_returns_false_and_logs_warning(self, tmp_path):
        """Unparseable file content returns False and logs a warning."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_bytes(b'\x80\x81\x82\x83')  # invalid UTF-8 / YAML

        with patch('deploy.ConsoleAndLog') as mock_log:
            result = self.deployer._has_s3_includes(tmpl)

        assert result is False
        mock_log.warning.assert_called_once()


# =============================================================================
# Tests for _resolve_parameter_references()
# =============================================================================

class TestResolveParameterReferences:
    """Unit tests for TemplateDeployer._resolve_parameter_references()."""

    def setup_method(self):
        self.deployer = make_deployer()
        self.overrides = {
            'S3ModuleLocation': 's3://my-bucket/modules',
            'S3ModuleNamespace': 'my-namespace',
        }

    def test_plain_string_returned_unchanged(self):
        """A plain string Location is returned as-is."""
        location = 's3://my-bucket/modules/role.yml'
        assert self.deployer._resolve_parameter_references(location, {}) == location

    def test_ref_with_matching_param(self):
        """{'Ref': 'S3ModuleLocation'} resolves to the parameter value."""
        result = self.deployer._resolve_parameter_references(
            {'Ref': 'S3ModuleLocation'}, self.overrides
        )
        assert result == 's3://my-bucket/modules'

    def test_ref_missing_param_raises_value_error(self):
        """{'Ref': 'MissingParam'} raises ValueError with the param name."""
        with pytest.raises(ValueError, match='MissingParam'):
            self.deployer._resolve_parameter_references({'Ref': 'MissingParam'}, {})

    def test_fn_sub_string_form(self):
        """{'Fn::Sub': '${S3ModuleLocation}/file.yml'} resolves correctly."""
        location = {'Fn::Sub': '${S3ModuleLocation}/modules/file.yml'}
        result = self.deployer._resolve_parameter_references(location, self.overrides)
        assert result == 's3://my-bucket/modules/modules/file.yml'

    def test_fn_sub_list_form(self):
        """{'Fn::Sub': ['${Param}/path', {'Param': 's3://bucket'}]} resolves correctly."""
        location = {'Fn::Sub': ['${Param}/path', {'Param': 's3://bucket'}]}
        result = self.deployer._resolve_parameter_references(location, {})
        assert result == 's3://bucket/path'

    def test_fn_join_with_ref(self):
        """Fn::Join with Ref parts joins correctly."""
        location = {
            'Fn::Join': ['/', [{'Ref': 'S3ModuleLocation'}, 'modules', 'file.yml']]
        }
        result = self.deployer._resolve_parameter_references(location, self.overrides)
        assert result == 's3://my-bucket/modules/modules/file.yml'

    def test_unsupported_format_raises_value_error(self):
        """Unsupported format {'Fn::Select': [0, []]} raises ValueError."""
        with pytest.raises(ValueError):
            self.deployer._resolve_parameter_references({'Fn::Select': [0, []]}, {})

    def test_fn_sub_missing_param_raises_value_error(self):
        """{'Fn::Sub': '${MissingParam}/path'} with no matching param raises ValueError."""
        location = {'Fn::Sub': '${MissingParam}/path'}
        with pytest.raises(ValueError, match='MissingParam'):
            self.deployer._resolve_parameter_references(location, {})


# =============================================================================
# Tests for _read_parameter_overrides()
# =============================================================================

SAMCONFIG_WITH_STAGE = """\
[default.deploy.parameters]
parameter_overrides = "DefaultKey=default-value"

[dev.deploy.parameters]
parameter_overrides = "DevKey=dev-value"
"""

SAMCONFIG_DEFAULT_ONLY = """\
[default.deploy.parameters]
parameter_overrides = "MyKey=my-value OtherKey=other-value"
"""

SAMCONFIG_STAGE_OVERRIDES_DEFAULT = """\
[default.deploy.parameters]
parameter_overrides = "SharedKey=default-shared StageKey=default-stage"

[dev.deploy.parameters]
parameter_overrides = "StageKey=dev-stage"
"""

SAMCONFIG_NO_PARAM_OVERRIDES = """\
[default.deploy.parameters]
stack_name = "my-stack"
"""

SAMCONFIG_MALFORMED = """\
[default.deploy.parameters
invalid toml content ===
"""


class TestReadParameterOverrides:
    """Unit tests for TemplateDeployer._read_parameter_overrides()."""

    def test_stage_specific_parameter_overrides(self, tmp_path):
        """Returns the stage-specific parameter_overrides dict."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_WITH_STAGE)
        deployer = make_deployer(stage_id='dev', samconfig_path=str(config_file))
        result = deployer._read_parameter_overrides()
        assert result == {'DevKey': 'dev-value'}

    def test_default_only_parameter_overrides(self, tmp_path):
        """Returns the default parameter_overrides when no stage section exists."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_DEFAULT_ONLY)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        result = deployer._read_parameter_overrides()
        assert result == {'MyKey': 'my-value', 'OtherKey': 'other-value'}

    def test_stage_overrides_default(self, tmp_path):
        """Stage parameter_overrides takes precedence over default."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_STAGE_OVERRIDES_DEFAULT)
        deployer = make_deployer(stage_id='dev', samconfig_path=str(config_file))
        result = deployer._read_parameter_overrides()
        # The dev stage only has StageKey; after merge, StageKey from dev wins
        assert result.get('StageKey') == 'dev-stage'

    def test_no_parameter_overrides_returns_empty_dict(self, tmp_path):
        """Returns {} when parameter_overrides key is absent."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_NO_PARAM_OVERRIDES)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        result = deployer._read_parameter_overrides()
        assert result == {}

    def test_missing_samconfig_raises_value_error(self, tmp_path):
        """Missing samconfig file raises ValueError."""
        deployer = make_deployer(
            stage_id='default',
            samconfig_path=str(tmp_path / 'nonexistent.toml')
        )
        with pytest.raises(ValueError):
            deployer._read_parameter_overrides()

    def test_malformed_toml_raises_value_error(self, tmp_path):
        """Malformed TOML raises ValueError."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_MALFORMED)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        with pytest.raises(ValueError):
            deployer._read_parameter_overrides()


# =============================================================================
# Tests for _download_s3_module()
# =============================================================================

from botocore.exceptions import ClientError as BotocoreClientError


def make_client_error(code, message='An error occurred'):
    """Create a botocore ClientError for testing error handling."""
    response = {'Error': {'Code': code, 'Message': message}}
    return BotocoreClientError(response, 'GetObject')


class TestDownloadS3Module:
    """Unit tests for TemplateDeployer._download_s3_module()."""

    def setup_method(self):
        self.deployer = make_deployer()
        self.deployer.settings = {}

    def _setup_mock_s3(self, content=b'module content', public=False):
        """Configure s3_client mock to return given content."""
        mock_response = {'Body': MagicMock()}
        mock_response['Body'].read.return_value = content
        if public:
            self.deployer.s3_client_anonymous.get_object.return_value = mock_response
        else:
            self.deployer.s3_client.get_object.return_value = mock_response
        self.deployer.settings = {}
        return mock_response

    def test_successful_download_writes_file_and_returns_path(self, tmp_path):
        """Successful download writes the file and returns the relative path."""
        self._setup_mock_s3()
        result = self.deployer._download_s3_module(
            's3://my-bucket/modules/role.yml', tmp_path, 0
        )
        assert result == './module-0.yml'
        assert (tmp_path / 'module-0.yml').exists()

    def test_extension_from_key_json(self, tmp_path):
        """Key with .json extension produces module-0.json."""
        self._setup_mock_s3()
        result = self.deployer._download_s3_module(
            's3://my-bucket/modules/config.json', tmp_path, 0
        )
        assert result == './module-0.json'
        assert (tmp_path / 'module-0.json').exists()

    def test_no_extension_defaults_to_yml(self, tmp_path):
        """Key with no extension produces module-0.yml."""
        self._setup_mock_s3()
        result = self.deployer._download_s3_module(
            's3://my-bucket/modules/no-ext', tmp_path, 0
        )
        assert result == './module-0.yml'
        assert (tmp_path / 'module-0.yml').exists()

    def test_version_id_forwarded_to_get_object(self, tmp_path):
        """VersionId is forwarded to get_object when present in the URL."""
        mock_response = {'Body': MagicMock()}
        mock_response['Body'].read.return_value = b'versioned content'
        self.deployer.s3_client.get_object.return_value = mock_response
        self.deployer._download_s3_module(
            's3://my-bucket/modules/role.yml?versionId=abc123', tmp_path, 0
        )
        call_kwargs = self.deployer.s3_client.get_object.call_args[1]
        assert call_kwargs.get('VersionId') == 'abc123'

    def test_anonymous_client_used_for_public_bucket(self, tmp_path):
        """Anonymous S3 client is used when is_bucket_public returns True."""
        self._setup_mock_s3(public=True)
        with patch.object(self.deployer, 'is_bucket_public', return_value=True):
            self.deployer._download_s3_module(
                's3://public-bucket/modules/role.yml', tmp_path, 0
            )
        self.deployer.s3_client_anonymous.get_object.assert_called_once()
        self.deployer.s3_client.get_object.assert_not_called()

    def test_authenticated_client_used_for_private_bucket(self, tmp_path):
        """Authenticated S3 client is used when is_bucket_public returns False."""
        self._setup_mock_s3(public=False)
        with patch.object(self.deployer, 'is_bucket_public', return_value=False):
            self.deployer._download_s3_module(
                's3://private-bucket/modules/role.yml', tmp_path, 0
            )
        self.deployer.s3_client.get_object.assert_called_once()
        self.deployer.s3_client_anonymous.get_object.assert_not_called()

    def test_access_denied_raises_value_error(self, tmp_path):
        """AccessDenied ClientError raises ValueError with 'Access denied' in message."""
        self.deployer.s3_client.get_object.side_effect = make_client_error('AccessDenied')
        with patch.object(self.deployer, 'is_bucket_public', return_value=False):
            with pytest.raises(ValueError, match='[Aa]ccess denied'):
                self.deployer._download_s3_module(
                    's3://my-bucket/modules/role.yml', tmp_path, 0
                )

    def test_no_such_key_raises_value_error(self, tmp_path):
        """NoSuchKey ClientError raises ValueError containing the S3 URL."""
        self.deployer.s3_client.get_object.side_effect = make_client_error('NoSuchKey')
        s3_url = 's3://my-bucket/modules/role.yml'
        with patch.object(self.deployer, 'is_bucket_public', return_value=False):
            with pytest.raises(ValueError, match='my-bucket'):
                self.deployer._download_s3_module(s3_url, tmp_path, 0)

    def test_generic_client_error_raises_value_error(self, tmp_path):
        """Generic ClientError raises ValueError."""
        self.deployer.s3_client.get_object.side_effect = make_client_error(
            'InternalError', 'Something went wrong'
        )
        with patch.object(self.deployer, 'is_bucket_public', return_value=False):
            with pytest.raises(ValueError):
                self.deployer._download_s3_module(
                    's3://my-bucket/modules/role.yml', tmp_path, 0
                )


# =============================================================================
# Tests for _read_artifact_bucket_config()
# =============================================================================

SAMCONFIG_ARTIFACT_ATLANTIS = """\
[atlantis.deploy.parameters]
s3_bucket = "atlantis-bucket"
s3_prefix = "atlantis-prefix"
"""

SAMCONFIG_ARTIFACT_STAGE_OVERRIDE = """\
[atlantis.deploy.parameters]
s3_bucket = "atlantis-bucket"
s3_prefix = "atlantis-prefix"

[dev.deploy.parameters]
s3_bucket = "stage-bucket"
s3_prefix = "stage-prefix"
"""

SAMCONFIG_ARTIFACT_NO_PREFIX = """\
[atlantis.deploy.parameters]
s3_bucket = "my-bucket"
"""

SAMCONFIG_ARTIFACT_NO_BUCKET = """\
[atlantis.deploy.parameters]
s3_prefix = "some-prefix"
"""

SAMCONFIG_ARTIFACT_MALFORMED = """\
[atlantis.deploy.parameters
invalid = ===
"""


class TestReadArtifactBucketConfig:
    """Unit tests for TemplateDeployer._read_artifact_bucket_config()."""

    def test_reads_from_atlantis_section(self, tmp_path):
        """Returns (s3_bucket, s3_prefix) from the atlantis section."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_ARTIFACT_ATLANTIS)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        s3_bucket, s3_prefix = deployer._read_artifact_bucket_config()
        assert s3_bucket == 'atlantis-bucket'
        assert s3_prefix == 'atlantis-prefix'

    def test_stage_override_takes_precedence(self, tmp_path):
        """Stage-specific s3_bucket/s3_prefix takes precedence over atlantis values."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_ARTIFACT_STAGE_OVERRIDE)
        deployer = make_deployer(stage_id='dev', samconfig_path=str(config_file))
        s3_bucket, s3_prefix = deployer._read_artifact_bucket_config()
        assert s3_bucket == 'stage-bucket'
        assert s3_prefix == 'stage-prefix'

    def test_absent_prefix_returns_empty_string(self, tmp_path):
        """s3_prefix defaults to '' when not configured."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_ARTIFACT_NO_PREFIX)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        s3_bucket, s3_prefix = deployer._read_artifact_bucket_config()
        assert s3_bucket == 'my-bucket'
        assert s3_prefix == ''

    def test_missing_s3_bucket_raises_value_error(self, tmp_path):
        """Missing s3_bucket raises ValueError with 's3_bucket' and 'config.py' in message."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_ARTIFACT_NO_BUCKET)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        with pytest.raises(ValueError, match='s3_bucket'):
            deployer._read_artifact_bucket_config()

    def test_malformed_toml_raises_value_error(self, tmp_path):
        """Malformed TOML raises ValueError."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_ARTIFACT_MALFORMED)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        with pytest.raises(ValueError):
            deployer._read_artifact_bucket_config()

    def test_missing_samconfig_raises_value_error(self, tmp_path):
        """Missing samconfig file raises ValueError."""
        deployer = make_deployer(
            stage_id='default',
            samconfig_path=str(tmp_path / 'nonexistent.toml')
        )
        with pytest.raises(ValueError):
            deployer._read_artifact_bucket_config()


# =============================================================================
# Tests for _run_sam_package()
# =============================================================================

class TestRunSamPackage:
    """Unit tests for TemplateDeployer._run_sam_package()."""

    def setup_method(self):
        self.deployer = make_deployer()

    def _run_package(self, s3_prefix='my-prefix', profile=None, returncode=0, tmp_path=None):
        """Helper to run _run_sam_package with a patched subprocess.run."""
        self.deployer.profile = profile
        template_path = tmp_path / 'template-rewritten.yml' if tmp_path else Path('/tmp/template-rewritten.yml')
        output_path = tmp_path / 'template-packaged.yml' if tmp_path else Path('/tmp/template-packaged.yml')
        mock_result = MagicMock()
        mock_result.returncode = returncode
        with patch('deploy.subprocess.run', return_value=mock_result) as mock_run:
            with patch('deploy.ConsoleAndLog'):
                result = self.deployer._run_sam_package(
                    template_path, output_path, 'my-bucket', s3_prefix
                )
        return result, mock_run

    def test_successful_run_returns_zero(self, tmp_path):
        """Successful run (exit code 0) returns 0."""
        result, _ = self._run_package(returncode=0, tmp_path=tmp_path)
        assert result == 0

    def test_nonzero_exit_returned_and_logged(self, tmp_path):
        """Non-zero exit code is returned and an error is logged."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        template_path = tmp_path / 'template-rewritten.yml'
        output_path = tmp_path / 'template-packaged.yml'
        with patch('deploy.subprocess.run', return_value=mock_result):
            with patch('deploy.ConsoleAndLog') as mock_log:
                result = self.deployer._run_sam_package(
                    template_path, output_path, 'my-bucket', 'my-prefix'
                )
        assert result == 1
        mock_log.error.assert_called_once()

    def test_s3_prefix_included_when_non_empty(self, tmp_path):
        """--s3-prefix is included when s3_prefix is non-empty."""
        _, mock_run = self._run_package(s3_prefix='my-prefix', tmp_path=tmp_path)
        cmd = mock_run.call_args[0][0]
        assert '--s3-prefix' in cmd
        assert 'my-prefix' in cmd

    def test_s3_prefix_omitted_when_empty(self, tmp_path):
        """--s3-prefix is omitted when s3_prefix is empty string."""
        _, mock_run = self._run_package(s3_prefix='', tmp_path=tmp_path)
        cmd = mock_run.call_args[0][0]
        assert '--s3-prefix' not in cmd

    def test_profile_included_when_set(self, tmp_path):
        """--profile is included when self.profile is not None."""
        _, mock_run = self._run_package(profile='myprofile', tmp_path=tmp_path)
        cmd = mock_run.call_args[0][0]
        assert '--profile' in cmd
        assert 'myprofile' in cmd

    def test_profile_omitted_when_none(self, tmp_path):
        """--profile is omitted when self.profile is None."""
        _, mock_run = self._run_package(profile=None, tmp_path=tmp_path)
        cmd = mock_run.call_args[0][0]
        assert '--profile' not in cmd


# =============================================================================
# Tests for _prepare_template_with_s3_includes()
# =============================================================================

TEMPLATE_TWO_S3_INCLUDES = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  RoleInclude:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
  PolicyInclude:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/policy.yml
"""

TEMPLATE_DUPLICATE_S3_INCLUDE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  First:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
  Second:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
"""

TEMPLATE_MIXED_INCLUDES = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  S3Include:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: s3://my-bucket/modules/role.yml
  LocalInclude:
    Fn::Transform:
      Name: AWS::Include
      Parameters:
        Location: ./local-module.yml
"""


class TestPrepareTemplateWithS3Includes:
    """Unit tests for TemplateDeployer._prepare_template_with_s3_includes()."""

    def setup_method(self):
        self.deployer = make_deployer()

    def _mock_download(self, side_effects=None):
        """Patch _download_s3_module to return sequential paths without real downloads."""
        call_count = [0]

        def fake_download(url, temp_dir, index):
            call_count[0] += 1
            filename = f'module-{index}.yml'
            (temp_dir / filename).write_text(f'# module {index}')
            return f'./{filename}'

        if side_effects:
            patcher = patch.object(
                self.deployer, '_download_s3_module', side_effect=side_effects
            )
        else:
            patcher = patch.object(
                self.deployer, '_download_s3_module', side_effect=fake_download
            )
        return patcher, call_count

    def test_two_s3_includes_both_downloaded(self, tmp_path):
        """Template with two S3 includes downloads both modules and rewrites locations."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(TEMPLATE_TWO_S3_INCLUDES)
        patcher, call_count = self._mock_download()
        with patcher:
            with patch.object(self.deployer, '_read_parameter_overrides', return_value={}):
                with patch('deploy.ConsoleAndLog'):
                    rewritten = self.deployer._prepare_template_with_s3_includes(
                        tmpl, tmp_path
                    )
        assert rewritten.name == 'template-rewritten.yml'
        assert rewritten.exists()
        assert call_count[0] == 2
        content = rewritten.read_text()
        assert 's3://' not in content

    def test_duplicate_url_downloaded_only_once(self, tmp_path):
        """Template referencing the same S3 URL twice downloads only once."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(TEMPLATE_DUPLICATE_S3_INCLUDE)
        patcher, call_count = self._mock_download()
        with patcher:
            with patch.object(self.deployer, '_read_parameter_overrides', return_value={}):
                with patch('deploy.ConsoleAndLog'):
                    self.deployer._prepare_template_with_s3_includes(tmpl, tmp_path)
        assert call_count[0] == 1

    def test_local_includes_not_rewritten(self, tmp_path):
        """Non-S3 Location values in the template are left unchanged."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(TEMPLATE_MIXED_INCLUDES)
        patcher, _ = self._mock_download()
        with patcher:
            with patch.object(self.deployer, '_read_parameter_overrides', return_value={}):
                with patch('deploy.ConsoleAndLog'):
                    rewritten = self.deployer._prepare_template_with_s3_includes(
                        tmpl, tmp_path
                    )
        content = rewritten.read_text()
        assert './local-module.yml' in content

    def test_value_error_from_resolve_propagates(self, tmp_path):
        """ValueError from _resolve_parameter_references propagates out."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(TEMPLATE_TWO_S3_INCLUDES)
        with patch.object(
            self.deployer, '_resolve_parameter_references',
            side_effect=ValueError('missing param')
        ):
            with patch.object(self.deployer, '_read_parameter_overrides', return_value={}):
                with patch('deploy.ConsoleAndLog'):
                    with pytest.raises(ValueError, match='missing param'):
                        self.deployer._prepare_template_with_s3_includes(tmpl, tmp_path)

    def test_value_error_from_download_propagates(self, tmp_path):
        """ValueError from _download_s3_module propagates out."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(TEMPLATE_TWO_S3_INCLUDES)
        with patch.object(
            self.deployer, '_download_s3_module',
            side_effect=ValueError('download failed')
        ):
            with patch.object(self.deployer, '_read_parameter_overrides', return_value={}):
                with patch('deploy.ConsoleAndLog'):
                    with pytest.raises(ValueError, match='download failed'):
                        self.deployer._prepare_template_with_s3_includes(tmpl, tmp_path)

    def test_rewritten_template_has_no_s3_urls_in_locations(self, tmp_path):
        """Written template-rewritten.yml contains no S3 URLs in any Location field."""
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(TEMPLATE_TWO_S3_INCLUDES)
        patcher, _ = self._mock_download()
        with patcher:
            with patch.object(self.deployer, '_read_parameter_overrides', return_value={}):
                with patch('deploy.ConsoleAndLog'):
                    rewritten = self.deployer._prepare_template_with_s3_includes(
                        tmpl, tmp_path
                    )
        content = rewritten.read_text()
        assert 's3://my-bucket/modules/role.yml' not in content
        assert 's3://my-bucket/modules/policy.yml' not in content
