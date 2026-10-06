# SL-018 — User docs site on GitHub Pages: mkdocs.yml, Diátaxis pages, gated deploy

Milestone: M17 · State: open · Depends on: M15 shipped (`docs/` is pure site), M16 shipped (workflow conventions) · Closes: —

## Outcome

A user can browse complete `cam` documentation — install, guides, CLI/settings/env reference, architecture and ADRs — as a MkDocs Material site that every pull request proves builds under `--strict`, deployed to GitHub Pages from `main` the moment the repo goes public.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. `uv run --group docs mkdocs build --strict` exits 0 locally and the `docs` CI job is green on the push.
2. `uv run --group docs mkdocs serve` — click through every nav entry; no 404s, search index covers the pages.
3. Post-flip (maintainer enables Pages source = GitHub Actions, flips visibility): the `deploy` job goes green on the next `main` push and the site serves at `https://dmenezesgabriel.github.io/claude-acc-manager/`.
4. `maintainer/` never enters the build — `grep -ri maintainer site/` on the built output finds nothing.
5. While private: `docs` job green, `deploy` job reports skipped (not failed) on a `main` push.

Write this PRD to be grepped: do not hard-wrap paragraphs, keep one fact per table row, write file names in full, and tag every gap it closes with its `GAP-NNN`.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap (v0.27.0b1, Python) | ABSENT | `research_repos/claude-swap/README.md` (388 lines) | single-file README carries all user docs — Installation → Usage → Tips → How it works → Data locations; no `docs/`, no SSG |
| ai-usagebar (v1.14.0, Rust) | PARTIAL — user docs, no site | `research_repos/ai-usagebar/docs/` (5 flat `.md` files), `research_repos/ai-usagebar/README.md` (~40 inline links into `docs/`) | hub-and-spoke: README links `docs/{claude-accounts,configuration,format-placeholders,openrouter-accounts,vendor-endpoints}.md`; no SSG, no deploy — `Makefile` has no docs target |
| toad (v0.6.20, Python) | ABSENT | `research_repos/toad/README.md` (337 lines), `research_repos/toad/CONTRIBUTING.md` | README-only; `notes.md` is a scratch dev log, not user docs |
| claude-code itself (vendor behavior we must interoperate with) | — | closed-source vendor; user docs hosted off-repo at code.claude.com/docs | not an interop surface — nothing to mirror |

**Count:** 0 of 3 references ship a docs site; 1 ships flat user docs. A built site is an invention relative to the references — justified by the maintainer ordering that made M17 a milestone and by the community convention verified in `maintainer/research/docs-site.md` (uv, ruff, textual, httpx, fastapi all run MkDocs Material on `docs/`).

## Implementation inventory

For **every** repo marked FULL or PARTIAL above, the files an implementer must actually open — not a summary of them. Group by concern. Where two repos disagree, that disagreement **is** the decision the milestone has to make, and it is named.

### ai-usagebar

| Concern | Files |
| --- | --- |
| Page inventory (what users need) | `research_repos/ai-usagebar/docs/claude-accounts.md` (account setup guide), `research_repos/ai-usagebar/docs/configuration.md` (key-by-key reference), `research_repos/ai-usagebar/docs/format-placeholders.md` (template reference), `research_repos/ai-usagebar/docs/openrouter-accounts.md`, `research_repos/ai-usagebar/docs/vendor-endpoints.md` |
| Entry/hub pattern | `research_repos/ai-usagebar/README.md` — deep-links `docs/*.md` throughout; the README is the index, `docs/` is the annex |

### claude-swap

| Concern | Files |
| --- | --- |
| Single-file user docs | `research_repos/claude-swap/README.md` — Installation → Usage (per-command walkthroughs) → Tips → How it works → Data locations |

### Community convention (external, verified 2026-10-06 — not `research_repos/`)

| Concern | Source |
| --- | --- |
| Nav structure + `Internals` label for design docs | `astral-sh/uv` `mkdocs.yml` — explicit `Title: path` entries per page; `Getting started`/`Guides`/`Concepts`/`Reference` top sections; design docs under an `Internals` label; every nav section leads with an `index.md` landing + `navigation.indexes` |
| Link/omission validation | `astral-sh/uv` `mkdocs.yml` — `validation:` block `omitted_files`/`absolute_links`/`unrecognized_links` (warn → error under `--strict`) |
| Deploy mechanics | `maintainer/research/docs-site.md` — `configure-pages`/`upload-pages-artifact`/`deploy-pages`, `pages: write`+`id-token` on the deploy job only |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Deploy path | `mkdocs gh-deploy` → `gh-pages` branch + `contents: write` vs native Pages actions → artifact, `pages: write`+`id-token` on deploy job only | a write-capable token on every docs build vs generated HTML never entering git | **Native actions** — matches `permissions: {}` posture; no HTML branch (research §Deploy decision) |
| SSG | MkDocs Material vs Zensical (alpha, reads `mkdocs.yml`) vs Sphinx/RTD | Material is in maintenance mode (security fixes ~May 2027) but is the deployed convention; Zensical is 0.x | **Material + plain `mkdocs.yml`** — the config Zensical migrates natively; no plugins beyond `search` |
| Build-strict enforcement | local pre-commit hook vs named CI job vs both | hook preserves "CI can never pass what a commit cannot"; a named job gives the ruleset a check to bind | **Both** (maintainer decision) — hook under `files: ^(docs/\|mkdocs\.yml$)` + `docs` job in `docs.yml` |
| ADR nav | directory auto-listing vs explicit `Title: path` list | dir-listing is less YAML but gives no titles and silently hides `0000-template.md` | **Explicit list** (uv convention) — pairs with `omitted_files` validation so a nav-less page fails `--strict`: a forcing function, not ceremony |
| Durable-docs placement | move `architecture.md`/`adr/` under `docs/internals/` vs label-only nav | the research skeleton showed a move; ~20 relative `adr/NNNN-*.md` links plus root-doc citations (`README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `pyproject.toml` comments) resolve correctly only if nothing moves | **Label-only** — nav `Internals` → `Architecture: architecture.md`, `Decisions: adr/…`; zero repoints |
| Nav section naming | `Internals` / `Explanation` / `Concepts` / two top-levels | user-facing IA convention | **`Internals`** — the label uv uses for design docs (maintainer: follow community convention) |
| Section landing pages | uv → every section has `index.md` + `navigation.indexes` vs expandable nav groups | landing pages need curated prose — filler at 9 pages | **Expandable groups, no index pages** (recorded as deviation; revisit if sections grow) |
| Versioning | `mike` (Material versioning convention) vs none | versioning without released versions is decoration | **Skip `mike`** — adopt when M18 produces real versions |
| README ↔ index.md | duplicate command tables vs single canonical | drift between two "sources of truth" | README keeps the repo-glance pitch; **flag-level detail lives only in the site**; README links the site at close-out |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| User documentation | `README.md` command table only — no user pages | `research_repos/ai-usagebar/docs/*.md`, `research_repos/claude-swap/README.md` Usage walkthroughs | absent — Diátaxis pages to write |
| Site config | none | uv `mkdocs.yml` (external convention) | absent — `mkdocs.yml` at root |
| Docs dependencies | none — `uv.lock` has no mkdocs | — | absent — `docs` dependency-group |
| Build gate | `gate` runs `pre-commit run --all-files` (`.pre-commit-config.yaml`) — no mkdocs hook | — | absent — local hook + `docs` CI job |
| Deploy | none | — | absent — `docs.yml` deploy job, visibility-gated |
| Build-artifact ignore | `.gitignore` lacks `site/` | — | absent — one line |
| Site↔repo links | `README.md` Docs section lists machinery; `pyproject.toml` has no `[project.urls]` | ai-usagebar README→docs deep-links | absent — lands at close-out (site must serve first) |
| Durable docs on site | `docs/architecture.md`, `docs/adr/` exist but unreachable by a browser | uv `Internals` nav label | present, unreachable — nav'd under `Internals` |

## Deviations

- No file moves under `docs/`: the research skeleton nested `architecture.md`/`adr/` under `internals/`, but relative links already resolve and ~20 repo-tree citations would repoint for cosmetics — nav labels carry the structure instead.
- No `section/index.md` landing pages and no `navigation.indexes` — uv's convention needs curated landing prose that is filler at 9 pages; expandable nav groups suffice (revisit if a section outgrows one screen).
- `docs/adr/0000-template.md` is `exclude_docs`d — author machinery living in a durable dir; the repo file stays for ADR authors.
- `deploy` job inert while private (`github.event.repository.visibility == 'public'`, same guard as `codeql`/`scorecard`) — it activates at the flip, no workflow edit needed.
- No `mike`, no `mkdocstrings` API docs (the public surface is the CLI, documented in `reference/cli.md`), no blog/i18n/l10n — minimum site that covers the four Diátaxis quadrants.

## Open decisions

None — deploy path, gate placement, nav naming, and content scope were settled with the maintainer in this session; `mike` deferred until M18 produces versions.

## Surface

| Layer | Files |
| ----- | ----- |
| site config | `mkdocs.yml` (new), `.gitignore` (+`site/`), `pyproject.toml` (`[dependency-groups] docs`, `[project.urls]` at close-out), `uv.lock` |
| site content | `docs/index.md`, `docs/getting-started/{installation,quickstart}.md`, `docs/guides/{switching,auto-switching,scripting,diagnostics}.md`, `docs/reference/{cli,json-output,settings,environment-variables}.md` — all new |
| gate | `.pre-commit-config.yaml` (mkdocs local hook) |
| ci | `.github/workflows/docs.yml` (new — `docs` check job + `deploy` job) |
| repo | `README.md` (Docs repoint, close-out), `maintainer/backlog.md` (M17 row) |

## Tasks

One commit each, gate green every step. Content tasks carry no unit tests — the test is `mkdocs build --strict` green plus a `mkdocs serve` click-through; YAML tasks verify via `actionlint` + `uv run zizmor --persona pedantic .github/` like SL-015/016.

- [ ] T1 — `build(deps): add docs group — mkdocs-material` — `uv add --group docs "mkdocs-material>=9.7,<10"`; verify deptry does not flag the group.
- [ ] T2 — `docs(site): mkdocs.yml + index.md` — plain Material config, `site_url`, `repo_url`, `plugins: [search]`, `exclude_docs: adr/0000-template.md`, `validation:` block, nav covering `index.md`/`architecture.md`/15 ADRs under `Internals`; `.gitignore` += `site/`.
- [ ] T3 — `chore(pre-commit): mkdocs build --strict hook` — local `system` hook `uv run --group docs mkdocs build --strict`, `files: ^(docs/|mkdocs\.yml$)`, `pass_filenames: false`. Must land after T2 — the hook needs the config and the synced group.
Commits run inside-out along the link direction — `--strict` fails on links
to not-yet-existing pages, so reference lands first (self-contained), guides
link backward to it, getting-started links to everything.

- [ ] T4 — `docs(site): reference pages` — `cli.md`, `json-output.md`, `settings.md` (5 `autoswitch.*` keys + bounds), `environment-variables.md` (`CLAUDE_CONFIG_DIR`, `CLAUDE_SECURESTORAGE_CONFIG_DIR`, `CAM_ASSUME_CLAUDE_CONTRACT`, `CAM_DARK`, `CAM_LIGHT`, `NO_COLOR`, `TERM`).
- [ ] T5 — `docs(site): guides pages` — `switching.md`, `auto-switching.md` (knobs → `settings.json`, quarantine, `--once` exit codes), `scripting.md` (`--json` schema-v1), `diagnostics.md` (`cam doctor`, `NO_COLOR`/`TERM=dumb`).
- [ ] T6 — `docs(site): getting-started pages` — `installation.md` (Linux-only, Python ≥3.11, `uv tool install`/`pipx`, claude prerequisite) + `quickstart.md` (`cam add` → `list` → `status` → TUI); nav entries in the same commit.
- [ ] T7 — `ci(github): docs.yml — docs check + gated Pages deploy` — `docs` job (PR+push:main+dispatch; `contents: read`; build `--strict`; on push+public also `configure-pages` + `upload-pages-artifact` `path: site/`); `deploy` job (`needs: docs`, `if:` push+public; `pages: write`+`id-token: write` only; `environment: github-pages`). No path filters — a filtered required check deadlocks untouched PRs. SHA-pin the three `actions/*-pages` actions with `# vX.Y.Z` comments.
- [ ] T8 — `docs(repo): README + pyproject urls` — **post-flip**: site must serve before anything links it. README "Docs" section repoints at the site; `pyproject.toml` `[project.urls] Documentation`.
- [ ] T9 — `docs(backlog): ship M17` — **post-flip**: deploy green, site 200, `maintainer/` absent from artifact; closing commit body records the numbers; M17 row → `shipped`; delete this file and `maintainer/research/docs-site.md`.

## Out of scope

- `mike` versioning — needs released versions; M18 territory.
- `mkdocstrings`/Python API docs — the user surface is the CLI; the internals quadrant is served by `architecture.md` + `adr/`.
- Section `index.md` landing pages, i18n, blog, social cards — embellishments past the milestone's contract.
- The visibility flip and ruleset — maintainer actions shared with M14 T3/T11; this slice only makes the deploy leg activate when they land.
- Any change to `src/` or `test/` — docs milestone, no product code.
