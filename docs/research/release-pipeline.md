# M15 evidence — semantic release → PyPI pipeline

Ephemeral research for the M15 PRD. Delete when M15 ships. Sources fetched
2026-04; workflow shapes below are quoted from official docs and reference
repositories pinned at commit SHAs.

## Official sources consulted

| Source | URL |
| --- | --- |
| PyPA publishing guide | https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/ |
| PyPI Trusted Publishers | https://docs.pypi.org/trusted-publishers/ |
| gh-action-pypi-publish README | https://github.com/pypa/gh-action-pypi-publish (`release/v1`) |
| python-semantic-release docs | https://python-semantic-release.readthedocs.io/en/latest/ (v10.7.0) — GH Actions page + uv integration guide |
| actions/attest | https://github.com/actions/attest (attest-build-provenance v4+ is a thin wrapper; new impls should use `actions/attest`) |
| Reference: attrs | `python-attrs/attrs/.github/workflows/pypi-package.yml` + `zizmor.yml` + `codeql-analysis.yml` |
| Reference: ai-usagebar | `research_repos/ai-usagebar/.github/workflows/release.yml` (tag-driven, verify-version gate) |

## The canonical workflow shape (PSR's own published example)

python-semantic-release ships official actions and a reference workflow —
verified against v10.7.0 docs:

```yaml
on:
  push:
    branches: [main]

permissions:          # least privilege by default
  contents: read

jobs:
  release:
    runs-on: ubuntu-latest
    concurrency:
      group: ${{ github.workflow }}-release-${{ github.ref_name }}
      cancel-in-progress: false        # never cancel a release mid-flight
    permissions:
      contents: write                  # push release commit + tag + GH release
      id-token: write                  # PSR's own OIDC needs
    steps:
      - uses: actions/checkout@<sha>
        with: { ref: ${{ github.ref_name }} }
      - run: git reset --hard ${{ github.sha }}   # never release unevaluated commits
      - uses: python-semantic-release/python-semantic-release@<sha>   # v10.7.0
        id: release
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
      - uses: python-semantic-release/publish-action@<sha>            # v10.7.0
        if: steps.release.outputs.released == 'true'
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          tag: ${{ steps.release.outputs.tag }}
      - uses: actions/upload-artifact@<sha>
        with: { name: dist, path: dist, if-no-files-found: error }
    outputs:
      released: ${{ steps.release.outputs.released || 'false' }}

  deploy:
    needs: release
    if: needs.release.outputs.released == 'true'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write                  # OIDC lives ONLY here
    environment: pypi
    steps:
      - uses: actions/download-artifact@<sha>
        with: { name: dist, path: dist }
      - uses: pypa/gh-action-pypi-publish@<sha>
        with: { packages-dir: dist, print-hash: true }
```

Key semantics:

- **`git reset --hard ${{ github.sha }}` after checkout** — main may have
  moved between trigger and run; PSR must version exactly what CI evaluated.
- **`concurrency` with `cancel-in-progress: false`** — serializes releases,
  prevents tag races on rapid main pushes.
- **Separate `deploy` job** — `id-token: write` is scoped to the job that
  publishes; build/release jobs never see an OIDC-capable token. Retrying a
  failed publish doesn't re-run the release.
- **`steps.release.outputs.released`** — when no conventional commit
  warrants a bump, PSR exits cleanly and downstream jobs are skipped via
  `if:`.
- **`python-semantic-release/publish-action`** — attaches `dist/*` as GitHub
  Release assets (separate action so the release exists even if PyPI fails).

## PSR configuration surface (confirm exact keys at PRD)

- `version_toml = ["pyproject.toml:project.version"]` — bumps the static
  version field; `__version__` follows automatically via
  `importlib.metadata` (no code change needed).
- `tag_format = "v{version}"` — matches existing `v1.0.0` tag.
- `commit_parser` defaults parse conventional commits; this repo's
  `conventional-pre-commit` hook already enforces the input format.
- **`no_operation_mode: true` input → `--noop`**: dry-run mode for
  validating the pipeline without side effects (M15 validation step).
- `root_options` input was **removed in v10.0.0 for a command-injection
  vulnerability** — pin v10.x SHA, never pass root options.
- PSR action runs in a Docker image — uv is NOT inside it (see below).

## The `uv.lock` trap — documented by PSR's uv integration guide

PSR bumps `pyproject.toml` version → `uv.lock` records the project version →
lock goes stale → next `uv run`/`uv lock --check` fails. Official fix
(PSR docs, "UV Project Setup"):

```toml
[project.optional-dependencies]
build = ["uv ~= 0.7"]        # pin uv INSIDE the project so the PSR
                             # Docker action can pip-install it and
                             # Dependabot keeps the pin fresh

[tool.semantic_release]
build_command = """
  python -m pip install -e '.[build]'
  uv lock --upgrade-package "$PACKAGE_NAME"
  git add uv.lock
  uv build
"""
```

`uv lock --upgrade-package "$PACKAGE_NAME"` relocks ONLY our own package's
version — it does not touch dependency pins. `git add uv.lock` inside
`build_command` lets PSR commit the relocked file in the release commit.

## Trusted publishing — the no-token PyPI path

- PyPI-side one-time setup (user action, outside CI): add a "pending
  publisher" or configure publisher on the project — repo, workflow
  filename, environment name must match exactly.
- OIDC flow: GitHub mints a short-lived token → `gh-action-pypi-publish`
  exchanges it for a **15-minute project-scoped PyPI token** — no stored
  credential to leak.
- **Do NOT run `gh-action-pypi-publish` inside a reusable workflow**
  (explicit upstream warning — OIDC claims break).
- Publish on GitHub-provided `ubuntu-latest` runners only.
- **Attestations are ON BY DEFAULT** under trusted publishing (PEP 740
  sigstore attestations uploaded with the dists); attrs sets
  `attestations: true` explicitly.
- TestPyPI: same action with
  `repository-url: https://test.pypi.org/legacy/` + a separate PyPI-side
  trusted publisher on TestPyPI.

## Environment protection (PyPA guide recommendation)

- GitHub **environment `pypi`** on the publish job; PyPA guide recommends
  **required reviewers** on it so every real publish needs a human click.
- attrs uses `environment: release-pypi` / `release-test-pypi` — per-target
  environments let TestPyPI auto-publish on main while PyPI stays gated.

## Community conventions worth adopting

From `attrs` (`pypi-package.yml`):

- Build job once, upload artifact; TestPyPI job on `push` to main
  (`environment: release-test-pypi`); PyPI job on `release: published`
  (`environment: release-pypi`) — i.e. **GitHub Release creation is the PyPI
  trigger**, which composes cleanly with PSR's `publish-action`.
- `github.repository_owner` guards on publish jobs — fork runs can never
  reach publishing (defense in depth alongside missing secrets).
- `attestations: write` + `id-token: write` on the *build* job for
  `actions/attest` (GitHub artifact attestations — separate from the PyPI
  PEP 740 attestations the publish action adds).

From `ai-usagebar` (`release.yml`):

- **verify-version job first**: tag must be `vX.Y.Z`, annotated, point at a
  commit on main; every version surface must agree; CHANGELOG must contain
  `## [X.Y.Z]`. With PSR the surfaces are derived, but a post-PSR assertion
  (`pyproject version == tag`, `uv.lock` version == tag) is cheap defense —
  consider a small verify step.
- **Idempotent publish**: "already exists" → warn + exit 0 (matters for
  re-runs of a half-failed pipeline).
- Secret-presence gating: check `secrets.X` non-empty before use, warn+skip
  rather than fail — keeps forks green.

## Open decision points for the M15 PRD

1. **Branch protection on main**: if main is protected,
   `GITHUB_TOKEN` cannot push PSR's release commit/tag — PSR docs say use a
   PAT secret; the modern alternative is a **repository ruleset bypass for
   the GitHub Actions app / a dedicated bot identity**. Rulesets are
   readable by the default token (Scorecard docs) and avoid a long-lived
   PAT. PRD must pick: (a) no protection + `GITHUB_TOKEN` (simplest,
   current state), (b) ruleset + Actions bypass, (c) PAT secret.
2. **PyPI trigger model**: PSR-on-push (release commit + tag + GH release +
   publish in one pipeline) vs attrs-style `release: published` trigger
   (PSR creates release; separate workflow publishes). Both are official;
   PSR-on-push matches PSR's own example and keeps one workflow.
3. **Required reviewer on `pypi` environment** — recommended by PyPA for
   production publish; decide whether TestPyPI stays ungated (attrs model:
   TestPyPI auto on main, PyPI gated).
4. **`actions/attest` for GitHub artifact attestations** on dists —
   additive provenance beyond PEP 740; attrs does it on the build job.
5. Whether PSR config lives in `pyproject.toml` `[tool.semantic_release]`
   (conventional) — yes; and `build` optional-dep group for uv-in-action.
6. First-release bootstrap: current version is `1.0.0` with manual tag
   `v1.0.0` — PSR reads existing tags, so history is consistent.
