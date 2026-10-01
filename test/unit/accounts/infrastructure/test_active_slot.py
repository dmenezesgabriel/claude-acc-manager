"""Unit tests for accounts.infrastructure.active_slot and the
ActiveSlotPort it implements."""

import json
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


class TestWriteCredentials:
    """write_credentials creates .credentials.json atomically with mode 0600."""

    def test_creates_file_with_0600_mode(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)
        payload = {"claudeAiOauth": {"accessToken": "new"}}

        # act
        slot.write_credentials(payload)

        # assert
        target = credentials_path({}, tmp_path)
        assert target.exists()
        assert file_mode(target) == 0o600
        assert json.loads(target.read_text(encoding="utf-8")) == payload

    def test_replaces_existing_content(self, tmp_path: Path):
        # arrange
        creds = credentials_path({}, tmp_path)
        creds.parent.mkdir(parents=True)
        creds.write_text('{"old": true}', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        slot.write_credentials({"claudeAiOauth": {"accessToken": "replaced"}})

        # assert
        assert json.loads(creds.read_text(encoding="utf-8")) == {
            "claudeAiOauth": {"accessToken": "replaced"}
        }

    def test_creates_parent_dir_with_0700(self, tmp_path: Path):
        # arrange — config home doesn't exist yet
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        slot.write_credentials({"claudeAiOauth": {}})

        # assert
        config_home = tmp_path / ".claude"
        assert config_home.is_dir()
        assert stat.S_IMODE(config_home.stat().st_mode) == 0o700


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


class TestWriteConfig:
    """write_config creates ~/.claude.json atomically with mode 0600."""

    def test_creates_file_with_0600_mode(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)
        payload = {"oauthAccount": {"emailAddress": "user@test.com"}}

        # act
        slot.write_config(payload)

        # assert
        target = global_config_path({}, tmp_path)
        assert target.exists()
        assert file_mode(target) == 0o600
        assert json.loads(target.read_text(encoding="utf-8")) == payload


class TestSalvageTornConfig:
    """salvage_torn_config copies torn config aside with 0600 before overwrite."""

    def test_returns_none_when_absent(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.salvage_torn_config()

        # assert
        assert result is None

    def test_copies_torn_file_aside(self, tmp_path: Path):
        # arrange
        config = global_config_path({}, tmp_path)
        torn_content = '{"broken": true'
        config.write_text(torn_content, encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        result = slot.salvage_torn_config()

        # assert
        assert result is not None
        assert result.exists()
        assert "unreadable-" in result.name
        assert result.read_text(encoding="utf-8") == torn_content
        assert file_mode(result) == 0o600
        # original still exists
        assert config.exists()

    def test_collision_suffix_when_second_in_same_second(self, tmp_path: Path):
        # arrange — pre-create a salvage file to trigger collision
        config = global_config_path({}, tmp_path)
        config.write_text('{"broken": true', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        import time

        epoch = str(int(time.time()))
        stem = f"{config.name}.unreadable-{epoch}"
        first_salvage = config.with_name(stem)
        first_salvage.write_text("pre-existing", encoding="utf-8")

        # act
        result = slot.salvage_torn_config()

        # assert — should get .1 suffix
        assert result is not None
        assert result.name == f"{stem}.1"

    def test_collision_increments_counter_for_two_existing_salvages(self, tmp_path: Path):
        # arrange — two salvage files already exist, so the counter must reach .2
        config = global_config_path({}, tmp_path)
        config.write_text('{"broken": true', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        import time

        epoch = str(int(time.time()))
        stem = f"{config.name}.unreadable-{epoch}"
        config.with_name(stem).write_text("first", encoding="utf-8")
        config.with_name(f"{stem}.1").write_text("second", encoding="utf-8")

        # act
        result = slot.salvage_torn_config()

        # assert — skips both existing names, lands on .2
        assert result is not None
        assert result.name == f"{stem}.2"


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


class TestDeleteCredentials:
    """delete_credentials restores the absent state (rollback's undo of write)."""

    def test_removes_the_existing_file(self, tmp_path: Path):
        # arrange
        creds = credentials_path({}, tmp_path)
        creds.parent.mkdir(parents=True)
        creds.write_text('{"claudeAiOauth": {}}', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        slot.delete_credentials()

        # assert
        assert not creds.exists()

    def test_noop_when_absent(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert — restoring "absent" over "absent" is a no-op, not an error
        slot.delete_credentials()
        assert not credentials_path({}, tmp_path).exists()


class TestDeleteConfig:
    """delete_config unlinks the same path the other config methods target."""

    def test_removes_the_existing_file(self, tmp_path: Path):
        # arrange
        config = global_config_path({}, tmp_path)
        config.write_text('{"oauthAccount": {}}', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        slot.delete_config()

        # assert
        assert not config.exists()

    def test_noop_when_absent(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act / assert
        slot.delete_config()
        assert not global_config_path({}, tmp_path).exists()

    def test_honors_the_legacy_config_reroute(self, tmp_path: Path):
        # arrange — the legacy path exists, so global_config_path targets it
        legacy = tmp_path / ".claude" / ".config.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"oauthAccount": {}}', encoding="utf-8")
        modern = tmp_path / ".claude.json"
        modern.write_text('{"oauthAccount": {}}', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        slot.delete_config()

        # assert — the legacy file goes, the modern one is untouched
        assert not legacy.exists()
        assert modern.exists()


class TestSpliceConfigOauthAccount:
    """splice_config_oauth_account sets oauthAccount, preserves all other keys."""

    def test_inserts_oauth_account_into_valid_config(self, tmp_path: Path):
        # arrange — config with projects and userID
        config = global_config_path({}, tmp_path)
        config.write_text(
            (FIXTURES / "config_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)
        new_oauth = {"emailAddress": "new@test.com", "accountUuid": "new-uuid"}

        # act
        slot.splice_config_oauth_account(new_oauth)

        # assert — oauthAccount replaced, other keys preserved
        result = json.loads(config.read_text(encoding="utf-8"))
        assert result["oauthAccount"] == new_oauth
        assert "projects" in result
        assert "userID" in result

    def test_replaces_existing_oauth_account(self, tmp_path: Path):
        # arrange — config already has oauthAccount
        config = global_config_path({}, tmp_path)
        config.write_text(
            (FIXTURES / "config_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        slot = ActiveSlotAdapter(env={}, home=tmp_path)
        new_oauth = {"emailAddress": "replaced@test.com"}

        # act
        slot.splice_config_oauth_account(new_oauth)

        # assert
        result = json.loads(config.read_text(encoding="utf-8"))
        assert result["oauthAccount"] == new_oauth
        assert result["oauthAccount"]["emailAddress"] == "replaced@test.com"

    def test_creates_fresh_config_when_absent(self, tmp_path: Path):
        # arrange — no config file
        slot = ActiveSlotAdapter(env={}, home=tmp_path)
        oauth = {"emailAddress": "fresh@test.com"}

        # act
        slot.splice_config_oauth_account(oauth)

        # assert
        target = global_config_path({}, tmp_path)
        result = json.loads(target.read_text(encoding="utf-8"))
        assert result == {"oauthAccount": oauth}

    def test_salvages_torn_config_then_writes(self, tmp_path: Path):
        # arrange — torn config file exists
        config = global_config_path({}, tmp_path)
        config.write_text('{"broken', encoding="utf-8")
        slot = ActiveSlotAdapter(env={}, home=tmp_path)
        oauth = {"emailAddress": "after-salvage@test.com"}

        # act
        slot.splice_config_oauth_account(oauth)

        # assert — torn file salvaged, new config written
        result = json.loads(config.read_text(encoding="utf-8"))
        assert result == {"oauthAccount": oauth}
        # salvage copy exists alongside
        salvages = list(config.parent.glob(f"{config.name}.unreadable-*"))
        assert len(salvages) == 1
        assert salvages[0].read_text(encoding="utf-8") == '{"broken'

    def test_written_config_is_0600(self, tmp_path: Path):
        # arrange
        slot = ActiveSlotAdapter(env={}, home=tmp_path)

        # act
        slot.splice_config_oauth_account({"emailAddress": "test@test.com"})

        # assert
        target = global_config_path({}, tmp_path)
        assert file_mode(target) == 0o600
