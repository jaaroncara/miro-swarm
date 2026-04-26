"""
Task context injection helper.

Builds a compact task-summary message for a given agent and injects it
into the agent's CAMEL memory so the LLM sees pending tasks before acting.
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)

_BLOCKED_ESCALATION_THRESHOLD = 2


def task_requires_agent_response(
    task: Any,
    *,
    current_round: int | None = None,
    total_rounds: int | None = None,
) -> bool:
    """Return True when a task should force a directed response this round."""
    if task.status in {"offered", "open", "in_progress"}:
        return True
    if task.status != "blocked":
        return False
    return _should_escalate_blocked_task(
        task,
        current_round=current_round,
        total_rounds=total_rounds,
    )


def build_task_context_message(
    agent_name: str,
    store: Any,
    *,
    current_round: int | None = None,
    total_rounds: int | None = None,
) -> str | None:
    """Build a forcing task-directive string for one agent.

    For each offered, open, or in-progress task assigned to this agent,
    emits an explicit instruction block that requires a directed reply this
    round. The message stays MCP-first while still documenting the legacy XML
    fallback.

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
        offered or active tasks.
    """
    offered_tasks = store.list_tasks(assigned_to=agent_name, status="offered")
    open_tasks = store.list_tasks(assigned_to=agent_name, status="open")
    in_progress_tasks = store.list_tasks(assigned_to=agent_name, status="in_progress")
    blocked_tasks = [
        task
        for task in store.list_tasks(assigned_to=agent_name, status="blocked")
        if task_requires_agent_response(
            task,
            current_round=current_round,
            total_rounds=total_rounds,
        )
    ]

    # Priority order is: offers, accepted work, then blocked work near expiry.
    tasks = offered_tasks + open_tasks + in_progress_tasks + blocked_tasks

    if not tasks:
        return None

    future_rounds_remaining = _future_rounds_remaining(
        current_round=current_round,
        total_rounds=total_rounds,
    )

    lines: list[str] = [
        "=== REQUIRED ACTIONS THIS ROUND ===",
        f"You have {len(tasks)} task(s) that require a response from you RIGHT NOW.",
    ]

    if current_round is not None and total_rounds is not None:
        lines.append(f"Simulation clock: round {current_round} of {total_rounds}.")
        if future_rounds_remaining == 0:
            lines.append(
                "This is the final round. Anything still unfinished after this turn can expire automatically."
            )
        elif future_rounds_remaining == 1:
            lines.append(
                "Only 1 future round remains after this turn. Resolve offers now and surface blockers explicitly."
            )
        else:
            lines.append(
                f"{future_rounds_remaining} future round(s) remain after this turn."
            )

    lines.extend(
        [
            "Priority order this round: resolve pending offers first, then progress accepted work, then escalate blocked work before the run ends.",
            "For each task below you MUST create a post or reply that:",
            "  1. Directly addresses the person who assigned the task (tag them by name).",
            "  2. Uses MCP task tools for all task lifecycle updates in this run.",
            "  3. Keeps the work executable inside the simulation. If a request is really a meeting or conversation, decline it or rewrite it into a concrete deliverable.",
            "  4. If the deliverable is file-like, such as a markdown brief, memo, CSV, JSON, code/config, or PDF, save it with `save_task_artifact` first using a clear filename and media type.",
            "  5. Leave visible public updates for high-signal lifecycle events only: accepted, blocked, and completed. Keep each update concise and avoid repetitive progress pings.",
            "  6. When you publish a final report or deliverable, store that same content in the task completion output, or summarize the saved artifact when you complete the task.",
            "Before posting unrelated topics, ensure each task listed here has received the required response this round.",
            "",
        ]
    )

    for task in tasks:
        issue_key = task.issue_key or task.task_id[:8]
        assigner = task.assigned_by or "a colleague"
        if task.status == "offered":
            status_label = "OFFERED - awaiting your decision"
        elif task.status == "open":
            status_label = "OPEN - accepted but not yet started"
        elif task.status == "in_progress":
            status_label = "IN PROGRESS"
        else:
            status_label = "BLOCKED - requires escalation"

        lines.append(f"--- TASK [{issue_key}] ({status_label}) ---")
        lines.append(f"  Assigned by : {assigner}")
        lines.append(f"  Title       : {task.title}")
        if task.description:
            lines.append(f"  Description : {task.description}")
        if task.parent_goal:
            lines.append(f"  Goal        : {task.parent_goal}")
        if task.created_round is not None:
            lines.append(f"  Created round : {task.created_round}")
        if task.due_round is not None:
            lines.append(f"  Due round     : {task.due_round}")
        if task.round_budget is not None:
            lines.append(f"  Round budget  : {task.round_budget}")
        if getattr(task, "deliverable_type", None):
            lines.append(f"  Deliverable   : {task.deliverable_type}")
        if getattr(task, "acceptance_criteria", None):
            lines.append(f"  Acceptance    : {task.acceptance_criteria[0]}")
        if getattr(task, "suggested_tools", None):
            lines.append(f"  Suggested tools : {', '.join(task.suggested_tools)}")
        if getattr(task, "tool_plan", None):
            lines.append(f"  Tool plan    : {task.tool_plan}")
        time_window = _describe_task_time_window(
            task,
            current_round=current_round,
            total_rounds=total_rounds,
        )
        if time_window:
            lines.append(f"  Time left   : {time_window}")
        mention_context = getattr(task, "mention_context", {}) or {}
        if mention_context.get("snippet"):
            lines.append(f"  Public context : {mention_context['snippet']}")
        lines.append(f"  Issue key   : {issue_key}")
        lines.append(f"  Hidden task ID: {task.task_id}")
        lines.append("")

        if task.status == "offered":
            lines.append(
                f"  ACTION REQUIRED: Decide whether to accept or decline this offer before you do other work. "
                f"Prefer MCP `accept_task` or `decline_task` with issue_key {issue_key}, then acknowledge the decision publicly in chat."
            )
        elif task.status == "open":
            lines.append(
                f"  ACTION REQUIRED: Reply to {assigner} acknowledging this task and "
                f"either start working on it or complete it immediately if you can. "
                f"Prefer MCP `start_task`, `update_task_status`, or `complete_task`. If the finished deliverable is file-like, save it with `save_task_artifact` before `complete_task`, using a descriptive filename such as `brief.md` or `results.json`."
            )
        elif task.status == "in_progress":
            lines.append(
                f"  ACTION REQUIRED: Post an update to {assigner} on the progress of "
                f"this task, or complete it if the work is done. Prefer MCP `update_task_status` for progress notes and `complete_task` when possible. If the deliverable is a file, save it with `save_task_artifact` first and then mention the saved filename in the completion summary."
            )
        else:
            lines.append(
                f"  ACTION REQUIRED: You are still blocked on this task. Reply to {assigner} with the blocker, "
                f"what you need, and whether the task should be re-scoped before the run ends."
            )
            lines.append(
                "  A plain reply is enough here; only use MCP task actions if the task status is changing again."
            )

        lines.append("")

    lines.append("=== END REQUIRED ACTIONS ===")
    return "\n".join(lines)


def inject_task_context(
    active_agents: List[Tuple[int, Any]],
    store: Any,
    agent_graph: Any,
    pending_notifications: "dict[str, list[str]] | None" = None,
    *,
    current_round: int | None = None,
    total_rounds: int | None = None,
) -> None:
    """Inject task context and notifications into each active agent's memory.

    For each active agent:
    - Delivers any queued persistent task notifications for that agent, plus
      any legacy in-memory notifications still passed by older callers.
    - Injects the forcing task-directive for any offered/open/in-progress tasks
      assigned to the agent.

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
        Legacy mutable dict mapping agent display-name to a list of notification
        strings queued since the last round. Delivered items are removed from
        the dict so entries are never replayed.
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
            notifications: list[str] = []

            consume_notifications = getattr(store, "consume_notifications", None)
            if callable(consume_notifications):
                notifications.extend(
                    [item.message for item in consume_notifications(agent_name)]
                )

            if pending_notifications:
                notifications.extend(pending_notifications.pop(agent_name, None) or [])

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

            # --- inject task directives for offered/open/in-progress tasks ---
            context_message = build_task_context_message(
                agent_name,
                store,
                current_round=current_round,
                total_rounds=total_rounds,
            )
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


def _future_rounds_remaining(
    *,
    current_round: int | None,
    total_rounds: int | None,
) -> int | None:
    if current_round is None or total_rounds is None:
        return None
    return max(total_rounds - current_round, 0)


def _task_future_rounds_remaining(
    task: Any,
    *,
    current_round: int | None,
) -> int | None:
    due_round = getattr(task, "due_round", None)
    if current_round is None or due_round is None:
        return None
    return max(due_round - current_round, 0)


def _should_escalate_blocked_task(
    task: Any,
    *,
    current_round: int | None,
    total_rounds: int | None,
) -> bool:
    task_future_rounds = _task_future_rounds_remaining(
        task,
        current_round=current_round,
    )
    global_future_rounds = _future_rounds_remaining(
        current_round=current_round,
        total_rounds=total_rounds,
    )

    if task_future_rounds is None and global_future_rounds is None:
        return True
    if (
        task_future_rounds is not None
        and task_future_rounds <= _BLOCKED_ESCALATION_THRESHOLD
    ):
        return True
    if (
        global_future_rounds is not None
        and global_future_rounds <= _BLOCKED_ESCALATION_THRESHOLD
    ):
        return True
    return False


def _describe_task_time_window(
    task: Any,
    *,
    current_round: int | None,
    total_rounds: int | None,
) -> str | None:
    task_future_rounds = _task_future_rounds_remaining(
        task,
        current_round=current_round,
    )
    if task_future_rounds is not None and getattr(task, "due_round", None) is not None:
        if task_future_rounds == 0:
            return f"Due now (must be resolved by round {task.due_round})."
        if task_future_rounds == 1:
            return f"1 future round remains before round {task.due_round}."
        return f"{task_future_rounds} future round(s) remain before round {task.due_round}."

    global_future_rounds = _future_rounds_remaining(
        current_round=current_round,
        total_rounds=total_rounds,
    )
    if global_future_rounds is None:
        return None
    if global_future_rounds == 0:
        return "No future rounds remain after this turn."
    if global_future_rounds == 1:
        return "1 future round remains after this turn."
    return f"{global_future_rounds} future round(s) remain after this turn."
