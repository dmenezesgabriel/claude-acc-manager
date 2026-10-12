# SL-027 — TUI action-runner split

Milestone: M26 · State: open · Depends on: — · Closes: AUD-001, AUD-017 (`maintainer/research/architecture-audit.md`)

> PRD for the executing session: never guess, never assume. Every `research_repos/` path below was verified with `test -e` in the writing session.

## Outcome

`src/claude_acc_manager/tui/app.py` drops under the 500-line ceiling: the single-flight mutating-action lane (`do_switch`/`action_switch_best`/`do_toggle_enabled`/`confirm_remove`/`do_remove` + `_run_action`/`_action_blocking`/`_action_done` machinery) moves to an `ActionRunner` collaborator, and the ~50 private-member test accesses in `test/unit/tui/` become observable-state assertions or ride blessed public seams.

## Exit gate

`uv run pre-commit run --all-files` clean · `wc -l src/claude_acc_manager/tui/app.py` < 500 · `grep -rn "app\._" test/unit/tui/` returns zero hits · `uv run pytest test/unit/tui -n auto` green. Numbers go in the closing commit body.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | FULL | `research_repos/claude-swap/src/claude_swap/tui/app.py`, `research_repos/claude-swap/src/claude_swap/tui/data.py` | `_start_action` busy-gate → `self.run_worker(partial(...), thread=True, group="action", name=label)` → `call_from_thread(self._action_done)`; confirm modal via `push_screen(screen, callback)` — no worker |
| ai-usagebar | ABSENT | — | waybar widget in Rust; no Textual, no action lane |
| toad | PARTIAL | `research_repos/toad/src/toad/app.py` | `@work` methods on `ToadApp` directly (862-line app, no file ceiling, no busy-gate/single-flight lane) |
| claude-code itself | — | n/a | not a Textual app; nothing to interoperate with here |

**Count:** 2 of 3 references have the lane; **none** extracts a collaborator — the split itself is ours, justified by this repo's 500-line file ceiling (AGENTS.md / ADR-0010), which no reference shares. What we *port* is the mechanism: claude-swap's `run_worker(partial(...), name=label)` and `push_screen(screen, callback)` are the exact idioms a non-`DOMNode` collaborator must use (`textual/_work_decorator.py` asserts `isinstance(self, DOMNode)` — `@work` cannot live on a plain class).

## Implementation inventory

### claude-swap

| Concern | Files |
| --- | --- |
| Action lane (busy gate, worker spawn, completion) | `research_repos/claude-swap/src/claude_swap/tui/app.py` — `_start_action`/`_action_blocking`/`_action_done` |
| `do_*` entry points (switch/best/toggle/remove) | same file — `do_switch`, `action_switch_best`, `do_toggle_disabled` |
| Confirm modal (callback style, no worker) | same file — `confirm_remove`/`_on_remove_confirm`; modal itself `research_repos/claude-swap/src/claude_swap/tui/modals.py` |
| Captured-action result type | `research_repos/claude-swap/src/claude_swap/tui/data.py` — `ActionResult`, `run_action` |
| Snapshot lane (generation guard, status note) | `tui/app.py` — `_tick`/`_refresh_blocking`/`_apply_snapshot`/`_update_refresh_status` (same shape as ours; stays on our app) |

### toad

| Concern | Files |
| --- | --- |
| App-level actions | `research_repos/toad/src/toad/app.py` — `@work`-decorated `action_*`/event methods on `ToadApp`; terminal-title blink (`update_terminal_title`, `watch_terminal_title_blink`, `terminal_alert`) |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| Worker spawn from a non-DOMNode collaborator | claude-swap → `app.run_worker(partial(...))`; toad → `@work` on the App | `@work` is impossible off `DOMNode`; `run_worker` is public and restores per-call identity | `app.run_worker(partial(self._blocking, ...), thread=True, group="action", name=label, exit_on_error=False)` — `name` carries the label (claude-swap parity; our `@work` migration had demoted it to auto-built description) |
| Confirm-modal plumbing | claude-swap → `push_screen(screen, callback)`; ours → `@work` + `push_screen_wait` | callback removes the `group="modal"` worker lane and the await-indirection; our `ConfirmModal` docstring already documents callback style | adopt `push_screen(screen, partial(self._on_remove_answer, name))` |
| Where the boundary Protocol lives | (none — our constraint) | `tui/ports.py` matches the component `ports.py` convention and drops a TYPE_CHECKING cycle | move `TuiUseCases` to `src/claude_acc_manager/tui/ports.py` (needed anyway for the 500 ceiling: the action block alone leaves app.py ~515) |
| Runner ↔ app typing | protocol `ActionHost` vs concrete `CamApp` | a ~9-member protocol is ceremony; every screen already annotates `app: CamApp` | `app: CamApp` under `TYPE_CHECKING` — `palette.py` already does this back-import |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Busy gate + lane | `tui/app.py` `_run_action` | claude-swap `_start_action` | complete logic, wrong home — moves to `ActionRunner._start` |
| Thread worker | `tui/app.py` `_action_blocking` (`@work`) | claude-swap `run_worker(partial)` | present but `@work` cannot move off the App — becomes `app.run_worker(partial(...))` |
| Completion callback | `tui/app.py` `_action_done` | claude-swap `_action_done` | complete — moves; calls `app.blink_terminal_title()` (blessed public rename) |
| `do_*` entries | `tui/app.py` | claude-swap `do_*` | complete — moves as `switch`/`switch_best`/`toggle_enabled`/`remove` on `app.actions` |
| Remove confirm | `tui/app.py` `confirm_remove` (`@work` async + `push_screen_wait`) | claude-swap `push_screen(screen, callback)` | present, heavier mechanism — adopt callback, drop modal worker |
| Use-case surface | `tui/app.py` `TuiUseCases` | — (invention boundary) | complete — relocates to `tui/ports.py` |
| Test seam health | `test/unit/tui/` ~50 `app._*` accesses | — | partial — reworked to observable state or the three blessed seams |

## Deviations

- Method names lose the `do_` prefix on the runner (`app.actions.switch(...)`) — the prefix existed only to disambiguate from `action_*` dispatch on the App.
- `action_switch_best` remains a thin delegate on `CamApp`: the `app.switch_best` binding (`account_list.py`) resolves `action_*` on the App object only.
- Worker identity moves from auto-built `description` back to `name=label` (claude-swap); the `run_worker`-spy tests re-assert the exact kwarg dict.

## Open decisions

None — the audit named the seam, claude-swap named the mechanism, the ceiling names the second file (`tui/ports.py`).

## Surface

| Layer | Files |
| ----- | ----- |
| cli / tui | `src/claude_acc_manager/tui/action_runner.py` (NEW ~190) · `src/claude_acc_manager/tui/ports.py` (NEW ~75) · `src/claude_acc_manager/tui/app.py` (689 → ~435) · `account_list.py`, `dashboard.py`, `palette.py`, `tui/__init__.py` (call-site/imports) · `pyproject.toml` (contract comment path) |
| tests | `test/unit/tui/test_app.py`, `test_terminal_title.py`, `test_watch.py`, `test_switch.py`, `test_palette.py` · `test/support/tui_app.py` (`_GatedCollect` gains `entered`) |

## Tasks

One unit per conventional commit, gate green at each.

- [ ] T1 — `refactor(tui)`: bless `update_refresh_status`, `apply_snapshot`, `blink_terminal_title` (public renames, docstrings mark them the worker/Pilot seam); rework every remaining `app._*` access in `test_app.py`, `test_terminal_title.py`, `test_watch.py` — gated-refresh for lane state, `set_interval` spy for blink machinery, `app.workers`/`api.requests`/notify-dedup for poll-lane counters.
- [ ] T2 — `refactor(tui)`: move `TuiUseCases` → `tui/ports.py`; update `app.py`, `tui/__init__.py`, pyproject contract comment.
- [ ] T3 — `refactor(tui)`: extract `ActionRunner`/`ActionToast`/`_switch_toast` → `tui/action_runner.py`; `app.actions` wired in `__init__`; `push_screen` callback modal; repoint `account_list`/`dashboard`/`palette` + all `app.do_*`/`app.confirm_remove`/`app.action_switch_best` test calls; `run_worker`-spy asserts updated to `name=label`.
- [ ] T4 — `docs(maintainer)`: backlog row → shipped, delete this file, exit-gate numbers in commit body.

## Out of scope

- `test/unit/tui/test_app.py` and other >500 test files — M27 (AUD-019/020) owns test-file decomposition; this milestone keeps the rework roughly line-neutral.
- `WatchScreen._selecting` and other non-`CamApp` private reads — not part of AUD-017's blocking cluster.
- The poll loop, theme, settings feed, terminal-title write path — stay on `CamApp` (the app "owns the snapshot poll loop" per its docstring).
