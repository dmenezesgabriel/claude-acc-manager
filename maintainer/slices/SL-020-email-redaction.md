# SL-020 — keep account emails out of screenshots

Milestone: M19 · State: open · Depends on: — · Closes: —

> Written at pickup per `_TEMPLATE.md`. Deleted when M19 ships.

## Outcome

A user can flip email visibility off (default) and on with one key so a TUI or terminal screenshot never exposes the account emails behind their account names.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below. Measurements go in the closing commit's body.

1. `cam config get privacy.redactEmails` → `true` on a fresh store (redacted by default).
2. `cam list` prints names without emails; `cam list --json` still carries `email` (machine contract untouched).
3. TUI: minis, active card, auto-view rows, dashboard submenu, and the remove modal all omit the email; pressing `p` reveals them everywhere at once and writes `privacy.redactEmails: false` to `settings.json`; pressing `p` again re-hides and re-persists.
4. Settings screen shows the new row; editing it there repaints the TUI immediately (same path as `autoswitch.threshold`).
5. `cam config set privacy.redactEmails not-a-bool` fails loudly naming the key and the expected `true`/`false`.

Maintainer decisions settled before this PRD was written (2026-10 session): redacted by default · key + persisted setting · TUI + CLI human output · `--json` stays raw.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | ABSENT | `research_repos/claude-swap/src/claude_swap/tui/widgets.py` (~178, ~257), `tui/dashboard.py` (~98, ~113), `tui/autoview.py` (~310), `tui/app.py` (~317) | renders `alias (email)` unconditionally in the same five-site shape our TUI inherited; no toggle, no setting |
| ai-usagebar | ABSENT (precedent only) | `research_repos/ai-usagebar/src/tui/settings.rs` (~245, ~929, ~1120) | account emails are not its surface; its masking precedent is API-key *input fields* — masked by default, revealed on toggle |
| claude-code itself | — | `oauthAccount.emailAddress` in `.claude.json` is where the email comes from | not a display surface we interoperate with |

**Count:** 0 of the references implement this. An invention, justified by the maintainer's stated need: the repo is public, so TUI/terminal screenshots land in issues and docs, and the emails behind account names are third-party-identifying. ai-usagebar's masked-by-default-then-reveal pattern for sensitive values is the adopted precedent for the default state.

## Implementation inventory

No reference implements it, so the inventory is our own surface — the files an implementer must open.

### Ours — render sites (the leak)

| Concern | Files |
| --- | --- |
| Mini lines (inactive accounts) | `src/claude_acc_manager/tui/formatting.py` `_mini_header` (~345) |
| Active account card | `src/claude_acc_manager/tui/visuals.py` `_card_header` (~212) |
| Auto-view candidate rows | `src/claude_acc_manager/tui/autoview.py` (~238) |
| Dashboard submenu labels | `src/claude_acc_manager/tui/dashboard.py` (~189) |
| Remove-account modal | `src/claude_acc_manager/tui/app.py` (~471) |
| `cam list` rows / `cam status` line | `src/claude_acc_manager/cli/commands.py` (~74, ~94) |

All five TUI sites duplicate the same `if account.email: append(f" ({account.email})")` — the duplication is why the helper gets one home.

### Ours — machinery the toggle rides

| Concern | Files |
| --- | --- |
| Spec schema (kinds, defaults, clamps, strict parse) | `src/claude_acc_manager/settings/domain/settings_spec.py` — `SettingSpec.kind` is `Literal["float", "choice"]`; `spec_default` reads off `AutoSettings` only; `SETTING_SPECS` holds five `autoswitch.*` keys |
| Port | `src/claude_acc_manager/settings/application/ports.py` — `load() -> AutoSettings` |
| Adapter | `src/claude_acc_manager/settings/infrastructure/file_settings.py` — `load`/`effective` read only the `autoswitch` section; `set_value`/`unset_value` are already section-generic via `spec.section` |
| Use cases + wiring | `src/claude_acc_manager/settings/application/use_cases/{load,set,unset,list}_settings.py`; bundle wired at `src/claude_acc_manager/__main__.py` (~116) |
| TUI state + repaint | `src/claude_acc_manager/tui/app.py` — `threshold_pct: reactive` seeded on mount (~232), live-updated by `apply_setting` (~377); widgets read `app.threshold_pct` at render (`tui/widgets.py` ~79, ~99) |
| Visual cache | `src/claude_acc_manager/tui/visuals.py` — `_STRIPS` keyed on `(text.plain, style, spans)` (~68): a changed rendering self-invalidates; no cache surgery needed |
| Settings screen editor | `src/claude_acc_manager/tui/settings_screen.py` — `_editor` branches on `kind` (Select for choice, number Input otherwise) |
| CLI config commands | `src/claude_acc_manager/cli/commands.py` `config_list/get/set/unset` (~272–305) — spec-driven, key-agnostic |
| Docs | `docs/reference/settings.md` (key table says "All five keys tune the `cam auto` engine"), `src/claude_acc_manager/settings/domain/settings_spec.py` module docstring ("The `autoswitch` settings section"), `tui/settings_screen.py` docstring |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Default state | ai-usagebar → sensitive input masked by default, revealed on toggle; claude-swap/ours → always visible | redacted-by-default changes today's display for existing users; visible-by-default leaks on a forgotten toggle | **Redacted by default** — maintainer decision; a screenshot is safe without remembering anything, and account names already identify accounts |
| Mask style | (none in references) omit entirely · partial `g***@…` · placeholder `(hidden)` | partial keeps a hint of the address; omission is unambiguous | **Omit entirely** — cleanest screenshots; no invented glyph grammar to explain |
| Mechanism | (none in references) session keybinding only · persisted setting + keybinding · setting only | session-only is a third of the work but resets every launch and can't preset | **Persisted `privacy.redactEmails` + `e` keybinding that writes through** — durable privacy default plus the quick pre-screenshot flip; reuses the `apply_setting` write path |
| Scope | — TUI only · TUI + CLI human output | terminal screenshots leak the same way | **Both**; `--json` stays raw — the M7 schema contract is machine-facing |
| Settings domain shape | — second dataclass + per-section defaults · one combined dataclass | a combined record reshapes `load()`'s contract and every `cam auto` consumer | **Second dataclass `PrivacySettings` + section→dataclass map in `spec_default`; port gains `load_privacy()`** — `load() -> AutoSettings` and the auto plumbing stay untouched |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Email rendering toggle | absent — 5 TUI sites + 2 CLI sites print unconditionally | claude-swap `tui/widgets.py` (same shape, also absent) | **absent** |
| Persisted user setting for display | `settings.json` machinery exists but is `autoswitch`-shaped (one section, `float`/`choice` kinds, `load() -> AutoSettings`) | ai-usagebar `tui/settings.rs` (masked input precedent) | **present but partial** — the port/spec/adapter generalize, the domain does not |

## Deviations

Nothing is ported — the feature is an invention (justified above). The one borrowed pattern (ai-usagebar's masked-by-default sensitive value) is a default-state choice, not code.

## Open decisions

None — all four axes were settled by the maintainer before pickup (see Exit gate).

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `src/claude_acc_manager/settings/domain/settings_spec.py` (bool kind, `PrivacySettings`, `clamped_privacy_settings`, section-map `spec_default`, strict bool parse) |
| application | `settings/application/ports.py` (`load_privacy`), `settings/application/use_cases/load_privacy_settings.py` |
| infrastructure | `settings/infrastructure/file_settings.py` (`load_privacy`, section-generic `effective`) |
| cli | `cli/commands.py` (`cmd_list`, `cmd_status` read the flag) |
| tui | `tui/formatting.py` (shared `email_fragment` helper), `tui/visuals.py`, `tui/autoview.py`, `tui/dashboard.py`, `tui/app.py` (reactive + `e` action + modal), `tui/widgets.py` (thread the flag), `tui/settings_screen.py` (bool editor) |
| tests | `tests/settings/…` (spec + adapter + use case), `tests/tui/…` (render sites redacted/visible, toggle Pilot), `tests/cli/…` (human matrix) |

## Tasks

One TDD unit each, one conventional commit each.

- [x] T1 — `feat(settings)`: `privacy.redactEmails` end-to-end in the settings component — `bool` kind, `PrivacySettings` (default `True`), forgiving clamp, strict `true`/`false` parse, section-map `spec_default`, port `load_privacy()`, adapter second section, `LoadPrivacySettings` use case wired in `__main__.py`, `EffectiveSetting.value`/`format_setting_value` widened to bool, settings-screen bool editor (Select riding the choice branch); `docs/reference/settings.md` key table + module docstring generalized
- [x] T2 — `feat(tui)`: shared `email_fragment` helper in `tui/formatting.py`; all five TUI sites consume it; `CamApp.redact_emails` reactive (default `True`) seeded from `load_privacy_settings`, `p` binding flips via `apply_setting` (persists + repaints) — `e` was already the root menu's enable/disable accelerator, so `p` (privacy) carries the toggle; menu frames gained a builder slot so a flip mid-submenu rebuilds baked labels
- [x] T3 — `feat(cli)`: `cmd_list`/`cmd_status` honor the flag in human output; `--json` payloads untouched

## Out of scope

- Partial masking styles (`g***@…`) — omission was chosen; a style axis would need a consumer first.
- Redacting account names or the `--json` payloads — names are user-chosen labels; JSON is the machine contract (M7).
- `cam doctor` / usage human output — verified today to print no emails.
- Hiding emails in `cam remove`'s JSON or in claude-code's own surfaces — out of our reach.
