# SL-012 — TUI speaks current textual idioms

Milestone: M11 · State: open · Depends on: M10 shipped · Closes: —

## Outcome

A maintainer reading `src/claude_acc_manager/tui/` sees the same idioms textual 8.x teaches — `getters` descriptors, `@work`/`@on` decorators, `data_bind`, `AUTO_FOCUS`, `push_screen_wait` — instead of the pre-modern style ported from claude-swap, and M12's UX features land on that plumbing without a second refactor. **Zero user-visible change is the requirement, not a side effect.**

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. `cam tui` — walk dashboard → watch → back → switch → back → auto view → theme toggle → quit; every screen renders and navigates identically to M10.
2. `cam watch` — `s` arms selection, `Esc` disarms then exits, armed row flashes, cursor keys gated while armed.
3. `cam tui` → remove an account → `n` cancels, `y` + Enter confirms; toast fires once.
4. `TERM=dumb cam tui` still launches (textual handles it); `cam tui` under a 60-col terminal does not crash.
5. `git diff` on `test/` contains only spy/seam moves justified in task commit bodies — no assertion weakened, no test deleted.

The behavioral contract is the existing Pilot suite: it stays green. Spies coupled to `run_worker` internals (`test/unit/tui/test_app.py` ×2, `test/unit/tui/test_auto.py` ×1) may move to the equivalent seam only if `@work` stops routing through the instance attribute — it routes through `self.run_worker` on our pin (verified 2026-10-03), so even those should not move.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| toad | FULL | `src/toad/app.py`, `src/toad/screens/*.py`, `src/toad/widgets/*.py` | `getters.app`/`query_one` descriptors, `@work(thread=True)`, `@on(Msg, selector)`, `data_bind`, `AUTO_FOCUS`, `prevent()`, `push_screen_wait`, `check_action`, `focus_chain` |
| claude-swap | ABSENT | `src/claude_swap/tui/*.py` | The exact older style our `tui/` ports — manual `query_one`, `run_worker(partial(...))`, `push_screen(..., callback)` |
| ai-usagebar | ABSENT | `src/tui/settings.rs` | ratatui, different paradigm — no equivalent plumbing to compare |
| claude-code itself | — | n/a | Vendor interop surface, not a textual codebase |

**Count:** 1 of the references implements this. That is enough — the one that does is the framework author's own production app on our exact textual pin (8.2.x), which makes it the canonical demonstration, not a stylistic outlier.

## Implementation inventory

For **every** repo marked FULL or PARTIAL above, the files an implementer must actually open — not a summary of them. Group by concern. Where two repos disagree, that disagreement **is** the decision the milestone has to make, and it is named.

### toad (`research_repos/toad/` — verified on disk 2026-10-03)

| Concern | Files |
| --- | --- |
| App-level idiom usage (`@work`, `@on`, `data_bind`, reactives) | `src/toad/app.py` |
| `getters.app`/`getters.query_one` descriptors | `src/toad/screens/sessions.py`, `src/toad/screens/main.py`, `src/toad/screens/store.py`, `src/toad/widgets/session_tabs.py` |
| `@on` with selectors; `prevent()`; `AUTO_FOCUS` | `src/toad/screens/settings.py` (all three), `src/toad/screens/main.py`, `src/toad/screens/permissions.py` (`AUTO_FOCUS`) |
| `push_screen_wait` result flow | `src/toad/app.py` `action_settings`, `action_sessions` |
| `check_action` conditional bindings | `src/toad/widgets/question.py` (already in our `account_list.py`) |
| `focus_chain`, `query_one_optional`, `set_class` | `src/toad/screens/sessions.py`, `src/toad/widgets/session_tabs.py` |
| GC/scroll flags (`PAUSE_GC_ON_SCROLL`, `gc.freeze()`) | `src/toad/app.py`, `src/toad/screens/main.py` `on_mount` |

### claude-swap (`research_repos/claude-swap/` — the style we are moving away from)

| Concern | Files |
| --- | --- |
| Older idiom baseline | `src/claude_swap/tui/app.py`, `src/claude_swap/tui/dashboard.py` (AccountListScreen/SwitchScreen/WatchScreen — we split them into `account_list.py` during the port), `src/claude_swap/tui/autoview.py`, `src/claude_swap/tui/widgets.py`, `src/claude_swap/tui/modals.py`, `src/claude_swap/tui/data.py`, `src/claude_swap/tui/theme.py` |

## Trade-offs and what we adopt

One row per real decision. "Options seen" must come from the inventory above, not from imagination.

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Widget queries | toad → `getters.query_one` descriptors; claude-swap → `self.query_one` at call site | Descriptor is declared once at class level, typed, and cannot drift from the selector; call-site form needs `# pragma: no mutate` to survive mutmut | `getters.query_one` — deletes ~15 pragma'd lines, gains a typed attribute |
| Worker plumbing | toad → `@work(thread=True)` methods; claude-swap → `run_worker(partial(m, args), thread=True)` | Decorator names the worker at the method (`name`/`group`/`thread`/`exit_on_error` kwargs); partial form scatters it at the call site | `@work` — routes through `self.run_worker` on our pin, so Pilot spies keep intercepting; keep `# pragma: no mutate` on decorator kwargs (`thread=True` is a real-behavior mutant) |
| Message handlers | toad → `@on(Msg, "selector")`; claude-swap → conventional `on_*` names | `@on` scopes to a selector and stacks multiple sources on one handler; conventional names are implicit | `@on` uniformly — one handler style, selector explicit |
| Snapshot/theme propagation | toad → `data_bind(attr=CamApp.reactive)` at compose; claude-swap → `self.watch(app, attr, cb)` in `on_mount` | `data_bind` requires the child to declare the reactive + watcher; `watch()` is one line but implicit | `data_bind` where the child already wants a reactive (`AccountsPanel`, `AccountItem`); keep `watch()` where the callback is orchestration (`_on_snapshot` reconciles rows, not just repaints) |
| Initial focus | toad → `AUTO_FOCUS`; claude-swap → `query_one(...).focus()` in `on_mount` | Class-level declaration vs imperative call | `AUTO_FOCUS` on `DashboardScreen`, `SwitchScreen`; NOT on `WatchScreen` (its focus is armed-state-dependent) |
| Modal result | toad → `push_screen_wait`; claude-swap → `push_screen(..., partial(cb, args))` | `await`-style returns the dismiss value; callback threads state through a partial | `push_screen_wait` for `ConfirmModal` — the `confirm_remove` flow reads top-to-bottom |
| Event suppression | toad → `prevent(Msg)` / `with w.prevent(Msg)`; claude-swap → absent | Only needed where programmatic writes fire handled messages | Adopt opportunistically only where the refactor creates the hazard (e.g. setting `menu.index`); the real consumer is M12's settings screen |
| Pub/sub for app state | toad → `Signal` objects; claude-swap → watch reactives | A second event channel next to the reactive pipeline | NOT adopted — one propagation mechanism; revisit only if a producer can't be a reactive |
| Typed `self.app` in screens | toad → `getters.app(ToadApp)`; claude-swap → `app: CamApp` + `TYPE_CHECKING` | `getters.app` needs screens to import `CamApp` eagerly → forces lazy screen imports in `app.py` to break the cycle | NOT adopted — the `TYPE_CHECKING` annotation already gives strict typing; the cycle surgery buys a runtime `assert isinstance` we don't need |
| Focus order | toad → `focus_chain` property; claude-swap → absent | Declarative tab order for multi-widget screens | Adopt where a screen's tab order is non-obvious (auto screen); skip single-focusable screens |

## Gap analysis — what we already have vs the references

Read our own code first. A capability that half-exists is worse than one that does not, and this is where that gets caught.

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Widget queries | `query_one` + `pragma: no mutate` ×~15 in `tui/app.py`, `tui/dashboard.py`, `tui/account_list.py`, `tui/autoview.py`, `tui/widgets.py` | `research_repos/toad/src/toad/screens/settings.py` | present and partial |
| Worker plumbing | `run_worker(partial(...))` in `tui/app.py` `_tick` + `_run_action`, `tui/autoview.py` `_kick_decision` | `research_repos/toad/src/toad/app.py` `@work` methods | present and partial |
| Message handlers | `on_*` conventional methods across all screens + `tui/modals.py` | `research_repos/toad/src/toad/screens/settings.py` `@on` stacks | present and partial |
| Reactive propagation | `self.watch(self.app, …)` ×5 (`dashboard.py`, `account_list.py` ×2, `autoview.py` ×2, `widgets.py` ×2) | `research_repos/toad/src/toad/screens/main.py` `data_bind` | present and partial |
| Initial focus | `query_one(...).focus()` in `dashboard.py`, `account_list.py` `on_mount` | `research_repos/toad/src/toad/screens/main.py` `AUTO_FOCUS` | present and partial |
| Modal result | `push_screen(ConfirmModal, partial(_on_remove_confirm, name))` in `tui/app.py` | `research_repos/toad/src/toad/app.py` `push_screen_wait` | present and partial |
| Event suppression | none | `research_repos/toad/src/toad/screens/settings.py` `prevent` | absent — opportunistic only |
| GC/scroll tuning | none | `research_repos/toad/src/toad/app.py`, `screens/main.py` | absent — M11 (class var + one call) |
| `check_action` | present on `WatchScreen` | `research_repos/toad/src/toad/widgets/question.py` | complete |
| Single-flight + generation guards | `_refreshing`, `_refresh_generation` in `tui/app.py` | n/a (toad's traffic model differs) | complete — preserve exactly |

## Deviations

Anything we will not port as-is, and why. A deviation that outlives the milestone becomes an ADR; the rest is stated in a code comment at the point it applies.

- `getters.app` skipped: adopting it forces lazy screen imports in `tui/app.py` to break an `app ↔ screens` import cycle; the `TYPE_CHECKING` + `app: CamApp` annotations already deliver strict typing. If a future screen needs the runtime `assert isinstance`, revisit then.
- `Signal` skipped: `watch()`/`data_bind` over `CamApp.snapshot`/`refresh_status`/`theme` is the single propagation pipeline; a parallel pub/sub channel is a second thing to reason about with no consumer today.
- `MODES`/lazy screen factories skipped: stacked `push_screen` nav fits three screens + one modal; factories exist to defer import cost we don't pay measurably.
- `_refreshing`/`_refresh_generation`/`_action_lock` guards stay verbatim: they are semantics (skip-tick, drop-stale, single-flight), not plumbing — `@work`'s `exclusive` flag is a different guarantee (cancel-in-flight) and must not replace them.
- `on_worker_state_changed` stays: it is the error surface for `exit_on_error=False` workers; `@work` does not remove it.
- `# pragma: no mutate` comments die only with the lines they annotate; equivalent ones go on `@work(thread=True)`/`@work(exit_on_error=False)` and any remaining behavior-bearing literal.

## Open decisions

None for this milestone — it is mechanical parity with the reference. The product-level questions (help panel, palette provider, settings screen, menu accelerators, Flash-vs-title status) are M12's and live in `docs/research/toad-ux.md`.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | — |
| application (ports / use cases) | — |
| infrastructure | — |
| cli / tui | `src/claude_acc_manager/tui/app.py`, `tui/dashboard.py`, `tui/account_list.py`, `tui/autoview.py`, `tui/widgets.py`, `tui/modals.py` |
| tests | `test/unit/tui/test_app.py`, `test/unit/tui/test_auto.py`, `test/unit/tui/test_switch.py`, `test/unit/tui/test_watch.py`, `test/unit/tui/test_dashboard.py`, `test/unit/tui/test_modals.py`, `test/support/tui_app.py` — expected unmodified; spy moves only if `@work` stops routing through `app.run_worker` (it does route through it on textual 8.2.8) |

## Tasks

One TDD unit each, one conventional commit each. Small enough that a unit takes well under an hour; if it does not, decompose further.

Every task is refactor-shaped: the Pilot suite is the spec and must stay green without touching assertions. "RED" here means a failing state only if the suite catches a mistake — not a new test.

- [ ] T1 — `getters.query_one` descriptors across `dashboard.py`, `account_list.py`, `autoview.py`, `widgets.py` (and `app.py` if any survive there); drop the `pragma: no mutate` comments that annotated those lines
- [ ] T2 — `@on(Msg, selector)` for all `on_*` message handlers (ListView.Selected, Button.Pressed incl. `tui/modals.py`); `AUTO_FOCUS` on `DashboardScreen`/`SwitchScreen`; `focus_chain` where a screen has >1 focusable
- [ ] T3 — `@work(thread=True, exit_on_error=False, name=…, group=…)` for `_refresh_blocking`, `_action_blocking`, `_decide_blocking`; keep `_refreshing`/`_refresh_generation`/action-lock guards and `call_from_thread` returns verbatim; pragma on decorator kwargs
- [ ] T4 — `push_screen_wait` for `ConfirmModal` (`confirm_remove` becomes async/@work); `data_bind` on `AccountsPanel`/`AccountItem` where it deletes a `watch()`; `prevent()` only where the refactor introduces an event hazard
- [ ] T5 — `PAUSE_GC_ON_SCROLL = True` + `gc.freeze()` in `CamApp.on_mount` (one-line comment naming why: scroll-heavy screen churn); sweep leftover `# pragma: no mutate` that no longer annotate a live line

## Out of scope

What this milestone deliberately does not do, and which milestone or deferred row owns it.

- Any new widget, binding, help surface, throbber, terminal title, breakpoint CSS, settings screen, palette provider, `Visual`/`Strip` renderer — all M12 (SL-013 at pickup).
- CLI output, `--version`, `cam doctor`, bare-`cam` behavior — all M13.
- `getters.app`, `Signal`, `MODES`, lazy screen factories — rejected above, not deferred.
- Changes to `cli/`, `shared/`, `settings/`, `switch/`, `watch/` components — the refactor stays inside `tui/`.
