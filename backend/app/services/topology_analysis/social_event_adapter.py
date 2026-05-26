"""Adapter to convert OASIS social actions into CoordinationEvents.

Bridges the gap between OASIS agent activities (posts, comments, likes, follows)
and the topology analysis event schema. This allows the TDA pipeline to analyze
social interaction patterns using the same infrastructure built for MCP task events.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ...utils.logger import get_logger
from .events import CoordinationEvent

logger = get_logger("mirofish.topology_analysis.social_event_adapter")

# OASIS action types that map to coordination events
_ACTION_TYPE_MAP: Dict[str, str] = {
    "CREATE_POST": "task_created",
    "CREATE_COMMENT": "task_handoff",
    "QUOTE_POST": "task_referenced",
    "FOLLOW": "relationship_established",
    "LIKE_POST": "feedback_given",
    "LIKE_COMMENT": "feedback_given",
    "DISLIKE_POST": "feedback_given",
    "DISLIKE_COMMENT": "feedback_given",
    "REPOST": "task_referenced",
    "MUTE": "relationship_severed",
}

# System event types to skip when reading JSONL logs
_SYSTEM_EVENT_TYPES = frozenset({
    "round_end",
    "round_start",
    "simulation_complete",
    "simulation_start",
    "system",
})


def oasis_action_to_coordination_event(
    action_data: Dict[str, Any],
) -> Optional[CoordinationEvent]:
    """Convert a raw OASIS action dict into a CoordinationEvent.

    Args:
        action_data: Raw action dictionary from the JSONL action log.
            Expected keys: action_type, agent_name, round_num, timestamp,
            action_args, platform.

    Returns:
        A CoordinationEvent if the action maps to one, otherwise None.
    """
    action_type = action_data.get("action_type", "")

    # Skip actions that don't map to coordination events
    if action_type not in _ACTION_TYPE_MAP:
        logger.debug("Skipping unmapped action type: %s", action_type)
        return None

    event_type = _ACTION_TYPE_MAP[action_type]
    agent_name = action_data.get("agent_name", "unknown")
    round_num = action_data.get("round_num", 0)
    platform = action_data.get("platform", "twitter")
    action_args = action_data.get("action_args", {})

    # Parse timestamp
    raw_ts = action_data.get("timestamp")
    if raw_ts:
        try:
            timestamp = datetime.fromisoformat(str(raw_ts))
        except (ValueError, TypeError):
            timestamp = datetime.utcnow()
    else:
        timestamp = datetime.utcnow()

    # Generate task_id for event grouping
    task_id = _generate_task_id(action_type, action_args, agent_name, round_num)

    # Extract target agent for interaction tracking
    target_agent = _extract_target_agent(action_type, action_args)

    # Build details dict
    details: Dict[str, Any] = {
        "source": "oasis_social",
        "action_type": action_type,
        "platform": platform,
    }
    if target_agent:
        details["target_agent"] = target_agent

    # Include relevant action_args (exclude overly verbose content)
    for key in ("post_id", "comment_id", "content", "hashtags", "topic"):
        if key in action_args:
            # Truncate content to avoid bloating details
            val = action_args[key]
            if key == "content" and isinstance(val, str) and len(val) > 200:
                val = val[:200] + "..."
            details[key] = val

    # Include sentiment for feedback events
    if action_type in ("DISLIKE_POST", "DISLIKE_COMMENT"):
        details["sentiment"] = "negative"
    elif action_type in ("LIKE_POST", "LIKE_COMMENT"):
        details["sentiment"] = "positive"

    return CoordinationEvent(
        task_id=task_id,
        event_type=event_type,
        actor=agent_name,
        timestamp=timestamp,
        round_index=round_num,
        details=details,
    )


def convert_action_log(actions: List[Dict[str, Any]]) -> List[CoordinationEvent]:
    """Batch convert a list of raw action dicts to CoordinationEvents.

    Filters out None results and sorts by timestamp.

    Args:
        actions: List of raw action dictionaries from OASIS.

    Returns:
        Sorted list of CoordinationEvents.
    """
    events: List[CoordinationEvent] = []
    for action in actions:
        event = oasis_action_to_coordination_event(action)
        if event is not None:
            events.append(event)

    events.sort(key=lambda e: e.timestamp)
    logger.info("Converted %d/%d OASIS actions to coordination events", len(events), len(actions))
    return events


def load_social_events_from_jsonl(jsonl_path: Path) -> List[CoordinationEvent]:
    """Read an actions.jsonl file and convert to CoordinationEvents.

    Reads line by line, parses JSON, skips system events, and converts
    social actions using oasis_action_to_coordination_event.

    Args:
        jsonl_path: Path to the JSONL action log file.

    Returns:
        Sorted list of CoordinationEvents from social actions.
    """
    if not jsonl_path.exists():
        logger.warning("JSONL file not found: %s", jsonl_path)
        return []

    actions: List[Dict[str, Any]] = []
    skipped = 0

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON at line %d in %s", line_num, jsonl_path)
                skipped += 1
                continue

            # Skip system events
            event_type = data.get("event_type", "")
            if event_type in _SYSTEM_EVENT_TYPES:
                skipped += 1
                continue

            actions.append(data)

    logger.info(
        "Read %d action lines from %s (skipped %d system/malformed)",
        len(actions),
        jsonl_path,
        skipped,
    )
    return convert_action_log(actions)


def _extract_target_agent(
    action_type: str, action_args: Dict[str, Any]
) -> Optional[str]:
    """Extract the target agent name from action_args based on action type.

    Args:
        action_type: The OASIS action type string.
        action_args: The action arguments dictionary.

    Returns:
        Target agent name if identifiable, otherwise None.
    """
    if action_type == "CREATE_COMMENT":
        return (
            action_args.get("parent_comment_author_name")
            or action_args.get("post_author_name")
        )
    elif action_type in ("QUOTE_POST", "REPOST"):
        return (
            action_args.get("original_author_name")
            or action_args.get("post_author_name")
        )
    elif action_type in ("LIKE_POST", "DISLIKE_POST"):
        return action_args.get("post_author_name")
    elif action_type in ("LIKE_COMMENT", "DISLIKE_COMMENT"):
        return action_args.get("comment_author_name")
    elif action_type in ("FOLLOW", "MUTE"):
        return action_args.get("target_user_name")

    return None


def _generate_task_id(
    action_type: str,
    action_args: Dict[str, Any],
    agent_name: str,
    round_num: int,
) -> str:
    """Generate a synthetic task_id for grouping related events.

    Consistent task_ids allow the windowing logic to group related events
    (e.g., a post and its comments share the same task_id).

    Args:
        action_type: The OASIS action type string.
        action_args: The action arguments dictionary.
        agent_name: Name of the acting agent.
        round_num: Current simulation round number.

    Returns:
        A string task_id for the coordination event.
    """
    # Relationship actions use a dedicated ID scheme
    if action_type in ("FOLLOW", "MUTE"):
        target = action_args.get("target_user_name", "unknown")
        return f"rel_{agent_name}_{target}"

    # Post-related actions: try to use post_id for consistency
    post_id = action_args.get("post_id")
    if post_id is not None:
        return f"post_{post_id}"

    # For comments referencing a parent post
    parent_post_id = action_args.get("parent_post_id")
    if parent_post_id is not None:
        return f"post_{parent_post_id}"

    # For quote/repost referencing the original
    original_post_id = action_args.get("original_post_id")
    if original_post_id is not None:
        return f"post_{original_post_id}"

    # Fallback: generate unique ID
    return f"social_{agent_name}_{round_num}_{uuid4().hex[:8]}"
