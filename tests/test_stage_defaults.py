"""Property-based tests for stage calculated defaults in cli/config.py.

Uses Hypothesis for property-based testing with minimum 100 iterations.
"""
# Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import ConfigManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for stage_id: random lowercase alphanumeric strings 1-10 chars,
# plus specific values like "prod", "dev", "test"
stage_id_strategy = st.one_of(
    st.text(
        alphabet=st.characters(
            whitelist_categories=(),
            whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789",
        ),
        min_size=1,
        max_size=10,
    ),
    st.sampled_from(["prod", "dev", "test", "demo", "beta", "stage", "testing", "development"]),
)


# ---------------------------------------------------------------------------
# Helper to create a minimal ConfigManager without AWS calls
# ---------------------------------------------------------------------------

def _create_config_manager_minimal():
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        return cm


# ---------------------------------------------------------------------------
# Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules
# ---------------------------------------------------------------------------

class TestStageCalculatedDefaultsProperty:
    """Property 6: Stage calculated defaults follow derivation rules.

    For any stage_id string, calculate_stage_defaults() SHALL return:
    - DeployEnvironment="DEV" if stage_id starts with "d", "TEST" if starts with "t", "PROD" otherwise
    - RepositoryBranch="main" if stage_id=="prod", else equals stage_id
    - CodeCommitBranch="main" if stage_id=="prod", else equals stage_id

    Validates: Requirements 3.3
    """

    @given(stage_id=stage_id_strategy)
    @settings(max_examples=100)
    def test_deploy_environment_derivation(self, stage_id):
        """DeployEnvironment is DEV if stage_id starts with 'd', TEST if starts with 't', PROD otherwise."""
        # Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules
        cm = _create_config_manager_minimal()
        result = cm.calculate_stage_defaults(stage_id)

        if stage_id.startswith('d'):
            expected_env = 'DEV'
        elif stage_id.startswith('t'):
            expected_env = 'TEST'
        else:
            expected_env = 'PROD'

        assert result['DeployEnvironment'] == expected_env, (
            f"For stage_id='{stage_id}', expected DeployEnvironment='{expected_env}', "
            f"got '{result['DeployEnvironment']}'"
        )

    @given(stage_id=stage_id_strategy)
    @settings(max_examples=100)
    def test_repository_branch_derivation(self, stage_id):
        """RepositoryBranch is 'main' if stage_id=='prod', else equals stage_id."""
        # Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules
        cm = _create_config_manager_minimal()
        result = cm.calculate_stage_defaults(stage_id)

        if stage_id == 'prod':
            expected_branch = 'main'
        else:
            expected_branch = stage_id

        assert result['RepositoryBranch'] == expected_branch, (
            f"For stage_id='{stage_id}', expected RepositoryBranch='{expected_branch}', "
            f"got '{result['RepositoryBranch']}'"
        )

    @given(stage_id=stage_id_strategy)
    @settings(max_examples=100)
    def test_codecommit_branch_derivation(self, stage_id):
        """CodeCommitBranch is 'main' if stage_id=='prod', else equals stage_id."""
        # Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules
        cm = _create_config_manager_minimal()
        result = cm.calculate_stage_defaults(stage_id)

        if stage_id == 'prod':
            expected_branch = 'main'
        else:
            expected_branch = stage_id

        assert result['CodeCommitBranch'] == expected_branch, (
            f"For stage_id='{stage_id}', expected CodeCommitBranch='{expected_branch}', "
            f"got '{result['CodeCommitBranch']}'"
        )

    @given(stage_id=stage_id_strategy)
    @settings(max_examples=100)
    def test_all_three_keys_present(self, stage_id):
        """calculate_stage_defaults always returns all three keys: DeployEnvironment, RepositoryBranch, CodeCommitBranch."""
        # Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules
        cm = _create_config_manager_minimal()
        result = cm.calculate_stage_defaults(stage_id)

        assert 'DeployEnvironment' in result, "Missing 'DeployEnvironment' key in result"
        assert 'RepositoryBranch' in result, "Missing 'RepositoryBranch' key in result"
        assert 'CodeCommitBranch' in result, "Missing 'CodeCommitBranch' key in result"

    @given(stage_id=stage_id_strategy)
    @settings(max_examples=100)
    def test_repository_and_codecommit_branch_are_equal(self, stage_id):
        """RepositoryBranch and CodeCommitBranch always have the same value."""
        # Feature: headless-skeleton-mode, Property 6: Stage calculated defaults follow derivation rules
        cm = _create_config_manager_minimal()
        result = cm.calculate_stage_defaults(stage_id)

        assert result['RepositoryBranch'] == result['CodeCommitBranch'], (
            f"For stage_id='{stage_id}', RepositoryBranch='{result['RepositoryBranch']}' "
            f"!= CodeCommitBranch='{result['CodeCommitBranch']}'"
        )
