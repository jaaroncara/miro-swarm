"""Simulation-scoped task persistence with visible issue keys and history."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import Config

_VALID_STATUSES = {"open", "in_progress", "done", "blocked"}
_ISSUE_KEY_RE = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]{1,9})-(?P<number>[1-9]\d*)$")
_GENERIC_PREFIX_TOKENS = {"PROJECT", "PROJ", "SIMULATION", "SIM", "GRAPH"}


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _resolve_tasks_file(base_dir: Path, simulation_id: str) -> Path:
    """Resolve the task file from either uploads/ or uploads/simulations/."""
    if base_dir.name == "simulations":
        return base_dir / simulation_id / "sim_tasks.json"
    return base_dir / "simulations" / simulation_id / "sim_tasks.json"


def _resolve_simulation_dir(base_dir: Path, simulation_id: str) -> Path:
    if base_dir.name == "simulations":
        return base_dir / simulation_id
    return base_dir / "simulations" / simulation_id


def _normalise_prefix_token(token: str) -> Optional[str]:
    cleaned = re.sub(r"[^A-Z0-9]", "", token.upper())
    if len(cleaned) < 2 or not re.search(r"[A-Z]", cleaned):
        return None
    if not cleaned[0].isalpha():
        cleaned = f"S{cleaned}"
    return cleaned[:8]


def _derive_issue_key_prefix(simulation_dir: Path, simulation_id: str) -> str:
    """Build a stable, local Jira-style prefix from simulation metadata."""
    candidates: list[str] = []
    state_path = simulation_dir / "state.json"
    if state_path.exists():
        try:
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
            candidates.extend(
                [
                    str(state_data.get("project_id") or ""),
                    str(state_data.get("graph_id") or ""),
                ]
            )
        except (json.JSONDecodeError, OSError):
            pass

    candidates.append(simulation_id)

    for candidate in candidates:
        if not candidate:
            continue
        raw_tokens = [
            token for token in re.split(r"[^A-Za-z0-9]+", candidate.upper()) if token
        ]
        filtered_tokens = [
            token for token in raw_tokens if token not in _GENERIC_PREFIX_TOKENS
        ]
        for token in filtered_tokens or raw_tokens:
            normalized = _normalise_prefix_token(token)
            if normalized:
                return normalized

    return "SIM"


@dataclass
class TaskEvent:
    """Immutable lifecycle event stored with each simulation task."""

    event_id: str
    event_type: str
    actor: str
    created_at: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        event_type: str,
        actor: str,
        details: Optional[dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> "TaskEvent":
        return cls(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            actor=actor,
            created_at=created_at or _utc_now(),
            details=details or {},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskEvent":
        return cls(
            event_id=str(data.get("event_id") or uuid.uuid4().hex),
            event_type=str(data.get("event_type") or "unknown"),
            actor=str(data.get("actor") or "system"),
            created_at=str(data.get("created_at") or _utc_now()),
            details=dict(data.get("details") or {}),
        )


@dataclass
class SimulationTask:
    """A single task record within a simulation run."""

    task_id: str
    issue_key: str
    sequence_number: int
    simulation_id: str
    title: str
    description: str
    assigned_by: str
    assigned_to: str
    status: str
    created_at: str
    updated_at: str
    parent_goal: Optional[str] = None
    output: Optional[str] = None
    events: list[TaskEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = self.issue_key
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimulationTask":
        return cls(
            task_id=str(data["task_id"]),
            issue_key=str(data["issue_key"]),
            sequence_number=int(data["sequence_number"]),
            simulation_id=str(data["simulation_id"]),
            title=str(data["title"]),
            description=str(data.get("description") or ""),
            assigned_by=str(data.get("assigned_by") or ""),
            assigned_to=str(data.get("assigned_to") or ""),
            status=str(data["status"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            parent_goal=data.get("parent_goal"),
            output=data.get("output"),
            events=[TaskEvent.from_dict(item) for item in data.get("events") or []],
        )


class SimulationTaskStore:
    """Thread-safe, disk-backed task store for one simulation run."""

    def __init__(self, simulation_id: str, base_dir: Path) -> None:
        self._simulation_id = simulation_id
        self._base_dir = Path(base_dir)
        self._simulation_dir = _resolve_simulation_dir(self._base_dir, simulation_id)
        self._tasks_file = _resolve_tasks_file(self._base_dir, simulation_id)
        self._tasks: dict[str, SimulationTask] = {}
        self._lock = threading.Lock()
        self._loaded = False
        self._issue_key_prefix: Optional[str] = None
        self._next_sequence_number = 1

    def _ensure_valid_status(self, status: str) -> None:
        if status not in _VALID_STATUSES:
            valid_values = ", ".join(sorted(_VALID_STATUSES))
            raise ValueError(
                f"Invalid task status '{status}'. Valid values: {valid_values}."
            )

    def _get_issue_key_prefix_locked(self) -> str:
        if self._issue_key_prefix is None:
            self._issue_key_prefix = _derive_issue_key_prefix(
                self._simulation_dir, self._simulation_id
            )
        return self._issue_key_prefix

    def _extract_sequence_number(self, issue_key: str) -> Optional[int]:
        match = _ISSUE_KEY_RE.match(issue_key)
        if match is None:
            return None
        return int(match.group("number"))

    def _build_issue_key_locked(self, sequence_number: int) -> str:
        prefix = self._get_issue_key_prefix_locked()
        return f"{prefix}-{sequence_number}"

    def _resolve_task_locked(self, task_ref: str) -> Optional[SimulationTask]:
        task = self._tasks.get(task_ref)
        if task is not None:
            return task

        for candidate in self._tasks.values():
            if candidate.issue_key == task_ref:
                return candidate

        return None

    def _build_created_event(self, task: SimulationTask) -> TaskEvent:
        return TaskEvent.create(
            event_type="created",
            actor=task.assigned_by or "system",
            created_at=task.created_at,
            details={
                "issue_key": task.issue_key,
                "assigned_to": task.assigned_to,
                "status": task.status,
                "parent_goal": task.parent_goal,
            },
        )

    def _normalise_loaded_task(
        self,
        raw_task: dict[str, Any],
        seen_issue_keys: set[str],
    ) -> tuple[SimulationTask, bool]:
        migrated = False
        task_data = dict(raw_task)

        status = str(task_data.get("status") or "")
        self._ensure_valid_status(status)

        sequence_number = task_data.get("sequence_number")
        if sequence_number is None:
            issue_key = str(task_data.get("issue_key") or "")
            parsed_sequence = (
                self._extract_sequence_number(issue_key) if issue_key else None
            )
            if parsed_sequence is not None:
                sequence_number = parsed_sequence
            else:
                sequence_number = self._next_sequence_number
                migrated = True
            self._next_sequence_number = max(
                self._next_sequence_number, int(sequence_number) + 1
            )
        else:
            sequence_number = int(sequence_number)
            self._next_sequence_number = max(
                self._next_sequence_number, sequence_number + 1
            )

        issue_key = str(task_data.get("issue_key") or "")
        if not issue_key:
            issue_key = self._build_issue_key_locked(int(sequence_number))
            migrated = True
        if self._extract_sequence_number(issue_key) is None:
            issue_key = self._build_issue_key_locked(int(sequence_number))
            migrated = True

        if issue_key in seen_issue_keys:
            raise ValueError(
                f"Duplicate issue_key found while loading tasks: {issue_key}"
            )
        if self._resolve_task_locked(str(task_data["task_id"])) is not None:
            raise ValueError(
                f"Duplicate task_id found while loading tasks: {task_data['task_id']}"
            )

        task_data["issue_key"] = issue_key
        task_data["sequence_number"] = int(sequence_number)
        task_data.setdefault("description", "")
        task_data.setdefault("parent_goal", None)
        task_data.setdefault("output", None)

        events = task_data.get("events") or []
        if not events:
            migrated = True
            synthetic_task = SimulationTask(
                task_id=str(task_data["task_id"]),
                issue_key=issue_key,
                sequence_number=int(sequence_number),
                simulation_id=str(task_data["simulation_id"]),
                title=str(task_data["title"]),
                description=str(task_data.get("description") or ""),
                assigned_by=str(task_data.get("assigned_by") or ""),
                assigned_to=str(task_data.get("assigned_to") or ""),
                status=status,
                created_at=str(task_data["created_at"]),
                updated_at=str(task_data["updated_at"]),
                parent_goal=task_data.get("parent_goal"),
                output=task_data.get("output"),
            )
            task_data["events"] = [asdict(self._build_created_event(synthetic_task))]

        task = SimulationTask.from_dict(task_data)
        seen_issue_keys.add(task.issue_key)
        return task, migrated

    def _load(self) -> None:
        if self._loaded:
            return

        self._loaded = True
        self._get_issue_key_prefix_locked()

        if not self._tasks_file.exists():
            return

        with self._tasks_file.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        if not isinstance(raw, list):
            raise ValueError("Simulation task payload must be a JSON list.")

        migration_required = False
        seen_issue_keys: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Each simulation task entry must be a JSON object.")
            task, migrated = self._normalise_loaded_task(item, seen_issue_keys)
            self._tasks[task.task_id] = task
            migration_required = migration_required or migrated

        if migration_required:
            self._save()

    def _sorted_tasks_locked(self) -> list[SimulationTask]:
        tasks = list(self._tasks.values())
        tasks.sort(key=lambda task: (task.sequence_number, task.created_at))
        return tasks

    def _save(self) -> None:
        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)
        payload = [task.to_dict() for task in self._sorted_tasks_locked()]
        tmp_path = self._tasks_file.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        tmp_path.replace(self._tasks_file)

    def create_task(
        self,
        title: str,
        description: str,
        assigned_by: str,
        assigned_to: str,
        parent_goal: Optional[str] = None,
    ) -> SimulationTask:
        now = _utc_now()
        with self._lock:
            self._load()
            sequence_number = self._next_sequence_number
            self._next_sequence_number += 1
            task = SimulationTask(
                task_id=uuid.uuid4().hex,
                issue_key=self._build_issue_key_locked(sequence_number),
                sequence_number=sequence_number,
                simulation_id=self._simulation_id,
                title=title,
                description=description,
                assigned_by=assigned_by,
                assigned_to=assigned_to,
                status="open",
                created_at=now,
                updated_at=now,
                parent_goal=parent_goal,
            )
            task.events.append(self._build_created_event(task))
            self._tasks[task.task_id] = task
            self._save()
        return task

    def save_task(self, task: SimulationTask) -> SimulationTask:
        self._ensure_valid_status(task.status)
        if self._extract_sequence_number(task.issue_key) is None:
            raise ValueError(f"Invalid issue_key: {task.issue_key}")
        with self._lock:
            self._load()
            existing = self._resolve_task_locked(task.issue_key)
            if existing is not None and existing.task_id != task.task_id:
                raise ValueError(f"Duplicate issue_key detected: {task.issue_key}")
            self._tasks[task.task_id] = task
            self._next_sequence_number = max(
                self._next_sequence_number, task.sequence_number + 1
            )
            self._save()
        return task

    def get_task(self, task_id: str) -> Optional[SimulationTask]:
        with self._lock:
            self._load()
            return self._resolve_task_locked(task_id)

    def get_task_by_issue_key(self, issue_key: str) -> Optional[SimulationTask]:
        return self.get_task(issue_key)

    def list_tasks(
        self,
        assigned_to: Optional[str] = None,
        status: Optional[str] = None,
        completed: Optional[bool] = None,
        issue_key: Optional[str] = None,
    ) -> list[SimulationTask]:
        with self._lock:
            self._load()
            tasks = list(self._tasks.values())

        if assigned_to is not None:
            tasks = [task for task in tasks if task.assigned_to == assigned_to]
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        if completed is not None:
            tasks = [task for task in tasks if (task.status == "done") is completed]
        if issue_key is not None:
            tasks = [task for task in tasks if task.issue_key == issue_key]

        tasks.sort(key=lambda task: (task.sequence_number, task.created_at))
        return tasks

    def update_status(
        self,
        task_id: str,
        status: str,
        output: Optional[str] = None,
        actor: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Optional[SimulationTask]:
        self._ensure_valid_status(status)
        with self._lock:
            self._load()
            task = self._resolve_task_locked(task_id)
            if task is None:
                return None

            previous_status = task.status
            task.status = status
            task.updated_at = _utc_now()
            if status == "done" and output is not None:
                task.output = output

            event_type = {
                "in_progress": "started",
                "blocked": "blocked",
                "done": "completed",
            }.get(status, "status_updated")
            task.events.append(
                TaskEvent.create(
                    event_type=event_type,
                    actor=actor or task.assigned_to or task.assigned_by or "system",
                    details={
                        "issue_key": task.issue_key,
                        "from_status": previous_status,
                        "to_status": status,
                        "note": note,
                        "output": output if status == "done" else None,
                    },
                )
            )
            self._save()
        return task

    def complete_task(
        self,
        task_id: str,
        output: str,
        actor: Optional[str] = None,
    ) -> Optional[SimulationTask]:
        return self.update_status(task_id, status="done", output=output, actor=actor)

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [task.to_dict() for task in self.list_tasks()]


def get_simulation_task_store(
    simulation_id: str,
    base_dir: Optional[Path] = None,
) -> SimulationTaskStore:
    if base_dir is None:
        configured_dir = getattr(Config, "OASIS_SIMULATION_DATA_DIR", "")
        if configured_dir:
            base_dir = Path(configured_dir)
        else:
            base_dir = Path(__file__).parent.parent.parent / "uploads"
    return SimulationTaskStore(simulation_id=simulation_id, base_dir=base_dir)
