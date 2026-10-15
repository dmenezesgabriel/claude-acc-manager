"""Export the docs TUI shots to committed SVGs for the README.

The site renders ``cam`` fences inline at build time
(``textual._doc.format_svg``, see mkdocs.yml); a README rendered on
github.com or PyPI cannot run that fence, so it needs real files under
``docs/assets/``. Run from the repo root:

    uv run python maintainer/docs-shots/export_svg.py

Same fake-backed sources as the docs build, so the output is deterministic.
"""

from pathlib import Path

from textual._doc import take_svg_screenshot

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "assets"
SOURCE = ROOT / "maintainer" / "docs-shots" / "dashboard.py"

SHOTS: tuple[tuple[str, tuple[str, ...], tuple[int, int]], ...] = (
    ("tui-dashboard.svg", (), (100, 34)),
    ("tui-auto-preview.svg", ("g",), (100, 34)),
)


def main() -> None:
    """Render each shot in ``SHOTS`` to ``docs/assets/``.

    Example: ``uv run python maintainer/docs-shots/export_svg.py`` regenerates
    every file after a TUI change.
    """
    OUT_DIR.mkdir(exist_ok=True)
    for name, press, size in SHOTS:
        svg = take_svg_screenshot(
            None,
            str(SOURCE),
            press,
            terminal_size=size,
            wait_for_animation=False,
            simplify=False,
        )
        assert svg is not None
        target = OUT_DIR / name
        # Match the commit hooks (trailing-whitespace, end-of-file-fixer) so a
        # regeneration never produces diff noise the hooks would strip anyway.
        normalized = "\n".join(line.rstrip() for line in svg.splitlines()) + "\n"
        target.write_text(normalized)
        print(f"{target.relative_to(ROOT)}: {len(svg) / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
