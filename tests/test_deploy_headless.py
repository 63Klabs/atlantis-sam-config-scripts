"""Unit tests for deploy.py headless mode.

Tests that the --headless flag correctly:
- Is parsed as store_true defaulting to False
- Suppresses prompts and forces confirm_changeset=false
- Calls headless git operations instead of interactive ones
- Propagates exit codes on failure

Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 10.7, 10.8, 10.9
"""

import subprocess
import sys
import os
from unittest.mock import patch, MagicMock, call
from argparse import Namespace

import pytest

# Add cli/ to path so deploy.py can resolve its relative imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from deploy import parse_args, main, TemplateDeployer


class TestParseArgsHeadlessFlag:
    """Tests for --headless flag parsing in deploy.py (Req 10.1)."""

    def test_headless_flag_defaults_to_false(self):
        """--headless defaults to False when not provided."""
        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev"]):
            args = parse_args()
            assert args.headless is False

    def test_headless_flag_store_true(self):
        """--headless is parsed as store_true."""
        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            args = parse_args()
            assert args.headless is True

    def test_headless_flag_with_other_args(self):
        """--headless works alongside other optional flags."""
        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless", "--no-browser"]):
            args = parse_args()
            assert args.headless is True
            assert args.no_browser is True


class TestMainHeadlessGitPull:
    """Tests that headless mode calls Git.headless_git_pull() (Req 10.2, 10.6)."""

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_headless_calls_headless_git_pull(self, mock_git_cls, mock_deployer_cls):
        """When --headless is set, Git.headless_git_pull() is called instead of prompt_git_pull()."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                main()

        mock_git_cls.headless_git_pull.assert_called_once()
        mock_git_cls.prompt_git_pull.assert_not_called()

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_non_headless_calls_prompt_git_pull(self, mock_git_cls, mock_deployer_cls):
        """When --headless is NOT set, Git.prompt_git_pull() is called (Req 10.2)."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev"]):
            with patch("deploy.Log"):
                main()

        mock_git_cls.prompt_git_pull.assert_called_once()
        mock_git_cls.headless_git_pull.assert_not_called()

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_headless_git_pull_failure_aborts(self, mock_git_cls, mock_deployer_cls):
        """When headless git pull fails (SystemExit), deployment is aborted (Req 10.6)."""
        mock_git_cls.headless_git_pull.side_effect = SystemExit("Error: git pull failed: remote error")

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert "git pull failed" in str(exc_info.value)
        # Deployer should never be instantiated if git pull fails
        mock_deployer_cls.assert_not_called()


class TestMainHeadlessConfirmChangeset:
    """Tests that headless mode forces confirm_changeset=false (Req 10.3, 10.9)."""

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_headless_sets_override_confirm_changeset(self, mock_git_cls, mock_deployer_cls):
        """When --headless is set, deployer.override_confirm_changeset is set to True."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                main()

        # Verify override_confirm_changeset was set to True
        assert mock_deployer.override_confirm_changeset is True

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_non_headless_does_not_set_override_confirm_changeset(self, mock_git_cls, mock_deployer_cls):
        """When --headless is NOT set, override_confirm_changeset remains False."""
        mock_deployer = MagicMock()
        mock_deployer.override_confirm_changeset = False
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev"]):
            with patch("deploy.Log"):
                main()

        # override_confirm_changeset should not have been set to True
        assert mock_deployer.override_confirm_changeset is False


class TestMainHeadlessGitCommitAndPush:
    """Tests that headless mode calls Git.headless_git_commit_and_push() on success (Req 10.4, 10.7)."""

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_headless_success_calls_headless_git_commit_and_push(self, mock_git_cls, mock_deployer_cls):
        """When --headless and deployment succeeds, Git.headless_git_commit_and_push() is called (Req 10.4)."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                main()

        mock_git_cls.headless_git_commit_and_push.assert_called_once()
        # Verify commit message contains infra_type, prefix, project_id, stage_id
        commit_msg = mock_git_cls.headless_git_commit_and_push.call_args[0][0]
        assert "pipeline" in commit_msg
        assert "acme" in commit_msg
        assert "myapp" in commit_msg
        assert "dev" in commit_msg

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_headless_failure_does_not_call_git_commit(self, mock_git_cls, mock_deployer_cls):
        """When --headless and deployment fails, git commit/push is NOT called."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 1  # failure
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                exit_code = main()

        mock_git_cls.headless_git_commit_and_push.assert_not_called()
        assert exit_code == 1

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_headless_git_commit_failure_exits(self, mock_git_cls, mock_deployer_cls):
        """When headless git commit/push fails, sys.exit is raised (Req 10.7)."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        mock_git_cls.headless_git_commit_and_push.side_effect = SystemExit(
            "Error: git push failed: remote: Permission denied"
        )

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert "git push failed" in str(exc_info.value)

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_non_headless_success_calls_interactive_git_commit(self, mock_git_cls, mock_deployer_cls):
        """When NOT headless and deployment succeeds, Git.git_commit_and_push() is called."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev"]):
            with patch("deploy.Log"):
                main()

        mock_git_cls.git_commit_and_push.assert_called_once()
        mock_git_cls.headless_git_commit_and_push.assert_not_called()


class TestMainExitCodePropagation:
    """Tests that exit codes are propagated correctly (Req 10.8)."""

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_successful_deployment_returns_zero(self, mock_git_cls, mock_deployer_cls):
        """Successful deployment returns exit code 0 (Req 10.8)."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 0
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                exit_code = main()

        assert exit_code == 0

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_failed_deployment_propagates_nonzero_exit_code(self, mock_git_cls, mock_deployer_cls):
        """Non-zero exit from deploy propagates as return value."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.return_value = "s3://bucket/template.yml"
        mock_deployer.deploy_with_temp_template.return_value = 2  # SAM deploy failure
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                exit_code = main()

        assert exit_code == 2

    @patch("deploy.TemplateDeployer")
    @patch("deploy.Git")
    def test_value_error_returns_exit_code_1(self, mock_git_cls, mock_deployer_cls):
        """ValueError from get_template_from_config returns exit code 1."""
        mock_deployer = MagicMock()
        mock_deployer.get_template_from_config.side_effect = ValueError("Config file not found")
        mock_deployer_cls.return_value = mock_deployer

        with patch("sys.argv", ["deploy.py", "pipeline", "acme", "myapp", "dev", "--headless"]):
            with patch("deploy.Log"):
                exit_code = main()

        assert exit_code == 1
