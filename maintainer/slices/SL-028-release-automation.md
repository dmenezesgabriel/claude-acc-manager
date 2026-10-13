# SL-028 — one-click release cut driven by conventional commits

Milestone: M28 · State: in-progress · Depends on: — · Closes: —

## Outcome

One sentence: merging a `feat`/`fix` PR to main produces a ready-to-approve PyPI release with zero terminal commands — the only human act is the `pypi` environment approval that already exists.

## Exit gate

`uv run pre-commit run --all-files` clean (zizmor pedantic + actionlint cover the new workflows) · then the live-fire validation below, which needs the maintainer's one-time setup (§ Maintainer setup).

1. Maintainer completes § Maintainer setup (app, secrets, auto-merge toggle).
2. A `chore`/`docs`-only merge to main: `release-cut` runs, psr finds no bump, exits 0, no PR appears.
3. A `fix`/`feat` merge to main: `release-cut` opens or updates the `release/next` → `main` PR; its nine checks run (app token = real actor); auto-merge lands it; `release-tag` pushes the annotated `v*` tag; `release.yml` builds + GH-Releases + TestPyPIs; `deploy` waits on `pypi` approval — approve → PyPI.
4. `workflow_dispatch` on `release.yml` with `ref=v1.2.0` re-runs the pipeline against the existing tag without a new release.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `research_repos/claude-swap/.github/workflows/publish.yml` | `release: published` event → build + `pypa/gh-action-pypi-publish` — the human does every upstream step |
| ai-usagebar | PARTIAL | `research_repos/ai-usagebar/.github/workflows/release.yml` | tag push + `workflow_dispatch`(ref) → `verify-version` gate → matrix build → GH Release → crates/AUR publishes; maintainer still hand-cuts the tag per its CLAUDE.md checklist |
| toad | ABSENT | — | no `.github/workflows/` — FUNDING + ISSUE_TEMPLATE only |
| claude-code itself | — | n/a | closed source, nothing to interoperate with |

**Count:** 0 of the references automate the cut; 2 automate post-tag publish. The derivation is not invented — `pyproject.toml [tool.semantic_release]` already owns version math/changelog/build; this milestone automates its invocation (the release-please/semantic-release-bot ecosystem pattern), and keeps both human gates the references lack anyway.

## Implementation inventory

### ai-usagebar

| Concern | Files |
| --- | --- |
| Trigger shape (tag push + dispatch-with-ref) | `research_repos/ai-usagebar/.github/workflows/release.yml` `on:` block (~line 3–11) |
| Tag hygiene asserts (annotated tag, tag-on-main, manifest agreement) | same file, `verify-version` job (~lines 21–83) — our `release.yml` already ports the manifest half; adopt annotated-tagging in the tag job |
| Idempotent publish (already-exists → warn, not fail) | same file, `publish-crates-io` (~lines 361–384) |
| Secret-presence degrade (missing key → skip, not fail) | same file, `publish-aur` `aur_key` check (~lines 424–433) |

### claude-swap

| Concern | Files |
| --- | --- |
| Minimal publish surface (GH-Release-event → publish only) | `research_repos/claude-swap/.github/workflows/publish.yml` — counter-evidence for "no automation is normal"; our bar is already higher |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Bot actor | PAT (claude-swap-style secrets) · GitHub App (`create-github-app-token`) | PAT is user-scoped and static; app is repo+permission scoped and minted per run | **App** — smallest credential surface that beats GITHUB_TOKEN event suppression (research §The wall) |
| Cut trigger | `workflow_dispatch` only · `push: [main]` standing-PR (release-please model) | dispatch = one click per release; standing PR = zero clicks, PR always fresh | **Both** — push keeps it automatic, dispatch is the manual "cut now" escape hatch |
| Release branch | computed `release/vX.Y.Z` per release · fixed `release/next` | computed names pile up open PRs on drift; fixed name gives one standing PR, force-pushed as bumps recompute | **`release/next`** — bot-owned, force-push is the designed mechanism |
| Merge | human clicks merge · auto-merge armed by the app | click is one more human step; auto-merge still passes through the nine required checks | **auto-merge** — checks remain the gate; repo toggle enabled once by maintainer |
| Tag timing | tag in the cut job · tag on `pull_request.closed` | tagging at cut time tags an unmerged commit | **`pull_request.closed` on `merge_commit_sha`** — race-free, fires only for merged `release/*` heads |
| Tag style | lightweight (`git tag`, our v1.1.0/v1.2.0 habit) · annotated (`git tag -a`, ai-usagebar's verify-version requirement) | annotated carries tagger+message; lightweight is a bare ref | **annotated** — adopt the stronger reference habit |
| Missing app secrets | fail the run · warn + exit 0 | a fork or an unconfigured repo should not go red | **warn + exit 0** — ai-usagebar's `aur_key` degrade pattern |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Version derivation + changelog | `pyproject.toml [tool.semantic_release]` — complete, maintainer-invoked | none (references don't derive) | complete config; invocation is manual — automate it |
| Release commit path | maintainer-local `release/*` branch + PR (documented in `.github/workflows/release.yml` header) | — | correct shape already; needs a bot actor to run it in CI |
| Post-tag pipeline | `.github/workflows/release.yml` — build + assert + GH Release + TestPyPI + reviewer-gated PyPI | `research_repos/ai-usagebar/.github/workflows/release.yml` | complete; missing only `workflow_dispatch`+`ref` rebuild input |
| Tag trigger | maintainer `git push origin v*` | ai-usagebar tag asserts | absent in CI — needs `release-tag.yml` |

## Deviations

- Standing `release/next` PR instead of release-please's per-version branch names — the fixed name keeps exactly one PR alive and the force-push keeps it honest; recorded here, dies with the milestone.
- No `verify-version`-style annotated-tag assert added to our `release.yml` — ai-usagebar needs it because humans tag by hand and slip; our tag job always annotates. If a manual tag ever re-enters the flow, reassess.

## Open decisions

- Whether `release-cut` should also fire on `push: [main]` (chosen) vs dispatch-only — chosen both; if the per-push run proves noisy it can be narrowed to dispatch without losing the design.

## Maintainer setup (one-time, cannot be done in-session)

1. `github.com/settings/apps/new` → app `cam-release` (or similar): webhook off; permissions `Contents: Read & write`, `Pull requests: Read & write`. Generate + download private key.
2. Install the app on `dmenezesgabriel/claude-acc-manager` only.
3. Repo → Settings → Secrets and variables → Actions: variable `CAM_RELEASE_CLIENT_ID` (the app's OAuth Client ID — public identifier per create-github-app-token README), secret `CAM_RELEASE_APP_PRIVATE_KEY`.
4. Repo → Settings → General → Pull Requests: enable auto-merge (or `gh repo edit --enable-auto-merge`).

## Surface

| Layer | Files |
| ----- | ----- |
| workflows | `.github/workflows/release-cut.yml` (new), `.github/workflows/release-tag.yml` (new), `.github/workflows/release.yml` (dispatch input + comment refresh) |
| maintainer docs | `maintainer/research/release-automation.md` (evidence), this PRD |

## Tasks

- [x] T1 — `ci(release): release-cut workflow — app-token psr cut to standing release/next PR` (4518cbc)
- [x] T2 — `ci(release): tag merged release PRs on merge_commit_sha` (457a9db)
- [x] T3 — `ci(release): workflow_dispatch ref input + tag hygiene asserts on release.yml` (55902b7)
- [ ] T4 — maintainer setup + live-fire per § Exit gate (records numbers in closing commit body)

## Out of scope

- Removing the `pypi` environment reviewer (that is option C — a deliberate posture decision, not automation plumbing).
- Ruleset bypass actors (the app works through the PR gate, not around it).
- Commitizen — a commit-formatting helper, orthogonal to release machinery; the `commit-msg` hook already enforces conventional format.
