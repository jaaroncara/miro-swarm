"""Load and window MCP task-tool events from SimulationTaskStore."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ...config import Config
from ...core.simulation_task_store import SimulationTaskStore, get_simulation_task_store
from ...utils.logger import get_logger

logger = get_logger("mirofish.topology_analysis.events")


@dataclass
class CoordinationEvent:
    task_id: str
    event_type: str
    actor: str
    timestamp: datetime
    round_index: Optional[int]
    details: dict


@dataclass
class TimeWindow:
    window_id: int
    start_round: int
    end_round: int
    events: list[CoordinationEvent] = field(default_factory=list)


def load_events(simulation_id: str, base_dir: Path) -> list[CoordinationEvent]:
    store = get_simulation_task_store(simulation_id, base_dir=base_dir)
    tasks = store.list_tasks()

    if not tasks:
        logger.debug("No tasks found for simulation %s", simulation_id)
        return []

    events: list[CoordinationEvent] = []
    for task in tasks:
        for te in task.events:
            events.append(
                CoordinationEvent(
                    task_id=task.task_id,
                    event_type=te.event_type,
                    actor=te.actor,
                    timestamp=datetime.fromisoformat(te.created_at),
                    round_index=te.round_index,
                    details=te.details,
                )
            )

    events.sort(key=lambda e: e.timestamp)
    logger.debug(
        "Loaded %d events from %d tasks for simulation %s",
        len(events),
        len(tasks),
        simulation_id,
    )
    return events


def _infer_round_index(
    event: CoordinationEvent,
    round_boundaries: list[tuple[int, datetime]],
) -> int:
    if not round_boundaries:
        return 0
    for round_idx, boundary_ts in reversed(round_boundaries):
        if event.timestamp >= boundary_ts:
            return round_idx
    return round_boundaries[0][0]


def window_events(
    events: list[CoordinationEvent],
    window_size: int = Config.TOPOLOGY_WINDOW_SIZE,
) -> list[TimeWindow]:
    if not events:
        return []

    round_boundaries: list[tuple[int, datetime]] = sorted(
        [(e.round_index, e.timestamp) for e in events if e.round_index is not None],
        key=lambda x: x[0],
    )

    effective_rounds: list[tuple[CoordinationEvent, int]] = []
    for event in events:
        if event.round_index is not None:
            effective_rounds.append((event, event.round_index))
        else:
            inferred = _infer_round_index(event, round_boundaries)
            effective_rounds.append((event, inferred))

    if not effective_rounds:
        return []

    min_round = min(r for _, r in effective_rounds)
    max_round = max(r for _, r in effective_rounds)

    windows: list[TimeWindow] = []
    window_id = 0
    start = min_round
    while start <= max_round:
        end = start + window_size - 1
        window = TimeWindow(
            window_id=window_id,
            start_round=start,
            end_round=end,
        )
        for event, r in effective_rounds:
            if start <= r <= end:
                window.events.append(event)
        windows.append(window)
        window_id += 1
        start = end + 1

    return windows


def get_actors_per_task(window: TimeWindow) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for event in window.events:
        if event.task_id not in mapping:
            mapping[event.task_id] = set()
        mapping[event.task_id].add(event.actor)
    return mapping
