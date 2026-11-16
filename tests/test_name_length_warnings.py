"""Unit tests for get_name_length_warnings in cli/config.py.

Covers the boundaries at each recommended limit, the combined limits, the
explanation note, which template parameters are considered, and that no
returned line echoes a value.
"""
# Feature: config-name-length-warnings

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Add cli directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import get_name_length_warnings


# ---------------------------------------------------------------------------
# Helpers and expected text
# ---------------------------------------------------------------------------

# Pinned literal from requirement 1.8. Do not import the constant from
# config.py, so a change to the production text fails this test.
EXPECTED_NOTE = (
    "Combined lengths of Prefix+ProjectId+StageId > 32 may cause deployment "
    "errors when creating resources with name-length restrictions. "
    "(e.g., S3 bucket names must not exceed 63 characters and IAM role names "
    "must not exceed 64 characters)"
)


def _declared(*names):
    """Return a template ``parameters`` dict that declares the given names."""
    return {name: {} for name in names}


ALL_DECLARED = _declared('Prefix', 'ProjectId', 'StageId')


def _prefix_line(length):
    return f"Prefix is {length} characters (recommended maximum: 6)."


def _project_id_line(length):
    return f"ProjectId is {length} characters (recommended maximum: 20)."


def _stage_id_line(length):
    return f"StageId is {length} characters (recommended maximum: 6)."


def _prefix_project_line(length):
    return f"Prefix+ProjectId is {length} characters (recommended maximum: 28)."


def _combined_line(length):
    return (
        f"Prefix+ProjectId+StageId is {length} characters "
        f"(recommended maximum: 32)."
    )


# ---------------------------------------------------------------------------
# Boundaries (requirements 1.5, 1.6, 1.7)
# ---------------------------------------------------------------------------

class TestBoundaries:
    """A value at its limit gives no line; one over gives exactly one line."""

    def test_prefix_at_6_gives_no_line(self):
        result = get_name_length_warnings('a' * 6, 'p', 's', ALL_DECLARED)
        assert result == []

    def test_prefix_at_7_gives_prefix_line_and_note(self):
        result = get_name_length_warnings('a' * 7, 'p', 's', ALL_DECLARED)
        assert result == [_prefix_line(7), EXPECTED_NOTE]

    def test_project_id_at_20_gives_no_line(self):
        result = get_name_length_warnings('ab', 'p' * 20, 's', ALL_DECLARED)
        assert result == []

    def test_project_id_at_21_gives_project_id_line_and_note(self):
        result = get_name_length_warnings('ab', 'p' * 21, 's', ALL_DECLARED)
        assert result == [_project_id_line(21), EXPECTED_NOTE]

    def test_stage_id_at_6_gives_no_line(self):
        result = get_name_length_warnings('ab', 'p', 's' * 6, ALL_DECLARED)
        assert result == []

    def test_stage_id_at_7_gives_stage_id_line_and_note(self):
        result = get_name_length_warnings('ab', 'p', 's' * 7, ALL_DECLARED)
        assert result == [_stage_id_line(7), EXPECTED_NOTE]

    def test_prefix_project_id_at_28_gives_no_combined_line(self):
        # Prefix 6 + ProjectId 22 = 28. ProjectId is over its own limit, so
        # only that line appears (the pair cannot reach 28 otherwise).
        result = get_name_length_warnings(
            'a' * 6, 'p' * 22, None, _declared('Prefix', 'ProjectId'))
        assert result == [_project_id_line(22), EXPECTED_NOTE]

    def test_prefix_project_id_at_29_gives_combined_line(self):
        result = get_name_length_warnings(
            'a' * 6, 'p' * 23, None, _declared('Prefix', 'ProjectId'))
        assert result == [
            _project_id_line(23),
            _prefix_project_line(29),
            EXPECTED_NOTE,
        ]

    def test_total_at_32_gives_no_line(self):
        result = get_name_length_warnings(
            'a' * 6, 'p' * 20, 's' * 6, ALL_DECLARED)
        assert result == []

    def test_total_at_33_gives_three_way_line(self):
        # ProjectId 21 is the one value over its own limit.
        result = get_name_length_warnings(
            'a' * 6, 'p' * 21, 's' * 6, ALL_DECLARED)
        assert result == [
            _project_id_line(21),
            _combined_line(33),
            EXPECTED_NOTE,
        ]


# ---------------------------------------------------------------------------
# Combined limits versus individual limits (requirements 1.5 to 1.7)
# ---------------------------------------------------------------------------

class TestCombinedOnly:
    """Individual and combined lines are independent of each other."""

    def test_value_over_own_limit_with_combined_within_gives_only_own_line(self):
        result = get_name_length_warnings('a' * 7, 'p', 's', ALL_DECLARED)
        assert result == [_prefix_line(7), EXPECTED_NOTE]
        # The note mentions the combined names, so look at the other lines.
        assert not any(
            line.startswith('Prefix+ProjectId') for line in result[:-1])

    def test_all_values_at_limits_give_no_combined_line(self):
        # The limits are chosen so the largest each-within-limit total is
        # 6 + 20 + 6 = 32. A combined line therefore cannot appear unless at
        # least one individual value is over its own limit.
        result = get_name_length_warnings(
            'a' * 6, 'p' * 20, 's' * 6, ALL_DECLARED)
        assert result == []

    def test_combined_lines_appear_only_with_an_individual_line(self):
        result = get_name_length_warnings(
            'a' * 8, 'p' * 26, 's' * 8, ALL_DECLARED)
        assert result == [
            _prefix_line(8),
            _project_id_line(26),
            _stage_id_line(8),
            _prefix_project_line(34),
            _combined_line(42),
            EXPECTED_NOTE,
        ]

    def test_three_way_line_without_prefix_project_line(self):
        # Prefix 6 + ProjectId 20 = 26 (within 28); StageId 8 pushes the total
        # to 34, so the three-way line appears without the pair line.
        result = get_name_length_warnings(
            'a' * 6, 'p' * 20, 's' * 8, ALL_DECLARED)
        assert result == [
            _stage_id_line(8),
            _combined_line(34),
            EXPECTED_NOTE,
        ]


# ---------------------------------------------------------------------------
# Explanation note (requirements 1.8, 1.9)
# ---------------------------------------------------------------------------

class TestNote:
    """The note is last, and present exactly when another line is present."""

    def test_note_text_equals_requirement_1_8(self):
        result = get_name_length_warnings('a' * 7, 'p', 's', ALL_DECLARED)
        assert result[-1] == (
            "Combined lengths of Prefix+ProjectId+StageId > 32 may cause "
            "deployment errors when creating resources with name-length "
            "restrictions. (e.g., S3 bucket names must not exceed 63 "
            "characters and IAM role names must not exceed 64 characters)"
        )

    def test_note_is_absent_when_nothing_is_over(self):
        result = get_name_length_warnings('acme', 'myapp', 'test', ALL_DECLARED)
        assert result == []
        assert EXPECTED_NOTE not in result

    @pytest.mark.parametrize('prefix, project_id, stage_id', [
        ('a' * 7, 'p', 's'),
        ('ab', 'p' * 21, 's'),
        ('ab', 'p', 's' * 7),
        ('a' * 6, 'p' * 23, 's'),
        ('a' * 8, 'p' * 26, 's' * 8),
    ])
    def test_note_is_last_and_appears_once_when_a_line_is_present(
            self, prefix, project_id, stage_id):
        result = get_name_length_warnings(
            prefix, project_id, stage_id, ALL_DECLARED)
        assert len(result) >= 2
        assert result[-1] == EXPECTED_NOTE
        assert result.count(EXPECTED_NOTE) == 1

    @pytest.mark.parametrize('prefix, project_id, stage_id', [
        ('a' * 6, 'p' * 20, 's' * 6),
        ('a', 'p', 's'),
        ('', '', ''),
        (None, None, None),
    ])
    def test_note_is_never_returned_alone(
            self, prefix, project_id, stage_id):
        result = get_name_length_warnings(
            prefix, project_id, stage_id, ALL_DECLARED)
        assert result == []


# ---------------------------------------------------------------------------
# Declared parameters (requirements 1.3, 1.4, 1.7)
# ---------------------------------------------------------------------------

class TestDeclaredParameters:
    """Only parameters the template declares, with str values, are checked."""

    def test_prefix_only_template_ignores_long_project_id_and_stage_id(self):
        result = get_name_length_warnings(
            'acme', 'p' * 30, 's' * 30, _declared('Prefix'))
        assert result == []

    def test_prefix_only_template_still_checks_prefix(self):
        result = get_name_length_warnings(
            'a' * 8, 'p' * 30, 's' * 30, _declared('Prefix'))
        assert result == [_prefix_line(8), EXPECTED_NOTE]
        assert not any(line.startswith('ProjectId') for line in result)
        assert not any(line.startswith('StageId') for line in result)

    def test_prefix_project_id_template_ignores_long_stage_id(self):
        # Without the StageId exclusion the total would be 26 + 30 = 56.
        result = get_name_length_warnings(
            'a' * 6, 'p' * 20, 's' * 30, _declared('Prefix', 'ProjectId'))
        assert result == []

    def test_prefix_project_id_template_gives_no_three_way_line(self):
        result = get_name_length_warnings(
            'a' * 8, 'p' * 26, 's' * 30, _declared('Prefix', 'ProjectId'))
        assert result == [
            _prefix_line(8),
            _project_id_line(26),
            _prefix_project_line(34),
            EXPECTED_NOTE,
        ]
        assert not any(line.startswith('StageId') for line in result)
        assert not any(
            line.startswith('Prefix+ProjectId+StageId') for line in result)

    def test_all_three_declared_gives_all_lines(self):
        result = get_name_length_warnings(
            'a' * 8, 'p' * 26, 's' * 8, ALL_DECLARED)
        assert result == [
            _prefix_line(8),
            _project_id_line(26),
            _stage_id_line(8),
            _prefix_project_line(34),
            _combined_line(42),
            EXPECTED_NOTE,
        ]

    def test_empty_parameters_give_empty_list(self):
        assert get_name_length_warnings(
            'a' * 8, 'p' * 26, 's' * 8, {}) == []

    def test_none_parameters_give_empty_list(self):
        assert get_name_length_warnings(
            'a' * 8, 'p' * 26, 's' * 8, None) == []

    @pytest.mark.parametrize('stage_id', [None, '', 'default'])
    def test_stage_id_none_empty_or_default_is_absent(self, stage_id):
        # 'default' has 7 characters. If it were considered, StageId would be
        # over 6 and the total (6 + 20 + 7 = 33) would be over 32.
        result = get_name_length_warnings(
            'a' * 6, 'p' * 20, stage_id, ALL_DECLARED)
        assert result == []

    @pytest.mark.parametrize('stage_id', [None, '', 'default'])
    def test_absent_stage_id_does_not_hide_other_lines(self, stage_id):
        result = get_name_length_warnings(
            'a' * 7, 'p' * 22, stage_id, ALL_DECLARED)
        assert result == [
            _prefix_line(7),
            _project_id_line(22),
            _prefix_project_line(29),
            EXPECTED_NOTE,
        ]

    @pytest.mark.parametrize('bad_value', [
        None,
        123,
        MagicMock(),
    ], ids=['none', 'int', 'magicmock'])
    def test_non_str_prefix_is_absent_and_does_not_raise(self, bad_value):
        result = get_name_length_warnings(
            bad_value, 'p' * 21, 's' * 7, ALL_DECLARED)
        assert result == [
            _project_id_line(21),
            _stage_id_line(7),
            EXPECTED_NOTE,
        ]

    @pytest.mark.parametrize('bad_value', [
        None,
        123,
        MagicMock(),
    ], ids=['none', 'int', 'magicmock'])
    def test_non_str_project_id_is_absent_and_does_not_raise(self, bad_value):
        result = get_name_length_warnings(
            'a' * 7, bad_value, 's' * 7, ALL_DECLARED)
        assert result == [
            _prefix_line(7),
            _stage_id_line(7),
            EXPECTED_NOTE,
        ]

    @pytest.mark.parametrize('bad_value', [
        None,
        123,
        MagicMock(),
    ], ids=['none', 'int', 'magicmock'])
    def test_non_str_stage_id_is_absent_and_does_not_raise(self, bad_value):
        result = get_name_length_warnings(
            'a' * 7, 'p' * 21, bad_value, ALL_DECLARED)
        # Prefix 7 + ProjectId 21 = 28, which is at the pair limit.
        assert result == [
            _prefix_line(7),
            _project_id_line(21),
            EXPECTED_NOTE,
        ]


# ---------------------------------------------------------------------------
# Values never appear in the output (requirements 1.5, 1.10)
# ---------------------------------------------------------------------------

class TestNoValueInOutput:
    """Lines carry names and lengths only, and no character checks are made."""

    HOSTILE_VALUE = 'bad\n\x1b[31m' + 'x' * 40

    @pytest.mark.parametrize('position', ['prefix', 'project_id', 'stage_id'])
    def test_hostile_value_is_not_echoed_in_any_line(self, position):
        values = {'prefix': 'ab', 'project_id': 'p', 'stage_id': 's'}
        values[position] = self.HOSTILE_VALUE
        result = get_name_length_warnings(
            values['prefix'], values['project_id'], values['stage_id'],
            ALL_DECLARED)
        assert result, 'a value over its limit must produce lines'
        for line in result:
            assert self.HOSTILE_VALUE not in line
            assert '\n' not in line
            assert '\x1b' not in line

    def test_all_three_hostile_values_are_not_echoed(self):
        result = get_name_length_warnings(
            self.HOSTILE_VALUE, self.HOSTILE_VALUE, self.HOSTILE_VALUE,
            ALL_DECLARED)
        assert len(result) == 6
        for line in result:
            assert self.HOSTILE_VALUE not in line
            assert '\n' not in line
            assert '\x1b' not in line

    @pytest.mark.parametrize('stage_id', ['a-b-c-', '------', 'a-b-c'])
    def test_stage_id_with_dashes_within_limit_gives_no_line(self, stage_id):
        result = get_name_length_warnings(
            'acme', 'myapp', stage_id, ALL_DECLARED)
        assert result == []

    def test_one_character_prefix_gives_no_line(self):
        result = get_name_length_warnings('a', 'myapp', 'test', ALL_DECLARED)
        assert result == []


# ---------------------------------------------------------------------------
# Property-based tests (task 2.4)
# ---------------------------------------------------------------------------

# Numeric limits from requirements 1.5 to 1.7. They are repeated here, not
# imported from config.py, so the oracle stays independent of the function.
LIMIT_PREFIX = 6
LIMIT_PROJECT_ID = 20
LIMIT_STAGE_ID = 6
LIMIT_PREFIX_PROJECT_ID = 28
LIMIT_COMBINED = 32

name_lengths = st.integers(min_value=0, max_value=40)
declared_names = st.sets(
    st.sampled_from(['Prefix', 'ProjectId', 'StageId']))


class TestWarningsProperty:
    """Property: lines appear exactly when the oracle says they should.

    **Validates: Requirements 6.5**
    """

    @given(
        prefix_length=name_lengths,
        project_id_length=name_lengths,
        stage_id_length=name_lengths,
        declared=declared_names,
    )
    @settings(max_examples=100, deadline=None)
    def test_lines_match_oracle(
            self, prefix_length, project_id_length, stage_id_length, declared):
        """Each line is present exactly when its limit is exceeded."""
        result = get_name_length_warnings(
            'a' * prefix_length,
            'a' * project_id_length,
            'a' * stage_id_length,
            _declared(*declared),
        )

        # Oracle. A StageId of length 0 is the empty string, which counts as
        # absent. Prefix and ProjectId of length 0 are still str values with
        # length 0, so they are considered (and can never be over a limit).
        considered = {}
        if 'Prefix' in declared:
            considered['Prefix'] = prefix_length
        if 'ProjectId' in declared:
            considered['ProjectId'] = project_id_length
        if 'StageId' in declared and stage_id_length > 0:
            considered['StageId'] = stage_id_length

        expect_prefix = (
            'Prefix' in considered and considered['Prefix'] > LIMIT_PREFIX)
        expect_project_id = (
            'ProjectId' in considered
            and considered['ProjectId'] > LIMIT_PROJECT_ID)
        expect_stage_id = (
            'StageId' in considered
            and considered['StageId'] > LIMIT_STAGE_ID)
        expect_pair = (
            'Prefix' in considered and 'ProjectId' in considered
            and considered['Prefix'] + considered['ProjectId']
            > LIMIT_PREFIX_PROJECT_ID)
        expect_triple = (
            len(considered) == 3
            and sum(considered.values()) > LIMIT_COMBINED)
        expect_empty = not (
            expect_prefix or expect_project_id or expect_stage_id
            or expect_pair or expect_triple)

        # Match lines by their exact leading text. The note also contains
        # "Prefix+ProjectId+StageId", so substring checks would be wrong.
        has_prefix = any(line.startswith('Prefix is ') for line in result)
        has_project_id = any(
            line.startswith('ProjectId is ') for line in result)
        has_stage_id = any(line.startswith('StageId is ') for line in result)
        has_pair = any(
            line.startswith('Prefix+ProjectId is ') for line in result)
        has_triple = any(
            line.startswith('Prefix+ProjectId+StageId is ')
            for line in result)

        assert has_prefix == expect_prefix
        assert has_project_id == expect_project_id
        assert has_stage_id == expect_stage_id
        assert has_pair == expect_pair
        assert has_triple == expect_triple
        assert (result == []) == expect_empty

        if expect_empty:
            assert EXPECTED_NOTE not in result
        else:
            # Individual and combined lines plus the note, nothing else.
            expected_count = sum([
                expect_prefix, expect_project_id, expect_stage_id,
                expect_pair, expect_triple,
            ]) + 1
            assert len(result) == expected_count
            assert result[-1] == EXPECTED_NOTE


# ---------------------------------------------------------------------------
# Printer and final-values wrapper (task 3.3)
# ---------------------------------------------------------------------------

from unittest.mock import call, patch

import config
from config import (
    NAME_LENGTH_HEADING,
    NAME_LENGTH_HEADING_FINAL,
    show_name_length_warnings,
    warn_if_final_names_exceed,
)
from lib.tools import Colorize

SAMPLE_LINES = [
    "Prefix is 8 characters (recommended maximum: 6).",
    "ProjectId is 22 characters (recommended maximum: 20).",
    EXPECTED_NOTE,
]


class TestShowWarnings:
    """show_name_length_warnings prints and logs in the right style.

    **Validates: Requirements 2.1, 2.2, 2.3, 6.9**
    """

    def test_interactive_echoes_heading_and_each_line_colored(self):
        with patch('config.click.echo') as mock_echo, \
                patch('config.Log') as mock_log:
            show_name_length_warnings(SAMPLE_LINES)

        expected = [call(), call(Colorize.warning(NAME_LENGTH_HEADING))]
        expected += [call(Colorize.warning(f"  {line}")) for line in SAMPLE_LINES]
        expected += [call()]
        assert mock_echo.call_args_list == expected
        # Interactive output goes to stdout, never to stderr.
        assert all('err' not in c.kwargs for c in mock_echo.call_args_list)

    def test_interactive_logs_each_line_once(self):
        with patch('config.click.echo'), patch('config.Log') as mock_log:
            show_name_length_warnings(SAMPLE_LINES)

        assert mock_log.warning.call_args_list == [
            call(line) for line in SAMPLE_LINES]

    def test_interactive_uses_custom_heading(self):
        with patch('config.click.echo') as mock_echo, patch('config.Log'):
            show_name_length_warnings(
                SAMPLE_LINES, heading=NAME_LENGTH_HEADING_FINAL)

        assert call(Colorize.warning(NAME_LENGTH_HEADING_FINAL)) \
            in mock_echo.call_args_list
        assert call(Colorize.warning(NAME_LENGTH_HEADING)) \
            not in mock_echo.call_args_list

    def test_empty_list_prints_and_logs_nothing(self):
        for headless in (False, True):
            with patch('config.click.echo') as mock_echo, \
                    patch('config.Log') as mock_log:
                show_name_length_warnings([], headless=headless)

            mock_echo.assert_not_called()
            mock_log.warning.assert_not_called()

    def test_headless_echoes_prefixed_lines_to_stderr(self):
        with patch('config.click.echo') as mock_echo, patch('config.Log'):
            show_name_length_warnings(SAMPLE_LINES, headless=True)

        assert mock_echo.call_args_list == [
            call(f"Warning: {line}", err=True) for line in SAMPLE_LINES]

    def test_headless_has_no_heading_or_color(self):
        with patch('config.click.echo') as mock_echo, patch('config.Log'):
            show_name_length_warnings(
                SAMPLE_LINES, headless=True, heading='SHOULD NOT APPEAR')

        for c in mock_echo.call_args_list:
            text = c.args[0]
            assert 'SHOULD NOT APPEAR' not in text
            assert '\x1b' not in text

    def test_headless_logs_each_line_once(self):
        with patch('config.click.echo'), patch('config.Log') as mock_log:
            show_name_length_warnings(SAMPLE_LINES, headless=True)

        assert mock_log.warning.call_args_list == [
            call(line) for line in SAMPLE_LINES]

    def test_headless_without_patches_writes_stderr_only(self, capsys):
        show_name_length_warnings(SAMPLE_LINES, headless=True)

        captured = capsys.readouterr()
        assert captured.out == ''
        assert captured.err.splitlines() == [
            f"Warning: {line}" for line in SAMPLE_LINES]


class TestFailureIsolation:
    """A failing stream or logger never stops the run.

    **Validates: Requirements 2.5, 6.9**
    """

    @pytest.mark.parametrize('headless', [False, True])
    def test_click_echo_failure_is_swallowed(self, headless):
        with patch('config.click.echo', side_effect=OSError('broken pipe')), \
                patch('config.Log') as mock_log:
            result = show_name_length_warnings(SAMPLE_LINES, headless=headless)

        assert result is None
        # Logging still happens when printing fails.
        assert mock_log.warning.call_count == len(SAMPLE_LINES)

    @pytest.mark.parametrize('headless', [False, True])
    def test_log_warning_failure_is_swallowed(self, headless, capsys):
        with patch('config.Log') as mock_log:
            mock_log.warning.side_effect = RuntimeError('logger broken')
            result = show_name_length_warnings(SAMPLE_LINES, headless=headless)

        assert result is None
        # Every line was still attempted, and printing was not affected.
        assert mock_log.warning.call_count == len(SAMPLE_LINES)
        captured = capsys.readouterr()
        assert SAMPLE_LINES[0] in captured.out + captured.err

    def test_both_failing_together_is_swallowed(self):
        with patch('config.click.echo', side_effect=OSError('x')), \
                patch('config.Log') as mock_log:
            mock_log.warning.side_effect = RuntimeError('y')
            assert show_name_length_warnings(SAMPLE_LINES) is None


class TestNoPrompts:
    """Neither function ever prompts the user.

    **Validates: Requirements 2.4, 6.10**
    """

    @pytest.fixture
    def prompts_forbidden(self):
        boom = AssertionError('a prompt function was called')
        with patch('config.click.confirm', side_effect=boom), \
                patch('config.click.prompt', side_effect=boom), \
                patch('config.Colorize.prompt', side_effect=boom), \
                patch('config.Log'):
            yield

    @pytest.mark.parametrize('headless', [False, True])
    def test_show_does_not_prompt(self, prompts_forbidden, headless, capsys):
        show_name_length_warnings(SAMPLE_LINES, headless=headless)
        show_name_length_warnings([], headless=headless)

    def test_warn_if_final_does_not_prompt(self, prompts_forbidden, capsys):
        # The wrapper is interactive-only and has no headless argument.
        initial = ('acme', 'myapp', 'dev')
        changed = {'Prefix': 'a' * 8, 'ProjectId': 'myapp', 'StageId': 'dev'}
        parameters = _declared('Prefix', 'ProjectId', 'StageId')

        assert warn_if_final_names_exceed(initial, changed, parameters) is True
        assert warn_if_final_names_exceed(initial, {}, parameters) is False


class TestFinalNames:
    """warn_if_final_names_exceed only checks when the values changed.

    **Validates: Requirements 3.2, 6.6**
    """

    INITIAL = ('acme', 'myapp', 'dev')
    PARAMETERS = _declared('Prefix', 'ProjectId', 'StageId')

    def test_unchanged_values_return_false_and_do_not_show(self):
        values = {'Prefix': 'acme', 'ProjectId': 'myapp', 'StageId': 'dev'}
        with patch('config.show_name_length_warnings') as mock_show:
            result = warn_if_final_names_exceed(
                self.INITIAL, values, self.PARAMETERS)

        assert result is False
        mock_show.assert_not_called()

    def test_unchanged_over_limit_values_are_not_repeated(self):
        # The first check already covered these, so no second warning.
        initial = ('a' * 8, 'myapp', 'dev')
        values = {'Prefix': 'a' * 8, 'ProjectId': 'myapp', 'StageId': 'dev'}
        with patch('config.show_name_length_warnings') as mock_show:
            result = warn_if_final_names_exceed(
                initial, values, self.PARAMETERS)

        assert result is False
        mock_show.assert_not_called()

    def test_changed_prefix_over_limit_returns_true_with_final_heading(self):
        values = {'Prefix': 'a' * 8, 'ProjectId': 'myapp', 'StageId': 'dev'}
        with patch('config.show_name_length_warnings') as mock_show:
            result = warn_if_final_names_exceed(
                self.INITIAL, values, self.PARAMETERS)

        assert result is True
        mock_show.assert_called_once_with(
            [_prefix_line(8), EXPECTED_NOTE],
            heading=NAME_LENGTH_HEADING_FINAL,
        )

    def test_changed_value_within_limits_returns_true_and_prints_nothing(self):
        values = {'Prefix': 'beta', 'ProjectId': 'myapp', 'StageId': 'dev'}
        with patch('config.click.echo') as mock_echo, \
                patch('config.Log') as mock_log:
            result = warn_if_final_names_exceed(
                self.INITIAL, values, self.PARAMETERS)

        assert result is True
        mock_echo.assert_not_called()
        mock_log.warning.assert_not_called()

    def test_values_without_the_three_keys_return_false(self):
        with patch('config.show_name_length_warnings') as mock_show:
            result = warn_if_final_names_exceed(
                self.INITIAL, {'Other': 'x' * 50}, self.PARAMETERS)

        assert result is False
        mock_show.assert_not_called()

    def test_empty_values_return_false(self):
        with patch('config.show_name_length_warnings') as mock_show:
            assert warn_if_final_names_exceed(
                self.INITIAL, {}, self.PARAMETERS) is False
        mock_show.assert_not_called()

    def test_stage_id_changed_from_default_to_long_value_is_detected(self):
        initial = ('acme', 'myapp', 'default')
        values = {'StageId': 'prod-east'}
        with patch('config.show_name_length_warnings') as mock_show:
            result = warn_if_final_names_exceed(
                initial, values, self.PARAMETERS)

        assert result is True
        mock_show.assert_called_once_with(
            [_stage_id_line(9), EXPECTED_NOTE],
            heading=NAME_LENGTH_HEADING_FINAL,
        )

    def test_missing_key_keeps_initial_value_in_the_check(self):
        # Only Prefix changed; ProjectId keeps its (long) initial value.
        initial = ('acme', 'p' * 21, 'dev')
        values = {'Prefix': 'beta'}
        with patch('config.show_name_length_warnings') as mock_show:
            result = warn_if_final_names_exceed(
                initial, values, self.PARAMETERS)

        assert result is True
        mock_show.assert_called_once_with(
            [_project_id_line(21), EXPECTED_NOTE],
            heading=NAME_LENGTH_HEADING_FINAL,
        )
