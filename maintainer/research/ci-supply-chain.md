# M14 evidence — CI + supply-chain gate

Ephemeral research for the M14 PRD. Delete when M14 ships. Sources fetched
2026-04; every claim below is anchored to an official doc or a reference
workflow pinned at a commit SHA.

## Official sources consulted

| Source | URL |
| --- | --- |
| GitHub security hardening | https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions |
| setup-uv README | https://github.com/astral-sh/setup-uv (`astral-sh/setup-uv`, SHA-pinned examples) |
| zizmor docs | https://docs.zizmor.sh/usage/ + https://docs.zizmor.sh/integrations/ |
| pip-audit README | https://github.com/pypa/pip-audit |
| gitleaks-action README | https://github.com/gitleaks/gitleaks-action (v3) |
| scorecard-action README | https://github.com/ossf/scorecard-action (v2+) |
| dependabot options ref | https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference |

## Community conventions verified in the wild

`python-attrs/attrs/.github/workflows/` (hynek's gold-standard Python repo) and
`astral-sh/uv/.github/workflows/` agree on a baseline this repo should adopt
verbatim:

- **`permissions: {}` at workflow top level** — every job re-declares exactly
  what it needs. attrs does this in `pypi-package.yml`, `zizmor.yml`,
  `codeql-analysis.yml` alike.
- **`persist-credentials: false` on every `actions/checkout`** unless the job
  pushes (checkout's default persists `GITHUB_TOKEN` in `.git/config`, so any
  later step — including compromised tooling — inherits a write-capable token).
- **Full-commit-SHA pins with a `# vX.Y.Z` comment** on every `uses:` — the
  scorecard/zizmor/uv/attrs workflows all do this; Dependabot can still bump
  SHA pins.
- **`concurrency: group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}`**
  with `cancel-in-progress: true` for PR-triggered quality jobs.
- **`uv` projects pin uv itself**: uv's `check-lock.yml` passes
  `version:` + `checksum:` to `setup-uv` (supply-chain pin of the tool
  installer) and sets `UV_LOCKED: 1` as a job env so every `uv` invocation
  refuses to relock.

## Scanner inventory — what runs, what it needs

### Existing gate (reuse, don't duplicate)

`uv run pre-commit run --all-files` already covers ruff, ruff-format, pyright
strict, deptry, bandit, vulture, xenon, import-linter, pytest ≥95% branch,
mutmut. The CI `gate` job is this command plus `setup-uv` — nothing more
invented. Use `uv run --frozen` / `UV_LOCKED=1` so CI can never silently
relock.

### uv lock freshness

`uv lock --check` (or `UV_LOCKED=1 uv run …`, which already fails on a stale
lock) — uv's own CI does exactly this (`check-lock.yml`).

### pip-audit — dependency CVE scan

- PyPA-maintained (Trail of Bits/Google origin), official GH action
  `pypa/gh-action-pip-audit@v1.1.0`, or run via `uvx pip-audit`.
- `--locked` audits the project's lockfile directly (our `uv.lock` —
  verify flag semantics at PRD: it audits lock files "from the local Python
  project"; the uv-lock path may need `pip-audit` on the synced env or
  `-r` on an export; cheapest reliable form is `uv export --format
  requirements-txt --locked | pip-audit -r -` or audit the synced venv).
- Vulnerability source: PyPI advisory DB (default) or OSV (`-s osv`) — both
  account-free.
- No suppressions: finding = defect (repo policy).

### gitleaks — secret scan

- `gitleaks/gitleaks-action@v3` (Node 24 runtime; v2 dies with Node 20
  deprecation Sept 2026).
- **No license needed for personal-account repos** — `GITLEAKS_LICENSE` is
  only required for org-owned repos. This repo is personal → zero setup.
- Needs `actions/checkout` with `fetch-depth: 0` (full history) and
  `GITHUB_TOKEN` only if PR commenting is wanted (`GITLEAKS_ENABLE_COMMENTS`).
- Also runnable offline as `uvx`-style binary/pre-commit hook for local
  repro.

### zizmor — workflow security lint

- Trail of Bits-backed (`zizmorcore/zizmor`), audits template injection,
  credential persistence, excessive permissions, unpinned refs, etc.
- Official action `zizmorcore/zizmor-action` (v0.6.4 SHA-pinned in attrs).
  attrs runs it with `persona: pedantic` — which additionally surfaces code
  smells (the user's explicit ask).
- **Critical caveat (official docs)**: `--format=sarif` always exits 0 —
  the action path uploads SARIF to code scanning and never fails the job on
  findings. A *blocking* gate needs either (a) code-scanning ruleset that
  fails PRs on alerts, or (b) plain/`github` format run which exits nonzero.
  PRD decision: run `uvx zizmor@<pin> --persona=pedantic .` as a failing
  check (annotations, no `security-events` perm), or action+SARIF+ruleset.
- Permissions for SARIF path: `security-events: write` (job-scoped) +
  `actions: read` on private repos. Plain format needs nothing.
- Offline by default; `GH_TOKEN`/`GITHUB_TOKEN` in env flips it online
  (extra audits). PRD decides whether the gate job exports `GH_TOKEN`.

### CodeQL — SAST

- `github/codeql-action` init/autobuild/analyze, `languages: python`
  (interpreted — autobuild is a no-op but harmless; attrs keeps it).
- attrs runs it scheduled-only (`cron` + `workflow_dispatch`); for a PR gate
  add `push`/`pull_request` triggers — or enable GitHub's zero-config
  **default setup** in repo settings and keep the workflow only if we want
  it versioned/audited by zizmor. PRD decision (versioned workflow is more
  consistent with this repo's everything-in-repo posture).
- Job needs `security-events: write` (+ `actions: read`, `contents: read` on
  private repos).

### OpenSSF Scorecard

- `ossf/scorecard-action` v2+: free on public repos; `publish_results: true`
  (badge/API) requires `id-token: write`; SARIF upload needs
  `security-events: write`.
- Supported triggers: `push` (default branch) + `schedule`;
  `pull_request`/`workflow_dispatch` are experimental.
- Private repo without Advanced Security → run CLI-only or skip; this repo
  is public-eligible once public. **Flag: if the repo is still private at
  M14 time, Scorecard job must be conditional or deferred.**

### Dependabot — `.github/dependabot.yml`

- `version: 2`; ecosystems needed: `uv` (GA ecosystem per options ref —
  keeps `uv.lock` + `pyproject` fresh) and `github-actions` (bumps SHA
  pins — this is what makes SHA pinning sustainable).
- Weekly interval is conventional (attrs/uv cadence); `open-pull-requests-limit`
  default 5 is fine.

## GitHub-native hardening checklist (from the official hardening doc)

- Workflow-level `permissions: {}`; per-job elevation only.
- No `pull_request_target` anywhere — PRs get `pull_request` + read-only
  token, so fork PR code can never touch secrets/publish jobs.
- No `${{ github.event.* }}` interpolation inside `run:` blocks — untrusted
  context goes through `env:` + quoted shell vars (script-injection rule).
- `concurrency` on every workflow.
- `timeout-minutes` on every job (uv's convention).
- Actions must be GitHub-provided or verified-publisher where possible:
  `actions/*`, `github/codeql-action/*`, `astral-sh/setup-uv` (Astral is a
  verified publisher), `zizmorcore/zizmor-action` (Trail of Bits),
  `gitleaks/gitleaks-action`, `ossf/scorecard-action`,
  `pypa/gh-action-pip-audit` / run pip-audit via `uvx` instead if we prefer
  fewer third-party actions in the trust boundary.

## Decisions deferred to the M14 PRD

1. zizmor blocking mode: plain failing run vs SARIF + ruleset.
2. CodeQL: versioned workflow file vs repo-settings default setup.
3. Scorecard: include now (if repo public) or defer behind a condition.
4. pip-audit invocation form: `pypa/gh-action-pip-audit` vs
   `uvx pip-audit` on synced env/lock export.
5. Whether the monolithic `pre-commit --all-files` gate runs as one job or
   mutmut splits out (mutmut dominates wall time; splitting keeps PR signal
   fast — but two jobs duplicate setup-uv/install; measure at PRD).
6. Python version matrix: project supports `>=3.12`; matrix `3.12`+`3.13`
   for pytest, single-version for lint jobs (matching pyright target).
