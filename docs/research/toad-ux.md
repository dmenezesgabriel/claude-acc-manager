# R1 — toad UX/performance inventory for cam's CLI and TUI

**Ephemeral.** Consumed by M11 (TUI ergonomics refactor), M12 (TUI UX features), M13 (CLI UX). Deleted when M13 ships — durable residue lands as ADRs and code comments, never citations of `research_repos/`.

## Method and limits

- Reference read: `research_repos/toad` v0.6.20 (Python; Will McGugan — the Rich/Textual author's production agent TUI). Every path below was opened this session, not inferred from symbols.
- API availability: `getters`, `lazy.Reveal`, `Signal`, `MODES`, `HORIZONTAL_BREAKPOINTS`, `PAUSE_GC_ON_SCROLL`, `push_screen_wait` were all exercised against our pinned `textual==8.2.8` — every pattern cited runs on the version we ship.
- cam column: read from `src/` at M10-shipped state (2026-10-03). Our TUI is a port of `claude-swap`'s older Textual style; toad is the newer idiom layer on the same pin.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| toad (v0.6.20, Python/textual 8.2.7) | FULL — the pattern source | `src/toad/app.py`, `src/toad/toad.tcss`, `src/toad/widgets/`, `src/toad/screens/`, `src/toad/cli.py` | Modern textual idioms: `getters` descriptors, `@work`/`@on`, `data_bind`, `Signal`, `MODES`, lazy screen factories, `Visual`/`Strip` renderers, schema-generated settings screen |
| claude-swap (v0.27.0b1, Python) | PARTIAL — same older idiom layer we ported | `src/claude_swap/tui/*.py` (mirror of our `tui/`), `src/claude_swap/printer.py`, `src/claude_swap/cli.py` | Manual `query_one`/`run_worker`; hand-rolled ANSI `printer.py` (NO_COLOR/TERM=dumb/TTY detection, dark/light palettes, `--version`) — our terracotta accent is its xterm-173 |
| ai-usagebar (v1.14.0, Rust) | PARTIAL — different surface, same UX goals | `src/tui/settings.rs` (settings overlay), `src/display.rs` | Waybar module + ratatui settings overlay; widget always exits 0; sanitizes untrusted text at the sink |

## UX principles → toad evidence → cam today

One row per heuristic; the "cam today" column names the file that owns the equivalent (or names the gap).

| Principle | toad evidence | cam today | Verdict |
| --- | --- | --- | --- |
| Visibility of system status | `widgets/throbber.py` (animated `Visual`/`Strip` busy bar, `-busy` class), `widgets/flash.py` (inline status messages), `app.py` `update_terminal_title` (`\033]0;title\007` + blink on attention) | `tui/app.py` `refresh_status` reactive rendered in watch title only; toasts for actions | PARTIAL — no busy indicator, no terminal title, status line exists on one screen |
| Match system to real world | `friendly_time_ago`, `CondensedPath`, severity-colored pills | `format_duration`, `reset_clock`, severity ramp in `theme.py` | COMPLETE |
| User control & freedom | Esc dismisses popup/menu/screen; blur-dismiss on `Menu`/`DirectoryDisplay` | Esc pops screens; armed-then-pop on watch (`account_list.py`) | COMPLETE |
| Consistency & standards | `j`/`k` + arrows everywhere; `check_action` gates cursor keys post-selection (`widgets/question.py`) | same conventions; `check_action` already used on watch | COMPLETE |
| Error prevention | `Question` locks options once selected; permissions screen explicit allow/reject | `ConfirmModal` explicit-yes; armed selection on watch | COMPLETE |
| Recognition over recall | F1 `HelpPanel` + `BINDING_GROUP_TITLE`/`Binding.Group`/`tooltip=`/`key_display=`; footer shows significant keys; menu rows carry single-key accelerators (`widgets/menu.py` `on_key`) | half the bindings `show=False`; no help panel; no tooltips; menu is arrows+enter only | ABSENT |
| Flexibility & efficiency | digit quick-launch (`1-9 a-f`), command palette `Provider` (`screens/main.py` `ModeProvider`), fuzzy match (`fuzzy.py` + `textual.cache.LRUCache`) | top-level `s`/`w`/`g`/`b`/`f` bindings exist; palette deliberately disabled (`ENABLE_COMMAND_PALETTE = False`) | PARTIAL — palette off was a pre-toad choice, now pre-decided ON |
| Aesthetic & minimalist | `ALLOW_SELECT = False` on chrome labels (`widgets/menu.py`, `question.py`), transparent Footer styling (`toad.tcss`), toast severity borders | chrome selectable; footer default; toasts default | PARTIAL |
| Help users recover | error toasts with title + severity; `notify` on worker failure | same (`on_worker_state_changed` → notify) | COMPLETE |
| Help & documentation | F1 HelpPanel renders each widget's `HELP` markdown + grouped bindings | nothing | ABSENT |
| Responsiveness (perf) | `@work(thread=True)` everywhere; `gc.freeze()` on mount (`screens/main.py`); `PAUSE_GC_ON_SCROLL`; `lazy.Reveal` mounts off-screen content on demand | thread workers single-flight; no GC tuning; all children mounted eagerly | PARTIAL |
| Render efficiency | `Visual`/`Strip` + `lru_cache`/`LRUCache` (`widgets/throbber.py`, `option_content.py`, `visuals/columns.py`) | `bar_cells` builds `Text` cell-by-cell per render (`tui/widgets.py`) | PARTIAL — works, measurable waste |

## Pattern inventory (toad files to open, by concern)

### App architecture — `research_repos/toad/src/toad/app.py`

- `SCREENS = {"settings": get_settings_screen, …}` + `MODES = {"store": get_store_screen}` — lazy screen factories keep module imports (and mount cost) deferred.
- `Signal(self, "settings_changed")` / `session_update_signal` — app-owned pub/sub; widgets `subscribe` in `on_mount` instead of reaching into each other (`widgets/session_tabs.py` shows the consumer side).
- `inherit_bindings=False`, `BINDING_GROUP_TITLE`, `Binding(..., tooltip=…, key_display=…)`, `Binding.Group` — help-surface metadata.
- `HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]` — width-responsive classes.
- `PAUSE_GC_ON_SCROLL = True` + `gc.freeze()` in `screens/main.py` `on_mount` — GC pause control for scroll-heavy UIs.
- `update_terminal_title` — writes `\033]0;{icon} {title}\007`; `terminal_title_flash` var drives a 0.5s blink timer (attention signal for unfocused terminals).
- `action_help_quit` — ctrl+c double-press-to-quit: first press notifies "again to quit", second within 5s exits.
- `run_on_exit` — called by `cli.py` after `app.run()`; prints a rich `Panel` post-TUI (upgrade nag in toad; for cam: a switch recap line at most).
- `ansi_theme_dark = DRACULA_TERMINAL_THEME` — sets the palette ANSI-colored child output renders against.

### Ergonomics idioms — the M11 refactor set

| Idiom | toad citation | Replaces in cam |
| --- | --- | --- |
| `getters.query_one("#id", Type)` class-level descriptor | `screens/main.py`, `screens/settings.py`, `screens/store.py`, `screens/sessions.py`, `widgets/conversation.py` | `self.query_one(...)` calls + their `# pragma: no mutate` comments in `tui/app.py`, `dashboard.py`, `account_list.py`, `autoview.py`, `widgets.py` |
| `getters.app(AppClass)` — typed `self.app` (accepts class or callable; asserts isinstance) | `screens/sessions.py`, `widgets/session_tabs.py`, `screens/store.py` | `app: CamApp` + `TYPE_CHECKING` import — NOT adopted (see Deviations in SL-012: cycle cost > benefit) |
| `@work(thread=True, exit_on_error=False)` method decorator | `app.py` (`system_notify`, `set_process_title`, `launch_agent`), `screens/action_modal.py` | `run_worker(partial(m, args), thread=True, group=, name=)` in `tui/app.py` `_tick`/`_run_action`, `tui/autoview.py` `_kick_decision` |
| `@on(Msg, "selector")` stacked handler decorators | `app.py` (all `@on(messages.…)`), `screens/settings.py` (`@on(Input.Blurred, "Input")` + `@on(Input.Submitted, "Input")`), `screens/store.py` (`@on(events.Click, "CondensedPath")`) | conventional `on_*` methods in all screens |
| `data_bind(attr=OwnerClass.reactive)` | `screens/main.py`, `screens/store.py`, `widgets/question.py`, `session_tabs.py` usage | manual `self.watch(self.app, "snapshot", cb)` in `dashboard.py`, `account_list.py`, `autoview.py`, `widgets.py` |
| `AUTO_FOCUS = "selector"` | `screens/main.py`, `screens/permissions.py`, `screens/settings.py` | `query_one(...).focus()` in `dashboard.py`/`account_list.py` `on_mount` |
| `push_screen_wait(screen)` returning the dismiss value | `app.py` `action_settings`/`action_sessions` | `push_screen(ConfirmModal(...), partial(cb, name))` in `tui/app.py` |
| `self.prevent(Msg)` / `with widget.prevent(Msg)` | `screens/settings.py` (yield-time), `widgets/slash_complete.py` (`with self.input.prevent(...)`) | nothing today — needed once programmatic writes fire events (M12 settings screen) |
| `query_one_optional`, `call_after_refresh`, `set_class`, `focus_chain` property | `widgets/session_tabs.py`, `screens/sessions.py`, `app.py` | scattered equivalents |
| `reactive(x, toggle_class="-cls")`, `var(toggle_class=…)` | `app.py` `show_sessions`, `widgets/question.py` `selected`, `screens/store.py` `edit` | `_set_selecting` class flips in `account_list.py` (partial — method does more than the class flip) |
| `check_action` to disable bindings conditionally | `widgets/question.py`, `screens/settings.py` | already used on `WatchScreen` |

### UX affordances — the M12 feature set

| Feature | toad citation | Notes |
| --- | --- | --- |
| F1 `HelpPanel` (built-in) + binding groups/tooltips/`key_display` | `app.py` BINDINGS; `screens/main.py`, `screens/store.py`, `screens/sessions.py` `BINDING_GROUP_TITLE`; `LauncherGridSelect.HELP` markdown convention | Footer shows significant keys; F1 shows all — the discoverability pair |
| Busy throbber | `widgets/throbber.py` (`ThrobberVisual(Visual)` — `lru_cache`'d `make_segments`, `auto_refresh = 1/15`, `-busy` class in `toad.tcss`) | Gradient is toad-specific; a severity-tinted or primary bar matches our palette |
| Flash status line | `widgets/flash.py` (severity classes, self-hiding timer) | Alternative/complement to toasts — decide at M12 whether refresh_status becomes a Flash-style widget or stays in the watch title |
| Terminal title + blink | `app.py` `update_terminal_title`/`terminal_title_flash`/`watch_terminal_title` | `cam — watching 3 accounts`; blink on switch completion is the analog of toad's input-requested flash |
| Menu key accelerators | `widgets/menu.py` `on_key` (each `MenuItem.key` jumps+activates), `menus.py` `MenuItem(description, action, key)` | Our nested ListView menu can bind keys directly, or adopt the overlay `Menu` (`overlay: screen`, `position: absolute`, `constrain: inside inside`) |
| `ALLOW_SELECT = False` | `widgets/menu.py` `NonSelectableLabel`/`MenuOption`, `question.py`, `session_tabs.py` | Stops text-selection dragging over chrome labels — our `MenuItem`/menu `Static`s today |
| `HORIZONTAL_BREAKPOINTS` classes | `app.py` + `-narrow`/`-wide` CSS | Narrow terms: collapse minis or shrink bars (bars already adapt; breakpoint hides the mini rows) |
| Command palette `Provider` + `Hit`/`DiscoveryHit`/`matcher` | `screens/main.py` `ModeProvider` + `COMMANDS = {ModeProvider}` | PRE-DECIDED ON: re-enable `ENABLE_COMMAND_PALETTE`, add a cam-command provider (switch/watch/auto/refresh/theme/settings) |
| Schema-generated settings screen | `screens/settings.py` (compose→widget per `Setting.type`: Input/Select/Checkbox/TextArea + `Number` validators + `prevent(Changed)`; `filter_settings` search via `display`), `settings.py` `Schema`/`Settings` | PRE-DECIDED: generate ours from `settings_spec.SETTING_SPECS` (float→Input+Number validators, choice→Select); toad's `set_all` replay ≈ our `list_settings` effective rows |
| `get_loading_widget` | `screens/main.py` (quotes/`FutureText`), `screens/action_modal.py` (`LoadingIndicator`) | Our first paint is a `loading…` Static — a branded or plain indicator is nicer |
| `DataTable` + `RowHighlighted`→enable-button | `screens/session_resume_modal.py` | Pattern reference for any future tabular surface; no consumer today |
| `focus_chain` property | `screens/sessions.py` | Declarative tab order — cheap polish |
| `run_on_exit` rich print | `app.py` + `cli.py` call site | Optional: one-line recap after `cam tui` exits (e.g. `switched to 'work'`); decide at M12 |

### CLI patterns — the M13 set

| Pattern | toad citation | Notes |
| --- | --- | --- |
| Default subcommand (`DefaultCommandGroup.parse_args` inserts `run`) | `cli.py` | PRE-DECIDED: bare `cam` → `cam tui` (dashboard). Non-TTY/`TERM=dumb` must fall back to usage — textual can't drive a headless terminal; flag the edge in the M13 PRD |
| `about`/`doctor` report — markdown template + env/version/paths table printed via rich | `about.py` + `cli.py` `about`/`settings` commands | PRE-DECIDED `cam doctor`: claude version + band check, secure-store/config paths, lock presence, env vars, terminal caps, package versions |
| `--version` | `cli.py` `-v/--version` | claude-swap also has it (`action="version"`); `importlib.metadata.version` or a `__version__` |
| `run_on_exit` rich `Panel` | `app.py` + `cli.py` | As above |
| rich `Console`/`print` for human output | `cli.py` (`from rich import print` farewell), `about.py`, `app.py` `run_on_exit` | rich is a declared dep (`pyproject.toml`, README): zero new supply chain. `Console` handles `NO_COLOR`/non-TTY/`TERM=dumb` natively; severity colors reuse `theme.py` constants; `--json` stdout path stays plain `json.dumps` |
| claude-swap `printer.py` | `src/claude_swap/printer.py` | Alternative: hand-rolled ANSI + `colors_enabled()` detection. Weaker (no wrap/ellipsis/markup-safety) but zero-dep-ish. Rejected — rich is already installed and the ADR-0002 spirit is supply-chain, which does not grow |

### Performance patterns

| Pattern | toad citation | Application |
| --- | --- | --- |
| `gc.freeze()` + `PAUSE_GC_ON_SCROLL` | `app.py`, `screens/main.py` `on_mount` | M11 — class var + one call in `on_mount`; invisible behaviorally |
| `Visual`/`Strip` renderers + `lru_cache`/`LRUCache` | `widgets/throbber.py` (`make_segments` cached), `option_content.py`, `visuals/columns.py` (`_render_cache`) | M12 — rewrite `bar_cells`/`usage_bar`/`account_card_text` as `Visual`s producing cached `Strip`s instead of per-cell `Text.append` |
| `lazy.Reveal` deferred mounting | `screens/settings.py` (wraps the settings container) | M12 — only where mount cost exists (settings screen; account list is small) |
| `auto_refresh` pacing for animated widgets | `widgets/throbber.py` (`1/15`) | M12 throbber |
| `asyncio.to_thread` for blocking writes | `app.py` `save_settings` | Already equivalent (thread workers) |
| `textual-speedups` optional C ext | `pyproject.toml` | NOT adopted — new native dep fights ADR-0002's supply-chain driver for unmeasurable gain here |

## Decisions taken (user, 2026-10-03)

| Decision | Settled as |
| --- | --- |
| Bare `cam` with no subcommand | Launches the TUI dashboard (`cam tui` semantics); non-TTY/`TERM=dumb` falls back to current usage+exit-2 — lands M13 |
| Command palette | Re-enabled with a `Provider` for cam commands — lands M12 |
| TUI settings screen | Generated from `SETTING_SPECS` — lands M12 |
| `cam doctor` | New read-only diagnostics command — lands M13 |

## Gap analysis

| Concern | Ours today (file) | Best reference (file) | Gap |
| --- | --- | --- | --- |
| Widget queries | `self.query_one(...)` + `pragma: no mutate` ×~15 (`tui/*.py`) | `screens/settings.py` `getters.query_one` | present and partial — M11 |
| Worker plumbing | `run_worker(partial(...))` + `call_from_thread` (`tui/app.py`, `autoview.py`) | `app.py` `@work(thread=True)` | present and partial — M11 |
| Message handlers | `on_*` conventional methods | `@on(Msg, selector)` stacked | present and partial — M11 |
| Reactive propagation | `self.watch(app, attr, cb)` per child | `data_bind` at compose | present and partial — M11 |
| Initial focus | imperative `focus()` in `on_mount` | `AUTO_FOCUS` | present and partial — M11 |
| Modal result | callback via `push_screen(..., cb)` | `push_screen_wait` | present and partial — M11 |
| Event suppression | none (not yet needed) | `prevent(Msg)` | absent — needed by M12 settings screen |
| Busy indication | text status on watch screen | `Throbber` `Visual` + `-busy` class | absent — M12 |
| Discoverability | footer hints only | HelpPanel + binding metadata + key accelerators | absent — M12 |
| Terminal integration | none | title escape + blink | absent — M12 |
| Text-selection hygiene | selectable chrome | `ALLOW_SELECT = False` | absent — M12 |
| Responsive width | bars adapt arithmetically | `HORIZONTAL_BREAKPOINTS` classes | present and partial — M12 |
| Bar rendering | per-cell `Text.append` | `Visual`/`Strip` + caches | present and partial — M12 |
| Human CLI output | plain `print()` | rich `Console` | absent — M13 |
| Version flag | none | `--version` | absent — M13 |
| Diagnostics | none | `toad about` template | absent — M13 (`cam doctor`) |
| Default command | bare → usage exit 2 | `DefaultCommandGroup` | absent — M13 |

## Not adopted, with reasons

| Pattern | Why not |
| --- | --- |
| `MODES` / `get_mode` nav | Stacked `push_screen` nav fits cam's three screens + modal; modes swap full screens, which would orphan the dashboard-first UX |
| `Signal` pub/sub | `watch()` on app reactives already delivers snapshot/theme to children; a second event channel duplicates one pipeline — adopt only if a producer can't be a reactive |
| `getters.app(AppClass)` | Requires screens to import `CamApp` eagerly → `app.py` must stop importing screens (lazy factories) to break the cycle; `app: CamApp` + `TYPE_CHECKING` annotations already give strict typing at zero cost |
| `ItemGrid`/`GridSelect`, fuzzy match | Account counts are small (a ListView of ≤ a dozen cards); grid nav and fuzzy search solve a density problem we don't have |
| `textual_serve` web mode, `ansi/` terminal emulation, ACP/agent machinery, telemetry/PostHog, setproctitle, shell integration | Out of domain — toad is an agent host, cam is an account manager |
| Hand-rolled ANSI `printer.py` (claude-swap) | rich is already a runtime dep and strictly more capable |

## Open decisions for M12/M13 PRDs

| Question | Candidate answers | Evidence |
| --- | --- | --- |
| Refresh-status surface: keep in watch title, or a `Flash`-style status line on all screens? | (a) keep title slot; (b) one status widget under the panel | `widgets/flash.py` vs our `refresh_status` reactive |
| `run_on_exit` recap after `cam tui` | print a one-line outcome summary or exit silent | `app.py` + `cli.py` |
| Menu accelerators: bind keys on the nested ListView, or adopt the overlay `Menu` widget? | (a) keys on existing stack; (b) `Menu` overlay popup | `widgets/menu.py` `overlay: screen` + `on_key` vs `dashboard.py` `_menu_stack` |
| `cam doctor` surface | which checks gate the exit code (band fail → nonzero?) | `about.py` report shape; ADR-0015 probe seam |
