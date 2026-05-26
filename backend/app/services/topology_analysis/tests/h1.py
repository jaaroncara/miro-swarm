"""H1: density-matched higher-order vs pairwise comparison.

Research hypothesis H1: Higher-order interactions (k≥2 simplices) produce better
coordination outcomes than pairwise-only interactions, after controlling for edge
density via density matching.

For each time window snapshot we compare windows exhibiting significant
higher-order topology (b_k > 0 for k≥1 above the null threshold δ_P) against
windows that are purely pairwise (all b_k = 0 for k≥1), after Mahalanobis-style
density matching on |E_t| to eliminate the trivial confound that more edges
produce higher Betti numbers mechanically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

from ..homology import PersistenceResult
from ..nullmodel import is_significant
from ..reward import RewardComponents
from ....utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.tests.h1")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class H1Result:
    """Result of the H1 hypothesis test.

    Attributes:
        n_higher_order: Number of windows classified as "higher-order".
        n_pairwise_only: Number of density-matched pairwise-only windows.
        mean_reward_higher: Mean R_t for higher-order group.
        mean_reward_pairwise: Mean R_t for pairwise-only group.
        cohens_d: Cohen's d effect size (positive = higher-order is better).
        p_value: p-value from paired t-test on density-matched pairs.
        significant: True if p < 0.05 and d > 0.
        matching_details: Metadata about the density-matching procedure.
    """

    n_higher_order: int
    n_pairwise_only: int
    mean_reward_higher: float
    mean_reward_pairwise: float
    cohens_d: float
    p_value: float
    significant: bool
    matching_details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Window classification
# ---------------------------------------------------------------------------


def classify_windows(
    persistence_results: list[PersistenceResult],
    null_thresholds: list[dict[int, float]],
) -> tuple[list[int], list[int]]:
    """Classify each window as higher-order or pairwise-only.

    A window is *higher-order* if any persistence pair in dimension ≥ 1
    exceeds the null-model threshold δ_P for that dimension.

    A window is *pairwise-only* if no persistence pair in dimension ≥ 1
    exceeds δ_P.

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        One PersistenceResult per time window.
    null_thresholds : list[dict[int, float]]
        Per-window null thresholds mapping dimension → δ_P.

    Returns
    -------
    tuple[list[int], list[int]]
        (higher_order_indices, pairwise_only_indices)
    """
    higher_order_indices: list[int] = []
    pairwise_only_indices: list[int] = []

    for i, (pr, thresholds) in enumerate(zip(persistence_results, null_thresholds)):
        has_higher_order = False

        for dim, (birth, death) in pr.persistence_pairs:
            if dim >= 1 and is_significant((birth, death), dim, thresholds):
                has_higher_order = True
                break

        if has_higher_order:
            higher_order_indices.append(i)
        else:
            pairwise_only_indices.append(i)

    logger.info(
        "Window classification: %d higher-order, %d pairwise-only",
        len(higher_order_indices),
        len(pairwise_only_indices),
    )
    return higher_order_indices, pairwise_only_indices


# ---------------------------------------------------------------------------
# Density matching
# ---------------------------------------------------------------------------


def density_match(
    higher_indices: list[int],
    pairwise_indices: list[int],
    edge_counts: list[int],
    caliper: float = 0.5,
) -> tuple[list[int], list[int]]:
    """Match higher-order windows to pairwise-only windows by edge density.

    Uses standardized absolute difference on |E_t|. For each higher-order
    window, selects the nearest (unmatched) pairwise-only window within
    the caliper (in units of pooled standard deviation). Greedy 1:1 matching
    without replacement.

    Parameters
    ----------
    higher_indices : list[int]
        Indices of higher-order windows.
    pairwise_indices : list[int]
        Indices of pairwise-only windows.
    edge_counts : list[int]
        Edge count |E_t| for every window.
    caliper : float
        Maximum standardized distance for a valid match (default 0.5 SD).

    Returns
    -------
    tuple[list[int], list[int]]
        (higher_matched, pairwise_matched) — parallel arrays of matched indices.
    """
    if not higher_indices or not pairwise_indices:
        logger.warning("Empty group(s): cannot perform density matching.")
        return [], []

    # Compute pooled standard deviation of edge counts across both groups
    all_edges = np.array(
        [edge_counts[i] for i in higher_indices]
        + [edge_counts[i] for i in pairwise_indices],
        dtype=np.float64,
    )
    pooled_sd = float(np.std(all_edges, ddof=1))

    if pooled_sd < 1e-12:
        # All edge counts identical — every pair matches trivially
        pooled_sd = 1.0

    higher_matched: list[int] = []
    pairwise_matched: list[int] = []
    available_pairwise = set(pairwise_indices)

    # Sort higher-order by edge count to improve matching quality
    sorted_higher = sorted(higher_indices, key=lambda idx: edge_counts[idx])

    for h_idx in sorted_higher:
        h_edges = edge_counts[h_idx]
        best_idx: int | None = None
        best_dist = float("inf")

        for p_idx in available_pairwise:
            dist = abs(edge_counts[p_idx] - h_edges) / pooled_sd
            if dist < best_dist:
                best_dist = dist
                best_idx = p_idx

        if best_idx is not None and best_dist <= caliper:
            higher_matched.append(h_idx)
            pairwise_matched.append(best_idx)
            available_pairwise.discard(best_idx)

    logger.info(
        "Density matching: %d/%d higher-order windows matched (caliper=%.2f SD)",
        len(higher_matched),
        len(higher_indices),
        caliper,
    )
    return higher_matched, pairwise_matched


# ---------------------------------------------------------------------------
# Effect size
# ---------------------------------------------------------------------------


def compute_cohens_d(group1: np.ndarray, group2: np.ndarray) -> float:
    """Compute Cohen's d with pooled standard deviation.

    Positive d means group1 > group2.

    Parameters
    ----------
    group1 : np.ndarray
        Observations for the first group (higher-order).
    group2 : np.ndarray
        Observations for the second group (pairwise-only).

    Returns
    -------
    float
        Cohen's d effect size. Returns 0.0 if pooled variance is zero.
    """
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        return 0.0

    var1 = float(np.var(group1, ddof=1))
    var2 = float(np.var(group2, ddof=1))

    # Pooled standard deviation
    pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)

    if pooled_var < 1e-12:
        return 0.0

    pooled_sd = np.sqrt(pooled_var)
    d = (float(np.mean(group1)) - float(np.mean(group2))) / pooled_sd
    return float(d)


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


def run_h1_test(
    persistence_results: list[PersistenceResult],
    null_thresholds: list[dict[int, float]],
    rewards: list[RewardComponents],
    edge_counts: list[int],
    caliper: float = 0.5,
) -> H1Result:
    """Run the H1 hypothesis test.

    Pipeline: classify windows → density match → compare R_t between groups.

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        One per time window.
    null_thresholds : list[dict[int, float]]
        Per-window null thresholds (dimension → δ_P).
    rewards : list[RewardComponents]
        Per-window reward decomposition.
    edge_counts : list[int]
        Per-window edge count |E_t|.
    caliper : float
        Caliper for density matching in pooled SD units.

    Returns
    -------
    H1Result
        Complete test result including effect size and p-value.
    """
    n_windows = len(persistence_results)
    logger.info("Running H1 test on %d windows", n_windows)

    # Step 1: Classify
    higher_indices, pairwise_indices = classify_windows(
        persistence_results, null_thresholds
    )

    # Step 2: Density match
    higher_matched, pairwise_matched = density_match(
        higher_indices, pairwise_indices, edge_counts, caliper=caliper
    )

    n_matched = len(higher_matched)

    # Handle degenerate cases
    if n_matched < 2:
        logger.warning(
            "Insufficient matched pairs (%d) for H1 test — returning null result.",
            n_matched,
        )
        return H1Result(
            n_higher_order=n_matched,
            n_pairwise_only=n_matched,
            mean_reward_higher=float("nan"),
            mean_reward_pairwise=float("nan"),
            cohens_d=0.0,
            p_value=1.0,
            significant=False,
            matching_details={
                "total_higher_order": len(higher_indices),
                "total_pairwise_only": len(pairwise_indices),
                "matched_pairs": n_matched,
                "caliper": caliper,
                "reason": "insufficient_pairs",
            },
        )

    # Step 3: Extract rewards for matched groups
    rewards_higher = np.array([rewards[i].R_t for i in higher_matched])
    rewards_pairwise = np.array([rewards[i].R_t for i in pairwise_matched])

    # Step 4: Statistical test — paired t-test on matched pairs
    t_stat, p_value = stats.ttest_rel(rewards_higher, rewards_pairwise)
    # One-sided: we hypothesize higher-order > pairwise
    # ttest_rel is two-sided; convert to one-sided
    if t_stat > 0:
        p_one_sided = float(p_value) / 2.0
    else:
        p_one_sided = 1.0 - float(p_value) / 2.0

    # Step 5: Effect size
    d = compute_cohens_d(rewards_higher, rewards_pairwise)

    # Step 6: Significance decision
    significant = p_one_sided < 0.05 and d > 0

    # Matching metadata
    edge_diff_matched = np.array(
        [
            abs(edge_counts[h] - edge_counts[p])
            for h, p in zip(higher_matched, pairwise_matched)
        ]
    )

    matching_details: dict[str, Any] = {
        "total_higher_order": len(higher_indices),
        "total_pairwise_only": len(pairwise_indices),
        "matched_pairs": n_matched,
        "caliper": caliper,
        "mean_edge_diff_matched": float(np.mean(edge_diff_matched)),
        "max_edge_diff_matched": int(np.max(edge_diff_matched)),
        "t_statistic": float(t_stat),
        "p_two_sided": float(p_value),
    }

    result = H1Result(
        n_higher_order=n_matched,
        n_pairwise_only=n_matched,
        mean_reward_higher=float(np.mean(rewards_higher)),
        mean_reward_pairwise=float(np.mean(rewards_pairwise)),
        cohens_d=d,
        p_value=p_one_sided,
        significant=significant,
        matching_details=matching_details,
    )

    logger.info(
        "H1 result: d=%.3f, p=%.4f, significant=%s (n=%d matched pairs)",
        result.cohens_d,
        result.p_value,
        result.significant,
        n_matched,
    )
    return result
