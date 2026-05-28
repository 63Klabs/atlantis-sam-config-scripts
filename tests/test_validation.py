"""Property-based tests for parameter validation correctness in cli/config.py.

Uses Hypothesis for property-based testing with minimum 100 iterations.
"""
# Feature: headless-skeleton-mode, Property 9: Parameter validation correctness

import re
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
# Helper to create a minimal ConfigManager without AWS calls
# ---------------------------------------------------------------------------

def _create_config_manager_minimal():
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        return cm


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe regex patterns that are always valid and testable
safe_patterns = st.sampled_from([
    r'^[a-z]+$',
    r'^[A-Z]+$',
    r'^[0-9]+$',
    r'^[a-z0-9]+$',
    r'^[a-zA-Z]+$',
    r'^[a-z]{2,8}$',
    r'^[0-9]{3}$',
    r'^[a-z][a-z0-9]*$',
    r'^[A-Z][a-zA-Z0-9]*$',
    r'^[a-z0-9\-]+$',
    r'^[a-zA-Z0-9_]+$',
    r'^[a-z]{1,4}$',
    r'^[0-9]{1,5}$',
    r'^[a-z][a-z0-9\-]{0,10}$',
    r'^(dev|test|prod)$',
    r'^(DEV|TEST|PROD)$',
])

# Values to test against patterns - mix of likely matches and non-matches
test_values = st.text(
    alphabet=st.characters(
        whitelist_categories=('L', 'N'),
        whitelist_characters='-_',
    ),
    min_size=0,
    max_size=20,
)

# Strategy for AllowedValues lists
allowed_values_list = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=('L', 'N')),
        min_size=1,
        max_size=10,
    ),
    min_size=1,
    max_size=10,
    unique=True,
)

# Strategy for string values used in length tests
length_test_values = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
    min_size=0,
    max_size=50,
)

# Strategy for min/max length bounds
min_length_strategy = st.integers(min_value=0, max_value=25)
max_length_strategy = st.integers(min_value=0, max_value=50)


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
# ---------------------------------------------------------------------------

class TestParameterValidationAllowedPattern:
    """Property 9: Parameter validation correctness - AllowedPattern.

    For any string value and parameter definition with an AllowedPattern constraint,
    validate_parameter() SHALL return valid=True if and only if the value matches
    the regex pattern.

    Validates: Requirements 7.2, 7.4
    """

    @given(pattern=safe_patterns, value=test_values)
    @settings(max_examples=100)
    def test_allowed_pattern_validity(self, pattern, value):
        """validate_parameter returns valid=True iff value matches the AllowedPattern."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        assume(len(value) > 0)  # Skip empty values (they have special handling with Default)

        cm = _create_config_manager_minimal()
        param_def = {
            'Type': 'String',
            'AllowedPattern': pattern,
        }

        result = cm.validate_parameter(value, param_def)

        # Determine expected validity by matching the pattern ourselves
        expected_valid = bool(re.match(pattern, value))

        assert result['valid'] == expected_valid, (
            f"For pattern='{pattern}', value='{value}': "
            f"expected valid={expected_valid}, got valid={result['valid']}"
        )

    @given(pattern=safe_patterns, value=test_values)
    @settings(max_examples=100)
    def test_allowed_pattern_invalid_gives_reason(self, pattern, value):
        """When validation fails due to AllowedPattern, a reason is provided."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        assume(len(value) > 0)

        cm = _create_config_manager_minimal()
        param_def = {
            'Type': 'String',
            'AllowedPattern': pattern,
        }

        result = cm.validate_parameter(value, param_def)

        if not result['valid']:
            assert 'reason' in result
            assert len(result['reason']) > 0


class TestParameterValidationAllowedValues:
    """Property 9: Parameter validation correctness - AllowedValues.

    For any value and AllowedValues list, validate_parameter() SHALL return
    valid=True if and only if the value is a member of the list.

    Validates: Requirements 7.2, 7.4
    """

    @given(
        allowed_values=allowed_values_list,
        use_valid=st.booleans(),
    )
    @settings(max_examples=100)
    def test_allowed_values_membership(self, allowed_values, use_valid):
        """validate_parameter returns valid=True iff value is in AllowedValues list."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        cm = _create_config_manager_minimal()

        if use_valid:
            # Pick a value from the allowed list
            value = allowed_values[0]
        else:
            # Generate a value guaranteed not to be in the list
            value = "NOTINLIST_" + "_".join(allowed_values)

        param_def = {
            'Type': 'String',
            'AllowedValues': allowed_values,
        }

        result = cm.validate_parameter(value, param_def)

        expected_valid = value in allowed_values

        assert result['valid'] == expected_valid, (
            f"For AllowedValues={allowed_values}, value='{value}': "
            f"expected valid={expected_valid}, got valid={result['valid']}"
        )

    @given(allowed_values=allowed_values_list)
    @settings(max_examples=100)
    def test_allowed_values_all_members_valid(self, allowed_values):
        """Every member of AllowedValues should validate as valid."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        cm = _create_config_manager_minimal()

        param_def = {
            'Type': 'String',
            'AllowedValues': allowed_values,
        }

        for value in allowed_values:
            result = cm.validate_parameter(value, param_def)
            assert result['valid'] is True, (
                f"Value '{value}' is in AllowedValues but validated as invalid"
            )


class TestParameterValidationMinMaxLength:
    """Property 9: Parameter validation correctness - MinLength/MaxLength.

    For any string value with MinLength/MaxLength constraints,
    validate_parameter() SHALL return valid=True if and only if
    len(value) is within bounds.

    Validates: Requirements 7.2, 7.4
    """

    @given(
        value=length_test_values,
        min_length=min_length_strategy,
        max_length=max_length_strategy,
    )
    @settings(max_examples=100)
    def test_min_max_length_validity(self, value, min_length, max_length):
        """validate_parameter returns valid=True iff len(value) is within [min_length, max_length]."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        assume(min_length <= max_length)  # Only test valid constraint combinations
        assume(len(value) > 0)  # Skip empty values (special handling with Default)

        cm = _create_config_manager_minimal()
        param_def = {
            'Type': 'String',
            'MinLength': str(min_length),
            'MaxLength': str(max_length),
        }

        result = cm.validate_parameter(value, param_def)

        expected_valid = min_length <= len(value) <= max_length

        assert result['valid'] == expected_valid, (
            f"For value='{value}' (len={len(value)}), "
            f"MinLength={min_length}, MaxLength={max_length}: "
            f"expected valid={expected_valid}, got valid={result['valid']}"
        )

    @given(
        value=length_test_values,
        min_length=min_length_strategy,
    )
    @settings(max_examples=100)
    def test_min_length_only(self, value, min_length):
        """With only MinLength defined, valid iff len(value) >= min_length."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        assume(len(value) > 0)  # Skip empty values

        cm = _create_config_manager_minimal()
        param_def = {
            'Type': 'String',
            'MinLength': str(min_length),
        }

        result = cm.validate_parameter(value, param_def)

        expected_valid = len(value) >= min_length

        assert result['valid'] == expected_valid, (
            f"For value='{value}' (len={len(value)}), MinLength={min_length}: "
            f"expected valid={expected_valid}, got valid={result['valid']}"
        )

    @given(
        value=length_test_values,
        max_length=max_length_strategy,
    )
    @settings(max_examples=100)
    def test_max_length_only(self, value, max_length):
        """With only MaxLength defined, valid iff len(value) <= max_length."""
        # Feature: headless-skeleton-mode, Property 9: Parameter validation correctness
        assume(len(value) > 0)  # Skip empty values

        cm = _create_config_manager_minimal()
        param_def = {
            'Type': 'String',
            'MaxLength': str(max_length),
        }

        result = cm.validate_parameter(value, param_def)

        expected_valid = len(value) <= max_length

        assert result['valid'] == expected_valid, (
            f"For value='{value}' (len={len(value)}), MaxLength={max_length}: "
            f"expected valid={expected_valid}, got valid={result['valid']}"
        )
