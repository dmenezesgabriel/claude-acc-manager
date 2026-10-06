# JSON output — schema-v1

`--json` makes a command emit one JSON object on stdout instead of the
human render. Every payload carries `"schemaVersion": 1`; the version only
bumps on a breaking change, and fields are additive — **consumers must
ignore unknown keys**.

stdout stays pure JSON: progress and warnings go to stderr, and handled
failures emit the error envelope on stdout (so piped consumers always get
parseable JSON on handled errors).

## Error envelope

```json
{
  "schemaVersion": 1,
  "error": { "type": "ValueError", "message": "…" }
}
```

`error.type` is the stable tag to match on: `KeyError` (unknown account),
`ValueError` (validation), `UnsupportedClaudeVersion` (contract gate),
`TimeoutError` (lock bound exceeded), `RootRefused` (euid 0 outside a
container). Exit code is `1` for all of them.

## Per-command payloads

`cam list --json` — registry rows plus cached usage:

```json
{
  "schemaVersion": 1,
  "active": "work",
  "accounts": [
    {
      "name": "work", "email": "…", "accountUuid": "…",
      "organizationUuid": "…", "organizationName": "…",
      "isOrganization": true, "active": true, "enabled": true,
      "quarantined": false,
      "usageStatus": "ok", "usage": { … }, "usageFetchedAt": "…", "usageAgeSeconds": 12.3
    }
  ]
}
```

`cam status --json` — the live login: `{"schemaVersion": 1, "active": null}`
when no claude login exists; otherwise `active` holds identity fields plus
`managed` (in cam's registry?) and, when managed, `managedAs` and the same
usage fields as a `list` row.

`cam usage <name> --json`:

```json
{
  "schemaVersion": 1, "account": "work",
  "usageStatus": "ok | unavailable | relogin_required",
  "usage": null,
  "stale": false, "usageError": null,
  "permanentAuthError": false, "quarantined": false
}
```

`usage` is `{"fiveHour": {"pct": …, "resetsAt": …}, "sevenDay": {…},
"scoped": [{"name": …, "pct": …}]}` or `null`. Rows without trusted usage
may carry display-grade `lastGoodUsage`/`lastGoodFetchedAt`/
`lastGoodAgeSeconds`; rows in backoff carry `usageRetryAt`.

`cam switch --json` — the transaction result: `dryRun`, `switched`,
`outcome`, `from`/`to` as `{"name", "email"}` or `null`, `unmanagedLive`,
`preservedTo`, `strategy`, `skipped` (`[{"name", "reason"}]`),
`quarantined`, `message`.

`cam config get/list --json` — `{"key", "value", "isSet"}` for one key, or
`{"path", "settings": [{"key", "value", "isSet"}]}` for the full table.

## `cam auto --json` — JSONL events

The loop can't stream one dict, so it emits one object per line:

```json
{"schemaVersion": 1, "event": "poll", "ts": "…", "active": "work", "headroomPct": 12.3, "threshold": 90.0}
{"schemaVersion": 1, "event": "switch", "ts": "…", "trigger": "…", "from": "work", "to": "personal", "dryRun": false}
```

`event` is one of `poll`, `switch`, `no_switch`, `quarantined`,
`all_exhausted`, `sleep`, `error`; the remaining fields are per-kind.
Consumers must ignore unknown `event` kinds and unknown fields.
