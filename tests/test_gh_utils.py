"""Unit tests for ``GitHubUtils._retry_gh_command()`` in ``cli/lib/gh_utils.py``.

The retry policy is 4 total attempts (1 initial + 3 retries) with exponential
backoff delays of 1, 2 and 4 seconds. Only ``CalledProcessError`` is retried.

``subprocess.run``, ``time.sleep`` and ``Log`` are mocked, so these tests never
call GitHub, the network or AWS, and never actually sleep.

Note on patch targets: ``_retry_gh_command`` does ``from lib.logger import Log``
inside the function body, so ``Log`` is looked up on ``lib.logger`` at call
time. Patching ``lib.logger.Log`` is therefore what takes effect (patching
``lib.gh_utils.Log`` would not).

Related, more detailed retry tests live in ``cli/lib/test_gh_utils_retry.py``.
"""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add cli/ to path so lib.gh_utils resolves its ``lib.logger`` import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli'))

from lib.gh_utils import GitHubUtils

COMMAND = ['gh', 'repo', 'view', 'owner/my-repo']


def _failure(stderr='boom'):
    """Build a ``CalledProcessError`` like ``subprocess.run(check=True)`` raises.

    Args:
        stderr (str): Text for the error's ``stderr`` attribute.

    Returns:
        subprocess.CalledProcessError: The error instance.
    """
    return subprocess.CalledProcessError(1, COMMAND, stderr=stderr)


@pytest.fixture
def mocks():
    """Patch ``subprocess.run``, ``time.sleep`` and ``Log`` for one test.

    Yields:
        tuple: ``(mock_run, mock_sleep, mock_log)``.
    """
    with patch('lib.gh_utils.subprocess.run') as mock_run, \
            patch('lib.gh_utils.time.sleep') as mock_sleep, \
            patch('lib.logger.Log') as mock_log:
        yield mock_run, mock_sleep, mock_log


class TestRetryLogic:
    """Tests for the retry loop in ``GitHubUtils._retry_gh_command()``."""

    def test_success_on_first_attempt(self, mocks):
        """A successful first attempt returns the result with no retry or sleep."""
        mock_run, mock_sleep, _ = mocks
        success = MagicMock(returncode=0)
        mock_run.return_value = success

        result = GitHubUtils._retry_gh_command(COMMAND)

        assert result is success
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    def test_success_on_first_retry(self, mocks):
        """One failure followed by success: 2 runs, 1 sleep."""
        mock_run, mock_sleep, _ = mocks
        success = MagicMock(returncode=0)
        mock_run.side_effect = [_failure(), success]

        result = GitHubUtils._retry_gh_command(COMMAND)

        assert result is success
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1

    def test_success_on_second_retry(self, mocks):
        """Two failures followed by success: 3 runs, 2 sleeps."""
        mock_run, mock_sleep, _ = mocks
        success = MagicMock(returncode=0)
        mock_run.side_effect = [_failure(), _failure(), success]

        result = GitHubUtils._retry_gh_command(COMMAND)

        assert result is success
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2

    def test_success_on_third_retry(self, mocks):
        """Three failures followed by success: 4 runs, 3 sleeps."""
        mock_run, mock_sleep, _ = mocks
        success = MagicMock(returncode=0)
        mock_run.side_effect = [_failure(), _failure(), _failure(), success]

        result = GitHubUtils._retry_gh_command(COMMAND)

        assert result is success
        assert mock_run.call_count == 4
        assert mock_sleep.call_count == 3

    def test_all_retries_exhausted(self, mocks):
        """When every attempt fails, 4 runs happen and the last error is raised."""
        mock_run, mock_sleep, _ = mocks
        errors = [_failure(f'error {n}') for n in range(1, 5)]
        mock_run.side_effect = errors

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            GitHubUtils._retry_gh_command(COMMAND)

        assert mock_run.call_count == 4
        assert exc_info.value is errors[-1]
        assert exc_info.value.stderr == 'error 4'
        assert mock_sleep.call_count == 3

    def test_exponential_backoff_delays(self, mocks):
        """Sleep is called with 1, 2 and 4 seconds, in that order."""
        mock_run, mock_sleep, _ = mocks
        mock_run.side_effect = [_failure() for _ in range(4)]

        with pytest.raises(subprocess.CalledProcessError):
            GitHubUtils._retry_gh_command(COMMAND)

        assert [c.args[0] for c in mock_sleep.call_args_list] == [1, 2, 4]

    def test_non_calledprocesserror_not_retried(self, mocks):
        """Exceptions other than CalledProcessError propagate immediately."""
        mock_run, mock_sleep, _ = mocks

        # Raised on the initial attempt (e.g. gh is not installed)
        mock_run.side_effect = FileNotFoundError("gh not found")
        with pytest.raises(FileNotFoundError):
            GitHubUtils._retry_gh_command(COMMAND)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

        # Raised during a retry: no further attempts after it
        mock_run.reset_mock()
        mock_sleep.reset_mock()
        mock_run.side_effect = [_failure(), FileNotFoundError("gh not found")]
        with pytest.raises(FileNotFoundError):
            GitHubUtils._retry_gh_command(COMMAND)
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1

    def test_stderr_logged_on_failure(self, mocks):
        """The failed command's stderr text is logged with ``Log.error``."""
        mock_run, _, mock_log = mocks
        stderr_text = 'GraphQL: Could not resolve to a Repository'
        mock_run.side_effect = [_failure(stderr_text), MagicMock(returncode=0)]

        GitHubUtils._retry_gh_command(COMMAND)

        mock_log.error.assert_any_call(f"gh command stderr: {stderr_text}")
