"""Unit tests for validate_mode_flags() in cli/config.py.

Tests mutual exclusivity of mode flags, skeleton-verbose precedence,
and that valid flag combinations pass without error.

Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

import argparse
import sys
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'cli'))

from config import validate_mode_flags


def _make_args(**kwargs):
    """Create an argparse.Namespace with default flag values, overridden by kwargs."""
    defaults = {
        'skeleton': False,
        'skeleton_verbose': False,
        'headless': False,
        'deploy': False,
        'check_stack': False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestMutuallyExclusiveFlags:
    """Test that mutually exclusive flag combinations cause sys.exit."""

    def test_skeleton_and_headless_exits(self):
        """--skeleton + --headless should exit with 'mutually exclusive' error."""
        args = _make_args(skeleton=True, headless=True)
        with pytest.raises(SystemExit) as exc_info:
            validate_mode_flags(args)
        assert "mutually exclusive" in str(exc_info.value)

    def test_skeleton_verbose_and_headless_exits(self):
        """--skeleton-verbose + --headless should exit with 'mutually exclusive' error."""
        args = _make_args(skeleton_verbose=True, headless=True)
        with pytest.raises(SystemExit) as exc_info:
            validate_mode_flags(args)
        assert "mutually exclusive" in str(exc_info.value)


class TestCheckStackIncompatibility:
    """Test that --check-stack is incompatible with skeleton/headless flags."""

    def test_check_stack_and_skeleton_exits(self):
        """--check-stack + --skeleton should exit with 'incompatible' error."""
        args = _make_args(check_stack=True, skeleton=True)
        with pytest.raises(SystemExit) as exc_info:
            validate_mode_flags(args)
        assert "incompatible" in str(exc_info.value).lower()

    def test_check_stack_and_skeleton_verbose_exits(self):
        """--check-stack + --skeleton-verbose should exit with 'incompatible' error."""
        args = _make_args(check_stack=True, skeleton_verbose=True)
        with pytest.raises(SystemExit) as exc_info:
            validate_mode_flags(args)
        assert "incompatible" in str(exc_info.value).lower()

    def test_check_stack_and_headless_exits(self):
        """--check-stack + --headless should exit with 'incompatible' error."""
        args = _make_args(check_stack=True, headless=True)
        with pytest.raises(SystemExit) as exc_info:
            validate_mode_flags(args)
        assert "incompatible" in str(exc_info.value).lower()


class TestSkeletonVerbosePrecedence:
    """Test that --skeleton + --skeleton-verbose resolves to skeleton-verbose."""

    def test_skeleton_plus_skeleton_verbose_sets_skeleton_false(self):
        """When both --skeleton and --skeleton-verbose are set, args.skeleton becomes False."""
        args = _make_args(skeleton=True, skeleton_verbose=True)
        validate_mode_flags(args)
        assert args.skeleton is False
        assert args.skeleton_verbose is True


class TestValidFlagCombinations:
    """Test that valid flag combinations pass validation without error."""

    def test_no_mode_flags_passes(self):
        """No mode flags (interactive flow) should pass validation without error."""
        args = _make_args()
        # Should not raise
        validate_mode_flags(args)

    def test_skeleton_only_passes(self):
        """--skeleton alone should pass validation."""
        args = _make_args(skeleton=True)
        validate_mode_flags(args)

    def test_skeleton_verbose_only_passes(self):
        """--skeleton-verbose alone should pass validation."""
        args = _make_args(skeleton_verbose=True)
        validate_mode_flags(args)

    def test_headless_only_passes(self):
        """--headless alone should pass validation."""
        args = _make_args(headless=True)
        validate_mode_flags(args)

    def test_headless_with_deploy_passes(self):
        """--headless + --deploy should pass validation."""
        args = _make_args(headless=True, deploy=True)
        validate_mode_flags(args)
