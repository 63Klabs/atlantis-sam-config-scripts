"""Property-based tests for headless validation reporting in cli/config.py.

Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures

Uses Hypothesis for property-based testing with minimum 100 iterations.
Validates: Requirements 6.4, 7.2, 7.3
"""

import sys
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

def _create_config_manager():
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        return cm


# ---------------------------------------------------------------------------
# Strategies for Property 8
# ---------------------------------------------------------------------------

# Strategy for valid parameter names (alphanumeric, starting with letter)
param_name_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ),
    min_size=1,
    max_size=20,
)

# Strategy for generating a parameter definition with AllowedPattern constraint
# and a value that VIOLATES it
def allowed_pattern_violation():
    """Generate a param def with AllowedPattern and a value that violates it."""
    # Use a strict pattern that only allows lowercase letters
    return st.fixed_dictionaries({
        "param_def": st.just({
            "Type": "String",
            "AllowedPattern": "^[a-z]+$",
        }),
        "invalid_value": st.text(
            alphabet=st.characters(
                whitelist_categories=(),
                whitelist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%",
            ),
            min_size=1,
            max_size=10,
        ),
    })


# Strategy for generating a parameter definition with AllowedValues constraint
# and a value that VIOLATES it
def allowed_values_violation():
    """Generate a param def with AllowedValues and a value not in the list."""
    allowed = ["dev", "test", "beta", "stage", "prod"]
    return st.fixed_dictionaries({
        "param_def": st.just({
            "Type": "String",
            "AllowedValues": allowed,
        }),
        # Generate a value that is NOT in the allowed list
        "invalid_value": st.text(
            alphabet=st.characters(
                whitelist_categories=(),
                whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789",
            ),
            min_size=1,
            max_size=15,
        ).filter(lambda v: v not in allowed),
    })


# Strategy for generating a parameter definition with MinLength constraint
# and a value that is too short
def min_length_violation():
    """Generate a param def with MinLength and a value that is too short."""
    return st.fixed_dictionaries({
        "param_def": st.just({
            "Type": "String",
            "MinLength": 5,
        }),
        # Generate a value shorter than 5 characters (but non-empty to avoid Default bypass)
        "invalid_value": st.text(
            alphabet=st.characters(
                whitelist_categories=(),
                whitelist_characters="abcdefghijklmnopqrstuvwxyz",
            ),
            min_size=1,
            max_size=4,
        ),
    })


# Strategy for generating a parameter definition with MaxLength constraint
# and a value that is too long
def max_length_violation():
    """Generate a param def with MaxLength and a value that exceeds it."""
    return st.fixed_dictionaries({
        "param_def": st.just({
            "Type": "String",
            "MaxLength": 5,
        }),
        # Generate a value longer than 5 characters
        "invalid_value": st.text(
            alphabet=st.characters(
                whitelist_categories=(),
                whitelist_characters="abcdefghijklmnopqrstuvwxyz",
            ),
            min_size=6,
            max_size=15,
        ),
    })


# Strategy for generating a parameter definition with numeric MinValue/MaxValue
# and a value that violates it
def numeric_violation():
    """Generate a Number param def with bounds and a value that violates them."""
    return st.fixed_dictionaries({
        "param_def": st.just({
            "Type": "Number",
            "MinValue": 1,
            "MaxValue": 100,
        }),
        # Generate a number outside the valid range (either < 1 or > 100)
        "invalid_value": st.one_of(
            st.integers(min_value=-1000, max_value=0).map(str),
            st.integers(min_value=101, max_value=10000).map(str),
        ),
    })


# Combined strategy: pick one violation type
invalid_param_strategy = st.one_of(
    allowed_pattern_violation(),
    allowed_values_violation(),
    min_length_violation(),
    max_length_violation(),
    numeric_violation(),
)


# Strategy for generating N invalid parameters with unique names
@st.composite
def invalid_parameter_set(draw, min_count=1, max_count=8):
    """Generate a set of N parameters, each with a known-invalid value and its definition."""
    n = draw(st.integers(min_value=min_count, max_value=max_count))

    # Use fixed distinct parameter name prefixes to ensure uniqueness
    base_names = [
        "ParamAlpha", "ParamBeta", "ParamGamma", "ParamDelta",
        "ParamEpsilon", "ParamZeta", "ParamEta", "ParamTheta",
    ]

    params = {}
    param_defs = {}

    for i in range(n):
        name = base_names[i]
        violation = draw(invalid_param_strategy)
        params[name] = violation["invalid_value"]
        param_defs[name] = violation["param_def"]

    return {
        "count": n,
        "parameter_overrides": params,
        "parameter_definitions": param_defs,
    }


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures
# ---------------------------------------------------------------------------

class TestHeadlessValidationReportsAllFailures:
    """Property 8: Headless validation reports all failures.

    For any skeleton containing N parameters that violate their template constraints,
    validate_all_parameters() SHALL return exactly N failure entries, one per invalid
    parameter, each identifying the parameter name, provided value, and violated constraint.

    Validates: Requirements 6.4, 7.2, 7.3
    """

    @given(data=invalid_parameter_set())
    @settings(max_examples=100)
    def test_failure_count_equals_invalid_parameter_count(self, data):
        """Number of failures returned equals exactly N (the number of invalid parameters)."""
        # Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures
        cm = _create_config_manager()

        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": data["parameter_overrides"]
                        }
                    }
                }
            }
        }

        failures = cm.validate_all_parameters(skeleton, data["parameter_definitions"])

        assert len(failures) == data["count"], (
            f"Expected {data['count']} failures, got {len(failures)}. "
            f"Params: {data['parameter_overrides']}, Defs: {data['parameter_definitions']}"
        )

    @given(data=invalid_parameter_set())
    @settings(max_examples=100)
    def test_each_failure_identifies_correct_parameter_name(self, data):
        """Each failure entry identifies the correct parameter name."""
        # Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures
        cm = _create_config_manager()

        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": data["parameter_overrides"]
                        }
                    }
                }
            }
        }

        failures = cm.validate_all_parameters(skeleton, data["parameter_definitions"])

        failed_param_names = {f["parameter"] for f in failures}
        expected_param_names = set(data["parameter_overrides"].keys())

        assert failed_param_names == expected_param_names, (
            f"Expected failures for params {expected_param_names}, "
            f"got failures for {failed_param_names}"
        )

    @given(data=invalid_parameter_set())
    @settings(max_examples=100)
    def test_each_failure_contains_provided_value(self, data):
        """Each failure entry contains the provided value that was invalid."""
        # Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures
        cm = _create_config_manager()

        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": data["parameter_overrides"]
                        }
                    }
                }
            }
        }

        failures = cm.validate_all_parameters(skeleton, data["parameter_definitions"])

        for failure in failures:
            param_name = failure["parameter"]
            expected_value = data["parameter_overrides"][param_name]
            assert failure["value"] == expected_value, (
                f"Failure for '{param_name}' has value '{failure['value']}', "
                f"expected '{expected_value}'"
            )

    @given(data=invalid_parameter_set())
    @settings(max_examples=100)
    def test_each_failure_contains_non_empty_reason(self, data):
        """Each failure entry contains a non-empty reason string."""
        # Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures
        cm = _create_config_manager()

        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": data["parameter_overrides"]
                        }
                    }
                }
            }
        }

        failures = cm.validate_all_parameters(skeleton, data["parameter_definitions"])

        for failure in failures:
            assert "reason" in failure, (
                f"Failure for '{failure['parameter']}' missing 'reason' key"
            )
            assert isinstance(failure["reason"], str), (
                f"Failure reason for '{failure['parameter']}' is not a string"
            )
            assert len(failure["reason"]) > 0, (
                f"Failure reason for '{failure['parameter']}' is empty"
            )

    @given(data=invalid_parameter_set())
    @settings(max_examples=100)
    def test_each_failure_has_required_keys(self, data):
        """Each failure dict has exactly the keys: parameter, value, reason."""
        # Feature: headless-skeleton-mode, Property 8: Headless validation reports all failures
        cm = _create_config_manager()

        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": data["parameter_overrides"]
                        }
                    }
                }
            }
        }

        failures = cm.validate_all_parameters(skeleton, data["parameter_definitions"])

        required_keys = {"parameter", "value", "reason"}
        for failure in failures:
            assert required_keys.issubset(failure.keys()), (
                f"Failure dict missing keys. Expected {required_keys}, "
                f"got {set(failure.keys())}"
            )
