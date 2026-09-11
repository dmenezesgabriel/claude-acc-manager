"""Unit tests for usage.domain.services.poll_policy.

Ports claude-swap poll_policy.py's plan_after_fetch tests
(research_repos/claude-swap/tests/test_poll_policy.py) onto our signature,
which takes an already-extracted binding pct (from headroom.account_headroom)
rather than a raw usage dict, and drops threshold/urgent-mode (M5 plan
decision 1 — deferred to M9, the auto loop that actually owns a threshold).
"""

from claude_acc_manager.usage.domain.services import poll_policy

NOW = 1_000_000.0
HALF = lambda: 0.5  # noqa: E731 — rng midpoint: jitter factor exactly 1.0


def _plan(**overrides: object) -> tuple[float, float]:
    kwargs: dict[str, object] = {
        "prev_interval_s": None,
        "prev_pct": None,
        "new_pct": 10.0,
        "is_active": False,
        "now_s": NOW,
        "rng": HALF,
    }
    kwargs.update(overrides)
    return poll_policy.plan_after_fetch(**kwargs)  # type: ignore[arg-type]


class TestIntervalAdaptation:
    def test_first_fetch_uses_defaults(self):
        _, active = _plan(is_active=True)
        _, candidate = _plan(is_active=False)
        assert active == poll_policy.MIN_INTERVAL_S
        assert candidate == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S

    def test_unmoved_decays_toward_the_ceiling(self):
        _, interval = _plan(prev_interval_s=300.0, prev_pct=10.0)
        assert interval == 450.0

    def test_unmoved_decay_caps_at_the_candidate_ceiling(self):
        _, capped = _plan(prev_interval_s=500.0, prev_pct=10.0)
        assert capped == poll_policy.CANDIDATE_MAX_INTERVAL_S

    def test_unmoved_decay_caps_at_the_active_ceiling(self):
        _, active_capped = _plan(prev_interval_s=250.0, prev_pct=10.0, is_active=True)
        assert active_capped == poll_policy.ACTIVE_MAX_INTERVAL_S

    def test_movement_halves_floored_at_min(self):
        _, interval = _plan(prev_interval_s=600.0, prev_pct=10.0, new_pct=15.0)
        assert interval == 300.0

    def test_movement_halving_never_drops_below_the_floor(self):
        _, floored = _plan(prev_interval_s=200.0, prev_pct=10.0, new_pct=15.0)
        assert floored == poll_policy.MIN_INTERVAL_S

    def test_sub_delta_wiggle_is_not_movement(self):
        _, interval = _plan(prev_interval_s=300.0, prev_pct=10.0, new_pct=10.5)
        assert interval == 450.0

    def test_delta_exactly_at_the_threshold_is_movement(self):
        _, interval = _plan(
            prev_interval_s=600.0, prev_pct=10.0, new_pct=10.0 + poll_policy.MOVEMENT_DELTA_PCT
        )
        assert interval == 300.0

    def test_unknown_new_pct_uses_the_default(self):
        _, interval = _plan(prev_interval_s=600.0, prev_pct=10.0, new_pct=None)
        assert interval == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S

    def test_unknown_prev_pct_uses_the_default(self):
        _, interval = _plan(prev_interval_s=600.0, prev_pct=None, new_pct=10.0)
        assert interval == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S


class TestJitter:
    def test_jitter_bounds(self):
        interval = poll_policy.CANDIDATE_DEFAULT_INTERVAL_S
        early, _ = _plan(rng=lambda: 0.0)
        late, _ = _plan(rng=lambda: 1.0)
        assert early == NOW + interval * (1.0 - poll_policy.JITTER_FRAC)
        assert late == NOW + interval * (1.0 + poll_policy.JITTER_FRAC)
