"""The command palette provider (slice T8).

``CamCommandsProvider`` serves two kinds of hits: the static nav/action
commands (switch list, watch, auto, settings, refresh, theme, quit) and a
``switch to '<name>'`` hit per switchable snapshot account. The palette
itself is Textual's; these tests drive the provider plus one end-to-end
open.
"""

from __future__ import annotations

from pathlib import Path

from support.tui_app import settle_workers, wired_app
from textual.command import CommandPalette, Hit

from claude_acc_manager.tui.palette import CamCommandsProvider

EXPECTED_COMMANDS = {
    "switch account…": "Pick an account to switch the live login to.",
    "watch accounts": "Open the hands-off account monitor.",
    "auto-switch view": "Preview the auto-switch engine's pick.",
    "settings…": "Edit settings.json without leaving the TUI.",
    "refresh usage": "Ask for a usage pass now.",
    "toggle theme": "Flip between the dark and light theme.",
    "quit": "Leave the TUI.",
}


async def _hits(app, query: str) -> list[Hit]:
    """Every scored hit a provider yields for *query*."""
    provider = CamCommandsProvider(app.screen)
    return [hit async for hit in provider.search(query)]


async def _hit_texts(app, query: str) -> list[str]:
    return [str(hit.text) for hit in await _hits(app, query)]


async def _discover_texts(app) -> list[str]:
    provider = CamCommandsProvider(app.screen)
    return [str(hit.text) async for hit in provider.discover() if hit.text]


class TestPaletteOpens:
    async def test_ctrl_space_opens_the_command_palette(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("ctrl+space")
            await pilot.pause()
            assert CommandPalette.is_open(app)

    async def test_the_palette_is_enabled_on_the_app(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        assert app.ENABLE_COMMAND_PALETTE
        assert "ctrl+space" in app.COMMAND_PALETTE_BINDING


class TestStaticCommands:
    async def test_navigation_commands_are_searchable(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            texts = await _hit_texts(app, "switch")
            assert "switch account…" in texts

    async def test_every_root_action_has_a_hit(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            found = await _discover_texts(app)
        for expected in EXPECTED_COMMANDS:
            assert expected in found

    async def test_every_command_carries_help_and_a_callable(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            provider = CamCommandsProvider(app.screen)
            async for hit in provider.discover():
                assert callable(hit.command), hit.text
                assert hit.help
                expected = EXPECTED_COMMANDS.get(str(hit.text))
                if expected is not None:
                    assert hit.help == expected

    async def test_scored_hits_carry_score_and_help(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            hits = await _hits(app, "sw")
            assert hits, "a fuzzy 'sw' query must match commands"
            for hit in hits:
                assert hit.score > 0
                assert hit.help

    async def test_an_unmatched_query_yields_nothing(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert await _hit_texts(app, "zzzqqq") == []


class TestSwitchHits:
    async def test_each_switchable_account_gets_a_hit(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path, active_name="personal")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            hits = await _hits(app, "switch")
            work = next(h for h in hits if h.text == "switch to 'work'")
            assert work.help == "Switch the live login to 'work'."
            assert callable(work.command)

    async def test_non_switchable_rows_have_no_hit(self, tmp_path: Path) -> None:
        app, _, store, _ = wired_app(
            tmp_path, names=("work", "personal", "off"), active_name="personal"
        )
        from claude_acc_manager.accounts.domain.value_objects import AccountName

        store.set_enabled(AccountName("off"), False)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            found = await _hit_texts(app, "switch")
            # active self-switch and disabled rows are not offered
            assert "switch to 'work'" in found
            assert "switch to 'personal'" not in found
            assert "switch to 'off'" not in found

    async def test_no_snapshot_means_no_account_hits(self, tmp_path: Path) -> None:
        import threading

        gate = threading.Event()
        app, *_ = wired_app(tmp_path, collect_gate=gate)
        async with app.run_test() as pilot:
            await pilot.pause()
            found = await _hit_texts(app, "switch")
            gate.set()
            assert "switch to 'work'" not in found
            assert "switch account…" in found

    async def test_choosing_a_hit_switches(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path, active_name="personal")
        calls: list[str] = []
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.do_switch = calls.append  # type: ignore[method-assign]
            provider = CamCommandsProvider(app.screen)
            async for hit in provider.search("switch to 'work'"):
                if hit.text == "switch to 'work'":
                    hit.command()
            assert calls == ["work"]

    async def test_choosing_a_nav_hit_pushes_the_screen(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            provider = CamCommandsProvider(app.screen)
            async for hit in provider.search("watch accounts"):
                if hit.text == "watch accounts":
                    hit.command()
            await pilot.pause()
            from claude_acc_manager.tui.account_list import WatchScreen

            assert isinstance(app.screen, WatchScreen)
