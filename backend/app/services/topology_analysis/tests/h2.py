"""H2: S monotonicity, top-q vs bottom-q, b0=1, single high-dim feature.

Research hypothesis H2: The platonic symmetry score S(K) increases
monotonically over simulation rounds, top-performing windows have higher S
than bottom-performing, and convergent topologies exhibit b0=1 (single
connected component) with a single dominant high-dimensional persistent feature.

Sub-tests:
    1. S monotonicity (Spearman rank correlation)
    2. Top-q vs bottom-q by R_t (Mann-Whitney U)
    3. b0 = 1 at final window
    4. Single high-dim feature above δ_P at final window
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from ..homology import PersistenceResult
from ..nullmodel import is_significant
from ..reward import RewardComponents
from ....utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.tests.h2")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class H2Result:
    """Aggregated results for hypothesis H2."""

    # Sub-test 1: S monotonicity
    s_spearman_rho: float
    s_spearman_p: float
    s_monotonic: bool

    # Sub-test 2: Top-q vs bottom-q
    top_q_mean_s: float
    bottom_q_mean_s: float
    top_vs_bottom_p: float
    top_greater: bool

    # Sub-test 3: b0 = 1
    final_b0: int
    b0_is_one: bool

    # Sub-test 4: Single high-dim feature
    final_k_star: int
    n_features_at_k_star: int
    single_high_dim_feature: bool

    # Overall
    all_pass: bool


# ---------------------------------------------------------------------------
# Sub-test 1: S monotonicity
# ---------------------------------------------------------------------------


def test_monotonicity(symmetry_scores: np.ndarray) -> tuple[float, float, bool]:
    """Test that S(K) has a statistically significant positive trend.

    Uses Spearman rank correlation of symmetry scores vs round index.

    Parameters
    ----------
    symmetry_scores : np.ndarray
        Array of symmetry scores S(K) ordered by simulation round.

    Returns
    -------
    tuple[float, float, bool]
        (rho, p_value, is_monotonic) where is_monotonic = rho > 0 and p < 0.05.
    """
    n = len(symmetry_scores)
    if n < 3:
        logger.warning(f"Too few windows ({n}) for monotonicity test; need >= 3")
        return 0.0, 1.0, False

    # Check if all values are identical (Spearman undefined)
    if np.all(symmetry_scores == symmetry_scores[0]):
        logger.info("All S values identical; rho = 0, not monotonic")
        return 0.0, 1.0, False

    indices = np.arange(n)
    rho, p_value = stats.spearmanr(indices, symmetry_scores)

    is_monotonic = bool(rho > 0 and p_value < 0.05)

    logger.info(
        f"Monotonicity test: rho={rho:.4f}, p={p_value:.4e}, "
        f"monotonic={is_monotonic}"
    )
    return float(rho), float(p_value), is_monotonic


# ---------------------------------------------------------------------------
# Sub-test 2: Top-q vs bottom-q
# ---------------------------------------------------------------------------


def test_top_vs_bottom(
    symmetry_scores: np.ndarray,
    rewards: np.ndarray,
    q: float = 0.25,
) -> tuple[float, float, float, float, bool]:
    """Test that top-quartile windows by R_t have higher S than bottom-quartile.

    Parameters
    ----------
    symmetry_scores : np.ndarray
        Array of symmetry scores S(K) per window.
    rewards : np.ndarray
        Array of R_t values per window.
    q : float
        Quantile fraction for top/bottom split (default: 0.25).

    Returns
    -------
    tuple[float, float, float, float, bool]
        (top_mean, bottom_mean, U_stat, p_value, top_greater)
        where top_greater = top_mean > bottom_mean and p < 0.05.
    """
    n = len(symmetry_scores)
    min_windows = max(8, int(np.ceil(2.0 / q)))  # Need at least 1 per quartile

    if n < min_windows:
        logger.warning(
            f"Too few windows ({n} < {min_windows}) for quartile split; "
            f"skipping top-vs-bottom test"
        )
        return 0.0, 0.0, 0.0, 1.0, False

    # Determine quartile thresholds
    top_threshold = np.percentile(rewards, 100 * (1 - q))
    bottom_threshold = np.percentile(rewards, 100 * q)

    top_mask = rewards >= top_threshold
    bottom_mask = rewards <= bottom_threshold

    top_s = symmetry_scores[top_mask]
    bottom_s = symmetry_scores[bottom_mask]

    if len(top_s) < 2 or len(bottom_s) < 2:
        logger.warning("Insufficient samples in top/bottom quartile")
        return 0.0, 0.0, 0.0, 1.0, False

    top_mean = float(np.mean(top_s))
    bottom_mean = float(np.mean(bottom_s))

    # One-sided Mann-Whitney: test that top > bottom
    u_stat, p_value = stats.mannwhitneyu(
        top_s, bottom_s, alternative="greater"
    )

    top_greater = bool(top_mean > bottom_mean and p_value < 0.05)

    logger.info(
        f"Top-vs-bottom test: top_mean={top_mean:.4f}, "
        f"bottom_mean={bottom_mean:.4f}, U={u_stat:.1f}, p={p_value:.4e}, "
        f"top_greater={top_greater}"
    )
    return top_mean, bottom_mean, float(u_stat), float(p_value), top_greater


# ---------------------------------------------------------------------------
# Sub-test 3: b0 = 1 at final window
# ---------------------------------------------------------------------------


def test_final_connectivity(
    persistence_results: list[PersistenceResult],
) -> tuple[int, bool]:
    """Check that the final window has b0 = 1 (single connected component).

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        Persistence results per window, ordered by simulation round.

    Returns
    -------
    tuple[int, bool]
        (final_b0, b0_is_one)
    """
    if not persistence_results:
        logger.warning("No persistence results; cannot check b0")
        return 0, False

    final = persistence_results[-1]
    final_b0 = final.betti_numbers.get(0, 0)
    b0_is_one = final_b0 == 1

    logger.info(f"Final connectivity: b0={final_b0}, b0_is_one={b0_is_one}")
    return final_b0, b0_is_one


# ---------------------------------------------------------------------------
# Sub-test 4: Single high-dim feature
# ---------------------------------------------------------------------------


def test_single_high_dim(
    persistence_results: list[PersistenceResult],
    null_thresholds: list[dict[int, float]],
) -> tuple[int, int, bool]:
    """Check that the final window has exactly one feature above δ_P at k*.

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        Persistence results per window.
    null_thresholds : list[dict[int, float]]
        Null model thresholds per window (parallel list).

    Returns
    -------
    tuple[int, int, bool]
        (k_star, n_features, is_single)
    """
    if not persistence_results:
        logger.warning("No persistence results; cannot check high-dim feature")
        return 0, 0, False

    final = persistence_results[-1]
    final_thresholds = null_thresholds[-1] if null_thresholds else {}

    k_star = final.max_persistent_dim

    if k_star == 0:
        logger.info("k* = 0 at final window (no higher-order persistence)")
        return 0, 0, False

    # Count features at dimension k* that exceed δ_P
    n_features = 0
    for dim, (birth, death) in final.persistence_pairs:
        if dim != k_star:
            continue
        if not np.isfinite(death):
            continue
        if is_significant((birth, death), dim, final_thresholds):
            n_features += 1

    is_single = n_features == 1

    logger.info(
        f"High-dim feature test: k*={k_star}, n_features={n_features}, "
        f"is_single={is_single}"
    )
    return k_star, n_features, is_single


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_h2_test(
    symmetry_scores: np.ndarray,
    rewards: list[RewardComponents],
    persistence_results: list[PersistenceResult],
    null_thresholds: list[dict[int, float]],
    q: float = 0.25,
) -> H2Result:
    """Run all 4 H2 sub-tests and return aggregated results.

    Parameters
    ----------
    symmetry_scores : np.ndarray
        Array of symmetry scores S(K) per window.
    rewards : list[RewardComponents]
        Reward components per window.
    persistence_results : list[PersistenceResult]
        Persistence results per window.
    null_thresholds : list[dict[int, float]]
        Null model thresholds per window.
    q : float
        Quantile fraction for top/bottom split (default: 0.25).

    Returns
    -------
    H2Result
        Aggregated hypothesis test results.
    """
    logger.info(
        f"Running H2 test: {len(symmetry_scores)} windows, q={q}"
    )

    # Extract R_t values from reward components
    reward_values = np.array([r.R_t for r in rewards])

    # Sub-test 1: Monotonicity
    rho, p_mono, is_monotonic = test_monotonicity(symmetry_scores)

    # Sub-test 2: Top-q vs bottom-q
    top_mean, bottom_mean, _u_stat, p_topbot, top_greater = test_top_vs_bottom(
        symmetry_scores, reward_values, q=q
    )

    # Sub-test 3: b0 = 1
    final_b0, b0_is_one = test_final_connectivity(persistence_results)

    # Sub-test 4: Single high-dim feature
    k_star, n_features, is_single = test_single_high_dim(
        persistence_results, null_thresholds
    )

    all_pass = all([is_monotonic, top_greater, b0_is_one, is_single])

    result = H2Result(
        s_spearman_rho=rho,
        s_spearman_p=p_mono,
        s_monotonic=is_monotonic,
        top_q_mean_s=top_mean,
        bottom_q_mean_s=bottom_mean,
        top_vs_bottom_p=p_topbot,
        top_greater=top_greater,
        final_b0=final_b0,
        b0_is_one=b0_is_one,
        final_k_star=k_star,
        n_features_at_k_star=n_features,
        single_high_dim_feature=is_single,
        all_pass=all_pass,
    )

    logger.info(
        f"H2 result: monotonic={is_monotonic}, top_greater={top_greater}, "
        f"b0_is_one={b0_is_one}, single_high_dim={is_single}, "
        f"ALL_PASS={all_pass}"
    )

    return result
