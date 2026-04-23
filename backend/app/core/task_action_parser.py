"""
Task action XML parser for simulation agents.

Agents may embed structured ``<task_action>`` XML blocks in their post/comment
content to create, complete, or update simulation tasks.  This module is a
standalone, dependency-free parser with no Flask imports.
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.core.simulation_task_store import SimulationTaskStore

from .task_lifecycle import (
    TaskAuthorizationError,
    TaskLifecycleError,
    TaskLifecycleService,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grammar constant – injected into agent system prompts at the prepare step
# ---------------------------------------------------------------------------

TASK_ACTION_GRAMMAR = """\
You may coordinate work by embedding structured task actions in your messages using XML tags. These are processed by the simulation engine — they do not appear in the public post.

To create a task and assign it to a colleague:
<task_action type="create">
  <title>Short task title</title>
  <assign_to>PERSONA_NAME</assign_to>
  <description>What needs to be done</description>
  <parent_goal>Optional: related topic or goal</parent_goal>
</task_action>

To mark one of your assigned tasks as complete:
<task_action type="complete">
    <issue_key>ABC-123</issue_key>
  <output>Summary of what was accomplished</output>
</task_action>

To update the status of a task (blocked or in_progress):
<task_action type="update_status">
    <issue_key>ABC-123</issue_key>
  <status>blocked</status>
  <reason>Why it is blocked</reason>
</task_action>

Legacy compatibility: ``<task_id>`` is still accepted, but new task replies should
prefer the visible ``<issue_key>`` value.

Only include a task_action tag when you genuinely intend to create or update a task. One task_action per message maximum."""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

_VALID_ACTION_TYPES = {"create", "complete", "update_status"}

# Regex: match the outermost <task_action ...>...</task_action> block (non-greedy)
_BLOCK_RE = re.compile(
    r"<task_action\b([^>]*)>(.*?)</task_action>",
    re.DOTALL | re.IGNORECASE,
)

# Regex: extract a single named attribute from the opening tag
_ATTR_RE = re.compile(r'\btype\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

# Regex: extract the text content of a named XML child element
_CHILD_RE = re.compile(r"<{tag}\b[^>]*>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)


def _extract_child(tag: str, block: str) -> Optional[str]:
    """Return the stripped text content of the first matching child element."""
    pattern = re.compile(
        rf"<{re.escape(tag)}\b[^>]*>(.*?)</{re.escape(tag)}>", re.DOTALL | re.IGNORECASE
    )
    m = pattern.search(block)
    if m:
        return m.group(1).strip() or None
    return None


@dataclass
class ParsedTaskAction:
    """Parsed representation of a ``<task_action>`` XML block."""

    action_type: str
    title: Optional[str] = None
    assign_to: Optional[str] = None
    description: Optional[str] = None
    parent_goal: Optional[str] = None
    issue_key: Optional[str] = None
    task_id: Optional[str] = None
    output: Optional[str] = None
    status: Optional[str] = None
    reason: Optional[str] = None

    @property
    def task_ref(self) -> Optional[str]:
        return self.issue_key or self.task_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_task_action(content: str) -> Optional[ParsedTaskAction]:
    """Parse the first ``<task_action>`` block found in ``content``.

    Parameters
    ----------
    content : str
        Raw message text that may contain a ``<task_action>`` block.

    Returns
    -------
    ParsedTaskAction or None
        A populated dataclass if a valid, recognised action block was found;
        ``None`` otherwise.  Never raises.
    """
    try:
        m = _BLOCK_RE.search(content)
        if m is None:
            return None

        attrs_str = m.group(1)
        body = m.group(2)

        type_match = _ATTR_RE.search(attrs_str)
        if type_match is None:
            return None

        action_type = type_match.group(1).strip().lower()
        if action_type not in _VALID_ACTION_TYPES:
            return None

        return ParsedTaskAction(
            action_type=action_type,
            title=_extract_child("title", body),
            assign_to=_extract_child("assign_to", body),
            description=_extract_child("description", body),
            parent_goal=_extract_child("parent_goal", body),
            issue_key=_extract_child("issue_key", body),
            task_id=_extract_child("task_id", body),
            output=_extract_child("output", body),
            status=_extract_child("status", body),
            reason=_extract_child("reason", body),
        )
    except Exception as exc:
        logger.debug(f"parse_task_action: failed to parse content: {exc}")
        return None


def strip_task_action(content: str) -> str:
    """Remove the first ``<task_action>`` block from ``content`` and tidy whitespace.

    Parameters
    ----------
    content : str
        Raw message text.

    Returns
    -------
    str
        Text with the ``<task_action>...</task_action>`` block removed and
        surrounding blank lines collapsed.  If no block is present, returns
        the original string unchanged.
    """
    try:
        stripped = _BLOCK_RE.sub("", content)
        # Collapse runs of blank lines introduced by the removal
        stripped = re.sub(r"\n{3,}", "\n\n", stripped)
        return stripped.strip()
    except Exception:
        return content


def apply_task_action(
    parsed: "ParsedTaskAction",
    agent_name: str,
    simulation_id: str,
    store: Any,
) -> Optional[str]:
    """Dispatch ``parsed`` through the canonical lifecycle service.

    Parameters
    ----------
    parsed : ParsedTaskAction
        The action to apply.
    agent_name : str
        Name of the agent issuing the action.
    simulation_id : str
        The running simulation identifier (informational; store is already bound).
    store : SimulationTaskStore
        Task store instance for the current simulation.

    Returns
    -------
    str or None
        The affected hidden ``task_id`` on success, or ``None`` when the action
        could not be applied (missing required fields, unauthorized actor,
        invalid transition, task not found, etc.). Never raises.
    """
    lifecycle = TaskLifecycleService(simulation_id=simulation_id, store=store)

    try:
        if parsed.action_type == "create":
            if not parsed.title or not parsed.assign_to:
                logger.debug(
                    f"apply_task_action: 'create' missing title or assign_to "
                    f"(simulation={simulation_id}, agent={agent_name})"
                )
                return None
            task = lifecycle.create_task(
                title=parsed.title,
                description=parsed.description or "",
                assigned_to=parsed.assign_to,
                assigned_by=agent_name,
                parent_goal=parsed.parent_goal,
                actor=agent_name,
            )
            logger.info(
                f"Task created: {task.issue_key!r} '{task.title}' "
                f"({agent_name} -> {parsed.assign_to}) simulation={simulation_id}"
            )
            return task.task_id

        elif parsed.action_type == "complete":
            if not parsed.task_ref:
                logger.debug(
                    f"apply_task_action: 'complete' missing task reference "
                    f"(simulation={simulation_id}, agent={agent_name})"
                )
                return None
            result = lifecycle.complete_task(
                task_ref=parsed.task_ref,
                actor=agent_name,
                output=parsed.output or "",
            )
            logger.info(
                f"Task completed: {result.issue_key!r} by {agent_name} simulation={simulation_id}"
            )
            return result.task_id

        elif parsed.action_type == "update_status":
            if not parsed.task_ref or not parsed.status:
                logger.debug(
                    f"apply_task_action: 'update_status' missing task reference or status "
                    f"(simulation={simulation_id}, agent={agent_name})"
                )
                return None
            result = lifecycle.update_task_status(
                task_ref=parsed.task_ref,
                actor=agent_name,
                status=parsed.status,
                reason=parsed.reason,
                output=parsed.output,
            )
            logger.info(
                f"Task status updated: {result.issue_key!r} -> {parsed.status!r} "
                f"by {agent_name} simulation={simulation_id}"
            )
            return result.task_id

    except (TaskAuthorizationError, TaskLifecycleError) as exc:
        logger.info(
            f"apply_task_action: rejected task action "
            f"(simulation={simulation_id}, agent={agent_name}, type={parsed.action_type}): {exc}"
        )
    except Exception as exc:
        logger.warning(
            f"apply_task_action: unexpected error "
            f"(simulation={simulation_id}, agent={agent_name}, type={parsed.action_type}): {exc}"
        )

    return None
