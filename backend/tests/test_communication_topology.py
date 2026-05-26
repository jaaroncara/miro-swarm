"""Unit tests for CommunicationTopology and EdgeState."""

import json

import numpy as np
import pytest

from app.services.communication_topology import CommunicationTopology, EdgeState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agents():
    """Standard 3-agent roster."""
    return ["alice", "bob", "carol"]


@pytest.fixture
def topo(agents):
    """Fresh topology with 3 agents."""
    return CommunicationTopology(agents)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_init_with_valid_agents(self, agents):
        topo = CommunicationTopology(agents)
        assert topo.agent_ids == agents, "agent_ids should match the input list"

    def test_init_rejects_duplicates(self):
        with pytest.raises(ValueError, match="duplicates"):
            CommunicationTopology(["alice", "bob", "alice"])

    def test_node_immutability(self, topo):
        """Mutating the returned agent_ids list does not affect internal state."""
        ids = topo.agent_ids
        ids.append("mallory")
        assert "mallory" not in topo.agent_ids, "Internal list must not be mutated externally"


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------


class TestUpdateEdge:
    def test_update_edge_creates_new_edge(self, topo):
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="CREATE_COMMENT", round_num=1)
        edge = topo.get_edge("alice", "bob")
        assert edge is not None, "Edge should have been created"
        assert edge.weight == 1.0
        assert edge.interaction_count == 1
        assert edge.created_at_round == 1

    def test_update_edge_increments_existing(self, topo):
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="CREATE_COMMENT", round_num=1)
        topo.update_edge("alice", "bob", weight_delta=0.5, action_type="LIKE_POST", round_num=2)
        edge = topo.get_edge("alice", "bob")
        assert edge.weight == pytest.approx(1.5), "Weights should accumulate"
        assert edge.interaction_count == 2

    def test_update_edge_tracks_interaction_types(self, topo):
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="CREATE_COMMENT", round_num=1)
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="CREATE_COMMENT", round_num=2)
        topo.update_edge("alice", "bob", weight_delta=0.3, action_type="LIKE_POST", round_num=3)
        edge = topo.get_edge("alice", "bob")
        assert edge.interaction_types == {"CREATE_COMMENT": 2, "LIKE_POST": 1}

    def test_update_edge_rejects_unknown_agent(self, topo):
        with pytest.raises(ValueError, match="not in agent roster"):
            topo.update_edge("alice", "unknown_agent", weight_delta=1.0, action_type="X", round_num=0)
        with pytest.raises(ValueError, match="not in agent roster"):
            topo.update_edge("unknown_agent", "bob", weight_delta=1.0, action_type="X", round_num=0)

    def test_update_edge_rejects_self_loop(self, topo):
        with pytest.raises(ValueError, match="Self-loops"):
            topo.update_edge("alice", "alice", weight_delta=1.0, action_type="X", round_num=0)


# ---------------------------------------------------------------------------
# Decay & Pruning
# ---------------------------------------------------------------------------


class TestDecayAndPruning:
    def test_apply_decay(self, topo):
        topo.update_edge("alice", "bob", weight_delta=2.0, action_type="X", round_num=0)
        topo.update_edge("bob", "carol", weight_delta=4.0, action_type="X", round_num=0)
        topo.apply_decay(0.5)
        assert topo.get_edge("alice", "bob").weight == pytest.approx(1.0)
        assert topo.get_edge("bob", "carol").weight == pytest.approx(2.0)

    def test_prune_edges(self, topo):
        topo.update_edge("alice", "bob", weight_delta=0.01, action_type="X", round_num=0)
        topo.update_edge("bob", "carol", weight_delta=5.0, action_type="X", round_num=0)
        topo.prune_edges(threshold=0.05)
        assert topo.get_edge("alice", "bob") is None, "Low-weight edge should be pruned"
        assert topo.get_edge("bob", "carol") is not None, "High-weight edge should remain"

    def test_prune_after_decay(self, topo):
        topo.update_edge("alice", "bob", weight_delta=0.1, action_type="X", round_num=0)
        # After ~10 rounds of 0.9 decay: 0.1 * 0.9^10 ≈ 0.035 < 0.05 threshold
        for _ in range(10):
            topo.apply_decay(0.9)
        topo.prune_edges(threshold=0.05)
        assert topo.get_edge("alice", "bob") is None, "Edge should be pruned after multiple decays"


# ---------------------------------------------------------------------------
# Matrix representations
# ---------------------------------------------------------------------------


class TestMatrixViews:
    def test_to_adjacency_matrix(self, topo):
        topo.update_edge("alice", "bob", weight_delta=2.0, action_type="X", round_num=0)
        topo.update_edge("carol", "alice", weight_delta=3.0, action_type="X", round_num=0)
        mat = topo.to_adjacency_matrix()
        assert mat.shape == (3, 3), "Matrix should be NxN"
        # alice=0, bob=1, carol=2
        assert mat[0, 1] == pytest.approx(2.0), "alice->bob weight"
        assert mat[2, 0] == pytest.approx(3.0), "carol->alice weight"
        assert mat[0, 2] == 0.0, "No alice->carol edge"

    def test_to_symmetric_matrix(self, topo):
        topo.update_edge("alice", "bob", weight_delta=2.0, action_type="X", round_num=0)
        topo.update_edge("bob", "alice", weight_delta=5.0, action_type="X", round_num=0)
        sym = topo.to_symmetric_matrix()
        # max(2.0, 5.0) = 5.0 in both directions
        assert sym[0, 1] == pytest.approx(5.0)
        assert sym[1, 0] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Snapshots & serialization
# ---------------------------------------------------------------------------


class TestSnapshots:
    def test_save_snapshot_creates_json(self, topo, tmp_path):
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="X", round_num=0)
        topo.save_snapshot(output_dir=tmp_path, window_id=0, round_start=0, round_end=5)
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1, "Exactly one JSON file should be created"

    def test_save_snapshot_format(self, topo, tmp_path):
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="X", round_num=0)
        topo.save_snapshot(output_dir=tmp_path, window_id=1, round_start=0, round_end=5)
        snapshot = json.loads((tmp_path / "window_001.json").read_text())
        assert "window_id" in snapshot
        assert "agent_ids" in snapshot
        assert "adjacency_directed" in snapshot
        assert "adjacency_symmetric" in snapshot
        assert "metrics" in snapshot
        assert snapshot["window_id"] == 1


# ---------------------------------------------------------------------------
# Reset & helpers
# ---------------------------------------------------------------------------


class TestResetAndHelpers:
    def test_reset_clears_edges_keeps_agents(self, topo):
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="X", round_num=0)
        topo.reset()
        assert topo.edge_count() == 0, "All edges should be cleared"
        assert topo.agent_ids == ["alice", "bob", "carol"], "Agent roster should remain"

    def test_edge_count(self, topo):
        assert topo.edge_count() == 0
        topo.update_edge("alice", "bob", weight_delta=1.0, action_type="X", round_num=0)
        assert topo.edge_count() == 1
        topo.update_edge("bob", "carol", weight_delta=1.0, action_type="X", round_num=0)
        assert topo.edge_count() == 2

    def test_get_edge_returns_none_for_missing(self, topo):
        assert topo.get_edge("alice", "bob") is None, "Non-existent edge should return None"
