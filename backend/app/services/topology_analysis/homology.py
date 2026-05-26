"""Compute persistent homology, Betti numbers, and persistence diagrams.

Given a SimplexTree (built from the Rips complex of a symmetrized weighted
graph), this module computes:
  - Persistent homology across the sublevel filtration
  - Betti numbers at the final filtration value
  - Persistence diagrams per dimension
  - Total persistence per dimension
  - k* (max dimension with persistence above a threshold)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gudhi
import numpy as np
import scipy.sparse

from .complex import create_simplex_tree_from_adjacency
from ...config import Config
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.homology")

# Cap for infinite death values in persistence pairs
_MAX_FILTRATION_CAP = 2.0


@dataclass
class PersistenceResult:
    """Result container for persistent homology computation.

    Attributes:
        betti_numbers: Mapping from dimension to Betti number at the final filtration value.
        persistence_pairs: List of (dimension, (birth, death)) tuples.
        persistence_diagrams: Mapping from dimension to Nx2 array of (birth, death) pairs.
        max_persistent_dim: k* — highest dimension with persistence > threshold.
        total_persistence: Mapping from dimension to sum of lifetimes (death - birth).
    """

    betti_numbers: dict[int, int] = field(default_factory=dict)
    persistence_pairs: list[tuple[int, tuple[float, float]]] = field(default_factory=list)
    persistence_diagrams: dict[int, np.ndarray] = field(default_factory=dict)
    max_persistent_dim: int = 0
    total_persistence: dict[int, float] = field(default_factory=dict)


def compute_persistence(
    simplex_tree: gudhi.SimplexTree,
    threshold: float = 0.0,
) -> PersistenceResult:
    """Compute persistent homology from a SimplexTree.

    Args:
        simplex_tree: A gudhi SimplexTree (with filtration values set).
        threshold: Minimum persistence (death - birth) for a feature to count
                   when determining k*.

    Returns:
        A PersistenceResult with all computed topological invariants.
    """
    # Edge case: empty or trivial simplex tree
    if simplex_tree.num_vertices() == 0:
        logger.warning("Empty simplex tree; returning trivial PersistenceResult.")
        return PersistenceResult()

    # Compute persistence
    persistence = simplex_tree.persistence()

    # Extract Betti numbers
    betti = simplex_tree.betti_numbers()
    betti_numbers: dict[int, int] = dict(betti) if betti else {}

    # Organize persistence pairs by dimension
    persistence_pairs: list[tuple[int, tuple[float, float]]] = []
    diagrams_by_dim: dict[int, list[tuple[float, float]]] = {}

    for dim, (birth, death) in persistence:
        # Replace infinite death with cap
        if death == float("inf"):
            death = _MAX_FILTRATION_CAP

        persistence_pairs.append((dim, (birth, death)))

        if dim not in diagrams_by_dim:
            diagrams_by_dim[dim] = []
        diagrams_by_dim[dim].append((birth, death))

    # Build persistence diagrams as numpy arrays
    persistence_diagrams: dict[int, np.ndarray] = {}
    for dim, pairs in diagrams_by_dim.items():
        persistence_diagrams[dim] = np.array(pairs, dtype=np.float64)

    # Compute total persistence per dimension
    total_persistence: dict[int, float] = {}
    for dim, diagram in persistence_diagrams.items():
        lifetimes = diagram[:, 1] - diagram[:, 0]
        total_persistence[dim] = float(np.sum(lifetimes))

    # Determine k*: max dimension where some feature has persistence > threshold
    max_persistent_dim = 0
    for dim, diagram in persistence_diagrams.items():
        lifetimes = diagram[:, 1] - diagram[:, 0]
        if np.any(lifetimes > threshold):
            max_persistent_dim = max(max_persistent_dim, dim)

    logger.debug(
        "Persistence computed: betti=%s, k*=%d, dims_with_features=%s",
        betti_numbers,
        max_persistent_dim,
        sorted(persistence_diagrams.keys()),
    )

    return PersistenceResult(
        betti_numbers=betti_numbers,
        persistence_pairs=persistence_pairs,
        persistence_diagrams=persistence_diagrams,
        max_persistent_dim=max_persistent_dim,
        total_persistence=total_persistence,
    )


def compute_persistence_from_adjacency(
    adjacency_symmetric: scipy.sparse.csr_matrix,
    max_dim: int | None = None,
    threshold: float = 0.0,
) -> PersistenceResult:
    """Main entry point: compute persistence directly from adjacency matrix.

    Combines simplex tree construction and persistence computation.

    Args:
        adjacency_symmetric: Symmetric weighted adjacency matrix.
        max_dim: Maximum simplex dimension. Defaults to Config.TOPOLOGY_MAX_DIM.
        threshold: Minimum persistence for k* determination.

    Returns:
        A PersistenceResult with all computed topological invariants.
    """
    if max_dim is None:
        max_dim = Config.TOPOLOGY_MAX_DIM

    n = adjacency_symmetric.shape[0]

    # Edge case: empty graph → trivial result (b0 = N, everything else 0)
    if adjacency_symmetric.nnz == 0:
        logger.info("All-zero adjacency (N=%d); returning trivial persistence.", n)
        return PersistenceResult(
            betti_numbers={0: n},
            persistence_pairs=[(0, (0.0, _MAX_FILTRATION_CAP)) for _ in range(n)],
            persistence_diagrams={
                0: np.column_stack([
                    np.zeros(n, dtype=np.float64),
                    np.full(n, _MAX_FILTRATION_CAP, dtype=np.float64),
                ])
            } if n > 0 else {},
            max_persistent_dim=0,
            total_persistence={0: float(n * _MAX_FILTRATION_CAP)} if n > 0 else {},
        )

    simplex_tree = create_simplex_tree_from_adjacency(adjacency_symmetric, max_dim=max_dim)
    return compute_persistence(simplex_tree, threshold=threshold)


def get_betti_curve(
    snapshots_persistence: list[PersistenceResult],
    dimension: int,
) -> np.ndarray:
    """Extract the Betti number at a given dimension across time windows.

    Args:
        snapshots_persistence: List of PersistenceResult, one per time window.
        dimension: The homological dimension to track.

    Returns:
        1D numpy array of Betti numbers over time (length = len(snapshots_persistence)).
    """
    curve = np.array(
        [result.betti_numbers.get(dimension, 0) for result in snapshots_persistence],
        dtype=np.int64,
    )
    logger.debug(
        "Betti curve for dim=%d: length=%d, range=[%d, %d]",
        dimension,
        len(curve),
        int(curve.min()) if len(curve) > 0 else 0,
        int(curve.max()) if len(curve) > 0 else 0,
    )
    return curve
