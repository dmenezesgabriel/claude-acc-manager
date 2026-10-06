<!--
Thanks for the contribution. The checklist below is what review would
otherwise ask for — see CONTRIBUTING.md for the reasoning behind each.
-->

## What this changes



## Checklist

- [ ] `uv run pre-commit run --all-files` is green — the same gate the commit hooks run (ruff, pyright strict, deptry, bandit, vulture, xenon, import-linter, pytest ≥95% branch, mutmut)
- [ ] Commit messages are conventional — `type(scope): imperative`
- [ ] Bug fixes include a test that fails on `main` and passes here — say so below
- [ ] Tests are hermetic — no real `$HOME`/`$XDG`, no network; `-m integration` is opt-in only
- [ ] Docs updated where they mention what changed (`README.md`, `docs/`)

## Testing

<!-- What you ran, and on which distribution. -->
