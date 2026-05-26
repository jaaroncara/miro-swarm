"""Integration tests for the full topology evolution pipeline.

Validates end-to-end data flow across:
  - CommunicationTopology (node/edge lifecycle)
  - EdgeRewiringEngine (decay, pruning, windowed snapshots)
  - Social event adapter (OASIS action → CoordinationEvent)
  - Graph module (load_precomputed_snapshots, load_snapshot_from_json)

No external dependencies (no LLM, no DB, no network).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict

import numpy as np
import numpy.testing as npt
import pytest
import scipy.sparse

from app.services.communication_topology import CommunicationTopology
from app.services.edge_rewiring_engine import EdgeRewiringEngine, RewiringConfig
from app.services.topology_analysis.social_event_adapter import (
    convert_action_log,
    oasis_action_to_coordination_event,
)
from app.services.topology_analysis.graph import (
    TopologySnapshot,
    load_precomputed_snapshots,
    load_snapshot_from_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_action(
    agent_name: str,
    action_type: str,
    round_num: int,
    **action_args: Any,
) -> Dict[str, Any]:
    """Create a synthetic OASIS action dict."""
    return {
        "agent_name": agent_name,
        "agent_id": 0,
        "action_type": action_type,
        "round_num": round_num,
        "timestamp": f"2024-01-01T00:{round_num:02d}:00",
        "action_args": action_args,
        "platform": "twitter",
        "success": True,
    }


def make_comment_action(source: str, target: str, round_num: int) -> Dict[str, Any]:
    """Shorthand for a CREATE_COMMENT action."""
    return make_action(source, "CREATE_COMMENT", round_num, post_author_name=target)


def make_like_action(source: str, target: str, round_num: int) -> Dict[str, Any]:
    """Shorthand for a LIKE_POST action."""
    return make_action(source, "LIKE_POST", round_num, post_author_name=target)


def make_follow_action(source: str, target: str, round_num: int) -> Dict[str, Any]:
    """Shorthand for a FOLLOW action."""
    return make_action(source, "FOLLOW", round_num, target_user_name=target)


def make_quote_action(source: str, target: str, round_num: int) -> Dict[str, Any]:
    """Shorthand for a QUOTE_POST action."""
    return make_action(source, "QUOTE_POST", round_num, original_author_name=target)


def make_mute_action(source: str, target: str, round_num: int) -> Dict[str, Any]:
    """Shorthand for a MUTE action."""
    return make_action(source, "MUTE", round_num, target_user_name=target)


def _write_snapshot_json(
    output_dir: Path,
    window_id: int,
    agent_ids: list[str],
    directed_edges: list[tuple[int, int, float]],
) -> Path:
    """Write a synthetic snapshot JSON file matching CommunicationTopology format."""
    n = len(agent_ids)
    rows = [e[0] for e in directed_edges]
    cols = [e[1] for e in directed_edges]
    data = [e[2] for e in directed_edges]

    # Build symmetric via max(w_ij, w_ji)
    sym_map: Dict[tuple[int, int], float] = {}
    for r, c, d in directed_edges:
        key = (min(r, c), max(r, c))
        sym_map[key] = max(sym_map.get(key, 0.0), d)

    sym_rows = [k[0] for k in sym_map] + [k[1] for k in sym_map if k[0] != k[1]]
    sym_cols = [k[1] for k in sym_map] + [k[0] for k in sym_map if k[0] != k[1]]
    sym_data = list(sym_map.values()) + [v for k, v in sym_map.items() if k[0] != k[1]]

    snapshot = {
        "window_id": window_id,
        "round_start": window_id * 5,
        "round_end": (window_id + 1) * 5,
        "agent_ids": agent_ids,
        "agent_types": {aid: "agent" for aid in agent_ids},
        "adjacency_directed": {
            "rows": rows,
            "cols": cols,
            "data": data,
            "shape": [n, n],
        },
        "adjacency_symmetric": {
            "rows": sym_rows,
            "cols": sym_cols,
            "data": sym_data,
            "shape": [n, n],
        },
        "metrics": {
            "edge_count": len(directed_edges),
            "mean_weight": float(np.mean(data)) if data else 0.0,
            "max_weight": float(np.max(data)) if data else 0.0,
            "density": len(directed_edges) / (n * (n - 1)) if n > 1 else 0.0,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"window_{window_id:03d}.json"
    filepath.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEndToEndTopologyEvolution:
    """Simulate a complete scenario: 3 agents, 5 rounds, known interactions."""

    AGENTS = ["Alice", "Bob", "Charlie"]

    def _build_round_actions(self) -> list[list[Dict[str, Any]]]:
        """Return actions per round matching the specification."""
        return [
            # Round 1: Alice→Bob (comment), Charlie→Bob (like)
            [
                make_comment_action("Alice", "Bob", 1),
                make_like_action("Charlie", "Bob", 1),
            ],
            # Round 2: Bob→Alice (comment), Charlie→Alice (comment)
            [
                make_comment_action("Bob", "Alice", 2),
                make_comment_action("Charlie", "Alice", 2),
            ],
            # Round 3: Alice→Charlie (follow), Bob→Charlie (like)
            [
                make_follow_action("Alice", "Charlie", 3),
                make_like_action("Bob", "Charlie", 3),
            ],
            # Round 4: Charlie→Alice (quote), Bob mutes Charlie
            [
                make_quote_action("Charlie", "Alice", 4),
                make_mute_action("Bob", "Charlie", 4),
            ],
            # Round 5: Alice→Charlie (comment), Bob→Alice (comment)
            [
                make_comment_action("Alice", "Charlie", 5),
                make_comment_action("Bob", "Alice", 5),
            ],
        ]

    def test_end_to_end_topology_evolution(self, tmp_path: Path) -> None:
        """Full 5-round simulation produces correct topology structure."""
        config = RewiringConfig(
            decay_lambda=0.9,
            prune_threshold=0.01,
            snapshot_interval=5,
        )
        topology = CommunicationTopology(self.AGENTS)
        engine = EdgeRewiringEngine(topology, config=config, output_dir=tmp_path)

        rounds = self._build_round_actions()
        for round_num, actions in enumerate(rounds, start=1):
            for action in actions:
                engine.process_activity_from_dict(action, platform="twitter")
            engine.end_round(round_num)

        stats = engine.finalize()

        # --- Assertions ---

        # Node count remains fixed at 3 throughout
        assert len(topology.agent_ids) == 3

        # All 3 agent names preserved
        assert set(topology.agent_ids) == set(self.AGENTS)

        # Edges were created (at least some survived decay/prune)
        assert topology.edge_count() > 0

        # Actions processed = 10 total bilateral actions
        assert stats["actions_processed"] == 10

        # At least one snapshot was produced (interval=5, 5 rounds → boundary hit)
        assert stats["snapshots_produced"] >= 1

        # Adjacency matrix shape is (3, 3)
        adj = topology.to_adjacency_matrix()
        assert adj.shape == (3, 3)

        # No self-loops (diagonal should be zero)
        npt.assert_array_equal(adj.diagonal(), np.zeros(3))

        # Alice→Bob edge should exist (created round 1, comment weight=1.0)
        alice_idx = topology._id_to_index["Alice"]
        bob_idx = topology._id_to_index["Bob"]
        # Weight decayed over rounds but should still be > 0
        assert adj[alice_idx, bob_idx] > 0

        # Snapshot file(s) written to tmp_path
        snapshot_files = list(tmp_path.glob("window_*.json"))
        assert len(snapshot_files) >= 1

    def test_weights_increase_with_interactions(self) -> None:
        """Multiple interactions between same pair increase edge weight."""
        topology = CommunicationTopology(["A", "B"])
        topology.update_edge("A", "B", 1.0, "CREATE_COMMENT", round_num=1)
        topology.update_edge("A", "B", 1.0, "CREATE_COMMENT", round_num=2)

        edge = topology.get_edge("A", "B")
        assert edge is not None
        assert edge.weight == 2.0
        assert edge.interaction_count == 2

    def test_decay_reduces_weights(self) -> None:
        """Decay multiplicatively reduces all edge weights."""
        topology = CommunicationTopology(["A", "B"])
        topology.update_edge("A", "B", 1.0, "CREATE_COMMENT", round_num=1)
        topology.apply_decay(0.5)

        edge = topology.get_edge("A", "B")
        assert edge is not None
        npt.assert_almost_equal(edge.weight, 0.5)


class TestSnapshotRoundTrip:
    """Save a snapshot to disk and reload it, verifying data integrity."""

    def test_snapshot_round_trip(self, tmp_path: Path) -> None:
        """Snapshot save → load preserves agent_ids, matrix shape, and values."""
        agents = ["Agent_A", "Agent_B", "Agent_C"]
        topology = CommunicationTopology(agents)

        # Apply several interactions
        topology.update_edge("Agent_A", "Agent_B", 1.5, "CREATE_COMMENT", round_num=1)
        topology.update_edge("Agent_B", "Agent_C", 0.8, "LIKE_POST", round_num=1)
        topology.update_edge("Agent_C", "Agent_A", 1.2, "QUOTE_POST", round_num=2)

        # Save snapshot
        topology.save_snapshot(tmp_path, window_id=0, round_start=0, round_end=2)

        # Load via load_precomputed_snapshots
        snapshots = load_precomputed_snapshots(tmp_path)
        assert len(snapshots) == 1

        snap = snapshots[0]

        # Verify agent_ids
        assert snap.agent_ids == agents

        # Verify adjacency matrix shape
        assert snap.adjacency.shape == (3, 3)
        assert snap.adjacency_symmetric.shape == (3, 3)

        # Verify specific values survived the round-trip
        original_directed = topology.to_adjacency_matrix()
        loaded_directed = snap.adjacency

        npt.assert_array_almost_equal(
            original_directed.toarray(),
            loaded_directed.toarray(),
            decimal=10,
        )

        # Symmetric matrix should be symmetric
        sym_arr = snap.adjacency_symmetric.toarray()
        npt.assert_array_almost_equal(sym_arr, sym_arr.T, decimal=10)


class TestPipelineWithPrecomputedSnapshots:
    """Load synthetic pre-computed snapshots and validate structure."""

    def test_load_multiple_snapshots(self, tmp_path: Path) -> None:
        """Directory with 3 window JSON files produces 3 valid snapshots."""
        agents = ["X", "Y", "Z"]

        _write_snapshot_json(tmp_path, 0, agents, [(0, 1, 1.0), (1, 2, 0.5)])
        _write_snapshot_json(tmp_path, 1, agents, [(0, 2, 0.8), (2, 0, 1.2)])
        _write_snapshot_json(tmp_path, 2, agents, [(1, 0, 0.3)])

        snapshots = load_precomputed_snapshots(tmp_path)

        assert len(snapshots) == 3

        # Ordered by window_id
        assert [s.window_id for s in snapshots] == [0, 1, 2]

        # Each has valid sparse matrices
        for snap in snapshots:
            assert isinstance(snap.adjacency, scipy.sparse.spmatrix)
            assert isinstance(snap.adjacency_symmetric, scipy.sparse.spmatrix)
            assert snap.adjacency.shape == (3, 3)
            assert snap.agent_ids == agents

    def test_load_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty list (no crash)."""
        tmp_path.mkdir(exist_ok=True)
        snapshots = load_precomputed_snapshots(tmp_path)
        assert snapshots == []


class TestSocialAdapterToPipelineFlow:
    """Convert synthetic OASIS actions to CoordinationEvents."""

    def test_convert_action_log_produces_events(self) -> None:
        """Valid social actions convert to properly structured events."""
        actions = [
            make_comment_action("Alice", "Bob", 1),
            make_like_action("Bob", "Alice", 2),
            make_follow_action("Charlie", "Alice", 3),
            make_quote_action("Alice", "Charlie", 4),
        ]

        events = convert_action_log(actions)

        assert len(events) == 4

        # All events have actor and round_index populated
        for event in events:
            assert event.actor != ""
            assert event.round_index is not None
            assert event.round_index >= 1

        # Verify first event maps correctly
        assert events[0].actor == "Alice"
        assert events[0].round_index == 1
        assert events[0].event_type == "task_handoff"  # CREATE_COMMENT maps to handoff

    def test_unmapped_actions_are_filtered(self) -> None:
        """Actions without a mapping (e.g., SEARCH_POSTS) are excluded."""
        actions = [
            make_action("Alice", "SEARCH_POSTS", 1, query="trending"),
            make_action("Bob", "CREATE_POST", 1, content="Hello world"),
            make_comment_action("Alice", "Bob", 2),
        ]

        events = convert_action_log(actions)

        # SEARCH_POSTS has no mapping → filtered out
        # CREATE_POST maps to task_created
        # CREATE_COMMENT maps to task_handoff
        assert len(events) == 2

    def test_single_action_conversion(self) -> None:
        """Individual action converts to event with correct details."""
        action = make_mute_action("Alice", "Bob", 5)
        event = oasis_action_to_coordination_event(action)

        assert event is not None
        assert event.actor == "Alice"
        assert event.round_index == 5
        assert event.event_type == "relationship_severed"
        assert event.details["target_agent"] == "Bob"
        assert event.details["action_type"] == "MUTE"


class TestRewiringEngineFullSimulation:
    """EdgeRewiringEngine with snapshot_interval=2, 6 rounds → 3 snapshots."""

    def test_rewiring_engine_produces_snapshots(self, tmp_path: Path) -> None:
        """6 rounds with interval=2 produce 3 snapshot files."""
        agents = ["Alpha", "Beta", "Gamma"]
        config = RewiringConfig(
            decay_lambda=0.95,
            prune_threshold=0.01,
            snapshot_interval=2,
        )
        topology = CommunicationTopology(agents)
        engine = EdgeRewiringEngine(topology, config=config, output_dir=tmp_path)

        # Feed 6 rounds of actions
        round_actions = [
            [make_comment_action("Alpha", "Beta", 1)],
            [make_like_action("Beta", "Gamma", 2), make_comment_action("Gamma", "Alpha", 2)],
            [make_follow_action("Alpha", "Gamma", 3)],
            [make_quote_action("Beta", "Alpha", 4)],
            [make_comment_action("Gamma", "Beta", 5), make_like_action("Alpha", "Beta", 5)],
            [make_mute_action("Gamma", "Alpha", 6)],
        ]

        for round_num, actions in enumerate(round_actions, start=1):
            for action in actions:
                engine.process_activity_from_dict(action, platform="twitter")
            engine.end_round(round_num)

        stats = engine.finalize()

        # 3 snapshots from interval=2 over 6 rounds
        assert stats["snapshots_produced"] == 3

        # Verify snapshot files on disk
        snapshot_files = sorted(tmp_path.glob("window_*.json"))
        assert len(snapshot_files) == 3

        # Verify actions_processed count (8 bilateral actions total)
        assert stats["actions_processed"] == 8

        # Edge weights reflect interactions minus decay
        # Alpha→Beta had interactions in round 1 and 5; should have positive weight
        edge_ab = topology.get_edge("Alpha", "Beta")
        assert edge_ab is not None
        assert edge_ab.weight > 0

    def test_stats_track_correctly(self, tmp_path: Path) -> None:
        """Engine stats reflect actions and snapshots accurately."""
        agents = ["A", "B"]
        config = RewiringConfig(decay_lambda=1.0, prune_threshold=0.0, snapshot_interval=1)
        topology = CommunicationTopology(agents)
        engine = EdgeRewiringEngine(topology, config=config, output_dir=tmp_path)

        engine.process_activity_from_dict(
            make_comment_action("A", "B", 1), platform="twitter"
        )
        engine.end_round(1)

        stats = engine.get_stats()
        assert stats["actions_processed"] == 1
        assert stats["snapshots_produced"] == 1
        assert stats["agent_count"] == 2


class TestBackwardCompatibilityNoPrecomputed:
    """Pipeline gracefully handles missing pre-computed snapshots."""

    def test_nonexistent_directory_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent directory returns empty list without error."""
        fake_dir = tmp_path / "does_not_exist"
        result = load_precomputed_snapshots(fake_dir)
        assert result == []

    def test_directory_with_no_matching_files(self, tmp_path: Path) -> None:
        """Directory exists but has no window_*.json files → empty list."""
        (tmp_path / "unrelated.txt").write_text("hello")
        result = load_precomputed_snapshots(tmp_path)
        assert result == []

    def test_directory_with_malformed_json(self, tmp_path: Path) -> None:
        """Malformed JSON files are skipped gracefully."""
        bad_file = tmp_path / "window_000.json"
        bad_file.write_text("{invalid json content", encoding="utf-8")

        result = load_precomputed_snapshots(tmp_path)
        assert result == []


class TestNodeCountInvariant:
    """Node count must remain constant regardless of interactions."""

    def test_node_count_invariant_under_random_interactions(self, tmp_path: Path) -> None:
        """5 agents, 20 rounds of random interactions — node count always 5."""
        agents = ["Agent_0", "Agent_1", "Agent_2", "Agent_3", "Agent_4"]
        config = RewiringConfig(
            decay_lambda=0.9,
            prune_threshold=0.01,
            snapshot_interval=10,
        )
        topology = CommunicationTopology(agents)
        engine = EdgeRewiringEngine(topology, config=config, output_dir=tmp_path)

        action_types_with_targets = [
            ("CREATE_COMMENT", "post_author_name"),
            ("LIKE_POST", "post_author_name"),
            ("FOLLOW", "target_user_name"),
            ("QUOTE_POST", "original_author_name"),
            ("MUTE", "target_user_name"),
        ]

        rng = random.Random(42)  # deterministic

        for round_num in range(1, 21):
            # 2-4 random actions per round
            n_actions = rng.randint(2, 4)
            for _ in range(n_actions):
                source = rng.choice(agents)
                target = rng.choice([a for a in agents if a != source])
                action_type, target_key = rng.choice(action_types_with_targets)
                action = make_action(source, action_type, round_num, **{target_key: target})
                engine.process_activity_from_dict(action, platform="twitter")

            engine.end_round(round_num)

            # --- Invariant checks after every round ---
            assert len(topology.agent_ids) == 5, f"Node count changed at round {round_num}"

            adj = topology.to_adjacency_matrix()
            assert adj.shape == (5, 5), f"Matrix shape wrong at round {round_num}"

            # No new agents in edges
            for (src, tgt) in topology.get_all_edges().keys():
                assert src in agents, f"Unknown source '{src}' at round {round_num}"
                assert tgt in agents, f"Unknown target '{tgt}' at round {round_num}"

    def test_cannot_add_agents_after_init(self) -> None:
        """Attempting to update_edge with unknown agent raises ValueError."""
        topology = CommunicationTopology(["A", "B"])

        with pytest.raises(ValueError, match="not in agent roster"):
            topology.update_edge("A", "UNKNOWN", 1.0, "FOLLOW", round_num=1)

        with pytest.raises(ValueError, match="not in agent roster"):
            topology.update_edge("UNKNOWN", "A", 1.0, "FOLLOW", round_num=1)

    def test_self_loop_rejected(self) -> None:
        """Self-loops are explicitly rejected."""
        topology = CommunicationTopology(["A", "B"])

        with pytest.raises(ValueError, match="Self-loops"):
            topology.update_edge("A", "A", 1.0, "FOLLOW", round_num=1)
