# M15 evidence — docs standardization pass

Ephemeral research for the M15 PRD (slice SL-016 at pickup). Delete when M15
ships. Sources fetched 2026-04-28; every claim below is anchored to an
official doc or a file verified present in a maintained repository.

## Official sources consulted

| Source | URL |
| --- | --- |
| arc42 template (12 sections) | https://docs.arc42.org — §1 Intro/Goals · §2 Constraints · §3 Context/Scope · §4 Solution Strategy · §5 Building Block View · §6 Runtime View · §7 Deployment View · §8 Crosscutting Concepts · §9 Architecture Decisions · §10 Quality Requirements · §11 Risks/Tech Debt · §12 Glossary |
| MADR template | https://raw.githubusercontent.com/adr/madr/develop/template/adr-template.md — YAML frontmatter (status/date/decision-makers/consulted/informed) + "Context and Problem Statement", "Decision Drivers", "Considered Options", "Decision Outcome" (w/ Consequences + Confirmation), "Pros and Cons of the Options", "More Information" |
| GitHub community health files | https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions — CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md, SUPPORT.md, FUNDING.yml, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md (root, `docs/`, or `.github/`); README+LICENSE are the profile baseline |
| Keep a Changelog | https://keepachangelog.com — the `CHANGELOG.md` format semantic-release emits at M18 |
| Diátaxis | https://diataxis.fr — tutorials / how-to / reference / explanation; governs site content shape (M17 consumes it) |
| AGENTS.md convention | https://agents.md — the tool-agnostic agent-instructions filename |
| Devin CLI skills format | `extensibility/skills/creating-skills` + `skills/overview` in the installed docs — project skills at `.devin/skills/<name>/SKILL.md` or `.agents/skills/<name>/SKILL.md` (both committed); `triggers: [user]` = human-only invocation via `/<name>`; directory name = invocation name |

## Community conventions verified in the wild

| Repo (maintained) | Root community files | Workflow/docs extras |
| --- | --- | --- |
| astral-sh/uv | `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `mkdocs.yml` | `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/actions/` (composite actions), `.github/zizmor.yml` |
| astral-sh/ruff | `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `mkdocs.yml` + `mkdocs.template.yml` | `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/actionlint.yaml`, `.github/zizmor.yml`, `.agents/`, `.claude/` |
| Textualize/textual | `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `CHANGELOG.md` | `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/FUNDING.yml` |
| pallets/flask | `CHANGELOG.md` (verified) | `.readthedocs.yaml`; `paths-ignore` workflow convention |
| psf/requests, encode/httpx | `CHANGELOG.md` (httpx) | `.readthedocs.yaml` (flask/requests — Sphinx-era convention); `mkdocs.yml` (httpx) |

The agent-guidance split is settled by evidence: `AGENTS.md` is the
auto-loaded orientation file maintained projects track (uv, ruff — ruff
additionally keeps a thin `CLAUDE.md`), while a session **bootstrap procedure**
is a different thing — it is a skill. `prompt-execution.md` is not a
community-recognized name; its content is a triggerable workflow.

## Gap inventory — our `docs/` + root vs the conventions

| File | Convention | Ours today | Gap |
| --- | --- | --- | --- |
| `docs/architecture.md` | arc42 §1–§12 | Has §1–§6, §8–§11 | §7 Deployment View absent (a CLI installed via pipx has a real deployment view — even if short); §12 Glossary absent; §1 lacks the arc42 stakeholder table and requirements-overview subsections; `### Out of scope` is not an arc42 §1 heading — either conform or record the deviation inside the doc |
| `docs/adr/0000-template.md` | MADR | Simplified variant: inline `Status:`/`Date:` lines; headings "Context", "Decision drivers", "Options considered" (table), "Decision", "Consequences" | Diverges from upstream heading names (`Context and Problem Statement`, `Considered Options`, `Decision Outcome`, `Confirmation`, `Pros and Cons of the Options`, `More Information`) and the status frontmatter — adopt upstream names or document the adaptation; then re-audit all 15 ADRs against whichever template wins |
| `AGENTS.md` | agents.md | Tracked; holds docs map + code style | Correct file, correct name. Gains one line pointing at the `next-task` skill so agents discover the bootstrap — the file itself stays an orientation map, not a procedure |
| `prompt-execution.md` | a project **skill**, not a root doc | Untracked (hygiene choice, 8f8af7e); holds the session bootstrap | Convert to `.agents/skills/next-task/SKILL.md` (decided): frontmatter `name: next-task`, `triggers: [user]` so only a human runs `/next-task` — verified the field exists and is exactly this semantic; content = today's bootstrap sanitized (`~/Documents/repos/datastudio` personal path out; `docs/` process paths repointed to `dev/`); `.agents/` is the cross-tool standard location (ruff ships `.agents/`) and is committed; delete the root scratch file afterwards. `allowed-tools`/`permissions` scoping is a PRD decision |
| docs tree split | `docs/` = published docs | `docs/` mixes durable docs with process machinery (`backlog.md`, `slices/`, `research/`) | Physical split (decided): `docs/` keeps only publishable content — today that's `architecture.md` + `adr/`, user pages arrive at M17; `backlog.md`, `slices/`, `research/` move to a top-level `dev/` dir. Rule that falls out: **durability == publishability** — `docs/` holds only content a user may read; `dev/` holds session machinery. Land the move early in M15 so the `next-task` skill is written against final paths. Repoint every reference: `grep -rn "docs/backlog\|docs/slices\|docs/research" --exclude-dir=.git` covers AGENTS.md, the backlog itself (its "Finding things" greps **and** the `evidence:` links in the M16/M17/M18 rows), `slices/_TEMPLATE.md`, `adr/0001` (lifetime-taxonomy text), the research docs' own titles, SL-015, `.gitignore` comments |
| `CONTRIBUTING.md` | GitHub community file | Absent | The human-facing counterpart of the bootstrap: dev loop, gate command, commit conventions, PR expectations |
| `SECURITY.md` | GitHub community file | Absent | Near-mandatory for a tool that reads credential stores — where to report a vuln privately |
| `CODE_OF_CONDUCT.md` | GitHub community file | Absent | Decision — textual has one; uv/ruff ship without |
| `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md` | GitHub community file | Absent | Decision — all three reference repos carry them |
| `CODEOWNERS`, `SUPPORT.md`, `FUNDING.yml` | GitHub community file | Absent | Likely overkill for a solo-maintainer repo — decide explicitly, don't drift |
| `CHANGELOG.md` | Keep a Changelog | Absent | Already planned: semantic-release generates it at M18 — verify PSR's emitted format is KAC-compatible at that PRD |
| `README.md` | GitHub profile | Install/Commands/Docs/Acknowledgments | Audit at M15: one-line description, badges (CI/license/PyPI — Actions badge only renders usefully once public), docs-site link after M17 |
| `docs/backlog.md`, `docs/slices/`, `docs/research/` | bespoke lifetime-split (ADR-0001) | Working | No external convention governs maintainer process docs — keep, audit for fluff only |

## Standardization rules the PRD should pin

- **One fact per row, one idea per section** — the repo's existing grep-first
  style is already a recognized pattern (docs written to be grepped); keep it
  and apply it to any new file.
- **Every durable doc must answer its arc42/MADR/Diátaxis type** — a reader
  should be able to name which quadrant/section a doc is; hybrid docs get
  split or rehomed.
- **No fluff**: a sentence that doesn't carry a fact, an instruction, or a
  decision criterion is deleted in the audit pass.
- **Deviations are stated, not silent** — where this repo departs from a
  convention it claims (arc42 section order, MADR headings), the doc itself
  says so in one line.

## Decisions deferred to the M15 PRD

1. arc42: add §7 Deployment + §12 Glossary (even minimal) vs. record a
   standing deviation at the top of `architecture.md`.
2. MADR: adopt upstream heading names + frontmatter, or keep the simplified
   template and rename the claimed convention.
3. Community files: CONTRIBUTING.md + SECURITY.md look mandatory; CoC, issue
   templates, PR template, CODEOWNERS, FUNDING, SUPPORT each need an explicit
   yes/no with a one-line reason.
4. Skill mechanics for `next-task`: `allowed-tools` auto-approvals (git
   log/status + reads are the obvious set), `model` pin, `subagent:` never —
   the bootstrap must run inline.
5. Badge set for README once public (CI status, license; PyPI only after M18).
6. Whether `dev/` is the final process-dir name vs. `meta/`/`maintainer/` —
   `dev/` is short and reads "for developing this project"; confirm before the
   move since every grep in the repo references it after.
