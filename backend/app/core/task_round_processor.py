"""Helpers for processing task mutations from simulation round activity."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any, Optional

from ..config import Config
from .simulation_task_store import TERMINAL_TASK_STATUSES
from .task_context_injector import task_requires_agent_response
from .task_observability import log_task_pipeline_metric
from .task_action_parser import apply_task_action, parse_task_action, strip_task_action
from .task_lifecycle import (
    TaskLifecycleError,
    TaskLifecycleService,
    prepare_task_request_metadata,
)

logger = logging.getLogger(__name__)

_GENERIC_MENTION_TOKENS = {"all", "everyone", "everybody", "team"}
_AMBIGUOUS_MENTION_ALIAS = "__ambiguous_mention_alias__"
_MENTION_TOKEN_RE = re.compile(r"(?<!\w)@(?P<handle>[A-Za-z0-9_][A-Za-z0-9_.-]{0,63})")
_MENTION_REFERENCE_RE = re.compile(r"@[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
_ISSUE_KEY_REFERENCE_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-[1-9]\d*\b")
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
_NON_DELEGATION_STATUS_AFTER_MENTION_PATTERNS = (
    re.compile(
        r"^\s*(?:[,:\-]\s*)?(?:draft|brief|memo|summary|analysis|report|outline|plan|review)\s+(?:is|was|looks|seems|feels)\b",
        re.IGNORECASE,
    ),
)
_GENERIC_REQUEST_PREFIXES = (
    "can you",
    "could you",
    "would you",
    "will you",
    "please",
    "need you to",
)
_MEETING_ONLY_CUE_PATTERNS = (
    re.compile(
        r"\b(?:set\s+up|schedule|book|arrange)\s+(?:a\s+)?(?:meeting|sync|call|huddle|discussion)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:let'?s|lets)\s+(?:sync|align|chat|talk|connect)\b", re.IGNORECASE
    ),
    re.compile(r"\b(?:quick\s+)?(?:sync|call|huddle)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:touch\s+base|take\s+this\s+offline|discuss\s+live|hop\s+on\s+(?:a\s+)?call)\b",
        re.IGNORECASE,
    ),
)
_DELIVERABLE_CUE_PATTERNS = (
    re.compile(
        r"\b(?:brief|report|memo|analysis|summary|recommendation|plan|draft|artifact|deliverable)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:slides?|deck|spreadsheet|table|csv|json|doc|document|write\s+up|write-up)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:compare|evaluate|review|investigate|compile|prepare|publish|share\s+(?:a|the))\b",
        re.IGNORECASE,
    ),
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
    xml_compat_enabled = Config.task_xml_compat_enabled()
    normalized_platform = (platform or "unknown").strip().lower() or "unknown"
    round_offer_pairs = set(structured_offer_pairs or set())

    for action_data in actual_actions:
        content = str((action_data.get("action_args") or {}).get("content") or "")
        if not content.strip():
            continue

        actor_name = str(action_data.get("agent_name") or "unknown")
        public_text = _normalize_space(strip_task_action(content)) or None
        chat_context = _build_chat_context(
            action_data=action_data,
            actor_name=actor_name,
            platform=normalized_platform,
            public_text=public_text,
            round_index=round_index,
        )
        parsed_candidate = parse_task_action(content)
        parsed = parsed_candidate if xml_compat_enabled else None
        if parsed_candidate is not None and not xml_compat_enabled:
            log_task_pipeline_metric(
                "compat_path_blocked",
                simulation_id=simulation_id,
                source="xml_compat",
                action_type=parsed_candidate.action_type,
                actor=actor_name,
                platform=normalized_platform,
                reason="task_execution_mode_disables_xml_compat",
            )
        linked_task_refs: set[str] = set()

        if parsed is not None:
            task_id = apply_task_action(
                parsed,
                agent_name=actor_name,
                simulation_id=simulation_id,
                store=store,
                published_text=public_text,
                chat_context=chat_context,
                round_index=round_index,
                total_rounds=total_rounds,
            )
            if parsed.action_type == "create" and task_id:
                task = store.get_task(task_id)
                if task is not None and task.assigned_by and task.assigned_to:
                    round_offer_pairs.add((task.assigned_by, task.assigned_to))
                    linked_task_refs.add(task.issue_key)
            elif parsed.task_ref:
                task = store.get_task(parsed.task_ref)
                if task is not None:
                    linked_task_refs.add(task.issue_key)

        if parsed is not None and parsed.action_type == "create":
            continue

        delegation_targets, skipped_mentions = _extract_delegation_targets(
            content,
            actor_name=actor_name,
            mention_aliases=mention_aliases,
        )

        if public_text:
            for skipped in skipped_mentions:
                log_task_pipeline_metric(
                    "mention_offer_skipped",
                    simulation_id=simulation_id,
                    actor=actor_name,
                    mention_token=skipped.get("mention_token"),
                    reason=skipped.get("reason"),
                    platform=normalized_platform,
                    snippet=_build_snippet(public_text),
                )

        for (
            mention_token,
            recipient_name,
            task_request_text,
        ) in delegation_targets:
            pair = (actor_name, recipient_name)
            if pair in round_offer_pairs:
                continue

            action_args = action_data.get("action_args") or {}
            if not public_text:
                continue

            mention_context = {
                "platform": normalized_platform,
                "source_actor": actor_name,
                "source_action_type": action_data.get("action_type"),
                "mention_token": mention_token,
                "target_agent": recipient_name,
                "task_request": task_request_text,
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
                title = _build_mention_offer_title(actor_name, task_request_text)
                if _looks_like_meeting_only_request(task_request_text):
                    _queue_non_executable_offer_notification(
                        store=store,
                        recipient_name=recipient_name,
                        actor_name=actor_name,
                        public_text=task_request_text,
                        mention_context=mention_context,
                        round_index=round_index,
                    )
                    log_task_pipeline_metric(
                        "non_executable_offer_detected",
                        simulation_id=simulation_id,
                        actor=actor_name,
                        recipient=recipient_name,
                        platform=normalized_platform,
                        reason="meeting_only_request_requires_deliverable_rewrite",
                        snippet=mention_context.get("snippet"),
                    )
                    continue
                task_request_metadata = prepare_task_request_metadata(
                    title=title,
                    description=task_request_text,
                )
            except TaskLifecycleError as exc:
                _queue_non_executable_offer_notification(
                    store=store,
                    recipient_name=recipient_name,
                    actor_name=actor_name,
                    public_text=task_request_text,
                    mention_context=mention_context,
                    round_index=round_index,
                )
                log_task_pipeline_metric(
                    "non_executable_offer_detected",
                    simulation_id=simulation_id,
                    actor=actor_name,
                    recipient=recipient_name,
                    platform=normalized_platform,
                    reason=str(exc),
                    snippet=mention_context.get("snippet"),
                )
                continue

            try:
                next_round_due: Optional[int] = None
                next_round_budget: Optional[int] = None
                if round_index is not None:
                    next_round_due = round_index + 1
                    if total_rounds is not None:
                        next_round_due = min(next_round_due, total_rounds)
                    next_round_budget = max(next_round_due - round_index, 0)
                elif total_rounds is not None:
                    next_round_due = total_rounds

                task = lifecycle.offer_task(
                    title=title,
                    description=task_request_text,
                    assigned_to=recipient_name,
                    actor=actor_name,
                    origin="mention_compat",
                    origin_metadata=origin_metadata,
                    mention_context=mention_context,
                    created_round=round_index,
                    due_round=next_round_due,
                    round_budget=next_round_budget,
                    deliverable_type=task_request_metadata["deliverable_type"],
                    acceptance_criteria=task_request_metadata["acceptance_criteria"],
                    suggested_tools=task_request_metadata["suggested_tools"],
                    tool_plan=task_request_metadata["tool_plan"],
                    chat_refs=[chat_context] if chat_context else None,
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
            linked_task_refs.add(task.issue_key)

        if public_text:
            for issue_key in _extract_public_task_refs(public_text):
                if issue_key in linked_task_refs:
                    continue

                task = store.get_task(issue_key)
                if task is None:
                    continue
                if actor_name not in {task.assigned_by, task.assigned_to}:
                    continue

                if actor_name == task.assigned_to:
                    task = _progress_task_from_public_update(
                        lifecycle=lifecycle,
                        task=task,
                        actor_name=actor_name,
                        public_text=public_text,
                        round_index=round_index,
                        issue_key=issue_key,
                    )

                store.transition_task(
                    issue_key,
                    actor=actor_name,
                    note=public_text,
                    event_type="public_update",
                    event_details={"summary": public_text},
                    chat_refs=[chat_context] if chat_context else None,
                    round_index=round_index,
                )
                linked_task_refs.add(issue_key)

        if public_text and not linked_task_refs:
            implied_task = _infer_single_active_task_for_actor(
                store=store,
                actor_name=actor_name,
                current_round=round_index,
                total_rounds=total_rounds,
            )
            if implied_task is not None:
                updated = _progress_task_from_public_update(
                    lifecycle=lifecycle,
                    task=implied_task,
                    actor_name=actor_name,
                    public_text=public_text,
                    round_index=round_index,
                    issue_key=implied_task.issue_key,
                    chat_refs=[chat_context] if chat_context else None,
                    inferred_source="single_active_task_update",
                )
                if updated is not None:
                    linked_task_refs.add(updated.issue_key)

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
            existing = aliases.get(alias)
            if existing is None:
                aliases[alias] = display_name
                continue
            if existing != display_name:
                aliases[alias] = _AMBIGUOUS_MENTION_ALIAS


def _derive_aliases(candidate: str) -> set[str]:
    normalized = _normalize_mention_token(candidate)
    if not normalized:
        return set()

    aliases = {normalized}
    aliases.add(normalized.replace(" ", ""))
    aliases.add(normalized.replace(" ", "_"))
    aliases.add(normalized.replace(" ", "-"))

    # Add aliases for suffixed names such as finance_403 -> finance.
    suffix_trimmed = re.sub(r"[_.\-]?\d{2,}$", "", normalized).strip(" ._-")
    if suffix_trimmed and suffix_trimmed != normalized:
        aliases.add(suffix_trimmed)
        aliases.add(suffix_trimmed.replace(" ", ""))
        aliases.add(suffix_trimmed.replace(" ", "_"))
        aliases.add(suffix_trimmed.replace(" ", "-"))
        head_token = re.split(r"[\s_.\-]+", suffix_trimmed)[0].strip(" ._-")
        if head_token:
            aliases.add(head_token)

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
) -> tuple[list[tuple[str, str, str]], list[dict[str, str]]]:
    public_text = _normalize_space(strip_task_action(content))
    if not public_text:
        return [], []

    matches = list(_MENTION_TOKEN_RE.finditer(public_text))
    if not matches:
        return [], []

    seen_recipients: set[str] = set()
    targets: list[tuple[str, str, str]] = []
    skipped_mentions: list[dict[str, str]] = []
    for match in matches:
        mention_token = match.group("handle")
        normalized_mention = _normalize_mention_token(mention_token)
        recipient_name = mention_aliases.get(normalized_mention)

        if recipient_name == _AMBIGUOUS_MENTION_ALIAS:
            skipped_mentions.append(
                {
                    "mention_token": mention_token,
                    "reason": "ambiguous_alias",
                }
            )
            continue

        if not recipient_name:
            skipped_mentions.append(
                {
                    "mention_token": mention_token,
                    "reason": "unresolved_alias",
                }
            )
            continue

        if _is_self_reference(actor_name, recipient_name, mention_token):
            skipped_mentions.append(
                {
                    "mention_token": mention_token,
                    "reason": "self_mention",
                }
            )
            continue

        if recipient_name in seen_recipients:
            continue

        if not _looks_like_delegation(public_text, match, matches):
            skipped_mentions.append(
                {
                    "mention_token": mention_token,
                    "reason": "not_delegation_pattern",
                }
            )
            continue

        task_request_text = _derive_mention_task_request(public_text, match, matches)
        if not task_request_text:
            skipped_mentions.append(
                {
                    "mention_token": mention_token,
                    "reason": "empty_task_request",
                }
            )
            continue

        targets.append((mention_token, recipient_name, task_request_text))
        seen_recipients.add(recipient_name)

    return targets, skipped_mentions


def _is_self_reference(
    actor_name: str, recipient_name: str, mention_token: str
) -> bool:
    actor_candidates = _identity_candidates(actor_name)
    recipient_candidates = _identity_candidates(recipient_name)
    token_candidates = _identity_candidates(mention_token)
    return bool(actor_candidates & (recipient_candidates | token_candidates))


def _identity_candidates(value: str) -> set[str]:
    normalized = _normalize_mention_token(value)
    if not normalized:
        return set()

    candidates = {normalized}
    suffix_trimmed = re.sub(r"[_.\-]?\d{2,}$", "", normalized).strip(" ._-")
    if suffix_trimmed:
        candidates.add(suffix_trimmed)

    collapsed = suffix_trimmed.replace("_", " ").replace("-", " ").replace(".", " ")
    collapsed = _normalize_space(collapsed)
    if collapsed:
        candidates.add(collapsed.replace(" ", ""))
        first_token = collapsed.split(" ")[0]
        if first_token:
            candidates.add(first_token)

    return {candidate for candidate in candidates if candidate}


def _looks_like_delegation(
    text: str,
    match: re.Match[str],
    matches: list[re.Match[str]],
) -> bool:
    local_after = _extract_local_after_window(text, match, matches)
    if any(
        pattern.search(local_after)
        for pattern in _NON_DELEGATION_STATUS_AFTER_MENTION_PATTERNS
    ):
        return False
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
    task_request_text: str,
) -> str:
    cleaned = _normalize_space(task_request_text).strip(" -:,.\t")
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


def _derive_mention_task_request(
    public_text: str,
    match: re.Match[str],
    matches: list[re.Match[str]],
) -> str:
    request_text = _extract_local_after_window(public_text, match, matches)
    request_text = _normalize_space(request_text).strip(" -:,.\t")

    if not request_text:
        fallback = _MENTION_REFERENCE_RE.sub("", public_text)
        request_text = _normalize_space(fallback).strip(" -:,.\t")

    request_text = _strip_request_leadin(request_text)
    if not request_text:
        return ""

    if len(request_text) > 320:
        request_text = f"{request_text[:317].rstrip()}..."

    return request_text


def _strip_request_leadin(text: str) -> str:
    cleaned = _normalize_space(text).strip(" -:,.\t")
    if not cleaned:
        return ""

    leadin_patterns = (
        r"^(?:can|could|would|will)\s+you\s+",
        r"^please\s+",
        r"^(?:i|we)\s+need\s+you\s+to\s+",
        r"^need\s+you\s+to\s+",
    )
    for pattern in leadin_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip(" -:,.\t")


def _build_chat_context(
    *,
    action_data: dict[str, Any],
    actor_name: str,
    platform: str,
    public_text: Optional[str],
    round_index: Optional[int],
) -> Optional[dict[str, Any]]:
    if not public_text:
        return None

    action_args = action_data.get("action_args") or {}
    return {
        "platform": platform,
        "action_type": action_data.get("action_type"),
        "actor": actor_name,
        "trace_rowid": action_data.get("trace_rowid"),
        "post_id": action_args.get("post_id"),
        "comment_id": action_args.get("comment_id"),
        "snippet": _build_snippet(public_text),
        "round_index": round_index,
        "metadata": {
            "source_action_type": action_data.get("action_type"),
        },
    }


def _extract_public_task_refs(text: str) -> list[str]:
    issue_keys: list[str] = []
    seen: set[str] = set()
    for match in _ISSUE_KEY_REFERENCE_RE.finditer(text or ""):
        issue_key = match.group(0)
        if issue_key in seen:
            continue
        issue_keys.append(issue_key)
        seen.add(issue_key)
    return issue_keys


def _queue_non_executable_offer_notification(
    *,
    store: Any,
    recipient_name: str,
    actor_name: str,
    public_text: str,
    mention_context: dict[str, Any],
    round_index: Optional[int],
) -> None:
    queue_notification = getattr(store, "queue_notification", None)
    if not callable(queue_notification):
        return

    snippet = mention_context.get("snippet") or _build_snippet(public_text)
    queue_notification(
        recipient=recipient_name,
        message=(
            f"[Task Rewrite Needed] {actor_name} asked you for work that sounds like off-screen coordination rather than an executable deliverable.\n"
            f"Public context: {snippet}\n"
            "Reply in public by declining it or rewriting it into a concrete brief, memo, analysis, summary, comparison, or report section."
        ),
        category="task_rewrite_needed",
        created_by=actor_name,
        event_type="rewrite_requested",
        round_index=round_index,
        metadata={
            "mention_context": dict(mention_context),
            "public_text": public_text,
        },
    )


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _looks_like_meeting_only_request(text: str) -> bool:
    normalized = _normalize_space(text)
    if not normalized:
        return False

    has_meeting_cue = any(
        pattern.search(normalized) for pattern in _MEETING_ONLY_CUE_PATTERNS
    )
    if not has_meeting_cue:
        return False

    has_deliverable_cue = any(
        pattern.search(normalized) for pattern in _DELIVERABLE_CUE_PATTERNS
    )
    return not has_deliverable_cue


def _progress_task_from_public_update(
    *,
    lifecycle: TaskLifecycleService,
    task: Any,
    actor_name: str,
    public_text: str,
    round_index: Optional[int],
    issue_key: str,
    chat_refs: Optional[list[dict[str, Any]]] = None,
    inferred_source: str = "public_issue_key_update",
) -> Any:
    """Infer lifecycle progress from assignee public updates that cite a task."""
    try:
        if task.status == "offered":
            task = lifecycle.accept_task(
                issue_key,
                actor=actor_name,
                reason="Implicit acceptance inferred from public task update.",
                round_index=round_index,
                event_details={"source": inferred_source, "inferred": True},
                chat_refs=chat_refs,
            )

        if task.status == "open":
            task = lifecycle.start_task(
                issue_key,
                actor=actor_name,
                reason="Implicit start inferred from public task update.",
                round_index=round_index,
                event_details={"source": inferred_source, "inferred": True},
                chat_refs=chat_refs,
            )

        # Completion is never inferred from free-form text cues.
        # A task reaches terminal state only through explicit lifecycle actions.
    except TaskLifecycleError as exc:
        logger.debug(
            "Public task update could not infer lifecycle transition (task=%s, actor=%s): %s",
            issue_key,
            actor_name,
            exc,
        )

    refreshed = lifecycle.get_task(issue_key)
    return refreshed or task


def _infer_single_active_task_for_actor(
    *,
    store: Any,
    actor_name: str,
    current_round: Optional[int],
    total_rounds: Optional[int],
) -> Any | None:
    candidate_tasks = [
        task
        for task in store.list_tasks(assigned_to=actor_name)
        if task_requires_agent_response(
            task,
            current_round=current_round,
            total_rounds=total_rounds,
        )
    ]
    if len(candidate_tasks) != 1:
        return None
    return candidate_tasks[0]
