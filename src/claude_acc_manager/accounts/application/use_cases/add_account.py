"""Register an account by capturing an isolated ``claude`` login."""

from claude_acc_manager.accounts.application.ports import (
    AccountDirReaderPort,
    AccountStorePort,
    ClockPort,
    LoginLauncherPort,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.oauth_identity import oauth_identity_from_config
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared import fsio


class AddAccount:
    """Launch ``claude`` login in the account's own dir, then register it.

    The login lands directly in the account's ``CLAUDE_CONFIG_DIR`` — tokens
    are never copied at add time (plan §4.4). The captured credential and
    ``oauthAccount`` identity are read back and the account is stored; a login
    that did not finish, or that produced no token / no identity, fails loudly
    and stores nothing.

    Example:
        AddAccount(launcher, reader, store, clock).execute(AccountName("work"))
    """

    def __init__(
        self,
        launcher: LoginLauncherPort,
        reader: AccountDirReaderPort,
        store: AccountStorePort,
        clock: ClockPort,
    ) -> None:
        """Store the injected ports."""
        self._launcher = launcher
        self._reader = reader
        self._store = store
        self._clock = clock

    def execute(self, name: AccountName) -> None:
        """Run the login for *name* and register the captured account.

        Raises ValueError when the login does not complete, writes no
        ``claudeAiOauth`` credential, or captures no ``oauthAccount`` identity.
        """
        account_dir = self._store.account_dir(name)
        fsio.ensure_private_dir(account_dir)  # 0700 before any token lands

        if not self._launcher.launch(account_dir):
            raise ValueError(f"claude login did not complete for account {name.value!r}")

        credentials, config = self._reader.read_account_data(account_dir)
        if "claudeAiOauth" not in credentials:
            raise ValueError(
                f"login for account {name.value!r} wrote no OAuth token "
                f"(credential keys: {sorted(credentials)})"
            )
        identity = oauth_identity_from_config(config)
        if identity is None:
            raise ValueError(f"login for account {name.value!r} captured no oauthAccount identity")

        # enabled is left to the entity default (True) — a new account is active
        self._store.upsert(
            Account(
                name=name,
                email=identity.email,
                account_uuid=identity.account_uuid,
                organization_uuid=identity.organization_uuid,
                organization_name=identity.organization_name,
                added_at=self._clock.now_iso(),
            )
        )
