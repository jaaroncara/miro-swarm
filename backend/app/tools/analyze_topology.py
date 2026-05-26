"""Tool for topology analysis of completed simulations."""

import threading
from typing import Any, Dict, Optional

from ..core.task_manager import TaskManager, TaskStatus
from ..resources.simulations import SimulationStore
from ..services.topology_analysis.pipeline import analyze
from ..utils.logger import get_logger

logger = get_logger("mirofish.tools.analyze_topology")


class AnalyzeTopologyTool:
    """Run topology analysis on a completed simulation in the background."""

    def __init__(
        self,
        simulation_store: Optional[SimulationStore] = None,
        task_manager: Optional[TaskManager] = None,
    ):
        self.simulation_store = simulation_store or SimulationStore()
        self.task_manager = task_manager or TaskManager()

    def start(
        self,
        simulation_id: str,
        *,
        window_size: Optional[int] = None,
        null_model_m: Optional[int] = None,
        max_dim: Optional[int] = None,
        seed: int = 42,
    ) -> Dict[str, Any]:
        """Start topology analysis for a completed simulation.

        Parameters
        ----------
        simulation_id : str
            ID of the simulation to analyze.
        window_size : int, optional
            Rounds per time window (default from Config).
        null_model_m : int, optional
            Null-model permutations (default from Config).
        max_dim : int, optional
            Max simplex dimension (default from Config).
        seed : int
            Random seed for reproducibility.

        Returns
        -------
        dict with 'task_id' and 'status' for async tracking.
        """
        state = self.simulation_store.get(simulation_id)
        if not state:
            raise FileNotFoundError(f"Simulation not found: {simulation_id}")

        task_id = self.task_manager.create_task(
            task_type="topology_analysis",
            metadata={"simulation_id": simulation_id},
        )

        thread = threading.Thread(
            target=self._run_analysis,
            args=(task_id, simulation_id),
            kwargs={
                "window_size": window_size,
                "null_model_m": null_model_m,
                "max_dim": max_dim,
                "seed": seed,
            },
            daemon=True,
        )
        thread.start()

        logger.info("Topology analysis started: task=%s, sim=%s", task_id, simulation_id)
        return {"task_id": task_id, "status": "started", "simulation_id": simulation_id}

    def _run_analysis(
        self,
        task_id: str,
        simulation_id: str,
        *,
        window_size: Optional[int] = None,
        null_model_m: Optional[int] = None,
        max_dim: Optional[int] = None,
        seed: int = 42,
    ) -> None:
        """Background thread that runs the full analysis pipeline."""
        try:
            self.task_manager.update_task(task_id, status=TaskStatus.IN_PROGRESS, message="Running topology analysis")

            results = analyze(
                simulation_id,
                window_size=window_size,
                null_model_m=null_model_m,
                max_dim=max_dim,
                seed=seed,
            )

            self.task_manager.complete_task(task_id, result=results)
            logger.info("Topology analysis completed: task=%s", task_id)

        except Exception as exc:
            logger.exception("Topology analysis failed: task=%s", task_id)
            self.task_manager.fail_task(task_id, error=str(exc))
