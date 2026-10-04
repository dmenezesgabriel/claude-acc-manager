# SL-013 — TUI UX affordances (discoverability, status, settings, responsive)

Milestone: M12 · State: open · Depends on: SL-012 (shipped, deleted) · Closes: —

## Outcome

A `cam tui` user can discover every key via F1 and a command palette, see
action progress as a throbber and the terminal title, edit `settings.json`
without leaving the TUI, and keep a usable layout in a ~60-column terminal —
while every bar render lands on a cached `Strip` instead of rebuilding `Text`
cell-by-cell.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then
the manual validation below, scripted against the real tool. Measurements go
in the closing commit's body.

1. `cam tui` in a real terminal: F1 opens the help panel showing grouped bindings; F1 again closes it.
2. `ctrl+space`/palette: typing `sw` ranks "Switch account" hits including per-account `switch to '<name>'`; choosing one switches.
3. Trigger a switch/remove — a throbber strip shows while the worker runs; an unfocused terminal's title blinks ~3s.
4. Menu: every row shows its accelerator; pressing it activates the row; digits pick account rows in submenus; `j`/`k`/Esc/← are never swallowed.
5. `settings` entry (menu + palette): rows render per spec kind (number Input, choice Select) seeded with effective values; a valid edit persists to `settings.json`; an out-of-range number notifies and reverts; `autoswitch.threshold` moves the bar tick live.
6. Narrow: at ~60 columns the `-narrow` class lands, minis collapse, bars still render; at ≥100 `-wide` restores.
7. `TERM=dumb cam tui` renders without broken glyphs; text-selection drag no longer selects chrome labels.
8. Startup shows the branded loading widget instead of the stock dots.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `src/claude_swap/tui/app.py`, `src/claude_swap/tui/dashboard.py` | Same older idiom layer we ported: title-slot status on watch, nested ListView menu, no help panel, no palette, no throbber |
| ai-usagebar | PARTIAL | `src/tui/settings.rs`, `src/display.rs` | ratatui settings overlay generated from a per-vendor `keys` schema vec; always-exits-0 widget contract |
| toad | FULL — the pattern source | `src/toad/app.py`, `src/toad/screens/`, `src/toad/widgets/`, `src/toad/visuals/`, `src/toad/toad.tcss` | F1 HelpPanel + `Binding.Group`/`tooltip=`/`key_display=`, `Throbber` Visual, terminal title + blink, menu `key` accelerators, `ALLOW_SELECT=False`, `HORIZONTAL_BREAKPOINTS`, palette `Provider`, schema-generated settings screen, `lazy.Reveal`, `get_loading_widget` |
| claude-code itself | — | no TUI interop surface for these features | n/a |

**Count:** 1 of the references implements this set fully. toad is the same textual generation we already ported M11 idioms from; every cited API (`HelpPanel`, `Binding.Group`, `tooltip=`, `key_display=`, `HORIZONTAL_BREAKPOINTS`, `Provider`/`Hit`/`DiscoveryHit`, `lazy.Reveal`, `get_loading_widget`, `Visual`/`Strip`, `prevent(Msg)`) was exercised against our pinned `textual==8.2.8` on 2026-10-04.

## Implementation inventory

### toad (`research_repos/toad`)

| Concern | Files |
| --- | --- |
| App-level bindings/groups/tooltips | `src/toad/app.py` (`BINDING_GROUP_TITLE`, `BINDINGS` with `tooltip=`/`key_display=`, `action_toggle_help_panel`), `src/toad/screens/main.py` (`SESSION_NAVIGATION_GROUP = Binding.Group(...)`, `BINDING_GROUP_TITLE`) |
| Busy throbber | `src/toad/widgets/throbber.py` (`ThrobberVisual(Visual)` — `lru_cache`'d `make_segments`, `auto_refresh = 1/15`), `-busy` class styles in `src/toad/toad.tcss` |
| Terminal title + blink | `src/toad/app.py` (`update_terminal_title`, `terminal_title`, `terminal_title_flash`, `terminal_title_blink`, `watch_*`, `terminal_alert`) |
| Menu accelerators | `src/toad/widgets/menu.py` (`MenuItem(description, action, key)` via `src/toad/menus.py`, `Menu.on_key` jump+activate, `overlay: screen` CSS) |
| ALLOW_SELECT chrome | `src/toad/widgets/menu.py` (`NonSelectableLabel`, `MenuOption`), `src/toad/widgets/question.py`, `src/toad/widgets/session_tabs.py` |
| Responsive width | `src/toad/app.py` `HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]`, `-narrow`/`-wide` rules in `src/toad/toad.tcss` |
| Command palette | `src/toad/screens/main.py` (`ModeProvider(Provider)`, `COMMANDS`, `matcher`, `Hit`, `DiscoveryHit`) |
| Settings screen | `src/toad/screens/settings.py` (schema→widget per `Setting.type`: `Input`+`Number` validators/`Select`/`Checkbox`, `self.prevent(Changed)` while seeding, blur/submit write + invalid→notify+revert, `filter_settings` search), `src/toad/settings.py` (`Schema`/`Settings`) |
| Loading widget | `src/toad/screens/main.py` `get_loading_widget` (settings-driven `FutureText` vs stock) |
| Visual/Strip renderers | `src/toad/visuals/columns.py` (`Columns._render_cache: LRUCache`, `Strip.from_lines`, `Content.render_segments`), `src/toad/widgets/throbber.py`, `src/toad/widgets/option_content.py` |
| Flash status line (NOT adopted) | `src/toad/widgets/flash.py` — self-hiding transient banner; our `notify()` covers that semantic |
| Exit recap (NOT adopted) | `src/toad/app.py` `run_on_exit` — prints an upgrade-nag Panel, not an outcome recap |

### claude-swap (`research_repos/claude-swap`)

| Concern | Files |
| --- | --- |
| Status line | `src/claude_swap/tui/app.py` (`refresh_status` reactive), `src/claude_swap/tui/dashboard.py` (`_title_text`/`_on_refresh_status` — the watch-title slot we ported) |
| Nested menu | `src/claude_swap/tui/dashboard.py` (`_menu_stack`, `MenuItem`) — same design as ours; no accelerators, no overlay |

Disagreement to decide: toad overlays a popup `Menu`; claude-swap (and we) use a nested-stack ListView — resolved in Deviations.

### ai-usagebar (`research_repos/ai-usagebar`)

| Concern | Files |
| --- | --- |
| Settings overlay | `src/tui/settings.rs` — schema-driven rows (`keys` vec: label, help, env hint), toml_edit-backed save, sanitizes untrusted text at the sink |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| Refresh-status surface | toad → self-hiding `Flash` banner; claude-swap → persistent title slot on one screen | Flash is a transient-notification widget (our `notify()` covers that); persistent state must not auto-hide | Title slot on **every** screen — append `refresh_status` to the existing `#menu-title`/`#list-title`/`#auto-summary` Statics; zero new widgets |
| Menu accelerators | toad → overlay `Menu` widget; claude-swap → none | Overlay replaces primary nav and drops the breadcrumb; we only need the key idiom | `key` field on our `MenuItem` + `on_key` dispatch on `DashboardScreen`; digits on per-account rows |
| Exit recap | toad → `run_on_exit` upgrade nag; others → none | 0/3 references print an outcome recap — invention; toasts already cover outcomes | Not adopted |
| Settings screen data flow | toad → live `Settings` object + schema; ai-usagebar → schema vec + save | We already have `SETTING_SPECS` + `EffectiveSetting` + strict `SetSetting` | Generate rows from `list_settings`, write through `set_setting` — never touch `SettingsPort` directly from the screen |
| Throbber palette | toad → rainbow `Gradient` | Off-palette for cam | Accent→track sweep from `Palette` |
| Title blink trigger | toad → persistent attention flag | Our analog event is an action finishing | Blink ~3s only when `not app_focus` |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Discoverability | `tui/dashboard.py` BINDINGS (half `show=False`), no help surface | toad `app.py` F1 + groups/tooltips/`key_display`, widget `HELP` | absent |
| Busy indication | text status only (`tui/app.py` `refresh_status`) | toad `widgets/throbber.py` | absent |
| Terminal title | none | toad `app.py` `update_terminal_title` | absent |
| Menu accelerators | none (arrows+Enter only) | toad `widgets/menu.py` `on_key` | absent |
| Selection hygiene | all chrome selectable | toad `ALLOW_SELECT=False` on chrome | absent |
| Command palette | `ENABLE_COMMAND_PALETTE = False` (`tui/app.py`) | toad `screens/main.py` `ModeProvider` | absent (pre-decided ON) |
| Settings editing | CLI only (`cam config`) | toad `screens/settings.py`, ai-usagebar `settings.rs` | absent |
| Responsive width | bars adapt arithmetically | toad `HORIZONTAL_BREAKPOINTS` | present and partial |
| Bar rendering | per-cell `Text.append` (`tui/widgets.py` `bar_cells`) | toad `visuals/columns.py` + `throbber.py` | present and partial |
| Loading widget | stock `LoadingIndicator` | toad `get_loading_widget` | absent |
| Persistent status | watch title only (`tui/account_list.py`) | claude-swap same; toad `Flash` (different semantic) | partial — dashboard/auto lack it |

## Deviations

- **No `Flash` widget** — persistent status extends into each screen's existing title Static instead; `Flash` semantics are already covered by `notify()`.
- **No overlay `Menu`** — nested-stack ListView stays; only the `key` idiom is ported.
- **No `run_on_exit`** — 0/3 references do an outcome recap; invention not justified.
- **No settings search box** — toad's `filter_settings` serves a ~100-key schema; ours is 5 keys.
- **No `lazy.Reveal`** — no mount cost to defer (toad wraps a giant schema).
- **No row-level settings reset** — `unset_setting` stays CLI-only in this screen's v1.
- **`Signal`, `getters.app`, `ItemGrid`, fuzzy match** — same rejections as SL-012 (see commit history).
- **Threshold tick wires live** — a `autoswitch.threshold` write updates `app.threshold_pct` (removing the "not wired yet" comment in `tui/app.py`); other auto knobs are `cam auto`-time reads.

## Open decisions

None — the three R1 open questions are settled in Trade-offs above.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | — (reads `settings.domain.settings_spec` types only) |
| application (ports / use cases) | `tui/app.py` `TuiUseCases` += `list_settings`, `set_setting` |
| infrastructure | — |
| cli / tui | `tui/app.py`, `tui/dashboard.py`, `tui/account_list.py`, `tui/autoview.py`, `tui/widgets.py`, `tui/modals.py`, `tui/cam.tcss`, new `tui/throbber.py`, `tui/settings_screen.py`, `tui/palette.py`, `tui/visuals.py` |
| tests | `test/unit/tui/test_*.py` per feature; `test/support/` unchanged |

## Tasks

One TDD unit each, one conventional commit each.

- [x] T1 — F1 help panel + binding metadata: `f1`→`toggle_help_panel`, `BINDING_GROUP_TITLE`, `Binding.Group`s, `tooltip=`/`key_display=`, `HELP` markdown on screens + `AccountsPanel`
- [x] T2 — menu key accelerators: `MenuItem.key`, `on_key` jump+activate, digits on per-account submenu rows, keys shown on rows
- [x] T3 — `ALLOW_SELECT=False` on chrome (menu rows, title Statics, mode badge, modal labels); cards stay selectable
- [x] T4 — busy throbber: `tui/throbber.py` (`ThrobberVisual` cached `Segment` sweep, `auto_refresh=1/15`), mounted per screen, `-busy` class on `app.busy`
- [x] T5 — terminal title + blink: `update_terminal_title` via driver write, screen `title`s, ~3s blink on action completion when `not app_focus`
- [x] T6 — settings screen read path: `tui/settings_screen.py` `SettingsScreen(ModalScreen)` generated from `EffectiveSetting`s — `Input`+`Number`/`Select` seeded under `prevent(Changed)`, Esc dismiss, menu + palette entry
- [ ] T7 — settings write path: `CamApp.settings_rows()`/`apply_setting()`, protocol += `list_settings`/`set_setting`, invalid → notify+revert, `autoswitch.threshold` → `app.threshold_pct` live
- [ ] T8 — command palette: drop `ENABLE_COMMAND_PALETTE=False`, `tui/palette.py` `CamCommandsProvider` (nav/action hits + per-account switch hits)
- [ ] T9 — `HORIZONTAL_BREAKPOINTS` `[(0,"-narrow"),(100,"-wide")]` + `-narrow` CSS; minis collapse in `AccountsPanel.render`
- [ ] T10 — `Visual`/`Strip` renderer: `tui/visuals.py` (`UsageBarVisual`, `AccountCardVisual`, `MiniAccountVisual` via `Content`/`Strip.from_lines` + `LRUCache`); `render()` returns Visuals
- [ ] T11 — `get_loading_widget` branded indicator

## Out of scope

- Rich human CLI output, `--version`, `cam doctor`, bare-`cam`→TUI — M13 (evidence: `docs/research/toad-ux.md` CLI patterns section).
- `Signal` pub/sub, `MODES` nav, `ItemGrid`, fuzzy matching — rejected in R1, not re-litigated here.
- Settings reset-to-default in the TUI, settings search — see Deviations.
- Live `cam auto` engine hot-reload of settings — the engine reads `settings.json` per process start; the TUI writes the file.
