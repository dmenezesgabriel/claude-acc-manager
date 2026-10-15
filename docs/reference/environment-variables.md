# Environment variables

## cam-specific

| Variable | Does |
| --- | --- |
| `CAM_ASSUME_CLAUDE_CONTRACT` | Set to `1` to skip the claude-version contract gate on mutating commands. The gate exists because cam interoperates with claude's on-disk layout; bypassing it is for when you have verified a newer claude yourself. Read the refusal message before reaching for this |
| `CAM_DISABLE_UPDATE_CHECK` | Any non-empty value skips the PyPI release check on every surface (post-command notice, TUI toast, `auto` event line); it overrides `updates.mode` |

## Claude Code interop

| Variable | Does |
| --- | --- |
| `CLAUDE_CONFIG_DIR` | Where cam looks for the live claude login. Also what `cam add` isolates per account: each registered account is a real `CLAUDE_CONFIG_DIR` under the cam store |
| `CLAUDE_SECURESTORAGE_CONFIG_DIR` | claude's own credential-store override; cam honors it verbatim: when defined it wins over `CLAUDE_CONFIG_DIR`, and defined-but-empty means `~/.claude` |

## Paths

| Variable | Does |
| --- | --- |
| `XDG_DATA_HOME` | Root of the cam store (`$XDG_DATA_HOME/claude-acc-manager/`, default `~/.local/share/claude-acc-manager/`): `registry.json`, `accounts/`, `usage-cache.json`, `settings.json`, `auto-state.json`, `update-check.json`, lock files |
| `UV_TOOL_DIR` | uv's relocated tool root; `cam upgrade` honors it when detecting a uv-installed cam |
| `PIPX_HOME` | pipx's relocated venv root; `cam upgrade` honors it when detecting a pipx-installed cam |

## Display

| Variable | Does |
| --- | --- |
| `NO_COLOR` | Disables color in human output (honored via rich); `--json` output is never colored |
| `TERM` | `TERM=dumb`/`unknown` marks the terminal non-interactive: bare `cam` prints usage instead of opening the TUI, and text output degrades to plain |
