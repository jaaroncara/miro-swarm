"""
Compute synthetic observed reward time series R_t from task telemetry.

The reward is NOT used for optimization — it serves as the dependent variable
in the H3 regression test (topology complexity → coordination reward).
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional

from .events import CoordinationEvent, TimeWindow, get_actors_per_task
from ...config import Config
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.reward")


@dataclass
class RewardComponents:
    """Decomposed reward for a single time window."""

    completion_rate: float
    type_coverage: int
    mean_latency: float
    R_t: float


def compute_window_reward(
    window: TimeWindow,
    agent_types: dict[str, str],
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 0.1,
) -> RewardComponents:
    """
    Compute composite reward for a single TimeWindow.

    Parameters
    ----------
    window : TimeWindow
        A time window containing coordination events.
    agent_types : dict[str, str]
        Mapping of actor name → entity type (e.g. "agent-1" → "planner").
    alpha : float
        Weight for completion rate component.
    beta : float
        Weight for type coverage bonus.
    gamma : float
        Penalty weight for mean latency.

    Returns
    -------
    RewardComponents with completion_rate, type_coverage, mean_latency, and R_t.
    """
    # Edge case: no events in window
    if not window.events:
        logger.debug("Window %s has no events — reward = 0.0", window.window_id)
        return RewardComponents(
            completion_rate=0.0, type_coverage=0, mean_latency=0.0, R_t=0.0
        )

    # --- Completion rate ---
    tasks: dict[str, list[CoordinationEvent]] = {}
    for ev in window.events:
        tasks.setdefault(ev.task_id, []).append(ev)

    total_tasks = len(tasks)
    completed_tasks: set[str] = set()
    for task_id, events in tasks.items():
        for ev in events:
            if "complete" in ev.event_type.lower() or "done" in ev.event_type.lower():
                completed_tasks.add(task_id)
                break

    completion_rate = len(completed_tasks) / total_tasks if total_tasks > 0 else 0.0

    # --- Type coverage ---
    actors_per_task = get_actors_per_task(window)
    all_actors: set[str] = set()
    for actor_set in actors_per_task.values():
        all_actors.update(actor_set)

    distinct_types: set[str] = set()
    for actor in all_actors:
        if actor in agent_types:
            distinct_types.add(agent_types[actor])

    k = len(distinct_types)
    K_max = len(set(agent_types.values())) if agent_types else 0

    # Quadratic (convex) bonus
    type_coverage_bonus = (k / K_max) ** 2 if K_max > 0 else 0.0

    # --- Mean latency ---
    if completed_tasks:
        latencies: list[float] = []
        for task_id in completed_tasks:
            task_events = tasks[task_id]
            # Try round-based latency first
            rounds = [
                ev.round_index for ev in task_events if ev.round_index is not None
            ]
            if len(rounds) >= 2:
                latency = max(rounds) - min(rounds)
                latencies.append(float(latency))
            else:
                # Fall back to timestamp-based (in hours)
                timestamps = [ev.timestamp for ev in task_events]
                if len(timestamps) >= 2:
                    delta = (max(timestamps) - min(timestamps)).total_seconds() / 3600
                    latencies.append(delta)

        if latencies:
            raw_mean_latency = sum(latencies) / len(latencies)
            # Normalize by window size (number of rounds)
            window_size = window.end_round - window.start_round
            normalized_latency = (
                raw_mean_latency / window_size if window_size > 0 else 1.0
            )
        else:
            normalized_latency = 1.0
    else:
        # No completed tasks → maximum penalty
        normalized_latency = 1.0

    # --- Composite R_t ---
    R_t = alpha * completion_rate + beta * type_coverage_bonus - gamma * normalized_latency
    R_t = max(R_t, 0.0)  # Clamp to [0, ∞)

    logger.debug(
        "Window %s: completion=%.3f, types=%d (bonus=%.3f), latency=%.3f → R_t=%.4f",
        window.window_id,
        completion_rate,
        k,
        type_coverage_bonus,
        normalized_latency,
        R_t,
    )

    return RewardComponents(
        completion_rate=completion_rate,
        type_coverage=k,
        mean_latency=normalized_latency,
        R_t=R_t,
    )


def compute_reward_series(
    windows: list[TimeWindow],
    agent_types: dict[str, str],
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    gamma: Optional[float] = None,
) -> list[RewardComponents]:
    """
    Compute RewardComponents for each window in sequence.

    Parameters
    ----------
    windows : list[TimeWindow]
        Ordered list of time windows.
    agent_types : dict[str, str]
        Actor → entity type mapping.
    alpha, beta, gamma : float or None
        Reward weights. Falls back to Config defaults when None.

    Returns
    -------
    Ordered list of RewardComponents, one per window.
    """
    _alpha = alpha if alpha is not None else Config.TOPOLOGY_REWARD_ALPHA
    _beta = beta if beta is not None else Config.TOPOLOGY_REWARD_BETA
    _gamma = gamma if gamma is not None else Config.TOPOLOGY_REWARD_GAMMA

    logger.info(
        "Computing reward series over %d windows (α=%.2f, β=%.2f, γ=%.3f)",
        len(windows),
        _alpha,
        _beta,
        _gamma,
    )

    return [
        compute_window_reward(w, agent_types, alpha=_alpha, beta=_beta, gamma=_gamma)
        for w in windows
    ]


def reward_curve(reward_series: list[RewardComponents]) -> np.ndarray:
    """
    Extract R_t values as a 1D numpy array for plotting and H3 regression.

    Parameters
    ----------
    reward_series : list[RewardComponents]
        Output of compute_reward_series.

    Returns
    -------
    np.ndarray of shape (T,) containing the R_t value per window.
    """
    return np.array([rc.R_t for rc in reward_series], dtype=np.float64)
