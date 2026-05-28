"""Property-based tests for skeleton generation in cli/config.py.

Uses Hypothesis for property-based testing with minimum 100 iterations.
"""

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from lib.atlantis import TagUtils
from config import ConfigManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Reserved tag keys as defined in TagUtils.is_atlantis_reserved_tag()
RESERVED_EXACT_KEYS = [
    'Provisioner', 'DeployedUsing', 'Name', 'Stage', 'Environment',
    'AlarmNotificationEmail', 'Repository', 'RepositoryBranch',
    'CodeCommitRepository', 'CodeCommitBranch',
]

# Strategy for reserved tag keys: either starts with "Atlantis"/"atlantis:" or is one of the exact reserved keys
reserved_atlantis_prefix_keys = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
    min_size=0, max_size=20
).map(lambda s: 'Atlantis' + s)

reserved_atlantis_colon_prefix_keys = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
    min_size=0, max_size=20
).map(lambda s: 'atlantis:' + s)

reserved_exact_key_strategy = st.sampled_from(RESERVED_EXACT_KEYS)

reserved_key_strategy = st.one_of(
    reserved_atlantis_prefix_keys,
    reserved_atlantis_colon_prefix_keys,
    reserved_exact_key_strategy,
)

# Strategy for non-reserved tag keys: alphanumeric keys that don't match any reserved pattern
non_reserved_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N')),
    min_size=1, max_size=30
).filter(
    lambda k: (
        not k.startswith('Atlantis')
        and not k.startswith('atlantis:')
        and k not in RESERVED_EXACT_KEYS
    )
)

# Strategy for tag values
tag_value_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
    min_size=0, max_size=50
)

# Strategy for a single tag in CloudFormation format
reserved_tag_strategy = st.builds(
    lambda k, v: {"Key": k, "Value": v},
    k=reserved_key_strategy,
    v=tag_value_strategy,
)

non_reserved_tag_strategy = st.builds(
    lambda k, v: {"Key": k, "Value": v},
    k=non_reserved_key_strategy,
    v=tag_value_strategy,
)

# Strategy for a mixed tag list containing both reserved and non-reserved tags
mixed_tag_list_strategy = st.lists(
    st.one_of(reserved_tag_strategy, non_reserved_tag_strategy),
    min_size=0, max_size=20,
)


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 5: Tag filtering excludes all reserved tags
# ---------------------------------------------------------------------------

class TestTagFilteringProperty:
    """Property 5: Tag filtering excludes all reserved tags.

    Validates: Requirements 2.9, 5.1, 5.2
    """

    @given(tag_list=mixed_tag_list_strategy)
    @settings(max_examples=100)
    def test_no_atlantis_prefix_keys_in_output(self, tag_list):
        """No key in the output starts with 'Atlantis'."""
        # Feature: headless-skeleton-mode, Property 5: Tag filtering excludes all reserved tags
        result = ConfigManager.get_user_editable_tags(None, tag_list)
        for key in result.keys():
            assert not key.startswith('Atlantis'), (
                f"Reserved key '{key}' (starts with 'Atlantis') found in output"
            )

    @given(tag_list=mixed_tag_list_strategy)
    @settings(max_examples=100)
    def test_no_atlantis_colon_prefix_keys_in_output(self, tag_list):
        """No key in the output starts with 'atlantis:'."""
        # Feature: headless-skeleton-mode, Property 5: Tag filtering excludes all reserved tags
        result = ConfigManager.get_user_editable_tags(None, tag_list)
        for key in result.keys():
            assert not key.startswith('atlantis:'), (
                f"Reserved key '{key}' (starts with 'atlantis:') found in output"
            )

    @given(tag_list=mixed_tag_list_strategy)
    @settings(max_examples=100)
    def test_no_reserved_exact_keys_in_output(self, tag_list):
        """No key in the output is one of the reserved exact keys."""
        # Feature: headless-skeleton-mode, Property 5: Tag filtering excludes all reserved tags
        result = ConfigManager.get_user_editable_tags(None, tag_list)
        for key in result.keys():
            assert key not in RESERVED_EXACT_KEYS, (
                f"Reserved key '{key}' found in output"
            )

    @given(tag_list=mixed_tag_list_strategy)
    @settings(max_examples=100)
    def test_all_non_reserved_keys_preserved(self, tag_list):
        """All non-reserved keys from the input appear in the output."""
        # Feature: headless-skeleton-mode, Property 5: Tag filtering excludes all reserved tags
        result = ConfigManager.get_user_editable_tags(None, tag_list)

        # Collect expected non-reserved keys (last value wins for duplicates)
        expected_non_reserved = {}
        for tag in tag_list:
            key = tag['Key']
            if not TagUtils.is_atlantis_reserved_tag(key):
                expected_non_reserved[key] = tag['Value']

        # All non-reserved keys must be present in output
        for key in expected_non_reserved:
            assert key in result, (
                f"Non-reserved key '{key}' missing from output"
            )

    @given(tag_list=mixed_tag_list_strategy)
    @settings(max_examples=100)
    def test_output_contains_only_non_reserved_keys(self, tag_list):
        """Output contains ONLY non-reserved keys (comprehensive check using is_atlantis_reserved_tag)."""
        # Feature: headless-skeleton-mode, Property 5: Tag filtering excludes all reserved tags
        result = ConfigManager.get_user_editable_tags(None, tag_list)
        for key in result.keys():
            assert not TagUtils.is_atlantis_reserved_tag(key), (
                f"Key '{key}' is reserved but appeared in output"
            )


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 1: Skeleton file path follows infra_type naming rules
# ---------------------------------------------------------------------------

# Strategies for Property 1
VALID_STAGE_IDS = ["dev", "test", "beta", "stage", "prod"]
VALID_INFRA_TYPES = ['pipeline', 'network', 'storage', 'service-role']

prefix_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz",
    ),
    min_size=2,
    max_size=8,
)

project_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789",
    ),
    min_size=1,
    max_size=32,
)

stage_id_strategy = st.sampled_from(VALID_STAGE_IDS)

infra_type_strategy = st.sampled_from(VALID_INFRA_TYPES)


def _create_config_manager_minimal(prefix, project_id, stage_id, infra_type):
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    from unittest.mock import patch

    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        cm.prefix = prefix
        cm.project_id = project_id
        cm.stage_id = stage_id
        cm.infra_type = infra_type
        return cm


class TestSkeletonFilePathNamingProperty:
    """Property 1: Skeleton file path follows infra_type naming rules.

    For any valid combination of prefix, project_id, stage_id, and infra_type,
    the skeleton file path SHALL include stage_id in the filename when infra_type
    is 'pipeline' or 'network', and SHALL exclude stage_id from the filename when
    infra_type is 'storage' or 'service-role'.

    Validates: Requirements 2.3, 6.1
    """

    @given(
        prefix=prefix_strategy,
        project_id=project_id_strategy,
        stage_id=stage_id_strategy,
        infra_type=infra_type_strategy,
    )
    @settings(max_examples=100)
    def test_stage_id_in_filename_iff_pipeline_or_network(self, prefix, project_id, stage_id, infra_type):
        """stage_id appears in filename if and only if infra_type is pipeline or network."""
        # Feature: headless-skeleton-mode, Property 1: Skeleton file path follows infra_type naming rules
        cm = _create_config_manager_minimal(prefix, project_id, stage_id, infra_type)
        path = cm.get_skeleton_file_path()
        filename = path.name

        if infra_type in ["pipeline", "network"]:
            expected = f"{prefix}-{project_id}-{stage_id}-{infra_type}.json"
            assert filename == expected, (
                f"For infra_type '{infra_type}', expected '{expected}', got '{filename}'"
            )
        else:
            expected = f"{prefix}-{project_id}-{infra_type}.json"
            assert filename == expected, (
                f"For infra_type '{infra_type}', expected '{expected}', got '{filename}'"
            )

    @given(
        prefix=prefix_strategy,
        project_id=project_id_strategy,
        stage_id=stage_id_strategy,
        infra_type=infra_type_strategy,
    )
    @settings(max_examples=100)
    def test_path_is_under_local_init_directory(self, prefix, project_id, stage_id, infra_type):
        """The skeleton file path is always under the local-init directory."""
        # Feature: headless-skeleton-mode, Property 1: Skeleton file path follows infra_type naming rules
        cm = _create_config_manager_minimal(prefix, project_id, stage_id, infra_type)
        path = cm.get_skeleton_file_path()

        assert path.parent.name == "local-init", (
            f"Path parent should be 'local-init', got: {path.parent.name}"
        )

    @given(
        prefix=prefix_strategy,
        project_id=project_id_strategy,
        stage_id=stage_id_strategy,
        infra_type=infra_type_strategy,
    )
    @settings(max_examples=100)
    def test_filename_ends_with_json(self, prefix, project_id, stage_id, infra_type):
        """The skeleton filename always ends with .json."""
        # Feature: headless-skeleton-mode, Property 1: Skeleton file path follows infra_type naming rules
        cm = _create_config_manager_minimal(prefix, project_id, stage_id, infra_type)
        path = cm.get_skeleton_file_path()

        assert path.name.endswith(".json"), (
            f"Filename should end with .json, got: {path.name}"
        )

    @given(
        prefix=prefix_strategy,
        project_id=project_id_strategy,
        stage_id=stage_id_strategy,
        infra_type=st.sampled_from(["storage", "service-role"]),
    )
    @settings(max_examples=100)
    def test_storage_and_service_role_exclude_stage_id(self, prefix, project_id, stage_id, infra_type):
        """For storage and service-role, stage_id does NOT appear as a segment in the filename."""
        # Feature: headless-skeleton-mode, Property 1: Skeleton file path follows infra_type naming rules
        cm = _create_config_manager_minimal(prefix, project_id, stage_id, infra_type)
        path = cm.get_skeleton_file_path()
        filename_without_ext = path.stem

        # The filename should be exactly prefix-project_id-infra_type (no stage_id segment)
        expected_stem = f"{prefix}-{project_id}-{infra_type}"
        assert filename_without_ext == expected_stem, (
            f"For infra_type '{infra_type}', expected stem '{expected_stem}', got '{filename_without_ext}'"
        )


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 2: Skeleton structure contains exactly one stage
# ---------------------------------------------------------------------------

# Strategy for stage_id: random lowercase alphanumeric strings 1-10 chars
stage_id_alnum_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789",
    ),
    min_size=1,
    max_size=10,
)


class TestSkeletonSingleStageProperty:
    """Property 2: Skeleton structure contains exactly one stage.

    For any generated skeleton dictionary, the `deployments` key SHALL contain
    exactly one entry, and that entry's key SHALL equal the stage_id argument
    provided to the generator.

    Validates: Requirements 2.10, 3.4
    """

    @given(stage_id=stage_id_alnum_strategy)
    @settings(max_examples=100)
    def test_deployments_has_exactly_one_key(self, stage_id):
        """The deployments dict in the skeleton has exactly one key."""
        # Feature: headless-skeleton-mode, Property 2: Skeleton structure contains exactly one stage
        from unittest.mock import patch, MagicMock

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = stage_id
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # Mock read_samconfig to return None (no existing config)
        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value=f"acme-myapp-{stage_id}-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("cli.config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = {
                "atlantis": {},
                "parameter_overrides": {},
            }
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        assert "deployments" in result, "Skeleton must contain 'deployments' key"
        assert len(result["deployments"]) == 1, (
            f"Expected exactly 1 deployment stage, got {len(result['deployments'])}"
        )

    @given(stage_id=stage_id_alnum_strategy)
    @settings(max_examples=100)
    def test_deployments_key_equals_stage_id(self, stage_id):
        """The single key in deployments equals the stage_id argument."""
        # Feature: headless-skeleton-mode, Property 2: Skeleton structure contains exactly one stage
        from unittest.mock import patch, MagicMock

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = stage_id
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # Mock read_samconfig to return None (no existing config)
        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value=f"acme-myapp-{stage_id}-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("cli.config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = {
                "atlantis": {},
                "parameter_overrides": {},
            }
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        deployment_keys = list(result["deployments"].keys())
        assert deployment_keys[0] == stage_id, (
            f"Expected deployment key '{stage_id}', got '{deployment_keys[0]}'"
        )


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 3: Template reference includes versionId for S3 URIs
# ---------------------------------------------------------------------------

# Strategy for S3 URIs with versionId
s3_bucket_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789-",
    ),
    min_size=3,
    max_size=20,
).filter(lambda s: not s.startswith('-') and not s.endswith('-'))

s3_path_segment_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789-_",
    ),
    min_size=1,
    max_size=15,
)

s3_path_strategy = st.lists(
    s3_path_segment_strategy, min_size=1, max_size=4
).map(lambda parts: "/".join(parts))

version_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ._",
    ),
    min_size=5,
    max_size=40,
)

s3_uri_with_version_strategy = st.builds(
    lambda bucket, path, version_id: f"s3://{bucket}/{path}/template.yml?versionId={version_id}",
    bucket=s3_bucket_strategy,
    path=s3_path_strategy,
    version_id=version_id_strategy,
)

# Strategy for local filenames (no s3:// prefix)
local_filename_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789-_",
    ),
    min_size=1,
    max_size=30,
).map(lambda s: f"{s}.yml")


def _create_mocked_config_manager_for_skeleton(stage_id="dev"):
    """Create a ConfigManager with mocked internals for generate_skeleton testing."""
    from unittest.mock import patch, MagicMock

    with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
        cm = ConfigManager.__new__(ConfigManager)
        cm.prefix = "acme"
        cm.project_id = "myapp"
        cm.stage_id = stage_id
        cm.infra_type = "pipeline"
        cm.settings = {"tag_keys": []}
        cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

    return cm


class TestTemplateReferenceProperty:
    """Property 3: Template reference includes versionId for S3 URIs.

    For any S3 URI returned by template selection (which includes ?versionId=xyz),
    the skeleton's template_file field SHALL preserve the full URI including the
    versionId. For any local template path, the skeleton's template_file field
    SHALL equal only the filename component.

    Validates: Requirements 2.6
    """

    @given(s3_uri=s3_uri_with_version_strategy)
    @settings(max_examples=100)
    def test_s3_uri_preserved_with_version_id(self, s3_uri):
        """S3 URIs are stored in full including the versionId query parameter."""
        # Feature: headless-skeleton-mode, Property 3: Template reference includes versionId for S3 URIs
        from unittest.mock import patch, MagicMock

        cm = _create_mocked_config_manager_for_skeleton()

        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("cli.config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = {
                "atlantis": {},
                "parameter_overrides": {},
            }
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file=s3_uri,
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        stored_template = result["atlantis"]["deploy"]["parameters"]["template_file"]
        assert stored_template == s3_uri, (
            f"S3 URI should be preserved in full.\n"
            f"  Expected: {s3_uri}\n"
            f"  Got:      {stored_template}"
        )

    @given(local_filename=local_filename_strategy)
    @settings(max_examples=100)
    def test_local_template_stores_filename_only(self, local_filename):
        """Local templates are stored as filename only (no path prefix)."""
        # Feature: headless-skeleton-mode, Property 3: Template reference includes versionId for S3 URIs
        from unittest.mock import patch, MagicMock

        cm = _create_mocked_config_manager_for_skeleton()

        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("cli.config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = {
                "atlantis": {},
                "parameter_overrides": {},
            }
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file=local_filename,
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        stored_template = result["atlantis"]["deploy"]["parameters"]["template_file"]
        # Local filenames should be stored as-is (just the filename, no directory path)
        assert stored_template == local_filename, (
            f"Local template should be stored as filename only.\n"
            f"  Expected: {local_filename}\n"
            f"  Got:      {stored_template}"
        )

    @given(
        s3_uri=s3_uri_with_version_strategy,
        local_filename=local_filename_strategy,
    )
    @settings(max_examples=100)
    def test_s3_uri_not_stripped_to_filename(self, s3_uri, local_filename):
        """S3 URIs are NOT reduced to just the filename — the full URI is kept."""
        # Feature: headless-skeleton-mode, Property 3: Template reference includes versionId for S3 URIs
        from unittest.mock import patch, MagicMock

        cm = _create_mocked_config_manager_for_skeleton()

        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("cli.config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = {
                "atlantis": {},
                "parameter_overrides": {},
            }
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file=s3_uri,
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        stored_template = result["atlantis"]["deploy"]["parameters"]["template_file"]
        # The stored template must start with s3:// (not stripped to filename)
        assert stored_template.startswith("s3://"), (
            f"S3 URI should start with 's3://', got: {stored_template}"
        )
        # The stored template must contain the versionId
        assert "?versionId=" in stored_template, (
            f"S3 URI should contain '?versionId=', got: {stored_template}"
        )


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 4: Pre-population merge precedence
# ---------------------------------------------------------------------------

# Strategy for valid S3 bucket names (lowercase, 3-63 chars, alphanumeric + hyphens)
s3_bucket_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789",
    ),
    min_size=3,
    max_size=20,
)

# Strategy for valid AWS region strings
region_strategy = st.sampled_from([
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-central-1", "ap-southeast-1",
])


class TestMergePrecedenceProperty:
    """Property 4: Pre-population merge precedence.

    For any parameter that exists in both an existing samconfig and the defaults
    hierarchy, the skeleton SHALL use the samconfig value. For any parameter that
    exists only in the defaults hierarchy, the skeleton SHALL use the defaults value.

    **Validates: Requirements 2.8, 3.1, 3.2, 5.3, 5.4, 5.5**
    """

    @given(
        samconfig_bucket=s3_bucket_strategy,
        samconfig_region=region_strategy,
        defaults_bucket=s3_bucket_strategy,
        defaults_region=region_strategy,
    )
    @settings(max_examples=100)
    def test_samconfig_s3_bucket_takes_precedence_over_defaults(
        self, samconfig_bucket, samconfig_region, defaults_bucket, defaults_region
    ):
        """When both samconfig and defaults provide s3_bucket, samconfig wins."""
        # Feature: headless-skeleton-mode, Property 4: Pre-population merge precedence
        from unittest.mock import patch, MagicMock

        assume(samconfig_bucket != defaults_bucket)

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = "dev"
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # samconfig provides s3_bucket and region
        samconfig_data = {
            "atlantis": {
                "deploy": {
                    "parameters": {
                        "s3_bucket": samconfig_bucket,
                        "region": samconfig_region,
                    }
                }
            },
            "deployments": {},
        }

        # defaults also provides s3_bucket and region
        defaults_data = {
            "atlantis": {
                "s3_bucket": defaults_bucket,
                "region": defaults_region,
            },
            "parameter_overrides": {},
        }

        with patch.object(cm, "read_samconfig", return_value=samconfig_data), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = defaults_data
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        atlantis_params = result["atlantis"]["deploy"]["parameters"]
        assert atlantis_params["s3_bucket"] == samconfig_bucket, (
            f"Expected samconfig s3_bucket '{samconfig_bucket}', "
            f"got '{atlantis_params['s3_bucket']}' (defaults was '{defaults_bucket}')"
        )

    @given(
        samconfig_region=region_strategy,
        defaults_bucket=s3_bucket_strategy,
        defaults_region=region_strategy,
    )
    @settings(max_examples=100)
    def test_samconfig_region_takes_precedence_over_defaults(
        self, samconfig_region, defaults_bucket, defaults_region
    ):
        """When both samconfig and defaults provide region, samconfig wins."""
        # Feature: headless-skeleton-mode, Property 4: Pre-population merge precedence
        from unittest.mock import patch, MagicMock

        assume(samconfig_region != defaults_region)

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = "dev"
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # samconfig provides region
        samconfig_data = {
            "atlantis": {
                "deploy": {
                    "parameters": {
                        "region": samconfig_region,
                    }
                }
            },
            "deployments": {},
        }

        # defaults also provides region and s3_bucket
        defaults_data = {
            "atlantis": {
                "s3_bucket": defaults_bucket,
                "region": defaults_region,
            },
            "parameter_overrides": {},
        }

        with patch.object(cm, "read_samconfig", return_value=samconfig_data), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = defaults_data
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        atlantis_params = result["atlantis"]["deploy"]["parameters"]
        assert atlantis_params["region"] == samconfig_region, (
            f"Expected samconfig region '{samconfig_region}', "
            f"got '{atlantis_params['region']}' (defaults was '{defaults_region}')"
        )

    @given(
        defaults_bucket=s3_bucket_strategy,
        defaults_region=region_strategy,
    )
    @settings(max_examples=100)
    def test_defaults_used_when_no_samconfig(self, defaults_bucket, defaults_region):
        """When no samconfig exists, defaults values are used."""
        # Feature: headless-skeleton-mode, Property 4: Pre-population merge precedence
        from unittest.mock import patch, MagicMock

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = "dev"
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # No samconfig
        defaults_data = {
            "atlantis": {
                "s3_bucket": defaults_bucket,
                "region": defaults_region,
            },
            "parameter_overrides": {},
        }

        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = defaults_data
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"Prefix": {"Type": "String", "Default": "acme"}},
                verbose=False,
            )

        atlantis_params = result["atlantis"]["deploy"]["parameters"]
        assert atlantis_params["s3_bucket"] == defaults_bucket, (
            f"Expected defaults s3_bucket '{defaults_bucket}', "
            f"got '{atlantis_params['s3_bucket']}'"
        )
        assert atlantis_params["region"] == defaults_region, (
            f"Expected defaults region '{defaults_region}', "
            f"got '{atlantis_params['region']}'"
        )

    @given(
        samconfig_bucket=s3_bucket_strategy,
        samconfig_region=region_strategy,
        defaults_bucket=s3_bucket_strategy,
        defaults_region=region_strategy,
        samconfig_param_value=st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N')),
            min_size=1, max_size=20,
        ),
        defaults_param_value=st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N')),
            min_size=1, max_size=20,
        ),
    )
    @settings(max_examples=100)
    def test_samconfig_parameter_overrides_take_precedence(
        self, samconfig_bucket, samconfig_region, defaults_bucket, defaults_region,
        samconfig_param_value, defaults_param_value,
    ):
        """When both samconfig and defaults provide parameter_overrides, samconfig wins."""
        # Feature: headless-skeleton-mode, Property 4: Pre-population merge precedence
        from unittest.mock import patch, MagicMock

        assume(samconfig_param_value != defaults_param_value)

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = "dev"
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # samconfig provides a parameter override for "RolePath"
        samconfig_data = {
            "atlantis": {
                "deploy": {
                    "parameters": {
                        "s3_bucket": samconfig_bucket,
                        "region": samconfig_region,
                    }
                }
            },
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "RolePath": samconfig_param_value,
                            }
                        }
                    }
                }
            },
        }

        # defaults also provides a value for "RolePath"
        defaults_data = {
            "atlantis": {
                "s3_bucket": defaults_bucket,
                "region": defaults_region,
            },
            "parameter_overrides": {
                "RolePath": defaults_param_value,
            },
        }

        with patch.object(cm, "read_samconfig", return_value=samconfig_data), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = defaults_data
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"RolePath": {"Type": "String", "Default": "/sam-app/"}},
                verbose=False,
            )

        param_overrides = result["deployments"]["dev"]["deploy"]["parameters"]["parameter_overrides"]
        assert param_overrides["RolePath"] == samconfig_param_value, (
            f"Expected samconfig RolePath '{samconfig_param_value}', "
            f"got '{param_overrides['RolePath']}' (defaults was '{defaults_param_value}')"
        )

    @given(
        defaults_param_value=st.text(
            alphabet=st.characters(whitelist_categories=('L', 'N')),
            min_size=1, max_size=20,
        ),
    )
    @settings(max_examples=100)
    def test_defaults_parameter_overrides_used_when_no_samconfig(self, defaults_param_value):
        """When no samconfig exists, defaults parameter_overrides values are used."""
        # Feature: headless-skeleton-mode, Property 4: Pre-population merge precedence
        from unittest.mock import patch, MagicMock

        with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
            cm = ConfigManager.__new__(ConfigManager)
            cm.prefix = "acme"
            cm.project_id = "myapp"
            cm.stage_id = "dev"
            cm.infra_type = "pipeline"
            cm.settings = {"tag_keys": []}
            cm.defaults = {"atlantis": {}, "parameter_overrides": {}}

        # No samconfig, defaults provides RolePath
        defaults_data = {
            "atlantis": {
                "s3_bucket": "my-bucket",
                "region": "us-east-1",
            },
            "parameter_overrides": {
                "RolePath": defaults_param_value,
            },
        }

        with patch.object(cm, "read_samconfig", return_value=None), \
             patch.object(cm, "get_settings_dir", return_value=Path("/fake/settings")), \
             patch.object(cm, "get_stack_name", return_value="acme-myapp-dev-pipeline"), \
             patch.object(cm, "get_user_editable_tags", return_value={}), \
             patch("config.DefaultsLoader") as MockDefaultsLoader:

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_defaults.return_value = defaults_data
            MockDefaultsLoader.return_value = mock_loader_instance

            result = cm.generate_skeleton(
                template_file="s3://bucket/template.yml?versionId=abc123",
                parameter_groups=[],
                parameters={"RolePath": {"Type": "String", "Default": "/sam-app/"}},
                verbose=False,
            )

        param_overrides = result["deployments"]["dev"]["deploy"]["parameters"]["parameter_overrides"]
        assert param_overrides["RolePath"] == defaults_param_value, (
            f"Expected defaults RolePath '{defaults_param_value}', "
            f"got '{param_overrides['RolePath']}'"
        )
