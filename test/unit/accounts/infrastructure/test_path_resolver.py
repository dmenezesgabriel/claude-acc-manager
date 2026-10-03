"""Unit tests for accounts.infrastructure.path_resolver."""

from pathlib import Path

from claude_acc_manager.accounts.infrastructure import path_resolver

EMPTY_ENV: dict[str, str] = {}


class TestClaudeConfigHome:
    """Config home: CLAUDE_CONFIG_DIR if set, else ~/.claude (claude-code rule)."""

    def test_env_var_wins_when_set(self, tmp_path: Path):
        # arrange
        env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "scratch")}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.claude_config_home(env, home)

        # assert
        assert resolved == tmp_path / "scratch"

    def test_defaults_to_home_claude_when_unset(self, tmp_path: Path):
        # arrange
        home = tmp_path / "home"

        # act
        resolved = path_resolver.claude_config_home(EMPTY_ENV, home)

        # assert
        assert resolved == home / ".claude"

    def test_empty_env_value_falls_back_to_default(self, tmp_path: Path):
        # arrange — an empty CLAUDE_CONFIG_DIR must not resolve to "."
        env = {"CLAUDE_CONFIG_DIR": ""}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.claude_config_home(env, home)

        # assert
        assert resolved == home / ".claude"


class TestSecureStorageHome:
    """Claude 2.1.x's secure-storage dir — where .credentials.json lives.

    Mirrors wS() in the claude bundle: CLAUDE_SECURESTORAGE_CONFIG_DIR wins
    whenever it is defined — a defined-but-empty value means ~/.claude —
    otherwise the CLAUDE_CONFIG_DIR chain applies.
    """

    def test_unset_follows_the_config_dir_chain(self, tmp_path: Path):
        # arrange
        env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "scratch")}

        # act
        resolved = path_resolver.secure_storage_home(env, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "scratch"

    def test_unset_and_no_config_dir_defaults_to_home_claude(self, tmp_path: Path):
        # arrange
        home = tmp_path / "home"

        # act
        resolved = path_resolver.secure_storage_home(EMPTY_ENV, home)

        # assert
        assert resolved == home / ".claude"

    def test_set_securestorage_dir_wins_over_config_dir(self, tmp_path: Path):
        # arrange
        env = {
            "CLAUDE_CONFIG_DIR": str(tmp_path / "scratch"),
            "CLAUDE_SECURESTORAGE_CONFIG_DIR": str(tmp_path / "secure"),
        }

        # act
        resolved = path_resolver.secure_storage_home(env, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "secure"

    def test_defined_but_empty_securestorage_dir_means_the_default(self, tmp_path: Path):
        # arrange — "" is defined, so it overrides even a set CLAUDE_CONFIG_DIR
        env = {
            "CLAUDE_CONFIG_DIR": str(tmp_path / "scratch"),
            "CLAUDE_SECURESTORAGE_CONFIG_DIR": "",
        }

        # act
        resolved = path_resolver.secure_storage_home(env, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "home" / ".claude"


class TestCredentialsPath:
    """Credentials live inside the secure-storage home:
    <secure_storage_home>/.credentials.json."""

    def test_inside_claude_config_dir_when_set(self, tmp_path: Path):
        # arrange
        env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "scratch")}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.credentials_path(env, home)

        # assert
        assert resolved == tmp_path / "scratch" / ".credentials.json"

    def test_inside_default_config_home_when_unset(self, tmp_path: Path):
        # arrange
        home = tmp_path / "home"

        # act
        resolved = path_resolver.credentials_path(EMPTY_ENV, home)

        # assert
        assert resolved == home / ".claude" / ".credentials.json"

    def test_securestorage_dir_reroutes_credentials(self, tmp_path: Path):
        # arrange — under CLAUDE_SECURESTORAGE_CONFIG_DIR claude reads its
        # credential file from that dir, not the config dir
        env = {"CLAUDE_SECURESTORAGE_CONFIG_DIR": str(tmp_path / "secure")}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.credentials_path(env, home)

        # assert
        assert resolved == tmp_path / "secure" / ".credentials.json"


class TestGlobalConfigPath:
    """.claude.json sits at homedir by default, not inside .claude/ — and a
    legacy <config_home>/.config.json wins when it exists."""

    def test_homedir_asymmetry_default_is_home_not_config_home(self, tmp_path: Path):
        # arrange — no env, no legacy file: .claude.json lands at homedir
        home = tmp_path / "home"

        # act
        resolved = path_resolver.global_config_path(EMPTY_ENV, home)

        # assert
        assert resolved == home / ".claude.json"

    def test_env_base_wins_when_set(self, tmp_path: Path):
        # arrange — with CLAUDE_CONFIG_DIR, .claude.json sits inside that dir
        env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "scratch")}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.global_config_path(env, home)

        # assert
        assert resolved == tmp_path / "scratch" / ".claude.json"

    def test_legacy_config_json_wins_when_it_exists(self, tmp_path: Path):
        # arrange — legacy file present in the config home (env-scoped here)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        (scratch / ".config.json").touch()
        env = {"CLAUDE_CONFIG_DIR": str(scratch)}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.global_config_path(env, home)

        # assert
        assert resolved == scratch / ".config.json"

    def test_legacy_check_targets_config_home_even_when_unset(self, tmp_path: Path):
        # arrange — legacy file under ~/.claude wins even without CLAUDE_CONFIG_DIR
        home = tmp_path / "home"
        legacy = home / ".claude" / ".config.json"
        legacy.parent.mkdir(parents=True)
        legacy.touch()

        # act
        resolved = path_resolver.global_config_path(EMPTY_ENV, home)

        # assert
        assert resolved == legacy


class TestGlobalConfigIn:
    """global_config_in: config path for an already-known config home (per-account dir)."""

    def test_defaults_to_claude_json_inside_home(self, tmp_path: Path):
        # arrange
        config_home = tmp_path / "scratch"

        # act
        resolved = path_resolver.global_config_in(config_home)

        # assert
        assert resolved == config_home / ".claude.json"

    def test_legacy_config_json_wins_when_it_exists(self, tmp_path: Path):
        # arrange
        config_home = tmp_path / "scratch"
        config_home.mkdir()
        (config_home / ".config.json").touch()

        # act
        resolved = path_resolver.global_config_in(config_home)

        # assert
        assert resolved == config_home / ".config.json"


class TestDataHome:
    """Our store root follows XDG: $XDG_DATA_HOME if absolute, else
    ~/.local/share — unset, empty, and non-absolute values are ignored
    (XDG Base Directory Specification)."""

    def test_absolute_xdg_value_wins(self, tmp_path: Path):
        # arrange
        env = {"XDG_DATA_HOME": str(tmp_path / "data")}

        # act
        resolved = path_resolver.data_home(env, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "data"

    def test_unset_defaults_to_local_share(self, tmp_path: Path):
        # arrange — env absent entirely (key missing, not just empty)
        # act
        resolved = path_resolver.data_home({}, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "home" / ".local" / "share"

    def test_empty_value_is_ignored(self, tmp_path: Path):
        # arrange
        env = {"XDG_DATA_HOME": ""}

        # act
        resolved = path_resolver.data_home(env, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "home" / ".local" / "share"

    def test_relative_value_is_ignored(self, tmp_path: Path):
        # arrange — spec: non-absolute XDG_DATA_HOME is ignored
        env = {"XDG_DATA_HOME": "relative/data"}

        # act
        resolved = path_resolver.data_home(env, tmp_path / "home")

        # assert
        assert resolved == tmp_path / "home" / ".local" / "share"

    def test_tilde_value_is_expanded_against_injected_home(self, tmp_path: Path):
        # arrange — "~" values (systemd units, containers) don't get shell expansion;
        # only the leading "~" is replaced, later ones are literal (XDG "~" handling)
        env = {"XDG_DATA_HOME": "~/data~"}
        home = tmp_path / "home"

        # act
        resolved = path_resolver.data_home(env, home)

        # assert
        assert resolved == home / "data~"
