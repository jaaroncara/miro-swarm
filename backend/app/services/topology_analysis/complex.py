"""Build gudhi clique complex (Rips/flag complex) on symmetrized weighted graph.

Implements the sublevel filtration described in the paper:
  d_ij = 1 - w_ij  (strongly-connected edges appear first in filtration)

The Rips complex is built from the resulting distance matrix with dimension
capped at k=6 (configurable) to prevent combinatorial blow-up.
"""

from __future__ import annotations

import gudhi
import numpy as np
import scipy.sparse

from ...config import Config
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.complex")


def build_filtration_matrix(adjacency_symmetric: scipy.sparse.csr_matrix) -> np.ndarray:
    """Convert symmetric sparse adjacency to a distance matrix for sublevel filtration.

    The transformation is:
        d_ij = 1 - w_ij   for connected pairs (w_ij > 0)
        d_ij = 2.0        for disconnected pairs (w_ij = 0)
        d_ii = 0.0        on the diagonal

    Weights are normalized to [0, 1] first if any w > 1.

    Args:
        adjacency_symmetric: Symmetric weighted adjacency matrix (csr_matrix).

    Returns:
        Dense distance matrix of shape (N, N) with values in [0, 2.0].
    """
    n = adjacency_symmetric.shape[0]

    if n == 0:
        logger.warning("Empty adjacency matrix received; returning empty distance matrix.")
        return np.zeros((0, 0), dtype=np.float64)

    # Work with a copy to avoid mutating input
    adj = adjacency_symmetric.copy().astype(np.float64)

    # Normalize weights to [0, 1] if any exceed 1
    max_weight = adj.max()
    if max_weight > 1.0:
        logger.debug("Normalizing weights: max_weight=%.4f", max_weight)
        adj = adj / max_weight

    # Build distance matrix: start with 2.0 (disconnected default)
    distance = np.full((n, n), 2.0, dtype=np.float64)

    # Fill connected entries with d = 1 - w
    adj_coo = adj.tocoo()
    for i, j, w in zip(adj_coo.row, adj_coo.col, adj_coo.data):
        if w > 0:
            distance[i, j] = 1.0 - w

    # Diagonal is zero
    np.fill_diagonal(distance, 0.0)

    logger.debug(
        "Built filtration matrix: N=%d, min_dist=%.4f, max_dist=%.4f",
        n,
        distance[np.triu_indices(n, k=1)].min() if n > 1 else 0.0,
        distance[np.triu_indices(n, k=1)].max() if n > 1 else 0.0,
    )

    return distance


def build_rips_complex(
    distance_matrix: np.ndarray,
    max_dim: int = 6,
    max_edge_length: float = 2.0,
) -> gudhi.RipsComplex:
    """Create a gudhi RipsComplex from a distance matrix.

    Args:
        distance_matrix: Dense NxN distance matrix.
        max_dim: Maximum simplex dimension (used downstream when creating the tree).
        max_edge_length: Maximum filtration value for edge inclusion.

    Returns:
        A gudhi.RipsComplex instance.
    """
    rips = gudhi.RipsComplex(
        distance_matrix=distance_matrix,
        max_edge_length=max_edge_length,
    )
    logger.debug(
        "Built RipsComplex: N=%d, max_edge_length=%.2f",
        distance_matrix.shape[0],
        max_edge_length,
    )
    return rips


def build_simplex_tree(
    distance_matrix: np.ndarray,
    max_dim: int = 6,
    max_edge_length: float = 2.0,
) -> gudhi.SimplexTree:
    """Build a SimplexTree from the distance matrix via Rips complex.

    The simplex tree dimension is capped at max_dim to prevent combinatorial
    explosion for large graphs.

    Args:
        distance_matrix: Dense NxN distance matrix.
        max_dim: Maximum dimension for the simplex tree.
        max_edge_length: Maximum filtration value for edge inclusion.

    Returns:
        A gudhi.SimplexTree ready for persistence computation.
    """
    rips = build_rips_complex(distance_matrix, max_dim=max_dim, max_edge_length=max_edge_length)
    simplex_tree = rips.create_simplex_tree(max_dimension=max_dim)

    logger.debug(
        "SimplexTree created: num_simplices=%d, num_vertices=%d, dimension=%d",
        simplex_tree.num_simplices(),
        simplex_tree.num_vertices(),
        simplex_tree.dimension(),
    )

    return simplex_tree


def create_simplex_tree_from_adjacency(
    adjacency_symmetric: scipy.sparse.csr_matrix,
    max_dim: int | None = None,
) -> gudhi.SimplexTree:
    """Main entry point: build simplex tree from symmetric adjacency matrix.

    Combines build_filtration_matrix + build_simplex_tree for convenience.

    Args:
        adjacency_symmetric: Symmetric weighted adjacency matrix.
        max_dim: Maximum simplex dimension. Defaults to Config.TOPOLOGY_MAX_DIM.

    Returns:
        A gudhi.SimplexTree ready for persistence computation.
    """
    if max_dim is None:
        max_dim = Config.TOPOLOGY_MAX_DIM

    distance_matrix = build_filtration_matrix(adjacency_symmetric)

    # Edge case: empty graph
    if distance_matrix.size == 0:
        logger.warning("Empty distance matrix; returning trivial simplex tree.")
        return gudhi.SimplexTree()

    simplex_tree = build_simplex_tree(distance_matrix, max_dim=max_dim)
    return simplex_tree
