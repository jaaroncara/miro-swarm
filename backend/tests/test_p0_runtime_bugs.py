import builtins
import json
import secrets
from datetime import datetime, timedelta

if not hasattr(builtins, "_get_bool_env"):
    builtins._get_bool_env = lambda key, default=False: default
if not hasattr(builtins, "_get_cors_origins"):
    builtins._get_cors_origins = lambda: []
if not hasattr(builtins, "secrets"):
    builtins.secrets = secrets

import app.api.graph  # noqa: F401
import app.api.report  # noqa: F401
import pytest
from flask import Flask

from app.api import graph_bp, report_bp
from app.api import graph as graph_api
from app.api import report as report_api
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner


@pytest.fixture
def api_client():
    app = Flask(__name__)
    app.register_blueprint(graph_bp, url_prefix="/api/graph")
    app.register_blueprint(report_bp, url_prefix="/api/report")
    return app.test_client()


def test_graph_tasks_accepts_pre_serialized_task_dicts(api_client, monkeypatch):
    monkeypatch.setattr(
        graph_api.TaskManager,
        "list_tasks",
        lambda self: [
            {
                "task_id": "task-1",
                "task_type": "graph_build",
                "status": "processing",
                "progress": 25,
            }
        ],
    )

    response = api_client.get("/api/graph/tasks")

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        {
            "task_id": "task-1",
            "task_type": "graph_build",
            "status": "processing",
            "progress": 25,
        }
    ]


def test_report_status_get_resolves_active_task_by_report_id(api_client, monkeypatch):
    monkeypatch.setattr(
        report_api.TaskManager,
        "list_tasks",
        lambda self, task_type=None: [
            {
                "task_id": "task-1",
                "status": "processing",
                "progress": 42,
                "message": "Generating report",
                "metadata": {"report_id": "report-1"},
            }
        ],
    )
    monkeypatch.setattr(report_api.ReportManager, "get_report", lambda report_id: None)

    response = api_client.get(
        "/api/report/generate/status",
        query_string={"report_id": "report-1"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "task_id": "task-1",
        "status": "processing",
        "progress": 42,
        "message": "Generating report",
        "metadata": {"report_id": "report-1"},
    }


def test_get_profiles_reads_twitter_csv(tmp_path, monkeypatch):
    simulation_id = "sim-twitter"
    sim_dir = tmp_path / simulation_id
    sim_dir.mkdir(parents=True)

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))

    state = {
        "simulation_id": simulation_id,
        "project_id": "project-1",
        "graph_id": "graph-1",
        "status": "created",
    }
    (sim_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (sim_dir / "twitter_profiles.csv").write_text(
        "agent_id,username,bio\n1,alice,Researcher\n2,bob,Analyst\n",
        encoding="utf-8",
    )

    profiles = SimulationManager().get_profiles(simulation_id, platform="twitter")

    assert profiles == [
        {"agent_id": "1", "username": "alice", "bio": "Researcher"},
        {"agent_id": "2", "username": "bob", "bio": "Analyst"},
    ]


def test_timeline_and_agent_stats_are_complete_and_chronological(tmp_path, monkeypatch):
    simulation_id = "sim-actions"
    actions_dir = tmp_path / simulation_id / "twitter"
    actions_dir.mkdir(parents=True)

    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))

    start = datetime(2024, 1, 1, 0, 0, 0)
    actions_path = actions_dir / "actions.jsonl"
    with actions_path.open("w", encoding="utf-8") as handle:
        for index in range(10001):
            timestamp = (start + timedelta(seconds=index)).isoformat()
            record = {
                "round": 1 if index < 5001 else 2,
                "timestamp": timestamp,
                "agent_id": 7,
                "agent_name": "Agent 7",
                "action_type": "CREATE_POST",
                "success": True,
            }
            handle.write(json.dumps(record) + "\n")

    timeline = SimulationRunner.get_timeline(simulation_id)
    stats = SimulationRunner.get_agent_stats(simulation_id)

    assert len(timeline) == 2
    assert timeline[0]["total_actions"] == 5001
    assert timeline[0]["first_action_time"] == start.isoformat()
    assert timeline[0]["last_action_time"] == (start + timedelta(seconds=5000)).isoformat()
    assert timeline[0]["first_action_time"] < timeline[0]["last_action_time"]
    assert timeline[1]["total_actions"] == 5000
    assert timeline[1]["first_action_time"] == (start + timedelta(seconds=5001)).isoformat()
    assert timeline[1]["last_action_time"] == (start + timedelta(seconds=10000)).isoformat()
    assert timeline[1]["first_action_time"] < timeline[1]["last_action_time"]

    assert stats[0]["total_actions"] == 10001
    assert stats[0]["first_action_time"] == start.isoformat()
    assert stats[0]["last_action_time"] == (start + timedelta(seconds=10000)).isoformat()
    assert stats[0]["first_action_time"] < stats[0]["last_action_time"]
