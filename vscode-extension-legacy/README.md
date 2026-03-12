# VS Code Extension (Legacy)

> **This extension has been replaced by the HiveMind MCP server.**

The TypeScript VS Code extension in this directory was the original orchestration
layer for HiveMind. It has been superseded by a clean MCP (Model Context Protocol)
server that exposes all Python tools directly to GitHub Copilot.

## Why it was replaced

- The TypeScript extension was a brittle orchestrator that duplicated logic
  already implemented in the Python tools.
- The MCP server approach is simpler: Copilot calls Python tools directly
  via the standard MCP protocol, with no intermediate TypeScript layer.
- All 13 tools are now available as native MCP tools that Copilot discovers
  and calls automatically.

## New architecture

```
Copilot → MCP protocol (stdio) → hivemind_mcp/hivemind_server.py → tools/*.py
```

Configuration: `.vscode/mcp.json`

## Rollback

If you need to revert to the extension approach:

1. Rename this directory back to `vscode-extension/`
2. Remove `.vscode/mcp.json`
3. Rebuild and install the extension:
   ```
   cd vscode-extension
   npm install
   npm run compile
   ```
4. Revert `.github/copilot-instructions.md` to the pre-MCP version

## Files preserved

- `package.json` — extension manifest
- `tsconfig.json` — TypeScript configuration
- `src/extension.ts` — extension entry point
- `node_modules/` — (gitignored) npm dependencies
