"""Unit tests for accounts.domain.value_objects — AccountName."""

import pytest

from claude_acc_manager.accounts.domain.value_objects import AccountName, normalized_account_name


class TestAccountNameNormalizes:
    """Input is normalized: surrounding whitespace stripped, case folded."""

    def test_uppercase_input_is_folded_to_lowercase(self):
        # arrange
        # act
        name = AccountName("Work")

        # assert
        assert name.value == "work"

    def test_surrounding_whitespace_is_stripped(self):
        # arrange
        # act
        name = AccountName("  personal \n")

        # assert
        assert name.value == "personal"


class TestAccountNameRejects:
    """Rejected inputs raise ValueError with the offending value and the
    rule violated — the message text itself is user-facing CLI output, so it
    is pinned exactly (evidence: claude-swap models.py normalize_alias +
    ai-usagebar config.rs validate_account_label)."""

    @pytest.mark.parametrize(
        ("raw", "expected_message"),
        [
            ("", "account name cannot be empty (got '')"),
            ("   ", "account name cannot be empty (got '   ')"),
            (".", "account name '.' is reserved (path safety)"),
            ("..", "account name '..' is reserved (path safety)"),
            (
                "-work",
                "account name '-work' cannot start with '-' (argparse would read it as a flag)",
            ),
            (
                "a/b",
                "account name 'a/b' may only contain letters, digits, '-', '_' and '.'",
            ),
            (
                "wo\nrk",
                "account name 'wo\\nrk' may only contain letters, digits, '-', '_' and '.'",
            ),
        ],
    )
    def test_invalid_names_raise_value_error(self, raw: str, expected_message: str):
        # arrange
        # act
        with pytest.raises(ValueError) as raised:
            normalized_account_name(raw)

        # assert
        assert str(raised.value) == expected_message


class TestAccountNameValueSemantics:
    """The name is an immutable, hashable value object."""

    def test_equal_names_are_equal_and_hashable(self):
        # arrange
        # act / assert
        assert AccountName("work") == AccountName("WORK")
        assert len({AccountName("work"), AccountName("work")}) == 1

    def test_str_returns_normalized_value(self):
        # arrange
        # act
        name = AccountName("Work")

        # assert
        assert str(name) == "work"
