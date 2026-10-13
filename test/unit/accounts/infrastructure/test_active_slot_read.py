"""``ActiveSlotAdapter`` — the read path: credentials, config, live path.

Unit tests for accounts.infrastructure.active_slot and the ActiveSlotPort it
implements. The adapter is real; fixtures on disk pin the parsing behavior.
"""

import stat
from pathlib import Path

import pytest

from claude_acc_manager.accounts.application.ports import ActiveSlotPort
from claude_acc_manager.accounts.infrastructure.active_slot import ActiveSlotAdapter
from claude_acc_manager.accounts.infrastructure.path_resolver import (
    credentials_path,
    global_config_path,
)

FIXTURES = Path(__file__).parent / "fixtures"


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestActiveSlotPort:
    """ActiveSlotAdapter explicitly subclasses the port (greppable map)."""

    def test_adapter_is_an_active_slot_port(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert
        assert isinstance(slot, ActiveSlotPort)


class TestReadCredentials:
    """read_credentials parses .credentials.json; absent → None; torn → raises."""

    def test_returns_parsed_dict_when_valid(self, tmp_path: Path):
        # arrange
        creds = credentials_path({}, tmp_path)
        creds.parent.mkdir(parents=True)
        creds.write_text(
            (FIXTURES / "credentials_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.read_credentials()

        # assert
        assert result is not None
        assert "claudeAiOauth" in result
        oauth = result["claudeAiOauth"]
        assert isinstance(oauth, dict)
        assert oauth["accessToken"] == "tok-access-live"

    def test_returns_none_when_absent(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.read_credentials()

        # assert
        assert result is None

    def test_raises_when_torn(self, tmp_path: Path):
        # arrange
        creds = credentials_path({}, tmp_path)
        creds.parent.mkdir(parents=True)
        creds.write_text(
            (FIXTURES / "credentials_torn.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert — message must name the credentials file (kills label mutants)
        with pytest.raises(ValueError) as excinfo:
            slot.read_credentials()
        assert "credentials file" in str(excinfo.value)
        assert "torn" in str(excinfo.value) or "parse" in str(excinfo.value)

    def test_raises_when_not_json_object(self, tmp_path: Path):
        # arrange — valid JSON array, not a dict
        creds = credentials_path({}, tmp_path)
        creds.parent.mkdir(parents=True)
        creds.write_text(
            (FIXTURES / "credentials_not_object.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert — message reports the real non-dict type (kills type-name mutant)
        with pytest.raises(ValueError) as excinfo:
            slot.read_credentials()
        message = str(excinfo.value)
        assert "credentials file" in message
        assert message.endswith("not a JSON object")
        assert " is list," in message

    def test_preserves_sibling_keys_on_read(self, tmp_path: Path):
        # arrange — mcpOAuth, pluginSecrets survive the read
        creds = credentials_path({}, tmp_path)
        creds.parent.mkdir(parents=True)
        creds.write_text(
            (FIXTURES / "credentials_sibling_keys.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.read_credentials()

        # assert
        assert result is not None
        assert "mcpOAuth" in result
        assert "pluginSecrets" in result


class TestReadConfig:
    """read_config parses ~/.claude.json; absent → None; torn → raises."""

    def test_returns_parsed_dict_when_valid(self, tmp_path: Path):
        # arrange
        config = global_config_path({}, tmp_path)
        config.write_text(
            (FIXTURES / "config_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.read_config()

        # assert
        assert result is not None
        assert "oauthAccount" in result
        assert "projects" in result
        assert "userID" in result

    def test_returns_none_when_absent(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.read_config()

        # assert
        assert result is None

    def test_raises_when_torn(self, tmp_path: Path):
        # arrange
        config = global_config_path({}, tmp_path)
        config.write_text(
            (FIXTURES / "config_torn.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert — message must name the config file (kills label mutants)
        with pytest.raises(ValueError) as excinfo:
            slot.read_config()
        assert "config file" in str(excinfo.value)
        assert "torn" in str(excinfo.value) or "parse" in str(excinfo.value)

    def test_raises_when_not_json_object(self, tmp_path: Path):
        # arrange — valid JSON array
        config = global_config_path({}, tmp_path)
        config.write_text('["not", "an", "object"]', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert — message reports the real non-dict type (kills type-name mutant)
        with pytest.raises(ValueError) as excinfo:
            slot.read_config()
        message = str(excinfo.value)
        assert "config file" in message
        assert message.endswith("not a JSON object")
        assert " is list," in message


class TestCredentialsPath:
    """credentials_path exposes the resolved live path for the scoped-shell guard."""

    def test_returns_the_default_live_path(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert
        assert slot.credentials_path() == tmp_path / ".claude" / ".credentials.json"

    def test_honors_claude_config_dir(self, tmp_path: Path):
        # arrange — a scoped shell reroutes the live slot entirely
        scoped = tmp_path / "scoped"
        slot = ActiveSlotAdapter(env={"CLAUDE_CONFIG_DIR": str(scoped)}, home=tmp_path)

        # act / assert
        assert slot.credentials_path() == scoped / ".credentials.json"
