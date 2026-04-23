import json
import sys
import asyncio
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_servers import task_server

from app import create_app
from app.config import Config
from app.core.simulation_task_store import get_simulation_task_store
from app.core.task_action_parser import ParsedTaskAction, apply_task_action
from app.core.task_lifecycle import (
    TaskAuthorizationError,
    TaskLifecycleService,
)


@pytest.fixture
def simulation_root(tmp_path: Path) -> Path:
    base_dir = tmp_path / "simulations"
    sim_dir = base_dir / "sim_test"
    sim_dir.mkdir(parents=True)
    (sim_dir / "state.json").write_text(
        json.dumps({"project_id": "proj_test", "graph_id": "graph_demo"}),
        encoding="utf-8",
    )
    return base_dir


@pytest.fixture
def task_api_client(simulation_root: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = simulation_root.parent / "json_graphs"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Config, "GRAPH_BACKEND", "json")
    monkeypatch.setattr(Config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(Config, "MCP_SERVER_ENABLED", False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))

    app = create_app(Config)
    app.config.update(TESTING=True)

    with app.test_client() as client:
        yield client


def test_task_store_creates_visible_issue_keys_and_events(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)

    task = store.create_task(
        title="Compile findings",
        description="Summarize the latest market data.",
        assigned_by="Alice",
        assigned_to="Bob",
        parent_goal="Weekly report",
    )

    assert task.issue_key == "TEST-1"
    assert task.sequence_number == 1
    assert task.events[0].event_type == "created"
    assert task.events[0].details["issue_key"] == "TEST-1"

    persisted = json.loads(
        (simulation_root / "sim_test" / "sim_tasks.json").read_text(encoding="utf-8")
    )
    assert persisted[0]["issue_key"] == "TEST-1"
    assert persisted[0]["id"] == "TEST-1"
    assert persisted[0]["events"][0]["event_type"] == "created"


def test_legacy_task_file_is_migrated_with_issue_key_and_history(simulation_root: Path):
    legacy_payload = [
        {
            "task_id": "legacy-task-1",
            "simulation_id": "sim_test",
            "title": "Legacy task",
            "description": "Pre-existing task without issue key.",
            "assigned_by": "Alice",
            "assigned_to": "Bob",
            "status": "open",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    ]
    (simulation_root / "sim_test" / "sim_tasks.json").write_text(
        json.dumps(legacy_payload),
        encoding="utf-8",
    )

    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    task = store.list_tasks()[0]

    assert task.task_id == "legacy-task-1"
    assert task.issue_key == "TEST-1"
    assert task.events[0].event_type == "created"

    migrated_payload = json.loads(
        (simulation_root / "sim_test" / "sim_tasks.json").read_text(encoding="utf-8")
    )
    assert migrated_payload[0]["issue_key"] == "TEST-1"
    assert migrated_payload[0]["sequence_number"] == 1


def test_lifecycle_enforces_authorization_and_records_transitions(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    created = lifecycle.create_task(
        title="Produce analysis",
        description="Build the regional summary.",
        assigned_to="Bob",
        actor="Alice",
    )
    started = lifecycle.start_task(
        created.issue_key, actor="Bob", reason="Collecting inputs"
    )
    assert started.status == "in_progress"
    completed = lifecycle.complete_task(
        created.issue_key, actor="Bob", output="Report delivered"
    )

    assert completed.status == "done"
    assert completed.output == "Report delivered"
    assert [event.event_type for event in completed.events] == [
        "created",
        "started",
        "completed",
    ]

    with pytest.raises(TaskAuthorizationError):
        lifecycle.complete_task(
            created.issue_key, actor="Mallory", output="Spoofed completion"
        )


def test_apply_task_action_uses_lifecycle_and_issue_key(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)
    task = lifecycle.create_task(
        title="Review draft",
        description="Check the narrative before publishing.",
        assigned_to="Bob",
        actor="Alice",
    )

    parsed = ParsedTaskAction(
        action_type="complete",
        issue_key=task.issue_key,
        output="Reviewed and approved.",
    )

    task_id = apply_task_action(
        parsed,
        agent_name="Bob",
        simulation_id="sim_test",
        store=store,
    )

    updated = store.get_task(task_id)
    assert updated is not None
    assert updated.issue_key == task.issue_key
    assert updated.status == "done"
    assert updated.events[-1].event_type == "completed"


def test_task_server_exposes_explicit_lifecycle_tools(
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))

    created_message = asyncio.run(
        task_server.create_task(
            simulation_id="sim_test",
            title="Prepare summary",
            description="Collect the latest highlights.",
            assigned_to="Bob",
            actor="Alice",
            parent_goal="Weekly report",
        )
    )
    assert "Task created:" in created_message
    assert "TEST-1" in created_message

    task_detail_raw = asyncio.run(
        task_server.get_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
        )
    )
    task_detail = json.loads(task_detail_raw)
    assert task_detail["issue_key"] == "TEST-1"
    assert task_detail["assigned_by"] == "Alice"

    started_message = asyncio.run(
        task_server.start_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
            reason="Collecting inputs",
        )
    )
    assert "Task started:" in started_message
    assert "[in_progress]" in started_message

    blocked_message = asyncio.run(
        task_server.block_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
            reason="Waiting on source data",
        )
    )
    assert "Task blocked:" in blocked_message
    assert "[blocked]" in blocked_message

    listed_message = asyncio.run(
        task_server.list_my_tasks(
            simulation_id="sim_test",
            actor="Bob",
        )
    )
    assert "Tasks for Bob" in listed_message
    assert "TEST-1 [blocked]" in listed_message

    outsider_lookup = asyncio.run(
        task_server.get_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Mallory",
        )
    )
    assert "Task lookup rejected:" in outsider_lookup

    restarted_message = asyncio.run(
        task_server.start_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
            reason="Inputs arrived",
        )
    )
    assert "Task started:" in restarted_message
    assert "[in_progress]" in restarted_message

    completed_message = asyncio.run(
        task_server.complete_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
            output="Summary delivered",
        )
    )
    assert "Task completed:" in completed_message
    assert "[done]" in completed_message


@pytest.mark.parametrize(
    "payload",
    [
        [
            {
                "task_id": "task-1",
                "issue_key": "TEST-1",
                "sequence_number": 1,
                "simulation_id": "sim_test",
                "title": "One",
                "description": "",
                "assigned_by": "Alice",
                "assigned_to": "Bob",
                "status": "open",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "events": [],
            },
            {
                "task_id": "task-2",
                "issue_key": "TEST-1",
                "sequence_number": 2,
                "simulation_id": "sim_test",
                "title": "Two",
                "description": "",
                "assigned_by": "Alice",
                "assigned_to": "Bob",
                "status": "open",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "events": [],
            },
        ],
        [
            {
                "task_id": "task-1",
                "issue_key": "TEST-1",
                "sequence_number": 1,
                "simulation_id": "sim_test",
                "title": "Broken",
                "description": "",
                "assigned_by": "Alice",
                "assigned_to": "Bob",
                "status": "unknown",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "events": [],
            }
        ],
    ],
)
def test_invalid_task_payloads_fail_fast(simulation_root: Path, payload: list[dict]):
    (simulation_root / "sim_test" / "sim_tasks.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    store = get_simulation_task_store("sim_test", base_dir=simulation_root)

    with pytest.raises(ValueError):
        store.list_tasks()


def test_simulation_task_api_supports_create_query_and_detail(task_api_client):
    create_response = task_api_client.post(
        "/api/simulation/sim_test/tasks",
        json={
            "title": "Assemble brief",
            "description": "Summarize the key developments.",
            "assigned_to": "Bob",
            "actor": "Alice",
            "parent_goal": "Leadership update",
        },
    )

    assert create_response.status_code == 201
    created_payload = create_response.get_json()
    created_task = created_payload["data"]["task"]
    assert created_task["issue_key"] == "TEST-1"
    assert created_task["is_completed"] is False
    assert created_task["events_count"] == 1
    assert created_task["latest_event"]["event_type"] == "created"
    assert created_task["participants"] == {
        "assigned_by": "Alice",
        "assigned_to": "Bob",
    }

    list_response = task_api_client.get(
        "/api/simulation/sim_test/tasks",
        query_string={"assigned_to": "Bob", "status": "open", "completed": "false"},
    )
    assert list_response.status_code == 200
    list_payload = list_response.get_json()["data"]
    assert list_payload["count"] == 1
    assert list_payload["status_counts"]["open"] == 1
    assert list_payload["filters"] == {
        "assigned_to": "Bob",
        "status": "open",
        "completed": False,
    }
    assert list_payload["tasks"][0]["issue_key"] == "TEST-1"

    detail_response = task_api_client.get(
        "/api/simulation/sim_test/tasks/TEST-1",
        query_string={"actor": "Bob"},
    )
    assert detail_response.status_code == 200
    detail_task = detail_response.get_json()["data"]["task"]
    assert detail_task["issue_key"] == "TEST-1"
    assert detail_task["assigned_by"] == "Alice"

    unauthorized_response = task_api_client.get(
        "/api/simulation/sim_test/tasks/TEST-1",
        query_string={"actor": "Mallory"},
    )
    assert unauthorized_response.status_code == 403
    assert "not allowed to view task" in unauthorized_response.get_json()["error"]

    invalid_filter_response = task_api_client.get(
        "/api/simulation/sim_test/tasks",
        query_string={"completed": "maybe"},
    )
    assert invalid_filter_response.status_code == 400


def test_simulation_task_api_supports_start_block_and_complete(task_api_client):
    task_api_client.post(
        "/api/simulation/sim_test/tasks",
        json={
            "title": "Draft response",
            "description": "Prepare the response memo.",
            "assigned_to": "Bob",
            "actor": "Alice",
        },
    )

    started_response = task_api_client.post(
        "/api/simulation/sim_test/tasks/TEST-1/start",
        json={"actor": "Bob", "reason": "Reviewing source material"},
    )
    assert started_response.status_code == 200
    started_task = started_response.get_json()["data"]["task"]
    assert started_task["status"] == "in_progress"
    assert started_task["latest_event"]["event_type"] == "started"

    blocked_response = task_api_client.post(
        "/api/simulation/sim_test/tasks/TEST-1/block",
        json={"actor": "Bob", "reason": "Waiting for legal review"},
    )
    assert blocked_response.status_code == 200
    blocked_task = blocked_response.get_json()["data"]["task"]
    assert blocked_task["status"] == "blocked"
    assert blocked_task["latest_event"]["event_type"] == "blocked"

    completed_response = task_api_client.post(
        "/api/simulation/sim_test/tasks/TEST-1/complete",
        json={"actor": "Bob", "output": "Memo delivered"},
    )
    assert completed_response.status_code == 200
    completed_task = completed_response.get_json()["data"]["task"]
    assert completed_task["status"] == "done"
    assert completed_task["output"] == "Memo delivered"
    assert completed_task["latest_event"]["event_type"] == "completed"

    unauthorized_start = task_api_client.post(
        "/api/simulation/sim_test/tasks/TEST-1/start",
        json={"actor": "Mallory", "reason": "Hijacking task"},
    )
    assert unauthorized_start.status_code == 403

    completed_filter_response = task_api_client.get(
        "/api/simulation/sim_test/tasks",
        query_string={"completed": "true"},
    )
    assert completed_filter_response.status_code == 200
    completed_payload = completed_filter_response.get_json()["data"]
    assert completed_payload["count"] == 1
    assert completed_payload["tasks"][0]["status"] == "done"
