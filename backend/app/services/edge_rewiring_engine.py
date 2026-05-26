"""
Edge Rewiring Engine — Processes agent activities in real-time and mutates
the CommunicationTopology graph during simulation.

Responsibilities:
  - Map each agent action to a weight delta on the (source → target) edge.
  - Apply per-round exponential decay and pruning.
  - Produce topology snapshots at configurable window boundaries.

This engine is NOT thread-safe — the caller (SimulationRunner) must ensure
sequential access from the monitoring thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.logger import get_logger
from .communication_topology import CommunicationTopology

logger = get_logger("mirofish.services.edge_rewiring_engine")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RewiringConfig:
    """Configuration for the edge rewiring engine."""

    decay_lambda: float = 0.95        # Per-round decay factor
    prune_threshold: float = 0.05     # Minimum edge weight before pruning
    snapshot_interval: int = 5        # Rounds per time window

    # Weight deltas by action type
    weight_comment: float = 1.0
    weight_quote: float = 0.8
    weight_repost: float = 0.6
    weight_follow: float = 0.5
    weight_like: float = 0.3
    weight_dislike: float = 0.3
    weight_mute: float = -0.5

    @classmethod
    def from_config(cls) -> "RewiringConfig":
        """Load from app Config (environment variables)."""
        from ..config import Config

        return cls(
            decay_lambda=getattr(Config, "TOPOLOGY_DECAY_LAMBDA", 0.95),
            prune_threshold=getattr(Config, "TOPOLOGY_PRUNE_THRESHOLD", 0.05),
            snapshot_interval=getattr(Config, "TOPOLOGY_SNAPSHOT_INTERVAL", 5),
            weight_comment=getattr(Config, "TOPOLOGY_WEIGHT_COMMENT", 1.0),
            weight_quote=getattr(Config, "TOPOLOGY_WEIGHT_QUOTE", 0.8),
            weight_repost=getattr(Config, "TOPOLOGY_WEIGHT_REPOST", 0.6),
            weight_follow=getattr(Config, "TOPOLOGY_WEIGHT_FOLLOW", 0.5),
            weight_like=getattr(Config, "TOPOLOGY_WEIGHT_LIKE", 0.3),
            weight_dislike=getattr(Config, "TOPOLOGY_WEIGHT_DISLIKE", 0.3),
            weight_mute=getattr(Config, "TOPOLOGY_WEIGHT_MUTE", -0.5),
        )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class EdgeRewiringEngine:
    """
    Processes agent activities in real-time and mutates the communication
    topology graph.  Designed to run alongside the simulation's action log
    reader.

    This engine is NOT thread-safe — the caller (SimulationRunner) must ensure
    sequential access from the monitoring thread.
    """

    def __init__(
        self,
        topology: CommunicationTopology,
        config: Optional[RewiringConfig] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.topology = topology
        self.config = config or RewiringConfig.from_config()
        self.output_dir = output_dir  # Where to save snapshots

        self._current_round: int = 0
        self._window_start_round: int = 0
        self._snapshots_produced: int = 0
        self._actions_processed: int = 0

    # ------------------------------------------------------------------
    # Public API — activity processing
    # ------------------------------------------------------------------

    def process_activity(self, activity: Any) -> None:
        """Process a single AgentActivity and update the topology.

        Args:
            activity: An AgentActivity instance (from graph_memory_updater).
                      Expected attributes: agent_name, action_type, action_args, round_num.
        """
        target = self._extract_target_agent(activity.action_type, activity.action_args)

        if target is None:
            return  # No bilateral edge for this action type

        # Skip if target not in topology's agent roster
        if target not in self.topology._agent_set:
            logger.debug(
                "Target '%s' not in topology roster, skipping action %s from %s",
                target,
                activity.action_type,
                activity.agent_name,
            )
            return

        # Skip if source not in topology's agent roster
        if activity.agent_name not in self.topology._agent_set:
            logger.debug(
                "Source '%s' not in topology roster, skipping", activity.agent_name
            )
            return

        # Skip self-loops
        if activity.agent_name == target:
            return

        delta = self._get_weight_delta(activity.action_type)
        if delta == 0.0:
            return

        self.topology.update_edge(
            source=activity.agent_name,
            target=target,
            weight_delta=delta,
            action_type=activity.action_type,
            round_num=activity.round_num,
        )
        self._actions_processed += 1

    def process_activity_from_dict(self, action_data: Dict[str, Any], platform: str) -> None:
        """Process a raw action dict (from JSONL action log) and update topology.

        This avoids importing AgentActivity and potential circular imports.

        Args:
            action_data: Dict with keys: agent_name, action_type, action_args, round_num.
            platform: Platform identifier (for logging context).
        """
        agent_name = action_data.get("agent_name", "")
        action_type = action_data.get("action_type", "")
        action_args = action_data.get("action_args", {})
        round_num = action_data.get("round_num", 0)

        # Ensure action_args is a dict
        if isinstance(action_args, str):
            import json

            try:
                action_args = json.loads(action_args)
            except (json.JSONDecodeError, TypeError):
                action_args = {}

        target = self._extract_target_agent(action_type, action_args)

        if target is None:
            return

        if target not in self.topology._agent_set:
            return

        if agent_name not in self.topology._agent_set:
            return

        if agent_name == target:
            return

        delta = self._get_weight_delta(action_type)
        if delta == 0.0:
            return

        self.topology.update_edge(
            source=agent_name,
            target=target,
            weight_delta=delta,
            action_type=action_type,
            round_num=round_num,
        )
        self._actions_processed += 1

    # ------------------------------------------------------------------
    # Public API — round and window management
    # ------------------------------------------------------------------

    def end_round(self, round_num: int) -> None:
        """Signal end of a simulation round — apply decay, prune, check window.

        Args:
            round_num: The round number that just completed.
        """
        self.topology.apply_decay(self.config.decay_lambda)
        self.topology.prune_edges(self.config.prune_threshold)
        self.topology.increment_round()
        self._current_round = round_num

        # Check if we've reached a window boundary
        if (round_num - self._window_start_round) >= self.config.snapshot_interval:
            self.end_window(self._snapshots_produced)
            self._window_start_round = round_num

    def end_window(self, window_id: int) -> None:
        """Produce a topology snapshot for the completed window.

        Args:
            window_id: Sequential window identifier.
        """
        if self.output_dir is not None:
            self.topology.save_snapshot(
                output_dir=self.output_dir,
                window_id=window_id,
                round_start=self._window_start_round,
                round_end=self._current_round,
            )

        self._snapshots_produced += 1
        logger.info(
            "Window %d complete (rounds %d–%d): %d edges active",
            window_id,
            self._window_start_round,
            self._current_round,
            self.topology.edge_count(),
        )

    def finalize(self) -> Dict[str, Any]:
        """Finalize the engine at simulation end.

        Produces a final snapshot if there are unwritten rounds since the last
        window boundary.  Returns summary statistics.

        Returns:
            Dict with summary stats.
        """
        # Produce final snapshot if there are unwritten rounds
        rounds_since_last_window = self._current_round - self._window_start_round
        if rounds_since_last_window > 0:
            logger.info(
                "Producing final snapshot for %d remaining rounds", rounds_since_last_window
            )
            self.end_window(self._snapshots_produced)

        stats = self.get_stats()
        logger.info(
            "EdgeRewiringEngine finalized: %d actions processed, %d snapshots produced, "
            "%d final edges",
            stats["actions_processed"],
            stats["snapshots_produced"],
            stats["edge_count"],
        )
        return stats

    def get_stats(self) -> Dict[str, Any]:
        """Return current engine statistics.

        Returns:
            Dict with actions_processed, current_round, snapshots_produced,
            edge_count, agent_count.
        """
        return {
            "actions_processed": self._actions_processed,
            "current_round": self._current_round,
            "snapshots_produced": self._snapshots_produced,
            "edge_count": self.topology.edge_count(),
            "agent_count": len(self.topology._agent_ids),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_target_agent(self, action_type: str, action_args: Dict) -> Optional[str]:
        """Determine the target agent for a given action.

        Args:
            action_type: The action type string (e.g. "CREATE_COMMENT").
            action_args: Dict of action arguments containing target info.

        Returns:
            Target agent name, or None if the action has no bilateral target.
        """
        if not isinstance(action_args, dict):
            return None

        if action_type == "CREATE_COMMENT":
            return action_args.get("parent_comment_author_name") or action_args.get(
                "post_author_name"
            )

        if action_type == "QUOTE_POST":
            return action_args.get("original_author_name") or action_args.get(
                "post_author_name"
            )

        if action_type in ("LIKE_POST", "DISLIKE_POST"):
            return action_args.get("post_author_name")

        if action_type in ("LIKE_COMMENT", "DISLIKE_COMMENT"):
            return action_args.get("comment_author_name")

        if action_type in ("FOLLOW", "MUTE"):
            return action_args.get("target_user_name")

        if action_type == "REPOST":
            return action_args.get("original_author_name") or action_args.get(
                "post_author_name"
            )

        # Actions with no bilateral edge: CREATE_POST, SEARCH_POSTS, SEARCH_USER, etc.
        return None

    def _get_weight_delta(self, action_type: str) -> float:
        """Map action type to weight delta from config.

        Args:
            action_type: The action type string.

        Returns:
            Weight delta (can be negative for adversarial actions).
        """
        mapping = {
            "CREATE_COMMENT": self.config.weight_comment,
            "QUOTE_POST": self.config.weight_quote,
            "REPOST": self.config.weight_repost,
            "FOLLOW": self.config.weight_follow,
            "LIKE_POST": self.config.weight_like,
            "LIKE_COMMENT": self.config.weight_like,
            "DISLIKE_POST": self.config.weight_dislike,
            "DISLIKE_COMMENT": self.config.weight_dislike,
            "MUTE": self.config.weight_mute,
        }
        return mapping.get(action_type, 0.0)
