# SL-017 — Workflow restructure to reference grade: per-concern files, composite setup, actionlint, sha-keyed concurrency

Milestone: M16 · State: open · Depends on: M14 T5–T10 (workflows exist and are green) · Closes: —

## Outcome

`.github/workflows/` reads as a reference: one file per concern (`ci` = required merge gate, `security` = audit battery, `scorecard` = repo health), the pasted checkout+setup-uv+`uv sync` block lives once in a `.github/actions/` composite, `actionlint` runs in the local commit gate, main pushes no longer cancel each other's runs, and every workflow header documents that job `name:` values are the required-check API the branch ruleset binds to.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. `uv run actionlint` and `uv run zizmor --persona pedantic .github/` both report zero findings across `.github/workflows/` and `.github/actions/`.
2. Two consecutive pushes to `main` both run to completion — the later push does not cancel the earlier run (verify via `gh run list --branch main` and both runs' `conclusion`).
3. A PR or push shows the same check names as before the restructure: `gate`, `test (3.11)`, `test (3.12)`, `test (3.13)`, `pip-audit`, `zizmor`, `gitleaks`, `codeql` — the names SL-015 T11 will bind into the branch ruleset.
4. `gate` job on a fresh push restores `mutants/` from the cache key family `mutants-t<test-tree-hash>-` (cache-banking preserved through the move).

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified. For CI *structure* the authoritative references are the maintained-repo conventions in `maintainer/research/ci-workflow-conventions.md`; the `research_repos/` products are cited for the workflow files they ship.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap (v0.27.0b1, Python) | PARTIAL — CI exists, no structure conventions | `research_repos/claude-swap/.github/workflows/ci.yml`, `research_repos/claude-swap/.github/workflows/publish.yml` | two files (`ci`, `publish`); floating tags, no permissions/concurrency, no composite or reuse |
| ai-usagebar (v1.14.0, Rust) | PARTIAL — hardened CI, monolithic file | `research_repos/ai-usagebar/.github/workflows/ci.yml`, `research_repos/ai-usagebar/.github/workflows/release.yml`, `research_repos/ai-usagebar/.github/dependabot.yml` | `ci` + `release` split; full-SHA pins, `permissions`, `concurrency` — but all check jobs in one file, no dedup of setup steps |
| toad (v0.6.20, Python) | ABSENT | `research_repos/toad/.github/` holds FUNDING + ISSUE_TEMPLATE only | no CI at all |
| claude-code itself | — | closed-source vendor | nothing to mirror |
| astral-sh/uv (external, per research) | FULL | `maintainer/research/ci-workflow-conventions.md` §community | ~30 `check-*` files + `ci.yml` orchestrator via `workflow_call`; `.github/actions/` composites; sha-keyed `concurrency.group` |
| astral-sh/ruff (external, per research) | FULL | `maintainer/research/ci-workflow-conventions.md` §community | same split; actionlint runs **via pre-commit** with `.github/actionlint.yaml` |
| pallets/flask (external, per research) | FULL | `maintainer/research/ci-workflow-conventions.md` §community | `tests.yaml` / `pre-commit.yaml` / `zizmor.yaml` / `publish.yaml`; `permissions: {}` top-level |

**Count:** 3 of 3 external convention repos use file-per-concern + extracted setup; the `research_repos/` products do not. This milestone ports the external convention, justified by the maintainer goal that these files be readable as a reference.

## Implementation inventory

### astral-sh/uv (via `maintainer/research/ci-workflow-conventions.md`, fetched 2026-04-28)

| Concern | Files |
| --- | --- |
| File-per-concern layout | `check-*` workflow files per gate concern; `ci.yml` orchestrates |
| Step reuse | `.github/actions/` composites; `ci.yml` calls `uses: ./.github/workflows/check-zizmor.yml` (`workflow_call`) for job-level reuse |
| Concurrency | `concurrency.group: ${{ github.workflow }}-${{ github.ref_name }}-${{ github.event.pull_request.number \|\| github.sha }}` — sha-keyed so distinct main pushes never cancel each other |
| Runner pinning | named images (`github-ubuntu-24.04-x86_64-4`) |

### astral-sh/ruff (via the same research file)

| Concern | Files |
| --- | --- |
| actionlint in the local gate | `.github/actionlint.yaml` config; actionlint runs via pre-commit (prek), not a CI job |

### ai-usagebar — `research_repos/ai-usagebar/.github/workflows/ci.yml` (verified on disk today)

| Concern | Files |
| --- | --- |
| Pinning/permissions/concurrency baseline | `ci.yml` — full-SHA `uses:` pins with `# vX.Y.Z`, top-level `permissions`, `concurrency` + `cancel-in-progress` |
| Freshness | `.github/dependabot.yml` — `github-actions` + `cargo` weekly |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Split granularity | uv → ~30 `check-*.yml` + orchestrator; flask → ~4 concern files; backlog row → `ci` + `security` + `scorecard` | finer splits multiply `permissions:`/`concurrency:` skeletons and required-check bookkeeping; coarser keeps one merge gate and one audit battery | **`ci.yml` (`gate` + `test` matrix), `security.yml` (`pip-audit`, `zizmor`, `gitleaks`, `codeql`), `scorecard.yml` stays** — the backlog row's prescription; `gate` stays the single required merge check, scanners stay required but grouped by cadence |
| Setup dedup mechanism | composite action (uv `.github/actions/`) vs `workflow_call` reusable job | `workflow_call` runs a *separate job* — it cannot inject steps into the caller's runner, so it dedupes nothing here | **Composite** `.github/actions/setup-env/action.yml` carrying `setup-uv` (SHA + `version:` + `checksum:` + `enable-cache`) + `uv sync --locked`; `checkout` stays a job step — a composite-internal checkout would force the action to own `persist-credentials` decisions (research recommendation) |
| Concurrency key | uv → `github.workflow`-`ref`-(`pr.number \|\| sha`); flask → `workflow`-`pr.number \|\| ref` with cancel; status quo → `ci-${{ github.ref }}` cancels main runs | ref-keyed + cancel drops in-flight main runs (loses coverage signal and mutmut cache banking) | **uv's sha-keyed group** `…-${{ github.event.pull_request.number \|\| github.sha }}`, `cancel-in-progress: true` — PR pushes still cancel stale PR runs; main pushes are unique-keyed and never self-cancel |
| `paths-ignore` for docs-only changes | flask → `paths-ignore: ['docs/**', 'README.md']`; ours → none | saves the mutmut-heavy gate on docs commits, but… | **Rejected.** GitHub docs ("Troubleshooting required status checks"): a workflow skipped by path filtering leaves associated checks **Pending and blocks merging**. With `gate` a required check (SL-015 T11), `paths-ignore` would deadlock every docs-only PR. Recorded as a deviation |
| actionlint delivery | official pre-commit hook `rhysd/actionlint` (`language: golang`/`docker`/`system`) vs `actionlint-py` dev dep | official hook needs Go/Docker on every committer machine; `actionlint-py` is sdist-only → install-time GitHub fetch, but the sdist (hash-pinned in `uv.lock`) embeds per-platform SHA256s verified at build — verified by unpacking `actionlint_py-1.7.12.25.tar.gz` | **`uv add --dev actionlint-py` + `language: system` hook `uv run actionlint`** — identical to how pyright/bandit/zizmor already reach the gate; keeps the binary version in `pyproject.toml`/`uv.lock` |
| Weekly cron placement | keep on `ci.yml` vs move to `security.yml` | the cron exists for external-drift scanners (pip-audit advisories, new CodeQL queries); a weekly `ci.yml` run would only re-warm `mutants/` | **`security.yml` only** (maintainer decision) — the comment's rationale is scanner-specific |
| Runner pinning | `ubuntu-latest` (flask) vs named image (uv) | `-latest` rolls forward silently; pinning matches the SHA-pin posture | **`ubuntu-24.04`** on every job (maintainer decision) |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| File-per-concern layout | `.github/workflows/ci.yml` holds `gate` + `test` matrix + 4 scanners; `scorecard.yml` separate | flask `tests.yaml`/`zizmor.yaml`; uv `check-*` | partial — scorecard already split, battery not |
| Setup dedup | `checkout` + `setup-uv` + `uv sync --locked` pasted into `gate`, `test`, `pip-audit`, `zizmor` jobs | uv `.github/actions/` composites | absent |
| Concurrency on main | `group: ci-${{ github.ref }}` + `cancel-in-progress: true` — second push kills the first | uv sha-keyed group | present but wrong semantics |
| Workflow correctness lint | none — zizmor covers security, not syntax/expression validity | ruff: actionlint via pre-commit | absent |
| `name:`↔ruleset coupling doc | none | — (repo-specific need: SL-015 T11 binds these names) | absent |
| Permissions/pins/timeouts/cache | `permissions: {}` + per-job redeclare; SHA pins; `timeout-minutes`; `UV_LOCKED=1`; mutants restore/save split | GitHub hardening doc + uv | complete — preserve verbatim through the moves |
| zizmor scope | `zizmor --persona pedantic .github/workflows/` | — | partial — misses `.github/actions/` once the composite lands; expand path arg to `.github/` |

## Deviations

- No `paths-ignore`/`paths` filtering anywhere: required checks under rulesets stay Pending-and-blocking when their workflow is skipped (GitHub documented behavior). Docs-only commits pay the full gate deliberately.
- No `workflow_call` orchestrator layer (uv-style `ci.yml` calling `check-*` files): three files is the backlog-prescribed granularity; an orchestrator adds a hop without adding a check.
- `actionlint` runs without shellcheck/pyflakes sidecars: our `run:` steps are one-line `uv run …`/`uv sync` calls; actionlint skips shell lint when shellcheck is absent rather than failing. Adding `shellcheck-py` later is a one-line dev dep if the `run:` surface grows.
- zizmor SARIF upload stays unadopted (GHAS, unchanged from SL-015); the zizmor job gains `.github/` scope only.
- `actionlint-py` is a third-party PyPI wrapper around upstream actionlint — accepted because the sdist pins and verifies the binary's SHA256 (integrity chain: `uv.lock` → sdist → embedded checksum → GitHub release asset).

## Open decisions

None — split granularity, dedup mechanism, concurrency key, `paths-ignore`, actionlint delivery, cron placement, and runner pinning were settled with the maintainer in the PRD session.

## Surface

| Layer | Files |
| ----- | ----- |
| ci | `.github/workflows/ci.yml` (gate + test), `.github/workflows/security.yml` (new: pip-audit, zizmor, gitleaks, codeql + weekly cron), `.github/workflows/scorecard.yml` (concurrency only), `.github/actions/setup-env/action.yml` (new composite) |
| local gate | `.pre-commit-config.yaml` (actionlint hook) |
| packaging | `pyproject.toml`, `uv.lock` (actionlint-py dev dep) |
| docs | `docs/adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md` (hook-chain list gains actionlint), `.agents/skills/next-task/SKILL.md` (gate parenthetical gains actionlint) |
| repo config | none — T11's ruleset lands post-visibility; this milestone only guarantees its check names resolve |

## Tasks

One commit each. For YAML/config tasks the "test" is `uv run actionlint` + `uv run zizmor --persona pedantic .github/` locally and the pushed workflow run itself (SL-015 precedent); each commit is pushed to `main`.

- [ ] T1 — `build(deps): dev-pin actionlint-py; add actionlint to the local gate` — `uv add --dev actionlint-py`; `.pre-commit-config.yaml` local hook (`language: system`, `entry: uv run actionlint`, `files: ^\.github/workflows/`, comment noting shellcheck is optional); update the hook-chain enumeration in `docs/adr/0011` and the gate parenthetical in `.agents/skills/next-task/SKILL.md`.
- [ ] T2 — `ci(github): split scanner battery into security.yml` — move `pip-audit`/`zizmor`/`gitleaks`/`codeql` jobs verbatim; `security.yml` gets the weekly cron + `workflow_dispatch` + push/PR; `ci.yml` drops the cron; concurrency prefix `${{ github.workflow }}` in all three files; per-file header comments including the `name:`↔ruleset coupling note ("job `name:` values are the required-check API — renaming requires a ruleset update in the same commit"); expand the zizmor step to `uv run zizmor --persona pedantic .github/`.
- [ ] T3 — `ci(github): extract setup-env composite action` — `.github/actions/setup-env/action.yml` (`using: composite`; `setup-uv` SHA+version+checksum+cache + `uv sync --locked` with `shell: bash`; optional `python-version` input — verify setup-uv treats empty input as unset, else `default: "3.12"`); swap the four pasted blocks in `gate`, `test`, `pip-audit`, `zizmor`.
- [ ] T4 — `fix(ci): sha-keyed concurrency — main pushes no longer self-cancel` — `group: ${{ github.workflow }}-${{ github.ref }}-${{ github.event.pull_request.number || github.sha }}` in `ci.yml`, `security.yml`, `scorecard.yml`.
- [ ] T5 — `ci(github): pin ubuntu-24.04 runners` — `runs-on:` across all three files.
- [ ] T6 — `docs(backlog): ship M16` — run the exit-gate validation (actionlint+zizmor output, two consecutive completed main runs via `gh run list`, check-name diff vs the SL-015 list, mutants-cache restore observed); record measurements in the commit body; flip the M16 row to `shipped`, mark M17 `open ← next`; delete this file and `maintainer/research/ci-workflow-conventions.md`.

## Out of scope

- The branch ruleset itself — SL-015 T11 owns it, gated on the visibility flip. This milestone guarantees the check names it will bind.
- `docs.yml` (M17) and `release.yml` (M18) — future files follow the conventions set here.
- SARIF upload for zizmor, `shellcheck-py`, org-level ruleset workflows, `merge_group` — no consumer today.
- Product code — zero `src/` changes in this milestone.
