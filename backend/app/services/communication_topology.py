"""
Communication Topology — Dynamic edge-evolving graph for agent simulations.

Nodes (agent_ids) are fixed at initialization; edges evolve based on
agent interactions during simulation rounds.

Key invariants:
  - Nodes cannot be modified after initialization.
  - Self-loops are NOT allowed (source != target).
  - Edge weight can go negative (e.g. from MUTE actions) but prune removes
    edges below a configurable threshold.
  - This class is NOT thread-safe; caller must synchronize if needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse

from ..utils.logger import get_logger

logger = get_logger("mirofish.services.communication_topology")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EdgeState:
    """State of a single directed edge between two agents."""

    weight: float = 0.0                             # Cumulative interaction weight
    relation: str = "INTERACTS_WITH"                # Current semantic label
    last_updated_round: int = 0                     # For decay computation
    interaction_count: int = 0                      # Raw total interaction count
    interaction_types: Dict[str, int] = field(default_factory=dict)  # e.g. {"CREATE_COMMENT": 3}
    created_at_round: int = 0                       # When this edge first appeared

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return {
            "weight": self.weight,
            "relation": self.relation,
            "last_updated_round": self.last_updated_round,
            "interaction_count": self.interaction_count,
            "interaction_types": dict(self.interaction_types),
            "created_at_round": self.created_at_round,
        }


# Type alias for the snapshot payload returned by to_snapshot.
TopologySnapshotData = Dict


# ---------------------------------------------------------------------------
# Core topology class
# ---------------------------------------------------------------------------


class CommunicationTopology:
    """
    Directed, weighted communication topology over a fixed set of agents.

    Edges are created and updated via `update_edge`; decay and pruning manage
    lifecycle.  Matrix views (sparse CSR) are available for analytics.
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self, agent_ids: List[str]) -> None:
        """Initialize with a fixed agent roster.

        Args:
            agent_ids: Ordered list of unique agent identifiers.

        Raises:
            ValueError: If duplicates are found in agent_ids.
        """
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("agent_ids must not contain duplicates")

        self._agent_ids: List[str] = list(agent_ids)  # ordered, immutable after init
        self._agent_set: frozenset = frozenset(agent_ids)  # O(1) membership lookup
        self._id_to_index: Dict[str, int] = {aid: idx for idx, aid in enumerate(agent_ids)}

        self._adjacency: Dict[Tuple[str, str], EdgeState] = {}

        self.window_id: int = 0
        self.round_counter: int = 0

        logger.info(
            "CommunicationTopology initialized with %d agents", len(agent_ids)
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_ids(self) -> List[str]:
        """Return a copy of the ordered agent list (cannot be mutated)."""
        return list(self._agent_ids)

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def update_edge(
        self,
        source: str,
        target: str,
        weight_delta: float,
        action_type: str,
        round_num: int,
    ) -> None:
        """Create or update a directed edge.

        Args:
            source: Source agent id.
            target: Target agent id.
            weight_delta: Additive weight change (can be negative).
            action_type: Semantic action label (e.g. "CREATE_COMMENT").
            round_num: Current simulation round number.

        Raises:
            ValueError: If source or target not in agent_ids or self-loop.
        """
        if source not in self._agent_set:
            raise ValueError(f"source '{source}' not in agent roster")
        if target not in self._agent_set:
            raise ValueError(f"target '{target}' not in agent roster")
        if source == target:
            raise ValueError("Self-loops are not allowed")

        key = (source, target)
        edge = self._adjacency.get(key)

        if edge is None:
            edge = EdgeState(created_at_round=round_num)
            self._adjacency[key] = edge
            logger.debug("Edge created: %s -> %s at round %d", source, target, round_num)

        edge.weight += weight_delta
        edge.interaction_count += 1
        edge.interaction_types[action_type] = edge.interaction_types.get(action_type, 0) + 1
        edge.last_updated_round = round_num

    def get_edge(self, source: str, target: str) -> Optional[EdgeState]:
        """Return edge state or None if no edge exists."""
        return self._adjacency.get((source, target))

    def get_all_edges(self) -> Dict[Tuple[str, str], EdgeState]:
        """Return a shallow copy of the adjacency map."""
        return dict(self._adjacency)

    def edge_count(self) -> int:
        """Number of active (existing) edges."""
        return len(self._adjacency)

    # ------------------------------------------------------------------
    # Decay & pruning
    # ------------------------------------------------------------------

    def apply_decay(self, decay_lambda: float) -> None:
        """Multiply all edge weights by decay_lambda (use-it-or-lose-it).

        Args:
            decay_lambda: Multiplicative decay factor in (0, 1].
        """
        for edge in self._adjacency.values():
            edge.weight *= decay_lambda

    def prune_edges(self, threshold: float) -> None:
        """Remove edges whose weight falls below threshold.

        Args:
            threshold: Minimum weight to retain an edge.
        """
        keys_to_remove = [k for k, e in self._adjacency.items() if e.weight < threshold]
        for k in keys_to_remove:
            del self._adjacency[k]
        if keys_to_remove:
            logger.debug("Pruned %d edges below threshold %.4f", len(keys_to_remove), threshold)

    # ------------------------------------------------------------------
    # Round management
    # ------------------------------------------------------------------

    def increment_round(self) -> None:
        """Advance the round counter by 1."""
        self.round_counter += 1

    # ------------------------------------------------------------------
    # Matrix representations
    # ------------------------------------------------------------------

    def to_adjacency_matrix(self) -> scipy.sparse.csr_matrix:
        """Convert to directed sparse CSR adjacency matrix.

        Rows/columns follow self._agent_ids ordering.
        """
        n = len(self._agent_ids)
        if not self._adjacency:
            return scipy.sparse.csr_matrix((n, n))

        rows, cols, data = [], [], []
        for (src, tgt), edge in self._adjacency.items():
            rows.append(self._id_to_index[src])
            cols.append(self._id_to_index[tgt])
            data.append(edge.weight)

        return scipy.sparse.csr_matrix(
            (np.array(data, dtype=np.float64), (np.array(rows), np.array(cols))),
            shape=(n, n),
        )

    def to_symmetric_matrix(self) -> scipy.sparse.csr_matrix:
        """Convert to symmetric adjacency via max(w_ij, w_ji)."""
        directed = self.to_adjacency_matrix()
        # Element-wise maximum of A and A^T
        symmetric = directed.maximum(directed.T)
        return symmetric.tocsr()

    # ------------------------------------------------------------------
    # Snapshot & serialization
    # ------------------------------------------------------------------

    def to_snapshot(self, round_start: int, round_end: int) -> TopologySnapshotData:
        """Produce a snapshot dict suitable for JSON serialization.

        Args:
            round_start: First round in the window.
            round_end: Last round in the window.

        Returns:
            Dictionary with full topology state and metrics.
        """
        directed = self.to_adjacency_matrix()
        symmetric = self.to_symmetric_matrix()

        dir_coo = directed.tocoo()
        sym_coo = symmetric.tocoo()

        n = len(self._agent_ids)

        # Compute metrics
        weights = [e.weight for e in self._adjacency.values()] if self._adjacency else [0.0]
        max_possible_edges = n * (n - 1)  # directed
        density = len(self._adjacency) / max_possible_edges if max_possible_edges > 0 else 0.0

        # Agent types: extract type from agent_id if possible (convention: "type_name")
        agent_types: Dict[str, str] = {}
        for aid in self._agent_ids:
            parts = aid.rsplit("_", 1)
            agent_types[aid] = parts[0] if len(parts) > 1 else "unknown"

        return {
            "window_id": self.window_id,
            "round_start": round_start,
            "round_end": round_end,
            "agent_ids": list(self._agent_ids),
            "agent_types": agent_types,
            "adjacency_directed": {
                "rows": dir_coo.row.tolist(),
                "cols": dir_coo.col.tolist(),
                "data": dir_coo.data.tolist(),
                "shape": [n, n],
            },
            "adjacency_symmetric": {
                "rows": sym_coo.row.tolist(),
                "cols": sym_coo.col.tolist(),
                "data": sym_coo.data.tolist(),
                "shape": [n, n],
            },
            "metrics": {
                "edge_count": len(self._adjacency),
                "mean_weight": float(np.mean(weights)),
                "max_weight": float(np.max(weights)),
                "density": round(density, 4),
            },
        }

    def save_snapshot(
        self,
        output_dir: Path,
        window_id: int,
        round_start: int,
        round_end: int,
    ) -> None:
        """Save JSON snapshot to disk.

        File is written to output_dir/window_{NNN}.json.

        Args:
            output_dir: Directory for snapshot files.
            window_id: Window identifier (used in filename and payload).
            round_start: First round in the window.
            round_end: Last round in the window.
        """
        self.window_id = window_id
        snapshot = self.to_snapshot(round_start, round_end)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = output_dir / f"window_{window_id:03d}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)

        logger.info("Snapshot saved: %s (%d edges)", filename, self.edge_count())

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all edges but keep agent_ids intact. Useful for testing."""
        self._adjacency.clear()
        self.round_counter = 0
        self.window_id = 0
        logger.info("Topology reset — all edges cleared")
