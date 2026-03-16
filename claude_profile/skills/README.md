# Agent Skills Checklist

The RTL AI Agent expects the following AgentSkills to be available in your Claude Code environment. If you are using the stock OpenClaw distribution, these ship with the CLI under `~/.nvm/versions/node/<ver>/lib/node_modules/openclaw/skills/`. Copy or symlink each skill directory into the location that your internal Claude Code deployment reads from (typically `~/.config/claude/skills/` or the `AGENT_SKILLS_DIR` you configure).

| Skill | Why it matters |
| --- | --- |
| `coding-agent` | Delegates large refactors or exploratory code work to Codex/Claude/Pi agents. Required for multi-file changes in this repo. |
| `healthcheck` | Provides hardened checklists when auditing hosts or deployment targets. Useful when this agent is asked to validate internal infra. |
| `node-connect` | Troubleshoots OpenClaw node pairing and mobile companion connectivity (handy for remote debugging flows). |
| `openai-image-gen` | Optional, but lets the agent batch-generate UI references or diagrams when design work crops up. |
| `openai-whisper-api` | Enables audio transcription via Whisper for meetings / voice notes tied to RTL specs. |
| `skill-creator` | Required whenever the agent needs to author or update additional skills inside your org. |
| `weather` | Lightweight weather lookups for scheduling lab/field work. |

## Installing inside a secure network

1. On a networked machine, install or update OpenClaw so you have the latest `skills/` directory.
2. For each skill above, archive the folder (e.g., `tar czf coding-agent.tgz coding-agent/`).
3. Move the archives into the secure environment (USB, artifact repo, etc.).
4. Extract them into the skill search path that Claude Code uses (set `CLAUDE_CODE_SKILLS_DIR` if necessary).
5. Restart Claude Code so it rescans the skills.

If your internal Claude deployment uses a centralized skill registry, add these directories there instead of copying them by hand.
