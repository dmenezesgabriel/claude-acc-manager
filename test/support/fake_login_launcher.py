"""LoginLauncherPort fake that records calls instead of running claude."""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import LoginLauncherPort


class FakeLoginLauncher(LoginLauncherPort):
    """Records each launched dir; reports *succeeds* as the login outcome."""

    def __init__(self, *, succeeds: bool = True) -> None:
        """Pin the boolean this launcher returns from ``launch``."""
        self._succeeds = succeeds
        self.launched: list[Path] = []

    def launch(self, account_dir: Path) -> bool:
        """Record *account_dir* and return the pinned outcome."""
        self.launched.append(account_dir)
        return self._succeeds
