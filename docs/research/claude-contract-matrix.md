# Claude-version contract matrix (R-session evidence for M10)

Ephemeral — delete when M10 ships. Every claim cites the artifact and the check used; all paths verified with `test -e` today (2026-10-03).

Artifacts on disk:

- `research_repos/claude-swap` (v0.27.0b1), `research_repos/ai-usagebar` (v1.14.0) — reference sources.
- `/tmp/claude-versions/ext-<v>/package/cli.js` — npm JS bundles: 0.2.126, 1.0.128, 2.0.77, 2.1.0, 2.1.50, 2.1.70–2.1.110 (several).
- `/tmp/claude-versions/nat-<v>/package/bin/claude` or `.../claude` — linux-x64 native binaries via `npm pack @anthropic-ai/claude-code-linux-x64@<v>`: 2.1.120, 2.1.129, 2.1.131, 2.1.133, 2.1.136, 2.1.140, 2.1.142–2.1.145, 2.1.150, 2.1.218, 2.1.250, 2.1.288.
- `~/.local/share/claude/versions/{2.1.284,2.1.285,2.1.286,2.1.287}` — installed native binaries (2.1.288 local file is a 0-byte staged download; active symlink → 2.1.287).
- Deleted SL-010 PRD (`git show f513bba^:docs/slices/SL-010-credential-write-boundary.md`) — prior band matrix + strace/bunfs method.

## Contract-feature introduction versions (linux-x64, grep-pinned)

| Feature | First existing version carrying it | Evidence |
| --- | --- | --- |
| `.oauth_refresh.lock` | ≤2.1.70 in cli.js; absent ≤2.1.50 | `grep -c oauth_refresh` ext-2.1.50=0, ext-2.1.70=1, nat-2.1.120=3 |
| `.storage-write` | 2.1.136 (absent 2.1.133) | `grep -ac storage-write`: nat-2.1.133=0, nat-2.1.136=2 |
| `CLAUDE_SECURESTORAGE_CONFIG_DIR` (wS) | 2.1.144 (absent 2.1.143) | `grep -ac SECURESTORAGE_CONFIG_DIR`: nat-2.1.143=0, nat-2.1.144=5 |
| refresh-lock `stale:60000,update:5000` | (2.1.150, 2.1.218] | `.oauth_refresh.lock` ctx: `stale:1e4` in nat-2.1.144/.150, `stale:60000,update:5000` in nat-2.1.218/.250 |
| native-binary packaging (no cli.js) | mixed zone 2.1.60–2.1.150; fully native ≥2.1.150 | `ls ext-<v>/package/cli.js` presence per version |
| `claude auth status` / `auth login` / `/login` | ≤0.2.x | `grep` in ext-0.2.126 cli.js |
| `claude setup-token` | ≤1.0.x | `grep` in ext-1.0.128 cli.js (absent 0.2.126) |
| `.design_oauth_refresh.lock` (unrelated new OAuth flow) | ≤2.1.218 | literal in nat-2.1.218 (absent 2.1.150) |

**Full contract (wS + dXr + nKo together) exists from 2.1.144.** Versions 2.1.0–2.1.143 each lack a different subset of it.

## Stable across the contract era (2.1.144 → 2.1.288)

| Seam | Verified | Evidence |
| --- | --- | --- |
| wS() semantics: `CSSCD !== undefined → (CSSCD || ~/.claude).normalize("NFC")`, else `CCD || ~/.claude` | identical at 2.1.144 (`function Ia(){let H=process.env.CLAUDE_SECURESTORAGE_CONFIG_DIR;if(H!==void 0)return(H||scq.join(QU$.homedir(),".claude")).normalize("NFC");return n8()}`) and 2.1.287 (SL-010) | context grep on binaries |
| `.storage-write` lock options | identical `{realpath:!1,retries:{retries:10,minTimeout:100,maxTimeout:1000},stale:15000}` at 2.1.144/.150/.218/.250 | context grep |
| `.oauth_refresh.lock` location `<wS()>`, `realpath:!1` | 2.1.144→.250 | context grep |
| `--version` output `X.Y.Z (Claude Code)` | all bands (cli.js-era per SL-010; native 2.1.284–2.1.288 run locally) | `<bin> --version` |
| Schema literals `claudeAiOauth`, `accessToken`, `refreshToken`, `expiresAt`, `oauthAccount`, `emailAddress`, `accountUuid`, `organizationUuid`, `hasCompletedOnboarding` | present 2.1.144–2.1.288 | `grep -ac` counts (grow, never vanish) |
| Endpoint literals `api/oauth/usage`, `api/oauth/profile`, `platform.claude.com`, client_id `9d1c250a`, beta `oauth-2025-04-20` | present 2.1.144–2.1.288 | `grep -ac` |
| `auth status` JSON shape `{loggedIn,authMethod,apiProvider,configDirectory,email,orgId,orgName,...}` | 2.1.287 (live `claude auth status`, no API call) | live run |
| `auth login`/`setup-token`/`hasCompletedOnboarding` commands+flags | present ≥2.1.144 | `grep -ac` |

## Drift inside the 2.1.x band (why bands must be re-verified, not assumed)

- `.oauth_refresh.lock` staleness: `stale:1e4` (10s, no heartbeat) at 2.1.144–2.1.150 → `stale:60000,update:5000` (60s + 5s touch) by 2.1.218. cam's `CREDENTIALS_STALENESS_S=60` is safe-direction both ways (cam never steals an upstream-live lock; its own 3s touch beats upstream's 10s floor) but proves **patch releases change lock semantics**.
- New lock artifacts appear mid-band: `.design_oauth_refresh.lock` (2.1.218+).
- The env-var surface grows every release (hundreds of `CLAUDE_*`/`ANTHROPIC_*` reads in 2.1.288).

## Env-var hazard surface vs cam's launcher strip list (2.1.288 binary)

cam strips: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR`, `CLAUDE_SECURESTORAGE_CONFIG_DIR`. All six still read by 2.1.288 ✓.

Credential-supply / endpoint-redirect / wrong-slot vars 2.1.288 reads that cam does **not** strip:

| Var | Class | Why it matters to `cam add` |
| --- | --- | --- |
| `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_GB_BASE_URL`, `ANTHROPIC_BEDROCK_BASE_URL`, `ANTHROPIC_VERTEX_BASE_URL`, `ANTHROPIC_FOUNDRY_BASE_URL`, `ANTHROPIC_GOOGLE_CLOUD_BASE_URL`, `ANTHROPIC_MEMORY_API_BASE_URL` | endpoint redirect | OAuth/API traffic could leave Anthropic hosts |
| `CLAUDE_LOCAL_OAUTH_*` (`API_BASE`,`APPS_BASE`,`CONSOLE_BASE`), `USE_LOCAL_OAUTH` | endpoint redirect | local-OAuth override — login lands elsewhere |
| `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`, `CLAUDE_CODE_SESSION_ACCESS_TOKEN`, `CLAUDE_CODE_OAUTH_CLIENT_ID`, `CLAUDE_CODE_OAUTH_SCOPES` | credential supply | pre-seeded tokens bypass or skew the login |
| `ANTHROPIC_IDENTITY_TOKEN`, `ANTHROPIC_IDENTITY_TOKEN_FILE`, `CLAUDE_TRUSTED_DEVICE_TOKEN`, `CLAUDE_SESSION_INGRESS_TOKEN_FILE`, `CLAUDE_CODE_GATEWAY_TOKEN`, `CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_HFI_BEARER_TOKEN`, `CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR` | credential supply | alternate auth material |
| `ANTHROPIC_CONFIG_DIR`, `ANTHROPIC_PROFILE`, `CLAUDE_CODE_FEDERATION_CACHE_DIR` | wrong-slot redirect | drives the federation store (`de()`: `ANTHROPIC_CONFIG_DIR || XDG_CONFIG_HOME/anthropic`), not `claudeAiOauth` — a login could land outside `.credentials.json` |
| `CLAUDE_CODE_USER_EMAIL`, `CLAUDE_CODE_ORGANIZATION_UUID`, `CLAUDE_CODE_SUBSCRIPTION_TYPE`, `CLAUDE_CODE_RATE_LIMIT_TIER` | identity injection | skews captured identity claims |
| `CLAUDE_CODE_HOST_AUTH_ENV_VAR`, `CLAUDE_CODE_HOST_CREDS_FILE`, `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, `CLAUDE_CODE_REMOTE_TOOLS_PIN_STORED_LOGIN` | credential supply | host-managed credentials |
| `CLAUDE_ENV_FILE` | indirect injection | loads additional env vars from a file |
| `ANTHROPIC_CUSTOM_HEADERS` | request injection | arbitrary headers on API calls |

Also read but benign-to-cam (not stripped, keep passing): `CLAUDE_CONFIG_DIR` (cam sets it), `HOME`, `XDG_CONFIG_HOME`, proxy vars, `PATH`-style process vars.

## Reference-repo positions on versions

| Repo | Position | Files |
| --- | --- | --- |
| claude-swap | mirrors wS() for reads; **refuses to operate under a set CSSCD** ("store-unmirrored"); uses `claude auth status` as a local-only login check | `src/claude_swap/credentials.py`, `src/claude_swap/session.py` (~lines 200, 822, 955) |
| claude-swap | detects live claude sessions via `sessions/{pid}.json` + `ide/{port}.lock` (the mechanism cam does **not** adopt — floor ≥2.1.144 gives lock interop instead) | `src/claude_swap/process_detection.py` |
| ai-usagebar | `CLAUDE_CONFIG_DIR` account model only; **zero version awareness** — no probes, no gates | `src/config.rs`, `src/anthropic_api/` |

## What the matrix means for cam (gap list for the PRD)

| Seam | cam today | Contract evidence | Gap |
| --- | --- | --- | --- |
| Version floor | `MIN_SUPPORTED=(1,0,0)` at `cam add` only | full contract exists only ≥2.1.144; 2.1.0–.143 each lack a different subset | floor wrong and enforced only on the add path |
| Unknown versions | no check at all | band drift is real (staleness flip, new locks, native packaging) | `≥2.2` proceeds silently on every command |
| Mutating-op gating | none outside `add` | lock interop is the only thing protecting `.credentials.json` writes | `switch`/`usage`-refresh/`auto` run unverified |
| Probe failure | `add` returns False (indistinct error) | fail-closed doctrine chosen for M10 | need distinct error + dispatch mapping |
| Launcher env | 6-var strip list | ≥9 classes of redirect/supply vars in 2.1.288 (table above) | scoped login can be hijacked by ambient env |
| Contract knowledge | scattered literals in 4 files (path_resolver, claude_locks, launcher) | one version → one contract | no single band model; no re-verification procedure |
| `auth status` | unused | JSON probe exists ≥0.2.x; `configDirectory` self-report on 2.1.287 (shape on 2.1.144 binary not grep-verified — field name may differ pre-`configDirectory` introduction) | optional upgrade, not adopted for the gate |
