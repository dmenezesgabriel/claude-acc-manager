"""Unit tests for accounts.application.switch_message.

The TUI exercises the happy paths through notifications; these pin the
``SwitchResult`` fields no UI flow reaches — dry runs and a live login that
isn't a registry account (or is absent entirely).
"""

from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.application.switch_message import switch_message


class TestDryRunPrefix:
    def test_a_dry_run_switch_is_prefixed(self) -> None:
        # arrange
        result = SwitchResult(outcome="switched", target="work", previous="personal", dry_run=True)

        # act / assert
        assert switch_message(result) == "dry run: switched to 'work' (was 'personal')"


class TestSwitchFrom:
    def test_an_unmanaged_live_login_is_named_as_such(self) -> None:
        # arrange
        result = SwitchResult(outcome="switched", target="work", unmanaged_live=True)

        # act / assert
        assert switch_message(result) == "switched to 'work' (was an unmanaged login)"

    def test_no_outgoing_login_reads_as_no_login(self) -> None:
        # arrange
        result = SwitchResult(outcome="switched", target="work")

        # act / assert
        assert switch_message(result) == "switched to 'work' (was no login)"
