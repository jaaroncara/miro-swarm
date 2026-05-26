"""Topology analysis API blueprint.

Endpoints:
  POST /api/topology/analyze               Start topology analysis for a completed simulation
  GET  /api/topology/results/<sim_id>      Get analysis results (metrics.json)
  GET  /api/topology/status/<task_id>      Check background task status
"""

import json
from pathlib import Path

from flask import request, jsonify

from . import topology_bp
from ..core.workbench_session import WorkbenchSession
from ..core.task_manager import TaskManager
from ..utils.logger import get_logger

logger = get_logger("mirofish.api.topology")


def _default_output_dir(simulation_id: str) -> Path:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir / "data" / simulation_id / "topology"


@topology_bp.route("/analyze", methods=["POST"])
def start_analysis():
    """Start topology analysis for a completed simulation.

    Body (JSON):
        simulation_id   (required) str
        window_size     (optional) int  — rounds per window
        null_model_m    (optional) int  — permutations for null model
        max_dim         (optional) int  — max simplex dimension
        seed            (optional) int  — random seed (default 42)

    Returns:
        { success: bool, task_id: str, simulation_id: str }
    """
    try:
        data = request.get_json() or {}
        simulation_id = data.get("simulation_id", "").strip()
        if not simulation_id:
            return jsonify({"success": False, "error": "simulation_id is required"}), 400

        session = WorkbenchSession()
        result = session.analyze_topology_tool.start(
            simulation_id,
            window_size=data.get("window_size"),
            null_model_m=data.get("null_model_m"),
            max_dim=data.get("max_dim"),
            seed=int(data.get("seed", 42)),
        )
        return jsonify({"success": True, **result})

    except FileNotFoundError as exc:
        logger.warning("Simulation not found: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("Error starting topology analysis")
        return jsonify({"success": False, "error": str(exc)}), 500


@topology_bp.route("/results/<simulation_id>", methods=["GET"])
def get_results(simulation_id: str):
    """Return the metrics.json from a completed topology analysis.

    Returns:
        { success: bool, data: { ...metrics } }  or 404 if not yet run.
    """
    try:
        output_dir = _default_output_dir(simulation_id)
        metrics_path = output_dir / "metrics.json"

        if not metrics_path.exists():
            return jsonify({
                "success": False,
                "error": f"No topology analysis results found for simulation {simulation_id}",
            }), 404

        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        return jsonify({"success": True, "data": metrics})

    except Exception as exc:
        logger.exception("Error reading topology results for %s", simulation_id)
        return jsonify({"success": False, "error": str(exc)}), 500


@topology_bp.route("/status/<task_id>", methods=["GET"])
def get_task_status(task_id: str):
    """Poll the status of a background topology analysis task.

    Returns:
        { success: bool, status: str, result: {...} | null, error: str | null }
    """
    try:
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "error": f"Task {task_id} not found"}), 404

        task_data = task if isinstance(task, dict) else task.to_dict()
        return jsonify({
            "success": True,
            "status": task_data.get("status"),
            "result": task_data.get("result"),
            "error": task_data.get("error"),
        })

    except Exception as exc:
        logger.exception("Error fetching task status for %s", task_id)
        return jsonify({"success": False, "error": str(exc)}), 500
