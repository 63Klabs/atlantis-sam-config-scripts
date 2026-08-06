"""Unit tests for the CloudFormation branch formatting/confirmation in deploy.py.

Covers the new CFN-branch behavior added to ``_cfn_deploy_packaged`` and its
private helpers on ``TemplateDeployer``:

    - ``_print_deploy_values_summary`` — pre-deploy values summary field
      conditions (Role ARN only when non-empty; Deployment s3 bucket only on the
      S3-upload path; compact ``{Key: Value}`` rendering).
    - ``_print_changeset_summary`` — changeset listing rendering (Action /
      LogicalId / Type, plus Replacement / PhysicalId when present).
    - ``_print_success_banner`` / ``_print_stack_outputs`` — success banner and
      Outputs listing (and no Outputs section when empty).
    - ``_wait_for_stack_operation`` — polling loop success / failure / timeout and
      green in-progress status output.
    - ``_cfn_deploy_packaged`` — confirmation gate matrix
      (confirm_changeset x headless/override_confirm_changeset), empty-changeset
      no-op, and accept/headless -> execute_change_set.

All AWS calls are mocked; the CloudFormation client is a ``MagicMock``.

Requirements: R1, R3, R4, R5, R6, R7, R8, R9
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add cli/ to path so deploy.py can resolve its relative imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from deploy import TemplateDeployer


def make_deployer(override_confirm_changeset=False):
    """Create a TemplateDeployer with __init__ bypassed for helper-level tests.

    Args:
        override_confirm_changeset (bool): Value for the deployer's
            ``override_confirm_changeset`` flag (headless when True).

    Returns:
        TemplateDeployer: An instance with the minimum attributes needed by the
        formatting/confirmation helpers and ``_cfn_deploy_packaged``.
    """
    with patch.object(TemplateDeployer, '__init__', return_value=None):
        deployer = TemplateDeployer.__new__(TemplateDeployer)
        deployer.stage_id = 'default'
        deployer.profile = None
        deployer.settings = {}
        deployer.override_confirm_changeset = override_confirm_changeset
        deployer.s3_client = MagicMock()
        deployer.s3_client_anonymous = MagicMock()
        deployer.aws_session = MagicMock()
        deployer.infra_type = 'pipeline'
        deployer.prefix = 'acme'
        deployer.project_id = 'myapp'
    return deployer


def base_deploy_params(**overrides):
    """Build a deploy_params dict resembling ``_read_deploy_params_for_packaged``.

    Args:
        **overrides: Keys to override on the returned dict.

    Returns:
        dict: Deploy parameters with sensible defaults.
    """
    params = {
        'stack_name': 'acme-myapp-test-pipeline',
        'capabilities': 'CAPABILITY_NAMED_IAM',
        'region': 'us-east-1',
        'role_arn': '',
        'confirm_changeset': True,
        'parameter_overrides': 'Env=test Prefix=acme',
        'tags': 'Project=acme',
    }
    params.update(overrides)
    return params


# =============================================================================
# _print_deploy_values_summary
# =============================================================================

class TestPrintDeployValuesSummary:
    """Unit tests for TemplateDeployer._print_deploy_values_summary (R1)."""

    def setup_method(self):
        self.deployer = make_deployer()

    def test_always_present_fields(self, capsys):
        """Summary includes the always-present fields (R1.1, R1.2)."""
        self.deployer._print_deploy_values_summary(
            base_deploy_params(),
            [{'ParameterKey': 'Env', 'ParameterValue': 'test'}],
            [{'Key': 'Project', 'Value': 'acme'}],
        )
        out = capsys.readouterr().out
        assert 'Deploying with following values' in out
        assert 'Stack name' in out
        assert 'acme-myapp-test-pipeline' in out
        assert 'Region' in out
        assert 'us-east-1' in out
        assert 'Confirm changeset' in out
        assert 'Capabilities' in out
        assert 'CAPABILITY_NAMED_IAM' in out
        assert 'Parameter overrides' in out
        assert 'Tags' in out

    def test_role_arn_omitted_when_empty(self, capsys):
        """Role ARN line is omitted when role_arn is empty (R1.3)."""
        self.deployer._print_deploy_values_summary(
            base_deploy_params(role_arn=''), [], []
        )
        out = capsys.readouterr().out
        assert 'Role ARN' not in out

    def test_role_arn_present_when_configured(self, capsys):
        """Role ARN line appears when role_arn is non-empty (R1.3)."""
        arn = 'arn:aws:iam::123456789012:role/deploy-role'
        self.deployer._print_deploy_values_summary(
            base_deploy_params(role_arn=arn), [], []
        )
        out = capsys.readouterr().out
        assert 'Role ARN' in out
        assert arn in out

    def test_s3_bucket_omitted_when_not_uploaded(self, capsys):
        """Deployment s3 bucket line is omitted when no S3 upload occurred (R1.4)."""
        self.deployer._print_deploy_values_summary(
            base_deploy_params(), [], [], s3_bucket_display=None
        )
        out = capsys.readouterr().out
        assert 'Deployment s3 bucket' not in out

    def test_s3_bucket_present_on_upload_path(self, capsys):
        """Deployment s3 bucket line appears on the S3-upload path (R1.4)."""
        self.deployer._print_deploy_values_summary(
            base_deploy_params(), [], [], s3_bucket_display='my-artifacts-bucket'
        )
        out = capsys.readouterr().out
        assert 'Deployment s3 bucket' in out
        assert 'my-artifacts-bucket' in out

    def test_disable_rollback_and_signing_profiles_omitted(self, capsys):
        """Disable rollback and Signing Profiles are never printed (R1.5)."""
        self.deployer._print_deploy_values_summary(base_deploy_params(), [], [])
        out = capsys.readouterr().out
        assert 'Disable rollback' not in out
        assert 'Signing Profiles' not in out

    def test_compact_key_value_rendering(self, capsys):
        """Parameter overrides and Tags render compactly as {Key: Value, ...} (R1.6)."""
        self.deployer._print_deploy_values_summary(
            base_deploy_params(),
            [
                {'ParameterKey': 'Env', 'ParameterValue': 'test'},
                {'ParameterKey': 'Prefix', 'ParameterValue': 'acme'},
            ],
            [{'Key': 'Project', 'Value': 'acme'}],
        )
        out = capsys.readouterr().out
        assert '{Env: test, Prefix: acme}' in out
        assert '{Project: acme}' in out

    def test_empty_pairs_render_as_empty_braces(self, capsys):
        """Empty parameter/tag lists render as ``{}`` (R1.6)."""
        self.deployer._print_deploy_values_summary(base_deploy_params(), [], [])
        out = capsys.readouterr().out
        assert '{}' in out


# =============================================================================
# _print_changeset_summary
# =============================================================================

class TestPrintChangesetSummary:
    """Unit tests for TemplateDeployer._print_changeset_summary (R3)."""

    def setup_method(self):
        self.deployer = make_deployer()

    def test_renders_action_logical_id_and_type(self, capsys):
        """Each change renders Action, LogicalResourceId and ResourceType (R3.2)."""
        changes = [
            {'ResourceChange': {
                'Action': 'Add',
                'LogicalResourceId': 'MyBucket',
                'ResourceType': 'AWS::S3::Bucket',
            }},
            {'ResourceChange': {
                'Action': 'Modify',
                'LogicalResourceId': 'MyFunction',
                'ResourceType': 'AWS::Lambda::Function',
            }},
        ]
        self.deployer._print_changeset_summary(changes)
        out = capsys.readouterr().out
        assert 'Changeset' in out
        assert 'Action' in out
        assert 'LogicalResourceId' in out
        assert 'ResourceType' in out
        assert 'Add' in out
        assert 'MyBucket' in out
        assert 'AWS::S3::Bucket' in out
        assert 'Modify' in out
        assert 'MyFunction' in out
        assert 'AWS::Lambda::Function' in out

    def test_replacement_and_physical_id_shown_when_present(self, capsys):
        """Replacement and PhysicalResourceId columns appear when present (R3.2)."""
        changes = [
            {'ResourceChange': {
                'Action': 'Modify',
                'LogicalResourceId': 'MyFunction',
                'ResourceType': 'AWS::Lambda::Function',
                'Replacement': 'True',
                'PhysicalResourceId': 'acme-my-function',
            }},
        ]
        self.deployer._print_changeset_summary(changes)
        out = capsys.readouterr().out
        assert 'Replacement' in out
        assert 'True' in out
        assert 'PhysicalResourceId' in out
        assert 'acme-my-function' in out

    def test_replacement_and_physical_id_omitted_when_absent(self, capsys):
        """Replacement / PhysicalResourceId columns are omitted when absent (R3.2)."""
        changes = [
            {'ResourceChange': {
                'Action': 'Add',
                'LogicalResourceId': 'MyBucket',
                'ResourceType': 'AWS::S3::Bucket',
            }},
        ]
        self.deployer._print_changeset_summary(changes)
        out = capsys.readouterr().out
        assert 'Replacement' not in out
        assert 'PhysicalResourceId' not in out

    def test_no_raw_json_printed(self, capsys):
        """The listing does not dump raw change set JSON (R3.4)."""
        changes = [
            {'ResourceChange': {
                'Action': 'Add',
                'LogicalResourceId': 'MyBucket',
                'ResourceType': 'AWS::S3::Bucket',
            }},
        ]
        self.deployer._print_changeset_summary(changes)
        out = capsys.readouterr().out
        assert 'ResourceChange' not in out
        assert "{'" not in out


# =============================================================================
# _print_success_banner / _print_stack_outputs
# =============================================================================

class TestSuccessBannerAndOutputs:
    """Unit tests for the success banner and Outputs helpers (R7)."""

    def setup_method(self):
        self.deployer = make_deployer()

    def test_success_banner_printed(self, capsys):
        """The success banner prints a completion message (R7.1)."""
        self.deployer._print_success_banner()
        out = capsys.readouterr().out
        assert 'Successfully deployed stack' in out

    def test_outputs_listed_when_present(self, capsys):
        """Each Output is listed under an Outputs heading (R7.2)."""
        outputs = [
            {'OutputKey': 'ApiUrl',
             'OutputValue': 'https://api.example.com',
             'Description': 'Base URL of the deployed API'},
            {'OutputKey': 'BucketName', 'OutputValue': 'acme-bucket'},
        ]
        self.deployer._print_stack_outputs(outputs)
        out = capsys.readouterr().out
        assert 'Outputs' in out
        assert 'ApiUrl' in out
        assert 'https://api.example.com' in out
        assert 'Base URL of the deployed API' in out
        assert 'BucketName' in out
        assert 'acme-bucket' in out

    def test_no_outputs_section_when_empty(self, capsys):
        """No Outputs section is printed when the list is empty (R7.3)."""
        self.deployer._print_stack_outputs([])
        out = capsys.readouterr().out
        assert out.strip() == ''


# =============================================================================
# _wait_for_stack_operation
# =============================================================================

class TestWaitForStackOperation:
    """Unit tests for TemplateDeployer._wait_for_stack_operation (R6)."""

    def setup_method(self):
        self.deployer = make_deployer()

    def test_success_after_in_progress_prints_green_status(self, capsys):
        """Loop returns True and prints in-progress status per cycle (R6.2)."""
        cfn = MagicMock()
        cfn.describe_stacks.side_effect = [
            {'Stacks': [{'StackStatus': 'UPDATE_IN_PROGRESS'}]},
            {'Stacks': [{'StackStatus': 'UPDATE_COMPLETE'}]},
        ]
        with patch('time.sleep'):
            with patch('deploy.ConsoleAndLog'):
                result = self.deployer._wait_for_stack_operation(
                    cfn, 'my-stack', 'UPDATE')

        assert result is True
        out = capsys.readouterr().out
        assert 'Stack update in progress' in out
        assert 'UPDATE_IN_PROGRESS' in out

    def test_failure_status_returns_false(self):
        """A failure status makes the loop return False (R6.1)."""
        cfn = MagicMock()
        cfn.describe_stacks.side_effect = [
            {'Stacks': [{'StackStatus': 'UPDATE_IN_PROGRESS'}]},
            {'Stacks': [{'StackStatus': 'UPDATE_ROLLBACK_COMPLETE'}]},
        ]
        with patch('time.sleep'):
            with patch('deploy.ConsoleAndLog'):
                result = self.deployer._wait_for_stack_operation(
                    cfn, 'my-stack', 'UPDATE')

        assert result is False

    def test_timeout_returns_false(self):
        """Exceeding the polling cap returns False (R6.4)."""
        cfn = MagicMock()
        cfn.describe_stacks.return_value = {
            'Stacks': [{'StackStatus': 'UPDATE_IN_PROGRESS'}]
        }
        with patch('time.sleep'):
            with patch('deploy.ConsoleAndLog'):
                result = self.deployer._wait_for_stack_operation(
                    cfn, 'my-stack', 'UPDATE')

        assert result is False

    def test_keyboard_interrupt_exits_nonzero(self):
        """KeyboardInterrupt during the wait exits with status 1 (R6.5)."""
        cfn = MagicMock()
        cfn.describe_stacks.side_effect = KeyboardInterrupt()
        with patch('time.sleep'):
            with patch('deploy.Log'):
                with pytest.raises(SystemExit) as exc_info:
                    self.deployer._wait_for_stack_operation(
                        cfn, 'my-stack', 'UPDATE')

        assert exc_info.value.code == 1


# =============================================================================
# _cfn_deploy_packaged — confirmation gate matrix, empty no-op, banner/outputs
# =============================================================================

SMALL_TEMPLATE = """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
"""


def make_cfn_client(has_changes=True, empty_changeset=False, outputs=None):
    """Build a mock CloudFormation client for _cfn_deploy_packaged flow tests.

    Args:
        has_changes (bool): When True (and not empty), describe_change_set
            returns a change with one resource.
        empty_changeset (bool): When True, the change_set_create_complete waiter
            raises and describe_change_set reports the "didn't contain changes"
            reason (empty-changeset no-op path).
        outputs (list, optional): Outputs returned by describe_stacks after a
            successful deploy. Defaults to an empty list.

    Returns:
        MagicMock: A configured CloudFormation client mock.
    """
    cfn = MagicMock()

    # describe_stacks is used for: stack existence check, the polling loop, and
    # the post-success Outputs read. A single UPDATE_COMPLETE response satisfies
    # all three (existence -> UPDATE, poll -> success immediately, outputs read).
    cfn.describe_stacks.return_value = {
        'Stacks': [{
            'StackStatus': 'UPDATE_COMPLETE',
            'Outputs': outputs if outputs is not None else [],
        }]
    }

    waiter = MagicMock()
    if empty_changeset:
        waiter.wait.side_effect = Exception('waiter failed')
        cfn.describe_change_set.return_value = {
            'Status': 'FAILED',
            'StatusReason': "The submitted information didn't contain changes.",
        }
    else:
        changes = [] if not has_changes else [
            {'ResourceChange': {
                'Action': 'Add',
                'LogicalResourceId': 'MyBucket',
                'ResourceType': 'AWS::S3::Bucket',
            }},
        ]
        cfn.describe_change_set.return_value = {
            'Status': 'CREATE_COMPLETE',
            'Changes': changes,
        }
    cfn.get_waiter.return_value = waiter

    return cfn


def run_packaged_deploy(deployer, cfn, tmp_path, deploy_params):
    """Invoke _cfn_deploy_packaged with the CFN client wired to the deployer.

    Args:
        deployer (TemplateDeployer): The deployer under test.
        cfn (MagicMock): The mock CloudFormation client to return from the
            session.
        tmp_path: pytest tmp_path fixture for the on-disk template file.
        deploy_params (dict): Deploy parameters passed to the method.

    Returns:
        int: The exit code returned by _cfn_deploy_packaged.
    """
    template_file = tmp_path / 'template-resolved.yml'
    template_file.write_text(SMALL_TEMPLATE)
    deployer.aws_session.get_client.return_value = cfn
    with patch('time.sleep'):
        with patch('deploy.ConsoleAndLog'):
            with patch('deploy.Log'):
                return deployer._cfn_deploy_packaged(template_file, deploy_params)


class TestCfnDeployConfirmationGate:
    """Confirmation gate matrix for _cfn_deploy_packaged (R4)."""

    def test_confirm_true_interactive_accept_executes(self, tmp_path):
        """confirm_changeset + interactive + accept -> execute_change_set (R4.1)."""
        deployer = make_deployer(override_confirm_changeset=False)
        cfn = make_cfn_client(has_changes=True)
        with patch('deploy.click.confirm', return_value=True) as mock_confirm:
            result = run_packaged_deploy(
                deployer, cfn, tmp_path,
                base_deploy_params(confirm_changeset=True))

        assert result == 0
        mock_confirm.assert_called_once()
        cfn.execute_change_set.assert_called_once()

    def test_confirm_true_interactive_decline_deletes_and_returns_1(self, tmp_path):
        """Declining deletes the change set and returns 1; no execute (R4.3)."""
        deployer = make_deployer(override_confirm_changeset=False)
        cfn = make_cfn_client(has_changes=True)
        with patch('deploy.click.confirm', return_value=False) as mock_confirm:
            result = run_packaged_deploy(
                deployer, cfn, tmp_path,
                base_deploy_params(confirm_changeset=True))

        assert result == 1
        mock_confirm.assert_called_once()
        cfn.execute_change_set.assert_not_called()
        cfn.delete_change_set.assert_called_once()

    def test_confirm_false_skips_prompt_and_executes(self, tmp_path):
        """confirm_changeset false -> no prompt, execute_change_set (R4.2)."""
        deployer = make_deployer(override_confirm_changeset=False)
        cfn = make_cfn_client(has_changes=True)
        with patch('deploy.click.confirm') as mock_confirm:
            result = run_packaged_deploy(
                deployer, cfn, tmp_path,
                base_deploy_params(confirm_changeset=False))

        assert result == 0
        mock_confirm.assert_not_called()
        cfn.execute_change_set.assert_called_once()

    def test_headless_override_skips_prompt_and_executes(self, tmp_path):
        """override_confirm_changeset (headless) -> no prompt, execute (R4.2)."""
        deployer = make_deployer(override_confirm_changeset=True)
        cfn = make_cfn_client(has_changes=True)
        with patch('deploy.click.confirm') as mock_confirm:
            result = run_packaged_deploy(
                deployer, cfn, tmp_path,
                base_deploy_params(confirm_changeset=True))

        assert result == 0
        mock_confirm.assert_not_called()
        cfn.execute_change_set.assert_called_once()


class TestCfnDeployEmptyChangeset:
    """Empty-changeset no-op path for _cfn_deploy_packaged (R5)."""

    def test_empty_changeset_returns_0_no_prompt_no_listing(self, tmp_path, capsys):
        """Empty change set -> return 0, no prompt, no listing, delete (R5.1, R5.2)."""
        deployer = make_deployer(override_confirm_changeset=False)
        cfn = make_cfn_client(empty_changeset=True)
        with patch('deploy.click.confirm') as mock_confirm:
            result = run_packaged_deploy(
                deployer, cfn, tmp_path,
                base_deploy_params(confirm_changeset=True))

        assert result == 0
        mock_confirm.assert_not_called()
        cfn.execute_change_set.assert_not_called()
        cfn.delete_change_set.assert_called_once()
        # No changeset listing heading on the no-op path.
        assert 'Changeset' not in capsys.readouterr().out


class TestCfnDeploySuccessBannerAndOutputs:
    """Success banner and Outputs listing in _cfn_deploy_packaged (R7)."""

    def test_success_banner_and_outputs_shown(self, tmp_path, capsys):
        """A successful deploy with Outputs shows the banner and the Outputs (R7.1, R7.2)."""
        deployer = make_deployer(override_confirm_changeset=True)
        cfn = make_cfn_client(
            has_changes=True,
            outputs=[{'OutputKey': 'ApiUrl', 'OutputValue': 'https://api.example.com'}],
        )
        result = run_packaged_deploy(
            deployer, cfn, tmp_path,
            base_deploy_params(confirm_changeset=True))

        assert result == 0
        out = capsys.readouterr().out
        assert 'Successfully deployed stack' in out
        assert 'Outputs' in out
        assert 'ApiUrl' in out
        assert 'https://api.example.com' in out

    def test_success_without_outputs_omits_section(self, tmp_path, capsys):
        """A successful deploy with no Outputs omits the Outputs section (R7.3)."""
        deployer = make_deployer(override_confirm_changeset=True)
        cfn = make_cfn_client(has_changes=True, outputs=[])
        result = run_packaged_deploy(
            deployer, cfn, tmp_path,
            base_deploy_params(confirm_changeset=True))

        assert result == 0
        out = capsys.readouterr().out
        assert 'Successfully deployed stack' in out
        # 'Outputs' heading must not appear when there are none.
        assert 'Outputs' not in out


class TestCfnDeployFailureReporting:
    """Failure event reporting in _cfn_deploy_packaged (R8)."""

    def test_failed_stack_operation_returns_1_and_lists_events(self, tmp_path, capsys):
        """A failed stack operation returns 1 and lists FAILED events (R8.1, R8.2)."""
        deployer = make_deployer(override_confirm_changeset=True)
        cfn = make_cfn_client(has_changes=True)
        # Stack existence check -> UPDATE, then polling loop reports a failure.
        cfn.describe_stacks.side_effect = [
            {'Stacks': [{'StackStatus': 'UPDATE_COMPLETE'}]},
            {'Stacks': [{'StackStatus': 'UPDATE_ROLLBACK_COMPLETE'}]},
        ]
        cfn.describe_stack_events.return_value = {
            'StackEvents': [
                {'LogicalResourceId': 'MyBucket',
                 'ResourceStatus': 'CREATE_FAILED',
                 'ResourceStatusReason': 'Bucket name already exists'},
            ]
        }
        result = run_packaged_deploy(
            deployer, cfn, tmp_path,
            base_deploy_params(confirm_changeset=True))

        assert result == 1
        out = capsys.readouterr().out
        assert 'MyBucket' in out
        assert 'Bucket name already exists' in out
