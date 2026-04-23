"""Task MCP server backed by the canonical lifecycle service."""

import base64
import binascii
import json
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from mcp.server.fastmcp import FastMCP

from app.core.simulation_task_store import TASK_STATUS_ORDER
from app.core.task_lifecycle import (
    TaskAuthorizationError,
    TaskLifecycleError,
    TaskLifecycleService,
)

mcp = FastMCP("task-tools")

_STATUS_ORDER = list(TASK_STATUS_ORDER)


def _format_task_summary(task) -> str:
    goal_label = f" | Goal: {task.parent_goal}" if task.parent_goal else ""
    deadline_parts = []
    if getattr(task, "due_round", None) is not None:
        deadline_parts.append(f"due_round={task.due_round}")
    if getattr(task, "deadline_at", None):
        deadline_parts.append(f"deadline_at={task.deadline_at}")
    deadline_label = (
        f" | Deadline: {', '.join(deadline_parts)}" if deadline_parts else ""
    )
    artifact_count = len(getattr(task, "artifact_refs", []) or [])
    artifact_label = f" | Artifacts: {artifact_count}" if artifact_count else ""
    return (
        f'{task.issue_key} [{task.status}] "{task.title}" '
        f"({task.assigned_by} -> {task.assigned_to}{goal_label})"
        f"{deadline_label}{artifact_label}"
    )


def _format_task_detail(task) -> str:
    return json.dumps(task.to_dict(), ensure_ascii=False, indent=2)


def _get_lifecycle(simulation_id: str) -> TaskLifecycleService:
    return TaskLifecycleService(simulation_id=simulation_id)


@mcp.tool()
async def offer_task(
    simulation_id: str,
    title: str,
    description: str,
    assigned_to: str,
    actor: str,
    parent_goal: str = "",
    due_round: int | None = None,
    round_budget: int | None = None,
    deadline_at: str = "",
) -> str:
    """Offer a new task to a colleague so they can accept or decline it."""
    try:
        task = _get_lifecycle(simulation_id).offer_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            parent_goal=parent_goal or None,
            actor=actor,
            due_round=due_round,
            round_budget=round_budget,
            deadline_at=deadline_at or None,
            origin="mcp_offer",
            origin_metadata={"source": "mcp", "tool": "offer_task"},
        )
        return f"Task offered: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task offer rejected: {exc}"


@mcp.tool()
async def accept_task(
    simulation_id: str,
    issue_key: str,
    actor: str,
    reason: str = "",
) -> str:
    """Accept a pending task offer assigned to you."""
    try:
        task = _get_lifecycle(simulation_id).accept_task(
            task_ref=issue_key,
            actor=actor,
            reason=reason,
        )
        return f"Task accepted: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task acceptance rejected: {exc}"


@mcp.tool()
async def decline_task(
    simulation_id: str,
    issue_key: str,
    actor: str,
    reason: str = "",
) -> str:
    """Decline a pending task offer assigned to you and record why."""
    try:
        task = _get_lifecycle(simulation_id).decline_task(
            task_ref=issue_key,
            actor=actor,
            reason=reason,
        )
        return f"Task declined: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task decline rejected: {exc}"


@mcp.tool()
async def get_task(
    simulation_id: str,
    issue_key: str,
    actor: str,
) -> str:
    """Get details for a task you assigned or that is assigned to you."""
    try:
        task = _get_lifecycle(simulation_id).get_task_for_actor(
            task_ref=issue_key,
            actor=actor,
        )
        return _format_task_detail(task)
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task lookup rejected: {exc}"


@mcp.tool()
async def start_task(
    simulation_id: str,
    issue_key: str,
    actor: str,
    reason: str = "",
) -> str:
    """Mark one of your assigned tasks as in progress."""
    try:
        task = _get_lifecycle(simulation_id).start_task(
            task_ref=issue_key,
            actor=actor,
            reason=reason,
        )
        return f"Task started: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task start rejected: {exc}"


@mcp.tool()
async def block_task(
    simulation_id: str,
    issue_key: str,
    actor: str,
    reason: str,
) -> str:
    """Mark one of your assigned tasks as blocked and record why."""
    try:
        task = _get_lifecycle(simulation_id).block_task(
            task_ref=issue_key,
            actor=actor,
            reason=reason,
        )
        return f"Task blocked: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task block rejected: {exc}"


@mcp.tool()
async def complete_task(
    simulation_id: str,
    issue_key: str,
    output: str,
    actor: str,
) -> str:
    """Complete one of your assigned tasks using its visible issue key."""
    try:
        task = _get_lifecycle(simulation_id).complete_task(
            task_ref=issue_key,
            actor=actor,
            output=output,
        )
        return f"Task completed: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task completion rejected: {exc}"


def _decode_artifact_content(content: str, encoding: str) -> str | bytes:
    normalized_encoding = (encoding or "utf-8").strip().lower()
    if normalized_encoding in {"utf-8", "utf8", "text", "plain"}:
        return content
    if normalized_encoding in {"base64", "b64"}:
        try:
            return base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise TaskLifecycleError(f"Invalid base64 artifact payload: {exc}") from exc
    raise TaskLifecycleError(
        f"Unsupported artifact encoding '{encoding}'. Use utf-8 or base64."
    )


@mcp.tool()
async def save_task_artifact(
    simulation_id: str,
    issue_key: str,
    filename: str,
    content: str,
    actor: str,
    media_type: str = "",
    encoding: str = "utf-8",
    kind: str = "deliverable",
    note: str = "",
) -> str:
    """Save a file-like deliverable before completing a task.

    Use this for outputs that naturally belong in a file, such as markdown briefs,
    memos, meeting notes, CSV tables, JSON payloads, code/config snippets, or
    base64-encoded PDFs. Choose a descriptive filename with an appropriate
    extension, set the matching media type, and then call `complete_task` with a
    short summary that references the saved file.
    """
    try:
        artifact = _get_lifecycle(simulation_id).save_artifact(
            issue_key,
            actor=actor,
            filename=filename,
            content=_decode_artifact_content(content, encoding),
            media_type=media_type or None,
            kind=kind or "deliverable",
            note=note or None,
        )
        media_label = artifact.media_type or "application/octet-stream"
        size_label = artifact.size_bytes or 0
        return (
            f"Task artifact saved: {issue_key} -> {artifact.filename} "
            f"({media_label}, {size_label} bytes) at {artifact.relative_path}"
        )
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task artifact save rejected: {exc}"


@mcp.tool()
async def list_my_tasks(
    simulation_id: str,
    actor: str,
    status: str = "",
) -> str:
    """List tasks assigned to the acting agent, grouped by status."""
    lifecycle = _get_lifecycle(simulation_id)
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status not in set(_STATUS_ORDER):
        valid_values = ", ".join(_STATUS_ORDER)
        return f"Invalid status '{status}'. Valid values: {valid_values}."

    tasks = lifecycle.store.list_tasks(
        assigned_to=actor,
        status=normalized_status or None,
    )
    if not tasks:
        if normalized_status:
            return f"No {normalized_status} tasks assigned to {actor}."
        return f"No tasks assigned to {actor}."

    grouped: dict[str, list] = {value: [] for value in _STATUS_ORDER}
    for task in tasks:
        grouped.setdefault(task.status, []).append(task)

    lines = [f"Tasks for {actor} ({len(tasks)} total):"]
    for status_name in _STATUS_ORDER:
        group = grouped.get(status_name, [])
        if not group:
            continue
        lines.append(f"[{status_name.upper()}]")
        for task in group:
            lines.append(f"  - {_format_task_summary(task)}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
