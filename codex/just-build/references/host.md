# Codex host adapter

- Invocation: `$just-build` defaults to Auto; `$just-build guided` opts into choices. Read applicable `AGENTS.md` files before editing. Use the host's configured skill location; preserve existing installation scope.
- Choices: use a native selection tool only if exposed in this session, else one concise numbered prompt at a time. Do not claim a browser launcher exists.
- Connections: inspect available Codex MCP/tool facilities, optionally `codex mcp list` if the CLI is installed; a configured server alone is not proof of authorization. Check actual read/search capability and respect user scope. Never request or expose secrets. Do not assume ChatGPT connections transfer.
- Delegation: use actual Codex subagent tools only when available and authorized; otherwise sequential explicit role passes and `single-agent-fallback`. Keep test command and repo safety requirements from the shared skill.
