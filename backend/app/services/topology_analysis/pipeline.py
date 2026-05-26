"""Pipeline entrypoint: analyze(simulation_id) -> full topology analysis.

Orchestrates the complete sequence:
  events -> graphs -> complexes -> homology -> S(K) / δ_P -> reward -> H1/H2/H3 -> figures

Outputs are persisted under:
  backend/data/<simulation_id>/topology/{snapshots/, metrics.json, figures/}
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ...config import Config
from ...core.simulation_task_store import get_simulation_task_store
from ...utils.logger import get_logger
from .events import load_events, window_events, get_actors_per_task
from .graph import build_snapshot, save_snapshot, TopologySnapshot
from .complex import create_simplex_tree_from_adjacency
from .homology import PersistenceResult, compute_persistence_from_adjacency
from .symmetry import compute_symmetry_score, compute_symmetry_curve
from .nullmodel import compute_null_thresholds_for_snapshots
from .reward import RewardComponents, compute_reward_series, reward_curve
from .figures import generate_all_figures
from .tests.h1 import H1Result, run_h1_test
from .tests.h2 import H2Result, run_h2_test
from .tests.h3 import H3Result, run_h3_test

logger = get_logger("mirofish.topology_analysis.pipeline")


def _default_output_dir(simulation_id: str) -> Path:
    """Resolve default output directory for topology analysis artifacts."""
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent
    return backend_dir / "data" / simulation_id / "topology"


def _collect_agent_roster(simulation_id: str, base_dir: Optional[Path] = None) -> list[str]:
    """Collect the ordered list of all distinct actors from the task store."""
    store = get_simulation_task_store(simulation_id, base_dir=base_dir)
    tasks = store.list_tasks()
    actors: set[str] = set()
    for task in tasks:
        if task.assigned_by:
            actors.add(task.assigned_by)
        if task.assigned_to:
            actors.add(task.assigned_to)
        for event in task.events:
            if event.actor:
                actors.add(event.actor)
    return sorted(actors)


def _collect_agent_types(simulation_id: str, base_dir: Optional[Path] = None) -> dict[str, str]:
    """Collect agent_id -> entity_type mapping from the task store metadata.

    Falls back to 'unknown' for agents without a resolvable type.
    """
    store = get_simulation_task_store(simulation_id, base_dir=base_dir)
    tasks = store.list_tasks()
    agent_types: dict[str, str] = {}
    for task in tasks:
        for event in task.events:
            if event.actor and event.actor not in agent_types:
                actor_type = event.details.get("entity_type", "unknown")
                agent_types[event.actor] = actor_type
    return agent_types


def analyze(
    simulation_id: str,
    *,
    base_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    window_size: Optional[int] = None,
    null_model_m: Optional[int] = None,
    max_dim: Optional[int] = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Run the full topology analysis pipeline for a completed simulation.

    Parameters
    ----------
    simulation_id : str
        The simulation to analyze.
    base_dir : Path, optional
        Base directory for the simulation task store. Uses Config default if None.
    output_dir : Path, optional
        Output directory for artifacts. Defaults to data/<sim_id>/topology/.
    window_size : int, optional
        Number of rounds per time window. Defaults to Config.TOPOLOGY_WINDOW_SIZE.
    null_model_m : int, optional
        Number of null-model permutations. Defaults to Config.TOPOLOGY_NULL_MODEL_M.
    max_dim : int, optional
        Maximum simplex dimension for TDA. Defaults to Config.TOPOLOGY_MAX_DIM.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict with keys: 'output_dir', 'n_windows', 'h1', 'h2', 'h3', 'figures'
    """
    t_start = time.time()
    _window_size = window_size or Config.TOPOLOGY_WINDOW_SIZE
    _null_m = null_model_m or Config.TOPOLOGY_NULL_MODEL_M
    _max_dim = max_dim or Config.TOPOLOGY_MAX_DIM
    _output_dir = Path(output_dir) if output_dir else _default_output_dir(simulation_id)
    _output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting topology analysis: sim=%s, window_size=%d, M=%d, max_dim=%d",
        simulation_id, _window_size, _null_m, _max_dim,
    )

    # --- Phase 1: Load events and build time windows ---
    events = load_events(simulation_id, base_dir or Path(""))
    if not events:
        logger.warning("No events found for simulation %s — aborting.", simulation_id)
        return {"output_dir": str(_output_dir), "n_windows": 0, "error": "no_events"}

    windows = window_events(events, window_size=_window_size)
    n_windows = len(windows)
    logger.info("Phase 1 complete: %d events → %d windows", len(events), n_windows)

    # --- Phase 2: Build graphs + snapshots ---
    agent_ids = _collect_agent_roster(simulation_id, base_dir=base_dir)
    agent_types = _collect_agent_types(simulation_id, base_dir=base_dir)
    logger.info("Agent roster: %d agents, %d typed", len(agent_ids), len(agent_types))

    snapshots_dir = _output_dir / "snapshots"
    snapshots: list[TopologySnapshot] = []
    for window in windows:
        snapshot = build_snapshot(window, agent_ids)
        snapshot.agent_types = agent_types
        save_snapshot(snapshot, snapshots_dir)
        snapshots.append(snapshot)

    logger.info("Phase 2 complete: %d snapshots built and saved", len(snapshots))

    # --- Phase 3: Persistent homology ---
    persistence_results: list[PersistenceResult] = []
    for snap in snapshots:
        pr = compute_persistence_from_adjacency(snap.adjacency_symmetric, max_dim=_max_dim)
        persistence_results.append(pr)

    logger.info("Phase 3 complete: persistent homology computed for %d snapshots", len(persistence_results))

    # --- Phase 4: Symmetry scores ---
    symmetry_scores = compute_symmetry_curve(
        [s.adjacency_symmetric for s in snapshots]
    )
    logger.info("Phase 4 complete: symmetry scores computed (mean=%.4f)", symmetry_scores.mean())

    # --- Phase 5: Null model ---
    null_thresholds = compute_null_thresholds_for_snapshots(
        [s.adjacency_symmetric for s in snapshots],
        M=_null_m,
        max_dim=_max_dim,
        seed=seed,
    )
    logger.info("Phase 5 complete: null thresholds computed (M=%d)", _null_m)

    # --- Phase 6: Reward series ---
    rewards = compute_reward_series(windows, agent_types)
    logger.info("Phase 6 complete: reward series computed")

    # --- Phase 7: Hypothesis tests ---
    edge_counts = [int(s.adjacency_symmetric.nnz // 2) for s in snapshots]

    h1_result = run_h1_test(persistence_results, null_thresholds, rewards, edge_counts)
    h2_result = run_h2_test(symmetry_scores, rewards, persistence_results, null_thresholds)
    h3_result = run_h3_test(persistence_results, rewards, edge_counts)

    logger.info(
        "Phase 7 complete: H1(sig=%s, d=%.3f) H2(all_pass=%s) H3(model_sig=%s, R²=%.3f)",
        h1_result.significant, h1_result.cohens_d,
        h2_result.all_pass,
        h3_result.model_significant, h3_result.r_squared,
    )

    # --- Phase 8: Figures ---
    figures_dir = _output_dir / "figures"
    null_threshold_for_plot = float(np.median([
        max(t.values()) for t in null_thresholds if t
    ])) if null_thresholds else 0.0

    figure_paths = generate_all_figures(
        rewards=rewards,
        persistence_results=persistence_results,
        symmetry_scores=symmetry_scores,
        null_threshold=null_threshold_for_plot,
        output_dir=figures_dir,
    )
    logger.info("Phase 8 complete: %d figures generated", len(figure_paths))

    # --- Save metrics summary ---
    elapsed = time.time() - t_start
    metrics = {
        "simulation_id": simulation_id,
        "n_windows": n_windows,
        "n_agents": len(agent_ids),
        "n_agent_types": len(set(agent_types.values())),
        "window_size": _window_size,
        "null_model_m": _null_m,
        "max_dim": _max_dim,
        "seed": seed,
        "elapsed_seconds": round(elapsed, 2),
        "h1": {
            "significant": h1_result.significant,
            "cohens_d": h1_result.cohens_d,
            "p_value": h1_result.p_value,
            "n_higher_order": h1_result.n_higher_order,
            "n_pairwise_only": h1_result.n_pairwise_only,
        },
        "h2": {
            "all_pass": h2_result.all_pass,
            "s_monotonic": h2_result.s_monotonic,
            "top_greater": h2_result.top_greater,
            "b0_is_one": h2_result.b0_is_one,
            "single_high_dim_feature": h2_result.single_high_dim_feature,
        },
        "h3": {
            "model_significant": h3_result.model_significant,
            "r_squared": h3_result.r_squared,
            "adj_r_squared": h3_result.adj_r_squared,
            "beta1_negative": h3_result.beta1_negative,
            "beta2_negative": h3_result.beta2_negative,
        },
        "figures": {k: str(v) for k, v in figure_paths.items()},
    }

    metrics_path = _output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    logger.info(
        "Topology analysis complete for %s in %.1fs — results at %s",
        simulation_id, elapsed, _output_dir,
    )

    return metrics
