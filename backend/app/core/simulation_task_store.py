"""Simulation-scoped task persistence with lifecycle metadata and artifact staging."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from ..config import Config
from .task_observability import log_task_pipeline_metric

if os.name == "nt":
    import msvcrt
else:
    import fcntl

TASK_STATUS_OFFERED = "offered"
TASK_STATUS_OPEN = "open"
TASK_STATUS_IN_PROGRESS = "in_progress"
TASK_STATUS_BLOCKED = "blocked"
TASK_STATUS_DONE = "done"
TASK_STATUS_DECLINED = "declined"
TASK_STATUS_EXPIRED = "expired"

TASK_STATUS_ORDER = (
    TASK_STATUS_OFFERED,
    TASK_STATUS_OPEN,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DONE,
    TASK_STATUS_DECLINED,
    TASK_STATUS_EXPIRED,
)
TASK_STATUSES = set(TASK_STATUS_ORDER)
TERMINAL_TASK_STATUSES = {
    TASK_STATUS_DONE,
    TASK_STATUS_DECLINED,
    TASK_STATUS_EXPIRED,
}

_ISSUE_KEY_RE = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]{1,9})-(?P<number>[1-9]\d*)$")
_GENERIC_PREFIX_TOKENS = {"PROJECT", "PROJ", "SIMULATION", "SIM", "GRAPH"}
_DEFAULT_ARTIFACT_DIRNAME = "task_artifacts"
_DEFAULT_NOTIFICATION_FILENAME = "task_notifications.json"


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def _normalise_metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    return {"raw": value}


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


def _sanitize_artifact_filename(filename: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", (filename or "artifact").strip())
    sanitized = sanitized.strip("._") or "artifact"
    return sanitized[:128]


@contextmanager
def _exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)

        if os.name == "nt":
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


@dataclass
class TaskArtifactRef:
    """Reference to a staged task artifact under the simulation uploads tree."""

    artifact_id: str
    filename: str
    relative_path: str
    media_type: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)
    created_by: Optional[str] = None
    kind: str = "deliverable"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskArtifactRef":
        return cls(
            artifact_id=str(data.get("artifact_id") or uuid.uuid4().hex),
            filename=str(data.get("filename") or "artifact"),
            relative_path=str(data.get("relative_path") or ""),
            media_type=data.get("media_type"),
            size_bytes=_coerce_optional_int(data.get("size_bytes")),
            checksum_sha256=data.get("checksum_sha256"),
            created_at=str(data.get("created_at") or _utc_now()),
            created_by=data.get("created_by"),
            kind=str(data.get("kind") or "deliverable"),
        )


@dataclass
class TaskNotification:
    """Persistent notification delivered to an agent during task injection."""

    notification_id: str
    simulation_id: str
    recipient: str
    message: str
    created_at: str
    category: str = "task_update"
    task_ref: Optional[str] = None
    created_by: Optional[str] = None
    event_type: Optional[str] = None
    round_index: Optional[int] = None
    delivered_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskNotification":
        return cls(
            notification_id=str(data.get("notification_id") or uuid.uuid4().hex),
            simulation_id=str(data.get("simulation_id") or ""),
            recipient=str(data.get("recipient") or ""),
            message=str(data.get("message") or ""),
            created_at=str(data.get("created_at") or _utc_now()),
            category=str(data.get("category") or "task_update"),
            task_ref=data.get("task_ref"),
            created_by=data.get("created_by"),
            event_type=data.get("event_type"),
            round_index=_coerce_optional_int(data.get("round_index")),
            delivered_at=data.get("delivered_at"),
            metadata=_normalise_metadata_dict(data.get("metadata")),
        )


@dataclass
class TaskEvent:
    """Immutable lifecycle event stored with each simulation task."""

    event_id: str
    event_type: str
    actor: str
    created_at: str
    details: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[TaskArtifactRef] = field(default_factory=list)
    round_index: Optional[int] = None

    @classmethod
    def create(
        cls,
        event_type: str,
        actor: str,
        details: Optional[dict[str, Any]] = None,
        created_at: Optional[str] = None,
        artifact_refs: Optional[list[TaskArtifactRef]] = None,
        round_index: Optional[int] = None,
    ) -> "TaskEvent":
        return cls(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            actor=actor,
            created_at=created_at or _utc_now(),
            details=details or {},
            artifact_refs=list(artifact_refs or []),
            round_index=round_index,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskEvent":
        return cls(
            event_id=str(data.get("event_id") or uuid.uuid4().hex),
            event_type=str(data.get("event_type") or "unknown"),
            actor=str(data.get("actor") or "system"),
            created_at=str(data.get("created_at") or _utc_now()),
            details=dict(data.get("details") or {}),
            artifact_refs=[
                TaskArtifactRef.from_dict(item)
                for item in data.get("artifact_refs") or []
            ],
            round_index=_coerce_optional_int(data.get("round_index")),
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
    origin: str = "manual"
    origin_metadata: dict[str, Any] = field(default_factory=dict)
    mention_context: dict[str, Any] = field(default_factory=dict)
    created_round: Optional[int] = None
    due_round: Optional[int] = None
    round_budget: Optional[int] = None
    deadline_at: Optional[str] = None
    artifact_refs: list[TaskArtifactRef] = field(default_factory=list)
    events: list[TaskEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = self.issue_key
        payload["is_terminal"] = self.status in TERMINAL_TASK_STATUSES
        payload["has_deadline"] = (
            self.deadline_at is not None or self.due_round is not None
        )
        payload["artifact_count"] = len(self.artifact_refs)
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
            origin=str(data.get("origin") or "manual"),
            origin_metadata=_normalise_metadata_dict(data.get("origin_metadata")),
            mention_context=_normalise_metadata_dict(data.get("mention_context")),
            created_round=_coerce_optional_int(data.get("created_round")),
            due_round=_coerce_optional_int(data.get("due_round")),
            round_budget=_coerce_optional_int(data.get("round_budget")),
            deadline_at=data.get("deadline_at"),
            artifact_refs=[
                TaskArtifactRef.from_dict(item)
                for item in data.get("artifact_refs") or []
            ],
            events=[TaskEvent.from_dict(item) for item in data.get("events") or []],
        )


class SimulationTaskStore:
    """Thread-safe, disk-backed task store for one simulation run."""

    def __init__(self, simulation_id: str, base_dir: Path) -> None:
        self._simulation_id = simulation_id
        self._base_dir = Path(base_dir)
        self._simulation_dir = _resolve_simulation_dir(self._base_dir, simulation_id)
        self._tasks_file = _resolve_tasks_file(self._base_dir, simulation_id)
        self._notifications_file = self._simulation_dir / _DEFAULT_NOTIFICATION_FILENAME
        self._lock_file = self._tasks_file.with_suffix(".lock")
        self._artifact_dir = self._simulation_dir / _DEFAULT_ARTIFACT_DIRNAME
        self._tasks: dict[str, SimulationTask] = {}
        self._notifications: list[TaskNotification] = []
        self._lock = threading.RLock()
        self._issue_key_prefix: Optional[str] = None
        self._next_sequence_number = 1

    def _ensure_valid_status(self, status: str) -> None:
        if status not in TASK_STATUSES:
            valid_values = ", ".join(TASK_STATUS_ORDER)
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

    def _clone_task(self, task: SimulationTask) -> SimulationTask:
        return SimulationTask.from_dict(task.to_dict())

    def _default_event_details(self, task: SimulationTask) -> dict[str, Any]:
        return {
            "issue_key": task.issue_key,
            "assigned_to": task.assigned_to,
            "assigned_by": task.assigned_by,
            "status": task.status,
            "parent_goal": task.parent_goal,
            "origin": task.origin,
            "origin_metadata": dict(task.origin_metadata),
            "mention_context": dict(task.mention_context),
            "created_round": task.created_round,
            "due_round": task.due_round,
            "round_budget": task.round_budget,
            "deadline_at": task.deadline_at,
            "artifact_count": len(task.artifact_refs),
        }

    def _build_created_event(
        self,
        task: SimulationTask,
        *,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        note: Optional[str] = None,
    ) -> TaskEvent:
        details = self._default_event_details(task)
        if note:
            details["note"] = note
        return TaskEvent.create(
            event_type=event_type
            or ("offered" if task.status == TASK_STATUS_OFFERED else "created"),
            actor=actor or task.assigned_by or "system",
            created_at=task.created_at,
            details=details,
            artifact_refs=list(task.artifact_refs),
            round_index=task.created_round,
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
        sequence_number = int(sequence_number)
        self._next_sequence_number = max(
            self._next_sequence_number, sequence_number + 1
        )

        issue_key = str(task_data.get("issue_key") or "")
        if not issue_key or self._extract_sequence_number(issue_key) is None:
            issue_key = self._build_issue_key_locked(sequence_number)
            migrated = True

        if issue_key in seen_issue_keys:
            raise ValueError(
                f"Duplicate issue_key found while loading tasks: {issue_key}"
            )
        if self._resolve_task_locked(str(task_data["task_id"])) is not None:
            raise ValueError(
                f"Duplicate task_id found while loading tasks: {task_data['task_id']}"
            )

        if "origin" not in task_data:
            task_data["origin"] = "legacy"
            migrated = True
        if "origin_metadata" not in task_data:
            task_data["origin_metadata"] = {}
            migrated = True
        else:
            task_data["origin_metadata"] = _normalise_metadata_dict(
                task_data.get("origin_metadata")
            )
        if "mention_context" not in task_data:
            task_data["mention_context"] = {}
            migrated = True
        else:
            task_data["mention_context"] = _normalise_metadata_dict(
                task_data.get("mention_context")
            )

        for key in ("created_round", "due_round", "round_budget"):
            if key not in task_data:
                task_data[key] = None
                migrated = True
            else:
                task_data[key] = _coerce_optional_int(task_data.get(key))

        if "deadline_at" not in task_data:
            task_data["deadline_at"] = None
            migrated = True

        artifact_refs = task_data.get("artifact_refs")
        if artifact_refs is None:
            artifact_refs = task_data.pop("artifacts", []) or []
            task_data["artifact_refs"] = artifact_refs
            migrated = True

        task_data["issue_key"] = issue_key
        task_data["sequence_number"] = sequence_number
        task_data.setdefault("description", "")
        task_data.setdefault("parent_goal", None)
        task_data.setdefault("output", None)

        events = task_data.get("events") or []
        if not events:
            migrated = True
            synthetic_task = SimulationTask(
                task_id=str(task_data["task_id"]),
                issue_key=issue_key,
                sequence_number=sequence_number,
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
                origin=str(task_data.get("origin") or "legacy"),
                origin_metadata=_normalise_metadata_dict(
                    task_data.get("origin_metadata")
                ),
                mention_context=_normalise_metadata_dict(
                    task_data.get("mention_context")
                ),
                created_round=_coerce_optional_int(task_data.get("created_round")),
                due_round=_coerce_optional_int(task_data.get("due_round")),
                round_budget=_coerce_optional_int(task_data.get("round_budget")),
                deadline_at=task_data.get("deadline_at"),
                artifact_refs=[
                    TaskArtifactRef.from_dict(item)
                    for item in task_data.get("artifact_refs") or []
                ],
            )
            task_data["events"] = [asdict(self._build_created_event(synthetic_task))]

        task = SimulationTask.from_dict(task_data)
        seen_issue_keys.add(task.issue_key)
        return task, migrated

    @contextmanager
    def _locked_state(self) -> Iterator[None]:
        with self._lock:
            with _exclusive_file_lock(self._lock_file):
                self._load_locked()
                self._load_notifications_locked()
                yield

    def _load_locked(self) -> None:
        self._tasks = {}
        self._next_sequence_number = 1
        self._get_issue_key_prefix_locked()

        if not self._tasks_file.exists():
            return

        with self._tasks_file.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

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
            self._save_locked()
            log_task_pipeline_metric(
                "migration_applied",
                simulation_id=self._simulation_id,
                task_count=len(self._tasks),
            )

    def _sorted_tasks_locked(self) -> list[SimulationTask]:
        tasks = list(self._tasks.values())
        tasks.sort(key=lambda task: (task.sequence_number, task.created_at))
        return tasks

    def _save_locked(self) -> None:
        payload = [task.to_dict() for task in self._sorted_tasks_locked()]
        _write_json_atomic(self._tasks_file, payload)

    def _load_notifications_locked(self) -> None:
        self._notifications = []

        if not self._notifications_file.exists():
            return

        with self._notifications_file.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        if not isinstance(raw, list):
            raise ValueError(
                "Simulation task notifications payload must be a JSON list."
            )

        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(
                    "Each simulation task notification entry must be a JSON object."
                )
            self._notifications.append(TaskNotification.from_dict(item))

    def _save_notifications_locked(self) -> None:
        payload = [notification.to_dict() for notification in self._notifications]
        _write_json_atomic(self._notifications_file, payload)

    def _apply_updates_locked(
        self,
        task: SimulationTask,
        *,
        updated_fields: Optional[dict[str, Any]] = None,
        artifact_refs: Optional[list[TaskArtifactRef]] = None,
        output: Optional[str] = None,
    ) -> None:
        updated_fields = updated_fields or {}
        for field_name, value in updated_fields.items():
            if not hasattr(task, field_name):
                raise ValueError(f"Unknown task field: {field_name}")

            if field_name in {"created_round", "due_round", "round_budget"}:
                value = _coerce_optional_int(value)
            elif field_name in {"origin_metadata", "mention_context"}:
                value = _normalise_metadata_dict(value)
            setattr(task, field_name, value)

        if output is not None:
            task.output = output
        if artifact_refs:
            task.artifact_refs.extend(artifact_refs)

    def create_task(
        self,
        title: str,
        description: str,
        assigned_by: str,
        assigned_to: str,
        parent_goal: Optional[str] = None,
        *,
        status: str = TASK_STATUS_OPEN,
        origin: str = "manual",
        origin_metadata: Optional[dict[str, Any]] = None,
        mention_context: Optional[dict[str, Any]] = None,
        created_round: Optional[int] = None,
        due_round: Optional[int] = None,
        round_budget: Optional[int] = None,
        deadline_at: Optional[str] = None,
        artifact_refs: Optional[list[TaskArtifactRef]] = None,
        actor: Optional[str] = None,
        note: Optional[str] = None,
    ) -> SimulationTask:
        self._ensure_valid_status(status)
        now = _utc_now()
        normalized_artifacts = list(artifact_refs or [])
        with self._locked_state():
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
                status=status,
                created_at=now,
                updated_at=now,
                parent_goal=parent_goal,
                origin=origin or "manual",
                origin_metadata=_normalise_metadata_dict(origin_metadata),
                mention_context=_normalise_metadata_dict(mention_context),
                created_round=created_round,
                due_round=due_round,
                round_budget=round_budget,
                deadline_at=deadline_at,
                artifact_refs=normalized_artifacts,
            )
            task.events.append(
                self._build_created_event(task, actor=actor or assigned_by, note=note)
            )
            self._tasks[task.task_id] = task
            self._save_locked()
            return self._clone_task(task)

    def save_task(self, task: SimulationTask) -> SimulationTask:
        self._ensure_valid_status(task.status)
        if self._extract_sequence_number(task.issue_key) is None:
            raise ValueError(f"Invalid issue_key: {task.issue_key}")

        normalized_task = SimulationTask.from_dict(task.to_dict())
        with self._locked_state():
            existing = self._resolve_task_locked(normalized_task.issue_key)
            if existing is not None and existing.task_id != normalized_task.task_id:
                raise ValueError(
                    f"Duplicate issue_key detected: {normalized_task.issue_key}"
                )
            self._tasks[normalized_task.task_id] = normalized_task
            self._next_sequence_number = max(
                self._next_sequence_number,
                normalized_task.sequence_number + 1,
            )
            self._save_locked()
            return self._clone_task(normalized_task)

    def get_task(self, task_id: str) -> Optional[SimulationTask]:
        with self._locked_state():
            task = self._resolve_task_locked(task_id)
            return None if task is None else self._clone_task(task)

    def get_task_by_issue_key(self, issue_key: str) -> Optional[SimulationTask]:
        return self.get_task(issue_key)

    def list_tasks(
        self,
        assigned_to: Optional[str] = None,
        status: Optional[str] = None,
        completed: Optional[bool] = None,
        issue_key: Optional[str] = None,
        assigned_by: Optional[str] = None,
    ) -> list[SimulationTask]:
        if status is not None:
            self._ensure_valid_status(status)

        with self._locked_state():
            tasks = list(self._tasks.values())

        if assigned_to is not None:
            tasks = [task for task in tasks if task.assigned_to == assigned_to]
        if assigned_by is not None:
            tasks = [task for task in tasks if task.assigned_by == assigned_by]
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        if completed is not None:
            tasks = [
                task for task in tasks if (task.status == TASK_STATUS_DONE) is completed
            ]
        if issue_key is not None:
            tasks = [task for task in tasks if task.issue_key == issue_key]

        tasks.sort(key=lambda task: (task.sequence_number, task.created_at))
        return [self._clone_task(task) for task in tasks]

    def transition_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        actor: Optional[str] = None,
        note: Optional[str] = None,
        output: Optional[str] = None,
        event_type: Optional[str] = None,
        event_details: Optional[dict[str, Any]] = None,
        artifact_refs: Optional[list[TaskArtifactRef]] = None,
        updated_fields: Optional[dict[str, Any]] = None,
        round_index: Optional[int] = None,
    ) -> Optional[SimulationTask]:
        if status is not None:
            self._ensure_valid_status(status)

        normalized_artifact_refs = list(artifact_refs or [])
        with self._locked_state():
            task = self._resolve_task_locked(task_id)
            if task is None:
                return None

            previous_status = task.status
            if status is not None:
                task.status = status

            self._apply_updates_locked(
                task,
                updated_fields=updated_fields,
                artifact_refs=normalized_artifact_refs,
                output=output,
            )
            task.updated_at = _utc_now()

            details = {
                "issue_key": task.issue_key,
                "from_status": previous_status,
                "to_status": task.status,
                "origin": task.origin,
                "origin_metadata": dict(task.origin_metadata),
                "mention_context": dict(task.mention_context),
                "created_round": task.created_round,
                "due_round": task.due_round,
                "round_budget": task.round_budget,
                "deadline_at": task.deadline_at,
                "artifact_count": len(task.artifact_refs),
            }
            if note:
                details["note"] = note
            if output is not None:
                details["output"] = output
            if event_details:
                details.update(event_details)

            task.events.append(
                TaskEvent.create(
                    event_type=event_type or "status_updated",
                    actor=actor or task.assigned_to or task.assigned_by or "system",
                    details=details,
                    artifact_refs=normalized_artifact_refs,
                    round_index=round_index,
                )
            )
            self._save_locked()
            return self._clone_task(task)

    def update_status(
        self,
        task_id: str,
        status: str,
        output: Optional[str] = None,
        actor: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Optional[SimulationTask]:
        event_type = {
            TASK_STATUS_OFFERED: "offered",
            TASK_STATUS_OPEN: "opened",
            TASK_STATUS_IN_PROGRESS: "started",
            TASK_STATUS_BLOCKED: "blocked",
            TASK_STATUS_DONE: "completed",
            TASK_STATUS_DECLINED: "declined",
            TASK_STATUS_EXPIRED: "expired",
        }.get(status, "status_updated")
        return self.transition_task(
            task_id,
            status=status,
            actor=actor,
            note=note,
            output=output,
            event_type=event_type,
        )

    def complete_task(
        self,
        task_id: str,
        output: str,
        actor: Optional[str] = None,
    ) -> Optional[SimulationTask]:
        return self.update_status(
            task_id,
            status=TASK_STATUS_DONE,
            output=output,
            actor=actor,
        )

    def save_artifact(
        self,
        task_ref: str,
        *,
        filename: str,
        content: str | bytes,
        actor: Optional[str] = None,
        media_type: Optional[str] = None,
        kind: str = "deliverable",
        note: Optional[str] = None,
    ) -> Optional[TaskArtifactRef]:
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        normalized_name = _sanitize_artifact_filename(filename)

        with self._locked_state():
            task = self._resolve_task_locked(task_ref)
            if task is None:
                return None

            artifact_dir = self._artifact_dir / task.issue_key
            artifact_path = artifact_dir / normalized_name
            if artifact_path.exists():
                artifact_path = artifact_dir / (
                    f"{artifact_path.stem}-{uuid.uuid4().hex[:8]}{artifact_path.suffix}"
                )

            _write_bytes_atomic(artifact_path, content_bytes)
            relative_path = artifact_path.relative_to(self._simulation_dir).as_posix()
            artifact_ref = TaskArtifactRef(
                artifact_id=uuid.uuid4().hex,
                filename=artifact_path.name,
                relative_path=relative_path,
                media_type=media_type,
                size_bytes=len(content_bytes),
                checksum_sha256=hashlib.sha256(content_bytes).hexdigest(),
                created_by=actor,
                kind=kind,
            )

            task.artifact_refs.append(artifact_ref)
            task.updated_at = _utc_now()
            task.events.append(
                TaskEvent.create(
                    event_type="artifact_saved",
                    actor=actor or task.assigned_to or task.assigned_by or "system",
                    details={
                        "issue_key": task.issue_key,
                        "status": task.status,
                        "relative_path": relative_path,
                        "media_type": media_type,
                        "kind": kind,
                        "note": note,
                        "artifact_count": len(task.artifact_refs),
                    },
                    artifact_refs=[artifact_ref],
                    round_index=task.created_round,
                )
            )
            self._save_locked()
            return TaskArtifactRef.from_dict(asdict(artifact_ref))

    def queue_notification(
        self,
        *,
        recipient: str,
        message: str,
        category: str = "task_update",
        task_ref: Optional[str] = None,
        created_by: Optional[str] = None,
        event_type: Optional[str] = None,
        round_index: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TaskNotification:
        if not recipient.strip():
            raise ValueError("Task notifications require a recipient.")
        if not message.strip():
            raise ValueError("Task notifications require a message.")

        notification = TaskNotification(
            notification_id=uuid.uuid4().hex,
            simulation_id=self._simulation_id,
            recipient=recipient.strip(),
            message=message.strip(),
            created_at=_utc_now(),
            category=(category or "task_update").strip() or "task_update",
            task_ref=task_ref,
            created_by=created_by,
            event_type=event_type,
            round_index=round_index,
            metadata=_normalise_metadata_dict(metadata),
        )

        with self._locked_state():
            self._notifications.append(notification)
            self._save_notifications_locked()
            return TaskNotification.from_dict(notification.to_dict())

    def list_notifications(
        self,
        *,
        recipient: Optional[str] = None,
        delivered: Optional[bool] = None,
        category: Optional[str] = None,
    ) -> list[TaskNotification]:
        with self._locked_state():
            notifications = list(self._notifications)

        if recipient is not None:
            notifications = [
                notification
                for notification in notifications
                if notification.recipient == recipient
            ]
        if delivered is not None:
            notifications = [
                notification
                for notification in notifications
                if (notification.delivered_at is not None) is delivered
            ]
        if category is not None:
            notifications = [
                notification
                for notification in notifications
                if notification.category == category
            ]

        notifications.sort(key=lambda notification: notification.created_at)
        return [TaskNotification.from_dict(item.to_dict()) for item in notifications]

    def consume_notifications(self, recipient: str) -> list[TaskNotification]:
        normalized_recipient = recipient.strip()
        if not normalized_recipient:
            return []

        with self._locked_state():
            pending = [
                notification
                for notification in self._notifications
                if notification.recipient == normalized_recipient
                and notification.delivered_at is None
            ]
            if not pending:
                return []

            delivered_at = _utc_now()
            for notification in pending:
                notification.delivered_at = delivered_at

            self._save_notifications_locked()
            pending.sort(key=lambda notification: notification.created_at)
            return [TaskNotification.from_dict(item.to_dict()) for item in pending]

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
