"""Figure generators for Figures 1-4 (matplotlib).

Generates the 4 key figures for the research paper (§5):
  - Figure 1: Reward trajectory R_t over simulation rounds
  - Figure 2: Betti number evolution over simulation rounds
  - Figure 3: Persistence diagram at final round
  - Figure 4: Platonic symmetry score S(K) evolution
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

from .homology import PersistenceResult
from .reward import RewardComponents
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.figures")

# ---------------------------------------------------------------------------
# Style & constants
# ---------------------------------------------------------------------------
_DPI = 150
_FIGSIZE = (10, 6)
_STYLE = "seaborn-v0_8-whitegrid"
_PALETTE = plt.cm.tab10  # colorblind-friendly discrete palette


def _apply_style() -> None:
    """Apply clean academic plot style, falling back gracefully."""
    try:
        plt.style.use(_STYLE)
    except OSError:
        # Fallback for older matplotlib versions
        plt.style.use("ggplot")


# ---------------------------------------------------------------------------
# Figure 1 — Reward trajectory
# ---------------------------------------------------------------------------


def plot_reward_trajectory(
    rewards: list[RewardComponents],
    output_path: Path,
) -> Path:
    """Plot coordination reward R_t over simulation rounds.

    Parameters
    ----------
    rewards : list[RewardComponents]
        One entry per time window / simulation round.
    output_path : Path
        Destination file path (e.g. .png).

    Returns
    -------
    Path
        The path the figure was saved to.
    """
    _apply_style()
    fig, ax = plt.subplots(figsize=_FIGSIZE)

    rounds = list(range(len(rewards)))
    r_values = [r.R_t for r in rewards]

    ax.plot(rounds, r_values, marker="o", linewidth=2, markersize=5, color=_PALETTE(0))
    ax.set_xlabel("Simulation Round (time window)", fontsize=12)
    ax.set_ylabel("$R_t$", fontsize=12)
    ax.set_title("Coordination Reward Over Simulation Rounds", fontsize=14)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Figure 1 saved to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Figure 2 — Betti number evolution
# ---------------------------------------------------------------------------


def plot_betti_evolution(
    persistence_results: list[PersistenceResult],
    output_path: Path,
    max_dim: int = 4,
) -> Path:
    """Plot Betti numbers (b0, b1, ...) over simulation rounds.

    Parameters
    ----------
    persistence_results : list[PersistenceResult]
        One PersistenceResult per time window.
    output_path : Path
        Destination file path.
    max_dim : int
        Maximum homological dimension to display.

    Returns
    -------
    Path
        The path the figure was saved to.
    """
    _apply_style()
    fig, ax = plt.subplots(figsize=_FIGSIZE)

    rounds = list(range(len(persistence_results)))

    for dim in range(max_dim + 1):
        values = [
            pr.betti_numbers.get(dim, 0) for pr in persistence_results
        ]
        ax.plot(
            rounds,
            values,
            marker="s",
            linewidth=2,
            markersize=4,
            color=_PALETTE(dim),
            label=f"$\\beta_{dim}$",
        )

    ax.set_xlabel("Simulation Round (time window)", fontsize=12)
    ax.set_ylabel("Betti Number", fontsize=12)
    ax.set_title("Betti Number Evolution", fontsize=14)
    ax.legend(fontsize=11, loc="best")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Figure 2 saved to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Figure 3 — Persistence diagram (final round)
# ---------------------------------------------------------------------------


def plot_persistence_diagram(
    persistence_result: PersistenceResult,
    output_path: Path,
    max_dim: int = 4,
) -> Path:
    """Plot a standard TDA persistence diagram (birth vs death).

    Parameters
    ----------
    persistence_result : PersistenceResult
        Homology result for the final time window.
    output_path : Path
        Destination file path.
    max_dim : int
        Maximum dimension to show.

    Returns
    -------
    Path
        The path the figure was saved to.
    """
    _apply_style()
    fig, ax = plt.subplots(figsize=_FIGSIZE)

    # Collect all birth/death points across dimensions
    all_births: list[float] = []
    all_deaths: list[float] = []

    for dim in range(max_dim + 1):
        diagram = persistence_result.persistence_diagrams.get(dim, np.empty((0, 2)))
        if diagram.size == 0:
            continue
        births = diagram[:, 0]
        deaths = diagram[:, 1]
        ax.scatter(
            births,
            deaths,
            color=_PALETTE(dim),
            label=f"dim {dim}",
            s=40,
            alpha=0.7,
            edgecolors="k",
            linewidths=0.3,
        )
        all_births.extend(births.tolist())
        all_deaths.extend(deaths.tolist())

    # Diagonal reference line (birth = death)
    if all_births and all_deaths:
        lo = min(min(all_births), min(all_deaths), 0.0)
        hi = max(max(all_births), max(all_deaths))
        margin = (hi - lo) * 0.05
        ax.plot(
            [lo - margin, hi + margin],
            [lo - margin, hi + margin],
            "k--",
            linewidth=1,
            alpha=0.5,
            label="birth = death",
        )
        ax.set_xlim(lo - margin, hi + margin)
        ax.set_ylim(lo - margin, hi + margin)
    else:
        ax.plot([0, 1], [0, 1], "k--", linewidth=1, alpha=0.5, label="birth = death")

    ax.set_xlabel("Birth", fontsize=12)
    ax.set_ylabel("Death", fontsize=12)
    ax.set_title("Persistence Diagram (Final Round)", fontsize=14)
    ax.legend(fontsize=10, loc="lower right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Figure 3 saved to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Figure 4 — Symmetry score evolution
# ---------------------------------------------------------------------------


def plot_symmetry_evolution(
    symmetry_scores: np.ndarray,
    null_threshold: float,
    output_path: Path,
) -> Path:
    """Plot platonic symmetry score S(K) over simulation rounds.

    Parameters
    ----------
    symmetry_scores : np.ndarray
        1-D array of S(K) values, one per time window.
    null_threshold : float
        95th percentile from the null model, shown as horizontal reference.
    output_path : Path
        Destination file path.

    Returns
    -------
    Path
        The path the figure was saved to.
    """
    _apply_style()
    fig, ax = plt.subplots(figsize=_FIGSIZE)

    rounds = list(range(len(symmetry_scores)))

    ax.plot(
        rounds,
        symmetry_scores,
        marker="D",
        linewidth=2,
        markersize=5,
        color=_PALETTE(0),
        label="$S(K)$",
    )
    ax.axhline(
        y=null_threshold,
        color="red",
        linestyle="--",
        linewidth=1.5,
        label="95th percentile null",
    )

    ax.set_xlabel("Simulation Round (time window)", fontsize=12)
    ax.set_ylabel("$S(K)$", fontsize=12)
    ax.set_title("Platonic Symmetry Score $S(K)$ Over Rounds", fontsize=14)
    ax.legend(fontsize=11, loc="best")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Figure 4 saved to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Orchestrator — generate all figures
# ---------------------------------------------------------------------------


def generate_all_figures(
    rewards: list[RewardComponents],
    persistence_results: list[PersistenceResult],
    symmetry_scores: np.ndarray,
    null_threshold: float,
    output_dir: Path,
) -> dict[str, Path]:
    """Generate all 4 paper figures and save to output_dir.

    Parameters
    ----------
    rewards : list[RewardComponents]
        Reward data per time window.
    persistence_results : list[PersistenceResult]
        Homology results per time window.
    symmetry_scores : np.ndarray
        S(K) values per time window.
    null_threshold : float
        95th percentile from null model for symmetry reference line.
    output_dir : Path
        Directory to save figures into (created if needed).

    Returns
    -------
    dict[str, Path]
        Mapping of figure name to saved file path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    figures: dict[str, Path] = {}

    # Figure 1 — Reward trajectory
    figures["fig1_reward"] = plot_reward_trajectory(
        rewards=rewards,
        output_path=output_dir / "fig1_reward.png",
    )

    # Figure 2 — Betti evolution
    figures["fig2_betti"] = plot_betti_evolution(
        persistence_results=persistence_results,
        output_path=output_dir / "fig2_betti.png",
    )

    # Figure 3 — Persistence diagram (final round)
    if persistence_results:
        figures["fig3_persistence"] = plot_persistence_diagram(
            persistence_result=persistence_results[-1],
            output_path=output_dir / "fig3_persistence.png",
        )
    else:
        logger.warning("No persistence results available; skipping Figure 3.")

    # Figure 4 — Symmetry evolution
    figures["fig4_symmetry"] = plot_symmetry_evolution(
        symmetry_scores=symmetry_scores,
        null_threshold=null_threshold,
        output_path=output_dir / "fig4_symmetry.png",
    )

    logger.info(f"All figures generated in {output_dir}: {list(figures.keys())}")
    return figures
