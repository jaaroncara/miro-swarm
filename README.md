# ABIE.ai (swarm analytics)

A swarm intelligence prediction engine designed for simulating business scenarios to model outcomes. Upload documents describing any scenario, market shift, or business strategy, and the engine simulates thousands of AI agents (acting as customers, competitors, employees, or stakeholders) reacting in a networked environment to predict how events and decisions might unfold.

The engine also includes a **topology analysis pipeline** that treats each completed simulation as a source of time-indexed coordination data — building a communication graph from MCP task-tool interactions, running Topological Data Analysis (TDA), and surfacing emergent structural properties (Betti numbers, platonic symmetry scores, persistent homology) for research or advanced diagnostics.

> Built on a fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) — adapted for business scenario modeling, local graph storage, and expanded LLM provider support.

## What it does

1. **Upload business context** — Product launch plans, market research, policy drafts, financial reports, news articles, or internal memos (PDFs, markdown, text files)
2. **Describe a scenario** — Prompt in natural language (e.g., "Model market response to this new product launch over the next 60 days" or "Simulate stakeholder reactions to this strategic pivot")
3. **The engine builds a business model** — Extracts key topics, statistics, and relationships into a knowledge graph — then generates AI agent personas with distinct roles, priorities, opinions, and personalities
4. **Agents simulate team interactions** — A multi-agent simulation where personas post, reply, debate, and adapt to the incoming scenario as various stakeholders
5. **Get a business report** — An AI analyst reviews the aggregate simulation data to produce actionable findings. You can chat with the report agent or interview individual simulated stakeholders for deeper insights.
6. **Analyze emergent topology** *(optional)* — Run post-simulation topology analysis on the MCP coordination graph: extract time-windowed communication networks, compute persistent homology (Betti numbers, persistence diagrams), platonic symmetry scores, and statistical hypothesis tests (H1/H2/H3) with publication-ready figures.

## Changes from upstream

| Area | Upstream | This fork |
|------|----------|-----------|
| **Use Case** | Decision prediction | Business scenario and outcome modeling |
| **Language** | English Language UI + prompts | Full English (60+ files translated) |
| **LLM providers** | OpenAI, Anthropic, Claude CLI, Codex CLI |
| **Graph database** | Hosted graph service | Local KuzuDB (embedded, free) |
| **Entity extraction** | Managed extraction pipeline | LLM-based extraction (uses your own model) |
| **Auth** | Requires API keys | Can use Claude Code or Codex CLI subscriptions (no separate API cost) |
| **MCP tools** | Take real actions | Agents can call external tools (DBs, APIs) via MCP during simulation |

## Quick start

### Prerequisites

- Node.js 18+
- Python 3.12 recommended (`3.11` supported)
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Setup

```bash
cp .env.example .env
# Edit .env — pick your LLM provider (see below)
npm run setup:all
npm run dev
```

The backend Python environment is intentionally created at `backend/.venv`. Use that environment for all local backend commands:

```bash
cd backend
source .venv/bin/activate
```

Avoid creating a second repo-root `.venv`; the backend project metadata and workspace settings are pinned to `backend/.venv`.

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
    tools/         Composable workbench operations:
                     build_graph, generate_ontology, prepare_simulation,
                     run_simulation, generate_report, analyze_topology (NEW)
    services/
      graph_storage.py          GraphStorage abstraction + KuzuDB/JSON backends
      graph_db.py               Compatibility facade over per-graph storage backends
      entity_extractor.py       LLM-based entity/relationship extraction
      graph_builder.py          Ontology → graph pipeline
      simulation_runner.py      OASIS multi-agent simulation (subprocess)
      report_agent.py           ReACT agent with tool-calling for reports
      graph_tools.py            Search, interview, and analysis tools
      topology_analysis/        (NEW) Post-simulation TDA pipeline:
        events.py               Load + window MCP task events from SimulationTaskStore
        graph.py                Build directed weighted G_t per window, symmetrize
        complex.py              gudhi Rips complex on symmetrized adjacency
        homology.py             Persistent homology → Betti numbers, diagrams, k*
        symmetry.py             Platonic symmetry score S(K) (kernel alignment)
        nullmodel.py            M=200 weight permutations → δ_P thresholds
        reward.py               Synthetic R_t from task telemetry
        figures.py              Publication-ready Figures 1–4 (matplotlib)
        pipeline.py             analyze(simulation_id) orchestrator
        tests/h1.py             H1: density-matched higher-order vs pairwise
        tests/h2.py             H2: S monotonicity + structural features
        tests/h3.py             H3: OLS regression of R on topological predictors
    utils/
      llm_client.py        Multi-provider LLM client (OpenAI/Anthropic/CLI)
      mcp_manager.py       MCP client singleton (tool discovery, execution, sync bridge)
  mcp_servers/             Example / custom MCP tool servers
  scripts/                 OASIS simulation runner scripts (Slack + Email)
```

Workbench session metadata is persisted under `backend/uploads/workbench_sessions/`, and long-running task state is persisted under `backend/uploads/tasks/`. Topology analysis artifacts are written to `backend/data/<simulation_id>/topology/`.

## How the pipeline works

```
Document upload → LLM ontology extraction → Knowledge graph (GraphStorage → KuzuDB by default)
    → Entity filtering → Agent persona generation (types & counts emerge from the KG)
    → OASIS behavioral simulation (Slack / Email)  ←──  MCP tools (optional)
    → Graph memory updates → Report generation (ReACT agent)  ←──  MCP tools (optional)
    → Interactive chat with report agent or individual agents
    → Topology analysis (optional) ─────────────────────────────────────────────────────┐
         MCP task events → G_t (windowed graph) → Rips complex → persistent homology    │
         → Betti curves, S(K), δ_P null model, R_t reward → H1/H2/H3 tests + Figures   │
         → backend/data/<simulation_id>/topology/ ◄───────────────────────────────────────┘
```

## Topology Analysis

The topology analysis pipeline runs **after** a simulation completes. It reads the MCP `task_server` coordination log from `SimulationTaskStore`, builds a time-indexed communication graph from observed task-handoff patterns, and computes Topological Data Analysis (TDA) metrics over the sequence of snapshots.

### What it computes

| Metric | Description |
|--------|-------------|
| **G_t** | Directed weighted communication graph per time window (observed, not imposed) |
| **Betti numbers** b₀, b₁, ..., b_k | Connected components, loops, and higher-order voids in the coordination complex |
| **Persistence diagrams** D_k | Birth/death filtration values per dimension |
| **k\*** | Max persistent dimension with features above the null threshold |
| **S(K)** | Platonic symmetry score — kernel alignment of K against a maximally-symmetric circulant reference |
| **δ_P** | Null-model significance threshold (M=200 weight permutations, 95th percentile) |
| **R_t** | Synthetic observed reward from task telemetry (completion rate, type coverage, latency) |
| **H1** | Higher-order interactions vs. pairwise baseline after Mahalanobis density matching |
| **H2** | S(K) monotonicity, top-q vs. bottom-q, b₀=1, single dominant high-dim feature |
| **H3** | OLS regression: R_t ~ β₀ + β₁·TP1 + β₂·TP2 + β₃·\|E\| + β₄·k* |

### Running topology analysis

```python
from app.services.topology_analysis.pipeline import analyze

results = analyze("your-simulation-id")
# Outputs land in: backend/data/<simulation_id>/topology/
#   snapshots/          sparse adjacency matrices per window (.npz + _meta.json)
#   metrics.json        H1/H2/H3 results + summary stats
#   figures/            fig1_reward.png, fig2_betti.png, fig3_persistence.png, fig4_symmetry.png
```

Or via the `WorkbenchSession` tool (runs in the background):

```python
session.analyze_topology_tool.start("your-simulation-id")
```

Or via the REST API:

```bash
# Start analysis (returns task_id for polling)
curl -X POST http://localhost:5001/api/topology/analyze \
  -H "Content-Type: application/json" \
  -d '{"simulation_id": "your-simulation-id"}'

# Poll status
curl http://localhost:5001/api/topology/status/<task_id>

# Retrieve results
curl http://localhost:5001/api/topology/results/your-simulation-id
```

### Window-size sensitivity sweep

Before committing to a `TOPOLOGY_WINDOW_SIZE`, run the sensitivity sweep to see how results vary:

```bash
# CLI sweep (from backend/)
uv run python -m app.services.topology_analysis.sweep your-simulation-id \
  --sizes 3 5 7 10 15 \
  --null-m 50

# Report is written to: backend/data/<sim_id>/topology/sweep/sweep_report.json
```

```python
# Python API
from app.services.topology_analysis.sweep import run_window_sweep

report = run_window_sweep("your-simulation-id", window_sizes=[3, 5, 7, 10, 15])
# report["sensitivity"] shows coefficient of variation for H1/H3 metrics
```

The sweep prints a table of H1 Cohen's d, H3 R², and H2 pass/fail for each window size, plus a sensitivity summary indicating whether results are stable across window choices.

### Configuration

Add these to your `.env` to tune the analysis:

```env
# Number of simulation rounds per time window (default: 5)
TOPOLOGY_WINDOW_SIZE=5

# Null-model permutations for δ_P threshold (default: 200)
TOPOLOGY_NULL_MODEL_M=200

# Max simplex dimension, k (default: 6)
TOPOLOGY_MAX_DIM=6

# Reward weights: R_t = α·completion + β·type_coverage_bonus² − γ·latency
TOPOLOGY_REWARD_ALPHA=1.0
TOPOLOGY_REWARD_BETA=1.0
TOPOLOGY_REWARD_GAMMA=0.1
```

### Key design decisions

- **G_t is observed, not optimized.** The communication graph emerges from which agents jointly touched tasks via MCP tool calls — it is never controlled or rewired by the analysis.
- **Entity types are document-driven.** The population of agents and their types come entirely from the knowledge graph extracted from your uploaded documents. There are no preset role lists.
- **Coordination events = MCP tool invocations.** Any call to `task_server` tools (`offer_task`, `accept_task`, `start_task`, etc.) carrying a shared `task_id` constitutes an edge in G_t. Co-participation by k+1 distinct agents on one task defines a k-simplex.
- **Sparse by default.** G_t is stored as `scipy.sparse.csr_matrix`; the clique complex caps at `k=6` to keep memory bounded at large agent populations.

## MCP tool integration

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) lets the simulated agents call external tools — database queries, API lookups, file operations, or any custom capability — during a simulation run or report generation, without changing any agent code.

### How it works

1. An **MCP server** exposes tools over stdio. This repo includes:
  - `backend/mcp_servers/example.py` for business data and web-research tools
  - `backend/mcp_servers/task_server.py` for simulation task tools
  - `backend/mcp_servers/combined.py` to expose both sets together (recommended default)
2. **MCPManager** (`backend/app/utils/mcp_manager.py`) launches the server as a subprocess, discovers available tools at startup, and exposes them to agents.
3. During **simulation**, agents see the tool catalog in their system prompt and can invoke tools via an XML `<tool_call>` format. A multi-round loop in `oasis_llm.py` intercepts these calls, executes them through MCP, and feeds results back before the agent's final response.
4. During **report generation**, the ReACT agent in `report_agent.py` sees MCP tools registered with an `mcp__` prefix alongside the built-in tools (graph search, interview, etc.) and can call them in its reasoning loop.

### Setup

Add these to your `.env`:

```env
# Enable MCP tool support
MCP_SERVER_ENABLED=true
MCP_SERVER_CMD=python3
MCP_SERVER_ARGS=-m,mcp_servers.combined

# Optional tuning
MCP_TOOL_CALL_TIMEOUT=30    # seconds per tool call (default: 30)
MCP_MAX_TOOL_ROUNDS=3       # max tool-call rounds per LLM turn (default: 3)

# Task lifecycle safety policy
TASK_AUTO_ACCEPT_OFFERS=true
TASK_AUTO_ACCEPT_NOTE=Auto-accepted on assignment so work can start immediately.
TASK_MIN_COMPLETION_ROUNDS=2
TASK_REJECT_LATE_ASSIGNMENTS=true
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

### Updating docker and pushing images
git tag v1.0.x && git push origin v1.0.x

## Acknowledgments

- [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj — original project
- [OASIS](https://github.com/camel-ai/oasis) by CAMEL-AI — multi-agent social simulation framework
- [KuzuDB](https://github.com/kuzudb/kuzu) — embedded graph database

## License

AGPL-3.0
License
