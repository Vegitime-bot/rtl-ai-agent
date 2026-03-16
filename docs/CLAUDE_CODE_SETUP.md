# Running RTL AI Agent with an Internal Claude Code Deployment

This guide describes how to clone the repository inside your company network, install the prerequisites, and load the same agent instructions/skills that are used in the public workspace. Follow these steps once per environment; after that, Claude Code can work directly inside the repo with full context.

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.11+ | Matches the version used in the public workspace. |
| Surelog + UHDM (`capnp`) | Required for the `scripts/run_surelog.py` → `scripts/uhdm_extract.py` pipeline. |
| Claude Code CLI (v2.1+) | Install per Anthropic's documentation, then log in with your internal Claude/Console account. |
| AgentSkills directory | Ensure your Claude Code deployment can read custom skills (see `claude_profile/skills/README.md`). |
| Git + build-essential | Needed to clone and compile Surelog if not already available. |

## 2. Clone & bootstrap the repo

```bash
# Inside your secure network
cd /workspace
git clone https://<your-mirror>/rtl-ai-agent.git
cd rtl-ai-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Sync the agent profile files

The repo now bundles the same AGENTS/SOUL/USER templates that guide the assistant. Copy them into the workspace that Claude Code uses (defaults to `~/.openclaw/workspace`, but adjust if your deployment keeps a different directory):

```bash
python scripts/sync_claude_profile.py --dest /path/to/claude-workspace
# add --force if you need to overwrite existing files
```

This creates/updates the following files inside the destination:

- `AGENTS.md`, `SOUL.md`, `HEARTBEAT.md`
- `IDENTITY.md`, `USER.md`, `TOOLS.md` (from the templates if they don't exist)
- `skills/README.md` with the skill checklist

Edit `USER.md` and `IDENTITY.md` immediately after syncing so they reflect your in-house operator.

## 4. Install / vendor the required skills

Read `claude_profile/skills/README.md` for the exact list. If your internal Claude registry cannot reach the public internet, archive the skill directories on an online machine and import them into the secure environment. After the skills are in place, restart Claude Code so it rescans them.

## 5. Launch Claude Code inside the repo

```bash
# Log in once (choose your corporate method)
claude /login

# Start an interactive session rooted in the repo
cd /workspace/rtl-ai-agent
claude --permission-mode bypassPermissions --print "Load AGENTS.md/SOUL.md from ~/.openclaw/workspace before responding."
```

Because the workspace now contains the same instruction files, the agent will come online with the expected persona, boundaries, and heartbeat setup. You can further customize the prompt snippet above with run-specific context (e.g., "You're working on the RTL AI Agent project inside corp-net").

## 6. Keeping the profile in sync

Whenever the upstream instructions change, pull the latest repository version and rerun `scripts/sync_claude_profile.py`. To avoid clobbering local edits, omit `--force`; only use it when you intentionally want to overwrite your internal copies.

---

With this structure in place, anyone inside the company can clone the repo, run the sync script, and immediately start using Claude Code (or another MCP-compatible assistant) with the full set of instructions and skills that the project expects.
