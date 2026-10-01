"""Use case for switching the live account — the move-model transaction.

The five steps, in order, under claude-code's own mkdir locks:

1. Outgoing credentials leave the live slot — moved back into their
   account's dir, preserved under ``unclaimed/`` when the login matches
   no account, or destroyed when claude code already wiped the tokens
   (a wiped managed blob also quarantines its dead lineage).
2. The target's stored credential is staged into the live slot, composed
   with the machine's shared fields (mcpOAuth etc.) from the live blob.
3. The live config's ``oauthAccount`` is spliced to the target's identity.
4. The target's named credential copy is deleted — one lineage, one copy.
5. The registry's active pointer follows.

Any step's failure rolls back every prior one — each restore is attempted
independently and failures are attached as notes to the original error.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountStorePort,
    ActiveSlotPort,
    ClaudeLockPort,
    ClockPort,
    UnclaimedCredentialPort,
)
from claude_acc_manager.accounts.domain.credential_fields import (
    compose_activation_credentials,
    oauth_tokens_wiped,
    refresh_token_fingerprint,
)
from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.oauth_identity import oauth_identity_from_config
from claude_acc_manager.accounts.domain.services.identity_match import match_account_by_uuid
from claude_acc_manager.accounts.domain.services.switch_selection import (
    SkippedCandidate,
    SwitchSelection,
    SwitchStrategy,
    select_switch_target,
)
from claude_acc_manager.accounts.domain.value_objects import AccountName

SwitchStatus = Literal[
    "switched",
    "already-active",
    "no-valid-target",
    "already-best",
    "candidates-exhausted",
    "usage-unavailable",
]


@dataclass(frozen=True)
class SwitchResult:
    """What the switch did or would do — the CLI renders this verbatim."""

    outcome: SwitchStatus
    target: str | None = None
    previous: str | None = None
    unmanaged_live: bool = False
    preserved_to: Path | None = None
    quarantined: tuple[str, ...] = ()
    skipped: tuple[SkippedCandidate, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True)
class _LiveState:
    """The live slot, captured once, plus its outgoing classification."""

    credentials: dict[str, object] | None
    config: dict[str, object] | None
    matched: str | None
    wiped: bool
    unmanaged: bool


class SwitchAccount:
    """Move the target account's credential into the live slot, atomically.

    Example:
        switch = SwitchAccount(store, slot, files, unclaimed, locks, clock)
        result = switch.execute(AccountName("work"))
    """

    def __init__(
        self,
        store: AccountStorePort,
        slot: ActiveSlotPort,
        account_files: AccountDirPort,
        unclaimed: UnclaimedCredentialPort,
        locks: ClaudeLockPort,
        clock: ClockPort,
    ) -> None:
        """Store the injected ports."""
        self._store = store
        self._slot = slot
        self._files = account_files
        self._unclaimed = unclaimed
        self._locks = locks
        self._clock = clock

    def execute(
        self,
        target: AccountName | None = None,
        *,
        strategy: SwitchStrategy | None = None,
        headroom: Mapping[str, float | None] | None = None,
        dry_run: bool = False,
    ) -> SwitchResult:
        """Switch to *target*, or select one by *strategy* when target is None.

        A bare call rotates past the live account. *headroom* carries the
        caller's per-account measurements (missing = unknown, never
        exhausted). ``KeyError`` when *target* is unregistered; ``ValueError``
        when both a target and a strategy are passed.
        """
        if target is not None and strategy is not None:
            raise ValueError(
                f"cannot combine an explicit target {target.value!r} with strategy {strategy!r}"
            )
        self._refuse_scoped_shell()
        if target is None:
            # any non-"best"/non-"next-available" string reaches the same
            # _rotate branch — the literal is unmutatable-equivalent.
            chosen = strategy or "rotation"  # pragma: no mutate
            return self._select_and_apply(chosen, headroom or {}, dry_run)
        account = self._store.get(target)
        if account is None:
            raise KeyError(f"no account registered as {target.value!r}")
        if dry_run:
            return self._preview(target)
        return self._transact(target)

    def _select_and_apply(
        self,
        strategy: SwitchStrategy,
        headroom: Mapping[str, float | None],
        dry_run: bool,
    ) -> SwitchResult:
        """Feed live + registry state to switch_selection, then act on it."""
        live = self._capture()
        selection = self._pick(strategy, live, headroom)
        previous = live.matched if live.credentials is not None else None
        # target is None exactly when outcome != "switch" (domain contract) —
        # the or is a type-narrow, so the `and` mutant is equivalent.
        if selection.outcome != "switch" or selection.target is None:  # pragma: no mutate
            # the guard excluded "switch"; SwitchStatus's stay literals are a
            # subset of SwitchOutcome — cast is a no-op type-narrow.
            outcome = cast("SwitchStatus", selection.outcome)  # pragma: no mutate
            return SwitchResult(
                outcome=outcome,
                previous=previous,
                skipped=selection.skipped,
                dry_run=dry_run,
            )
        target = AccountName(selection.target)
        if dry_run:
            return SwitchResult(
                outcome="switched",
                target=selection.target,
                previous=previous,
                unmanaged_live=live.unmanaged,
                skipped=selection.skipped,
                dry_run=True,
            )
        return replace(self._transact(target), skipped=selection.skipped)

    def _pick(
        self,
        strategy: SwitchStrategy,
        live: _LiveState,
        headroom: Mapping[str, float | None],
    ) -> SwitchSelection:
        """Assemble the selection inputs: registry order, anchor, exclusions."""
        accounts = self._store.list_accounts()
        names = [account.name.value for account in accounts]
        current = live.matched if live.credentials is not None else None
        recorded = self._store.active()
        anchor = current or (recorded.name.value if recorded else None)
        return select_switch_target(
            names,
            anchor=anchor,
            current=current,
            strategy=strategy,
            disabled={account.name.value for account in accounts if not account.enabled},
            quarantined={entry.name for entry in self._store.quarantined()},
            has_credentials=self._dirs_with_credentials(names),
            headroom=headroom,
        )

    def _dirs_with_credentials(self, names: list[str]) -> set[str]:
        """Names whose account dir still parks a credential (the switchable set)."""
        return {
            name
            for name in names
            if self._files.read_credentials(self._store.account_dir(AccountName(name))) is not None
        }

    def _refuse_scoped_shell(self) -> None:
        """Refuse when the resolved live path sits inside a registered dir.

        Inside a ``CLAUDE_CONFIG_DIR``-scoped shell ``~/.claude`` resolves to
        one parked account dir — every "live" read and write would hit that
        account's store, so even a dry-run preview would describe the wrong
        slot.
        """
        live_path = self._slot.credentials_path()
        for account in self._store.list_accounts():
            account_dir = self._store.account_dir(account.name)
            if live_path.is_relative_to(account_dir):
                raise ValueError(
                    f"live credentials path {live_path} resolves inside "
                    f"registered account dir {account_dir} — refusing to "
                    f"switch inside a CLAUDE_CONFIG_DIR-scoped shell"
                )

    def _capture(self) -> _LiveState:
        """Read the live slot and classify whose credential sits in it."""
        credentials = self._slot.read_credentials()
        config = self._slot.read_config()
        identity = oauth_identity_from_config(config) if config is not None else None
        matched = self._match(identity.account_uuid) if identity else None
        wiped = credentials is not None and oauth_tokens_wiped(credentials)
        unmanaged = credentials is not None and matched is None and not wiped
        return _LiveState(credentials, config, matched, wiped, unmanaged)

    def _match(self, account_uuid: str) -> str | None:
        """The registered account owning *account_uuid* (status's rule)."""
        return match_account_by_uuid(self._store.list_accounts(), account_uuid)

    def _preview(self, target: AccountName) -> SwitchResult:
        """Report what a switch would do — no locks, no writes."""
        live = self._capture()
        previous = live.matched if live.credentials is not None else None
        if live.matched == target.value and live.credentials is not None:
            return SwitchResult(
                outcome="already-active", target=target.value, previous=previous, dry_run=True
            )
        target_dir = self._store.account_dir(target)
        self._require_target(target, target_dir)
        return SwitchResult(
            outcome="switched",
            target=target.value,
            previous=previous,
            unmanaged_live=live.unmanaged,
            dry_run=True,
        )

    def _require_target(
        self, target: AccountName, target_dir: Path
    ) -> tuple[dict[str, object], dict[str, object]]:
        """The target's parked credential + its oauthAccount marker.

        Absent parked credentials mean the account's lineage is lost — under
        the move model they should be live or parked, nowhere else.
        """
        credentials = self._files.read_credentials(target_dir)
        if credentials is None:
            raise ValueError(
                f"account {target.value!r} has no stored credentials — "
                f"expected {target_dir}/.credentials.json"
            )
        config = self._files.read_config(target_dir)
        oauth_account = config.get("oauthAccount") if config else None
        if not isinstance(oauth_account, dict):
            raise ValueError(
                f"account {target.value!r} config carries no oauthAccount object — "
                f"expected {target_dir} config with an oauthAccount block"
            )
        # cast() is a runtime no-op; isinstance already proved the shape.
        return credentials, cast("dict[str, object]", oauth_account)  # pragma: no mutate

    def _transact(self, target: AccountName) -> SwitchResult:
        """Run the five-step switch under claude-code's locks."""
        with self._locks.credentials_locked(), self._locks.config_locked():
            live = self._capture()
            quarantined = self._tombstone_if_wiped(live)
            target_dir = self._store.account_dir(target)
            if live.matched == target.value and live.credentials is not None:
                return SwitchResult(
                    outcome="already-active",
                    target=target.value,
                    previous=target.value,
                    quarantined=quarantined,
                )
            target_creds, target_oauth = self._require_target(target, target_dir)
            previous_active = self._store.active()
            preserved_to, moved_back = self._retire_outgoing(live)
            try:
                self._slot.write_credentials(
                    compose_activation_credentials(target_creds, live.credentials)
                )
                self._slot.splice_config_oauth_account(target_oauth)
                self._files.delete_credentials(target_dir)
                self._store.set_active(target)
            except Exception as exc:
                self._rollback(exc, live, target_dir, target_creds, moved_back, previous_active)
                raise
            return SwitchResult(
                outcome="switched",
                target=target.value,
                previous=live.matched,
                unmanaged_live=live.unmanaged,
                preserved_to=preserved_to,
                quarantined=quarantined,
            )

    def _tombstone_if_wiped(self, live: _LiveState) -> tuple[str, ...]:
        """Quarantine the matched account when claude wiped its tokens."""
        if live.credentials is None or not live.wiped or live.matched is None:
            return ()
        entry = QuarantineEntry(
            live.matched,
            "permanent_auth_error",
            self._clock.now_iso(),
            refresh_token_fingerprint(live.credentials),
        )
        self._store.set_quarantined(entry)
        return (live.matched,)

    def _retire_outgoing(self, live: _LiveState) -> tuple[Path | None, Path | None]:
        """Move a managed live credential home; stash a foreign one.

        Returns ``(preserved_to, moved_back_dir)`` — wiped or absent
        credentials have nothing to retire.
        """
        if live.credentials is None or live.wiped:
            return None, None
        if live.matched is None:
            return self._unclaimed.preserve(live.credentials, live.config, "foreign"), None
        account_dir = self._store.account_dir(AccountName(live.matched))
        self._files.write_credentials(account_dir, live.credentials)
        return None, account_dir

    def _rollback(
        self,
        original: Exception,
        live: _LiveState,
        target_dir: Path,
        target_creds: dict[str, object],
        moved_back: Path | None,
        previous_active: Account | None,
    ) -> None:
        """Restore every prior component; failures ride along as notes."""
        restores: list[tuple[str, Callable[[], None]]] = [
            (
                "active pointer",
                lambda: self._store.set_active(previous_active.name if previous_active else None),
            ),
            ("target credential", lambda: self._files.write_credentials(target_dir, target_creds)),
            ("live config", lambda: self._restore_config(live.config)),
            ("live credentials", lambda: self._restore_credentials(live.credentials)),
        ]
        if moved_back is not None:
            restores.append(
                ("outgoing credential", lambda: self._files.delete_credentials(moved_back))
            )
        for label, restore in restores:
            try:
                restore()
            except Exception as rb:  # noqa: BLE001 — best-effort restore
                original.add_note(f"rollback of {label} failed: {rb!r}")

    def _restore_credentials(self, credentials: dict[str, object] | None) -> None:
        """Put the live slot's credentials back — including "was absent"."""
        if credentials is None:
            self._slot.delete_credentials()
            return
        self._slot.write_credentials(credentials)

    def _restore_config(self, config: dict[str, object] | None) -> None:
        """Put the live config back — including "was absent"."""
        if config is None:
            self._slot.delete_config()
            return
        self._slot.write_config(config)
