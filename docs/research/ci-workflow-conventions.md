# M16 evidence — workflow structure and hardening conventions

Ephemeral research for the M16 PRD (slice SL-017 at pickup). Delete when M16
ships. Sources fetched 2026-04-28; every claim is anchored to a workflow file
verified in a maintained repository or an official doc.

## Official sources consulted

| Source | URL |
| --- | --- |
| Reusable workflows (`workflow_call`) | https://docs.github.com/en/actions/sharing-automations/reusing-workflows |
| Composite actions | https://docs.github.com/en/actions/sharing-automations/creating-actions/creating-a-composite-action |
| Security hardening for GitHub Actions | https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions (checklist already applied in M14 — permissions, SHA pins, `persist-credentials: false`) |
| actionlint | https://github.com/rhysd/actionlint — static checks for workflow syntax/expression errors; the correctness linter zizmor doesn't try to be |
| zizmor | https://docs.zizmor.sh — security lint; pedantic persona already in use |

## Community conventions verified in the wild

| Repo | File organization | Reuse mechanism | Notable details |
| --- | --- | --- | --- |
| astral-sh/uv | ~30 single-concern files: `check-*` (PR gates: fmt, lint, lock, zizmor, docs, generated-files, publish, release), `build-*`, `publish-*`, `ci.yml` orchestrates | `workflow_call` — `ci.yml` does `uses: ./.github/workflows/check-zizmor.yml`; composite actions under `.github/actions/` | `concurrency.group: ${{ github.workflow }}-${{ github.ref_name }}-${{ github.event.pull_request.number \|\| github.sha }}` — sha-keyed, so distinct main pushes never cancel each other; `.github/zizmor.yml` config file |
| astral-sh/ruff | same shape (`ci.yaml`, `build-*`, `publish-*`, `zizmor`-adjacent scanning) | `.github/actionlint.yaml` config — actionlint runs **via pre-commit** (prek), i.e. inside the local gate | `.github/CODEOWNERS`, ISSUE/PR templates |
| fastapi/fastapi | ~20 verb-named files: `test.yml`, `zizmor.yml`, `pre-commit.yml`, `deploy-docs.yml`, `build-docs.yml`, `publish.yml` | per-file single purpose | docs build and docs deploy are separate files |
| pallets/flask | `tests.yaml`, `pre-commit.yaml`, `zizmor.yaml`, `publish.yaml` | — | `paths-ignore: ['docs/**', 'README.md']` on tests; `permissions: {}` top-level; concurrency keyed `workflow`-`pr.number \|\| ref` |
| Textualize/textual | `pythonpackage.yml`, `codeql.yml`, `black_format.yml` | — | CodeQL lives in its own file |
| squidfunk/mkdocs-material | `build.yml`, `documentation.yml` | — | minimal two-file split |

The shared convention: **one file per concern**, named for what it does
(`check-*`/`test`/`security`/`docs`/`publish`), with shared setup extracted
behind `workflow_call` or `.github/actions/` composites. Nobody puts scanners,
tests, and release in one file at reference quality.

## Gap inventory — `.github/workflows/` vs the conventions

| Concern | Ours today | Convention | Gap |
| --- | --- | --- | --- |
| File layout | one `ci.yml` holds `gate` + `test` matrix + `pip-audit` + `zizmor` + `gitleaks` + `codeql`; `scorecard.yml` separate | file-per-concern | Candidate split: `ci.yml` (gate + test matrix — the required merge gate) · `security.yml` (pip-audit, zizmor, gitleaks, codeql — the audit battery) · `scorecard.yml` stays · `docs.yml` arrives at M17 · `release.yml` at M18. Alternative: uv-style `check-*.yml` per job + an orchestrator — decide granularity at PRD |
| Duplicated setup | `checkout` + `setup-uv` (version+checksum+cache) + `uv sync --locked` pasted into 5 jobs | `.github/actions/` composite (uv) or `workflow_call` reusable | Extract `.github/actions/setup-env/action.yml` carrying setup-uv + sync (checkout stays a job step — composite-internal checkout is unusual and forces the action to own `persist-credentials` decisions) — or a `workflow_call` job; composite is the lighter fit |
| Concurrency on main | `group: ci-${{ github.ref }}`, `cancel-in-progress: true` | uv: sha-keyed group → main runs never self-cancel; flask: ref-keyed (does cancel) | Any second push to `main` cancels the in-flight main run — loses the coverage signal *and* the mutmut cache banking. Fix: uv's `\|\| github.sha` key, or `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` |
| Workflow correctness lint | absent | ruff: `.github/actionlint.yaml` + runs actionlint in pre-commit | Add `rhysd/actionlint` to the pre-commit gate — checks syntax, expression types, action version validity; complements zizmor (security) with zero overlap |
| Required-check stability | job `name:` values feed the T11 ruleset (`gate`, `test (3.11)` …) | names are the public API of a workflow | Document in the workflow header that renaming a `name:` breaks the ruleset — renames must update ruleset + workflow in one commit |
| `paths` filtering | none — a README-only push pays the full mutmut gate | flask: `paths-ignore: ['docs/**', 'README.md']` | Candidate saving, but verify first: under rulesets a path-skipped required check must not sit pending forever (GitHub treats skipped-as-success in ruleset evaluation — confirm exact semantics at PRD before adopting) |
| `runs-on:` | `ubuntu-latest` everywhere | uv pins named runner images (`github-ubuntu-24.04-x86_64-4`); flask uses `ubuntu-latest` | Minor decision: pin `ubuntu-24.04` for reproducibility vs `-latest` for rolling freshness |
| zizmor invocation | `uv run zizmor` (lockfile-pinned version) | uv: `zizmorcore/zizmor-action` + SARIF upload w/ GHAS | Keep `uv run` — version stays in `uv.lock`, no GHAS dependency; once public, SARIF upload is an optional enhancement, not a requirement |
| Permissions/pins/timeouts | `permissions: {}` + per-job redeclare; SHA-pinned actions; `timeout-minutes` per job; `UV_LOCKED=1`; `persist-credentials: false` | the hardened baseline (GitHub docs + uv/attrs) | Already conforming — preserve when restructuring |
| Coverage signals | `gate` runs pytest inside pre-commit AND `test` matrix re-runs it | gate = whole-repo lint+test at one version; matrix = version surface | Intentional duplication — keep; document why in the header comment so a "dedupe" refactor doesn't strip it |

## Encapsulation target

The user wants these files readable as a reference by other projects. That
means: header comment per file stating the concern it owns, why it sits in its
own file when non-obvious (scorecard already does this), stable job names,
and every non-default knob (`concurrency`, `permissions`, `timeout`,
cache keys) justified in one inline comment — the style `ci.yml` already uses.

## Decisions deferred to the M16 PRD

1. Split granularity: `ci.yml` + `security.yml` two-way split vs. finer
   `check-*.yml` files — pick after weighing required-check bookkeeping.
2. Composite action vs `workflow_call` for the shared setup block.
3. Concurrency key: sha-keyed (uv) vs event-conditional cancel.
4. `paths-ignore` for docs-only changes — only if the skipped-required-check
   semantics verify clean.
5. actionlint: pre-commit hook (ruff pattern) vs a CI job — recommend
   pre-commit so the local gate catches it.
6. Runner pinning: `ubuntu-latest` vs `ubuntu-24.04`.
