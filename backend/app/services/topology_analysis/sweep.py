"""Window-size sensitivity sweep for topology analysis.

Runs the topology analysis pipeline at multiple window sizes for the same
simulation and reports how key metrics vary — helping justify the choice of
default TOPOLOGY_WINDOW_SIZE in the paper.

Usage
-----
From Python:
    from app.services.topology_analysis.sweep import run_window_sweep
    report = run_window_sweep("your-simulation-id", window_sizes=[3, 5, 7, 10])

From the command line:
    cd backend
    uv run python -m app.services.topology_analysis.sweep <simulation_id> [--sizes 3 5 7 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ...config import Config
from ...utils.logger import get_logger
from .pipeline import analyze

logger = get_logger("mirofish.topology_analysis.sweep")

_DEFAULT_SIZES = [3, 5, 7, 10, 15]


def run_window_sweep(
    simulation_id: str,
    window_sizes: list[int] = _DEFAULT_SIZES,
    *,
    base_dir: Optional[Path] = None,
    null_model_m: int = 50,
    max_dim: Optional[int] = None,
    seed: int = 42,
    output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Run topology analysis at multiple window sizes and report sensitivity.

    Parameters
    ----------
    simulation_id : str
        The simulation to analyze.
    window_sizes : list[int]
        Window sizes to sweep (in rounds).
    base_dir : Path, optional
        Base directory for the task store.
    null_model_m : int
        Null-model permutations per sweep run (default 50; use fewer than the
        production default of 200 since we're running many times).
    max_dim : int, optional
        Max simplex dimension (defaults to Config.TOPOLOGY_MAX_DIM).
    seed : int
        Random seed for reproducibility.
    output_dir : Path, optional
        Where to write the sweep report. Defaults to
        backend/data/<sim_id>/topology/sweep/.

    Returns
    -------
    dict with per-window-size results and a sensitivity summary.
    """
    _max_dim = max_dim or Config.TOPOLOGY_MAX_DIM
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    _output_dir = (
        Path(output_dir)
        if output_dir
        else backend_dir / "data" / simulation_id / "topology" / "sweep"
    )
    _output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting window sweep: sim=%s, sizes=%s, M=%d",
        simulation_id,
        window_sizes,
        null_model_m,
    )

    per_size: dict[int, dict[str, Any]] = {}

    for ws in window_sizes:
        logger.info("Sweeping window_size=%d ...", ws)
        run_output = _output_dir / f"ws{ws}"
        try:
            result = analyze(
                simulation_id,
                base_dir=base_dir,
                output_dir=run_output,
                window_size=ws,
                null_model_m=null_model_m,
                max_dim=_max_dim,
                seed=seed,
            )
            per_size[ws] = {
                "n_windows": result.get("n_windows", 0),
                "h1_cohens_d": result.get("h1", {}).get("cohens_d", None),
                "h1_significant": result.get("h1", {}).get("significant", None),
                "h2_all_pass": result.get("h2", {}).get("all_pass", None),
                "h2_s_monotonic": result.get("h2", {}).get("s_monotonic", None),
                "h3_r_squared": result.get("h3", {}).get("r_squared", None),
                "h3_model_significant": result.get("h3", {}).get("model_significant", None),
                "error": None,
            }
        except Exception as exc:
            logger.warning("window_size=%d failed: %s", ws, exc)
            per_size[ws] = {"error": str(exc)}

    sensitivity = _compute_sensitivity(per_size)

    report = {
        "simulation_id": simulation_id,
        "window_sizes_swept": window_sizes,
        "null_model_m": null_model_m,
        "max_dim": _max_dim,
        "seed": seed,
        "per_size": per_size,
        "sensitivity": sensitivity,
    }

    report_path = _output_dir / "sweep_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("Sweep report written to %s", report_path)

    _print_sweep_summary(report)
    return report


def _compute_sensitivity(per_size: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Compute coefficient of variation for each key metric across window sizes."""
    valid = {ws: v for ws, v in per_size.items() if not v.get("error")}
    if len(valid) < 2:
        return {"note": "insufficient successful runs for sensitivity analysis"}

    metrics = ["h1_cohens_d", "h3_r_squared"]
    sensitivity: dict[str, Any] = {}

    for metric in metrics:
        values = [v[metric] for v in valid.values() if v.get(metric) is not None]
        if len(values) < 2:
            sensitivity[metric] = {"cv": None, "note": "insufficient data"}
            continue
        arr = np.array(values, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std())
        cv = (std / abs(mean)) if mean != 0 else float("inf")
        sensitivity[metric] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "cv": round(cv, 4),
            "interpretation": (
                "low sensitivity" if cv < 0.15
                else "moderate sensitivity" if cv < 0.35
                else "high sensitivity — results depend on window choice"
            ),
        }

    h2_pass_rates = {
        ws: int(bool(v.get("h2_all_pass")))
        for ws, v in valid.items()
        if v.get("h2_all_pass") is not None
    }
    if h2_pass_rates:
        sensitivity["h2_all_pass_rate"] = round(
            sum(h2_pass_rates.values()) / len(h2_pass_rates), 3
        )

    return sensitivity


def _print_sweep_summary(report: dict[str, Any]) -> None:
    print(f"\n{'='*60}")
    print(f"Window-size sensitivity sweep: {report['simulation_id']}")
    print(f"{'='*60}")
    print(f"{'Size':>6} | {'Windows':>7} | {'H1 d':>8} | {'H3 R²':>8} | {'H2 pass':>8}")
    print(f"{'-'*6}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")
    for ws in report["window_sizes_swept"]:
        v = report["per_size"].get(ws, {})
        if v.get("error"):
            print(f"{ws:>6} | {'ERROR':>7}")
            continue
        d = v.get("h1_cohens_d")
        r2 = v.get("h3_r_squared")
        h2 = v.get("h2_all_pass")
        print(
            f"{ws:>6} | {v.get('n_windows', '?'):>7} | "
            f"{d:>8.3f} | {r2:>8.3f} | {'yes' if h2 else 'no':>8}"
            if d is not None and r2 is not None
            else f"{ws:>6} | {v.get('n_windows', '?'):>7} | {'N/A':>8} | {'N/A':>8} | {'N/A':>8}"
        )

    sens = report.get("sensitivity", {})
    print(f"\nSensitivity summary:")
    for metric, info in sens.items():
        if isinstance(info, dict) and "cv" in info and info["cv"] is not None:
            print(f"  {metric}: CV={info['cv']:.3f} → {info['interpretation']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Window-size sensitivity sweep")
    parser.add_argument("simulation_id", help="Simulation ID to analyze")
    parser.add_argument(
        "--sizes", nargs="+", type=int,
        default=_DEFAULT_SIZES,
        help="Window sizes to sweep (default: 3 5 7 10 15)",
    )
    parser.add_argument(
        "--null-m", type=int, default=50,
        help="Null-model permutations per run (default: 50)",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # Ensure backend is on the path
    _backend = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(_backend) not in sys.path:
        sys.path.insert(0, str(_backend))

    run_window_sweep(
        args.simulation_id,
        window_sizes=args.sizes,
        null_model_m=args.null_m,
        seed=args.seed,
    )
