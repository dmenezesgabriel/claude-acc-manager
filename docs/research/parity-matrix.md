# Parity matrix — capability × { claude-swap, ai-usagebar, cam }

**Ephemeral.** Construction scaffolding: deleted when M9 ships and the matrix reads all-FULL for in-scope rows. Each `GAP-NNN` names the backlog milestone that closes it; grep `GAP-` to list them all.

## Method and limits

- cam column: measured against `src/` + `docs/backlog.md` milestone states on 2026-10-01 (M0–M5 shipped).
- Reference columns: read from `research_repos/claude-swap` (v0.27.0b1) and `research_repos/ai-usagebar` (v1.14.0) source; `FULL` means the capability is implemented, whatever the mechanism.
- Scope filter: non-goal capabilities (macOS keychain, menubar, export/import, session merging, API-key accounts — architecture §11) are excluded; absence there is deliberate, not a gap.

## Matrix

| Capability | claude-swap | ai-usagebar | cam today | Gap |
| --- | --- | --- | --- | --- |
| Register account (login lands in the account's own dir) | FULL (`add`, `--add-token`) | FULL (`account add` via `CLAUDE_CONFIG_DIR`) | FULL — `cam add` | — |
| Remove account + its login dir | FULL | FULL | FULL — `cam remove` | — |
| List accounts with active marker | FULL | FULL | FULL — `cam list` | — |
| Show which account the live slot uses | FULL (`status`) | FULL (`account status`) | FULL — `cam status` | — |
| Per-account usage fetch + cache + poll budget | FULL (`usage_store.py`, `poll_policy.py`) | FULL (`anthropic/`, `cache.rs`) | FULL — `cam usage`, `FetchAccountUsage`, `FileUsageCache` | — |
| On-demand refresh of inactive tokens | FULL | FULL | FULL (active slot never refreshed — ADR-0009) | — |
| Identity oracle: classify a credential via profile GET | FULL (`/api/oauth/profile`) | PARTIAL (account registry is label-based; no oracle verified) | FULL — `AnthropicIdentityLookup` | — |
| Swap the live `claude` login (transaction under claude-code locks, outgoing captured, rollback) | FULL (`switcher.py`) | FULL (`account switch` → `switch_cli_account`, incl. `--dry-run`) | **ABSENT** | GAP-001 → M6 |
| Quota-driven target selection (`best`, `next-available`) | FULL (`_select_best_switchable`) | ABSENT (switch is by label only) | **ABSENT** | GAP-001 → M6 |
| Enable/disable account without removing it | FULL (`enable`/`disable`) | — | PARTIAL — `AccountStorePort.set_enabled` exists; no use case, no command | GAP-002 → M6/M7 |
| Quarantine `invalid_grant` lineages from auto-pick | FULL (`autoswitch.py`) | — | PARTIAL — `FetchAccountUsage` raises the signal; registry `quarantined` field exists but nothing writes it | GAP-003 → M6/M9 |
| Unattended auto-switch loop (threshold, cooldown, hysteresis, SIGTERM) | FULL (`autoswitch.py`) | — | **ABSENT** | GAP-004 → M9 |
| Urgent-mode / escalation-margin poll policy | FULL | — | **ABSENT** (threshold-independent core only; deferred — user decision 2026-09-10) | GAP-004 → M9 |
| TUI dashboard | FULL (`tui/`) | n/a (it *is* a status bar; different surface) | **ABSENT** — `textual` pinned, no `tui/` yet | GAP-005 → M8 |
| `--json` output contract | FULL (`json_output.py`) | PARTIAL (`status --json`) | **ABSENT** — plain text only today | GAP-006 → M7 |
| Root-execution refusal | — | — | **ABSENT** (planned safety rule, architecture §8.6) | GAP-006 → M7 |
| Persisted settings (threshold/interval/cooldown/strategy) | FULL (`settings.py` + `settings` subcommands) | FULL (`config.toml`) | **ABSENT** — `settings.json` specified, unwritten | GAP-007 → M9 |

## Deliberately absent (not gaps)

| Item | Why |
| --- | --- |
| `extra_usage` credits axis | On the wire, unparsed by design — no consumer yet ([ADR-0012](../adr/0012-schema-tolerant-usage-model.md)) |
| `--dry-run` on switch | ai-usagebar has it; candidate for M6 scope decision — record the choice in the M6 PRD |
| menubar / export / import / aliases / mappings / session merge | v1 non-goals (architecture §11) |
