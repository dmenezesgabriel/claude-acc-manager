# R1 — release automation evidence for M28

Ephemeral build evidence for SL-028; deleted when M28 ships. Verified 2026-10-13 in this session.

## The wall that dictates the design

| Fact | Consequence for M28 |
| --- | --- |
| `GITHUB_TOKEN`-authored events never trigger new workflow runs (except `workflow_dispatch`/`repository_dispatch`) — GitHub's documented anti-recursion rule | A bot-pushed release branch gets **zero** check runs → required checks stay "Expected" → the PR is unmergeable even by a human (the documented `peter-evans/create-pull-request` pitfall). A bot-pushed tag does **not** fire `release.yml`'s `push: tags` trigger. An app token is a real actor — every event fires normally. |
| Default-branch ruleset `main required checks`: zero bypass actors (verified via `gh api repos/…/rulesets` today) | `GITHUB_TOKEN` cannot push to main at all — the release commit must ride a PR, which the ruleset then gates. No bypass is added; the app works *through* the PR path, not around it. |
| Repo setting `enablePullRequestAutoMerge` is off (verified via `gh pr merge --auto` → GraphQL error today) | `gh pr merge --rebase --auto` cannot arm until the maintainer enables it — one checkbox in Settings → General. |
| Auto-merge attribution: the merge lands under the actor who armed it | Arming with the app token makes the merge a real-actor push → main-branch CI fires normally (coverage + mutmut cache banking, which ci.yml's sha-keyed concurrency protects). A GITHUB_TOKEN-armed merge would suppress that run. |
| `pypi` environment has a required reviewer (observed blocking deploy on run 38457735370 today) | Publish stays human-gated regardless of cut automation — the last gate survives every option. |

## Who else implements this

| Repo | Release automation | Files |
| --- | --- | --- |
| ai-usagebar (v1.14.0) | Tag-triggered build+publish only; maintainer hand-bumps, hand-changelogs, hand-tags (its CLAUDE.md is a 9-step manual checklist). Adds `workflow_dispatch` + `ref` input to rebuild an existing tag — worth porting to our `release.yml`. | `research_repos/ai-usagebar/.github/workflows/release.yml` (~line 6 `workflow_dispatch`, lines 21–83 `verify-version` incl. annotated-tag + on-main assertions) |
| claude-swap (v0.27.0b1) | `on: release: types: [published]` — human creates the GH Release, CI only builds + publishes. No version derivation anywhere. | `research_repos/claude-swap/.github/workflows/publish.yml` |
| toad (v0.6.20) | No `.github/workflows/` at all (FUNDING + ISSUE_TEMPLATE only). | — |
| claude-code itself | n/a — closed source, no public release pipeline to interoperate with. | — |

Zero of three references automate the cut. The capability is an ecosystem-standard one (release-please / semantic-release bot flows), not an invention: `pyproject.toml [tool.semantic_release]` already carries the version math, `tag_format`, `commit_message`, and `build_command` — M28 automates its invocation, not its semantics.

## The actor: GitHub App over PAT

| Axis | PAT | GitHub App |
| --- | --- | --- |
| Blast radius | All repos the user can reach, every scope granted | Repo-scoped install, permission-scoped grants (contents+PR write only) |
| Event triggering | Real actor — works | Real actor — works |
| Revocation | Password-like rotation | Suspend/uninstall the install |
| Minting | Static secret | `actions/create-github-app-token` per-run, token lives minutes |

Choice: app, `actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1` — pinned SHA for v3.2.0 (published 2026-05-12, >7 days; v3.3.0 shipped 2026-10-12, too fresh per the dependency rule).

## Shape

```
push → main   ─┐
               ├─ release-cut.yml ── app token ── psr version (no bump → exit 0)
dispatch ──────┘        │ branch release/next force-pushed, PR opened/updated,
                        │ auto-merge armed ── nine checks gate it
                        ▼
              PR merged → release-tag.yml ── app token ── git tag -a v$(pyproject)
                        │ on merge_commit_sha, pushed as the app
                        ▼
              release.yml on push tags (or workflow_dispatch ref) — unchanged pipeline
                        ▼
              pypi environment approval ← the surviving human act
```

Edge cases settled:

- **Self-triggering**: the release commit landing on main re-fires `release-cut` — psr finds no bump (`chore(release)` is non-bumping) and exits 0. No loop.
- **Standing PR drift**: another main merge while a release PR waits → next `release-cut` run force-pushes the rebased, recomputed commit; auto-merge re-arms. Bot-owned branch, force-push is the designed mechanism.
- **Race**: tag job tags `pull_request.merge_commit_sha`, never "main" — a later main push cannot mispoint the tag.
- **Forks**: write-capable jobs keep `github.repository == 'dmenezesgabriel/claude-acc-manager'` (release.yml's existing guard).
- **Annotated tag**: `git tag -a` — ai-usagebar's verify-version rejects lightweight tags; we adopt the habit even though our release.yml doesn't (yet) require it.
