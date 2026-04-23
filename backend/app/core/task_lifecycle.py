"""Canonical task lifecycle service for simulation tasks."""

from __future__ import annotations

from typing import Any, Optional

from .simulation_task_store import (
    SimulationTask,
    SimulationTaskStore,
    get_simulation_task_store,
)


class TaskLifecycleError(ValueError):
    """Raised when a requested task transition is invalid."""


class TaskAuthorizationError(PermissionError):
    """Raised when an actor attempts to mutate a task they do not own."""


class TaskLifecycleService:
    """Single write-path service for simulation task mutations."""

    def __init__(
        self,
        simulation_id: str,
        store: Optional[SimulationTaskStore] = None,
    ) -> None:
        self.simulation_id = simulation_id
        self.store = store or get_simulation_task_store(simulation_id)

    def get_task(self, task_ref: str) -> Optional[SimulationTask]:
        return self.store.get_task(task_ref)

    def get_task_for_actor(self, task_ref: str, actor: str) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_participant(task, actor)
        return task

    def to_payload(self, task: SimulationTask) -> dict[str, Any]:
        return task.to_dict()

    def create_task(
        self,
        title: str,
        description: str,
        assigned_to: str,
        assigned_by: Optional[str] = None,
        parent_goal: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> SimulationTask:
        normalized_assigner = (actor or assigned_by or "").strip()
        if actor and assigned_by and actor != assigned_by:
            raise TaskAuthorizationError("Assigned-by does not match the acting user.")
        if not normalized_assigner:
            raise TaskLifecycleError("Task creation requires an acting user.")
        if not title.strip():
            raise TaskLifecycleError("Task creation requires a title.")
        if not assigned_to.strip():
            raise TaskLifecycleError("Task creation requires an assignee.")

        return self.store.create_task(
            title=title.strip(),
            description=description.strip(),
            assigned_by=normalized_assigner,
            assigned_to=assigned_to.strip(),
            parent_goal=parent_goal.strip() if parent_goal else None,
        )

    def start_task(
        self,
        task_ref: str,
        actor: str,
        reason: Optional[str] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == "done":
            raise TaskLifecycleError(
                "Completed tasks cannot be moved back to in_progress."
            )
        if task.status == "in_progress":
            raise TaskLifecycleError(f"Task {task.issue_key} is already in progress.")

        updated = self.store.update_status(
            task_id=task_ref,
            status="in_progress",
            actor=actor,
            note=(reason or "").strip() or None,
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        return updated

    def block_task(self, task_ref: str, actor: str, reason: str) -> SimulationTask:
        if not reason.strip():
            raise TaskLifecycleError("Blocked transitions require a reason.")
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == "done":
            raise TaskLifecycleError("Completed tasks cannot be blocked.")
        if task.status == "blocked":
            raise TaskLifecycleError(f"Task {task.issue_key} is already blocked.")

        updated = self.store.update_status(
            task_id=task_ref,
            status="blocked",
            actor=actor,
            note=reason.strip(),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        return updated

    def complete_task(self, task_ref: str, actor: str, output: str) -> SimulationTask:
        if not output.strip():
            raise TaskLifecycleError("Completed transitions require an output summary.")
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == "done":
            raise TaskLifecycleError(f"Task {task.issue_key} is already complete.")

        updated = self.store.complete_task(
            task_id=task_ref, output=output.strip(), actor=actor
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        return updated

    def update_task_status(
        self,
        task_ref: str,
        actor: str,
        status: str,
        reason: Optional[str] = None,
        output: Optional[str] = None,
    ) -> SimulationTask:
        normalized_status = status.strip()
        if normalized_status == "in_progress":
            return self.start_task(task_ref, actor=actor, reason=reason)
        if normalized_status == "blocked":
            return self.block_task(task_ref, actor=actor, reason=reason or "")
        if normalized_status == "done":
            return self.complete_task(task_ref, actor=actor, output=output or "")
        raise TaskLifecycleError(
            f"Unsupported lifecycle status transition: {normalized_status}"
        )

    def _get_required_task(self, task_ref: str) -> SimulationTask:
        task = self.store.get_task(task_ref)
        if task is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        return task

    def _assert_assignee(self, task: SimulationTask, actor: str) -> None:
        if not actor.strip():
            raise TaskAuthorizationError("Task updates require an acting user.")
        if task.assigned_to != actor:
            raise TaskAuthorizationError(
                f"Actor '{actor}' is not allowed to update task {task.issue_key}."
            )

    def _assert_participant(self, task: SimulationTask, actor: str) -> None:
        if not actor.strip():
            raise TaskAuthorizationError("Task reads require an acting user.")
        participants = {task.assigned_to, task.assigned_by}
        if actor not in participants:
            raise TaskAuthorizationError(
                f"Actor '{actor}' is not allowed to view task {task.issue_key}."
            )
