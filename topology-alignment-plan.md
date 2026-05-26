# Topology Alignment Plan: Bridging ABIE.ai to the Research Paper

## Overview

This plan addresses the gaps between the current ABIE.ai (miro-swarm) implementation and the experimental design described in _"Personalization as an Emergent Property of Complex Systems in Organizational Behavior"_. The paper requires a **dynamic communication topology** among agents — where nodes remain fixed but edges and weights evolve based on simulation interactions — that can be analyzed via Topological Data Analysis (persistent homology, Betti numbers, platonic symmetry scores).

### Core Design Principle
> **Nodes are static; edges are dynamic.** The number of agents (nodes) is determined at document upload time and remains fixed throughout the simulation. Edges between agents and their weights are rewired in real-time based on MCP task actions triggered during the simulation.

---

## Current State Assessment

### What Already Exists and Works

| Component | Location | Status |
|-----------|----------|--------|
| Knowledge graph construction from documents | `tools/build_graph.py`, `services/graph_builder.py` | ✅ Complete |
| Agent persona generation from graph entities | `services/oasis_profile_generator.py` | ✅ Complete |
| Simulation runtime (OASIS subprocess) | `services/simulation_runner.py` | ✅ Complete |
| Episode ingestion during simulation | `services/graph_memory_updater.py` (`_send_batch_activities`) | ✅ Complete |
| LLM-driven edge relabeling (post-hoc) | `graph_memory_updater.py` (`analyze_and_mutate_graph`) | ✅ Complete |
| Topology analysis pipeline (post-simulation) | `services/topology_analysis/pipeline.py` | ✅ Complete |
| Persistent homology computation | `topology_analysis/homology.py` (uses `gudhi`) | ✅ Complete |
| Platonic symmetry score S(K) | `topology_analysis/symmetry.py` | ✅ Complete |
| Null model (M=200 permutations for δ_P) | `topology_analysis/nullmodel.py` | ✅ Complete |
| Hypothesis tests H1, H2, H3 | `topology_analysis/tests/h1.py`, `h2.py`, `h3.py` | ✅ Complete |
| Reward computation (CLV proxy) | `topology_analysis/reward.py` | ✅ Complete |
| Communication graph from task handoffs | `topology_analysis/graph.py` | ✅ Complete |
| Window-size sensitivity sweep | `topology_analysis/sweep.py` | ✅ Complete |

### Critical Gaps

| Gap | Impact | Priority |
|-----|--------|----------|
| **G1**: No real-time edge creation/rewiring during simulation | Agent interactions don't structurally modify the KuzuDB graph | P0 |
| **G2**: Edge weights are static (`weight=1.0` at build time) | Cannot compute meaningful filtration distances for TDA | P0 |
| **G3**: Knowledge graph and communication topology are separate | TDA runs on task store events, not on the KuzuDB graph | P1 |
| **G4**: No per-round topology snapshots during simulation | Can only analyze topology post-hoc, not track evolution | P1 |
| **G5**: `analyze_and_mutate_graph()` only relabels edges semantically | Doesn't create new edges, update weights, or delete edges | P1 |
| **G6**: No bridge between OASIS social actions and MCP task events | Social actions (posts, likes, follows) don't map to task coordination | P2 |
| **G7**: No online reward signal coupled to topology evolution | Reward is computed post-hoc only | P2 |

---

## Architecture: Target State

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Document Upload (Static Nodes)                       │
│                                                                              │
│  PDF/MD/TXT → EntityExtractor → KuzuDB Nodes (agents) → FIXED ROSTER       │
│                                                                              │
│  Outcome: N nodes determined. These become simulation agents.                │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                      Initial Graph Construction (Seed Edges)                  │
│                                                                              │
│  EntityExtractor relationships → Initial edges with weight=1.0               │
│  These seed edges represent document-implied relationships.                   │
│  They may be rewired, reweighted, or replaced during simulation.             │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    Simulation (Dynamic Edge Rewiring)                         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  Per Round:                                                      │        │
│  │                                                                  │        │
│  │  1. OASIS agents act (posts, comments, follows, likes)           │        │
│  │  2. Actions parsed → MCP task coordination events                │        │
│  │  3. EdgeRewiringEngine processes events:                          │        │
│  │     a. Identify agent→agent interaction pairs                    │        │
│  │     b. Increment edge weight w(i,j) += Δw per interaction type   │        │
│  │     c. Create new edges where none existed (first contact)       │        │
│  │     d. Apply decay: w(i,j) *= λ each round (use-it-or-lose-it)  │        │
│  │     e. Prune edges where w < ε (threshold)                       │        │
│  │  4. TopologySnapshotRecorder captures G_t per window             │        │
│  │  5. Reward R_t computed for the window                           │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  Writes: KuzuDB edge mutations, snapshots to disk, metrics.json              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    Post-Simulation Topology Analysis                          │
│                                                                              │
│  (Existing pipeline — now operates on richer, dynamically-evolved graph)     │
│                                                                              │
│  Snapshots → Symmetrize → Rips filtration → Persistent homology             │
│           → S(K) scores → Null model → H1/H2/H3 tests → Figures             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Implementation Plan

### Phase 1: Communication Topology Layer (New Service)

**Goal:** Create a dedicated "communication topology" representation that tracks agent-to-agent interaction edges with dynamic weights, separate from (but linked to) the knowledge graph.

#### 1.1 — Create `CommunicationTopology` data model

**File:** `backend/app/services/communication_topology.py` (new)

Define a lightweight in-memory + persistent data structure:

```
CommunicationTopology:
  - agent_ids: List[str]          # Fixed at simulation start (from graph nodes)
  - adjacency: Dict[(str,str), EdgeState]  # Sparse edge map
  - window_id: int                # Current time window
  - round_counter: int

EdgeState:
  - weight: float                 # Cumulative interaction weight
  - relation: str                 # Current semantic label (can change)
  - last_updated_round: int       # For decay computation
  - interaction_count: int        # Raw count of interactions
  - interaction_types: Dict[str, int]  # Breakdown by type (post, comment, follow, etc.)
  - created_at_round: int         # When this edge first appeared
```

**Design decisions:**
- Nodes are immutable after initialization (seeded from `EntityReader.filter_defined_entities()`)
- Edges are created on first interaction between two agents
- Edge weight is a composite score, not just a raw count
- The topology is persisted per-round as JSON snapshots for reproducibility

#### 1.2 — Define interaction weight schema

Map each `AgentActivity.action_type` to a weight increment:

| Action Type | Weight Δ | Rationale |
|-------------|----------|-----------|
| `CREATE_COMMENT` (on another agent's post) | +1.0 | Direct bilateral communication |
| `QUOTE_POST` (quoting another agent) | +0.8 | Directed engagement with attribution |
| `LIKE_POST` / `LIKE_COMMENT` (of another agent) | +0.3 | Lightweight affirmation signal |
| `DISLIKE_POST` / `DISLIKE_COMMENT` | +0.3 | Conflict signal (same weight, different label update) |
| `FOLLOW` | +0.5 | Attention commitment |
| `REPOST` | +0.6 | Amplification/alignment signal |
| `MUTE` | −0.5 | Withdrawal/disengagement |
| `CREATE_POST` (no target) | 0 | Broadcast, no specific edge |
| `SEARCH_POSTS` / `SEARCH_USER` | 0 | Information seeking, no bilateral edge |

**Edge decay per round:** `w(i,j) *= λ` where `λ = 0.95` (configurable via `Config`). This implements the "use-it-or-lose-it" principle — edges that are not reinforced decay toward zero.

**Edge pruning threshold:** If `w(i,j) < ε` (default `ε = 0.05`), the edge is pruned from the adjacency. This prevents the graph from becoming fully connected over long simulations.

#### 1.3 — Agent-to-agent pairing logic

Currently, `AgentActivity` records contain:
- `agent_name` (the acting agent)
- `action_args` which may contain:
  - `post_author_name` (for comments on posts)
  - `original_author_name` (for quotes/reposts)
  - `target_user_name` (for follows/mutes)
  - `comment_author_name` (for likes/dislikes on comments)

**Implementation:** Extract the target agent name from `action_args` based on `action_type`, look up both agents in the fixed roster, and apply the weight delta to edge `(actor, target)`.

If the target agent is not in the simulation roster (e.g., an external user in OASIS), the interaction is ignored for topology purposes.

---

### Phase 2: Real-Time Edge Rewiring Engine

**Goal:** Replace the current "batch episode text to storage" approach with structural graph mutations during the simulation.

#### 2.1 — Create `EdgeRewiringEngine` class

**File:** `backend/app/services/edge_rewiring_engine.py` (new)

This replaces/extends the role of `GraphMemoryUpdater._send_batch_activities()`:

```python
class EdgeRewiringEngine:
    """
    Processes agent activities in real-time and mutates the communication
    topology graph. Runs as a background thread alongside the simulation.
    """
    
    def __init__(self, topology: CommunicationTopology, config: RewiringConfig):
        ...
    
    def process_activity(self, activity: AgentActivity):
        """Process a single activity and update edges."""
        target = self._extract_target_agent(activity)
        if target and target in self.topology.agent_ids:
            delta = self._compute_weight_delta(activity)
            self.topology.update_edge(activity.agent_name, target, delta, activity.action_type)
    
    def end_round(self, round_num: int):
        """Called at end of each round. Applies decay and pruning."""
        self.topology.apply_decay(self.config.decay_lambda)
        self.topology.prune_edges(self.config.prune_threshold)
        self.topology.increment_round()
    
    def end_window(self, window_id: int):
        """Called at end of each time window. Captures snapshot for TDA."""
        self.topology.save_snapshot(window_id)
```

#### 2.2 — Integrate with `SimulationRunner._read_action_log()`

Currently at line 678 of `simulation_runner.py`:
```python
if graph_updater:
    graph_updater.add_activity_from_dict(action_data, platform)
```

**Change:** In addition to (or replacing) the existing `graph_updater`, pass each action to the `EdgeRewiringEngine`:
```python
if edge_rewiring_engine:
    edge_rewiring_engine.process_activity_from_dict(action_data, platform)
```

Also detect `round_end` events (already parsed at line 638) and call `edge_rewiring_engine.end_round(round_num)`.

#### 2.3 — Write back to KuzuDB

At the end of each time window (or at simulation end), the `CommunicationTopology` state is materialized into KuzuDB:

1. For each edge in the topology:
   - If edge exists in KuzuDB: call `storage.update_edge(edge_id, {"weight": new_weight, "relation": new_relation})`
   - If edge is new (created during simulation): call `storage.add_edge({source_id, target_id, relation, weight, ...})`
2. For edges that existed in KuzuDB but have been pruned (weight < ε):
   - Mark them with `weight=0` or a `pruned=True` attribute (rather than deleting, to preserve provenance)

**Important:** Nodes are NEVER added or removed. Only edges change.

---

### Phase 3: Bridge OASIS Social Actions to Task Coordination Events

**Goal:** The existing `topology_analysis/` pipeline reads from `SimulationTaskStore` (MCP task events). We need to either (a) emit MCP task events from OASIS actions, or (b) make the topology analysis pipeline consume the new `CommunicationTopology` snapshots directly.

#### 3.1 — Option A: Dual-source event adapter (Recommended)

Create an adapter that converts OASIS social actions into `CoordinationEvent` objects compatible with the existing `topology_analysis/events.py` schema:

**File:** `backend/app/services/topology_analysis/social_event_adapter.py` (new)

```python
def oasis_action_to_coordination_event(action: AgentActivity) -> Optional[CoordinationEvent]:
    """
    Convert an OASIS social action to a CoordinationEvent.
    
    Mapping:
    - CREATE_POST → task_created (the post is treated as a task/artifact)
    - CREATE_COMMENT → task_handoff (replying to someone = coordination handoff)
    - QUOTE_POST → task_referenced
    - FOLLOW → relationship_established
    - LIKE/DISLIKE → feedback_given
    """
```

This allows the existing `load_events()` → `window_events()` → `build_snapshot()` pipeline to work with both MCP task events AND OASIS social events.

#### 3.2 — Option B: Direct snapshot injection

Alternatively, since `Phase 2` already produces `TopologySnapshot`-compatible adjacency matrices per window, the post-simulation TDA pipeline can simply load those snapshots directly, bypassing the event→graph construction step entirely.

**Preferred approach:** Use **both** — the `EdgeRewiringEngine` produces live snapshots during simulation (Phase 2), and post-simulation the `topology_analysis/pipeline.py` loads these pre-computed snapshots instead of rebuilding from events.

---

### Phase 4: Per-Window Snapshot Persistence

**Goal:** Store the adjacency matrix at the end of each time window so the TDA pipeline can analyze topology evolution.

#### 4.1 — Snapshot format

Each window produces a file at:
```
data/<simulation_id>/topology/snapshots/window_<NNN>.json
```

Contents:
```json
{
  "window_id": 3,
  "round_start": 15,
  "round_end": 19,
  "agent_ids": ["agent-A", "agent-B", "agent-C", ...],
  "agent_types": {"agent-A": "DataScience", "agent-B": "Engineering", ...},
  "adjacency_directed": {
    "rows": [0, 0, 1, ...],
    "cols": [1, 2, 0, ...],
    "data": [3.2, 1.1, 2.5, ...],
    "shape": [5, 5]
  },
  "adjacency_symmetric": {
    "rows": [...],
    "cols": [...],
    "data": [...],
    "shape": [5, 5]
  },
  "metrics": {
    "edge_count": 8,
    "mean_weight": 2.1,
    "max_weight": 4.7,
    "density": 0.4
  }
}
```

This format is already compatible with `topology_analysis/graph.py`'s `TopologySnapshot` dataclass.

#### 4.2 — Modify `topology_analysis/pipeline.py` to load pre-computed snapshots

Add a `load_snapshots_from_disk()` function that can read the JSON snapshots produced in Phase 2, converting them back to `TopologySnapshot` objects. The pipeline's Phase 2 (`-- Build graphs + snapshots --`) becomes:

```python
if precomputed_snapshots_exist(output_dir):
    snapshots = load_precomputed_snapshots(output_dir)
else:
    # Fall back to building from events (existing behavior)
    snapshots = [build_snapshot(w, agent_ids) for w in windows]
```

---

### Phase 5: Configuration & Integration

#### 5.1 — New Config parameters

Add to `app/config.py`:

```python
# Communication topology rewiring
TOPOLOGY_DECAY_LAMBDA = float(os.environ.get("TOPOLOGY_DECAY_LAMBDA", "0.95"))
TOPOLOGY_PRUNE_THRESHOLD = float(os.environ.get("TOPOLOGY_PRUNE_THRESHOLD", "0.05"))
TOPOLOGY_SNAPSHOT_INTERVAL = int(os.environ.get("TOPOLOGY_SNAPSHOT_INTERVAL", "5"))  # rounds per window

# Interaction weight deltas
TOPOLOGY_WEIGHT_COMMENT = float(os.environ.get("TOPOLOGY_WEIGHT_COMMENT", "1.0"))
TOPOLOGY_WEIGHT_QUOTE = float(os.environ.get("TOPOLOGY_WEIGHT_QUOTE", "0.8"))
TOPOLOGY_WEIGHT_REPOST = float(os.environ.get("TOPOLOGY_WEIGHT_REPOST", "0.6"))
TOPOLOGY_WEIGHT_FOLLOW = float(os.environ.get("TOPOLOGY_WEIGHT_FOLLOW", "0.5"))
TOPOLOGY_WEIGHT_LIKE = float(os.environ.get("TOPOLOGY_WEIGHT_LIKE", "0.3"))
TOPOLOGY_WEIGHT_MUTE = float(os.environ.get("TOPOLOGY_WEIGHT_MUTE", "-0.5"))
```

#### 5.2 — Wire into `RunSimulationTool`

When `enable_graph_memory_update=True`:
1. Initialize `CommunicationTopology` with agent roster from graph nodes
2. Initialize `EdgeRewiringEngine` with the topology and config
3. Pass the engine to `SimulationRunner.start_simulation()` (or register via a manager similar to `GraphMemoryManager`)
4. Engine processes actions in real-time alongside the existing `GraphMemoryUpdater`

#### 5.3 — Wire into `AnalyzeTopologyTool`

After simulation completes:
1. Check for pre-computed snapshots in `data/<sim_id>/topology/snapshots/`
2. If found, load them directly into the TDA pipeline
3. Run persistent homology, symmetry scores, null model, and H1/H2/H3 tests as before

---

### Phase 6: Semantic Edge Mutation (Enhanced)

**Goal:** Enhance `analyze_and_mutate_graph()` to support the paper's framework while maintaining backward compatibility.

#### 6.1 — Enrich the LLM mutation prompt

Currently the mutation prompt only handles relation type changes. Enhance it to also:
- Suggest new edges between agents that interacted heavily but have no existing knowledge-graph edge
- Suggest edge weight adjustments based on qualitative analysis of transcript content
- Distinguish between **structural mutations** (the paper's concern: topology changes) and **semantic mutations** (label changes)

#### 6.2 — Conflict/alignment edge typing

The paper's framework benefits from typed edges that capture the *nature* of the interaction:

| Edge Type | Meaning | TDA Interpretation |
|-----------|---------|-------------------|
| `COLLABORATES_WITH` | Active coordination on shared goals | Strong simplex-forming |
| `CONFLICTS_WITH` | Disagreement/blocking behavior | Negative edge (excluded from complex) |
| `DELEGATES_TO` | Directed task handoff | Directed edge (asymmetric weight) |
| `ALIGNED_WITH` | Shared perspective, no direct coordination | Weak simplex-forming |
| `MONITORS` | Information asymmetry (one watches the other) | Low-weight directed edge |

---

### Phase 7: Validation & Testing

#### 7.1 — Unit tests for `CommunicationTopology`

- Test that nodes cannot be added/removed after initialization
- Test weight increments, decay, and pruning
- Test edge creation on first interaction
- Test snapshot serialization/deserialization round-trip

#### 7.2 — Integration tests for `EdgeRewiringEngine`

- Mock simulation action log → verify correct edge state after N rounds
- Verify decay reduces weights over time without interaction
- Verify pruning removes below-threshold edges
- Verify snapshots are written at correct window boundaries

#### 7.3 — End-to-end pipeline test

- Small synthetic simulation (3 agents, 5 rounds)
- Verify: static nodes, dynamic edges, weight evolution, snapshot production
- Verify: TDA pipeline consumes snapshots and produces valid H1/H2/H3 results
- Compare with existing post-hoc analysis to confirm alignment

#### 7.4 — Regression test

- Ensure existing `analyze_and_mutate_graph()` still works (backward compatibility)
- Ensure existing `topology_analysis/pipeline.py` still works when no pre-computed snapshots exist
- Ensure the OASIS simulation subprocess is not affected by the new engine running in parallel

---

## Dependency Graph

```
Phase 1 (CommunicationTopology data model)
    │
    ├──► Phase 2 (EdgeRewiringEngine)
    │        │
    │        ├──► Phase 4 (Snapshot persistence)
    │        │        │
    │        │        └──► Phase 5.3 (Wire into AnalyzeTopologyTool)
    │        │
    │        └──► Phase 5.2 (Wire into RunSimulationTool)
    │
    ├──► Phase 3 (Social event adapter)
    │
    └──► Phase 5.1 (Config parameters)

Phase 6 (Enhanced semantic mutation) — independent, can be done in parallel

Phase 7 (Testing) — depends on all implementation phases
```

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `backend/app/services/communication_topology.py` | **CREATE** | CommunicationTopology + EdgeState data model |
| `backend/app/services/edge_rewiring_engine.py` | **CREATE** | Real-time edge rewiring logic |
| `backend/app/services/topology_analysis/social_event_adapter.py` | **CREATE** | OASIS action → CoordinationEvent converter |
| `backend/app/services/topology_analysis/pipeline.py` | **MODIFY** | Load pre-computed snapshots if available |
| `backend/app/services/topology_analysis/graph.py` | **MODIFY** | Add snapshot load/save from JSON format |
| `backend/app/services/simulation_runner.py` | **MODIFY** | Integrate EdgeRewiringEngine alongside GraphMemoryUpdater |
| `backend/app/services/graph_memory_updater.py` | **MODIFY** | Enhance `analyze_and_mutate_graph()` prompt + add weight-aware mutations |
| `backend/app/tools/run_simulation.py` | **MODIFY** | Initialize CommunicationTopology + EdgeRewiringEngine |
| `backend/app/tools/analyze_topology.py` | **MODIFY** | Support pre-computed snapshot loading |
| `backend/app/config.py` | **MODIFY** | Add topology rewiring config parameters |
| `backend/tests/test_communication_topology.py` | **CREATE** | Unit tests for Phase 1 |
| `backend/tests/test_edge_rewiring_engine.py` | **CREATE** | Unit tests for Phase 2 |
| `backend/tests/test_social_event_adapter.py` | **CREATE** | Unit tests for Phase 3 |
| `backend/tests/test_topology_integration.py` | **CREATE** | End-to-end integration test |

---

## Key Invariants to Maintain

1. **Node count is fixed.** After `BuildGraphTool` completes, no new nodes are added. The simulation operates on a fixed agent roster derived from document entities.

2. **Edges are bilateral.** Every interaction between agent A and agent B updates edge (A,B). The adjacency is stored directed but symmetrized for TDA via `max(w_ij, w_ji)`.

3. **Weight is monotonically meaningful.** Higher weight = stronger/more frequent interaction. The filtration distance `d = 1 - w_normalized` means strongly connected agents appear first in the Rips complex.

4. **Decay prevents trivial full-connectivity.** Without decay, any long-running simulation would produce a complete graph. The decay factor `λ` ensures only actively-maintained relationships persist.

5. **Backward compatibility.** The existing `GraphMemoryUpdater` episode ingestion continues to work. The `EdgeRewiringEngine` is an additional layer, not a replacement.

6. **Deterministic reproducibility.** Given the same simulation action log (JSONL files), the topology evolution must be perfectly reproducible. No randomness in the rewiring engine.

---

## Alignment with Paper Equations

| Paper Reference | Implementation Target |
|-----------------|----------------------|
| Eq. 1: G(V, E, W) directed weighted graph | `CommunicationTopology.adjacency` — directed, weighted by interaction frequency |
| Eq. 2: w_sym = max(w_ij, w_ji) | `topology_analysis/graph.py: symmetrize()` — already implemented |
| Eq. 3: d_ij = 1 − w̄_ij (sublevel filtration) | `topology_analysis/complex.py: build_filtration_matrix()` — already implemented |
| Eq. 4: Rips complex K at dimension k | `topology_analysis/complex.py: create_simplex_tree_from_adjacency()` — already implemented |
| Eq. 5: Betti numbers b_0, b_1, ..., b_k | `topology_analysis/homology.py: compute_persistence()` — already implemented |
| Eq. 6: S(K) kernel alignment score | `topology_analysis/symmetry.py: compute_symmetry_score()` — already implemented |
| Eq. 7: δ_P permutation threshold | `topology_analysis/nullmodel.py: compute_null_thresholds_for_snapshots()` — already implemented |
| Eq. 8: R_t composite reward | `topology_analysis/reward.py: compute_window_reward()` — already implemented |
| H1: higher-order > pairwise | `topology_analysis/tests/h1.py` — already implemented |
| H2: symmetry → reward | `topology_analysis/tests/h2.py` — already implemented |
| H3: complexity → coordination | `topology_analysis/tests/h3.py` — already implemented |

**The TDA math is already built.** The gap is exclusively in **feeding the TDA pipeline a dynamically-evolved communication topology** rather than a static or post-hoc-reconstructed one.

---

## Estimated Effort

| Phase | Complexity | Estimated LOC | Dependencies |
|-------|-----------|---------------|--------------|
| Phase 1 | Medium | ~200 | None |
| Phase 2 | High | ~300 | Phase 1 |
| Phase 3 | Low | ~100 | Phase 1 |
| Phase 4 | Medium | ~150 | Phase 2 |
| Phase 5 | Low | ~80 | Phases 1-4 |
| Phase 6 | Medium | ~100 | Independent |
| Phase 7 | High | ~400 | All phases |

**Total estimated new code:** ~1,330 lines (excluding tests: ~930 lines)

---

## Open Questions for Decision

1. **Should the communication topology replace the knowledge graph edges, or coexist as a separate layer?**
   - Recommendation: Coexist. The knowledge graph captures document-derived relationships; the communication topology captures simulation-observed interactions. Both are valuable for different analyses.

2. **Should decay apply uniformly or per-edge-type?**
   - Recommendation: Uniform decay initially (simplicity), with per-type decay as a future enhancement.

3. **Should the `EdgeRewiringEngine` write to KuzuDB every round or only at window boundaries?**
   - Recommendation: Write snapshots to disk every window, write to KuzuDB only at simulation end (minimizes I/O contention with the OASIS subprocess).

4. **How should negative interactions (DISLIKE, MUTE) be handled topologically?**
   - Recommendation: DISLIKE still adds edge weight (interaction is interaction). MUTE subtracts weight (active disengagement). Negative edges are excluded from the Rips complex (they don't form simplices). This means persistent conflict between two agents eventually removes them from shared cliques — a desirable property.

5. **Should the topology snapshots also be persisted into KuzuDB, or only as flat files?**
   - Recommendation: Flat files (JSON) for snapshots. KuzuDB for the final state. This matches the existing `topology_analysis/` pattern.
