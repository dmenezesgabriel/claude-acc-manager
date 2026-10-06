# Security Policy

`cam` reads and writes Claude Code OAuth credential stores — `~/.claude/.credentials.json` and the per-account copies under `$XDG_DATA_HOME/claude-acc-manager/`. Credential-hygiene defects — tokens landing in logs, argv, or error bodies; wrong file modes; a write that strands a refresh-token lineage — are the highest-priority bug class in this project.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

- Once the repository is public, use GitHub private vulnerability reporting: the repository's **Security** tab → **Report a vulnerability**.
- If that channel is unavailable, contact the maintainer through the GitHub profile that owns this repository.

Include what you observed, the versions (`cam --version`, `claude --version`), and a minimal reproduction. Never include real access tokens, refresh tokens, or credential-file contents in a report.

## Scope and expectations

- The latest release and `main` are in scope; older releases are not patched.
- Reports are acknowledged within a few days. Fixes land as ordinary commits; a GitHub security advisory is published once a fixed release exists.
