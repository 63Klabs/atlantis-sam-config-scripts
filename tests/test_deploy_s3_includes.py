"""Unit tests for deploy.py S3 include detection helpers.

Tests for:
    - TemplateDeployer._is_s3_url()
    - TemplateDeployer._has_s3_includes()
    - TemplateDeployer._read_artifact_bucket_config()
    - TemplateDeployer._read_parameter_overrides()
    - TemplateDeployer._resolve_parameter_references()

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

NO_INCLUDE_TEMPLATE_WITH_CF_TAGS = """\
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  Env:
    Type: String
  BucketRef:
    Type: String
    Default: !Ref SomeBucket
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub my-bucket-${Env}
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

    def test_cf_tags_with_s3_include_returns_true(self, tmp_path):
        """Template using !Sub + Fn::Transform AWS::Include S3 location returns True.

        Bug condition exploration test (Property 1). This test MUST FAIL on unfixed
        code because yaml.safe_load raises ConstructorError for the !Sub tag, causing
        _has_s3_includes() to fall through both parse attempts and return False.

        Validates: Requirements 1.1, 1.2
        """
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(S3_INCLUDE_TEMPLATE_WITH_CF_TAGS)
        assert self.deployer._has_s3_includes(tmpl) is True

    def test_cf_tags_without_s3_include_returns_false(self, tmp_path):
        """Template using !Sub/!Ref tags but without any S3 AWS::Include returns False.

        Preservation test (Property 2). On unfixed code, the outer exception handler
        catches the ConstructorError and returns False (fail-open). On fixed code,
        _CfnLoader parses successfully and finds no S3 includes, so it still returns
        False — but now for the correct reason.

        Validates: Requirements 3.2
        """
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(NO_INCLUDE_TEMPLATE_WITH_CF_TAGS)
        assert self.deployer._has_s3_includes(tmpl) is False

    def test_sub_s3_include_location_returns_true(self, tmp_path):
        """AWS::Include with Location: !Sub 's3://${X}/mod.yml' is detected as an S3 include."""
        template = (
            "AWSTemplateFormatVersion: '2010-09-09'\n"
            "Parameters:\n"
            "  S3ModuleLocation:\n"
            "    Type: String\n"
            "Resources:\n"
            "  MyRole:\n"
            "    Fn::Transform:\n"
            "      Name: AWS::Include\n"
            "      Parameters:\n"
            "        Location: !Sub 's3://${S3ModuleLocation}/atlantis/mod.yml'\n"
        )
        tmpl = tmp_path / 'template.yml'
        tmpl.write_text(template)
        assert self.deployer._has_s3_includes(tmpl) is True


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
        """A plain string Location without ${} is returned as-is."""
        location = 's3://my-bucket/modules/role.yml'
        assert self.deployer._resolve_parameter_references(location, {}) == location

    def test_plain_string_param_substituted(self):
        """A plain string Location with ${Param} has the param substituted."""
        location = '${S3ModuleLocation}/role.yml'
        result = self.deployer._resolve_parameter_references(location, self.overrides)
        assert result == 's3://my-bucket/modules/role.yml'

    def test_plain_string_missing_param_raises_value_error(self):
        """A plain string Location with an unresolved ${Param} raises ValueError."""
        location = '${MissingParam}/role.yml'
        with pytest.raises(ValueError, match='MissingParam'):
            self.deployer._resolve_parameter_references(location, {})

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

SAMCONFIG_QUOTED_FORMAT = """\
[default.deploy.parameters]
parameter_overrides = "\\"Prefix\\"=\\"acme\\" \\"S3ModuleLocation\\"=\\"63klabz\\""
"""

SAMCONFIG_MIXED_FORMAT = """\
[default.deploy.parameters]
parameter_overrides = "\\"Prefix\\"=\\"acme\\" Env=prod"
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

    def test_quoted_format_parameter_overrides(self, tmp_path):
        """SAM CLI quoted "Key"="Value" format is parsed correctly."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_QUOTED_FORMAT)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        result = deployer._read_parameter_overrides()
        assert result == {'Prefix': 'acme', 'S3ModuleLocation': '63klabz'}

    def test_mixed_format_parameter_overrides(self, tmp_path):
        """A mix of quoted and plain Key=Value pairs is parsed correctly."""
        config_file = tmp_path / 'samconfig.toml'
        config_file.write_text(SAMCONFIG_MIXED_FORMAT)
        deployer = make_deployer(stage_id='default', samconfig_path=str(config_file))
        result = deployer._read_parameter_overrides()
        assert result == {'Prefix': 'acme', 'Env': 'prod'}

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
