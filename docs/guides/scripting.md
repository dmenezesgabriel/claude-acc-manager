# Scripting with `cam`

Every machine-readable surface is `--json` with the
[schema-v1 contract](../reference/json-output.md): pure JSON on stdout,
humans channels on stderr, the error envelope (not a crash dump) on handled
failures.

## Shell patterns

Branch on the exit code first, parse second:

```sh
if cam status --json | jq -e '.active.managed'; then
  echo "live login is managed by cam"
fi
```

```sh
# headroom of every enabled account, worst first
cam list --json | jq -r '
  .accounts[] | select(.enabled) |
  [.name, (.usage.fiveHour.pct // "n/a")] | @tsv' | sort -k2 -rn
```

```sh
# which setting is overriding the default?
cam config list --json | jq '.settings[] | select(.isSet)'
```

```sh
# scheduled evaluation — outcomes are exit codes, not text
cam auto --once
case $? in
  0) echo "switched" ;; 3) echo "wanted to switch but blocked" ;;
esac
```

## Streaming the auto loop

`cam auto --json` is JSONL — one event object per line. Filter by `event`:

```sh
cam auto --json | while IFS= read -r line; do
  jq -e '.event == "switch"' <<<"$line" >/dev/null && \
    notify-send "cam switched" "$(jq -r '.to' <<<"$line")"
done
```

Unknown `event` kinds and unknown fields are part of the contract —
consumers ignore them so additive releases never break a parser.

## Stability rule

`schemaVersion` bumps only on breaking changes. New fields arrive silently
inside `1` — write parsers that accept, not parsers that enumerate.
