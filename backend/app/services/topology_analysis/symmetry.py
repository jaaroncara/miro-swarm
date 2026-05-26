"""Platonic symmetry score S(K) via kernel alignment.

Measures how close an interaction complex K is to a maximally-symmetric
reference complex using kernel alignment (Equation 6):

    S(K) = <K_K, K_ref>_F / (||K_K||_F * ||K_ref||_F)

The reference complex is a vertex-transitive circulant graph matched on (V, E).
"""

from __future__ import annotations

import numpy as np
import scipy.sparse
from scipy.sparse import csr_matrix

from ...config import Config
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.symmetry")


# ---------------------------------------------------------------------------
# 1. Circulant reference graph
# ---------------------------------------------------------------------------


def build_circulant_reference(n_vertices: int, n_edges: int) -> np.ndarray:
    """Build a vertex-transitive circulant graph C(n, S) with ~n_edges edges.

    A circulant graph C(n, S) connects vertex i to vertex (i+s) mod n for each
    s in the offset set S. Each offset s (with 1 <= s < n/2) contributes exactly
    n undirected edges; offset s = n/2 (when n is even) contributes n/2 edges.

    We choose the smallest set S = {1, 2, ..., k} such that the total edge count
    meets or exceeds n_edges.

    Parameters
    ----------
    n_vertices : int
        Number of nodes in the circulant graph.
    n_edges : int
        Target number of undirected edges.

    Returns
    -------
    np.ndarray
        Dense binary adjacency matrix of shape (n_vertices, n_vertices).
    """
    if n_vertices <= 0:
        return np.zeros((0, 0), dtype=np.float64)
    if n_edges <= 0:
        return np.zeros((n_vertices, n_vertices), dtype=np.float64)

    n = n_vertices
    adj = np.zeros((n, n), dtype=np.float64)
    edge_count = 0
    max_offset = n // 2

    for k in range(1, max_offset + 1):
        if edge_count >= n_edges:
            break
        # Connect i -> (i+k) mod n and i -> (i-k) mod n
        for i in range(n):
            j = (i + k) % n
            if adj[i, j] == 0:
                adj[i, j] = 1.0
                adj[j, i] = 1.0
        # Count edges added by this offset
        if k == max_offset and n % 2 == 0:
            edge_count += n // 2
        else:
            edge_count += n
        if edge_count >= n_edges:
            break

    logger.debug(
        f"Built circulant reference: V={n_vertices}, target_E={n_edges}, "
        f"actual_E={int(adj.sum()) // 2}"
    )
    return adj


# ---------------------------------------------------------------------------
# 2. Simplex adjacency kernel
# ---------------------------------------------------------------------------


def simplex_adjacency_kernel(
    adjacency_symmetric: csr_matrix, sigma: float = 1.0
) -> np.ndarray:
    """Compute the Gaussian kernel over the simplex adjacency representation.

    Simplified practical implementation:
        S_ij = (A @ A)[i,j] + A[i,j]   (shared neighbors + direct edge)
        S_norm = S / max(S)             (normalize to [0, 1])
        K_ij = exp(-(1 - S_norm_ij)^2 / (2 * sigma^2))

    Parameters
    ----------
    adjacency_symmetric : csr_matrix
        Symmetric (undirected) adjacency matrix (binary or weighted).
    sigma : float
        Bandwidth parameter for the Gaussian kernel.

    Returns
    -------
    np.ndarray
        Dense kernel matrix of shape (n, n).
    """
    A = adjacency_symmetric.astype(np.float64)

    # Shared-neighbor count (sparse matmul keeps things efficient for large N)
    A2 = A @ A  # still sparse

    # Simplex adjacency: shared neighbors + direct edge
    S = A2 + A  # sparse

    # Convert to dense for kernel computation
    S_dense = np.asarray(S.todense()) if scipy.sparse.issparse(S) else np.array(S)

    # Normalize to [0, 1]
    s_max = S_dense.max()
    if s_max > 0:
        S_norm = S_dense / s_max
    else:
        S_norm = S_dense

    # Gaussian kernel: K_ij = exp(-(1 - S_norm_ij)^2 / (2*sigma^2))
    dist_sq = (1.0 - S_norm) ** 2
    K = np.exp(-dist_sq / (2.0 * sigma**2))

    return K


# ---------------------------------------------------------------------------
# 3. Symmetry score (kernel alignment)
# ---------------------------------------------------------------------------


def _frobenius_inner_product(A: np.ndarray, B: np.ndarray) -> float:
    """Compute Frobenius inner product <A, B>_F = sum(A_ij * B_ij)."""
    return float(np.sum(A * B))


def _frobenius_norm(A: np.ndarray) -> float:
    """Compute Frobenius norm ||A||_F."""
    return float(np.sqrt(np.sum(A * A)))


def compute_symmetry_score(
    adjacency_symmetric: csr_matrix, sigma: float = 1.0
) -> float:
    """Compute the platonic symmetry score S(K) via kernel alignment.

    S(K) = <K_K, K_ref>_F / (||K_K||_F * ||K_ref||_F)

    Parameters
    ----------
    adjacency_symmetric : csr_matrix
        Symmetric adjacency matrix of the interaction complex.
    sigma : float
        Gaussian kernel bandwidth.

    Returns
    -------
    float
        Symmetry score in [0, 1]. Returns 0.0 for degenerate cases.
    """
    n_vertices = adjacency_symmetric.shape[0]
    # Count undirected edges (upper triangle nonzeros)
    upper = scipy.sparse.triu(adjacency_symmetric, k=1)
    n_edges = upper.nnz

    if n_vertices == 0 or n_edges == 0:
        logger.debug("Degenerate graph (V=0 or E=0), returning S(K)=0.0")
        return 0.0

    # Kernel of the input complex
    K_K = simplex_adjacency_kernel(adjacency_symmetric, sigma=sigma)

    # Build matched circulant reference and compute its kernel
    ref_adj_dense = build_circulant_reference(n_vertices, n_edges)
    ref_adj_sparse = csr_matrix(ref_adj_dense)
    K_ref = simplex_adjacency_kernel(ref_adj_sparse, sigma=sigma)

    # Kernel alignment
    norm_K = _frobenius_norm(K_K)
    norm_ref = _frobenius_norm(K_ref)

    if norm_K == 0.0 or norm_ref == 0.0:
        logger.debug("Zero-norm kernel, returning S(K)=0.0")
        return 0.0

    score = _frobenius_inner_product(K_K, K_ref) / (norm_K * norm_ref)

    logger.debug(f"Symmetry score S(K)={score:.6f} (V={n_vertices}, E={n_edges})")
    return float(score)


# ---------------------------------------------------------------------------
# 4. Symmetry curve over snapshots
# ---------------------------------------------------------------------------


def compute_symmetry_curve(
    snapshots: list[csr_matrix], sigma: float = 1.0
) -> np.ndarray:
    """Compute the symmetry score S(K) for each temporal snapshot.

    Parameters
    ----------
    snapshots : list[csr_matrix]
        List of symmetric adjacency matrices (one per time window).
    sigma : float
        Gaussian kernel bandwidth.

    Returns
    -------
    np.ndarray
        1-D array of symmetry scores, shape (len(snapshots),).
    """
    scores = np.zeros(len(snapshots), dtype=np.float64)
    for t, adj in enumerate(snapshots):
        scores[t] = compute_symmetry_score(adj, sigma=sigma)
        if (t + 1) % 10 == 0:
            logger.info(
                f"Symmetry curve progress: {t + 1}/{len(snapshots)} snapshots"
            )
    logger.info(
        f"Symmetry curve complete: {len(snapshots)} snapshots, "
        f"mean S(K)={scores.mean():.4f}"
    )
    return scores
