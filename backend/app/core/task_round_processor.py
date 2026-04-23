"""Helpers for processing task mutations from simulation round activity."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any, Optional

from .simulation_task_store import TERMINAL_TASK_STATUSES
from .task_observability import log_task_pipeline_metric
from .task_action_parser import apply_task_action, parse_task_action, strip_task_action
from .task_lifecycle import TaskLifecycleError, TaskLifecycleService

logger = logging.getLogger(__name__)

_GENERIC_MENTION_TOKENS = {"all", "everyone", "everybody", "team"}
_MENTION_TOKEN_RE = re.compile(r"(?<!\w)@(?P<handle>[A-Za-z0-9_][A-Za-z0-9_.-]{0,63})")
_MENTION_REFERENCE_RE = re.compile(r"@[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
_REQUEST_ANYWHERE_PATTERNS = (
    re.compile(r"\b(?:can|could|would|will)\s+you\b", re.IGNORECASE),
    re.compile(r"\bplease\b", re.IGNORECASE),
    re.compile(r"\b(?:i|we)\s+need\s+you\s+to\b", re.IGNORECASE),
    re.compile(r"\bneed\s+you\s+to\b", re.IGNORECASE),
    re.compile(
        r"\b(?:i|we)\s+need\s+@[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\s+to\b", re.IGNORECASE
    ),
    re.compile(r"\bneed\s+@[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\s+to\b", re.IGNORECASE),
)
_REQUEST_AFTER_MENTION_PATTERNS = (
    re.compile(r"^\s*(?:[,:\-]\s*)?(?:can|could|would|will)\s+you\b", re.IGNORECASE),
    re.compile(r"^\s*(?:[,:\-]\s*)?please\b", re.IGNORECASE),
    re.compile(
        r"^\s*(?:[,:\-]\s*)?(?:take|handle|review|prepare|draft|compile|investigate|look(?:\s+into)?|share|pull|coordinate|help|analy[sz]e)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:[,:\-]\s*)?(?:i|we)\s+need\s+you\s+to\b", re.IGNORECASE),
    re.compile(r"^\s*(?:[,:\-]\s*)?need\s+you\s+to\b", re.IGNORECASE),
)
_GENERIC_REQUEST_PREFIXES = (
    "can you",
    "could you",
    "would you",
    "will you",
    "please",
    "need you to",
)


def collect_structured_offer_pairs(
    store: Any,
    existing_task_ids: set[str],
) -> set[tuple[str, str]]:
    """Collect non-mention offers created earlier in the current round."""
    pairs: set[tuple[str, str]] = set()
    for task in store.list_tasks():
        if task.task_id in existing_task_ids:
            continue
        if task.origin == "mention_compat":
            continue
        if task.status != "offered":
            continue
        if task.assigned_by and task.assigned_to:
            pairs.add((task.assigned_by, task.assigned_to))
    return pairs


def load_mention_aliases(db_path: str, agent_names: dict[int, str]) -> dict[str, str]:
    """Build a mention-token to display-name map from config and OASIS users."""
    aliases: dict[str, str] = {}

    for agent_id, display_name in agent_names.items():
        _register_aliases(aliases, display_name, agent_id=agent_id)

    if not os.path.exists(db_path):
        return aliases

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, name, user_name FROM user")
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error:
        return aliases

    for agent_id, name, user_name in rows:
        display_name = agent_names.get(agent_id) or name or user_name
        if not display_name:
            continue
        _register_aliases(
            aliases,
            str(display_name),
            raw_values=[name, user_name],
            agent_id=agent_id,
        )

    return aliases


def process_task_actions_for_round(
    *,
    actual_actions: list[dict[str, Any]],
    simulation_id: str,
    store: Any,
    platform: str,
    round_index: Optional[int],
    total_rounds: Optional[int] = None,
    mention_aliases: dict[str, str],
    structured_offer_pairs: Optional[set[tuple[str, str]]] = None,
) -> set[tuple[str, str]]:
    """Apply XML task actions and derive mention-based offers for one round."""
    lifecycle = TaskLifecycleService(simulation_id=simulation_id, store=store)
    normalized_platform = (platform or "unknown").strip().lower() or "unknown"
    round_offer_pairs = set(structured_offer_pairs or set())

    for action_data in actual_actions:
        content = str((action_data.get("action_args") or {}).get("content") or "")
        if not content.strip():
            continue

        actor_name = str(action_data.get("agent_name") or "unknown")
        parsed = parse_task_action(content)

        if parsed is not None:
            task_id = apply_task_action(
                parsed,
                agent_name=actor_name,
                simulation_id=simulation_id,
                store=store,
                round_index=round_index,
                total_rounds=total_rounds,
            )
            if parsed.action_type == "create" and task_id:
                task = store.get_task(task_id)
                if task is not None and task.assigned_by and task.assigned_to:
                    round_offer_pairs.add((task.assigned_by, task.assigned_to))

        if parsed is not None and parsed.action_type == "create":
            continue

        for mention_token, recipient_name in _extract_delegation_targets(
            content,
            actor_name=actor_name,
            mention_aliases=mention_aliases,
        ):
            pair = (actor_name, recipient_name)
            if pair in round_offer_pairs:
                continue

            action_args = action_data.get("action_args") or {}
            public_text = _normalize_space(strip_task_action(content))
            if not public_text:
                continue

            mention_context = {
                "platform": normalized_platform,
                "source_actor": actor_name,
                "source_action_type": action_data.get("action_type"),
                "mention_token": mention_token,
                "target_agent": recipient_name,
                "snippet": _build_snippet(public_text),
            }
            if action_data.get("trace_rowid") is not None:
                mention_context["trace_rowid"] = action_data["trace_rowid"]
            if action_args.get("post_id") is not None:
                mention_context["post_id"] = action_args["post_id"]
            if action_args.get("comment_id") is not None:
                mention_context["comment_id"] = action_args["comment_id"]

            origin_metadata = {
                "source": "public_mention",
                "platform": normalized_platform,
                "source_action_type": action_data.get("action_type"),
            }
            if action_data.get("trace_rowid") is not None:
                origin_metadata["trace_rowid"] = action_data["trace_rowid"]
            if action_args.get("post_id") is not None:
                origin_metadata["post_id"] = action_args["post_id"]
            if action_args.get("comment_id") is not None:
                origin_metadata["comment_id"] = action_args["comment_id"]

            try:
                task = lifecycle.offer_task(
                    title=_build_mention_offer_title(
                        actor_name, public_text, mention_token
                    ),
                    description=public_text,
                    assigned_to=recipient_name,
                    actor=actor_name,
                    origin="mention_compat",
                    origin_metadata=origin_metadata,
                    mention_context=mention_context,
                    created_round=round_index,
                    due_round=total_rounds,
                    round_budget=(
                        max(total_rounds - round_index, 0)
                        if round_index is not None and total_rounds is not None
                        else None
                    ),
                )
            except TaskLifecycleError as exc:
                logger.info(
                    "Mention-driven offer rejected (simulation=%s, actor=%s, recipient=%s): %s",
                    simulation_id,
                    actor_name,
                    recipient_name,
                    exc,
                )
                continue
            except Exception as exc:
                logger.warning(
                    "Mention-driven offer failed unexpectedly (simulation=%s, actor=%s, recipient=%s): %s",
                    simulation_id,
                    actor_name,
                    recipient_name,
                    exc,
                )
                continue

            logger.info(
                "Created mention-driven offer %s (%s -> %s)",
                task.issue_key,
                actor_name,
                recipient_name,
            )
            round_offer_pairs.add(pair)

    return round_offer_pairs


def expire_unfinished_tasks(
    *,
    simulation_id: str,
    store: Any,
    final_round: Optional[int],
    reason: Optional[str] = None,
) -> list[str]:
    """Expire any task that did not reach a terminal state before simulation end."""
    lifecycle = TaskLifecycleService(simulation_id=simulation_id, store=store)
    expired_issue_keys: list[str] = []

    if final_round is not None:
        default_reason = f"Simulation ended at round {final_round} before this task reached a terminal state."
    else:
        default_reason = "Simulation ended before this task reached a terminal state."

    for task in store.list_tasks():
        if task.status in TERMINAL_TASK_STATUSES:
            continue
        try:
            lifecycle.expire_task(
                task.issue_key,
                actor="system",
                reason=reason or default_reason,
                round_index=final_round,
            )
        except TaskLifecycleError as exc:
            logger.info(
                "Task expiry skipped (simulation=%s, task=%s): %s",
                simulation_id,
                task.issue_key,
                exc,
            )
            continue
        expired_issue_keys.append(task.issue_key)

    log_task_pipeline_metric(
        "expired_tasks",
        simulation_id=simulation_id,
        final_round=final_round,
        expired_count=len(expired_issue_keys),
        issue_keys=expired_issue_keys,
    )

    return expired_issue_keys


def _register_aliases(
    aliases: dict[str, str],
    display_name: str,
    *,
    raw_values: Optional[list[Any]] = None,
    agent_id: Optional[int] = None,
) -> None:
    candidates: list[str] = [display_name]
    candidates.extend([str(value) for value in raw_values or [] if value])
    if agent_id is not None:
        candidates.extend([str(agent_id), f"agent_{agent_id}"])

    for candidate in candidates:
        for alias in _derive_aliases(candidate):
            if alias in _GENERIC_MENTION_TOKENS:
                continue
            aliases.setdefault(alias, display_name)


def _derive_aliases(candidate: str) -> set[str]:
    normalized = _normalize_mention_token(candidate)
    if not normalized:
        return set()

    aliases = {normalized}
    aliases.add(normalized.replace(" ", ""))
    aliases.add(normalized.replace(" ", "_"))
    aliases.add(normalized.replace(" ", "-"))

    if normalized.startswith("user_"):
        aliases.add(normalized[5:])
    elif normalized.startswith("user"):
        suffix = normalized[4:]
        if suffix:
            aliases.add(suffix.lstrip("_"))

    return {alias for alias in aliases if alias}


def _normalize_mention_token(value: str) -> str:
    cleaned = str(value or "").strip().lstrip("@").lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9_.\- ]+", "", cleaned)
    return cleaned.strip(" ._-")


def _extract_delegation_targets(
    content: str,
    *,
    actor_name: str,
    mention_aliases: dict[str, str],
) -> list[tuple[str, str]]:
    public_text = _normalize_space(strip_task_action(content))
    if not public_text:
        return []

    matches = list(_MENTION_TOKEN_RE.finditer(public_text))
    if not matches:
        return []

    seen_recipients: set[str] = set()
    targets: list[tuple[str, str]] = []
    for match in matches:
        mention_token = match.group("handle")
        recipient_name = mention_aliases.get(_normalize_mention_token(mention_token))
        if not recipient_name or recipient_name == actor_name:
            continue
        if recipient_name in seen_recipients:
            continue
        if not _looks_like_delegation(public_text, match, matches):
            continue

        targets.append((mention_token, recipient_name))
        seen_recipients.add(recipient_name)

    return targets


def _looks_like_delegation(
    text: str,
    match: re.Match[str],
    matches: list[re.Match[str]],
) -> bool:
    local_after = _extract_local_after_window(text, match, matches)
    if any(pattern.search(local_after) for pattern in _REQUEST_AFTER_MENTION_PATTERNS):
        return True

    has_request = any(pattern.search(text) for pattern in _REQUEST_ANYWHERE_PATTERNS)
    if len(matches) == 1 and has_request:
        return True

    leading_handle = f"@{match.group('handle').lower()}"
    if text.lstrip().lower().startswith(leading_handle) and has_request:
        return True

    return False


def _extract_local_after_window(
    text: str,
    match: re.Match[str],
    matches: list[re.Match[str]],
) -> str:
    end_index = len(text)
    for delimiter in ".!?\n":
        candidate_index = text.find(delimiter, match.end())
        if candidate_index != -1:
            end_index = min(end_index, candidate_index)

    for other_match in matches:
        if other_match.start() > match.start():
            end_index = min(end_index, other_match.start())
            break

    return text[match.end() : end_index]


def _build_mention_offer_title(
    actor_name: str,
    public_text: str,
    mention_token: str,
) -> str:
    cleaned = _MENTION_REFERENCE_RE.sub("", public_text, count=1)
    cleaned = _normalize_space(cleaned).strip(" -:,.\t")
    if not cleaned:
        cleaned = f"Public request from {actor_name}"
    elif cleaned.lower().startswith(_GENERIC_REQUEST_PREFIXES):
        cleaned = f"Public request from {actor_name}: {cleaned}"

    if len(cleaned) > 96:
        cleaned = f"{cleaned[:93].rstrip()}..."
    return cleaned


def _build_snippet(text: str, limit: int = 220) -> str:
    normalized = _normalize_space(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
