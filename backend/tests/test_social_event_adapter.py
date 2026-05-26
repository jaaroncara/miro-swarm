"""Unit tests for the social_event_adapter module."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.services.topology_analysis.social_event_adapter import (
    convert_action_log,
    load_social_events_from_jsonl,
    oasis_action_to_coordination_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    action_type: str,
    agent_name: str = "alice",
    round_num: int = 1,
    timestamp: str = "2024-01-01T00:00:00",
    **action_args,
) -> dict:
    """Create a minimal action dict."""
    return {
        "action_type": action_type,
        "agent_name": agent_name,
        "round_num": round_num,
        "timestamp": timestamp,
        "platform": "twitter",
        "action_args": action_args,
    }


# ---------------------------------------------------------------------------
# Event type mapping
# ---------------------------------------------------------------------------


class TestEventTypeMapping:
    def test_create_comment_maps_to_task_handoff(self):
        action = _make_action("CREATE_COMMENT", post_author_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event is not None
        assert event.event_type == "task_handoff"

    def test_create_post_maps_to_task_created(self):
        action = _make_action("CREATE_POST", content="Hello world")
        event = oasis_action_to_coordination_event(action)
        assert event is not None
        assert event.event_type == "task_created"

    def test_quote_post_maps_to_task_referenced(self):
        action = _make_action("QUOTE_POST", original_author_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event is not None
        assert event.event_type == "task_referenced"

    def test_follow_maps_to_relationship_established(self):
        action = _make_action("FOLLOW", target_user_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event is not None
        assert event.event_type == "relationship_established"

    def test_like_maps_to_feedback_given(self):
        action = _make_action("LIKE_POST", post_author_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event is not None
        assert event.event_type == "feedback_given"

    def test_mute_maps_to_relationship_severed(self):
        action = _make_action("MUTE", target_user_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event is not None
        assert event.event_type == "relationship_severed"

    def test_search_returns_none(self):
        action = _make_action("SEARCH_POSTS", query="test")
        event = oasis_action_to_coordination_event(action)
        assert event is None, "SEARCH_POSTS should not produce a coordination event"


# ---------------------------------------------------------------------------
# Event details
# ---------------------------------------------------------------------------


class TestEventDetails:
    def test_details_includes_source_marker(self):
        action = _make_action("CREATE_COMMENT", post_author_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event.details["source"] == "oasis_social"

    def test_target_agent_extracted(self):
        action = _make_action("CREATE_COMMENT", post_author_name="bob")
        event = oasis_action_to_coordination_event(action)
        assert event.details["target_agent"] == "bob"


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------


class TestBatchConversion:
    def test_convert_action_log_batch(self):
        actions = [
            _make_action("CREATE_COMMENT", agent_name="alice", timestamp="2024-01-01T00:02:00", post_author_name="bob"),
            _make_action("SEARCH_POSTS", agent_name="bob", timestamp="2024-01-01T00:01:00", query="test"),
            _make_action("LIKE_POST", agent_name="carol", timestamp="2024-01-01T00:00:00", post_author_name="alice"),
        ]
        events = convert_action_log(actions)
        # SEARCH_POSTS should be filtered out
        assert len(events) == 2, "Should filter out unmapped actions"
        # Should be sorted by timestamp
        assert events[0].timestamp <= events[1].timestamp, "Events should be sorted by timestamp"


# ---------------------------------------------------------------------------
# JSONL loading
# ---------------------------------------------------------------------------


class TestLoadFromJsonl:
    def test_load_social_events_from_jsonl(self, tmp_path):
        """Reads JSONL file, skips system events."""
        jsonl_file = tmp_path / "actions.jsonl"
        lines = [
            json.dumps({"event_type": "round_start", "round_num": 1}),
            json.dumps({
                "action_type": "CREATE_COMMENT",
                "agent_name": "alice",
                "round_num": 1,
                "timestamp": "2024-01-01T00:00:00",
                "platform": "twitter",
                "action_args": {"post_author_name": "bob"},
            }),
            json.dumps({"event_type": "simulation_complete"}),
            json.dumps({
                "action_type": "LIKE_POST",
                "agent_name": "bob",
                "round_num": 1,
                "timestamp": "2024-01-01T00:01:00",
                "platform": "twitter",
                "action_args": {"post_author_name": "alice"},
            }),
        ]
        jsonl_file.write_text("\n".join(lines))

        events = load_social_events_from_jsonl(jsonl_file)
        # 2 system events skipped, 2 social events converted
        assert len(events) == 2
        assert all(e.details["source"] == "oasis_social" for e in events)


# ---------------------------------------------------------------------------
# Task ID consistency
# ---------------------------------------------------------------------------


class TestTaskIdConsistency:
    def test_consistent_task_id_for_related_events(self):
        """A post and its comment share task_id when referencing the same post_id."""
        post_action = _make_action(
            "CREATE_POST",
            agent_name="alice",
            round_num=1,
            post_id="post_123",
        )
        comment_action = _make_action(
            "CREATE_COMMENT",
            agent_name="bob",
            round_num=2,
            parent_post_id="post_123",
            post_author_name="alice",
        )
        post_event = oasis_action_to_coordination_event(post_action)
        comment_event = oasis_action_to_coordination_event(comment_action)

        assert post_event is not None
        assert comment_event is not None
        assert post_event.task_id == comment_event.task_id, (
            "Post and its comment should share task_id via post_id"
        )
