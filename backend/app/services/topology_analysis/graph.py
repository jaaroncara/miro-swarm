"""Build directed weighted communication graph G_t per time window.

Constructs a directed weighted adjacency matrix from observed task-coordination
handoff patterns within a TimeWindow. The graph is *observed* from MCP task
coordination events — it is not imposed by an optimizer.

Each edge (i → j) with weight w means agent i handed off to agent j exactly w
times during the window across all tasks.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.sparse

from .events import CoordinationEvent, TimeWindow, get_actors_per_task
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.graph")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TopologySnapshot:
    """Immutable snapshot of the communication topology for a single window."""

    window_id: int
    adjacency: scipy.sparse.csr_matrix  # directed weighted
    adjacency_symmetric: scipy.sparse.csr_matrix  # undirected, w_sym = max(w_ij, w_ji)
    agent_ids: list[str]  # ordered list mapping matrix indices → agent identifiers
    agent_types: dict[str, str] = field(default_factory=dict)  # agent_id → entity_type (populated externally)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_directed_graph(
    window: TimeWindow,
    agent_ids: list[str],
) -> scipy.sparse.csr_matrix:
    """Build a directed weighted adjacency matrix from task handoff sequences.

    For each task in *window*, events are ordered by timestamp.  Each
    consecutive pair (actor_prev, actor_next) on the same task contributes +1
    to edge weight w(actor_prev → actor_next).

    Parameters
    ----------
    window : TimeWindow
        The time window containing coordination events.
    agent_ids : list[str]
        Fixed ordered roster of agent identifiers.  Determines matrix shape and
        index mapping.  Agents appearing in events but absent from *agent_ids*
        are silently ignored.

    Returns
    -------
    scipy.sparse.csr_matrix
        Sparse adjacency matrix of shape (n, n) where n = len(agent_ids).
    """
    n = len(agent_ids)
    agent_index = {aid: idx for idx, aid in enumerate(agent_ids)}

    # Group events by task_id, then sort each group by timestamp
    tasks: dict[str, list[CoordinationEvent]] = defaultdict(list)
    for event in window.events:
        tasks[event.task_id].append(event)

    # Count handoffs
    rows: list[int] = []
    cols: list[int] = []
    data: list[int] = []
    edge_counts: dict[tuple[int, int], int] = defaultdict(int)

    for task_id, events in tasks.items():
        # Sort by timestamp to get the handoff sequence
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Extract consecutive actor pairs
        for i in range(len(sorted_events) - 1):
            prev_actor = sorted_events[i].actor
            next_actor = sorted_events[i + 1].actor

            # Skip self-loops and unknown agents
            if prev_actor == next_actor:
                continue
            if prev_actor not in agent_index or next_actor not in agent_index:
                continue

            src = agent_index[prev_actor]
            dst = agent_index[next_actor]
            edge_counts[(src, dst)] += 1

    # Build sparse matrix from accumulated counts
    for (src, dst), weight in edge_counts.items():
        rows.append(src)
        cols.append(dst)
        data.append(weight)

    adjacency = scipy.sparse.csr_matrix(
        (np.array(data, dtype=np.float64), (np.array(rows), np.array(cols))),
        shape=(n, n),
    )

    logger.debug(
        "Built directed graph: %d agents, %d edges, %d total handoffs",
        n,
        len(data),
        sum(data),
    )
    return adjacency


# ---------------------------------------------------------------------------
# Symmetrization
# ---------------------------------------------------------------------------


def symmetrize(directed: scipy.sparse.csr_matrix) -> scipy.sparse.csr_matrix:
    """Symmetrize a directed adjacency matrix using element-wise max.

    w_sym(i, j) = max(w(i, j), w(j, i))

    Parameters
    ----------
    directed : scipy.sparse.csr_matrix
        Directed weighted adjacency matrix.

    Returns
    -------
    scipy.sparse.csr_matrix
        Symmetric sparse matrix where each entry is the max of the
        corresponding directed entries.
    """
    transposed = directed.T.tocsr()
    # Element-wise maximum produces the undirected graph
    symmetric = directed.maximum(transposed)
    return symmetric.tocsr()


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_snapshot(
    window: TimeWindow,
    agent_ids: list[str],
) -> TopologySnapshot:
    """Build a complete TopologySnapshot for a given time window.

    Parameters
    ----------
    window : TimeWindow
        The time window containing coordination events.
    agent_ids : list[str]
        Fixed ordered roster of agent identifiers.

    Returns
    -------
    TopologySnapshot
        Fully constructed snapshot with directed and symmetric adjacency.
    """
    directed = build_directed_graph(window, agent_ids)
    symmetric = symmetrize(directed)

    snapshot = TopologySnapshot(
        window_id=window.window_id,
        adjacency=directed,
        adjacency_symmetric=symmetric,
        agent_ids=list(agent_ids),  # defensive copy
        agent_types={},
    )

    logger.info(
        "Snapshot window=%d: %d agents, nnz_directed=%d, nnz_symmetric=%d",
        window.window_id,
        len(agent_ids),
        directed.nnz,
        symmetric.nnz,
    )
    return snapshot


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_snapshot(snapshot: TopologySnapshot, output_dir: Path) -> Path:
    """Serialize a TopologySnapshot to disk.

    Saves two files:
      - ``snapshot_{window_id}.npz`` — sparse matrices (directed + symmetric)
      - ``snapshot_{window_id}_meta.json`` — agent_ids and agent_types

    Parameters
    ----------
    snapshot : TopologySnapshot
        The snapshot to persist.
    output_dir : Path
        Directory to write files into (created if missing).

    Returns
    -------
    Path
        Path to the saved .npz file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"snapshot_{snapshot.window_id}"
    npz_path = output_dir / f"{prefix}.npz"
    meta_path = output_dir / f"{prefix}_meta.json"

    # Save sparse matrices in a single npz archive
    # We store both directed and symmetric using scipy's internal format
    scipy.sparse.save_npz(str(npz_path), snapshot.adjacency)

    # Save symmetric matrix separately
    sym_path = output_dir / f"{prefix}_sym.npz"
    scipy.sparse.save_npz(str(sym_path), snapshot.adjacency_symmetric)

    # Save metadata as JSON
    meta = {
        "window_id": snapshot.window_id,
        "agent_ids": snapshot.agent_ids,
        "agent_types": snapshot.agent_types,
        "n_agents": len(snapshot.agent_ids),
        "nnz_directed": snapshot.adjacency.nnz,
        "nnz_symmetric": snapshot.adjacency_symmetric.nnz,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.info("Saved snapshot window=%d to %s", snapshot.window_id, output_dir)
    return npz_path


def load_snapshot_from_json(json_path: Path) -> TopologySnapshot:
    """Load a TopologySnapshot from a JSON file produced by CommunicationTopology.save_snapshot().

    The JSON format stores adjacency matrices in COO form:
      {"rows": [...], "cols": [...], "data": [...], "shape": [n, n]}

    Parameters
    ----------
    json_path : Path
        Path to the JSON snapshot file (e.g., window_003.json).

    Returns
    -------
    TopologySnapshot
        Reconstructed snapshot with directed and symmetric adjacency matrices.

    Raises
    ------
    FileNotFoundError
        If the JSON file does not exist.
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Snapshot JSON not found: {json_path}")

    raw = json.loads(json_path.read_text(encoding="utf-8"))

    window_id = raw["window_id"]
    agent_ids = raw["agent_ids"]
    agent_types = raw.get("agent_types", {})

    # Reconstruct directed adjacency from COO format
    adj_dir = raw["adjacency_directed"]
    shape_dir = tuple(adj_dir["shape"])
    directed = scipy.sparse.csr_matrix(
        (
            np.array(adj_dir["data"], dtype=np.float64),
            (np.array(adj_dir["rows"], dtype=np.int32), np.array(adj_dir["cols"], dtype=np.int32)),
        ),
        shape=shape_dir,
    )

    # Reconstruct symmetric adjacency from COO format
    adj_sym = raw["adjacency_symmetric"]
    shape_sym = tuple(adj_sym["shape"])
    symmetric = scipy.sparse.csr_matrix(
        (
            np.array(adj_sym["data"], dtype=np.float64),
            (np.array(adj_sym["rows"], dtype=np.int32), np.array(adj_sym["cols"], dtype=np.int32)),
        ),
        shape=shape_sym,
    )

    snapshot = TopologySnapshot(
        window_id=window_id,
        adjacency=directed,
        adjacency_symmetric=symmetric,
        agent_ids=agent_ids,
        agent_types=agent_types,
    )

    logger.debug("Loaded snapshot from JSON: window=%d, agents=%d", window_id, len(agent_ids))
    return snapshot


def load_precomputed_snapshots(snapshots_dir: Path) -> list[TopologySnapshot]:
    """Load all pre-computed JSON topology snapshots from a directory.

    Scans for files matching ``window_*.json``, sorts by window_id (numeric),
    and returns an ordered list of TopologySnapshot objects.

    Parameters
    ----------
    snapshots_dir : Path
        Directory containing window_*.json files produced by EdgeRewiringEngine.

    Returns
    -------
    list[TopologySnapshot]
        Ordered list of snapshots (by window_id). Empty list if directory
        doesn't exist or contains no matching JSON files.
    """
    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.exists():
        return []

    json_files = sorted(snapshots_dir.glob("window_*.json"))
    if not json_files:
        return []

    snapshots: list[TopologySnapshot] = []
    for json_path in json_files:
        try:
            snap = load_snapshot_from_json(json_path)
            snapshots.append(snap)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load snapshot %s: %s", json_path.name, e)
            continue

    # Sort by window_id to ensure proper ordering
    snapshots.sort(key=lambda s: s.window_id)

    logger.info("Loaded %d pre-computed snapshots from %s", len(snapshots), snapshots_dir)
    return snapshots


def load_snapshot(output_dir: Path, window_id: int) -> TopologySnapshot:
    """Load a TopologySnapshot from disk.

    Parameters
    ----------
    output_dir : Path
        Directory containing the serialized snapshot files.
    window_id : int
        Window identifier used to locate the files.

    Returns
    -------
    TopologySnapshot
        Reconstructed snapshot.

    Raises
    ------
    FileNotFoundError
        If required files are missing from output_dir.
    """
    output_dir = Path(output_dir)
    prefix = f"snapshot_{window_id}"

    npz_path = output_dir / f"{prefix}.npz"
    sym_path = output_dir / f"{prefix}_sym.npz"
    meta_path = output_dir / f"{prefix}_meta.json"

    if not npz_path.exists():
        raise FileNotFoundError(f"Directed adjacency not found: {npz_path}")
    if not sym_path.exists():
        raise FileNotFoundError(f"Symmetric adjacency not found: {sym_path}")
    if not meta_path.exists():
        raise FileNotFoundError(f"Metadata not found: {meta_path}")

    adjacency = scipy.sparse.load_npz(str(npz_path))
    adjacency_symmetric = scipy.sparse.load_npz(str(sym_path))

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    snapshot = TopologySnapshot(
        window_id=meta["window_id"],
        adjacency=adjacency,
        adjacency_symmetric=adjacency_symmetric,
        agent_ids=meta["agent_ids"],
        agent_types=meta.get("agent_types", {}),
    )

    logger.debug("Loaded snapshot window=%d from %s", window_id, output_dir)
    return snapshot
