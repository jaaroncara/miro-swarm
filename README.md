# ABIE.ai (swarm analytics)

A swarm intelligence prediction engine designed for simulating business scenarios to model outcomes. Upload documents describing any scenario, market shift, or business strategy, and the engine simulates thousands of AI agents (acting as customers, competitors, employees, or stakeholders) reacting in a networked environment to predict how events and decisions might unfold.

> Built on a fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) — adapted for business scenario modeling, local graph storage, and expanded LLM provider support.

## What it does

1. **Upload business context** — Product launch plans, market research, policy drafts, financial reports, news articles, or internal memos (PDFs, markdown, text files)
2. **Describe a scenario** — Prompt in natural language (e.g., "Model market response to this new product launch over the next 60 days" or "Simulate stakeholder reactions to this strategic pivot")
3. **The engine builds a business model** — Extracts key topics, statistics, and relationships into a knowledge graph — then generates AI agent personas with distinct roles, priorities, opinions, and personalities
4. **Agents simulate team interactions** — A multi-agent simulation where personas post, reply, debate, and adapt to the incoming scenario as various stakeholders
5. **Get a business report** — An AI analyst reviews the aggregate simulation data to produce actionable findings. You can chat with the report agent or interview individual simulated stakeholders for deeper insights.

## Changes from upstream

| Area | Upstream | This fork |
|------|----------|-----------|
| **Use Case** | Social media prediction | Business scenario and outcome modeling |
| **Language** | English Language UI + prompts | Full English (60+ files translated) |
| **LLM providers** | OpenAI, Anthropic, Claude CLI, Codex CLI |
| **Graph database** | Hosted graph service | Local KuzuDB (embedded, free) |
| **Entity extraction** | Managed extraction pipeline | LLM-based extraction (uses your own model) |
| **Auth** | Requires API keys | Can use Claude Code or Codex CLI subscriptions (no separate API cost) |
| **MCP tools** | N/A | Agents can call external tools (DBs, APIs) via MCP during simulation |

## Quick start

### Prerequisites

- Node.js 18+
- Python 3.11-3.12
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Setup

```bash
cp .env.example .env
# Edit .env — pick your LLM provider (see below)
npm run setup:all
npm run dev
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:5001

### Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Docker builds the Vue frontend, serves it from the Flask app, and exposes the combined app on port `5001` inside the container.

## LLM providers

Set `LLM_PROVIDER` in `.env`:

| Provider | Config | Cost |
|----------|--------|------|
| `claude-cli` | Just set `LLM_PROVIDER=claude-cli` | Uses your Claude Code subscription |
| `codex-cli` | Just set `LLM_PROVIDER=codex-cli` | Uses your Codex CLI subscription |
| `openai` | Set `LLM_API_KEY` + `LLM_MODEL_NAME` | Pay-per-token |
| `anthropic` | Set `LLM_API_KEY` + `LLM_MODEL_NAME` | Pay-per-token |

```env
# Example: use Codex CLI (no API key needed)
LLM_PROVIDER=codex-cli

# Example: use OpenAI API
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL_NAME=gpt-4o-mini
```

## Using Codex CLI

For Docker deployments, the app now routes Codex CLI traffic through a local OpenAI-compatible sidecar service at `codex-proxy`. The container talks to `http://codex-proxy:11435/v1`, and the proxy translates each `/v1/chat/completions` request into `codex exec --skip-git-repo-check` with bounded concurrency.

`docker-compose.yml` already wires this up for the Docker stack:

-  runs with `LLM_PROVIDER=openai`
- `LLM_BASE_URL=http://codex-proxy:11435/v1`
- `LLM_API_KEY=codex`
- `LLM_MODEL_NAME=codex`
- `codex-proxy` uses `CODEX_PROXY_WORKERS=4` by default

To use it:

```bash
cp .env.example .env
docker compose up -d --build codex-proxy
curl http://localhost:11435/health
docker compose up -d
```

The proxy container mounts the host Codex binary and `~/.codex` auth state, so make sure Codex CLI is installed and authenticated on the host first. The legacy `LLM_PROVIDER=codex-cli` path remains available outside Docker as a fallback, but the proxy is the recommended Docker path because it queues requests instead of cold-starting an unbounded number of CLI subprocesses.

## Architecture

```
frontend/          Vue 3 + Vite + D3.js (graph visualization)
backend/
  app/
    api/           Thin Flask REST endpoints (graph, simulation, report)
    core/          Workbench session, session registry, resource loader, tasks
    resources/     Adapters for projects, documents, Kuzu, simulations, reports
    tools/         Composable workbench operations (ingest, build, prepare, run, report)
    services/
      graph_storage.py     GraphStorage abstraction + KuzuDB/JSON backends
      graph_db.py          Compatibility facade over per-graph storage backends
      entity_extractor.py  LLM-based entity/relationship extraction
      graph_builder.py     Ontology → graph pipeline
      simulation_runner.py OASIS multi-agent simulation (subprocess)
      report_agent.py      ReACT agent with tool-calling for reports
      graph_tools.py       Search, interview, and analysis tools
    utils/
      llm_client.py        Multi-provider LLM client (OpenAI/Anthropic/CLI)
      mcp_manager.py       MCP client singleton (tool discovery, execution, sync bridge)
  mcp_servers/             Example / custom MCP tool servers
  scripts/                 OASIS simulation runner scripts (Slack + Email)
```

Workbench session metadata is persisted under `backend/uploads/workbench_sessions/`, and long-running task state is persisted under `backend/uploads/tasks/`.

The backend is being refactored toward a pi-style shape: one workbench session core, pluggable resource adapters, composable tools, and thin API shells.

## How the pipeline works

```
Document upload → LLM ontology extraction → Knowledge graph (GraphStorage → KuzuDB by default)
    → Entity filtering → Agent persona generation (Stakeholders, Competitors, etc.)
    → OASIS behavioral simulation (Slack / Email)  ←──  MCP tools (optional)
    → Graph memory updates → Report generation (ReACT agent)  ←──  MCP tools (optional)
    → Interactive chat with report agent or individual agents
```

## MCP tool integration

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) lets the simulated agents call external tools — database queries, API lookups, file operations, or any custom capability — during a simulation run or report generation, without changing any agent code.

### How it works

1. An **MCP server** exposes tools over stdio. The included example server (`backend/mcp_servers/example.py`) provides `lookup_sales_data` and `get_weather`; replace or extend it with your own tools.
2. **MCPManager** (`backend/app/utils/mcp_manager.py`) launches the server as a subprocess, discovers available tools at startup, and exposes them to agents.
3. During **simulation**, agents see the tool catalog in their system prompt and can invoke tools via an XML `<tool_call>` format. A multi-round loop in `oasis_llm.py` intercepts these calls, executes them through MCP, and feeds results back before the agent's final response.
4. During **report generation**, the ReACT agent in `report_agent.py` sees MCP tools registered with an `mcp__` prefix alongside the built-in tools (graph search, interview, etc.) and can call them in its reasoning loop.

### Setup

Add these to your `.env`:

```env
# Enable MCP tool support
MCP_SERVER_ENABLED=true
MCP_SERVER_CMD=python3
MCP_SERVER_ARGS=mcp_servers/example.py

# Optional tuning
MCP_TOOL_CALL_TIMEOUT=30    # seconds per tool call (default: 30)
MCP_MAX_TOOL_ROUNDS=3       # max tool-call rounds per LLM turn (default: 3)
```

### Writing a custom MCP server

Create a Python file that uses the `FastMCP` helper from the MCP SDK:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-tools")

@mcp.tool()
def query_crm(account_id: str) -> str:
    """Look up account details in the CRM."""
    # your logic here
    return f"Account {account_id}: ..."

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

Then point your `.env` at it:

```env
MCP_SERVER_CMD=python3
MCP_SERVER_ARGS=path/to/my_server.py
```

All tools the server registers are automatically discovered and made available to every simulation agent and the report agent.

### Disabling MCP

Set `MCP_SERVER_ENABLED=false` (or omit it). The simulation and report pipelines fall back to their default behavior with zero overhead.

## Acknowledgments

- [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj — original project
- [OASIS](https://github.com/camel-ai/oasis) by CAMEL-AI — multi-agent social simulation framework
- [KuzuDB](https://github.com/kuzudb/kuzu) — embedded graph database

## License

AGPL-3.0
License
