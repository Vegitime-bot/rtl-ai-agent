# Claude Code Profile Template

This directory packages the instruction files and helper docs that the RTL AI Agent expects when it runs inside a Claude Code (or other MCP-compatible) environment. Clone this repository inside your internal network, then run the sync script described in [`docs/CLAUDE_CODE_SETUP.md`](../docs/CLAUDE_CODE_SETUP.md) to copy these profiles into the workspace that Claude Code will use.

## Contents

| File | Purpose |
| --- | --- |
| `AGENTS.md` | High-level workspace rules (read first when the agent wakes up). |
| `SOUL.md` | Persona/behavior contract for the agent. |
| `HEARTBEAT.md` | Optional periodic checklist template (kept minimal by default). |
| `IDENTITY.template.md` | Template for naming/branding the agent in a fresh environment. |
| `USER.template.md` | Template for capturing the in-house operator's preferences. |
| `TOOLS.template.md` | Template for local tool/infra notes. |
| `skills/README.md` | Instructions for installing or vendoring the required AgentSkills. |

You can safely modify the template files after syncing them into your private workspace. Re-running the sync script with `--force` will overwrite existing files, so omit that flag when you want to keep local edits.
