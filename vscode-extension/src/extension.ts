/**
 * HiveMind VS Code Extension (Simplified)
 *
 * Registers a @hivemind chat participant for quick commands and simple
 * questions. Agent routing and cross-agent collaboration are handled
 * natively by .github/agents/*.agent.md files -- not by this extension.
 *
 * This extension provides:
 *   - @hivemind chat participant with slash commands
 *   - Simplified free-form question handler (query_memory + query_graph)
 *   - Background tasks: client detection, branch tracking, status bar
 *
 * The ONLY AI used is GitHub Copilot Chat -- no external APIs.
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import { execFile } from "child_process";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PARTICIPANT_ID = "hivemind.assistant";
const STATUS_BAR_INTERVAL_MS = 60_000;

/**
 * Maximum characters for the assembled prompt sent to Copilot.
 * GPT-4o via VS Code LM API has a ~128k token window but the
 * extension API enforces tighter limits. Stay well under.
 * ~30k chars ≈ ~8k tokens — safe for any Copilot model.
 */
const MAX_PROMPT_CHARS = 30_000;
const MAX_PROFILE_CHARS = 3_000;
const MAX_TOOL_OUTPUT_CHARS = 18_000;
const MAX_INSTRUCTIONS_CHARS = 6_000;
const MAX_SINGLE_TOOL_CHARS = 6_000;

/** Cached project root — set once at activation, used everywhere. */
let _projectRoot: string | undefined;

/**
 * Resolve the HiveMind project root.
 *
 * After the extension is packaged and installed via VSIX, __dirname
 * points to ~/.vscode/extensions/…/out/ — NOT to the HiveMind repo.
 * We must find the workspace folder that contains HiveMind artefacts
 * (memory/, tools/, .github/) instead.
 *
 * Strategy (in order):
 *   1. Return the cached value if already resolved.
 *   2. Walk vscode.workspace.workspaceFolders and pick the first one
 *      that contains a "memory" directory (signature of a HiveMind root).
 *   3. Fall back to __dirname-relative resolution (works when running
 *      directly from the repo via `npm run watch` + F5 debug).
 */
function getProjectRoot(): string {
  if (_projectRoot) {
    return _projectRoot;
  }

  // Try workspace folders first
  const folders = vscode.workspace.workspaceFolders;
  console.log(`[HiveMind] getProjectRoot() searching ${folders?.length ?? 0} workspace folders`);
  if (folders) {
    for (const folder of folders) {
      const candidate = folder.uri.fsPath;
      console.log(`[HiveMind] getProjectRoot() checking candidate: ${candidate}`);
      if (
        fs.existsSync(path.join(candidate, "memory")) &&
        fs.existsSync(path.join(candidate, "tools"))
      ) {
        _projectRoot = candidate;
        console.log(`[HiveMind] getProjectRoot() resolved via memory+tools: ${_projectRoot}`);
        return _projectRoot;
      }
    }
    // If no folder has memory/tools, check if any folder is named HiveMind-ish
    for (const folder of folders) {
      const candidate = folder.uri.fsPath;
      if (
        fs.existsSync(path.join(candidate, ".github", "copilot-instructions.md"))
      ) {
        _projectRoot = candidate;
        console.log(`[HiveMind] getProjectRoot() resolved via copilot-instructions: ${_projectRoot}`);
        return _projectRoot;
      }
    }
  }

  // Fallback: __dirname-relative (works during extension development / F5)
  _projectRoot = path.resolve(__dirname, "..", "..");
  console.log(`[HiveMind] getProjectRoot() resolved via fallback: ${_projectRoot}`);
  return _projectRoot;
}

/**
 * Get the Python executable path.
 * Checks: VS Code setting > .venv in project > system 'python'.
 */
function getPythonPath(): string {
  const config = vscode.workspace.getConfiguration('hivemind');
  const configuredPath = config.get<string>('pythonPath');
  if (configuredPath && fs.existsSync(configuredPath)) {
    console.log(`[HiveMind] Using configured Python: ${configuredPath}`);
    return configuredPath;
  }
  // Try venv relative to project root
  const venvPath = path.join(getProjectRoot(), '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPath)) {
    console.log(`[HiveMind] Using venv Python: ${venvPath}`);
    return venvPath;
  }
  // Try Unix-style venv path
  const venvPathUnix = path.join(getProjectRoot(), '.venv', 'bin', 'python');
  if (fs.existsSync(venvPathUnix)) {
    console.log(`[HiveMind] Using venv Python (unix): ${venvPathUnix}`);
    return venvPathUnix;
  }
  console.log(`[HiveMind] Falling back to system python`);
  return 'python';
}

/** Path to a Python tool */
function toolPath(toolName: string): string {
  return path.join(getProjectRoot(), "tools", `${toolName}.py`);
}

/** Path to ingest CLI */
function ingestPath(): string {
  return path.join(getProjectRoot(), "ingest", "crawl_repos.py");
}

/** Path to copilot-instructions.md */
function getInstructionsPath(): string {
  return path.join(getProjectRoot(), ".github", "copilot-instructions.md");
}

/** Path to discovered_profile.yaml for a client */
function getProfilePath(client: string): string {
  return path.join(
    getProjectRoot(),
    "memory",
    client,
    "discovered_profile.yaml"
  );
}

// ---------------------------------------------------------------------------
// Python Tool Runner
// ---------------------------------------------------------------------------

interface ToolResult {
  success: boolean;
  output: string;
  error?: string;
}

/**
 * Run a Python tool asynchronously by name and return its stdout.
 */
async function runTool(tool: string, args: string[]): Promise<ToolResult> {
  const script = toolPath(tool);
  console.log(`[HiveMind] runTool: tool=${tool}, script=${script}, args=${JSON.stringify(args)}`);
  if (!fs.existsSync(script)) {
    console.log(`[HiveMind] runTool ERROR: script not found at ${script}`);
    return { success: false, output: "", error: `Tool not found: ${script}` };
  }
  const result = await runToolAsync(script, args);
  console.log(`[HiveMind] runTool result: tool=${tool}, success=${result.success}, outputLen=${result.output?.length ?? 0}`);
  if (!result.success) {
    console.log(`[HiveMind] runTool ERROR: ${result.error}`);
  } else {
    console.log(`[HiveMind] runTool first 300 chars: ${result.output?.substring(0, 300)}`);
  }
  return result;
}

/**
 * Run a Python tool asynchronously (for long-running operations).
 */
function runToolAsync(script: string, args: string[]): Promise<ToolResult> {
  const pythonPath = getPythonPath();
  const cwd = getProjectRoot();
  console.log(`[HiveMind] runToolAsync: python=${pythonPath}, cwd=${cwd}, script=${script}`);
  return new Promise((resolve) => {
    execFile(
      pythonPath,
      [script, ...args],
      {
        cwd,
        encoding: "utf-8",
        timeout: 120_000,
        windowsHide: true,
      },
      (err, stdout, stderr) => {
        if (err) {
          console.log(`[HiveMind] runToolAsync execFile error: ${err.message}`);
          console.log(`[HiveMind] runToolAsync stderr: ${stderr?.toString()?.substring(0, 500)}`);
          resolve({
            success: false,
            output: stdout?.toString() ?? "",
            error: stderr?.toString() ?? err.message,
          });
        } else {
          console.log(`[HiveMind] runToolAsync success, stdout length=${(stdout ?? '').length}`);
          resolve({ success: true, output: (stdout ?? "").trim() });
        }
      }
    );
  });
}

// ---------------------------------------------------------------------------
// Context Loaders
// ---------------------------------------------------------------------------

function loadInstructions(): string {
  const p = getInstructionsPath();
  if (fs.existsSync(p)) {
    const full = fs.readFileSync(p, "utf-8");
    if (full.length > MAX_INSTRUCTIONS_CHARS) {
      console.log(`[HiveMind] Instructions truncated from ${full.length} to ${MAX_INSTRUCTIONS_CHARS} chars`);
      return full.substring(0, MAX_INSTRUCTIONS_CHARS) + "\n# ... (instructions truncated for token budget) ...";
    }
    return full;
  }
  return "You are HiveMind, a local SRE assistant.";
}

function loadProfile(): string {
  const clientPath = path.join(
    getProjectRoot(),
    "memory",
    "active_client.txt"
  );
  if (!fs.existsSync(clientPath)) {
    return "";
  }
  const client = fs.readFileSync(clientPath, "utf-8").trim();
  const profilePath = getProfilePath(client);
  if (fs.existsSync(profilePath)) {
    const full = fs.readFileSync(profilePath, "utf-8");
    if (full.length > MAX_PROFILE_CHARS) {
      console.log(`[HiveMind] Profile truncated from ${full.length} to ${MAX_PROFILE_CHARS} chars`);
      return full.substring(0, MAX_PROFILE_CHARS) + "\n# ... (profile truncated for token budget) ...";
    }
    return full;
  }
  return "";
}

function getActiveClient(): string {
  const clientPath = path.join(
    getProjectRoot(),
    "memory",
    "active_client.txt"
  );
  if (fs.existsSync(clientPath)) {
    return fs.readFileSync(clientPath, "utf-8").trim();
  }
  return "unknown";
}

// ---------------------------------------------------------------------------
// Client & Branch Detection
// ---------------------------------------------------------------------------

/**
 * Detect the active client from workspace folder name and write it.
 */
function detectAndSetClient(): void {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return;
  }
  const rootName = path.basename(folders[0].uri.fsPath).toLowerCase();

  // Check if clients/ has a matching config
  const clientsDir = path.join(getProjectRoot(), "clients");
  if (fs.existsSync(clientsDir)) {
    const clients = fs.readdirSync(clientsDir);
    for (const c of clients) {
      if (rootName.includes(c.toLowerCase())) {
        writeActiveClient(c);
        return;
      }
    }
  }
  // Default: use first client found, or workspace name
  if (fs.existsSync(clientsDir)) {
    const clients = fs.readdirSync(clientsDir);
    if (clients.length > 0) {
      writeActiveClient(clients[0]);
      return;
    }
  }
  writeActiveClient(rootName);
}

function writeActiveClient(client: string): void {
  const memDir = path.join(getProjectRoot(), "memory");
  if (!fs.existsSync(memDir)) {
    fs.mkdirSync(memDir, { recursive: true });
  }
  fs.writeFileSync(path.join(memDir, "active_client.txt"), client, "utf-8");
}

/**
 * Read the active branch from memory/active_branch.txt.
 * No git commands — the HiveMind folder is not a git repo.
 * Git operations belong in the Python sync tools only.
 */
function getActiveBranch(rootPath: string): string {
  try {
    const branchFile = path.join(rootPath, 'memory', 'active_branch.txt');
    if (fs.existsSync(branchFile)) {
      return fs.readFileSync(branchFile, 'utf-8').trim();
    }
  } catch {}
  return 'main'; // safe default
}

// ---------------------------------------------------------------------------
// Slash Command Handlers
// ---------------------------------------------------------------------------

async function handleIngest(
  stream: vscode.ChatResponseStream
): Promise<string> {
  stream.markdown("**Re-indexing repos...** This may take a moment.\n\n");
  const result = await runToolAsync(ingestPath(), []);
  if (result.success) {
    return `Ingest complete.\n\n\`\`\`\n${result.output}\n\`\`\``;
  }
  return `Ingest encountered errors:\n\n\`\`\`\n${result.error}\n\`\`\``;
}

function handleStatus(): string {
  const client = getActiveClient();
  const instructionsExist = fs.existsSync(getInstructionsPath());
  const memoryDir = path.join(getProjectRoot(), "memory");
  const memoryExists = fs.existsSync(memoryDir);

  let status = `## HiveMind Status\n\n`;
  status += `- **Active client:** ${client}\n`;
  status += `- **Instructions:** ${instructionsExist ? "loaded" : "missing"}\n`;
  status += `- **Memory dir:** ${memoryExists ? "exists" : "not found"}\n`;

  if (memoryExists) {
    const graphDb = path.join(memoryDir, "graph.db");
    status += `- **Graph DB:** ${fs.existsSync(graphDb) ? "yes" : "no"}\n`;

    const profilePath = getProfilePath(client);
    status += `- **Profile:** ${fs.existsSync(profilePath) ? "yes" : "no"}\n`;
  }

  // Show sync status if available
  const syncPath = path.join(memoryDir, "sync_status.json");
  if (fs.existsSync(syncPath)) {
    try {
      const syncData = JSON.parse(fs.readFileSync(syncPath, "utf-8"));
      status += `- **Last sync:** ${syncData.last_sync ?? "unknown"}\n`;
      status += `- **Repos indexed:** ${syncData.repos_indexed ?? "unknown"}\n`;
    } catch {
      // Ignore parse errors
    }
  }

  return status;
}

async function handleSwitch(prompt: string): Promise<string> {
  const parts = prompt.trim().split(/\s+/);
  const clientName = parts[parts.length - 1];
  if (!clientName || clientName === "/switch") {
    const result = await runTool("set_client", ["--list"]);
    return result.success
      ? `Available clients:\n\n${result.output}`
      : "Could not list clients.";
  }
  const result = await runTool("set_client", ["--client", clientName]);
  return result.success
    ? `Switched to client: **${clientName}**`
    : `Failed to switch: ${result.error}`;
}

async function handleImpact(prompt: string): Promise<string> {
  const target = prompt.replace(/^\/impact\s*/i, "").trim();
  if (!target) {
    return "Please specify an entity. Example: `/impact deploy_audit.yaml`";
  }
  const activeClient = getActiveClient();
  const result = await runTool("impact_analysis", ["--client", activeClient, "--entity", target]);
  return result.success
    ? result.output
    : `Impact analysis failed: ${result.error}`;
}

async function handleSecrets(prompt: string): Promise<string> {
  const name = prompt.replace(/^\/secrets\s*/i, "").trim();
  if (!name) {
    return "Please specify a service. Example: `/secrets audit-service`";
  }
  const activeClient = getActiveClient();
  const result = await runTool("get_secret_flow", ["--client", activeClient, "--secret", name]);
  return result.success ? result.output : `Secret trace failed: ${result.error}`;
}

async function handlePipeline(prompt: string): Promise<string> {
  const name = prompt.replace(/^\/pipeline\s*/i, "").trim();
  if (!name) {
    return "Please specify a pipeline. Example: `/pipeline deploy_audit.yaml`";
  }
  const activeClient = getActiveClient();
  const result = await runTool("get_pipeline", ["--client", activeClient, "--name", name]);
  return result.success
    ? result.output
    : `Pipeline parse failed: ${result.error}`;
}

async function handleDiff(prompt: string): Promise<string> {
  const parts = prompt.replace(/^\/diff\s*/i, "").trim().split(/\s+/);
  if (parts.length < 2) {
    return "Please specify two branches. Example: `/diff develop release_26_1`";
  }
  const activeClient = getActiveClient();
  const base = parts[0];
  const compare = parts[1];
  const repo = parts.length >= 3 ? parts[2] : null;

  // If a specific repo is given, diff just that one
  if (repo) {
    const result = await runTool("diff_branches", ["--client", activeClient, "--repo", repo, "--base", base, "--compare", compare]);
    return result.success
      ? result.output
      : `Branch diff failed: ${result.error}`;
  }

  // No repo specified — diff all repos using vector file comparison
  const vectorDir = path.join(getProjectRoot(), "memory", activeClient, "vectors");
  if (!fs.existsSync(vectorDir)) {
    return "No indexed data found. Run `/ingest` first.";
  }

  const allFiles = fs.readdirSync(vectorDir).filter(f => f.endsWith(".json"));
  // Group by repo: repoName_branchName.json
  const repos = new Set<string>();
  for (const f of allFiles) {
    const lastUnderscore = f.lastIndexOf("_");
    if (lastUnderscore > 0) {
      repos.add(f.substring(0, lastUnderscore));
    }
  }

  const output: string[] = [`## Diff: ${base} vs ${compare} (all repos)\n`];
  for (const repoName of repos) {
    const result = await runTool("diff_branches", ["--client", activeClient, "--repo", repoName, "--base", base, "--compare", compare]);
    if (result.success && result.output && !/^Error/m.test(result.output)) {
      output.push(`### ${repoName}\n${result.output}\n`);
    }
  }
  return output.length > 1 ? output.join("\n") : `No diff data found for ${base} vs ${compare} across repos.`;
}

async function handleBranches(): Promise<string> {
  const activeClient = getActiveClient();
  // Read branch_index.json directly (list_branches.py needs local git repos)
  const branchIndexPath = path.join(getProjectRoot(), "memory", activeClient, "branch_index.json");
  if (fs.existsSync(branchIndexPath)) {
    try {
      const branchData = JSON.parse(fs.readFileSync(branchIndexPath, "utf-8"));
      const grouped: Record<string, { branch: string; tier: string; indexed_at: string }[]> = {};
      for (const [key, info] of Object.entries(branchData) as [string, any][]) {
        const repoName = info.repo || key.split(":")[0];
        if (!grouped[repoName]) { grouped[repoName] = []; }
        grouped[repoName].push({
          branch: info.branch || key.split(":")[1],
          tier: info.tier || "unknown",
          indexed_at: info.indexed_at || "",
        });
      }
      const lines: string[] = ["## Indexed Branches\n"];
      for (const [repoName, branches] of Object.entries(grouped)) {
        lines.push(`**${repoName}** (${branches.length} branches)`);
        for (const b of branches) {
          lines.push(`  [${b.tier.padEnd(12)}] ${b.branch.padEnd(40)} indexed: ${b.indexed_at}`);
        }
        lines.push("");
      }
      return lines.join("\n");
    } catch (e: any) {
      return `Branch listing error: ${e.message}`;
    }
  }
  // Fallback: try the Python tool
  const result = await runTool("list_branches", ["--client", activeClient]);
  return result.success
    ? result.output
    : `Branch listing failed: ${result.error}`;
}

// ---------------------------------------------------------------------------
// Simple Entity Extraction (for graph lookups)
// ---------------------------------------------------------------------------

/**
 * Truncate a single tool output to MAX_SINGLE_TOOL_CHARS.
 * For pipeline output, prefer cutting the Variables section first.
 */
function truncateToolOutput(output: string): string {
  if (output.length <= MAX_SINGLE_TOOL_CHARS) {
    return output;
  }
  // For pipeline output, try to cut at "Variables (" to keep stages/templates/environments
  const varIdx = output.indexOf("\nVariables (");
  if (varIdx > 0 && varIdx < MAX_SINGLE_TOOL_CHARS) {
    const truncated = output.substring(0, varIdx) + "\n\n# ... (variables omitted for brevity) ...";
    if (truncated.length <= MAX_SINGLE_TOOL_CHARS) {
      return truncated;
    }
  }
  return output.substring(0, MAX_SINGLE_TOOL_CHARS) + "\n\n# ... (output truncated) ...";
}

/**
 * Try to extract an entity name from the question for graph lookup.
 * Looks for quoted strings, known patterns, or capitalized multi-word names.
 */
function extractEntity(prompt: string): string | null {
  // Quoted entity
  const quoted = prompt.match(/["']([^"']+)["']/);
  if (quoted) {
    return quoted[1];
  }

  // Underscore-delimited identifiers like cd_deploy_env, get_artifact_versions
  // These are very likely entity names (pipeline, service, template identifiers)
  const underscored = prompt.match(/\b([a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+)\b/);
  if (underscored) {
    return underscored[1];
  }

  // Hyphenated identifiers like my-service, dfin-harness-pipelines
  const hyphenated = prompt.match(/\b([a-zA-Z][a-zA-Z0-9]*(?:-[a-zA-Z0-9]+)+)\b/);
  if (hyphenated && hyphenated[1].length > 4) {
    return hyphenated[1];
  }

  // Common patterns: "about X", "for X", "of X", "does X have"
  const patterns = [
    /(?:about|for|of|impact|trace|check)\s+(\S+)/i,
    /(?:does|do)\s+(\S+)\s+(?:have|use|reference|contain)/i,
    /(\S+)\s+(?:service|pipeline|secret|template|chart|have|stages)/i,
    /(?:in|from|repo|repository)\s+(\S+)/i,
  ];
  for (const pat of patterns) {
    const m = prompt.match(pat);
    if (m && m[1].length > 2 && !/^(the|and|this|that|how|what|why|is|are|a|an)$/i.test(m[1])) {
      return m[1];
    }
  }

  return null;
}

/**
 * Extract diff parameters: repo, base branch, compare branch.
 * Handles patterns like:
 *   "what changed between main and release_26_2 in dfin-harness-pipelines"
 *   "diff main release_26_2 dfin-harness-pipelines"
 */
function extractDiffParams(prompt: string): { repo: string; base: string; compare: string } | null {
  // Pattern: "between BASE and COMPARE in REPO"
  const betweenIn = prompt.match(/between\s+(\S+)\s+and\s+(\S+)\s+in\s+(\S+)/i);
  if (betweenIn) {
    return { base: betweenIn[1], compare: betweenIn[2], repo: betweenIn[3] };
  }
  // Pattern: "REPO between BASE and COMPARE" or "REPO from BASE to COMPARE"
  const repoBetween = prompt.match(/([\w][-\w]+)\s+(?:between|from)\s+(\S+)\s+(?:and|to)\s+(\S+)/i);
  if (repoBetween && !/^(what|how|which|show|list|tell|changed|compare)$/i.test(repoBetween[1])) {
    return { repo: repoBetween[1], base: repoBetween[2], compare: repoBetween[3] };
  }
  // Pattern: "diff BASE COMPARE REPO"
  const diffArgs = prompt.match(/diff\s+(\S+)\s+(\S+)\s+(\S+)/i);
  if (diffArgs) {
    return { base: diffArgs[1], compare: diffArgs[2], repo: diffArgs[3] };
  }
  // Pattern: "between BASE and COMPARE" (no repo — default to all)
  const betweenNoRepo = prompt.match(/between\s+([\w][-\w_.]+)\s+and\s+([\w][-\w_.]+)/i);
  if (betweenNoRepo) {
    // Try extracting repo from elsewhere in the prompt
    const repo = extractRepo(prompt) || "all";
    return { base: betweenNoRepo[1], compare: betweenNoRepo[2], repo };
  }
  return null;
}

/**
 * Extract a repo name from the prompt for list_branches or search_files.
 */
function extractRepo(prompt: string): string | null {
  // "branches for/of/in REPO" or "in REPO"
  // Skip common stop words AND the active client name (client ≠ repo)
  const activeClient = getActiveClient();
  const m = prompt.match(/(?:for|of|in|from|repo(?:sitory)?)\s+([\w][-\w]*)/i);
  if (
    m &&
    m[1].length > 2 &&
    !/^(the|and|this|that|a|an|all|my|our|each|every|which|what|how|it|its)$/i.test(m[1]) &&
    m[1].toLowerCase() !== activeClient.toLowerCase()
  ) {
    return m[1];
  }
  return null;
}

// ---------------------------------------------------------------------------
// Agent Config Loader & Handler Factory
// ---------------------------------------------------------------------------

interface AgentConfig {
  tools: string[];
  systemPrompt: string;
}

/**
 * Load an agent's .agent.md file and parse frontmatter.
 * Re-reads every call so edits take effect without rebuild.
 */
function loadAgentConfig(agentName: string): AgentConfig | null {
  const agentPath = path.join(
    getProjectRoot(),
    ".github",
    "agents",
    `${agentName}.agent.md`
  );
  if (!fs.existsSync(agentPath)) {
    return null;
  }
  const content = fs.readFileSync(agentPath, "utf-8");

  // Parse frontmatter between --- delimiters
  const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!fmMatch) {
    return { tools: [], systemPrompt: content };
  }

  const frontmatter = fmMatch[1];
  const body = fmMatch[2].trim();

  // Extract tools array: tools: ['query-memory', 'query-graph', ...]
  const toolsMatch = frontmatter.match(/^tools:\s*\[([^\]]*)\]/m);
  const tools = toolsMatch
    ? toolsMatch[1]
        .split(",")
        .map((t) => t.trim().replace(/['"]/g, ""))
        .filter((t) => t.length > 0)
    : [];

  return { tools, systemPrompt: body };
}

/** Map agent tool name (hyphenated) to Python script name (underscored). */
function toolNameToScript(tool: string): string {
  return tool.replace(/-/g, "_");
}

/**
 * Create a chat request handler for a specialist agent.
 * Each agent reads its .agent.md file for system prompt and tool list,
 * runs relevant tools, then sends the augmented prompt to Copilot.
 */
function createAgentHandler(
  agentName: string
): (
  request: vscode.ChatRequest,
  context: vscode.ChatContext,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
) => Promise<vscode.ChatResult> {
  return async (request, _context, stream, token) => {
    const prompt = request.prompt;

    // Load agent config (re-read each time so edits take effect)
    const config = loadAgentConfig(agentName);
    if (!config) {
      stream.markdown(
        `Agent file not found: \`.github/agents/${agentName}.agent.md\``
      );
      return {};
    }

    const displayName = agentName
      .replace("hivemind-", "")
      .replace(/^\w/, (c) => c.toUpperCase());
    stream.progress(`${displayName} is searching the knowledge base...`);

    const contextParts: string[] = [];
    const scriptTools = config.tools.map(toolNameToScript);

    // 1. Always run query_memory if agent has it
    const activeClient = getActiveClient();
    let lastToolError = '';
    console.log(`[HiveMind][${agentName}] handler fired, client=${activeClient}, prompt=${prompt.substring(0, 100)}`);
    if (
      scriptTools.includes("query_memory") &&
      !token.isCancellationRequested
    ) {
      const memResult = await runTool("query_memory", [
        "--client", activeClient, "--query", prompt, "--top_k", "8"
      ]);
      console.log(`[HiveMind][${agentName}] memResult success=${memResult.success}, len=${memResult.output?.length ?? 0}`);
      if (memResult.success && memResult.output) {
        contextParts.push(
          `### Knowledge Base Search\n\`\`\`\n${memResult.output}\n\`\`\``
        );
      } else {
        lastToolError = memResult.error || 'query_memory returned empty';
      }
    }

    // 2. Query graph if agent has it and we can extract an entity
    const entity = extractEntity(prompt);
    if (
      entity &&
      scriptTools.includes("query_graph") &&
      !token.isCancellationRequested
    ) {
      stream.progress(`Looking up relationships for: ${entity}`);
      const graphResult = await runTool("query_graph", [
        "--client", activeClient, "--entity", entity, "--direction", "both"
      ]);
      if (graphResult.success && graphResult.output) {
        contextParts.push(
          `### Graph Relationships\n\`\`\`\n${graphResult.output}\n\`\`\``
        );
      }
    }

    // 3. Run specialist tools if agent has them and we have an entity
    if (entity && !token.isCancellationRequested) {
      if (scriptTools.includes("get_pipeline")) {
        const result = await runTool("get_pipeline", [
          "--client", activeClient, "--name", entity
        ]);
        if (result.success && result.output) {
          contextParts.push(
            `### Pipeline Details\n\`\`\`\n${truncateToolOutput(result.output)}\n\`\`\``
          );
        }
      }
      if (scriptTools.includes("get_secret_flow")) {
        const result = await runTool("get_secret_flow", [
          "--client", activeClient, "--secret", entity
        ]);
        if (result.success && result.output) {
          contextParts.push(
            `### Secret Flow\n\`\`\`\n${result.output}\n\`\`\``
          );
        }
      }
      if (scriptTools.includes("impact_analysis")) {
        const result = await runTool("impact_analysis", [
          "--client", activeClient, "--entity", entity
        ]);
        if (result.success && result.output) {
          contextParts.push(
            `### Impact Analysis\n\`\`\`\n${result.output}\n\`\`\``
          );
        }
      }
    }

    // 4. Build augmented prompt with agent system prompt
    const instructions = loadInstructions();
    const profile = loadProfile();

    // Truncate tool context to stay within token budget
    let toolContext =
      contextParts.length > 0
        ? `\n\n## Tool Results\n\n${contextParts.join("\n\n")}`
        : "";
    if (toolContext.length > MAX_TOOL_OUTPUT_CHARS) {
      console.log(`[HiveMind][${agentName}] toolContext truncated from ${toolContext.length} to ${MAX_TOOL_OUTPUT_CHARS} chars`);
      toolContext = toolContext.substring(0, MAX_TOOL_OUTPUT_CHARS) + "\n\n# ... (results truncated for token budget) ...";
    }
    const profileContext = profile
      ? `\n\n## Discovered Profile\n\`\`\`yaml\n${profile}\n\`\`\``
      : "";

    // Guard: if toolContext is empty, provide explicit signal with diagnostics
    if (!toolContext || toolContext.trim() === '' || toolContext.trim() === '## Tool Results') {
      console.log(`[HiveMind][${agentName}] All tools returned empty. Last error: ${lastToolError}`);
      toolContext = `## Tool Results\n\nNO RESULTS RETURNED\nError detail: ${lastToolError}\nPython path used: ${getPythonPath()}\nProject root: ${getProjectRoot()}\nClient: ${activeClient}`;
    }
    console.log(`[HiveMind][${agentName}] toolContext length=${toolContext.length}, preview: ${toolContext.substring(0, 200)}`);

    const fullPrompt = [
      `## Agent: ${agentName}\n\n${config.systemPrompt}`,
      instructions,
      profileContext,
      `\n${'='.repeat(60)}`,
      `KNOWLEDGE BASE RESULTS — YOUR ONLY SOURCE OF TRUTH`,
      `This is real data from the DFIN infrastructure repos.`,
      `Base your ENTIRE answer on this data. Cite the exact file paths shown.`,
      `If empty → respond with "NOT IN KNOWLEDGE BASE" only.`,
      `${'='.repeat(60)}\n`,
      toolContext,
      `\n${'='.repeat(60)}`,
      `END OF KNOWLEDGE BASE RESULTS`,
      `${'='.repeat(60)}\n`,
      `QUESTION (answer using ONLY the knowledge base results above, never from training data):`,
      prompt,
    ].join("\n");

    // 5. Safety cap on total prompt size
    let finalPrompt = fullPrompt;
    if (finalPrompt.length > MAX_PROMPT_CHARS) {
      console.log(`[HiveMind][${agentName}] fullPrompt truncated from ${finalPrompt.length} to ${MAX_PROMPT_CHARS} chars`);
      finalPrompt = finalPrompt.substring(0, MAX_PROMPT_CHARS) + "\n\n# ... (prompt truncated for token budget) ...";
    }

    // 6. Send to Copilot LLM
    const messages = [vscode.LanguageModelChatMessage.User(finalPrompt)];

    try {
      const [model] = await vscode.lm.selectChatModels({
        vendor: "copilot",
        family: "gpt-4o",
      });

      if (model) {
        const chatResponse = await model.sendRequest(messages, {}, token);
        for await (const fragment of chatResponse.text) {
          stream.markdown(fragment);
        }
      } else {
        stream.markdown(
          "No language model available. Here is the raw tool output:\n\n"
        );
        stream.markdown(toolContext || "No relevant context found.");
      }
    } catch (err: any) {
      stream.markdown(
        `Error communicating with Copilot: ${err.message}\n\n`
      );
      if (toolContext) {
        stream.markdown("Here is the raw tool output:\n\n");
        stream.markdown(toolContext);
      }
    }

    return {};
  };
}

// ---------------------------------------------------------------------------
// Chat Request Handler (Main @hivemind participant)
// ---------------------------------------------------------------------------

async function handleChatRequest(
  request: vscode.ChatRequest,
  _context: vscode.ChatContext,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<vscode.ChatResult> {
  const prompt = request.prompt;

  // -----------------------------------------------------------------------
  // Handle slash commands
  // -----------------------------------------------------------------------
  if (request.command) {
    let response: string;

    switch (request.command) {
      case "ingest":
        response = await handleIngest(stream);
        break;
      case "status":
        response = handleStatus();
        break;
      case "switch":
        response = await handleSwitch(prompt);
        break;
      case "impact":
        response = await handleImpact(prompt);
        break;
      case "secrets":
        response = await handleSecrets(prompt);
        break;
      case "pipeline":
        response = await handlePipeline(prompt);
        break;
      case "diff":
        response = await handleDiff(prompt);
        break;
      case "branches":
        response = await handleBranches();
        break;
      default:
        response = `Unknown command: ${request.command}`;
    }

    stream.markdown(response);
    return {};
  }

  // -----------------------------------------------------------------------
  // Free-form question: simplified context gathering
  // -----------------------------------------------------------------------
  stream.progress("Searching HiveMind knowledge base...");

  const contextParts: string[] = [];
  let lastToolError = '';

  // 1. Always run query_memory
  const activeClient = getActiveClient();
  console.log(`[HiveMind] handler fired, client=${activeClient}, prompt=${prompt.substring(0, 100)}`);
  console.log(`[HiveMind] projectRoot=${getProjectRoot()}, pythonPath=${getPythonPath()}`);
  if (!token.isCancellationRequested) {
    const memResult = await runTool("query_memory", [
      "--client", activeClient, "--query", prompt, "--top_k", "8"
    ]);
    console.log(`[HiveMind] memResult success=${memResult.success}, len=${memResult.output?.length ?? 0}`);
    if (memResult.success && memResult.output) {
      contextParts.push(
        `### Knowledge Base Search\n\`\`\`\n${memResult.output}\n\`\`\``
      );
    } else {
      lastToolError = memResult.error || 'query_memory returned empty';
      console.log(`[HiveMind] query_memory failed or empty: ${lastToolError}`);
    }
  }

  // 2. Run query_graph if we can extract an entity from the question
  const entity = extractEntity(prompt);
  console.log(`[HiveMind] extracted entity: ${entity}`);
  if (entity && !token.isCancellationRequested) {
    stream.progress(`Looking up relationships for: ${entity}`);
    const graphResult = await runTool("query_graph", [
      "--client", activeClient, "--entity", entity, "--direction", "both"
    ]);
    console.log(`[HiveMind] graphResult success=${graphResult.success}, len=${graphResult.output?.length ?? 0}`);
    if (graphResult.success && graphResult.output) {
      contextParts.push(
        `### Graph Relationships\n\`\`\`\n${graphResult.output}\n\`\`\``
      );
    } else {
      lastToolError = graphResult.error || lastToolError || 'query_graph returned empty';
    }
  }

  // 2b. Run specialist tools when we have an entity
  if (entity && !token.isCancellationRequested) {
    // Detect if question is about pipelines/stages/templates
    if (/pipeline|stage|template|deploy|rollout|cd_|ci_/i.test(prompt)) {
      stream.progress(`Fetching pipeline details for: ${entity}`);
      const pipeResult = await runTool("get_pipeline", [
        "--client", activeClient, "--name", entity
      ]);
      console.log(`[HiveMind] get_pipeline success=${pipeResult.success}, len=${pipeResult.output?.length ?? 0}`);
      if (pipeResult.success && pipeResult.output) {
        contextParts.push(
          `### Pipeline Details\n\`\`\`\n${truncateToolOutput(pipeResult.output)}\n\`\`\``
        );
      }
    }
    // Detect if question is about secrets
    if (/secret|key.?vault|credential|password|token/i.test(prompt)) {
      stream.progress(`Tracing secret flow for: ${entity}`);
      const secretResult = await runTool("get_secret_flow", [
        "--client", activeClient, "--secret", entity
      ]);
      console.log(`[HiveMind] get_secret_flow success=${secretResult.success}, len=${secretResult.output?.length ?? 0}`);
      if (secretResult.success && secretResult.output) {
        contextParts.push(
          `### Secret Flow\n\`\`\`\n${secretResult.output}\n\`\`\``
        );
      }
    }
    // Detect if question is about impact/blast radius
    if (/impact|blast|affect|depend|downstream|upstream/i.test(prompt)) {
      stream.progress(`Running impact analysis for: ${entity}`);
      const impactResult = await runTool("impact_analysis", [
        "--client", activeClient, "--entity", entity
      ]);
      console.log(`[HiveMind] impact_analysis success=${impactResult.success}, len=${impactResult.output?.length ?? 0}`);
      if (impactResult.success && impactResult.output) {
        contextParts.push(
          `### Impact Analysis\n\`\`\`\n${impactResult.output}\n\`\`\``
        );
      }
    }
  }

  // 2c. Run list_branches if the question is about branches
  if (/\b(branch|branches|list.?branch)\b/i.test(prompt) && !token.isCancellationRequested) {
    const repo = extractRepo(prompt);
    stream.progress(`Listing branches${repo ? ` for ${repo}` : ''}...`);

    // Read branch_index.json directly (list_branches.py needs local git repos)
    const branchIndexPath = path.join(getProjectRoot(), "memory", activeClient, "branch_index.json");
    if (fs.existsSync(branchIndexPath)) {
      try {
        const branchData = JSON.parse(fs.readFileSync(branchIndexPath, "utf-8"));
        const grouped: Record<string, { branch: string; tier: string; indexed_at: string }[]> = {};
        for (const [key, info] of Object.entries(branchData) as [string, any][]) {
          const repoName = info.repo || key.split(":")[0];
          if (repo && repoName !== repo) { continue; }
          if (!grouped[repoName]) { grouped[repoName] = []; }
          grouped[repoName].push({
            branch: info.branch || key.split(":")[1],
            tier: info.tier || "unknown",
            indexed_at: info.indexed_at || "",
          });
        }
        const lines: string[] = [];
        for (const [repoName, branches] of Object.entries(grouped)) {
          lines.push(`${repoName} (${branches.length} branches)`);
          for (const b of branches) {
            lines.push(`  [${b.tier.padEnd(12)}] ${b.branch.padEnd(40)} indexed: ${b.indexed_at}`);
          }
          lines.push("");
        }
        const branchOutput = lines.join("\n");
        console.log(`[HiveMind] branch_index.json read, ${Object.keys(grouped).length} repos`);
        contextParts.push(
          `### Branches\n\`\`\`\n${branchOutput}\n\`\`\``
        );
      } catch (e: any) {
        console.log(`[HiveMind] branch_index.json parse error: ${e.message}`);
      }
    } else {
      console.log(`[HiveMind] branch_index.json not found at ${branchIndexPath}`);
    }
  }

  // 2d. Run diff_branches if the question is about changes between branches
  if (/\b(changed|change|diff|compare|difference)\b/i.test(prompt) && !token.isCancellationRequested) {
    const diffParams = extractDiffParams(prompt);
    if (diffParams) {
      const diffRepo = diffParams.repo;
      stream.progress(`Comparing ${diffParams.base} vs ${diffParams.compare}${diffRepo !== 'all' ? ` in ${diffRepo}` : ''}...`);

      if (diffRepo === 'all') {
        // Diff across all repos using vector file comparison
        const vectorDir = path.join(getProjectRoot(), "memory", activeClient, "vectors");
        if (fs.existsSync(vectorDir)) {
          const allVectorFiles = fs.readdirSync(vectorDir).filter(f => f.endsWith(".json"));
          const repoNames = new Set<string>();
          for (const f of allVectorFiles) {
            const lastUnderscore = f.lastIndexOf("_");
            if (lastUnderscore > 0) { repoNames.add(f.substring(0, lastUnderscore)); }
          }
          const diffLines: string[] = [];
          for (const rName of repoNames) {
            const singleResult = await runTool("diff_branches", [
              "--client", activeClient, "--repo", rName, "--base", diffParams.base, "--compare", diffParams.compare
            ]);
            if (singleResult.success && singleResult.output && !/^(Error|No repo|not found|Cannot)/m.test(singleResult.output)) {
              diffLines.push(singleResult.output);
            }
          }
          if (diffLines.length > 0) {
            contextParts.push(`### Branch Diff\n\`\`\`\n${diffLines.join("\n\n")}\n\`\`\``);
          } else {
            contextParts.push(`### Branch Diff\n\`\`\`\nNo diff data found for ${diffParams.base} vs ${diffParams.compare} across repos.\n\`\`\``);
          }
        }
      } else {
        // Specific repo diff
        const diffResult = await runTool("diff_branches", [
          "--client", activeClient,
          "--repo", diffRepo,
          "--base", diffParams.base,
          "--compare", diffParams.compare
        ]);
        console.log(`[HiveMind] diff_branches success=${diffResult.success}, len=${diffResult.output?.length ?? 0}`);
        if (diffResult.success && diffResult.output && !/^(Error|No repo|not found|Cannot)/m.test(diffResult.output)) {
          contextParts.push(
            `### Branch Diff\n\`\`\`\n${diffResult.output}\n\`\`\``
          );
        } else {
          // Fallback: compare indexed vector files between branches
          console.log(`[HiveMind] diff_branches tool failed, trying vector file comparison`);
          const vectorDir = path.join(getProjectRoot(), "memory", activeClient, "vectors");
          if (fs.existsSync(vectorDir)) {
            const baseFile = `${diffRepo}_${diffParams.base}.json`;
            const compareFile = `${diffRepo}_${diffParams.compare}.json`;
            const basePath = path.join(vectorDir, baseFile);
            const comparePath = path.join(vectorDir, compareFile);

            const baseFiles = new Set<string>();
            const compareFiles = new Set<string>();

            if (fs.existsSync(basePath)) {
              const chunks = JSON.parse(fs.readFileSync(basePath, "utf-8"));
              for (const c of chunks) { if (c.file) { baseFiles.add(c.file); } }
            }
            if (fs.existsSync(comparePath)) {
              const chunks = JSON.parse(fs.readFileSync(comparePath, "utf-8"));
              for (const c of chunks) { if (c.file) { compareFiles.add(c.file); } }
            }

            const onlyInBase = [...baseFiles].filter(f => !compareFiles.has(f));
            const onlyInCompare = [...compareFiles].filter(f => !baseFiles.has(f));
            const inBoth = [...baseFiles].filter(f => compareFiles.has(f));

            const lines: string[] = [
              `Diff: ${diffRepo} ${diffParams.base} vs ${diffParams.compare}`,
              `(Based on indexed files — not a git diff)`,
              ``,
              `Files in both branches: ${inBoth.length}`,
            ];
            if (onlyInBase.length > 0) {
              lines.push(`\nOnly in ${diffParams.base} (${onlyInBase.length}):`);
              for (const f of onlyInBase.slice(0, 20)) { lines.push(`  - ${f}`); }
            }
            if (onlyInCompare.length > 0) {
              lines.push(`\nOnly in ${diffParams.compare} (${onlyInCompare.length}):`);
              for (const f of onlyInCompare.slice(0, 20)) { lines.push(`  - ${f}`); }
            }
            if (onlyInBase.length === 0 && onlyInCompare.length === 0) {
              lines.push(`\nNo file-level differences detected in indexed data.`);
              lines.push(`Both branches have the same ${inBoth.length} indexed files.`);
            }
            contextParts.push(
              `### Branch Diff (from indexed data)\n\`\`\`\n${lines.join("\n")}\n\`\`\``
            );
          }
        }
      }
    }
  }

  // 2e. Run search_files for terraform/module/file/service search questions
  if (/\b(terraform|module|file|find|search|where|use|service)\b/i.test(prompt) && !token.isCancellationRequested) {
    // Extract a meaningful search query from the prompt — prefer subject keywords over entity/repo
    const repo = extractRepo(prompt);
    const subjectMatch = prompt.match(/\b(module|secret|service|variable|pipeline|template|helm|chart|environment|resource)s?\b/i);
    const searchQuery = subjectMatch
      ? subjectMatch[1]
      : entity || repo || prompt.split(/\s+/).slice(0, 5).join(" ");
    stream.progress(`Searching files for: ${searchQuery}...`);
    const args = ["--client", activeClient, "--query", searchQuery];
    if (repo) { args.push("--repo", repo); }
    if (/terraform|\.tf\b/i.test(prompt)) { args.push("--type", "terraform"); }
    const searchResult = await runTool("search_files", args);
    console.log(`[HiveMind] search_files success=${searchResult.success}, len=${searchResult.output?.length ?? 0}`);
    if (searchResult.success && searchResult.output) {
      contextParts.push(
        `### File Search\n\`\`\`\n${searchResult.output}\n\`\`\``
      );
    }
  }

  // 3. Build augmented prompt
  console.log(`[HiveMind] contextParts count=${contextParts.length}`);
  const instructions = loadInstructions();
  const profile = loadProfile();

  // Truncate tool context to stay within token budget
  let toolContext =
    contextParts.length > 0
      ? `\n\n## Tool Results\n\n${contextParts.join("\n\n")}`
      : "";
  if (toolContext.length > MAX_TOOL_OUTPUT_CHARS) {
    console.log(`[HiveMind] toolContext truncated from ${toolContext.length} to ${MAX_TOOL_OUTPUT_CHARS} chars`);
    toolContext = toolContext.substring(0, MAX_TOOL_OUTPUT_CHARS) + "\n\n# ... (results truncated for token budget) ...";
  }
  const profileContext = profile
    ? `\n\n## Discovered Profile\n\`\`\`yaml\n${profile}\n\`\`\``
    : "";

  // Guard: if toolContext is empty, provide explicit signal with diagnostics
  if (!toolContext || toolContext.trim() === '' || toolContext.trim() === '## Tool Results') {
    console.log(`[HiveMind] All tools returned empty. Last error: ${lastToolError}`);
    toolContext = `## Tool Results\n\nNO RESULTS RETURNED\nError detail: ${lastToolError}\nPython path used: ${getPythonPath()}\nProject root: ${getProjectRoot()}\nClient: ${activeClient}`;
  }

  const fullPrompt = [
    instructions,
    profileContext,
    `\n${'='.repeat(60)}`,
    `KNOWLEDGE BASE RESULTS — YOUR ONLY SOURCE OF TRUTH`,
    `This is real data from the DFIN infrastructure repos.`,
    `Base your ENTIRE answer on this data. Cite the exact file paths shown.`,
    `If empty → respond with "NOT IN KNOWLEDGE BASE" only.`,
    `${'='.repeat(60)}\n`,
    toolContext,
    `\n${'='.repeat(60)}`,
    `END OF KNOWLEDGE BASE RESULTS`,
    `${'='.repeat(60)}\n`,
    `QUESTION (answer using ONLY the knowledge base results above, never from training data):`,
    prompt,
  ].join("\n");

  // 4. Safety cap on total prompt size
  let finalPrompt = fullPrompt;
  if (finalPrompt.length > MAX_PROMPT_CHARS) {
    console.log(`[HiveMind] fullPrompt truncated from ${finalPrompt.length} to ${MAX_PROMPT_CHARS} chars`);
    finalPrompt = finalPrompt.substring(0, MAX_PROMPT_CHARS) + "\n\n# ... (prompt truncated for token budget) ...";
  }

  // 5. Send to Copilot
  console.log(`[HiveMind] toolContext length=${toolContext.length}`);
  console.log(`[HiveMind] toolContext preview: ${toolContext.substring(0, 300)}`);
  console.log(`[HiveMind] sending to Copilot, fullPrompt length=${finalPrompt.length}`);
  const messages = [vscode.LanguageModelChatMessage.User(finalPrompt)];

  try {
    const [model] = await vscode.lm.selectChatModels({
      vendor: "copilot",
      family: "gpt-4o",
    });
    console.log(`[HiveMind] LLM model selected: ${model?.name ?? 'NONE'}`);

    if (model) {
      const chatResponse = await model.sendRequest(messages, {}, token);
      for await (const fragment of chatResponse.text) {
        stream.markdown(fragment);
      }
    } else {
      stream.markdown(
        "No language model available. Here is the raw tool output:\n\n"
      );
      stream.markdown(toolContext || "No relevant context found.");
    }
  } catch (err: any) {
    console.log(`[HiveMind] Copilot LLM error: ${err.message}`);
    stream.markdown(`Error communicating with Copilot: ${err.message}\n\n`);
    if (toolContext) {
      stream.markdown("Here is the raw tool output:\n\n");
      stream.markdown(toolContext);
    }
  }

  return {};
}

// ---------------------------------------------------------------------------
// Status Bar
// ---------------------------------------------------------------------------

function createStatusBar(context: vscode.ExtensionContext): void {
  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    50
  );
  statusBar.text = "$(beaker) HiveMind";
  statusBar.tooltip = "HiveMind SRE Assistant";
  statusBar.command = "hivemind.showStatus";
  statusBar.show();
  context.subscriptions.push(statusBar);

  // Register show status command
  context.subscriptions.push(
    vscode.commands.registerCommand("hivemind.showStatus", () => {
      const status = handleStatus();
      vscode.window.showInformationMessage(
        `HiveMind: client=${getActiveClient()}`
      );
    })
  );

  // Periodic status bar update
  const interval = setInterval(() => {
    const syncPath = path.join(getProjectRoot(), "memory", "sync_status.json");
    if (fs.existsSync(syncPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(syncPath, "utf-8"));
        const health = data.healthy !== false ? "ok" : "!";
        statusBar.text = `$(beaker) HiveMind [${health}]`;
      } catch {
        // Ignore
      }
    }
  }, STATUS_BAR_INTERVAL_MS);

  context.subscriptions.push({ dispose: () => clearInterval(interval) });
}

// ---------------------------------------------------------------------------
// Extension Activation
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext) {
  const outputChannel = vscode.window.createOutputChannel("HiveMind");
  context.subscriptions.push(outputChannel);

  outputChannel.appendLine("HiveMind extension activated.");
  outputChannel.appendLine(`__dirname: ${__dirname}`);
  outputChannel.appendLine(`Project root: ${getProjectRoot()}`);
  outputChannel.appendLine(`Instructions path: ${getInstructionsPath()}`);
  outputChannel.appendLine(`Instructions exist: ${fs.existsSync(getInstructionsPath())}`);
  outputChannel.appendLine(`Tools dir exists: ${fs.existsSync(path.join(getProjectRoot(), "tools"))}`);
  outputChannel.appendLine(`Memory dir exists: ${fs.existsSync(path.join(getProjectRoot(), "memory"))}`);

  // 1. Detect and set active client
  detectAndSetClient();
  outputChannel.appendLine(`Active client: ${getActiveClient()}`);

  // 2. Register @hivemind chat participant (simplified)
  const participant = vscode.chat.createChatParticipant(
    PARTICIPANT_ID,
    handleChatRequest
  );
  participant.iconPath = vscode.Uri.joinPath(
    context.extensionUri,
    "icon.png"
  );
  context.subscriptions.push(participant);

  // 3. Register specialist agent participants
  const agentNames = [
    "hivemind-team-lead",
    "hivemind-devops",
    "hivemind-architect",
    "hivemind-security",
    "hivemind-investigator",
    "hivemind-analyst",
    "hivemind-planner",
  ];
  for (const agentName of agentNames) {
    const agentId = `hivemind.${agentName.replace("hivemind-", "")}`;
    const handler = createAgentHandler(agentName);
    const agentParticipant = vscode.chat.createChatParticipant(
      agentId,
      handler
    );
    agentParticipant.iconPath = vscode.Uri.joinPath(
      context.extensionUri,
      "icon.png"
    );
    context.subscriptions.push(agentParticipant);
  }

  // 4. Start status bar updater
  createStatusBar(context);

  // 5. Read active branch (no git commands — Python sync tools handle that)
  const activeBranch = getActiveBranch(getProjectRoot());
  outputChannel.appendLine(`Active branch: ${activeBranch}`);

  // 6. Check that instructions file exists
  if (!fs.existsSync(getInstructionsPath())) {
    vscode.window.showWarningMessage(
      "HiveMind: .github/copilot-instructions.md not found."
    );
  }
}

export function deactivate() {
  // Nothing to clean up
}
