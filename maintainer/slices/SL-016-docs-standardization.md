# SL-016 — Docs standardization: `docs/` = publishable only, `maintainer/` = process machinery

Milestone: M15 · State: open · Depends on: M14 open-but-gated (its remaining tasks wait on the visibility flip; orthogonal to this milestone) · Closes: —

## Outcome

A public reader finds only publishable documentation under `docs/`; every maintainer-facing process file (backlog, slice PRDs, research evidence) lives under `maintainer/`; `docs/architecture.md` conforms to arc42 §1–§12; all ADRs follow upstream MADR; the session bootstrap is a committed human-only `/next-task` skill; GitHub community-health files exist.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted. Measurements go in the closing commit's body.

1. `find docs -type f` lists only `architecture.md` and `adr/*` — no process machinery; `find maintainer -type f` lists `backlog.md`, `slices/`, `research/`.
2. `grep -rn "docs/backlog\|docs/slices\|docs/research" --exclude-dir=.git` returns no live references.
3. `.agents/skills/next-task/SKILL.md` parses with `triggers: [user]`; `/next-task` appears in Devin CLI completions and never auto-triggers (maintainer confirms once).
4. Every file under `docs/` answers a named convention (arc42 or MADR); `maintainer/` files answer ADR-0001's lifetime split.
5. Markdown links from `maintainer/backlog.md` into `docs/adr/` resolve on GitHub (`../docs/` relative form).

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it.**

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `research_repos/claude-swap/.github/ISSUE_TEMPLATE/` (`bug_report.yml`, `feature_request.yml`, `config.yml`), `research_repos/claude-swap/.github/FUNDING.yml` | Community files only — no `docs/` dir, no CONTRIBUTING/SECURITY/ADR; README carries everything |
| ai-usagebar | PARTIAL | `research_repos/ai-usagebar/CONTRIBUTING.md`, `research_repos/ai-usagebar/docs/` (5 user-docs pages), `research_repos/ai-usagebar/CLAUDE.md`, `research_repos/ai-usagebar/.github/pull_request_template.md`, `research_repos/ai-usagebar/CHANGELOG.md` | `docs/` holds user docs only; gate-first CONTRIBUTING; agent guidance as a flat `CLAUDE.md`; no ADR/architecture docs |
| toad | PARTIAL | `research_repos/toad/CONTRIBUTING.md`, `research_repos/toad/AI_POLICY.md`, `research_repos/toad/CHANGELOG.md`, `research_repos/toad/notes.md`, `research_repos/toad/.github/ISSUE_TEMPLATE/` (bug form + `pull_request_template.md` inside it) | Community files + human contributing guide; no `docs/`, no ADRs |
| claude-code itself | — | — | Vendor behavior only; no docs conventions to interoperate with |

**Count:** 0 of 3 references run a docs/ADR standardization — this milestone is *conformance* to external conventions (arc42, MADR, GitHub community-health, agents.md, Devin skills), verified in `maintainer/research/docs-standardization.md`, not a port. What is ported is file *shapes*: claude-swap's issue-form structure, ai-usagebar's gate-first CONTRIBUTING and PR-template checklist.

## Implementation inventory

Files an implementer opens. Where references disagree, the disagreement is named in Trade-offs.

### claude-swap

| Concern | Files |
| --- | --- |
| Issue forms (the model for ours) | `research_repos/claude-swap/.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `config.yml` |
| Community extras | `research_repos/claude-swap/.github/FUNDING.yml` |

### ai-usagebar

| Concern | Files |
| --- | --- |
| Contributor guide (gate-first shape) | `research_repos/ai-usagebar/CONTRIBUTING.md` |
| User docs under `docs/` | `research_repos/ai-usagebar/docs/claude-accounts.md`, `configuration.md`, `format-placeholders.md`, `openrouter-accounts.md`, `vendor-endpoints.md` |
| Agent bootstrap (contrast: a file, not a skill) | `research_repos/ai-usagebar/CLAUDE.md` |
| PR template | `research_repos/ai-usagebar/.github/pull_request_template.md` |
| Changelog (Keep-a-Changelog) | `research_repos/ai-usagebar/CHANGELOG.md` |

### toad

| Concern | Files |
| --- | --- |
| Contributor guide (discussion-gated shape) | `research_repos/toad/CONTRIBUTING.md` |
| Community extras | `research_repos/toad/.github/ISSUE_TEMPLATE/bug_report.yml`, `config.yml`, `pull_request_template.md`, `research_repos/toad/.github/FUNDING.yml`, `research_repos/toad/AI_POLICY.md` |

## Trade-offs and what we adopt

| Axis | Options seen | Trade-off | Our choice, and why |
| ---- | ------------ | --------- | ------------------- |
| Where machinery lives | A: `docs/` mixed (today) · B: `docs/` publishable-only + top-level machinery dir · C: site in `site/` subdir | A fails "a GitHub browser finds process files mixed with docs"; C inverts the convention | **B** — physical boundary, `maintainer/` (decided with maintainer this session; research doc's earlier `dev/` superseded) |
| Machinery dir name | `dev/` vs `meta/` vs `maintainer/` | `dev/` is shortest; `maintainer/` names the audience exactly | **`maintainer/`** — these files are maintainer process, not contributor dev docs (CONTRIBUTING is the dev-facing doc, and it lives at root) |
| arc42 §7/§12 + §1 shape | conform vs standing deviation | deviation is one line; conformance is real content (pipx install + XDG layout is a genuine deployment view) | **Conform** — add §7, §12, §1 subsections |
| MADR template | upstream MADR vs simplified local variant | upstream is the community-recognized format; retrofit is mechanical | **Adopt upstream** (frontmatter + heading names) and retrofit all 15 ADRs |
| Skill location | `.agents/skills/` vs `.devin/skills/` vs `.claude/skills/` | `.devin/` is tool-specific; `.agents/` is the cross-tool standard and Devin CLI reads it natively | **`.agents/skills/next-task/SKILL.md`** — committed, `/next-task` |
| Skill triggers | `[user]` vs `[user, model]` (default) | model-triggered means the bootstrap could fire autonomously mid-session | **`[user]`** — human-only invocation |
| Skill auto-approvals | none vs `allowed-tools` + `permissions.allow` | auto-approving `exec` wholesale is too broad; zero approvals prompts on every orient grep | **`allowed-tools: [read, grep, glob]` + `permissions.allow: [Exec(git status), Exec(git log), Exec(git diff)]`** — the orient step's command set only |
| Community files | CONTRIBUTING+SECURITY only vs plus templates/CoC/CODEOWNERS/FUNDING/SUPPORT | solo maintainer: CODEOWNERS/FUNDING/SUPPORT are ceremony with no consumer; templates help all three reference repos | **CONTRIBUTING.md + SECURITY.md + `.github/ISSUE_TEMPLATE/` + `.github/PULL_REQUEST_TEMPLATE.md`**; explicit no to CoC (uv/ruff ship without), CODEOWNERS, FUNDING, SUPPORT |
| Issue forms vs blank | `config.yml` with `blank_issues_enabled: false` vs no config | forcing forms adds friction pre-contributors | **No `config.yml`** — forms exist, blank issues stay allowed (claude-swap's own config keeps `blank_issues_enabled: true`) |
| README badges | add now vs defer | Actions badge renders usefully only once public; PyPI badge needs M18 | **Defer** — recorded, not drift |

## Gap analysis — what we already have vs the conventions

| Concern | Ours today (file) | Convention (source) | Gap |
| ------- | ----------------- | ------------------- | --- |
| Durable architecture doc | `docs/architecture.md` — §1–§6, §8–§11 | arc42 §1–§12 | partial — §7 Deployment View absent; §12 Glossary absent; §1 lacks stakeholder table and requirements-overview subsection |
| Decision template | `docs/adr/0000-template.md` | upstream MADR (`status`/`date` frontmatter; `Context and Problem Statement`, `Decision Drivers`, `Considered Options`, `Decision Outcome`+`Consequences`/`Confirmation`, `Pros and Cons of the Options`, `More Information`) | divergent headings + inline status/date — adopt upstream, retrofit 15 ADRs |
| Process machinery location | `docs/backlog.md`, `docs/slices/`, `docs/research/` | `docs/` = publishable docs | mixed lifetimes in one tree — move to `maintainer/` |
| Session bootstrap | `prompt-execution.md` (untracked scratch) | Devin skills (`.agents/skills/<name>/SKILL.md`) | absent as a committed skill — convert, `triggers: [user]`, sanitize `~/Documents/repos/datastudio` |
| Agent orientation | `AGENTS.md` | agents.md convention | complete — gains one `/next-task` pointer line |
| CONTRIBUTING | absent | GitHub community-health | absent — add, gate-first shape per ai-usagebar |
| SECURITY | absent | GitHub community-health | absent — add; justified: the tool reads credential stores |
| Issue/PR templates | absent | GitHub community-health | absent — add bug/feature forms + PR template |
| CoC/CODEOWNERS/FUNDING/SUPPORT | absent | GitHub community-health | absent — explicitly not adding (solo maintainer); recorded here so it is a decision, not drift |
| CHANGELOG | absent | Keep a Changelog | deferred — semantic-release generates it at M18 |
| README | install/commands/docs | GitHub profile | partial — `docs/backlog.md` line repoints to `maintainer/`; badges deferred |

## Deviations

- `maintainer/` is not a community-convention dir name (no survey found a standard); it names this repo's ADR-0001 lifetime split physically. Recorded here; if a convention emerges the dir renames cheaply.
- MADR `decision-makers`/`consulted`/`informed` frontmatter fields omitted — solo maintainer; `status`+`date` suffice.
- No CoC — uv and ruff ship without one; revisit when the repo has contributors.

## Open decisions

None — dir name, arc42 conformance, MADR adoption, community-file set, skill mechanics, and badge timing were settled with the maintainer at PRD pickup.

## Surface

| Layer | Files |
| ----- | ----- |
| move | `git mv docs/backlog.md docs/slices docs/research maintainer/` |
| repoint | `AGENTS.md`, `README.md`, `.gitignore` comment, `docs/architecture.md` (§11 backtick ref), `docs/adr/0001`, `maintainer/backlog.md` (greps + `evidence:` links + `dev/`→`maintainer/` row wording + `../docs/` markdown links), `maintainer/slices/SL-015-ci-supply-chain.md`, `maintainer/research/*.md` (self-refs + `dev/` layout block) |
| durable docs | `docs/adr/0000-template.md` (upstream MADR), `docs/adr/0001–0015` (retrofit), `docs/architecture.md` (§1, §7, §12) |
| skill | `.agents/skills/next-task/SKILL.md`; delete `prompt-execution.md` (untracked); `AGENTS.md` pointer line |
| community | `CONTRIBUTING.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `.github/PULL_REQUEST_TEMPLATE.md` |
| untouched (verified) | `src/`, `test/`, `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/`, `.gitleaks.toml` — no `docs/{backlog,slices,research}` references; ~20 `src/` comments cite `docs/architecture.md §N`/`docs/adr/NNNN` which stay in place |

## Tasks

Docs milestone — no TDD-able code. Each task is one conventional commit; the per-commit gate (`uv run pre-commit run --all-files`) runs every time.

- [x] T1 — `chore(repo): move process machinery to maintainer/` — `git mv docs/backlog.md docs/slices docs/research → maintainer/`; repoint the full surface listed above (AGENTS.md, backlog self-refs incl. `dev/`→`maintainer/` in M15/M17 rows and `evidence:` links, SL-015, research self-refs, `.gitignore` comment, README Docs section, `docs/architecture.md` §11 ref, `docs/adr/0001` path mentions).
- [x] T2 — `docs(adr): ADR-0001 — maintainer/ paths + publishability rule` — record durability == publishability: `docs/` holds only what a user may read; `maintainer/` holds the session machinery.
- [x] T3 — `docs(adr): adopt upstream MADR template` — rewrite `adr/0000-template.md`: YAML frontmatter (`status`, `date`), headings `Context and Problem Statement` / `Decision Drivers` / `Considered Options` / `Decision Outcome` (`### Consequences`, `### Confirmation`) / `Pros and Cons of the Options` / `More Information`; keep the "never cite `research_repos/`" guidance inside it.
- [x] T4 — `docs(adr): retrofit ADR-0001…0015 to MADR` — per file: inline `Status:`/`Date:` → frontmatter; `Context` → `Context and Problem Statement`; `Decision drivers` → `Decision Drivers`; `Options considered` table → `Considered Options` list + table moves under `Pros and Cons of the Options`; `Decision` → `Decision Outcome` with a `Chosen option:` lead; `Consequences` → `### Consequences` under it; `### Confirmation` only where a real fitness function exists (e.g. ADR-0011's gate). Split into two commits if the diff is too large to review.
- [ ] T5 — `docs(architecture): arc42 §1 audit + §7 + §12` — §1 gains requirements-overview and stakeholder table (solo maintainer is also the user — state it); `### Out of scope` folds into §1 requirements or carries a one-line deviation note; insert `## 7. Deployment view` (pipx/`uv tool` install → `cam` on PATH; runtime layout pointer to §3 — no duplicated content) and `## 12. Glossary` (headroom, active slot, lineage, quarantine, last-good/`trust_ok`, ops lock, mkdir lock, contract band).
- [ ] T6 — `chore(agents): add /next-task skill` — `.agents/skills/next-task/SKILL.md` from `prompt-execution.md`: frontmatter `name: next-task`, `description`, `triggers: [user]`, `allowed-tools: [read, grep, glob]`, `permissions.allow: [Exec(git status), Exec(git log), Exec(git diff)]`; body repoints `docs/backlog|slices|research` → `maintainer/` (ADR greps stay `docs/`); line-5 blockquote removed; `~/Documents/repos/datastudio` row replaced by a pointer to ADR-0010 + `AGENTS.md`; delete `prompt-execution.md`; `AGENTS.md` gains the `/next-task` pointer; `.gitignore` `prompt*.md` comment fixed.
- [ ] T7 — `docs(github): community health files` — `CONTRIBUTING.md` (gate-first per ai-usagebar: `uv sync`, `uv run pre-commit install`, the gate command, strict-TDD pointer to ADR-0011, conventional commits, PR expectations, `maintainer/backlog.md` + `/next-task` for picking work); `SECURITY.md` (private-reporting channel post-flip + interim contact — the tool reads credential stores); `.github/ISSUE_TEMPLATE/bug_report.yml` + `feature_request.yml` (claude-swap's shape: what happened / version+install / OS — Linux-only); `.github/PULL_REQUEST_TEMPLATE.md` (gate-green + conventional-commit checklist per ai-usagebar).
- [ ] T8 — `docs(repo): fluff + grep-density audit` — sweep `docs/`, `maintainer/`, `README.md`, `AGENTS.md`: every `docs/` file names its convention; delete sentences carrying no fact/instruction/criterion; zero `research_repos/` citations in durable docs; zero `docs/{backlog,slices,research}` strings outside git history.
- [ ] T9 — `docs(backlog): ship M15` — closing commit body records gate numbers + validation results; M15 row → `shipped`; delete `maintainer/slices/SL-016-docs-standardization.md` and `maintainer/research/docs-standardization.md`.

## Out of scope

- User-facing site pages + `mkdocs.yml` + Pages deploy — M17 builds on the clean `docs/` (`maintainer/research/docs-site.md`).
- Workflow restructure — M16 (`maintainer/research/ci-workflow-conventions.md`); M15 touches no workflow file.
- `CHANGELOG.md` — generated by semantic-release at M18.
- README badges — deferred to the visibility flip / M18 (decision recorded above).
- M14's remaining tasks (T3 pre-public sweep, T11 ruleset, T12 closeout) — gated on the visibility flip, per backlog rationale.
