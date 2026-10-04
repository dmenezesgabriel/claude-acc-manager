"""The shared modal screens — today just ``ConfirmModal``.

A ``ModalScreen[bool]`` answering a destructive question: ``y`` / the
action button dismiss ``True``; ``n``, Esc, or the Cancel button dismiss
``False``. The button labels adapt to the destructive verb ("Remove").
"""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from claude_acc_manager.tui.modals import ConfirmModal


class _ModalApp(App[None]):
    """Bare host — a modal needs only somewhere to stack."""

    def compose(self) -> ComposeResult:
        yield Static("host")


def _push(app: _ModalApp, modal: ConfirmModal) -> list[bool | None]:
    """Stack *modal* and capture whatever it dismisses with."""
    answers: list[bool | None] = []
    app.push_screen(modal, answers.append)
    return answers


class TestConfirmModal:
    async def test_compose_renders_the_question_and_choices(self) -> None:
        # arrange
        app = _ModalApp()

        async with app.run_test() as pilot:
            # act
            _push(
                app,
                ConfirmModal("Drop account 'work'?", title="Remove account", yes_label="Remove"),
            )
            await pilot.pause()

            # assert
            modal = app.screen
            assert isinstance(modal, ConfirmModal)
            modal.query_one(".modal-box", Vertical)  # styled container exists
            modal.query_one(".modal-buttons", Horizontal)
            assert str(modal.query_one(".modal-title", Static).content) == "Remove account"
            assert str(modal.query_one(".modal-body", Static).content) == ("Drop account 'work'?")
            assert str(modal.query_one("#yes", Button).label) == "Remove"
            assert str(modal.query_one("#no", Button).label) == "Cancel"
            assert "y remove" in str(modal.query_one(".modal-hint", Static).content)

    async def test_bare_kwargs_use_the_plain_defaults(self) -> None:
        # arrange / act
        app = _ModalApp()
        async with app.run_test() as pilot:
            _push(app, ConfirmModal("sure?"))
            await pilot.pause()

            # assert
            modal = app.screen
            assert str(modal.query_one(".modal-title", Static).content) == "Confirm"
            assert str(modal.query_one("#yes", Button).label) == "Yes"
            assert "y yes" in str(modal.query_one(".modal-hint", Static).content)

    async def test_y_confirms(self) -> None:
        app = _ModalApp()
        async with app.run_test() as pilot:
            answers = _push(app, ConfirmModal("sure?"))
            await pilot.press("y")
            assert answers == [True]

    async def test_n_and_escape_cancel(self) -> None:
        app = _ModalApp()
        async with app.run_test() as pilot:
            answers = _push(app, ConfirmModal("sure?"))
            await pilot.press("n")
            assert answers == [False]
            answers = _push(app, ConfirmModal("sure?"))
            await pilot.press("escape")
            assert answers == [False]

    async def test_the_buttons_answer_too(self) -> None:
        app = _ModalApp()
        async with app.run_test() as pilot:
            answers = _push(app, ConfirmModal("sure?", yes_label="Remove"))
            await pilot.pause()
            app.screen.query_one("#yes", Button).press()
            await pilot.pause()
            assert answers == [True]
            answers = _push(app, ConfirmModal("sure?"))
            await pilot.pause()
            app.screen.query_one("#no", Button).press()
            await pilot.pause()
            assert answers == [False]
