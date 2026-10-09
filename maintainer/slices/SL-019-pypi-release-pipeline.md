# SL-019 — releases cut themselves: a conventional commit on main ships to PyPI

Milestone: M18 · State: open · Depends on: SL-018 (M17 — repo public, CI proven) · Closes: —

> Copy this file to start a milestone. Delete it when the milestone ships.
>
> A PRD exists so the executing agent **never guesses and never assumes**. If a decision can be settled by opening a reference file, this document says which file. Every path is verified on disk in the session that writes the PRD — line ranges rot, so cite paths, and add a line range only where a file is large and the range was checked today.

## Outcome

One sentence: the maintainer cuts a release with one local command — python-semantic-release bumps the version, relocks `uv.lock`, and writes `CHANGELOG.md` into a release commit that rides a normal PR (the nine checks run on it) — and pushing the `v{version}` tag publishes the dists automatically: GitHub Release with assets, ungated TestPyPI canary, and a reviewer-gated PyPI publish via OIDC trusted publishing, with no stored credentials and no CI push to main.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. V1 (maintainer, PyPI): pending trusted publishers for `claude-acc-manager` on test.pypi.org (workflow `release.yml`, environment `pypi-test`) and pypi.org (environment `pypi`) — repo `dmenezesgabriel/claude-acc-manager`.
2. V2 (maintainer, GitHub): environments `pypi-test` (no protection) and `pypi` (required reviewer = maintainer) exist. No ruleset change — the ruleset binds PR merges only (verified: `eb1c3e6` direct push landed; GitHub ruleset docs scope `required_status_checks` to merges).
3. V3: the maintainer cuts 1.0.1 per the workflow-header flow — branch, `semantic-release version --no-tag --no-vcs-release` (commits `chore(release): 1.0.1` with the version bump, relocked `uv.lock`, `CHANGELOG.md`; the two post-tag `fix:` commits `eb1c3e6`, `2851ee1` warrant a patch), PR (the nine checks run on the release commit), rebase merge, then `git tag v1.0.1 && git push origin v1.0.1`.
4. V4: the tag push fires `release.yml` — `build` asserts tag == pyproject == uv.lock and uploads the dists; `release` creates the GitHub Release with dist assets; `deploy-test` publishes to TestPyPI — install from TestPyPI proves the artifact (the backlog's TestPyPI proof via `repository-url`).
5. V5: approve the `pypi` environment review → `deploy` publishes to PyPI.
6. V6: `pipx install claude-acc-manager==1.0.1` smoke; `cam --version` prints 1.0.1.

Write this PRD to be grepped: do not hard-wrap paragraphs, keep one fact per table row, write file names in full, and tag every gap it closes with its `GAP-NNN`.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `research_repos/claude-swap/.github/workflows/publish.yml` (28 lines, whole file checked) | Manual version bump + tag + GitHub Release; a `release: published` trigger builds with `python -m build` and publishes via `pypa/gh-action-pypi-publish@release/v1` (floating tag) with `id-token: write` on the single build+publish job — no version verification, no environment, no TestPyPI, no changelog automation, no SHA pins |
| ai-usagebar | FULL (for its registries: GH Release, crates.io, AUR) | `research_repos/ai-usagebar/.github/workflows/release.yml` — verify-version L21–83, release L251–348, publish-crates-io L350–383 (checked today) | Tag-driven: a verify-version job proves the tag is annotated, on main, and that every version surface (Cargo.toml, manifests, PKGBUILDs, .SRCINFO, CHANGELOG section) agrees before anything publishes; publish jobs are idempotent ("already exists" → warn + exit 0) and secret-presence-gated to keep forks green. Versioning itself is a manual 9-step checklist (research_repos/ai-usagebar/CLAUDE.md "Release checklist") |
| claude-code itself | N/A | — | Vendor CLI; no release-pipeline surface we interoperate with |

**Count:** 2 of the references implement release automation; neither automates the version bump (claude-swap bumps by hand, ai-usagebar by checklist). PSR is justified by the backlog decision, not by reference parity: this repo's `conventional-pre-commit` hook already enforces the exact input format PSR parses, so the version decision can be derived instead of maintained by hand.

## Implementation inventory

### claude-swap (Python — closest ecosystem match)

| Concern | Files |
| --- | --- |
| Trigger | `research_repos/claude-swap/.github/workflows/publish.yml` L3–5 — `release: types: [published]` |
| Build | same file L21–25 — `actions/setup-python` + `pip install build` + `python -m build` |
| Publish | same file L27–28 — `pypa/gh-action-pypi-publish@release/v1`, `id-token: write` on the job (L10–11) |
| Version verification | absent — the gap ai-usagebar's verify-version job exists to close |
| Environment / scoping | absent — one job holds `id-token: write` and does everything |

### ai-usagebar (Rust — process reference)

| Concern | Files |
| --- | --- |
| Version verification | `research_repos/ai-usagebar/.github/workflows/release.yml` L21–83 — tag format, annotated-tag check, commit-on-main ancestry, every version surface must agree, CHANGELOG section presence |
| Build + artifact | same file L85–249 — build matrix, SHA256 sidecars, `actions/upload-artifact` |
| GitHub Release | same file L251–348 — generated body (changelog section + checksums), idempotent create-or-update |
| Registry publish | same file L350–383 — secret-presence gating, "already exists" → warn + exit 0 |
| Manual release process | `research_repos/ai-usagebar/CLAUDE.md` "Release checklist" steps 1–9 — the process PSR replaces |

### python-semantic-release (official shape — `maintainer/research/release-pipeline.md`)

| Concern | Where (research file) |
| --- | --- |
| Canonical workflow | L24–72 — release job (checkout ref, `git reset --hard github.sha`, PSR action, publish-action, upload-artifact) + deploy job (`id-token: write` only there, `environment: pypi`, `gh-action-pypi-publish`) |
| Key semantics | L74–87 — reset-to-evaluated-SHA, `cancel-in-progress: false`, `released` output gating, publish-action as separate step |
| PSR config surface | L89–101 — `version_toml`, `tag_format`, `--noop`, `root_options` removed in v10 (security) |
| uv.lock trap | L103–126 — `[project.optional-dependencies] build` + `build_command` recipe (`uv lock --upgrade-package "$PACKAGE_NAME"`, `git add uv.lock`, `uv build`) |
| Trusted publishing | L128–144 — OIDC → 15-min project-scoped token; never inside a reusable workflow; ubuntu-latest runners only; PEP 740 attestations default-on; TestPyPI via `repository-url` |
| Environment protection | L146–152 — required reviewer on the publish environment (attrs: per-target environments) |
| Community conventions | L154–177 — attrs fork guard, build-once/upload-artifact; ai-usagebar post-PSR version assertion, idempotent publish |

## Trade-offs and what we adopt

One row per real decision. "Options seen" must come from the inventory above, not from imagination.

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Trigger model | PSR docs → PSR-on-push single pipeline; attrs → human-cut release + `release: published`/tag-triggered publish; claude-swap → manual tag + `release: published` | PSR-on-push is zero-manual-steps but requires CI to push the release commit to main — blocked by the ruleset (observed: GH013, "9 of 9 required status checks" on the first run) and unfixable without a credential (built-in `github-actions[bot]` cannot be a bypass actor on a personal repo — API 422) | **Attrs model** — the maintainer cuts the release locally; the release commit rides a normal PR so the nine checks run on it (strictly stronger than any bypass); the tag push (not ruleset-restricted) triggers the publish workflow. Chosen with the maintainer after the observed push rejection |
| PSR push vs main ruleset | research open point 1 → (a) drop protection, (b) ruleset bypass for the Actions app, (c) PAT secret | dissolved by the trigger-model pivot: the attrs model means CI never pushes to main, so no bypass actor is needed at all; (for the record — the built-in `github-actions[bot]` cannot be an `Integration` bypass actor on a personal repo: API 422 "must be part of the ruleset source or owner organization") | **No bypass actor, no credential** — the release commit is a normal PR commit |
| TestPyPI leg | attrs → permanent per-target environments (test auto, prod gated); research → one-time `repository-url` proof | permanent = every release gets a canary and the backlog's TestPyPI proof stays reproducible; one-time = less YAML, no standing proof | **Permanent ungated `deploy-test` job**, independent of `deploy` — a TestPyPI failure never blocks PyPI; the required reviewer is the human gate |
| Version verification | claude-swap → none; ai-usagebar → full pre-tag gate; research L173 → cheap post-PSR assertion | ai-usagebar's gate guards hand-made tags; with PSR the surfaces are derived, so only the residue needs guarding | **Post-PSR assertion** in the `build` job (first thing CI does with the tag): tag == `pyproject.toml` version == `uv.lock` version |
| dist attestations | PyPA → PEP 740 default-on under trusted publishing; attrs → adds `actions/attest` on the build job | `actions/attest` adds GitHub artifact attestations — extra permission + step beyond the backlog row | **PEP 740 only**; `actions/attest` out of scope |
| checkout credentials | PSR canonical → default `persist-credentials: true`; our house style → `false` everywhere | PSR's `push_new_version` builds an authenticated push URL from its `github_token` input (upstream `vcs_helpers.py`, verified 2026-10-08), so the persisted credential is unnecessary | **`persist-credentials: false` everywhere** — house style holds |

## Gap analysis — what we already have vs the references

Read our own code first. A capability that half-exists is worse than one that does not, and this is where that gets caught.

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Version bump automation | absent — static `version = "1.0.0"` (pyproject.toml L3), manual `v1.0.0` tag | ai-usagebar CLAUDE.md checklist (manual); PSR canonical (automated) | absent |
| PyPI publish | absent | claude-swap publish.yml (trusted publishing, minimal) | absent |
| GitHub Release + dist assets | absent | ai-usagebar release.yml L251–348 | absent |
| Version-surface verification | absent | ai-usagebar release.yml L21–83 | absent |
| uv.lock consistency on bump | absent — no bump exists | PSR uv guide (research file L103–126) | absent |
| Environment-scoped publish job | pattern present — docs.yml `deploy` job (L66–82: `pages: write` + `id-token: write` only there, `environment: github-pages`) | claude-swap (single job holds id-token — weaker) | present pattern, absent for PyPI |
| Build tooling | complete — hatchling backend + `uv build` (pyproject.toml L42–47) | claude-swap `python -m build` | complete (V4 proves it in CI) |
| Version surface in code | complete — `src/claude_acc_manager/__init__.py` reads `importlib.metadata.version("claude-acc-manager")`, so a `version_toml` bump flows to `cam --version` with zero code changes | — | complete |

## Deviations

Anything we will not port as-is, and why. A deviation that outlives the milestone becomes an ADR; the rest is stated in a code comment at the point it applies.

- The PSR uv-guide `build_command` recipe (`python -m pip install -e '.[build]'` first) exists to get uv into PSR's Docker action — we run PSR locally where uv already lives, so the recipe drops the pip dance and calls uv directly. Stated in the pyproject comment.
- No ADR: workflow-level design lives in workflow header comments (M14/M16 precedent).

## Open decisions

None — the research file's six open points are settled in the trade-offs table: trigger model (pivoted to the attrs model after the observed push rejection), ruleset interaction (dissolved — CI never pushes to main), TestPyPI leg, version assertion, attestations, config location (`[tool.semantic_release]` in pyproject.toml, conventional), first-release bootstrap (PSR reads the existing `v1.0.0` tag).

## Surface

| Layer | Files |
| ----- | ----- |
| domain / application / infrastructure | none — zero Python changes; `__init__.py` already resolves the version from dist metadata |
| packaging | pyproject.toml (+ uv.lock relock) |
| ci | .github/workflows/release.yml |
| tests | none writable — the gate (actionlint, zizmor pedantic, check-yaml) plus the dry-runs are the verification; there is no Python unit to mutate (ADR-0011 scope) |

## Tasks

One TDD unit each, one conventional commit each. Small enough that a unit takes well under an hour; if it does not, decompose further.

- [x] T1 — `build(deps)`: `[project.optional-dependencies] build = ["uv==0.11.8"]` + deptry dev-group marking + relock — **superseded**: the extra existed to get uv into PSR's Docker action; the attrs-model pivot removed the action from CI, so T4 reverts it.
- [x] T2 — `build(release)`: `[tool.semantic_release]` in pyproject.toml — `version_toml = ["pyproject.toml:project.version"]`, `tag_format = "v{version}"`, `build_command` = the PSR uv-guide recipe. Validated: `uv build` + `uvx twine check dist/*` clean; `semantic-release --noop version` parses the config. README wired in as the package description (twine warned on empty long_description).
- [x] T3 — `ci(release)`: `.github/workflows/release.yml` per the canonical shape, house style. Validated: actionlint + zizmor pedantic clean; full gate green. **Superseded**: the first real run proved the ruleset blocks the release-commit push (GH013, 9 of 9 required checks) — T5 rewrites the workflow.
- [x] T4 — `build(release)`: attrs-model pivot — drop the Docker-action-only `build` extra + deptry marking (relock), make `commit_message` conventional (PSR's default would be rejected by the commit-msg hook), simplify `build_command` to uv-native (no pip dance where uv already lives).
- [x] T5 — `ci(release)`: rewrite the workflow as tag-triggered publish — `build` (checkout tag, setup-env, version-surface assertion, `uv build`, upload-artifact), `release` (checkout + publish-action → GH Release with dist assets), `deploy-test` + `deploy` (trusted publishing, environments `pypi-test`/`pypi`); fork guard on every job; CI never pushes to main. Gate green.

## Out of scope

What this milestone deliberately does not do, and which milestone or deferred row owns it.

- `actions/attest` GitHub artifact attestations — PEP 740 covers PyPI-side provenance; additive later if wanted.
- CHANGELOG.md in the docs-site nav — the file lands at repo root only; a docs follow-up if wanted.
- Idempotent "already exists" publish handling (ai-usagebar's crates lesson) — trusted publishing + re-run-failed-jobs covers recovery.
- Release-PR mode (PSR opening a PR instead of pushing) — PSR v10 has no such mode; the ruleset bypass is the answer.
