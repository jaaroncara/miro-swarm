"""Round-level enforcement checks for simulation task SLAs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from .simulation_task_store import TERMINAL_TASK_STATUSES
from .task_lifecycle import (
    TaskLifecycleError,
    TaskLifecycleService,
    task_request_requires_rewrite,
)
from .task_observability import log_task_pipeline_metric

_ENFORCEMENT_MODES = {"disabled", "warn", "enforce"}
_ENFORCEMENT_ACTIONS = {"expire", "block"}
_ACTION_GUARD_KEYS: set[tuple[str, int, str, str]] = set()


@dataclass
class RoundEnforcementResult:
    """Summary payload for one enforcement checkpoint."""

    mode: str
    action: str
    grace_rounds: int
    phase: str
    current_round: int | None
    scanned_count: int = 0
    due_count: int = 0
    overdue_count: int = 0
    violation_count: int = 0
    applied_count: int = 0
    idempotent_skip_count: int = 0
    failed_count: int = 0
    max_overdue_rounds: int = 0
    violating_issue_keys: list[str] = field(default_factory=list)
    overdue_by_status: dict[str, int] = field(default_factory=dict)

    def to_metric_fields(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "grace_rounds": self.grace_rounds,
            "phase": self.phase,
            "current_round": self.current_round,
            "scanned_count": self.scanned_count,
            "due_count": self.due_count,
            "overdue_count": self.overdue_count,
            "violation_count": self.violation_count,
            "applied_count": self.applied_count,
            "idempotent_skip_count": self.idempotent_skip_count,
            "failed_count": self.failed_count,
            "max_overdue_rounds": self.max_overdue_rounds,
            "violating_issue_keys": list(self.violating_issue_keys),
            "overdue_by_status": dict(self.overdue_by_status),
        }


def _normalize_mode(mode: str | None) -> str:
    normalized = str(mode or "").strip().lower()
    return normalized if normalized in _ENFORCEMENT_MODES else "disabled"


def _normalize_action(action: str | None) -> str:
    normalized = str(action or "").strip().lower()
    return normalized if normalized in _ENFORCEMENT_ACTIONS else "expire"


def _register_action_guard(
    simulation_id: str,
    current_round: int,
    task_guard_ref: str,
    action: str,
) -> bool:
    key = (simulation_id, current_round, task_guard_ref, action)
    if key in _ACTION_GUARD_KEYS:
        return False
    _ACTION_GUARD_KEYS.add(key)
    return True


def run_round_enforcement(
    *,
    simulation_id: str,
    store: Any,
    phase: str,
    current_round: int | None,
    total_rounds: int | None,
    mode: str | None = None,
    action: str | None = None,
    grace_rounds: int | None = None,
    lifecycle: TaskLifecycleService | None = None,
) -> RoundEnforcementResult:
    """Run one enforcement checkpoint for overdue non-terminal tasks.

    A task is considered violating when:
    - it is not terminal,
    - it has a due_round,
    - current_round has passed due_round,
    - and it is still in an actionable status.
    """
    resolved_mode = _normalize_mode(mode or Config.task_round_enforcement_mode())
    resolved_action = _normalize_action(
        action or Config.task_round_enforcement_action()
    )
    resolved_grace_rounds = (
        Config.task_round_enforcement_grace_rounds()
        if grace_rounds is None
        else max(int(grace_rounds), 0)
    )
    result = RoundEnforcementResult(
        mode=resolved_mode,
        action=resolved_action,
        grace_rounds=resolved_grace_rounds,
        phase=phase,
        current_round=current_round,
    )

    tasks = store.list_tasks()
    result.scanned_count = len(tasks)

    log_task_pipeline_metric(
        "enforcement_scan",
        simulation_id=simulation_id,
        total_rounds=total_rounds,
        **result.to_metric_fields(),
    )

    if resolved_mode == "disabled" or current_round is None:
        log_task_pipeline_metric(
            "enforcement_summary",
            simulation_id=simulation_id,
            total_rounds=total_rounds,
            **result.to_metric_fields(),
        )
        return result

    service = lifecycle or TaskLifecycleService(
        simulation_id=simulation_id, store=store
    )

    for task in tasks:
        if task.status in TERMINAL_TASK_STATUSES:
            continue

        if task_request_requires_rewrite(
            title=task.title,
            description=task.description,
            deliverable_type=getattr(task, "deliverable_type", None),
            acceptance_criteria=getattr(task, "acceptance_criteria", None),
            tool_plan=getattr(task, "tool_plan", None),
        ):
            result.violation_count += 1
            result.violating_issue_keys.append(task.issue_key)

            log_task_pipeline_metric(
                "enforcement_violation",
                simulation_id=simulation_id,
                phase=phase,
                mode=resolved_mode,
                issue_key=task.issue_key,
                status=task.status,
                current_round=current_round,
                due_round=task.due_round,
                grace_rounds=resolved_grace_rounds,
                overdue_rounds=None,
                total_rounds=total_rounds,
                reason="non_executable_meeting_task",
            )

            if resolved_mode == "enforce":
                if not _register_action_guard(
                    simulation_id=simulation_id,
                    current_round=current_round or 0,
                    task_guard_ref=task.task_id,
                    action="expire_non_executable",
                ):
                    result.idempotent_skip_count += 1
                    continue
                try:
                    updated = service.expire_task(
                        task.issue_key,
                        actor="system",
                        reason=(
                            "Automatic expiry by task enforcement: this request is not executable inside the simulation. "
                            "Rewrite meeting-style work into a concrete brief, memo, summary, analysis, comparison, or report section."
                        ),
                        round_index=current_round,
                        event_details={
                            "enforcement": True,
                            "phase": phase,
                            "reason": "non_executable_meeting_task",
                        },
                    )
                    result.applied_count += 1
                    log_task_pipeline_metric(
                        "enforcement_action_applied",
                        simulation_id=simulation_id,
                        phase=phase,
                        mode=resolved_mode,
                        issue_key=updated.issue_key,
                        prior_status=task.status,
                        status=updated.status,
                        action="expire_task",
                        current_round=current_round,
                        due_round=task.due_round,
                        grace_rounds=resolved_grace_rounds,
                        total_rounds=total_rounds,
                        reason="non_executable_meeting_task",
                    )
                except TaskLifecycleError:
                    result.failed_count += 1
            continue

        if task.due_round is None:
            continue
        result.due_count += 1

        overdue_rounds = max(current_round - task.due_round, 0)
        if overdue_rounds > 0:
            result.overdue_count += 1
            result.max_overdue_rounds = max(result.max_overdue_rounds, overdue_rounds)
            result.overdue_by_status[task.status] = (
                result.overdue_by_status.get(task.status, 0) + 1
            )

        if overdue_rounds == 0:
            continue

        violation_threshold = task.due_round + resolved_grace_rounds
        if current_round <= violation_threshold:
            continue

        if task.status not in {"offered", "open", "in_progress", "blocked"}:
            continue

        result.violation_count += 1
        result.violating_issue_keys.append(task.issue_key)

        log_task_pipeline_metric(
            "enforcement_violation",
            simulation_id=simulation_id,
            phase=phase,
            mode=resolved_mode,
            issue_key=task.issue_key,
            status=task.status,
            current_round=current_round,
            due_round=task.due_round,
            grace_rounds=resolved_grace_rounds,
            overdue_rounds=overdue_rounds,
            total_rounds=total_rounds,
        )

        if resolved_mode != "enforce":
            continue

        if not _register_action_guard(
            simulation_id=simulation_id,
            current_round=current_round,
            task_guard_ref=task.task_id,
            action=resolved_action,
        ):
            result.idempotent_skip_count += 1
            log_task_pipeline_metric(
                "enforcement_action_skipped",
                simulation_id=simulation_id,
                phase=phase,
                mode=resolved_mode,
                action=resolved_action,
                issue_key=task.issue_key,
                status=task.status,
                reason="idempotency_guard",
                current_round=current_round,
                due_round=task.due_round,
                total_rounds=total_rounds,
            )
            continue

        try:
            if resolved_action == "block":
                if task.status == "offered":
                    updated = service.expire_task(
                        task.issue_key,
                        actor="system",
                        reason=(
                            "Automatic expiry by round enforcement: "
                            f"task offer exceeded due_round {task.due_round} at round {current_round} before it was accepted."
                        ),
                        round_index=current_round,
                        event_details={"enforcement": True, "phase": phase},
                    )
                    action_name = "expire_task"
                else:
                    if task.status == "blocked":
                        result.idempotent_skip_count += 1
                        log_task_pipeline_metric(
                            "enforcement_action_skipped",
                            simulation_id=simulation_id,
                            phase=phase,
                            mode=resolved_mode,
                            action=resolved_action,
                            issue_key=task.issue_key,
                            status=task.status,
                            reason="already_blocked",
                            current_round=current_round,
                            due_round=task.due_round,
                            total_rounds=total_rounds,
                        )
                        continue

                    updated = service.block_task(
                        task.issue_key,
                        actor=task.assigned_to,
                        reason=(
                            "Automatic block by round enforcement: "
                            f"task exceeded due_round {task.due_round} at round {current_round}."
                        ),
                        round_index=current_round,
                        event_details={"enforcement": True, "phase": phase},
                    )
                    action_name = "block_task"
            else:
                updated = service.expire_task(
                    task.issue_key,
                    actor="system",
                    reason=(
                        "Automatic expiry by round enforcement: "
                        f"task exceeded due_round {task.due_round} at round {current_round}."
                    ),
                    round_index=current_round,
                    event_details={"enforcement": True, "phase": phase},
                )
                action_name = "expire_task"

            result.applied_count += 1
            log_task_pipeline_metric(
                "enforcement_action_applied",
                simulation_id=simulation_id,
                phase=phase,
                mode=resolved_mode,
                issue_key=updated.issue_key,
                prior_status=task.status,
                status=updated.status,
                action=action_name,
                grace_rounds=resolved_grace_rounds,
                current_round=current_round,
                due_round=task.due_round,
                total_rounds=total_rounds,
            )
        except TaskLifecycleError as exc:
            result.failed_count += 1
            log_task_pipeline_metric(
                "enforcement_action_failed",
                level="warning",
                simulation_id=simulation_id,
                phase=phase,
                mode=resolved_mode,
                issue_key=task.issue_key,
                status=task.status,
                action=resolved_action,
                error=str(exc),
                grace_rounds=resolved_grace_rounds,
                current_round=current_round,
                due_round=task.due_round,
                total_rounds=total_rounds,
            )

    log_task_pipeline_metric(
        "enforcement_overdue_snapshot",
        simulation_id=simulation_id,
        mode=resolved_mode,
        action=resolved_action,
        grace_rounds=resolved_grace_rounds,
        phase=phase,
        current_round=current_round,
        total_rounds=total_rounds,
        overdue_count=result.overdue_count,
        overdue_by_status=result.overdue_by_status,
        max_overdue_rounds=result.max_overdue_rounds,
    )

    log_task_pipeline_metric(
        "enforcement_summary",
        simulation_id=simulation_id,
        total_rounds=total_rounds,
        **result.to_metric_fields(),
    )

    return result
