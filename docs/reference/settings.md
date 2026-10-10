# Settings reference

Persisted settings live in `settings.json` inside the cam store
(`cam config path` prints the exact location — `$XDG_DATA_HOME/
claude-acc-manager/settings.json` by default). Every key is managed through
`cam config`; hand edits are tolerated — out-of-range values clamp into
bounds, wrong types revert to defaults, unknown keys are preserved.

Five keys tune the `cam auto` engine; one controls display privacy:

| Key | Type | Default | Bounds | Meaning |
| --- | --- | --- | --- | --- |
| `autoswitch.threshold` | float | `90.0` | 50–99.9 | Switch when the active account's binding window (max of 5h/7d utilization) reaches this pct |
| `autoswitch.intervalSeconds` | float | `60.0` | 15–3600 | Poll interval of the `cam auto` loop |
| `autoswitch.cooldownSeconds` | float | `300.0` | 0–86400 | Minimum seconds between proactive switches |
| `autoswitch.hysteresisPct` | float | `10.0` | 0–50 | A `best` candidate must beat the active account by this margin — near-line pairs can't ping-pong |
| `autoswitch.strategy` | choice | `best` | `best`, `next-available` | How the engine picks the target account |
| `privacy.redactEmails` | bool | `true` | `true`, `false` | Drop account emails from the TUI and human CLI output so screenshots stay safe; `p` toggles it live in the TUI. `--json` payloads always carry the real email |

## CLI

```text
cam config list              # every key: effective value, explicitly set?
cam config get <key>         # bare value — scripts cleanly
cam config set <key> <value> # strict: out-of-bounds or mistyped fails loudly
cam config unset <key>       # revert to default
```

`cam auto` flags (`--threshold`, `--interval`, `--cooldown`, `--strategy`)
override the persisted value for that run only — they never write the file.
