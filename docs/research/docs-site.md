# M17 evidence — user docs site on GitHub Pages

Ephemeral research for the M17 PRD (slice SL-018 at pickup). Delete when M17
ships. Sources fetched 2026-04-28; every claim is anchored to an official doc
or a file verified present in a maintained repository.

## The question this milestone answers

`docs/` today holds **development docs** (backlog, slices, research — the
process machinery) and **durable architecture docs** (architecture.md, adr/).
None of it is *user* documentation for `cam` itself. The community convention
is `docs/` = a static site deployed to GitHub Pages. Two scopes, one
directory — how do maintained projects hold both?

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

## The two-scope resolution

| Option | How | Cost |
| --- | --- | --- |
| **A. One `docs/` dir, exclusion from the build** (recommended) | `docs/` becomes the site root; new user docs land beside the process docs; `exclude_docs` keeps `backlog.md`, `slices/**`, `research/**` out of the built site while they stay tracked and greppable at stable paths; `architecture.md` + `adr/` go **in** the nav under an Explanation/Architecture section — they are durable and publishable (mkdocs-material ships its contributing docs the same way) | Zero path churn — every `grep -n … docs/backlog.md` in AGENTS.md/backlog/prompt keeps working; process docs remain one `git add` away but can never reach the public site |
| B. Move process docs out of `docs/` | e.g. top-level `dev/` or `ops/`; `docs/` becomes pure site | Absolute boundary, but rewrites every `docs/backlog.md`/`docs/slices/` reference across AGENTS.md, prompt-execution, backlog greps, the slice template, and git history conventions — and the lifetime taxonomy (ADR-0001) gains a third home |
| C. Separate site dir (`site/`/`website/`) | `docs_dir` override | Inverts the convention every surveyed project follows; nobody looks for a site in `website/` in a Python repo |

Option A also survives `mkdocs serve` ergonomics via `exclude_docs` semantics
(excluded = as good as nonexistent during build), and `not_in_nav` exists if
some files should build but stay unlisted.

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
- `docs.yml` workflow (lands inside M16's file-per-concern layout):
  `mkdocs build --strict` on PRs, deploy job on `main` pushes only.
- `pyproject.toml` `[project.urls]` `Documentation` after the site is live.
- `README.md` "Docs" section points at the site.
- Versioning: `mike` is the Material versioning convention — decide at PRD;
  likely skip until M18 produces real versions.

## Decisions deferred to the M17 PRD

1. Option A vs B for the two-scope `docs/` (recommendation: A).
2. Exact `exclude_docs`/`not_in_nav` patterns — verify `strict` build is
   quiet with process files present.
3. Deploy path: native Pages actions (recommended) vs `gh-deploy`.
4. Which durable dev docs publish (architecture + adr almost certainly;
   backlog never — it's process state).
5. `mike` versioning: adopt now or defer.
