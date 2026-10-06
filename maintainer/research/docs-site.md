# M17 evidence — user docs site on GitHub Pages

Ephemeral research for the M17 PRD (slice SL-018 at pickup). Delete when M17
ships. Sources fetched 2026-04-28; every claim is anchored to an official doc
or a file verified present in a maintained repository.

## The question this milestone answers

`docs/` today holds **development docs** (backlog, slices, research — the
process machinery) and **durable architecture docs** (architecture.md, adr/).
None of it is *user* documentation for `cam` itself. The community convention
is `docs/` = a static site deployed to GitHub Pages. Two scopes must not be
confusable — the session-bootstrap skill will point agents at the machinery
(`maintainer/backlog.md`, `docs/adr/`), and the site must point users only at program
docs.

## Official sources consulted

| Source | URL |
| --- | --- |
| MkDocs configuration | https://www.mkdocs.org/user-guide/configuration/ — `docs_dir` (default `docs`), `nav`, `exclude_docs` (gitignore-style patterns excluded from the built site, MkDocs ≥1.6), `not_in_nav`, `draft_docs`, `strict` validation for nav omissions |
| Material for MkDocs — publishing | https://squidfunk.github.io/mkdocs-material/publishing-your-site/ — documents `mkdocs gh-deploy --force` (build → `gh-pages` branch, needs `contents: write`) |
| GitHub Pages via Actions | `actions/configure-pages` + `actions/upload-pages-artifact` + `actions/deploy-pages` — the starter-workflow pattern when Pages source = "GitHub Actions" |
| Diátaxis | https://diataxis.fr — tutorials / how-to guides / reference / explanation |
| Zensical | https://zensical.org + https://squidfunk.github.io/mkdocs-material/blog/2025/11/05/zensical/ — Material team's successor; alpha today, reads `mkdocs.yml` natively, Material enters maintenance-only until May 2027 |

## Community conventions verified in the wild

| Repo | SSG + config | `docs/` contents | Dev-docs home |
| --- | --- | --- | --- |
| astral-sh/uv | `mkdocs.yml` @ root, Material theme | **site only**: `index.md`, `getting-started/`, `concepts/`, `guides/`, `reference/`, `pip/`, assets | `CONTRIBUTING.md` at root |
| astral-sh/ruff | `mkdocs.yml` + `mkdocs.template.yml` | site | `CONTRIBUTING.md`, `AGENTS.md` at root |
| Textualize/textual | `mkdocs-common/nav/offline/online.yml` | **site only**: `index.md`, `tutorial.md`, `guide/`, `how-to/`, `reference/`, `widgets/`, `blog/`, `FAQ.md` — visibly Diátaxis-shaped | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` at root |
| encode/httpx, fastapi/fastapi | `mkdocs.yml` (httpx); docs + `docs_src/` tested examples (fastapi) | site | root |
| squidfunk/mkdocs-material | `mkdocs.yml` | site **including a `contributing/` nav section** | durable contributor docs inside the site — precedent that dev docs *can* publish |
| pallets/flask, psf/requests | `.readthedocs.yaml` + Sphinx `docs/` | site | older Python convention (Sphinx+RTD) — superseded for new projects by Material+Pages |

## The two-scope resolution — decided: physical split

| Option | Verdict | Why |
| --- | --- | --- |
| **A. One `docs/` dir, `exclude_docs` hides process files from the build** | rejected | Hides process docs from the *site* but not from the repo tree — a GitHub browser still finds `backlog.md`/`slices/`/`research/` mixed into `docs/`, which is exactly the confusion this milestone exists to remove |
| **B. Physical split — `docs/` pure site, `maintainer/` holds machinery** | **chosen** | Boundary is physical, not config-dependent: `docs/` = user docs + durable design docs (`architecture.md`, `adr/`); `maintainer/` = `backlog.md` + `slices/` + `research/` — tracked, never published, clearly labelled "for maintaining this project". Rule that falls out: **durability == publishability** — everything in `docs/` is publishable by construction, nothing ephemeral ever touches the site config. Move lands in M15 (docs-standardization owns the tree); M17 builds the site on the clean `docs/` |
| C. Site in a subdir (`site/`, `website/`) | rejected | Inverts the convention every surveyed project follows; `docs/` is where everyone looks |

Post-split layout:

```
docs/                        # published site root (docs_dir)
  index.md                   # site home — what cam is, install, links
  getting-started/           # Diátaxis: tutorials
  guides/                    # Diátaxis: how-to
  reference/                 # Diátaxis: reference
  internals/                 # Diátaxis: explanation — architecture.md + adr/
    architecture.md
    adr/…
maintainer/                  # process machinery — tracked, never in the site
  backlog.md                 # milestone ledger — the skill's routing table
  slices/  (+ _TEMPLATE.md)  # ephemeral PRDs
  research/                  # ephemeral evidence docs
```

Every reference repoint is M15's job (it owns the move): AGENTS.md docs map,
the backlog's own "Finding things" greps, `slices/_TEMPLATE.md`, ADR-0001's
lifetime-taxonomy text, SL-015, the `next-task` skill (`.agents/skills/`),
`.gitignore` comments — `grep -rn "docs/backlog\|docs/slices\|docs/research"`.

## Site tool decision

- **Material for MkDocs** — the deployed convention: uv, ruff, textual,
  httpx, fastapi all build on it; ~84k public repos depend on it.
- **Zensical** — same team's successor, currently 0.0.x alpha, natively reads
  `mkdocs.yml`. Choosing Material + a plain `mkdocs.yml` keeps a documented
  migration path open without betting on alpha software. Do not pick
  Sphinx/RTD — that is the legacy convention, not the current one.

## Deploy decision

| Path | Mechanics | Permissions |
| --- | --- | --- |
| `mkdocs gh-deploy` | pushes built HTML to a `gh-pages` branch; Pages source = "deploy from branch" | job needs `contents: write` — a write-capable token on every docs build |
| Native Pages actions (recommended) | `configure-pages` → `mkdocs build` → `upload-pages-artifact` → `deploy-pages`; Pages source = "GitHub Actions" | `pages: write` + `id-token: write` on the deploy job only; no `contents: write`, no generated-HTML branch — matches this repo's `permissions: {}` posture |

**Visibility gate:** GitHub Pages on a free plan requires a public repo.
The site source, `mkdocs.yml`, and the `build --strict` CI job can all land
before the flip; the deploy job verifies after it — same pattern as
codeql/scorecard's `visibility == 'public'` guard if M16 wants the guard.

## Content skeleton (Diátaxis)

| Quadrant | Candidate pages |
| --- | --- |
| Tutorial (getting started) | install via pipx/uv, `cam add`, first `cam` TUI session |
| How-to guides | switch strategies, `auto` loop + quarantine, `--json` scripting, `doctor`, config keys |
| Reference | CLI command-by-command, `--json` schema (schema-v1), `settings.json` keys, env vars (`CLAUDE_CONFIG_DIR`, `CAM_*`), exit codes |
| Explanation | `architecture.md`, `adr/` index, concepts: headroom, anti-flap, last-good cache, contract gate |

## Wiring and validation

- `mkdocs-material` (+ plugins) as a uv `docs` dependency-group → locked in
  `uv.lock`, covered by dependabot — consistent with the hash-pinning posture.
- `exclude_docs` is **not needed** under the physical split — `docs/` contains
  only publishable files, so `mkdocs build --strict` can run unfiltered.
- `docs.yml` workflow (lands inside M16's file-per-concern layout):
  `mkdocs build --strict` on PRs, deploy job on `main` pushes only.
- `pyproject.toml` `[project.urls]` `Documentation` after the site is live.
- `README.md` "Docs" section points at the site.
- Versioning: `mike` is the Material versioning convention — decide at PRD;
  likely skip until M18 produces real versions.

## Decisions deferred to the M17 PRD

1. Nav naming for the durable-docs section (`internals/` vs `architecture/` +
   `decisions/` as separate nav sections) — check what textual/uv call theirs.
2. Deploy path: native Pages actions (recommended) vs `gh-deploy`.
3. Landing-page content split between `README.md` and `docs/index.md` —
   they must not duplicate and drift (uv's `index.md` is a site homepage,
   not a README copy).
4. `mike` versioning: adopt now or defer.
5. `mkdocs build --strict` as a required check once M16's ruleset exists —
   gate docs PRs the same way as code.
