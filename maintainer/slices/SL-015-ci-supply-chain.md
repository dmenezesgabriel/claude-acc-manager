# SL-015 — CI + supply-chain gate: workflows, scanners, dependabot, required check

Milestone: M14 · State: open · Depends on: M13 shipped (full v1 surface) · Closes: —

## Outcome

Every push to `main` and every pull request runs the full local quality gate plus a supply-chain scanner battery on GitHub Actions, with `gate` a required status check that mechanically blocks merges; before CI lands the repo goes public after a documented hygiene pass (MIT license, clean full-history secret scan), because CodeQL and Scorecard cannot run on a private repo without GitHub Advanced Security.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. A real pull request shows `gate`, `test (3.11)`, `test (3.12)`, `test (3.13)`, `pip-audit`, `zizmor`, `gitleaks`, `codeql` green; job wall times recorded in the closing commit body (cold-run mutmut time especially).
2. Each scanner ran and reported zero findings — pip-audit on the synced env, `zizmor --persona pedantic` on `.github/workflows/`, gitleaks over full history, CodeQL analysis uploaded, Scorecard published.
3. A deliberately-failing commit pushed to the PR turns `gate` red and the merge button is blocked by the ruleset; the follow-up fix commit unblocks it.
4. `gh api repos/dmenezesgabriel/claude-acc-manager/rulesets` shows the required-check ruleset on the default branch.
5. `gh repo view --json visibility` returns `PUBLIC`, repo has an MIT `LICENSE`, and `gitleaks git` over all refs reports no real leaks (fixtures allowlisted).

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap (v0.27.0b1, Python) | PARTIAL — CI exists, gate-only | `research_repos/claude-swap/.github/workflows/ci.yml`, `research_repos/claude-swap/.github/workflows/publish.yml` | `astral-sh/setup-uv` + `uv sync --locked` + `uv run pytest` across ubuntu/windows/macos; floating `@v*` action tags, no permissions block, no concurrency, no scanners |
| ai-usagebar (v1.14.0, Rust) | PARTIAL — hardened CI, no scanners | `research_repos/ai-usagebar/.github/workflows/ci.yml`, `research_repos/ai-usagebar/.github/dependabot.yml`, `research_repos/ai-usagebar/.github/workflows/release.yml` | full-SHA action pins with `# vX.Y.Z` comments, `permissions: contents: read`, `concurrency` + `cancel-in-progress`, per-platform jobs, weekly dependabot for `github-actions` + `cargo` |
| toad (v0.6.20, Python) | ABSENT | `research_repos/toad/.github/` has no `workflows/` directory (FUNDING + issue templates only) | no CI at all — shipped from the local gate |
| claude-code itself (vendor behavior we must interoperate with) | — | closed-source vendor; no shared-file or process contract for CI | interop stays ADR-0015's version gate — nothing to mirror |

**Count:** 2 of 3 references run CI; none runs a scanner battery. The scanner set is an invention relative to the references — justified by repo policy (`.agents/skills/next-task/SKILL.md` §Release: every installed scanner must stay green, a new finding is a defect) and by the conventions verified in `maintainer/research/ci-supply-chain.md` (attrs, uv).

## Implementation inventory

### ai-usagebar

| Concern | Files |
| --- | --- |
| Triggers / job layout | `research_repos/ai-usagebar/.github/workflows/ci.yml` (`push` main + `pull_request` + `workflow_dispatch`; `linux`/`msrv`/`nix`/`macos`/`windows` jobs) |
| Action pinning | `research_repos/ai-usagebar/.github/workflows/ci.yml` (every `uses:` is a full commit SHA with a `# vX.Y.Z` comment) |
| Token hygiene | `research_repos/ai-usagebar/.github/workflows/ci.yml` (top-level `permissions: contents: read`) |
| Concurrency | `research_repos/ai-usagebar/.github/workflows/ci.yml` (`ci-${{ github.ref }}` + `cancel-in-progress: true`) |
| Dependency freshness | `research_repos/ai-usagebar/.github/dependabot.yml` (`github-actions` + `cargo`, weekly) |
| Release precedent (M15, not ported) | `research_repos/ai-usagebar/.github/workflows/release.yml` (tag `v*` + `workflow_dispatch`; `verify-version` gate job; idempotent publish; secret-presence gating) |

### claude-swap

| Concern | Files |
| --- | --- |
| Triggers / job layout | `research_repos/claude-swap/.github/workflows/ci.yml` (`push`/`pull_request` on main; `test`, `test-windows`, `macos-keychain`) |
| uv-in-CI baseline | `research_repos/claude-swap/.github/workflows/ci.yml` (`astral-sh/setup-uv@v6` `python-version:` → `uv sync --locked` → `uv run pytest`) |
| Hardening gaps (evidence of what to add) | `research_repos/claude-swap/.github/workflows/ci.yml` — floating `@v4`/`@v6` tags, no `permissions`, no `concurrency`, `timeout-minutes` on one job only |
| Release precedent (M15, not ported) | `research_repos/claude-swap/.github/workflows/publish.yml` (`release: published` → `pypa/gh-action-pypi-publish` trusted publishing) |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Gate composition | split per-concern jobs (attrs convention) vs one composite command | mutmut dominates wall time and a split duplicates `setup-uv` + `uv sync`; a required-check list grows per job | **Single `gate` job** running `uv run pre-commit run --all-files` verbatim — CI is an exact mirror of the local gate (maintainer decision); cold-run mutmut time measured and recorded in the first green run's commit body; split only if measurement demands it |
| Python coverage | claude-swap → single 3.12; ai-usagebar → single toolchain per OS | `requires-python` advertises a range nobody tests | `test` job matrix `[3.11, 3.12, 3.13]` on `ubuntu-latest` running `uv run pytest` (maintainer decision); `gate` stays 3.12 — the version `.python-version`, pyright, and the dev loop pin |
| 3.11 support cost | — | `src/claude_acc_manager/tui/app.py` `_run_action[T]` is PEP 695 syntax — the only parse blocker under `ast.parse(feature_version=(3,11))` (`test/` is clean; only 3.12+ stdlib hit is `tomllib`, which is 3.11-safe) | Rewrite as `TypeVar`; `requires-python = ">=3.11"`; ruff `target-version = "py311"` and pyright `pythonVersion = "3.11"` move to the minimum supported floor so lint flags 3.12-only APIs going forward; `.python-version` stays 3.12 (dev interpreter) |
| Action pinning | claude-swap → floating `@v4`/`@v6`; ai-usagebar → full SHA + `# vX.Y.Z` | floating tags are the textbook supply-chain hole; SHAs rot without a bumper | Full-SHA pins with `# vX.Y.Z` comments on every `uses:` + `dependabot.yml` covering the `github-actions` ecosystem — the combination is what makes SHA pinning sustainable |
| Scanner delivery | attrs → `zizmor-action` SARIF upload; research → `pypa/gh-action-pip-audit` or `uvx` | extra third-party actions widen the trust boundary; `uvx` pins a version but not a hash | **`zizmor` and `pip-audit` as dev-group dependencies** — `uv.lock` hash-pins them, `uv run pip-audit` / `uv run zizmor` reproduce locally, deptry does not flag unused dev deps (precedent: bandit, pyright, vulture already live there); `gitleaks` stays a SHA-pinned action (Go binary, not pip-installable) |
| zizmor blocking mode | SARIF + code-scanning ruleset (attrs) vs plain-format failing run | `--format=sarif` always exits 0 (official docs caveat); SARIF upload needs GHAS — impossible while private | `uv run zizmor --persona pedantic .github/workflows/` as a failing step — plain format exits nonzero, needs no `security-events` permission; findings are fixed, never suppressed (repo policy) |
| CodeQL delivery | versioned workflow (attrs `codeql-analysis.yml`) vs repo-settings default setup | everything-in-repo posture — and zizmor can only audit what is versioned | Versioned job in the workflow, `languages: python`, job-scoped `security-events: write` |
| Workflow file granularity | attrs → one file per concern (`zizmor.yml`, `codeql-analysis.yml`); ai-usagebar → `ci.yml` + `release.yml` | more files = more `permissions:`/`concurrency:` skeletons to keep hardened | Two files: `ci.yml` (push:main + PR + weekly schedule + dispatch — the weekly run exists so pip-audit catches newly-published CVEs in pinned deps and CodeQL picks up new queries) and `scorecard.yml` (push:main + weekly — different cadence and permission profile) |
| Public-first ordering | defer CodeQL/Scorecard until public vs hygiene-then-public inside M14 | while private, two backlog-listed scanners cannot run — shipping them inert leaves "each scanner runs and reports zero findings" unmet | **Hygiene first** (maintainer decision): LICENSE + history scan + sweep land first, the maintainer flips visibility, then the full battery lands and validates for real |
| License | MIT / Apache-2.0 / GPL-3.0 | going public without a license means all-rights-reserved; Scorecard's License check flags it | **MIT** (maintainer decision) — SPDX `license = "MIT"` in pyproject + `LICENSE` file |
| Required check | ai-usagebar/claude-swap rely on green-signal discipline | "a deliberately-failing commit proves the gate blocks" needs mechanical enforcement | Repo ruleset via `gh api` requiring `gate` + scanner jobs on the default branch (maintainer decision); classic `PUT /branches/main/protection` is the fallback if rulesets are plan-gated |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| CI workflow | none — no `.github/` directory | `research_repos/ai-usagebar/.github/workflows/ci.yml` | absent |
| uv-in-CI setup | none | `research_repos/claude-swap/.github/workflows/ci.yml` (`setup-uv` + `uv sync --locked`) | absent |
| Action pinning | none | ai-usagebar `ci.yml` full-SHA + comments | absent |
| Dependabot | none | `research_repos/ai-usagebar/.github/dependabot.yml` | absent |
| Dependency CVE scan | `deptry` in `.pre-commit-config.yaml` (unused/missing deps only — no CVE feed) | none in refs | absent — `pip-audit` added |
| Secret scan | none; `test/unit/usage/infrastructure/test_anthropic_oauth.py` lines 339+395 hold fake `sk-ant-oat01-*` literals that will trip it | none in refs | absent — gitleaks + path-scoped `.gitleaks.toml` fixture allowlist |
| Workflow security lint | none | attrs `zizmor.yml` (external, per `maintainer/research/ci-supply-chain.md`) | absent — zizmor pedantic, blocking |
| SAST | `bandit -ll` in `.pre-commit-config.yaml` (lint-level only) | attrs `codeql-analysis.yml` (external) | absent — CodeQL (post-public) |
| Repo health scorecard | none | — | absent — Scorecard (post-public) |
| LICENSE | none | — | absent — blocks going public and Scorecard's License check |
| uv lock freshness | implicit via `uv sync --locked`/`UV_LOCKED=1` | uv `check-lock.yml` (external) | covered by the gate job itself |
| Merge enforcement | none — green-signal discipline only | — | absent — ruleset required check |

## Deviations

- zizmor runs as a blocking plain-format step, not SARIF + code-scanning: SARIF upload needs GitHub Advanced Security (unavailable while private), and the blocking run fits "a new finding is a defect, never suppress" better than advisory annotations.
- Scanners run in CI only, not as pre-commit hooks: `pip-audit` needs the advisory network feed and `gitleaks git` walks full history — both too slow/networked for the commit gate. Dev-dep delivery keeps them locally reproducible via `uv run`.
- `.gitleaks.toml` allowlists the two fake `sk-ant-oat01-*` literals in `test/unit/usage/infrastructure/test_anthropic_oauth.py` — they are deliberately token-shaped redaction-test inputs, path-scoped to that file; this is the sole sanctioned suppression, recorded because the zero-suppression rule would otherwise forbid it.
- No `actionlint`: zizmor pedantic covers the workflow-lint surface and GitHub reports syntax errors on push.
- No OS matrix: the tool is Linux-only (`pyproject.toml` description); per-OS jobs in the references exist to cover per-OS code we do not have.
- No `pull_request_target` anywhere: fork PR code must never touch secrets or publish jobs.

## Open decisions

None — gate shape, Python matrix, hygiene ordering, license, and the required-check mechanism were settled with the maintainer in this session.

## Surface

| Layer | Files |
| ----- | ----- |
| ci | `.github/workflows/ci.yml` (`gate`, `test` matrix, `pip-audit`, `zizmor`, `gitleaks`, `codeql` jobs), `.github/workflows/scorecard.yml`, `.github/dependabot.yml`, `.gitleaks.toml` |
| packaging | `LICENSE`, `pyproject.toml` (`license = "MIT"`, `requires-python = ">=3.11"`, ruff `target-version = "py311"`, pyright `pythonVersion = "3.11"`, dev-group `zizmor` + `pip-audit`), `uv.lock` |
| src | `src/claude_acc_manager/tui/app.py` (`_run_action[T]` → module-level `TypeVar`) |
| repo config | GitHub ruleset on default branch via `gh api` (or classic branch protection fallback); repo visibility flip + description/topics — maintainer action |

## Tasks

One TDD unit each, one conventional commit each. For YAML/config tasks the "test" is the pushed workflow run itself plus `uv run zizmor` on the file; code changes still go RED → GREEN.

- [x] T1 — `chore(license): add MIT LICENSE and SPDX metadata` — `LICENSE` (MIT, Gabriel Menezes), `pyproject.toml` `license = "MIT"` + hatchling license-files; verify `uv build` dists carry `LICENSE`.
- [x] T2 — `chore(security): full-history gitleaks scan + fixture allowlist` — install gitleaks locally; `gitleaks git` over all refs (169 commits + `v1.0.0`); triage every hit — real ones rotate before going public; add `.gitleaks.toml` path-scoped allowlist for `test/unit/usage/infrastructure/test_anthropic_oauth.py` fake tokens.
- [x] T3 — `chore(repo): pre-public sweep` — assert `.claude/`, `prompt*.md`, `research_repos/`, `.coverage`, `dist/`, `mutants/`, `.venv/` are untracked; review tracked docs for internal-only content; `gh repo edit` description + topics. **STOP — maintainer flips visibility to public** (`gh repo edit --visibility public --accept-visibility-change-consequences`); execution resumes T4.
- [x] T4 — `build: support python >=3.11` — `_run_action[T]` → `TypeVar` in `src/claude_acc_manager/tui/app.py`; `requires-python = ">=3.11"`; ruff `py311`; pyright `pythonVersion = "3.11"`; `uv lock`; verify textual/rich/pytest dep floors accept 3.11; existing suite green under 3.12.
- [x] T5 — `ci(github): ci.yml — gate + test matrix` — triggers `push` branches `[main]` + `pull_request` + weekly `schedule` + `workflow_dispatch`; top-level `permissions: {}`; `concurrency` `ci-${{ github.ref }}` + `cancel-in-progress: true`; `timeout-minutes` per job; `actions/checkout` SHA-pinned + `persist-credentials: false`; `astral-sh/setup-uv` SHA-pinned with `version:` + `checksum:`; `UV_LOCKED=1`; `gate` job `uv sync --locked` → `uv run pre-commit run --all-files`; `test` job matrix `[3.11, 3.12, 3.13]` → `uv run pytest`.
- [x] T6 — `build(deps): dev-pin zizmor and pip-audit` — `uv add --dev zizmor pip-audit`; uv.lock hash-pins both.
- [x] T7 — `ci(github): scanner jobs — pip-audit, zizmor, gitleaks` — `pip-audit` job runs `uv run pip-audit` on the synced env (audits runtime + dev deps); `zizmor` job runs `uv run zizmor --persona pedantic .github/workflows/` (plain format, exits nonzero); `gitleaks` job uses `gitleaks/gitleaks-action` SHA-pinned v3 with checkout `fetch-depth: 0` — personal repo, no license needed; reads `.gitleaks.toml` from T2.
- [x] T8 — `ci(github): codeql job` — `github/codeql-action` init/analyze SHA-pinned, `languages: python`, job-scoped `security-events: write` + `contents: read` + `actions: read`; runs on PR + push + weekly.
- [x] T9 — `ci(github): scorecard.yml` — `ossf/scorecard-action` SHA-pinned; triggers `push` main + weekly `schedule`; `publish_results: true`; job-scoped `id-token: write` + `security-events: write` + `contents: read`.
- [x] T10 — `ci(github): dependabot` — `.github/dependabot.yml`, ecosystems `uv` + `github-actions`, `directory: /`, weekly.
- [ ] T11 — `ci(github): required-check ruleset + blocking proof` — `gh api repos/dmenezesgabriel/claude-acc-manager/rulesets` creating a ruleset on the default branch requiring `gate` + `test` matrix + scanner jobs (fallback: classic `PUT /branches/main/protection`); push a deliberately-failing commit to the validation PR, confirm `gate` red + merge blocked, push fix, confirm green.
- [ ] T12 — `docs(backlog): ship M14` — closing commit body records measured job times + zero-finding scanner results; flip M14 row to `shipped`; delete `maintainer/slices/SL-015-ci-supply-chain.md` and `maintainer/research/ci-supply-chain.md`.

## Out of scope

- Release pipeline — M15 (`maintainer/research/release-pipeline.md`); `publish.yml`/`release.yml` cited above are precedent only.
- macOS/Windows CI — the tool is Linux-only; the references' per-OS jobs cover per-OS code we do not have.
- `pull_request_target`, reusable workflows, self-hosted runners — none needed.
- `actionlint` — zizmor pedantic covers the workflow-lint surface.
- SARIF/ruleset path for zizmor — blocking plain run chosen; SARIF needs GHAS.
- `cam doctor --json` and all product-code changes beyond the `tui/app.py` PEP-695 rewrite — no other code changes in this milestone.
