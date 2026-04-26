"""Canonical task lifecycle service for simulation tasks."""

from __future__ import annotations

import re
from typing import Any, Optional

from ..config import Config
from .simulation_task_store import (
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DECLINED,
    TASK_STATUS_DONE,
    TASK_STATUS_EXPIRED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OFFERED,
    TASK_STATUS_OPEN,
    TERMINAL_TASK_STATUSES,
    SimulationTask,
    SimulationTaskStore,
    TaskArtifactRef,
    get_simulation_task_store,
)
from .task_observability import log_task_pipeline_metric


class TaskLifecycleError(ValueError):
    """Raised when a requested task transition is invalid."""


class TaskAuthorizationError(PermissionError):
    """Raised when an actor attempts to mutate a task they do not own."""


_MEETING_ONLY_PATTERNS = (
    re.compile(
        r"\b(?:set\s*up|schedule|arrange|book|organize|coordinate)\s+(?:a\s+)?(?:meeting|sync|call|discussion|touch\s*base|1:1|one[- ]on[- ]one)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bmeet\s+with\b", re.IGNORECASE),
    re.compile(r"\b(?:talk|speak)\s+to\b", re.IGNORECASE),
)
_DELIVERABLE_TYPE_PATTERNS = (
    ("research_brief", ("research", "scan", "evidence", "brief", "briefing")),
    (
        "analytics_summary",
        ("analysis", "analytics", "kpi", "metric", "dashboard", "trend", "summary"),
    ),
    ("competitor_comparison", ("competitor", "comparison", "compare", "benchmark")),
    ("risk_memo", ("risk", "assessment", "mitigation")),
    ("report_section", ("report", "section", "draft", "narrative")),
    ("review_notes", ("review", "feedback", "notes", "annotate")),
)
_DATA_TOOL_KEYWORDS = {
    "kpi",
    "metric",
    "metrics",
    "data",
    "analytics",
    "analysis",
    "trend",
    "summary",
}
_NEWS_TOOL_KEYWORDS = {
    "market",
    "competitor",
    "competitors",
    "industry",
    "launch",
    "news",
    "research",
}
_WEB_TOOL_KEYWORDS = {
    "web",
    "website",
    "benchmark",
    "scan",
    "compare",
    "comparison",
    "evidence",
}


def _normalize_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _split_list_text(value: Any, *, split_commas: bool = False) -> list[str]:
    if value in (None, ""):
        return []

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        separators = r"(?:\r?\n|;)"
        if split_commas:
            separators = r"(?:\r?\n|;|,)"
        parts = re.split(separators, stripped)
        normalized: list[str] = []
        seen: set[str] = set()
        for part in parts:
            cleaned = part.strip().lstrip("-*• ").strip()
            if not cleaned or cleaned in seen:
                continue
            normalized.append(cleaned)
            seen.add(cleaned)
        return normalized

    if isinstance(value, (list, tuple, set)):
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = _normalize_text(item)
            if not cleaned or cleaned in seen:
                continue
            normalized.append(cleaned)
            seen.add(cleaned)
        return normalized

    cleaned = _normalize_text(value)
    return [cleaned] if cleaned else []


def _infer_deliverable_type(title: str, description: str) -> str:
    haystack = f"{title} {description}".lower()
    for deliverable_type, keywords in _DELIVERABLE_TYPE_PATTERNS:
        if any(keyword in haystack for keyword in keywords):
            return deliverable_type
    return "written_update"


def _has_deliverable_hint(text: str) -> bool:
    lowered = (text or "").lower()
    for _, keywords in _DELIVERABLE_TYPE_PATTERNS:
        if any(keyword in lowered for keyword in keywords):
            return True
    return False


def _looks_like_meeting_only_request(
    title: str, description: str, deliverable_text: str
) -> bool:
    haystack = f"{title} {description}".strip()
    if not haystack:
        return False
    if any(pattern.search(haystack) for pattern in _MEETING_ONLY_PATTERNS):
        return not (deliverable_text.strip() or _has_deliverable_hint(haystack))
    return False


def task_request_requires_rewrite(
    *,
    title: str,
    description: str,
    deliverable_type: Optional[str] = None,
    acceptance_criteria: Any = None,
    tool_plan: Optional[str] = None,
) -> bool:
    deliverable_hints = " ".join(
        item
        for item in [
            _normalize_text(deliverable_type),
            _normalize_text(tool_plan),
            " ".join(_split_list_text(acceptance_criteria)),
        ]
        if item
    )
    return _looks_like_meeting_only_request(
        _normalize_text(title) or "",
        _normalize_text(description) or "",
        deliverable_hints,
    )


def _infer_acceptance_criteria(deliverable_type: str) -> list[str]:
    criteria = [
        "Produce a concrete deliverable using the current simulation context and available MCP tools.",
        "Do not rely on off-screen meetings or private conversations to finish the work.",
    ]
    if deliverable_type in {
        "research_brief",
        "analytics_summary",
        "competitor_comparison",
        "risk_memo",
        "report_section",
        "review_notes",
        "written_update",
    }:
        criteria.append(
            "If the output is file-like, save it with save_task_artifact before completing the task."
        )
    return criteria


def _infer_suggested_tools(title: str, description: str) -> list[str]:
    haystack = f"{title} {description}".lower()
    suggested_tools = ["update_task_status", "save_task_artifact", "complete_task"]
    if any(keyword in haystack for keyword in _DATA_TOOL_KEYWORDS):
        suggested_tools.insert(0, "lookup_business_data")
    if any(keyword in haystack for keyword in _NEWS_TOOL_KEYWORDS):
        suggested_tools.append("basic_news_search")
    if any(keyword in haystack for keyword in _WEB_TOOL_KEYWORDS):
        suggested_tools.append("basic_web_search")

    deduped: list[str] = []
    seen: set[str] = set()
    for tool_name in suggested_tools:
        if tool_name in seen:
            continue
        deduped.append(tool_name)
        seen.add(tool_name)
    return deduped


def prepare_task_request_metadata(
    *,
    title: str,
    description: str,
    deliverable_type: Optional[str] = None,
    acceptance_criteria: Any = None,
    suggested_tools: Any = None,
    tool_plan: Optional[str] = None,
) -> dict[str, Any]:
    normalized_title = _normalize_text(title) or ""
    normalized_description = _normalize_text(description) or ""
    normalized_deliverable_type = _normalize_text(deliverable_type)
    normalized_tool_plan = _normalize_text(tool_plan)
    normalized_acceptance_criteria = _split_list_text(acceptance_criteria)
    normalized_suggested_tools = _split_list_text(suggested_tools, split_commas=True)

    deliverable_hints = " ".join(
        item
        for item in [
            normalized_deliverable_type,
            normalized_tool_plan,
            " ".join(normalized_acceptance_criteria),
        ]
        if item
    )

    if _looks_like_meeting_only_request(
        normalized_title,
        normalized_description,
        deliverable_hints,
    ):
        raise TaskLifecycleError(
            "Meeting-style tasks are not executable inside the simulation. Rewrite the request as a concrete deliverable such as a brief, memo, analysis, summary, or report section."
        )

    resolved_deliverable_type = normalized_deliverable_type or _infer_deliverable_type(
        normalized_title,
        normalized_description,
    )
    if not normalized_acceptance_criteria:
        normalized_acceptance_criteria = _infer_acceptance_criteria(
            resolved_deliverable_type
        )
    if not normalized_suggested_tools:
        normalized_suggested_tools = _infer_suggested_tools(
            normalized_title,
            normalized_description,
        )

    return {
        "deliverable_type": resolved_deliverable_type,
        "acceptance_criteria": normalized_acceptance_criteria,
        "suggested_tools": normalized_suggested_tools,
        "tool_plan": normalized_tool_plan,
    }


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
        *,
        origin: str = "manual",
        origin_metadata: Optional[dict[str, Any]] = None,
        mention_context: Optional[dict[str, Any]] = None,
        created_round: Optional[int] = None,
        due_round: Optional[int] = None,
        round_budget: Optional[int] = None,
        deadline_at: Optional[str] = None,
        deliverable_type: Optional[str] = None,
        acceptance_criteria: Any = None,
        suggested_tools: Any = None,
        tool_plan: Optional[str] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        return self._create_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            assigned_by=assigned_by,
            parent_goal=parent_goal,
            actor=actor,
            initial_status=TASK_STATUS_OPEN,
            origin=origin,
            origin_metadata=origin_metadata,
            mention_context=mention_context,
            created_round=created_round,
            due_round=due_round,
            round_budget=round_budget,
            deadline_at=deadline_at,
            deliverable_type=deliverable_type,
            acceptance_criteria=acceptance_criteria,
            suggested_tools=suggested_tools,
            tool_plan=tool_plan,
            chat_refs=chat_refs,
        )

    def offer_task(
        self,
        title: str,
        description: str,
        assigned_to: str,
        assigned_by: Optional[str] = None,
        parent_goal: Optional[str] = None,
        actor: Optional[str] = None,
        *,
        origin: str = "offer",
        origin_metadata: Optional[dict[str, Any]] = None,
        mention_context: Optional[dict[str, Any]] = None,
        created_round: Optional[int] = None,
        due_round: Optional[int] = None,
        round_budget: Optional[int] = None,
        deadline_at: Optional[str] = None,
        deliverable_type: Optional[str] = None,
        acceptance_criteria: Any = None,
        suggested_tools: Any = None,
        tool_plan: Optional[str] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._create_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            assigned_by=assigned_by,
            parent_goal=parent_goal,
            actor=actor,
            initial_status=TASK_STATUS_OFFERED,
            origin=origin,
            origin_metadata=origin_metadata,
            mention_context=mention_context,
            created_round=created_round,
            due_round=due_round,
            round_budget=round_budget,
            deadline_at=deadline_at,
            deliverable_type=deliverable_type,
            acceptance_criteria=acceptance_criteria,
            suggested_tools=suggested_tools,
            tool_plan=tool_plan,
            chat_refs=chat_refs,
        )
        self._queue_offer_notification(task)
        return task

    def accept_task(
        self,
        task_ref: str,
        actor: str,
        reason: Optional[str] = None,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status != TASK_STATUS_OFFERED:
            raise TaskLifecycleError(
                f"Task {task.issue_key} is not awaiting acceptance."
            )

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_OPEN,
            actor=actor,
            note=(reason or "").strip() or None,
            event_type="accepted",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._queue_assigner_notification(updated, actor=actor, event_type="accepted")
        self._log_task_transition(
            updated,
            actor=actor,
            event_type="accepted",
            reason=reason,
        )
        return updated

    def decline_task(
        self,
        task_ref: str,
        actor: str,
        reason: Optional[str] = None,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status != TASK_STATUS_OFFERED:
            raise TaskLifecycleError(
                f"Task {task.issue_key} is not awaiting acceptance."
            )

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_DECLINED,
            actor=actor,
            note=(reason or "").strip() or None,
            event_type="declined",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._queue_assigner_notification(updated, actor=actor, event_type="declined")
        self._log_task_transition(
            updated,
            actor=actor,
            event_type="declined",
            reason=reason,
        )
        return updated

    def reopen_task(
        self,
        task_ref: str,
        actor: str,
        reason: Optional[str] = None,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == TASK_STATUS_OFFERED:
            raise TaskLifecycleError(
                f"Task {task.issue_key} must be accepted before it can be reopened."
            )
        if task.status in TERMINAL_TASK_STATUSES:
            raise TaskLifecycleError(
                f"Task {task.issue_key} cannot be reopened from status {task.status}."
            )
        if task.status == TASK_STATUS_OPEN:
            raise TaskLifecycleError(f"Task {task.issue_key} is already open.")

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_OPEN,
            actor=actor,
            note=(reason or "").strip() or None,
            event_type="reopened",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._log_task_transition(
            updated,
            actor=actor,
            event_type="reopened",
            reason=reason,
        )
        return updated

    def start_task(
        self,
        task_ref: str,
        actor: str,
        reason: Optional[str] = None,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == TASK_STATUS_OFFERED:
            raise TaskLifecycleError(
                f"Task {task.issue_key} must be accepted before it can start."
            )
        if task.status in TERMINAL_TASK_STATUSES:
            raise TaskLifecycleError(
                f"Task {task.issue_key} cannot move to in_progress from {task.status}."
            )
        if task.status == TASK_STATUS_IN_PROGRESS:
            raise TaskLifecycleError(f"Task {task.issue_key} is already in progress.")

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_IN_PROGRESS,
            actor=actor,
            note=(reason or "").strip() or None,
            event_type="started",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._log_task_transition(
            updated,
            actor=actor,
            event_type="started",
            reason=reason,
        )
        return updated

    def block_task(
        self,
        task_ref: str,
        actor: str,
        reason: str,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        if not reason.strip():
            raise TaskLifecycleError("Blocked transitions require a reason.")
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == TASK_STATUS_OFFERED:
            raise TaskLifecycleError(
                f"Task {task.issue_key} must be accepted before it can be blocked."
            )
        if task.status in TERMINAL_TASK_STATUSES:
            raise TaskLifecycleError(
                f"Task {task.issue_key} cannot be blocked from status {task.status}."
            )
        if task.status == TASK_STATUS_BLOCKED:
            raise TaskLifecycleError(f"Task {task.issue_key} is already blocked.")

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_BLOCKED,
            actor=actor,
            note=reason.strip(),
            event_type="blocked",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._queue_assigner_notification(updated, actor=actor, event_type="blocked")
        self._log_task_transition(
            updated,
            actor=actor,
            event_type="blocked",
            reason=reason,
        )
        return updated

    def complete_task(
        self,
        task_ref: str,
        actor: str,
        output: str,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        self._assert_assignee(task, actor)
        if task.status == TASK_STATUS_OFFERED:
            raise TaskLifecycleError(
                f"Task {task.issue_key} must be accepted before it can be completed."
            )
        if task.status in TERMINAL_TASK_STATUSES:
            raise TaskLifecycleError(f"Task {task.issue_key} is already terminal.")

        normalized_output = output.strip()
        if not normalized_output and not task.artifact_refs:
            raise TaskLifecycleError(
                "Completed transitions require an output summary or at least one saved artifact."
            )

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_DONE,
            actor=actor,
            output=normalized_output or None,
            event_type="completed",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._queue_assigner_notification(updated, actor=actor, event_type="completed")
        self._log_task_transition(
            updated,
            actor=actor,
            event_type="completed",
            output=normalized_output,
        )
        return updated

    def expire_task(
        self,
        task_ref: str,
        actor: str,
        reason: Optional[str] = None,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        task = self._get_required_task(task_ref)
        normalized_actor = actor.strip()
        if not normalized_actor:
            raise TaskAuthorizationError("Task expiry requires an acting user.")
        if normalized_actor.lower() != "system":
            self._assert_participant(task, normalized_actor)
        if task.status in TERMINAL_TASK_STATUSES:
            raise TaskLifecycleError(f"Task {task.issue_key} is already terminal.")

        updated = self.store.transition_task(
            task_ref,
            status=TASK_STATUS_EXPIRED,
            actor=normalized_actor,
            note=(reason or "").strip() or None,
            event_type="expired",
            event_details=event_details,
            chat_refs=chat_refs,
            round_index=self._resolve_transition_round_index(round_index),
        )
        if updated is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        self._log_task_transition(
            updated,
            actor=normalized_actor,
            event_type="expired",
            reason=reason,
        )
        return updated

    def save_artifact(
        self,
        task_ref: str,
        *,
        actor: str,
        filename: str,
        content: str | bytes,
        media_type: Optional[str] = None,
        kind: str = "deliverable",
        note: Optional[str] = None,
    ) -> TaskArtifactRef:
        task = self._get_required_task(task_ref)
        normalized_actor = actor.strip()
        if not normalized_actor:
            raise TaskAuthorizationError("Task artifacts require an acting user.")
        if normalized_actor.lower() != "system":
            self._assert_participant(task, normalized_actor)

        artifact = self.store.save_artifact(
            task_ref,
            filename=filename,
            content=content,
            actor=normalized_actor,
            media_type=media_type,
            kind=kind,
            note=note,
        )
        if artifact is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        updated_task = self._get_required_task(task_ref)
        self._log_task_transition(
            updated_task,
            actor=normalized_actor,
            event_type="artifact_saved",
            reason=note,
            artifact=artifact,
        )
        return artifact

    def update_task_status(
        self,
        task_ref: str,
        actor: str,
        status: str,
        reason: Optional[str] = None,
        output: Optional[str] = None,
        round_index: Optional[int] = None,
        event_details: Optional[dict[str, Any]] = None,
        chat_refs: Optional[list[dict[str, Any]]] = None,
    ) -> SimulationTask:
        normalized_status = status.strip().lower()
        task = self._get_required_task(task_ref)
        if normalized_status == task.status:
            self._assert_assignee(task, actor)
            if task.status == TASK_STATUS_OFFERED:
                raise TaskLifecycleError(
                    "Pending offers must be accepted or declined; they cannot be updated in place."
                )
            if task.status in TERMINAL_TASK_STATUSES:
                raise TaskLifecycleError(
                    f"Task {task.issue_key} is already terminal and cannot be updated."
                )

            normalized_reason = (reason or "").strip() or None
            normalized_output = (output or "").strip() or None
            if not any(
                [normalized_reason, normalized_output, event_details, chat_refs]
            ):
                raise TaskLifecycleError(
                    "Status updates without a state change require a note, output, or linked chat context."
                )

            event_type = (
                "progress_updated"
                if task.status in {TASK_STATUS_OPEN, TASK_STATUS_IN_PROGRESS}
                else "status_updated"
            )
            updated = self.store.transition_task(
                task_ref,
                status=task.status,
                actor=actor,
                note=normalized_reason,
                output=normalized_output,
                event_type=event_type,
                event_details=event_details,
                chat_refs=chat_refs,
                round_index=self._resolve_transition_round_index(round_index),
            )
            if updated is None:
                raise TaskLifecycleError(f"Task not found: {task_ref}")
            self._log_task_transition(
                updated,
                actor=actor,
                event_type=event_type,
                reason=normalized_reason,
                output=normalized_output,
            )
            return updated

        if normalized_status == TASK_STATUS_OPEN:
            if task.status == TASK_STATUS_OFFERED:
                return self.accept_task(
                    task_ref,
                    actor=actor,
                    reason=reason,
                    round_index=round_index,
                    event_details=event_details,
                    chat_refs=chat_refs,
                )
            return self.reopen_task(
                task_ref,
                actor=actor,
                reason=reason,
                round_index=round_index,
                event_details=event_details,
                chat_refs=chat_refs,
            )
        if normalized_status == TASK_STATUS_IN_PROGRESS:
            return self.start_task(
                task_ref,
                actor=actor,
                reason=reason,
                round_index=round_index,
                event_details=event_details,
                chat_refs=chat_refs,
            )
        if normalized_status == TASK_STATUS_BLOCKED:
            return self.block_task(
                task_ref,
                actor=actor,
                reason=reason or "",
                round_index=round_index,
                event_details=event_details,
                chat_refs=chat_refs,
            )
        if normalized_status == TASK_STATUS_DONE:
            return self.complete_task(
                task_ref,
                actor=actor,
                output=output or "",
                round_index=round_index,
                event_details=event_details,
                chat_refs=chat_refs,
            )
        if normalized_status == TASK_STATUS_DECLINED:
            return self.decline_task(
                task_ref,
                actor=actor,
                reason=reason,
                round_index=round_index,
                event_details=event_details,
                chat_refs=chat_refs,
            )
        if normalized_status == TASK_STATUS_EXPIRED:
            return self.expire_task(
                task_ref,
                actor=actor,
                reason=reason,
                round_index=round_index,
                event_details=event_details,
                chat_refs=chat_refs,
            )
        raise TaskLifecycleError(
            f"Unsupported lifecycle status transition: {normalized_status}"
        )

    def _create_task(
        self,
        *,
        title: str,
        description: str,
        assigned_to: str,
        assigned_by: Optional[str],
        parent_goal: Optional[str],
        actor: Optional[str],
        initial_status: str,
        origin: str,
        origin_metadata: Optional[dict[str, Any]],
        mention_context: Optional[dict[str, Any]],
        created_round: Optional[int],
        due_round: Optional[int],
        round_budget: Optional[int],
        deadline_at: Optional[str],
        deliverable_type: Optional[str],
        acceptance_criteria: Any,
        suggested_tools: Any,
        tool_plan: Optional[str],
        chat_refs: Optional[list[dict[str, Any]]],
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

        task_request_metadata = prepare_task_request_metadata(
            title=title.strip(),
            description=description.strip(),
            deliverable_type=deliverable_type,
            acceptance_criteria=acceptance_criteria,
            suggested_tools=suggested_tools,
            tool_plan=tool_plan,
        )

        (
            resolved_created_round,
            resolved_due_round,
            resolved_round_budget,
        ) = self._resolve_round_metadata(
            created_round=created_round,
            due_round=due_round,
            round_budget=round_budget,
        )

        task = self.store.create_task(
            title=title.strip(),
            description=description.strip(),
            assigned_by=normalized_assigner,
            assigned_to=assigned_to.strip(),
            parent_goal=parent_goal.strip() if parent_goal else None,
            status=initial_status,
            origin=(origin or "manual").strip() or "manual",
            origin_metadata=origin_metadata,
            mention_context=mention_context,
            created_round=resolved_created_round,
            due_round=resolved_due_round,
            round_budget=resolved_round_budget,
            deadline_at=deadline_at,
            deliverable_type=task_request_metadata["deliverable_type"],
            acceptance_criteria=task_request_metadata["acceptance_criteria"],
            suggested_tools=task_request_metadata["suggested_tools"],
            tool_plan=task_request_metadata["tool_plan"],
            chat_refs=chat_refs,
            actor=normalized_assigner,
        )
        if task.origin.endswith("_compat"):
            log_task_pipeline_metric(
                "compat_path_used",
                simulation_id=self.simulation_id,
                source=task.origin,
                issue_key=task.issue_key,
                assigned_by=task.assigned_by,
                assigned_to=task.assigned_to,
                status=task.status,
            )
        return task

    def _resolve_round_metadata(
        self,
        *,
        created_round: Optional[int],
        due_round: Optional[int],
        round_budget: Optional[int],
    ) -> tuple[Optional[int], Optional[int], Optional[int]]:
        normalized_created_round = self._coerce_round_value(
            created_round,
            field_name="created_round",
        )
        normalized_due_round = self._coerce_round_value(
            due_round,
            field_name="due_round",
        )
        normalized_round_budget = self._coerce_round_value(
            round_budget,
            field_name="round_budget",
            minimum=0,
        )

        state_current_round, state_total_rounds = self._load_run_state_rounds()

        if normalized_created_round is None:
            normalized_created_round = state_current_round

        if normalized_due_round is None:
            if (
                normalized_created_round is not None
                and normalized_round_budget is not None
            ):
                normalized_due_round = (
                    normalized_created_round + normalized_round_budget
                )
            else:
                default_round_budget = Config.task_default_round_budget()
                if normalized_created_round is not None:
                    normalized_round_budget = default_round_budget
                    normalized_due_round = (
                        normalized_created_round + default_round_budget
                    )
                    if state_total_rounds is not None:
                        normalized_due_round = min(
                            normalized_due_round,
                            state_total_rounds,
                        )
                else:
                    normalized_due_round = state_total_rounds

        if (
            normalized_created_round is None
            and normalized_due_round is not None
            and normalized_round_budget is not None
        ):
            normalized_created_round = max(
                normalized_due_round - normalized_round_budget,
                1,
            )

        if (
            normalized_created_round is not None
            and normalized_due_round is not None
            and normalized_due_round < normalized_created_round
        ):
            raise TaskLifecycleError("due_round cannot be earlier than created_round.")

        inferred_round_budget: Optional[int] = None
        if normalized_created_round is not None and normalized_due_round is not None:
            inferred_round_budget = max(
                normalized_due_round - normalized_created_round,
                0,
            )

        if normalized_round_budget is None:
            normalized_round_budget = inferred_round_budget
        elif (
            inferred_round_budget is not None
            and normalized_round_budget != inferred_round_budget
        ):
            raise TaskLifecycleError(
                "round_budget must match due_round - created_round when all three values are supplied."
            )

        return (
            normalized_created_round,
            normalized_due_round,
            normalized_round_budget,
        )

    def _resolve_transition_round_index(
        self,
        round_index: Optional[int],
    ) -> Optional[int]:
        normalized_round_index = self._coerce_round_value(
            round_index,
            field_name="round_index",
        )
        if normalized_round_index is not None:
            return normalized_round_index

        state_current_round, _ = self._load_run_state_rounds()
        return state_current_round

    def _load_run_state_rounds(self) -> tuple[Optional[int], Optional[int]]:
        try:
            from ..services.simulation_runner import SimulationRunner
        except Exception:
            return None, None

        state = SimulationRunner.get_run_state(self.simulation_id)
        if state is None:
            return None, None

        current_round = int(getattr(state, "current_round", 0) or 0)
        total_rounds = int(getattr(state, "total_rounds", 0) or 0)

        if current_round <= 0 and total_rounds > 0:
            current_round = 1

        return (
            current_round or None,
            total_rounds or None,
        )

    def _infer_remaining_rounds(self, task: SimulationTask) -> Optional[int]:
        if task.due_round is None:
            return None

        current_round, _ = self._load_run_state_rounds()
        if current_round is None:
            return None

        return max(task.due_round - current_round, 0)

    def _infer_completion_timestamp(self, task: SimulationTask) -> Optional[str]:
        for event in reversed(task.events):
            if event.event_type == "completed":
                return event.created_at
        return None

    def _build_metric_fields(
        self,
        task: SimulationTask,
        *,
        actor: str,
        event_type: str,
        reason: Optional[str] = None,
        output: Optional[str] = None,
        artifact: Optional[TaskArtifactRef] = None,
    ) -> dict[str, Any]:
        latest_event = task.events[-1] if task.events else None

        return {
            "simulation_id": self.simulation_id,
            "issue_key": task.issue_key,
            "task_id": task.task_id,
            "event_type": event_type,
            "status": task.status,
            "actor": actor,
            "assigned_by": task.assigned_by,
            "assigned_to": task.assigned_to,
            "origin": task.origin,
            "round_index": latest_event.round_index if latest_event else None,
            "created_round": task.created_round,
            "due_round": task.due_round,
            "remaining_rounds": self._infer_remaining_rounds(task),
            "deliverable_type": task.deliverable_type,
            "artifact_count": len(task.artifact_refs or []),
            "chat_ref_count": len(task.chat_refs or []),
            "completed_at": self._infer_completion_timestamp(task),
            "reason": reason or None,
            "output_present": bool(output or task.output),
            "artifact_filename": artifact.filename if artifact is not None else None,
            "artifact_kind": artifact.kind if artifact is not None else None,
        }

    def _log_task_transition(
        self,
        task: SimulationTask,
        *,
        actor: str,
        event_type: str,
        reason: Optional[str] = None,
        output: Optional[str] = None,
        artifact: Optional[TaskArtifactRef] = None,
    ) -> None:
        log_task_pipeline_metric(
            "task_transition",
            **self._build_metric_fields(
                task,
                actor=actor,
                event_type=event_type,
                reason=reason,
                output=output,
                artifact=artifact,
            ),
        )

    def _coerce_round_value(
        self,
        value: Optional[int],
        *,
        field_name: str,
        minimum: int = 1,
    ) -> Optional[int]:
        if value in (None, ""):
            return None

        normalized_value = int(value)
        if normalized_value < minimum:
            comparator = "at least 0" if minimum == 0 else "at least 1"
            raise TaskLifecycleError(f"{field_name} must be {comparator}.")

        return normalized_value

    def _get_required_task(self, task_ref: str) -> SimulationTask:
        task = self.store.get_task(task_ref)
        if task is None:
            raise TaskLifecycleError(f"Task not found: {task_ref}")
        return task

    def _queue_offer_notification(self, task: SimulationTask) -> None:
        queue_notification = getattr(self.store, "queue_notification", None)
        if not callable(queue_notification):
            return
        if not task.assigned_to or task.assigned_to == task.assigned_by:
            return

        lines = [
            f'[Task Offer] {task.assigned_by} offered you "{task.title}" [{task.issue_key}].',
        ]
        if task.deliverable_type:
            lines.append(f"Deliverable: {task.deliverable_type}.")
        if task.acceptance_criteria:
            lines.append(f"Acceptance criteria: {task.acceptance_criteria[0]}")
        snippet = (task.mention_context or {}).get("snippet")
        if snippet:
            lines.append(f"Public context: {snippet}")
        lines.append(
            "Accept or decline this offer before moving on to other work. Prefer MCP `accept_task` or `decline_task` when available, and respond in public chat once you decide."
        )

        queue_notification(
            recipient=task.assigned_to,
            message="\n".join(lines),
            category="task_offer",
            task_ref=task.issue_key,
            created_by=task.assigned_by,
            event_type="offered",
            round_index=task.created_round,
            metadata={
                "origin": task.origin,
                "status": task.status,
                "mention_context": dict(task.mention_context),
            },
        )

    def _queue_assigner_notification(
        self,
        task: SimulationTask,
        *,
        actor: str,
        event_type: str,
    ) -> None:
        queue_notification = getattr(self.store, "queue_notification", None)
        if not callable(queue_notification):
            return
        if not task.assigned_by or task.assigned_by == actor:
            return

        latest_event = task.events[-1] if task.events else None
        details = latest_event.details if latest_event is not None else {}
        lines: list[str]

        if event_type == "accepted":
            lines = [
                f'[Task Accepted] {actor} accepted your task "{task.title}" [{task.issue_key}].',
            ]
            if details.get("note"):
                lines.append(f"Plan: {details['note']}")
        elif event_type == "declined":
            lines = [
                f'[Task Declined] {actor} declined your task "{task.title}" [{task.issue_key}].',
            ]
            if details.get("note"):
                lines.append(f"Reason: {details['note']}")
        elif event_type == "blocked":
            lines = [
                f'[Task Blocked] {actor} is blocked on your task "{task.title}" [{task.issue_key}].',
            ]
            if details.get("note"):
                lines.append(f"Reason: {details['note']}")
            lines.append(
                f"Reply to {actor} to help unblock this work or revise the task."
            )
        elif event_type == "completed":
            lines = [
                f'[Task Completed] {actor} completed your task "{task.title}" [{task.issue_key}].',
            ]
            if details.get("output"):
                lines.append(f"Result: {details['output']}")
            lines.append(
                f"Reply to {actor} to acknowledge the result or assign follow-up work if needed."
            )
        else:
            return

        queue_notification(
            recipient=task.assigned_by,
            message="\n".join(lines),
            category="task_update",
            task_ref=task.issue_key,
            created_by=actor,
            event_type=event_type,
            round_index=(
                latest_event.round_index if latest_event is not None else None
            ),
            metadata={
                "status": task.status,
                "origin": task.origin,
                "mention_context": dict(task.mention_context),
            },
        )

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
