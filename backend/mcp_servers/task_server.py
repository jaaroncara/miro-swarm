"""Task MCP server backed by the canonical lifecycle service."""

import json
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from mcp.server.fastmcp import FastMCP

from app.core.task_lifecycle import (
    TaskAuthorizationError,
    TaskLifecycleError,
    TaskLifecycleService,
)

mcp = FastMCP("task-tools")

_STATUS_ORDER = ["open", "in_progress", "blocked", "done"]


def _format_task_summary(task) -> str:
    goal_label = f" | Goal: {task.parent_goal}" if task.parent_goal else ""
    return (
        f'{task.issue_key} [{task.status}] "{task.title}" '
        f"({task.assigned_by} -> {task.assigned_to}{goal_label})"
    )


def _format_task_detail(task) -> str:
    return json.dumps(task.to_dict(), ensure_ascii=False, indent=2)


def _get_lifecycle(simulation_id: str) -> TaskLifecycleService:
    return TaskLifecycleService(simulation_id=simulation_id)


@mcp.tool()
async def create_task(
    simulation_id: str,
    title: str,
    description: str,
    assigned_to: str,
    actor: str,
    parent_goal: str = "",
) -> str:
    """Create a new task for a colleague and return its visible issue key."""
    try:
        task = _get_lifecycle(simulation_id).create_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            parent_goal=parent_goal or None,
            actor=actor,
        )
        return f"Task created: {_format_task_summary(task)}"
    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        return f"Task creation rejected: {exc}"


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


@mcp.tool()
async def list_my_tasks(
    simulation_id: str,
    actor: str,
    status: str = "",
) -> str:
    """List tasks assigned to the acting agent, grouped by status."""
    lifecycle = _get_lifecycle(simulation_id)
    if status and status not in set(_STATUS_ORDER):
        valid_values = ", ".join(_STATUS_ORDER)
        return f"Invalid status '{status}'. Valid values: {valid_values}."

    tasks = lifecycle.store.list_tasks(assigned_to=actor, status=status or None)
    if not tasks:
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
