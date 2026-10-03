"""Unit tests for accounts.domain.credential_fields.

The shared-field compose (machine-shared MCP OAuth keys are live-owned,
everything else is slot-owned) and the lineage fingerprint bind onto parsed
credential dicts — our files are already JSON objects at the port boundary,
so these functions take ``Mapping``, not raw JSON strings.
"""

import hashlib
import json

from claude_acc_manager.accounts.domain.credential_fields import (
    compose_activation_credentials,
    oauth_tokens_wiped,
    refresh_token_fingerprint,
    shared_credential_fields,
)


def _creds(**oauth: object) -> dict[str, object]:
    """A credentials-shaped dict carrying *oauth* under ``claudeAiOauth``."""
    return {"claudeAiOauth": dict(oauth)}


class TestSharedCredentialFields:
    """Only the SHARED_CREDENTIAL_KEYS allowlist is machine-shared."""

    def test_none_means_no_live_credential_object(self):
        # arrange / act / assert
        assert shared_credential_fields(None) is None

    def test_absent_shared_keys_yield_empty_dict(self):
        # arrange — {} is authoritative: no shared key is held by the machine
        creds = _creds(accessToken="at", refreshToken="rt")

        # act / assert
        assert shared_credential_fields(creds) == {}

    def test_extracts_only_allowlisted_keys(self):
        # arrange
        creds = {
            "claudeAiOauth": {"accessToken": "at"},
            "mcpOAuth": {"server": {"token": "t"}},
            "pluginSecrets": {"k": "v"},
            "trustedDeviceToken": "device-secret",
        }

        # act
        fields = shared_credential_fields(creds)

        # assert
        assert fields == {"mcpOAuth": {"server": {"token": "t"}}, "pluginSecrets": {"k": "v"}}

    def test_every_allowlisted_key_is_extracted(self):
        # arrange
        creds = {
            "mcpOAuth": 1,
            "mcpOAuthClientConfig": 2,
            "mcpXaaIdp": 3,
            "mcpXaaIdpConfig": 4,
            "pluginSecrets": 5,
        }

        # act / assert
        assert shared_credential_fields(creds) == {
            "mcpOAuth": 1,
            "mcpOAuthClientConfig": 2,
            "mcpXaaIdp": 3,
            "mcpXaaIdpConfig": 4,
            "pluginSecrets": 5,
        }


class TestComposeActivationCredentials:
    """The activated credential = target blob minus shared keys plus live's."""

    def test_no_live_credential_activates_the_target_verbatim(self):
        # arrange
        target = _creds(accessToken="at-target")
        target["mcpOAuth"] = {"stale": True}

        # act / assert — a fresh machine has no live object to take shared
        # fields from, so the stored blob activates unchanged
        assert compose_activation_credentials(target, None) == target

    def test_live_shared_keys_win_presence_and_absence(self):
        # arrange — live holds the current mcpOAuth generation; the target's
        # frozen copy and any key the machine no longer holds must not survive
        target = {
            "claudeAiOauth": {"accessToken": "at-target", "refreshToken": "rt-target"},
            "mcpOAuth": {"old": "copy"},
            "pluginSecrets": {"old": "copy"},
            "trustedDeviceToken": "target-device",
        }
        live = {
            "claudeAiOauth": {"accessToken": "at-outgoing"},
            "mcpOAuth": {"new": "copy"},
            "organizationUuid": "org-9",
        }

        # act
        composed = compose_activation_credentials(target, live)

        # assert
        assert composed == {
            "claudeAiOauth": {"accessToken": "at-target", "refreshToken": "rt-target"},
            "trustedDeviceToken": "target-device",
            "mcpOAuth": {"new": "copy"},
        }

    def test_unknown_sibling_keys_stay_slot_owned(self):
        # arrange — an unrecognized sibling defaults to slot-owned (fails safe)
        target = _creds(accessToken="at")
        target["someFutureKey"] = {"kept": True}
        live = _creds(accessToken="other")

        # act / assert
        assert compose_activation_credentials(target, live) == target

    def test_target_and_live_inputs_are_not_mutated(self):
        # arrange
        target = {"claudeAiOauth": {}, "mcpOAuth": {"t": 1}}
        live = {"mcpOAuth": {"l": 2}}

        # act
        compose_activation_credentials(target, live)

        # assert
        assert target == {"claudeAiOauth": {}, "mcpOAuth": {"t": 1}}
        assert live == {"mcpOAuth": {"l": 2}}


class TestRefreshTokenFingerprint:
    """The fingerprint binds the refresh-token lineage, surviving AT rotation."""

    def test_refresh_token_sha256_with_prefix(self):
        # arrange
        creds = _creds(accessToken="at", refreshToken="rt-lineage")

        # act / assert
        expected = "sha256:" + hashlib.sha256(b"rt-lineage").hexdigest()
        assert refresh_token_fingerprint(creds) == expected

    def test_access_token_rotation_keeps_the_fingerprint(self):
        # arrange — two generations of one lineage
        before = _creds(accessToken="at-1", refreshToken="rt-same", expiresAt=1)
        after = _creds(accessToken="at-2", refreshToken="rt-same", expiresAt=2)

        # act / assert
        assert refresh_token_fingerprint(before) == refresh_token_fingerprint(after)

    def test_different_refresh_tokens_differ(self):
        # arrange / act / assert
        assert refresh_token_fingerprint(_creds(refreshToken="rt-a")) != refresh_token_fingerprint(
            _creds(refreshToken="rt-b")
        )

    def test_no_refresh_token_falls_back_to_canonical_content_hash(self):
        # arrange — a blob without an RT: content identity is lineage identity
        creds = _creds(accessToken="at")

        # act
        fingerprint = refresh_token_fingerprint(creds)

        # assert — canonical (sorted-keys) JSON is what makes the hash stable
        expected = (
            "sha256-json:" + hashlib.sha256(json.dumps(creds, sort_keys=True).encode()).hexdigest()
        )
        assert fingerprint == expected

    def test_content_hash_is_key_order_independent(self):
        # arrange / act / assert
        assert refresh_token_fingerprint({"a": 1, "b": 2}) == refresh_token_fingerprint(
            {"b": 2, "a": 1}
        )

    def test_blank_refresh_token_uses_content_hash(self):
        # arrange
        creds = _creds(accessToken="at", refreshToken="")

        # act / assert — an empty string is not a lineage to bind
        assert refresh_token_fingerprint(creds) is not None
        assert refresh_token_fingerprint(creds).startswith("sha256-json:")


class TestOauthTokensWiped:
    """Claude Code's invalid_grant reaction empties both token fields in place."""

    def test_empty_access_and_refresh_tokens_is_wiped(self):
        # arrange — the observed shape: wrapper and metadata survive
        creds = _creds(accessToken="", refreshToken="", expiresAt=123)

        # act / assert
        assert oauth_tokens_wiped(creds) is True

    def test_missing_token_fields_is_wiped(self):
        # arrange / act / assert
        assert oauth_tokens_wiped(_creds(scopes=["user:profile"])) is True

    def test_any_present_token_is_not_wiped(self):
        # arrange / act / assert
        assert oauth_tokens_wiped(_creds(accessToken="", refreshToken="rt")) is False
        assert oauth_tokens_wiped(_creds(accessToken="at")) is False

    def test_no_oauth_blob_is_not_wiped(self):
        # arrange — not an OAuth credential at all; "wiped" is a precise claim
        # about a known shape, so foreign bytes are preserved, not flagged
        assert oauth_tokens_wiped({"other": "blob"}) is False

    def test_non_object_oauth_value_is_not_wiped(self):
        # arrange / act / assert — a torn inner shape is not evidence of wiping
        assert oauth_tokens_wiped({"claudeAiOauth": "torn"}) is False
