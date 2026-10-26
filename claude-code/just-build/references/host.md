# Claude Code host adapter

- Invoke `/just-build` or `/just-build auto` for Auto, `/just-build guided` for choices. `$ARGUMENTS` contains the whole request: read an optional leading mode and preserve the remaining named-project/continuation text. `${CLAUDE_SKILL_DIR}` supplies this skill's directory in `SKILL.md`; quote expanded helper paths when invoking them through a shell.
- Read the relevant `CLAUDE.md` files before editing a repository; preserve uncommitted changes. Personal install: `~/.claude/skills/just-build/`; project install: `.claude/skills/just-build/`.
- Guided selection: call `AskUserQuestion` only if the current host exposes it, otherwise numbered chat options. Do not depend on a browser interface.
- Discover authorized connections through this Claude Code session's actual MCP tools or `/mcp` setup; configured does not mean accessible. Never silently link another service or assume ChatGPT or claude.ai account tools are automatically shared.
- Delegate quality and polish sequentially using Claude Code subagents only when available and authorized. If no delegation exists, record `single-agent-fallback` truthfully.
- Don't use broad `allowed-tools` or skip permission prompts for external or destructive actions. Follow the shared test and source-freshness gates.
