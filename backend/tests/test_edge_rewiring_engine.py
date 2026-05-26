"""Unit tests for EdgeRewiringEngine and RewiringConfig."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.services.communication_topology import CommunicationTopology
from app.services.edge_rewiring_engine import EdgeRewiringEngine, RewiringConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeActivity:
    """Minimal stand-in for AgentActivity."""

    agent_name: str
    action_type: str
    action_args: Dict[str, Any]
    round_num: int


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agents():
    return ["alice", "bob", "carol"]


@pytest.fixture
def topo(agents):
    return CommunicationTopology(agents)


@pytest.fixture
def config():
    return RewiringConfig()


@pytest.fixture
def engine(topo, config, tmp_path):
    return EdgeRewiringEngine(topology=topo, config=config, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# Initialization & Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_init_default_config(self, topo):
        engine = EdgeRewiringEngine(topology=topo, config=RewiringConfig())
        assert engine.config.decay_lambda == 0.95
        assert engine.config.prune_threshold == 0.05
        assert engine.config.snapshot_interval == 5

    def test_from_config_classmethod(self):
        """RewiringConfig.from_config() loads from Config attributes."""
        mock_config = type("MockConfig", (), {
            "TOPOLOGY_DECAY_LAMBDA": 0.8,
            "TOPOLOGY_PRUNE_THRESHOLD": 0.1,
            "TOPOLOGY_SNAPSHOT_INTERVAL": 10,
            "TOPOLOGY_WEIGHT_COMMENT": 2.0,
            "TOPOLOGY_WEIGHT_QUOTE": 1.5,
            "TOPOLOGY_WEIGHT_REPOST": 1.0,
            "TOPOLOGY_WEIGHT_FOLLOW": 0.7,
            "TOPOLOGY_WEIGHT_LIKE": 0.4,
            "TOPOLOGY_WEIGHT_DISLIKE": 0.4,
            "TOPOLOGY_WEIGHT_MUTE": -1.0,
        })()
        with patch("app.config.Config", mock_config):
            cfg = RewiringConfig.from_config()
            assert cfg.decay_lambda == 0.8
            assert cfg.snapshot_interval == 10
            assert cfg.weight_comment == 2.0
            assert cfg.weight_mute == -1.0


# ---------------------------------------------------------------------------
# Activity processing
# ---------------------------------------------------------------------------


class TestProcessActivity:
    def test_process_comment_action(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        edge = engine.topology.get_edge("alice", "bob")
        assert edge is not None
        assert edge.weight == pytest.approx(1.0), "CREATE_COMMENT weight should be 1.0"

    def test_process_like_action(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="LIKE_POST",
            action_args={"post_author_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        edge = engine.topology.get_edge("alice", "bob")
        assert edge.weight == pytest.approx(0.3), "LIKE_POST weight should be 0.3"

    def test_process_follow_action(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="FOLLOW",
            action_args={"target_user_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        edge = engine.topology.get_edge("alice", "bob")
        assert edge.weight == pytest.approx(0.5), "FOLLOW weight should be 0.5"

    def test_process_mute_action(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="MUTE",
            action_args={"target_user_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        edge = engine.topology.get_edge("alice", "bob")
        assert edge.weight == pytest.approx(-0.5), "MUTE weight should be -0.5"

    def test_process_create_post_no_edge(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_POST",
            action_args={"content": "Hello world"},
            round_num=1,
        )
        engine.process_activity(activity)
        assert engine.topology.edge_count() == 0, "CREATE_POST should not create edges"

    def test_process_unknown_target_skipped(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "unknown_user"},
            round_num=1,
        )
        engine.process_activity(activity)
        assert engine.topology.edge_count() == 0, "Unknown target should be skipped"

    def test_process_activity_from_dict(self, engine):
        action_data = {
            "agent_name": "alice",
            "action_type": "CREATE_COMMENT",
            "action_args": {"post_author_name": "bob"},
            "round_num": 1,
        }
        engine.process_activity_from_dict(action_data, platform="twitter")
        edge = engine.topology.get_edge("alice", "bob")
        assert edge is not None
        assert edge.weight == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Round and window management
# ---------------------------------------------------------------------------


class TestRoundManagement:
    def test_end_round_applies_decay(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        engine.end_round(round_num=1)
        edge = engine.topology.get_edge("alice", "bob")
        assert edge.weight == pytest.approx(1.0 * 0.95), "Weight should be decayed"

    def test_end_round_applies_pruning(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        # Set weight just below prune threshold
        engine.topology.get_edge("alice", "bob").weight = 0.04
        engine.end_round(round_num=1)
        assert engine.topology.get_edge("alice", "bob") is None, "Low-weight edge should be pruned"

    def test_window_boundary_triggers_snapshot(self, engine, tmp_path):
        """After snapshot_interval rounds, a snapshot file is produced."""
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=0,
        )
        engine.process_activity(activity)

        # Default snapshot_interval is 5; boundary triggers when
        # (round_num - window_start) >= 5, so we need round_num=5
        for r in range(1, 7):
            # Re-add weight each round so edge doesn't get pruned by decay
            engine.process_activity(FakeActivity(
                agent_name="alice",
                action_type="CREATE_COMMENT",
                action_args={"post_author_name": "bob"},
                round_num=r,
            ))
            engine.end_round(round_num=r)

        files = list(tmp_path.glob("*.json"))
        assert len(files) >= 1, "A snapshot file should be produced at window boundary"

    def test_finalize_produces_final_snapshot(self, engine, tmp_path):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=0,
        )
        engine.process_activity(activity)
        engine.end_round(round_num=1)
        stats = engine.finalize()
        files = list(tmp_path.glob("*.json"))
        assert len(files) >= 1, "finalize() should produce a snapshot"
        assert "actions_processed" in stats

    def test_get_stats(self, engine):
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=1,
        )
        engine.process_activity(activity)
        stats = engine.get_stats()
        assert stats["actions_processed"] == 1
        assert stats["edge_count"] == 1
        assert stats["agent_count"] == 3

    def test_multiple_rounds_weight_evolution(self, engine):
        """Simulate 10 rounds with an initial action, verify decay accumulates."""
        activity = FakeActivity(
            agent_name="alice",
            action_type="CREATE_COMMENT",
            action_args={"post_author_name": "bob"},
            round_num=0,
        )
        engine.process_activity(activity)
        initial_weight = 1.0

        for r in range(1, 11):
            engine.end_round(round_num=r)

        edge = engine.topology.get_edge("alice", "bob")
        if edge is not None:
            # After 10 rounds of 0.95 decay: 1.0 * 0.95^10 ≈ 0.5987
            expected = initial_weight * (0.95 ** 10)
            assert edge.weight == pytest.approx(expected, rel=1e-3)
        else:
            # Edge may have been pruned — that's valid behavior
            expected = initial_weight * (0.95 ** 10)
            assert expected < engine.config.prune_threshold


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestExtractTarget:
    def test_extract_target_agent_all_types(self, engine):
        """Verify _extract_target_agent for each action type."""
        cases = [
            ("CREATE_COMMENT", {"post_author_name": "bob"}, "bob"),
            ("CREATE_COMMENT", {"parent_comment_author_name": "carol"}, "carol"),
            ("QUOTE_POST", {"original_author_name": "bob"}, "bob"),
            ("LIKE_POST", {"post_author_name": "carol"}, "carol"),
            ("FOLLOW", {"target_user_name": "bob"}, "bob"),
            ("MUTE", {"target_user_name": "carol"}, "carol"),
            ("REPOST", {"original_author_name": "bob"}, "bob"),
            ("CREATE_POST", {"content": "hello"}, None),
            ("SEARCH_POSTS", {"query": "test"}, None),
        ]
        for action_type, action_args, expected in cases:
            result = engine._extract_target_agent(action_type, action_args)
            assert result == expected, f"Failed for {action_type}: got {result}, expected {expected}"
