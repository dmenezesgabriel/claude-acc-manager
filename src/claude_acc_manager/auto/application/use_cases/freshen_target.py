"""FreshenTarget — prove a candidate's parked credential is alive before switching to it.

A parked account's ``expiresAt`` may sit inside Claude Code's 5-minute
refresh buffer (or past it): activating it would hand Claude Code a token
it must immediately rotate — or worse, one whose refresh grant is already
dead. The engine therefore freshens each candidate before committing:
refresh through ``TokenRefresherPort`` when the parked token is near/at
expiry and persist the rotation through ``CredentialStorePort``.

Only ever touches the candidate's *parked* credential — the active
account's tokens belong to Claude Code (ADR-0009) and a candidate is by
definition not active.

Three outcomes: ``"ok"`` (safe to activate), ``"dead"`` (the lineage is
provably dead — the caller quarantines), ``"transient"`` (network trouble
or a missing credential file — try again next tick). There is no
identity-conflict axis: the wire model doesn't parse token-account
identity.

Example:
    outcome = FreshenTarget(refresher, credentials, clock, probe).execute("work")
"""

from claude_acc_manager.auto.application.ports import FreshenStatus
from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    ClaudeContractPort,
    ClockPort,
    CredentialStorePort,
    HttpTransportError,
    TokenRefresherPort,
)
from claude_acc_manager.usage.domain.oauth_credential import token_expired


class FreshenTarget:
    """Refresh a candidate's expired parked token; classify the lineage's health.

    Example:
        freshen = FreshenTarget(refresher, credentials, clock, probe)
        if freshen.execute("personal") == "ok":
            ...
    """

    def __init__(
        self,
        refresher: TokenRefresherPort,
        credentials: CredentialStorePort,
        clock: ClockPort,
        claude_contract: ClaudeContractPort,
    ) -> None:
        """Store the injected ports."""
        self._refresher = refresher
        self._credentials = credentials
        self._clock = clock
        self._claude_contract = claude_contract

    def execute(self, account_key: str) -> FreshenStatus:
        """``"ok"`` when the account's credential is fit to activate right now.

        Example:
            freshen.execute("work")  # "ok" | "dead" | "transient"
        """
        credential = self._credentials.read(account_key)
        if credential is None:
            return "transient"
        if not token_expired(credential.expires_at_ms, self._clock.now_epoch_s() * 1000.0):
            return "ok"
        if not credential.refresh_token:
            return "dead"
        return self._refresh(account_key, credential.refresh_token)

    def _refresh(self, account_key: str, refresh_token: str) -> FreshenStatus:
        """Run the grant; ``invalid_grant`` means the lineage is dead.

        The contract gate precedes the grant — the refresh token is
        one-time-use, so an unverifiable claude fails closed (propagating
        to the engine's ERROR) rather than consuming it.
        """
        self._claude_contract.probe().require_supported()
        try:
            refreshed = self._refresher.refresh(refresh_token)
        except AnthropicApiError as exc:
            return "dead" if exc.error_code == "invalid_grant" else "transient"
        except HttpTransportError:
            return "transient"
        self._credentials.persist_rotation(
            account_key,
            refreshed.access_token,
            refreshed.refresh_token or refresh_token,
            self._clock.now_epoch_s() * 1000.0 + refreshed.expires_in_s * 1000.0,
        )
        return "ok"
