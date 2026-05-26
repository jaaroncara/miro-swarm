"""Null model: M=200 weight permutations for significance threshold δ_P.

Establishes statistical significance thresholds for persistent homology features
by shuffling edge weights M times per snapshot and computing the 95th percentile
of max-persistence values per dimension.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse
from scipy.sparse import csr_matrix

from ...config import Config
from ...utils.logger import get_logger
from .complex import create_simplex_tree_from_adjacency
from .homology import compute_persistence

logger = get_logger("mirofish.topology_analysis.nullmodel")


# ---------------------------------------------------------------------------
# 1. Weight permutation
# ---------------------------------------------------------------------------


def permute_weights(
    adjacency_symmetric: csr_matrix, rng: np.random.Generator
) -> csr_matrix:
    """Shuffle edge weights while preserving the sparsity pattern.

    Extracts nonzero weights from the upper triangle, shuffles them,
    and reconstructs a symmetric sparse matrix.

    Parameters
    ----------
    adjacency_symmetric : csr_matrix
        Symmetric weighted adjacency matrix.
    rng : np.random.Generator
        Random number generator for reproducibility.

    Returns
    -------
    csr_matrix
        Symmetric adjacency matrix with shuffled edge weights.
    """
    # Extract upper triangle to avoid double-counting undirected edges
    upper = scipy.sparse.triu(adjacency_symmetric, k=1, format="coo")

    rows = upper.row.copy()
    cols = upper.col.copy()
    weights = upper.data.copy()

    # Shuffle weights in-place
    rng.shuffle(weights)

    # Rebuild symmetric matrix
    n = adjacency_symmetric.shape[0]
    # Upper triangle
    data = np.concatenate([weights, weights])
    row_idx = np.concatenate([rows, cols])
    col_idx = np.concatenate([cols, rows])

    permuted = csr_matrix(
        (data, (row_idx, col_idx)), shape=(n, n), dtype=np.float64
    )
    permuted.eliminate_zeros()

    return permuted


# ---------------------------------------------------------------------------
# 2. Null persistence thresholds
# ---------------------------------------------------------------------------


def compute_null_persistence(
    adjacency_symmetric: csr_matrix,
    M: int = 200,
    max_dim: int = 6,
    seed: int = 42,
) -> dict[int, float]:
    """Compute significance thresholds δ_P via edge-weight permutation null model.

    For each of M permutations:
        1. Shuffle edge weights (preserving topology)
        2. Build simplex tree from the permuted adjacency
        3. Compute persistent homology
        4. Record max persistence (death - birth) per dimension

    Then compute the 95th percentile per dimension as the threshold.

    Parameters
    ----------
    adjacency_symmetric : csr_matrix
        Original symmetric weighted adjacency matrix.
    M : int
        Number of permutations (default: 200).
    max_dim : int
        Maximum homological dimension to track.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict[int, float]
        Mapping from dimension d -> δ_P threshold (95th percentile).
    """
    rng = np.random.default_rng(seed)

    # Storage: for each dimension, collect max-persistence across permutations
    max_persistence_per_dim: dict[int, list[float]] = {
        d: [] for d in range(max_dim + 1)
    }

    n_edges = scipy.sparse.triu(adjacency_symmetric, k=1).nnz
    logger.info(
        f"Starting null model: M={M} permutations, max_dim={max_dim}, "
        f"V={adjacency_symmetric.shape[0]}, E={n_edges}"
    )

    for m in range(1, M + 1):
        # 1. Permute weights
        permuted = permute_weights(adjacency_symmetric, rng)

        # 2. Build simplex tree
        stree = create_simplex_tree_from_adjacency(permuted)

        # 3. Compute persistence
        persistence = compute_persistence(stree, max_dim=max_dim)

        # 4. Extract max persistence per dimension
        # persistence is expected to be a list of (dimension, (birth, death)) tuples
        dim_lifetimes: dict[int, float] = {d: 0.0 for d in range(max_dim + 1)}
        for dim, (birth, death) in persistence:
            if dim > max_dim:
                continue
            # Skip infinite-death features
            if not np.isfinite(death):
                continue
            lifetime = death - birth
            if lifetime > dim_lifetimes[dim]:
                dim_lifetimes[dim] = lifetime

        for d in range(max_dim + 1):
            max_persistence_per_dim[d].append(dim_lifetimes[d])

        # Progress logging
        if m % 50 == 0:
            logger.info(f"Null model progress: {m}/{M} permutations complete")

    # Compute 95th percentile thresholds
    thresholds: dict[int, float] = {}
    for d in range(max_dim + 1):
        values = np.array(max_persistence_per_dim[d])
        thresholds[d] = float(np.percentile(values, 95))

    logger.info(f"Null model complete. Thresholds: {thresholds}")
    return thresholds


# ---------------------------------------------------------------------------
# 3. Significance test
# ---------------------------------------------------------------------------


def is_significant(
    persistence_pair: tuple[float, float],
    dimension: int,
    thresholds: dict[int, float],
) -> bool:
    """Test whether a persistence pair exceeds the null model threshold.

    Parameters
    ----------
    persistence_pair : tuple[float, float]
        (birth, death) values of the persistence feature.
    dimension : int
        Homological dimension of the feature.
    thresholds : dict[int, float]
        Null model thresholds (from compute_null_persistence).

    Returns
    -------
    bool
        True if (death - birth) > threshold for the given dimension.
    """
    birth, death = persistence_pair
    lifetime = death - birth

    # If dimension not in thresholds, use inf (never significant)
    threshold = thresholds.get(dimension, float("inf"))

    return lifetime > threshold


# ---------------------------------------------------------------------------
# 4. Batch computation over snapshots
# ---------------------------------------------------------------------------


def compute_null_thresholds_for_snapshots(
    snapshots: list[csr_matrix],
    M: int = 200,
    max_dim: int = 6,
    seed: int = 42,
) -> list[dict[int, float]]:
    """Compute null model thresholds for each temporal snapshot.

    Parameters
    ----------
    snapshots : list[csr_matrix]
        List of symmetric adjacency matrices (one per time window).
    M : int
        Number of permutations per snapshot.
    max_dim : int
        Maximum homological dimension.
    seed : int
        Base random seed (incremented per snapshot for independence).

    Returns
    -------
    list[dict[int, float]]
        List of threshold dicts (one per snapshot).
    """
    logger.info(
        f"Computing null thresholds for {len(snapshots)} snapshots "
        f"(M={M}, max_dim={max_dim})"
    )

    all_thresholds: list[dict[int, float]] = []

    for t, adj in enumerate(snapshots):
        # Use different seed per snapshot for statistical independence
        snapshot_seed = seed + t
        logger.info(f"Snapshot {t + 1}/{len(snapshots)}: computing null model...")
        thresholds = compute_null_persistence(
            adj, M=M, max_dim=max_dim, seed=snapshot_seed
        )
        all_thresholds.append(thresholds)

    logger.info(f"All {len(snapshots)} snapshot null models complete.")
    return all_thresholds
