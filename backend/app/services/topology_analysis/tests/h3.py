"""H3: regression of R on topological predictors TP1, TP2, |E|, k*.

Research hypothesis H3: The reward R_t can be predicted by topological
features. Specifically:
    R_t = β₀ + β₁·TP1_t + β₂·TP2_t + β₃·|E_t| + β₄·k*_t + ε_t

We expect β₁ < 0 (loops reduce efficiency) and β₂ < 0 (voids reduce
efficiency), with edge count |E| and max persistent dimension k* as controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import statsmodels.api as sm
from statsmodels.stats.stattools import durbin_watson
from scipy.stats import shapiro

from ..homology import PersistenceResult
from ..reward import RewardComponents
from ....utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.tests.h3")

_PREDICTOR_NAMES = ["TP1", "TP2", "|E|", "k*"]
_MIN_OBSERVATIONS = 6


@dataclass
class H3Result:
    """Result container for the H3 hypothesis test (OLS regression)."""

    n_observations: int
    r_squared: float
    adj_r_squared: float
    coefficients: dict[str, float] = field(default_factory=dict)
    std_errors: dict[str, float] = field(default_factory=dict)
    t_values: dict[str, float] = field(default_factory=dict)
    p_values: dict[str, float] = field(default_factory=dict)
    beta1_negative: bool = False
    beta2_negative: bool = False
    f_statistic: float = 0.0
    f_p_value: float = 1.0
    model_significant: bool = False
    residual_diagnostics: dict[str, Any] = field(default_factory=dict)


def build_design_matrix(
    persistence_results: list[PersistenceResult],
    edge_counts: list[int],
) -> tuple[np.ndarray, list[str]]:
    """Build the (n_windows, 4) predictor matrix X.

    Columns: TP1, TP2, |E|, k*

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        One per time window.
    edge_counts : list[int]
        Edge count per time window.

    Returns
    -------
    X : np.ndarray of shape (n_windows, 4)
    column_names : list[str]
    """
    n = len(persistence_results)
    X = np.zeros((n, 4), dtype=np.float64)

    for i, pr in enumerate(persistence_results):
        X[i, 0] = pr.total_persistence.get(1, 0.0)
        X[i, 1] = pr.total_persistence.get(2, 0.0)
        X[i, 2] = float(edge_counts[i])
        X[i, 3] = float(pr.max_persistent_dim)

    return X, list(_PREDICTOR_NAMES)


def build_response(rewards: list[RewardComponents]) -> np.ndarray:
    """Extract R_t values as a 1-D array.

    Parameters
    ----------
    rewards : list[RewardComponents]
        One per time window.

    Returns
    -------
    y : np.ndarray of shape (n_windows,)
    """
    return np.array([r.R_t for r in rewards], dtype=np.float64)


def _empty_result(n: int) -> H3Result:
    """Return a zeroed-out H3Result when regression cannot be run."""
    return H3Result(
        n_observations=n,
        r_squared=0.0,
        adj_r_squared=0.0,
        coefficients={name: float("nan") for name in _PREDICTOR_NAMES},
        std_errors={name: float("nan") for name in _PREDICTOR_NAMES},
        t_values={name: float("nan") for name in _PREDICTOR_NAMES},
        p_values={name: 1.0 for name in _PREDICTOR_NAMES},
        beta1_negative=False,
        beta2_negative=False,
        f_statistic=0.0,
        f_p_value=1.0,
        model_significant=False,
        residual_diagnostics={},
    )


def run_h3_test(
    persistence_results: list[PersistenceResult],
    rewards: list[RewardComponents],
    edge_counts: list[int],
) -> H3Result:
    """Run the H3 OLS regression test.

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        Topological features per time window.
    rewards : list[RewardComponents]
        Reward per time window.
    edge_counts : list[int]
        Edge count per time window.

    Returns
    -------
    H3Result with full regression diagnostics.
    """
    n = len(persistence_results)

    # --- Guard: minimum observations ---
    if n < _MIN_OBSERVATIONS:
        logger.warning(
            "H3 requires >= %d observations, got %d. Returning empty result.",
            _MIN_OBSERVATIONS,
            n,
        )
        return _empty_result(n)

    # --- Build matrices ---
    X, col_names = build_design_matrix(persistence_results, edge_counts)
    y = build_response(rewards)

    # --- Handle constant (zero-variance) columns ---
    col_variances = np.var(X, axis=0)
    active_mask = col_variances > 0.0
    dropped_cols = [name for name, keep in zip(col_names, active_mask) if not keep]

    if dropped_cols:
        logger.warning(
            "H3: dropping constant predictors with zero variance: %s", dropped_cols
        )

    active_names = [name for name, keep in zip(col_names, active_mask) if keep]
    X_active = X[:, active_mask]

    # If no predictors remain after dropping, return empty
    if X_active.shape[1] == 0:
        logger.warning("H3: no non-constant predictors remain. Returning empty result.")
        return _empty_result(n)

    # --- Add intercept ---
    X_with_const = sm.add_constant(X_active, has_constant="skip")

    # --- Fit OLS ---
    try:
        model = sm.OLS(y, X_with_const)
        results = model.fit()
    except Exception as exc:
        logger.error("H3: OLS fitting failed: %s", exc)
        return _empty_result(n)

    # --- Extract results ---
    # Parameter names from statsmodels include 'const' at index 0
    param_names = ["const"] + active_names
    coefficients: dict[str, float] = {}
    std_errors: dict[str, float] = {}
    t_values: dict[str, float] = {}
    p_values: dict[str, float] = {}

    for i, name in enumerate(param_names):
        if name == "const":
            coefficients["const"] = float(results.params[i])
            std_errors["const"] = float(results.bse[i])
            t_values["const"] = float(results.tvalues[i])
            p_values["const"] = float(results.pvalues[i])
        else:
            coefficients[name] = float(results.params[i])
            std_errors[name] = float(results.bse[i])
            t_values[name] = float(results.tvalues[i])
            p_values[name] = float(results.pvalues[i])

    # Fill NaN for dropped columns
    for name in dropped_cols:
        coefficients[name] = float("nan")
        std_errors[name] = float("nan")
        t_values[name] = float("nan")
        p_values[name] = 1.0

    # --- Directional significance tests ---
    beta1_negative = (
        coefficients.get("TP1", float("nan")) < 0
        and p_values.get("TP1", 1.0) < 0.05
    )
    beta2_negative = (
        coefficients.get("TP2", float("nan")) < 0
        and p_values.get("TP2", 1.0) < 0.05
    )

    # --- F-test ---
    f_stat = float(results.fvalue) if not np.isnan(results.fvalue) else 0.0
    f_pval = float(results.f_pvalue) if not np.isnan(results.f_pvalue) else 1.0
    model_significant = f_pval < 0.05

    # --- Residual diagnostics ---
    residuals = results.resid
    dw_stat = float(durbin_watson(residuals))

    # Shapiro-Wilk normality test on residuals (max 5000 observations for scipy)
    if len(residuals) >= 3:
        shapiro_stat, shapiro_p = shapiro(residuals)
    else:
        shapiro_stat, shapiro_p = float("nan"), float("nan")

    residual_diagnostics = {
        "durbin_watson": dw_stat,
        "shapiro_wilk_stat": float(shapiro_stat),
        "shapiro_wilk_p": float(shapiro_p),
    }

    logger.info(
        "H3 regression: n=%d, R²=%.4f, adj_R²=%.4f, F=%.3f (p=%.4f), "
        "β_TP1=%.4f (p=%.4f), β_TP2=%.4f (p=%.4f)",
        n,
        results.rsquared,
        results.rsquared_adj,
        f_stat,
        f_pval,
        coefficients.get("TP1", float("nan")),
        p_values.get("TP1", 1.0),
        coefficients.get("TP2", float("nan")),
        p_values.get("TP2", 1.0),
    )

    return H3Result(
        n_observations=n,
        r_squared=float(results.rsquared),
        adj_r_squared=float(results.rsquared_adj),
        coefficients=coefficients,
        std_errors=std_errors,
        t_values=t_values,
        p_values=p_values,
        beta1_negative=beta1_negative,
        beta2_negative=beta2_negative,
        f_statistic=f_stat,
        f_p_value=f_pval,
        model_significant=model_significant,
        residual_diagnostics=residual_diagnostics,
    )
