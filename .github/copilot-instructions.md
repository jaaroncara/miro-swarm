# Copilot Instructions

## Project Overview

ABIE.ai (miro-swarm) is a swarm intelligence prediction engine. Users upload documents, describe a business scenario, and the engine generates AI agent personas that simulate stakeholder reactions across multiple rounds. Results feed into a ReACT-style report agent with optional MCP tool access.

## Commands

### Development
```bash
npm run setup:all          # install all deps (npm + uv sync)
npm run dev                # start backend + frontend concurrently
npm run backend            # backend only (port 5001)
npm run frontend           # frontend only (port 3000)
```

### Backend tests
```bash
cd backend
uv run pytest tests/                        # full suite
uv run pytest tests/test_llm.py             # single test file
uv run pytest tests/test_simulation_tasks.py -v  # verbose single file
```

### Docker
```bash
docker compose up -d --build               # full stack
docker compose up -d --build codex-proxy   # proxy only
```

### Release
```bash
git tag v1.0.x && git push origin v1.0.x  # triggers docker-image.yml CI
```

## Architecture

```
frontend/          Vue 3 + Vite + D3.js  →  http://localhost:3000
backend/
  run.py           Entry point → waitress (prod) / Flask dev server
  app/
    api/           Thin Flask blueprints: graph.py, simulation.py, report.py
    core/          WorkbenchSession + resource/task infrastructure
    resources/     Store adapters: ProjectStore, DocumentStore, KuzuGraphStore,
                   SimulationStore, SimulationRuntime, ReportStore
    tools/         Composable pipeline steps: GenerateOntologyTool,
                   BuildGraphTool, PrepareSimulationTool,
                   RunSimulationTool, GenerateReportTool
    services/      Domain logic: entity_extractor, graph_builder,
                   simulation_runner, report_agent, oasis_profile_generator…
    utils/         LLMClient, MCPManager, oasis_llm (CAMEL bridge), logger, retry
  scripts/         OASIS simulation subprocesses (Twitter, Reddit, parallel)
  mcp_servers/     example.py, task_server.py, combined.py
codex-proxy/       Node.js OpenAI-compatible proxy for Codex CLI in Docker
```

### Data flow

```
Upload → LLM ontology extraction → KuzuDB knowledge graph
       → Agent persona generation (OasisProfileGenerator)
       → OASIS simulation subprocess (scripts/run_*.py)  ←  MCP tools
       → Graph memory updates
       → ReACT report agent (report_agent.py)            ←  MCP tools
       → Interactive chat
```

## Key Conventions

### WorkbenchSession is the API entry point
API routes instantiate a `WorkbenchSession` and call its tool methods (e.g., `session.run_simulation_tool.start(...)`). Tools receive injected resource adapters; services are never called directly from routes.

### Tool vs. Service boundary
- **Tools** (`app/tools/`) orchestrate a pipeline step using resource adapters — they are the only callers of services.
- **Services** (`app/services/`) contain domain logic and are unaware of HTTP or session state.
- **Resources** (`app/resources/`) are thin store/adapter wrappers around persistence (KuzuDB, filesystem).

### KuzuDB singleton cache
KuzuDB allows only one `kuzu.Database` per directory path. `graph_storage.py` uses a module-level `_kuzu_cache` dict with double-checked locking (`get_cached_kuzu_storage()`). Never instantiate `KuzuDBStorage` directly — always go through this cache function.

### LLM client
`LLMClient` in `utils/llm_client.py` is the single abstraction for all LLM calls. It dispatches to OpenAI SDK, Anthropic SDK, or subprocess CLI based on `Config.LLM_PROVIDER`:
- `openai` / `anthropic` — SDK clients, require `LLM_API_KEY`
- `claude-cli` / `codex-cli` — subprocess, no API key needed
- All callers use `client.chat(messages=[...], response_format=...)` uniformly.

### MCP tool calling
`MCPManager` (`utils/mcp_manager.py`) is a singleton launched once at startup. Inside simulations, `oasis_llm.py` wraps CAMEL's model interface: it appends MCP tool schemas to the agent system prompt and runs a multi-round intercept loop when the model emits tool calls. Two execution modes (set via `TASK_EXECUTION_MODE`):
- `compatibility` — accepts XML `<tool_call>` blocks **and** OpenAI function-call format
- `mcp_only` — OpenAI function calls only

### OASIS simulation subprocess
`simulation_runner.py` spawns `scripts/run_twitter_simulation.py`, `run_reddit_simulation.py`, or `run_parallel_simulation.py` as a separate Python process. IPC goes through `simulation_ipc.py`. Don't attempt to call OASIS runner logic in-process.

### Python environment
The backend venv lives at `backend/.venv`. Always activate it with `cd backend && source .venv/bin/activate` or prefix commands with `uv run`. Never create a root-level `.venv`.

### Config
All configuration is in `app/config.py` (`Config` class), loaded from `.env` at project root. Boolean env vars accept `1/true/yes/on`. Use `Config.<ATTR>` everywhere; never call `os.environ.get()` directly in service code.

### Logging
All modules use `get_logger("mirofish.<module_path>")` from `utils/logger.py`. Logger names follow the Python package path (e.g., `"mirofish.api.simulation"`, `"mirofish.tools.run_simulation"`).

### Frontend API layer
`frontend/src/api/index.js` exports a preconfigured axios instance. All backend responses are expected in `{ success: bool, data: ..., error: ... }` shape. The 5-minute axios timeout is intentional for long-running ontology calls.

### Accepted file types
`pdf`, `md`, `txt`, `markdown` (enforced in `Config.ALLOWED_EXTENSIONS`).

### Graph backends
Default is `kuzu`. Set `GRAPH_BACKEND=json` to use the flat-file JSON backend (useful for debugging without KuzuDB). `graph_db.py` is the compatibility facade — prefer `GraphStorage` ABC in new code.
