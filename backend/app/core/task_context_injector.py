"""
Task context injection helper.

Builds a compact task-summary message for a given agent and injects it
into the agent's CAMEL memory so the LLM sees pending tasks before acting.
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)


def build_task_context_message(agent_name: str, store: Any) -> str | None:
    """Build a forcing task-directive string for one agent.

    For each open or in-progress task assigned to this agent, emits an
    explicit instruction block that requires a directed reply this round -
    including the full task description, assigner name, issue key, and the
    required ``<task_action>`` XML the agent must embed in their post.

    Parameters
    ----------
    agent_name : str
        Display name of the agent (must match ``assigned_to`` in the store).
    store : SimulationTaskStore
        Task store instance to query.

    Returns
    -------
    str or None
        A formatted directive message, or ``None`` if the agent has no
        active tasks.
    """
    open_tasks = store.list_tasks(assigned_to=agent_name, status="open")
    in_progress_tasks = store.list_tasks(assigned_to=agent_name, status="in_progress")

    # Open tasks (never acknowledged) are highest-priority; list them first.
    tasks = open_tasks + in_progress_tasks

    if not tasks:
        return None

    lines: list[str] = [
        "=== REQUIRED ACTIONS THIS ROUND ===",
        f"You have {len(tasks)} task(s) that require a response from you RIGHT NOW.",
        "For each task below you MUST create a post or reply that:",
        "  1. Directly addresses the person who assigned the task (tag them by name).",
        "  2. Either confirms you are working on it OR delivers the completed result.",
        "  3. Includes the appropriate <task_action> XML block at the end of your post.",
        "Do NOT post about any other topic until you have responded to every task listed here.",
        "",
    ]

    for task in tasks:
        issue_key = task.issue_key or task.task_id[:8]
        assigner = task.assigned_by or "a colleague"
        status_label = (
            "NEW - not yet acknowledged" if task.status == "open" else "IN PROGRESS"
        )

        lines.append(f"--- TASK [{issue_key}] ({status_label}) ---")
        lines.append(f"  Assigned by : {assigner}")
        lines.append(f"  Title       : {task.title}")
        if task.description:
            lines.append(f"  Description : {task.description}")
        if task.parent_goal:
            lines.append(f"  Goal        : {task.parent_goal}")
        lines.append(f"  Issue key   : {issue_key}")
        lines.append(f"  Hidden task ID: {task.task_id}")
        lines.append("")

        if task.status == "open":
            lines.append(
                f"  ACTION REQUIRED: Reply to {assigner} acknowledging this task and "
                f"either start working on it (update_status -> in_progress) or "
                f"complete it immediately if you can."
            )
            lines.append(
                f"  Your post MUST end with:\n"
                f'  <task_action type="update_status">\n'
                f"    <issue_key>{issue_key}</issue_key>\n"
                f"    <status>in_progress</status>\n"
                f"    <reason>Brief description of your plan</reason>\n"
                f"  </task_action>\n"
                f"  OR, if you can complete it now:\n"
                f'  <task_action type="complete">\n'
                f"    <issue_key>{issue_key}</issue_key>\n"
                f"    <output>Your complete response / result</output>\n"
                f"  </task_action>"
            )
        else:
            lines.append(
                f"  ACTION REQUIRED: Post an update to {assigner} on the progress of "
                f"this task, or complete it if the work is done."
            )
            lines.append(
                f'  Your post MUST end with a <task_action type="complete"> or '
                f'<task_action type="update_status"> block using issue_key {issue_key}.'
            )

        lines.append("")

    lines.append("=== END REQUIRED ACTIONS ===")
    return "\n".join(lines)


def inject_task_context(
    active_agents: List[Tuple[int, Any]],
    store: Any,
    agent_graph: Any,
    pending_notifications: "dict[str, list[str]] | None" = None,
) -> None:
    """Inject task context and pending notifications into each active agent's memory.

    For each active agent:
    - Delivers any queued task-completion or status-update notifications sent
      to that agent by other agents (draining ``pending_notifications`` in-place).
    - Injects the forcing task-directive for any open/in-progress tasks assigned
      to the agent.

    Errors are caught per-agent so a single failure never crashes the simulation.

    Parameters
    ----------
    active_agents : list of (agent_id, agent) tuples
        The OASIS active agents list for the current round.
    store : SimulationTaskStore
        Task store for the running simulation.
    agent_graph : AgentGraph
        The OASIS agent graph (kept as a parameter for future flexibility).
    pending_notifications : dict[str, list[str]], optional
        Mutable dict mapping agent display-name to a list of notification
        strings queued since the last round.  Delivered items are removed
        from the dict so entries are never replayed.
    """
    from camel.messages import BaseMessage
    from camel.types import OpenAIBackendRole

    for agent_id, agent in active_agents:
        try:
            # Resolve the agent's display name using the same attribute chain
            # that OASIS / camel populates when building the agent graph.
            user_info = getattr(agent, "user_info", None)
            if user_info is not None:
                agent_name = (
                    getattr(user_info, "name", None)
                    or getattr(user_info, "user_name", None)
                    or f"Agent_{agent_id}"
                )
            else:
                agent_name = f"Agent_{agent_id}"

            # --- deliver pending notifications for this agent ---
            if pending_notifications:
                notifications = pending_notifications.pop(agent_name, None)
                if notifications:
                    notif_text = "\n\n".join(notifications)
                    notif_msg = BaseMessage.make_user_message(
                        role_name="User", content=notif_text
                    )
                    agent.update_memory(notif_msg, OpenAIBackendRole.USER)
                    logger.debug(
                        "Delivered %d notification(s) to agent_id=%s (%s)",
                        len(notifications),
                        agent_id,
                        agent_name,
                    )

            # --- inject task directives for open/in-progress tasks ---
            context_message = build_task_context_message(agent_name, store)
            if context_message is None:
                continue

            msg = BaseMessage.make_user_message(
                role_name="User", content=context_message
            )
            agent.update_memory(msg, OpenAIBackendRole.USER)

        except Exception as exc:
            logger.warning(
                "Task context injection failed for agent_id=%s: %s",
                agent_id,
                exc,
                exc_info=False,
            )
