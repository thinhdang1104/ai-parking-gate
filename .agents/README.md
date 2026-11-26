# DATN2 AI-Native Harness & MCP Guide

This directory holds the project-scoped **Agent Harness** and **MCP Server** configuration for `C:\Study\DATN2`.

## Structure
- `skills/datn2-workflow/SKILL.md` — Project development loop, guardrails, and 4-phase verification discipline.
- `memory/decisions.md` — Persistent ADR log across sessions.
- `memory/gotchas.md` — Critical invariants and edge cases from legacy `DATN`.
- `mcp_config.json` — Project MCP server definitions using environment variables only (zero hardcoded secrets).

## MCP Servers
1. **MySQL (`datn2-mysql`)**: Read-only by default (`ALLOW_*_OPERATION=false`) so AI agents can inspect `plate_recognition_history` safely without mutating live data. Set `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DATABASE` in your shell or `.env`.
2. **GitHub (`datn2-github`)**: Manage issues, PRs, and CI runs via `GITHUB_PERSONAL_ACCESS_TOKEN`.
3. **Browser QA**: Install the official **Chrome DevTools** plugin from Antigravity Marketplace (or use the built-in `browser` subagent) for automated UI inspection and console/network debugging.
