"""Property-based tests for verbose metadata generation in cli/config.py.

Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields

Uses Hypothesis for property-based testing with minimum 100 iterations.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import ConfigManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid CloudFormation parameter types
VALID_PARAM_TYPES = [
    "String",
    "Number",
    "CommaDelimitedList",
    "AWS::SSM::Parameter::Value<String>",
]

param_type_strategy = st.sampled_from(VALID_PARAM_TYPES)

# Optional fields strategies
description_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'Z', 'P')),
    min_size=1,
    max_size=100,
)

allowed_values_strategy = st.lists(
    st.text(
        alphabet=st.characters(
            whitelist_categories=(),
            whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789-_",
        ),
        min_size=1,
        max_size=20,
    ),
    min_size=1,
    max_size=5,
)

allowed_pattern_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789^$.*+?[]{}()|\\",
    ),
    min_size=1,
    max_size=30,
)

min_length_strategy = st.integers(min_value=0, max_value=100)
max_length_strategy = st.integers(min_value=1, max_value=256)
min_value_strategy = st.integers(min_value=0, max_value=1000)
max_value_strategy = st.integers(min_value=1, max_value=10000)

constraint_description_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'Z', 'P')),
    min_size=1,
    max_size=100,
)

default_value_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789-_",
    ),
    min_size=0,
    max_size=50,
)

# Parameter name strategy
param_name_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    ),
    min_size=1,
    max_size=30,
)


# Strategy for a single parameter definition with random optional fields
@st.composite
def parameter_definition_strategy(draw):
    """Generate a random parameter definition with Type always present and other fields optional."""
    param_type = draw(param_type_strategy)
    param_def = {'Type': param_type}

    # Randomly include/exclude each optional field
    if draw(st.booleans()):
        param_def['Description'] = draw(description_strategy)
    if draw(st.booleans()):
        param_def['AllowedValues'] = draw(allowed_values_strategy)
    if draw(st.booleans()):
        param_def['AllowedPattern'] = draw(allowed_pattern_strategy)
    if draw(st.booleans()):
        param_def['MinLength'] = draw(min_length_strategy)
    if draw(st.booleans()):
        param_def['MaxLength'] = draw(max_length_strategy)
    if draw(st.booleans()):
        param_def['MinValue'] = draw(min_value_strategy)
    if draw(st.booleans()):
        param_def['MaxValue'] = draw(max_value_strategy)
    if draw(st.booleans()):
        param_def['ConstraintDescription'] = draw(constraint_description_strategy)
    if draw(st.booleans()):
        param_def['Default'] = draw(default_value_strategy)

    return param_def


# Strategy for a parameters dict with 1-5 parameters
@st.composite
def parameters_dict_strategy(draw):
    """Generate a dict of parameter names to parameter definitions."""
    num_params = draw(st.integers(min_value=1, max_value=5))
    params = {}
    for _ in range(num_params):
        name = draw(param_name_strategy)
        assume(name not in params)  # Ensure unique names
        params[name] = draw(parameter_definition_strategy())
    assume(len(params) >= 1)
    return params


def _create_config_manager_for_skeleton():
    """Create a ConfigManager instance with mocked __init__ for skeleton generation."""
    with patch.object(ConfigManager, "__init__", lambda self, *a, **kw: None):
        cm = ConfigManager.__new__(ConfigManager)
        cm.prefix = "acme"
        cm.project_id = "myapp"
        cm.stage_id = "dev"
        cm.infra_type = "pipeline"
        cm.settings = {"tag_keys": []}
        cm.defaults = {"atlantis": {}, "parameter_overrides": {}}
        return cm


def _generate_skeleton_verbose(parameters):
    """Helper to call generate_skeleton with verbose=True and return the result."""
    cm = _create_config_manager_for_skeleton()

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
            template_file="s3://bucket/template.yml?versionId=abc123",
            parameter_groups=[],
            parameters=parameters,
            verbose=True,
        )

    return result


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
# ---------------------------------------------------------------------------

class TestVerboseMetadataProperty:
    """Property 7: Verbose metadata includes all defined constraint fields.

    For any template parameter definition, the generated _parameter_metadata entry
    SHALL include the Type field always, SHALL include Description if defined,
    SHALL include AllowedValues if defined, SHALL include each constraint field
    (AllowedPattern, MinLength, MaxLength, MinValue, MaxValue, ConstraintDescription)
    if defined, and SHALL include Default if defined. If only Type is defined, the
    metadata entry SHALL contain only Type.

    Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10
    """

    @given(parameters=parameters_dict_strategy())
    @settings(max_examples=100)
    def test_parameter_metadata_section_exists(self, parameters):
        """The _parameter_metadata section exists in the result when verbose=True."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        result = _generate_skeleton_verbose(parameters)
        assert '_parameter_metadata' in result, (
            "Skeleton generated with verbose=True must contain '_parameter_metadata' key"
        )

    @given(parameters=parameters_dict_strategy())
    @settings(max_examples=100)
    def test_type_always_present_in_metadata(self, parameters):
        """For each parameter, Type is always present in metadata."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        result = _generate_skeleton_verbose(parameters)
        metadata = result['_parameter_metadata']

        for param_name in parameters:
            assert param_name in metadata, (
                f"Parameter '{param_name}' missing from _parameter_metadata"
            )
            assert 'Type' in metadata[param_name], (
                f"Parameter '{param_name}' metadata missing 'Type' field"
            )

    @given(parameters=parameters_dict_strategy())
    @settings(max_examples=100)
    def test_description_present_iff_defined(self, parameters):
        """Description is in metadata if and only if it was in the parameter definition."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        result = _generate_skeleton_verbose(parameters)
        metadata = result['_parameter_metadata']

        for param_name, param_def in parameters.items():
            if 'Description' in param_def:
                assert 'Description' in metadata[param_name], (
                    f"Parameter '{param_name}': Description defined in input but missing from metadata"
                )
                assert metadata[param_name]['Description'] == param_def['Description'], (
                    f"Parameter '{param_name}': Description value mismatch"
                )
            else:
                assert 'Description' not in metadata[param_name], (
                    f"Parameter '{param_name}': Description not defined in input but present in metadata"
                )

    @given(parameters=parameters_dict_strategy())
    @settings(max_examples=100)
    def test_allowed_values_present_iff_defined(self, parameters):
        """AllowedValues is in metadata if and only if it was in the parameter definition."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        result = _generate_skeleton_verbose(parameters)
        metadata = result['_parameter_metadata']

        for param_name, param_def in parameters.items():
            if 'AllowedValues' in param_def:
                assert 'AllowedValues' in metadata[param_name], (
                    f"Parameter '{param_name}': AllowedValues defined in input but missing from metadata"
                )
                assert metadata[param_name]['AllowedValues'] == param_def['AllowedValues'], (
                    f"Parameter '{param_name}': AllowedValues value mismatch"
                )
            else:
                assert 'AllowedValues' not in metadata[param_name], (
                    f"Parameter '{param_name}': AllowedValues not defined in input but present in metadata"
                )

    @given(parameters=parameters_dict_strategy())
    @settings(max_examples=100)
    def test_constraint_fields_present_iff_defined(self, parameters):
        """Each constraint field is in metadata if and only if it was in the parameter definition."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        constraint_fields = [
            'AllowedPattern', 'MinLength', 'MaxLength',
            'MinValue', 'MaxValue', 'ConstraintDescription',
        ]

        result = _generate_skeleton_verbose(parameters)
        metadata = result['_parameter_metadata']

        for param_name, param_def in parameters.items():
            for field in constraint_fields:
                if field in param_def:
                    assert field in metadata[param_name], (
                        f"Parameter '{param_name}': {field} defined in input but missing from metadata"
                    )
                    assert metadata[param_name][field] == param_def[field], (
                        f"Parameter '{param_name}': {field} value mismatch"
                    )
                else:
                    assert field not in metadata[param_name], (
                        f"Parameter '{param_name}': {field} not defined in input but present in metadata"
                    )

    @given(parameters=parameters_dict_strategy())
    @settings(max_examples=100)
    def test_default_present_iff_defined(self, parameters):
        """Default is in metadata if and only if it was in the parameter definition."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        result = _generate_skeleton_verbose(parameters)
        metadata = result['_parameter_metadata']

        for param_name, param_def in parameters.items():
            if 'Default' in param_def:
                assert 'Default' in metadata[param_name], (
                    f"Parameter '{param_name}': Default defined in input but missing from metadata"
                )
                assert metadata[param_name]['Default'] == param_def['Default'], (
                    f"Parameter '{param_name}': Default value mismatch"
                )
            else:
                assert 'Default' not in metadata[param_name], (
                    f"Parameter '{param_name}': Default not defined in input but present in metadata"
                )

    @given(param_type=param_type_strategy)
    @settings(max_examples=100)
    def test_type_only_when_no_other_fields_defined(self, param_type):
        """If only Type is defined, metadata entry contains only Type."""
        # Feature: headless-skeleton-mode, Property 7: Verbose metadata includes all defined constraint fields
        parameters = {"TestParam": {"Type": param_type}}
        result = _generate_skeleton_verbose(parameters)
        metadata = result['_parameter_metadata']

        assert 'TestParam' in metadata
        entry = metadata['TestParam']
        assert entry == {'Type': param_type}, (
            f"When only Type is defined, metadata should contain only Type. Got: {entry}"
        )
