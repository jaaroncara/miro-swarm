import base64
import json
import logging
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_servers import task_server

import app.api.report as report_api
import app.core.task_observability as task_observability
import app.services.report_agent as report_agent_service

from app import create_app
from app.config import Config
from app.core.simulation_task_store import get_simulation_task_store
from app.core.task_action_parser import (
    ParsedTaskAction,
    TASK_MCP_PREFERRED_GUIDANCE,
    apply_task_action,
)
from app.core.task_context_injector import build_task_context_message
from app.core.task_lifecycle import (
    TaskAuthorizationError,
    TaskLifecycleError,
    TaskLifecycleService,
)
from app.core.task_round_processor import (
    collect_structured_offer_pairs,
    expire_unfinished_tasks,
    process_task_actions_for_round,
)
from app.resources.reports.report_store import ReportStore
from app.services.report_agent import Report, ReportManager, ReportStatus
from app.utils.oasis_llm import (
    TASK_COORDINATION_SYSTEM_ADDENDUM,
    TASK_MCP_TOOL_ORDER,
    _ensure_task_tool_access,
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
    upload_dir = simulation_root.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Config, "GRAPH_BACKEND", "json")
    monkeypatch.setattr(Config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(Config, "MCP_SERVER_ENABLED", False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(upload_dir))
    monkeypatch.setattr(Config, "ALLOW_BROWSER_TASK_MUTATIONS", False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(upload_dir / "reports"))

    app = create_app(Config)
    app.config.update(TESTING=True)

    with app.test_client() as client:
        yield client


@pytest.fixture
def task_api_client_with_mutations(
    simulation_root: Path, monkeypatch: pytest.MonkeyPatch
):
    data_dir = simulation_root.parent / "json_graphs"
    data_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = simulation_root.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Config, "GRAPH_BACKEND", "json")
    monkeypatch.setattr(Config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(Config, "MCP_SERVER_ENABLED", False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(upload_dir))
    monkeypatch.setattr(Config, "ALLOW_BROWSER_TASK_MUTATIONS", True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(upload_dir / "reports"))

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


def test_apply_task_action_falls_back_to_published_text_for_accept_and_complete(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)
    offered = lifecycle.offer_task(
        title="Publish supplier brief",
        description="Share the final brief in-thread.",
        assigned_to="Bob",
        actor="Alice",
    )

    accepted_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="update_status",
            issue_key=offered.issue_key,
            status="open",
        ),
        agent_name="Bob",
        simulation_id="sim_test",
        store=store,
        published_text="@Alice Taking this now. I will publish the supplier brief shortly.",
    )

    accepted = store.get_task(accepted_task_id)
    assert accepted is not None
    assert accepted.status == "open"
    assert accepted.events[-1].details["note"] == (
        "@Alice Taking this now. I will publish the supplier brief shortly."
    )

    completed_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="complete",
            issue_key=offered.issue_key,
        ),
        agent_name="Bob",
        simulation_id="sim_test",
        store=store,
        published_text="@Alice Published the supplier brief: key risk is concentrated in the northern corridor, with mitigation attached.",
    )

    completed = store.get_task(completed_task_id)
    assert completed is not None
    assert completed.status == "done"
    assert completed.output == (
        "@Alice Published the supplier brief: key risk is concentrated in the northern corridor, with mitigation attached."
    )
    assert completed.events[-1].details["output"] == completed.output


def test_apply_task_action_create_is_translated_into_legacy_offer_flow(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)

    offered_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="create",
            title="Review draft",
            assign_to="Bob",
            description="Check the narrative before publishing.",
            parent_goal="Weekly report",
        ),
        agent_name="Alice",
        simulation_id="sim_test",
        store=store,
    )

    offered = store.get_task(offered_task_id)
    assert offered is not None
    assert offered.status == "offered"
    assert offered.origin == "xml_compat"
    assert offered.events[0].event_type == "offered"

    accepted_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="update_status",
            issue_key=offered.issue_key,
            status="OPEN",
            reason="Taking it",
        ),
        agent_name="Bob",
        simulation_id="sim_test",
        store=store,
    )

    accepted = store.get_task(accepted_task_id)
    assert accepted is not None
    assert accepted.status == "open"
    assert accepted.events[-1].event_type == "accepted"


def test_task_server_exposes_offer_lifecycle_tools(
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))

    offered_message = asyncio.run(
        task_server.offer_task(
            simulation_id="sim_test",
            title="Prepare summary",
            description="Collect the latest highlights.",
            assigned_to="Bob",
            actor="Alice",
            parent_goal="Weekly report",
        )
    )
    assert "Task offered:" in offered_message
    assert "TEST-1" in offered_message
    assert "[offered]" in offered_message

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
    assert task_detail["status"] == "offered"
    assert task_detail["origin"] == "mcp_offer"

    listed_offers = asyncio.run(
        task_server.list_my_tasks(
            simulation_id="sim_test",
            actor="Bob",
            status="offered",
        )
    )
    assert "[OFFERED]" in listed_offers
    assert "TEST-1 [offered]" in listed_offers

    accepted_message = asyncio.run(
        task_server.accept_task(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
            reason="Taking it",
        )
    )
    assert "Task accepted:" in accepted_message
    assert "[open]" in accepted_message

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

    artifact_payload = base64.b64encode(b"%PDF-1.4 test deliverable").decode("ascii")
    artifact_message = asyncio.run(
        task_server.save_task_artifact(
            simulation_id="sim_test",
            issue_key="TEST-1",
            filename="brief.pdf",
            content=artifact_payload,
            actor="Bob",
            media_type="application/pdf",
            encoding="base64",
            note="Draft deliverable",
        )
    )
    assert "Task artifact saved:" in artifact_message
    assert "brief.pdf" in artifact_message

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

    stored_task = get_simulation_task_store(
        "sim_test",
        base_dir=simulation_root,
    ).get_task("TEST-1")
    assert stored_task is not None
    assert stored_task.artifact_refs[0].filename == "brief.pdf"
    staged_path = (
        simulation_root / "sim_test" / stored_task.artifact_refs[0].relative_path
    )
    assert staged_path.read_bytes() == b"%PDF-1.4 test deliverable"

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

    progress_message = asyncio.run(
        task_server.update_task_status(
            simulation_id="sim_test",
            issue_key="TEST-1",
            actor="Bob",
            status="in_progress",
            reason="Halfway through the analysis",
        )
    )
    assert "Task updated:" in progress_message
    assert "[in_progress]" in progress_message

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

    second_offer = asyncio.run(
        task_server.offer_task(
            simulation_id="sim_test",
            title="Optional follow-up",
            description="Take this on if capacity allows.",
            assigned_to="Cara",
            actor="Alice",
        )
    )
    assert "TEST-2" in second_offer

    declined_message = asyncio.run(
        task_server.decline_task(
            simulation_id="sim_test",
            issue_key="TEST-2",
            actor="Cara",
            reason="No capacity this round",
        )
    )
    assert "Task declined:" in declined_message
    assert "[declined]" in declined_message


def test_meeting_only_tasks_are_rejected_until_rewritten(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    with pytest.raises(TaskLifecycleError):
        lifecycle.offer_task(
            title="Set up a meeting with Marketing",
            description="Schedule a sync so we can talk through the launch plan.",
            assigned_to="Bob",
            actor="Alice",
        )

    rewritten = lifecycle.offer_task(
        title="Prepare launch alignment brief",
        description="Create a concise summary for Marketing covering launch risks and next steps.",
        assigned_to="Bob",
        actor="Alice",
    )

    assert rewritten.status == "offered"
    assert rewritten.deliverable_type == "research_brief"
    assert "Do not rely on off-screen meetings" in rewritten.acceptance_criteria[1]


def test_update_task_status_supports_progress_notes_and_chat_refs(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    task = lifecycle.create_task(
        title="Compile findings",
        description="Prepare the findings summary.",
        assigned_to="Bob",
        actor="Alice",
    )

    updated = lifecycle.update_task_status(
        task.issue_key,
        actor="Bob",
        status="open",
        reason="Collected three source documents and drafted the outline.",
        event_details={"summary": "Collected three source documents."},
        chat_refs=[
            {
                "platform": "twitter",
                "actor": "Bob",
                "post_id": "42",
                "snippet": "@Alice TEST-1 collected three source documents and drafted the outline.",
                "round_index": 2,
            }
        ],
        round_index=2,
    )

    assert updated.status == "open"
    assert updated.events[-1].event_type == "progress_updated"
    assert updated.events[-1].details["note"] == (
        "Collected three source documents and drafted the outline."
    )
    assert updated.events[-1].chat_refs[0].post_id == "42"
    assert updated.chat_refs[0].snippet.startswith("@Alice TEST-1")


def test_task_tool_routing_keeps_task_lifecycle_tools_available():
    tools = [
        SimpleNamespace(name="lookup_business_data"),
        SimpleNamespace(name="basic_news_search"),
        *[SimpleNamespace(name=name) for name in TASK_MCP_TOOL_ORDER],
    ]

    selected = _ensure_task_tool_access(["lookup_business_data"], tools)

    assert selected is not None
    assert "lookup_business_data" in selected
    for tool_name in TASK_MCP_TOOL_ORDER:
        assert tool_name in selected


def test_phase_one_store_reloads_across_stale_instances_and_persists_metadata(
    simulation_root: Path,
):
    store_a = get_simulation_task_store("sim_test", base_dir=simulation_root)
    store_b = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle_a = TaskLifecycleService("sim_test", store=store_a)
    lifecycle_b = TaskLifecycleService("sim_test", store=store_b)

    assert store_a.list_tasks() == []
    assert store_b.list_tasks() == []

    offered_task = lifecycle_a.offer_task(
        title="Investigate mention-based request",
        description="Review the public delegation and prepare an offer response.",
        assigned_to="Bob",
        actor="Alice",
        origin="mention_compat",
        origin_metadata={"source": "public_post", "platform": "twitter"},
        mention_context={
            "platform": "twitter",
            "source_actor": "Alice",
            "snippet": "@Bob can you take this on?",
        },
        created_round=3,
        due_round=6,
        round_budget=3,
    )
    created_task = lifecycle_b.create_task(
        title="Follow-up analysis",
        description="Prepare the accepted task backlog.",
        assigned_to="Cara",
        actor="Dana",
        origin="api",
    )

    tasks = get_simulation_task_store("sim_test", base_dir=simulation_root).list_tasks()
    assert [task.issue_key for task in tasks] == ["TEST-1", "TEST-2"]

    persisted_task = tasks[0]
    assert persisted_task.status == "offered"
    assert persisted_task.origin == "mention_compat"
    assert persisted_task.origin_metadata == {
        "source": "public_post",
        "platform": "twitter",
    }
    assert persisted_task.mention_context["snippet"] == "@Bob can you take this on?"
    assert persisted_task.created_round == 3
    assert persisted_task.due_round == 6
    assert persisted_task.round_budget == 3
    assert persisted_task.events[0].event_type == "offered"

    payload = json.loads(
        (simulation_root / "sim_test" / "sim_tasks.json").read_text(encoding="utf-8")
    )
    assert payload[0]["origin"] == "mention_compat"
    assert payload[0]["mention_context"]["platform"] == "twitter"
    assert payload[1]["issue_key"] == created_task.issue_key
    assert offered_task.issue_key == "TEST-1"
    assert created_task.issue_key == "TEST-2"


def test_phase_one_lifecycle_supports_accept_decline_and_expire(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    offered = lifecycle.offer_task(
        title="Handle vendor escalation",
        description="Assess the incoming escalation.",
        assigned_to="Bob",
        actor="Alice",
    )
    accepted = lifecycle.accept_task(offered.issue_key, actor="Bob", reason="Taking it")
    assert accepted.status == "open"
    assert accepted.events[-1].event_type == "accepted"

    declined_offer = lifecycle.offer_task(
        title="Backup review",
        description="Review if capacity allows.",
        assigned_to="Cara",
        actor="Alice",
    )
    declined = lifecycle.decline_task(
        declined_offer.issue_key,
        actor="Cara",
        reason="Already committed elsewhere",
    )
    assert declined.status == "declined"
    assert declined.events[-1].event_type == "declined"

    expirable = lifecycle.create_task(
        title="Time-bound summary",
        description="Produce a summary before the simulation ends.",
        assigned_to="Bob",
        actor="Alice",
    )
    expired = lifecycle.expire_task(
        expirable.issue_key,
        actor="system",
        reason="Simulation ended before completion",
    )
    assert expired.status == "expired"
    assert expired.events[-1].event_type == "expired"

    with pytest.raises(TaskAuthorizationError):
        lifecycle.accept_task(offered.issue_key, actor="Mallory")

    with pytest.raises(TaskLifecycleError):
        lifecycle.start_task(declined.issue_key, actor="Cara")


def test_phase_one_artifacts_are_staged_and_registered(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    task = lifecycle.create_task(
        title="Draft deliverable",
        description="Prepare the markdown deliverable.",
        assigned_to="Bob",
        actor="Alice",
    )
    artifact = lifecycle.save_artifact(
        task.issue_key,
        actor="Bob",
        filename="summary.md",
        content="# Summary\n\nDelivered.",
        media_type="text/markdown",
        note="Initial draft",
    )

    staged_path = simulation_root / "sim_test" / artifact.relative_path
    assert staged_path.exists()
    assert staged_path.read_text(encoding="utf-8") == "# Summary\n\nDelivered."

    updated_task = store.get_task(task.issue_key)
    assert updated_task is not None
    assert updated_task.artifact_refs[0].filename == "summary.md"
    assert updated_task.artifact_refs[0].media_type == "text/markdown"
    assert updated_task.events[-1].event_type == "artifact_saved"
    assert updated_task.events[-1].artifact_refs[0].filename == "summary.md"


def test_phase_five_can_complete_task_with_artifact_only(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    task = lifecycle.create_task(
        title="Attach-only deliverable",
        description="Complete this task by uploading the deliverable artifact.",
        assigned_to="Bob",
        actor="Alice",
    )
    lifecycle.save_artifact(
        task.issue_key,
        actor="Bob",
        filename="deliverable.txt",
        content="Final deliverable attached.",
        media_type="text/plain",
    )

    completed = lifecycle.complete_task(
        task.issue_key,
        actor="Bob",
        output="",
    )

    assert completed.status == "done"
    assert completed.output is None
    assert completed.events[-1].event_type == "completed"


def test_phase_five_packages_completed_task_deliverables_into_report_manifest(
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_store = ReportStore()
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))
    report_root = simulation_root.parent / "reports"
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(report_root))

    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    task = lifecycle.create_task(
        title="Package report deliverable",
        description="Produce a markdown artifact for the final report package.",
        assigned_to="Bob",
        actor="Alice",
        parent_goal="Actionable Recommendations",
    )
    lifecycle.save_artifact(
        task.issue_key,
        actor="Bob",
        filename="summary.md",
        content="# Summary\n\nPackaged into report.",
        media_type="text/markdown",
    )
    lifecycle.complete_task(
        task.issue_key,
        actor="Bob",
        output="Final draft delivered.",
    )

    manifest = report_store.package_simulation_deliverables(
        report_id="report_test",
        simulation_id="sim_test",
        report_section_titles=["Actionable Recommendations"],
    )

    assert manifest["report_id"] == "report_test"
    assert len(manifest["deliverables"]) == 1
    entry = manifest["deliverables"][0]
    assert entry["issue_key"] == task.issue_key
    assert entry["mapped_report_section"] == "Actionable Recommendations"
    assert entry["file_types"] == [".md"]
    assert entry["artifacts"][0]["copied"] is True
    assert entry["artifacts"][0]["report_relative_path"] == (
        f"deliverables/{task.issue_key}/summary.md"
    )

    copied_path = (
        report_root / "report_test" / "deliverables" / task.issue_key / "summary.md"
    )
    assert copied_path.exists()
    assert (
        copied_path.read_text(encoding="utf-8") == "# Summary\n\nPackaged into report."
    )

    manifest_path = report_root / "report_test" / "deliverables" / "manifest.json"
    assert manifest_path.exists()


def test_phase_three_notifications_are_persisted_and_consumed(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    lifecycle.offer_task(
        title="Review public request",
        description="Please review the attached note.",
        assigned_to="Bob",
        actor="Alice",
        origin="mention_compat",
        mention_context={"snippet": "@Bob can you review this note?"},
        created_round=2,
    )

    pending = get_simulation_task_store(
        "sim_test",
        base_dir=simulation_root,
    ).list_notifications(recipient="Bob", delivered=False)
    assert len(pending) == 1
    assert pending[0].event_type == "offered"
    assert "Accept or decline" in pending[0].message

    consumed = store.consume_notifications("Bob")
    assert len(consumed) == 1
    assert consumed[0].notification_id == pending[0].notification_id

    assert store.list_notifications(recipient="Bob", delivered=False) == []
    delivered = store.list_notifications(recipient="Bob", delivered=True)
    assert len(delivered) == 1
    assert delivered[0].delivered_at is not None


def test_phase_three_task_context_includes_pending_offers(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    offered = lifecycle.offer_task(
        title="Review delegation",
        description="Please take the first pass on the public follow-up.",
        assigned_to="Bob",
        actor="Alice",
        origin="mention_compat",
        mention_context={"snippet": "@Bob can you take the first pass on this?"},
    )

    context_message = build_task_context_message("Bob", store)
    assert context_message is not None
    assert offered.issue_key in context_message
    assert "accept or decline" in context_message.lower()
    assert "@Bob can you take the first pass on this?" in context_message


def test_phase_four_lifecycle_defaults_round_metadata_from_run_state(
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services.simulation_runner import SimulationRunner

    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(simulation_root))
    SimulationRunner._run_states.pop("sim_test", None)

    (simulation_root / "sim_test" / "run_state.json").write_text(
        json.dumps(
            {
                "simulation_id": "sim_test",
                "runner_status": "running",
                "current_round": 4,
                "total_rounds": 9,
            }
        ),
        encoding="utf-8",
    )

    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    offered = lifecycle.offer_task(
        title="Review executive summary",
        description="Confirm the narrative before the run ends.",
        assigned_to="Bob",
        actor="Alice",
    )

    assert offered.created_round == 4
    assert offered.due_round == 9
    assert offered.round_budget == 5
    assert offered.events[0].round_index == 4

    notifications = store.list_notifications(recipient="Bob", delivered=False)
    assert len(notifications) == 1
    assert notifications[0].round_index == 4


def test_phase_four_xml_actions_stamp_round_metadata(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)

    offered_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="create",
            title="Review late-breaking note",
            assign_to="Bob",
            description="Please confirm whether this should be folded into the wrap-up.",
        ),
        agent_name="Alice",
        simulation_id="sim_test",
        store=store,
        round_index=4,
        total_rounds=7,
    )

    offered = store.get_task(offered_task_id)
    assert offered is not None
    assert offered.created_round == 4
    assert offered.due_round == 7
    assert offered.round_budget == 3

    accepted_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="update_status",
            issue_key=offered.issue_key,
            status="open",
            reason="Taking this on now",
        ),
        agent_name="Bob",
        simulation_id="sim_test",
        store=store,
        round_index=5,
        total_rounds=7,
    )

    completed_task_id = apply_task_action(
        ParsedTaskAction(
            action_type="complete",
            issue_key=offered.issue_key,
            output="Confirmed and folded into the final summary.",
        ),
        agent_name="Bob",
        simulation_id="sim_test",
        store=store,
        round_index=6,
        total_rounds=7,
    )

    accepted = store.get_task(accepted_task_id)
    completed = store.get_task(completed_task_id)
    assert accepted is not None
    assert accepted.events[-2].round_index == 5
    assert completed is not None
    assert completed.events[-1].round_index == 6


def test_phase_four_task_context_includes_clock_and_blocked_escalation(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    offered = lifecycle.offer_task(
        title="Resolve sourcing gap",
        description="Track down the missing source citation before final wrap-up.",
        assigned_to="Bob",
        actor="Alice",
        created_round=3,
        due_round=6,
        round_budget=3,
    )
    lifecycle.accept_task(
        offered.issue_key,
        actor="Bob",
        reason="I will handle it",
        round_index=4,
    )
    blocked = lifecycle.block_task(
        offered.issue_key,
        actor="Bob",
        reason="Waiting on external confirmation",
        round_index=5,
    )

    context_message = build_task_context_message(
        "Bob",
        store,
        current_round=5,
        total_rounds=6,
    )

    assert context_message is not None
    assert "Simulation clock: round 5 of 6." in context_message
    assert "Only 1 future round remains after this turn." in context_message
    assert blocked.issue_key in context_message
    assert "BLOCKED - requires escalation" in context_message
    assert "Due round     : 6" in context_message
    assert "before the run ends" in context_message
    assert "A plain reply is enough here" in context_message


def test_task_guidance_encourages_saving_file_like_artifacts(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    lifecycle.create_task(
        title="Draft the rollout brief",
        description="Produce a markdown brief and a JSON summary for the launch.",
        assigned_to="Bob",
        actor="Alice",
    )

    context_message = build_task_context_message(
        "Bob",
        store,
        current_round=2,
        total_rounds=5,
    )

    assert context_message is not None
    assert "save_task_artifact" in context_message
    assert "markdown brief" in context_message
    assert "media type" in context_message
    assert "results.json" in context_message
    assert "save_task_artifact" in TASK_COORDINATION_SYSTEM_ADDENDUM
    assert "markdown brief" in TASK_COORDINATION_SYSTEM_ADDENDUM
    assert "save_task_artifact" in TASK_MCP_PREFERRED_GUIDANCE
    assert "JSON payload" in TASK_MCP_PREFERRED_GUIDANCE


def test_phase_four_expire_unfinished_tasks_marks_remaining_work_terminal(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    offered = lifecycle.offer_task(
        title="Pending offer",
        description="Still waiting on acceptance.",
        assigned_to="Bob",
        actor="Alice",
    )
    open_task = lifecycle.create_task(
        title="Open work",
        description="Accepted manually earlier.",
        assigned_to="Bob",
        actor="Alice",
    )
    in_progress_task = lifecycle.create_task(
        title="In-flight work",
        description="Needs one more pass.",
        assigned_to="Bob",
        actor="Alice",
    )
    lifecycle.start_task(
        in_progress_task.issue_key,
        actor="Bob",
        reason="Working through the backlog",
        round_index=2,
    )
    completed_task = lifecycle.create_task(
        title="Completed work",
        description="Already done.",
        assigned_to="Bob",
        actor="Alice",
    )
    lifecycle.complete_task(
        completed_task.issue_key,
        actor="Bob",
        output="Delivered",
        round_index=3,
    )

    expired_issue_keys = expire_unfinished_tasks(
        simulation_id="sim_test",
        store=store,
        final_round=6,
    )

    assert set(expired_issue_keys) == {
        offered.issue_key,
        open_task.issue_key,
        in_progress_task.issue_key,
    }

    expired_offer = store.get_task(offered.issue_key)
    expired_open = store.get_task(open_task.issue_key)
    expired_in_progress = store.get_task(in_progress_task.issue_key)
    persisted_done = store.get_task(completed_task.issue_key)

    assert expired_offer is not None
    assert expired_offer.status == "expired"
    assert expired_offer.events[-1].round_index == 6
    assert "Simulation ended at round 6" in expired_offer.events[-1].details["note"]

    assert expired_open is not None
    assert expired_open.status == "expired"

    assert expired_in_progress is not None
    assert expired_in_progress.status == "expired"

    assert persisted_done is not None
    assert persisted_done.status == "done"


def test_phase_three_processes_mention_driven_offer(simulation_root: Path):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)

    structured_pairs = process_task_actions_for_round(
        actual_actions=[
            {
                "trace_rowid": 17,
                "agent_id": 1,
                "agent_name": "Alice",
                "action_type": "CREATE_POST",
                "action_args": {
                    "content": "@Bob can you review the rollout draft and send back notes?",
                    "post_id": 11,
                },
            }
        ],
        simulation_id="sim_test",
        store=store,
        platform="twitter",
        round_index=4,
        mention_aliases={"bob": "Bob"},
        structured_offer_pairs=set(),
    )

    tasks = store.list_tasks()
    assert len(tasks) == 1

    offered = tasks[0]
    assert offered.origin == "mention_compat"
    assert offered.status == "offered"
    assert offered.assigned_by == "Alice"
    assert offered.assigned_to == "Bob"
    assert offered.created_round == 4
    assert offered.mention_context["post_id"] == 11
    assert offered.mention_context["trace_rowid"] == 17
    assert (
        offered.events[0]
        .details["mention_context"]["snippet"]
        .startswith("@Bob can you review")
    )
    assert ("Alice", "Bob") in structured_pairs

    notifications = store.list_notifications(recipient="Bob", delivered=False)
    assert len(notifications) == 1
    assert notifications[0].category == "task_offer"
    assert notifications[0].task_ref == offered.issue_key


def test_phase_three_meeting_like_mentions_queue_rewrite_notification(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)

    structured_pairs = process_task_actions_for_round(
        actual_actions=[
            {
                "trace_rowid": 21,
                "agent_id": 1,
                "agent_name": "Alice",
                "action_type": "CREATE_POST",
                "action_args": {
                    "content": "@Bob please set up a meeting with Marketing so we can talk through this.",
                    "post_id": 14,
                },
            }
        ],
        simulation_id="sim_test",
        store=store,
        platform="twitter",
        round_index=4,
        mention_aliases={"bob": "Bob"},
        structured_offer_pairs=set(),
    )

    assert structured_pairs == set()
    assert store.list_tasks() == []

    notifications = store.list_notifications(recipient="Bob", delivered=False)
    assert len(notifications) == 1
    assert notifications[0].category == "task_rewrite_needed"
    assert "rewriting it into a concrete brief" in notifications[0].message


def test_phase_three_public_issue_key_updates_are_linked_to_tasks(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    task = lifecycle.create_task(
        title="Draft supplier summary",
        description="Prepare the supplier summary for Alice.",
        assigned_to="Bob",
        actor="Alice",
    )

    process_task_actions_for_round(
        actual_actions=[
            {
                "trace_rowid": 33,
                "agent_id": 2,
                "agent_name": "Bob",
                "action_type": "CREATE_POST",
                "action_args": {
                    "content": f"@Alice {task.issue_key} is in progress. I have the first draft ready.",
                    "post_id": 27,
                },
            }
        ],
        simulation_id="sim_test",
        store=store,
        platform="twitter",
        round_index=5,
        mention_aliases={"alice": "Alice"},
        structured_offer_pairs=set(),
    )

    updated = store.get_task(task.issue_key)
    assert updated is not None
    assert updated.events[-1].event_type == "public_update"
    assert updated.events[-1].details["summary"].startswith("@Alice")
    assert updated.events[-1].chat_refs[0].post_id == "27"
    assert updated.chat_refs[-1].snippet.startswith("@Alice")


def test_phase_three_skips_mention_offer_when_structured_offer_exists_in_round(
    simulation_root: Path,
):
    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    lifecycle.offer_task(
        title="Structured offer",
        description="Canonical offer created earlier in the round.",
        assigned_to="Bob",
        actor="Alice",
        origin="mcp_offer",
    )

    structured_offer_pairs = collect_structured_offer_pairs(
        store, existing_task_ids=set()
    )
    process_task_actions_for_round(
        actual_actions=[
            {
                "trace_rowid": 23,
                "agent_id": 1,
                "agent_name": "Alice",
                "action_type": "CREATE_POST",
                "action_args": {
                    "content": "@Bob can you take this on after the structured handoff?",
                    "post_id": 14,
                },
            }
        ],
        simulation_id="sim_test",
        store=store,
        platform="twitter",
        round_index=5,
        mention_aliases={"bob": "Bob"},
        structured_offer_pairs=structured_offer_pairs,
    )

    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].origin == "mcp_offer"

    notifications = store.list_notifications(recipient="Bob", delivered=False)
    assert len(notifications) == 1


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


def test_simulation_task_mutation_routes_are_disabled_by_default(task_api_client):
    create_response = task_api_client.post(
        "/api/simulation/sim_test/tasks",
        json={
            "title": "Assemble brief",
            "description": "Summarize the key developments.",
            "assigned_to": "Bob",
            "actor": "Alice",
        },
    )

    assert create_response.status_code == 403
    assert "manage tasks autonomously" in create_response.get_json()["error"]

    lifecycle = TaskLifecycleService("sim_test")
    task = lifecycle.create_task(
        title="Draft response",
        description="Prepare the response memo.",
        assigned_to="Bob",
        actor="Alice",
    )

    start_response = task_api_client.post(
        f"/api/simulation/sim_test/tasks/{task.issue_key}/start",
        json={"actor": "Bob", "reason": "Reviewing source material"},
    )
    assert start_response.status_code == 403
    assert "manage tasks autonomously" in start_response.get_json()["error"]


def test_simulation_task_api_supports_create_query_and_detail(
    task_api_client_with_mutations,
):
    create_response = task_api_client_with_mutations.post(
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

    list_response = task_api_client_with_mutations.get(
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

    detail_response = task_api_client_with_mutations.get(
        "/api/simulation/sim_test/tasks/TEST-1",
        query_string={"actor": "Bob"},
    )
    assert detail_response.status_code == 200
    detail_task = detail_response.get_json()["data"]["task"]
    assert detail_task["issue_key"] == "TEST-1"
    assert detail_task["assigned_by"] == "Alice"

    unauthorized_response = task_api_client_with_mutations.get(
        "/api/simulation/sim_test/tasks/TEST-1",
        query_string={"actor": "Mallory"},
    )
    assert unauthorized_response.status_code == 403
    assert "not allowed to view task" in unauthorized_response.get_json()["error"]

    invalid_filter_response = task_api_client_with_mutations.get(
        "/api/simulation/sim_test/tasks",
        query_string={"completed": "maybe"},
    )
    assert invalid_filter_response.status_code == 400


def test_simulation_task_api_supports_start_block_and_complete(
    task_api_client_with_mutations,
):
    task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks",
        json={
            "title": "Draft response",
            "description": "Prepare the response memo.",
            "assigned_to": "Bob",
            "actor": "Alice",
        },
    )

    started_response = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks/TEST-1/start",
        json={"actor": "Bob", "reason": "Reviewing source material"},
    )
    assert started_response.status_code == 200
    started_task = started_response.get_json()["data"]["task"]
    assert started_task["status"] == "in_progress"
    assert started_task["latest_event"]["event_type"] == "started"

    blocked_response = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks/TEST-1/block",
        json={"actor": "Bob", "reason": "Waiting for legal review"},
    )
    assert blocked_response.status_code == 200
    blocked_task = blocked_response.get_json()["data"]["task"]
    assert blocked_task["status"] == "blocked"
    assert blocked_task["latest_event"]["event_type"] == "blocked"

    completed_response = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks/TEST-1/complete",
        json={"actor": "Bob", "output": "Memo delivered"},
    )
    assert completed_response.status_code == 200
    completed_task = completed_response.get_json()["data"]["task"]
    assert completed_task["status"] == "done"
    assert completed_task["output"] == "Memo delivered"
    assert completed_task["latest_event"]["event_type"] == "completed"

    unauthorized_start = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks/TEST-1/start",
        json={"actor": "Mallory", "reason": "Hijacking task"},
    )
    assert unauthorized_start.status_code == 403

    completed_filter_response = task_api_client_with_mutations.get(
        "/api/simulation/sim_test/tasks",
        query_string={"completed": "true"},
    )
    assert completed_filter_response.status_code == 200
    completed_payload = completed_filter_response.get_json()["data"]
    assert completed_payload["count"] == 1
    assert completed_payload["tasks"][0]["status"] == "done"


def test_phase_six_task_api_supports_accept_decline_and_artifacts(
    task_api_client_with_mutations,
):
    lifecycle = TaskLifecycleService("sim_test")

    offered = lifecycle.offer_task(
        title="Accept me",
        description="Offered task requiring acceptance.",
        assigned_to="Bob",
        actor="Alice",
    )
    decline_offer = lifecycle.offer_task(
        title="Decline me",
        description="Optional follow-up.",
        assigned_to="Cara",
        actor="Alice",
    )

    accepted_response = task_api_client_with_mutations.post(
        f"/api/simulation/sim_test/tasks/{offered.issue_key}/accept",
        json={"actor": "Bob", "reason": "Taking it"},
    )
    assert accepted_response.status_code == 200
    accepted_task = accepted_response.get_json()["data"]["task"]
    assert accepted_task["status"] == "open"
    assert accepted_task["latest_event"]["event_type"] == "accepted"

    declined_response = task_api_client_with_mutations.post(
        f"/api/simulation/sim_test/tasks/{decline_offer.issue_key}/decline",
        json={"actor": "Cara", "reason": "No bandwidth"},
    )
    assert declined_response.status_code == 200
    declined_task = declined_response.get_json()["data"]["task"]
    assert declined_task["status"] == "declined"

    artifact_response = task_api_client_with_mutations.post(
        f"/api/simulation/sim_test/tasks/{offered.issue_key}/artifacts",
        json={
            "actor": "Bob",
            "filename": "brief.txt",
            "content": "Deliverable body",
            "media_type": "text/plain",
        },
    )
    assert artifact_response.status_code == 201
    artifact_payload = artifact_response.get_json()["data"]
    artifact_id = artifact_payload["artifact"]["artifact_id"]
    assert artifact_payload["artifact"]["filename"] == "brief.txt"

    artifacts_response = task_api_client_with_mutations.get(
        f"/api/simulation/sim_test/tasks/{offered.issue_key}/artifacts",
        query_string={"actor": "Bob"},
    )
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.get_json()["data"]["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["download_url"].endswith(f"/{artifact_id}")

    download_response = task_api_client_with_mutations.get(
        f"/api/simulation/sim_test/tasks/{offered.issue_key}/artifacts/{artifact_id}",
        query_string={"actor": "Bob"},
    )
    assert download_response.status_code == 200
    assert download_response.data == b"Deliverable body"

    completed_response = task_api_client_with_mutations.post(
        f"/api/simulation/sim_test/tasks/{offered.issue_key}/complete",
        json={"actor": "Bob", "output": ""},
    )
    assert completed_response.status_code == 200
    completed_task = completed_response.get_json()["data"]["task"]
    assert completed_task["status"] == "done"
    assert completed_task["artifact_count"] == 1


def test_phase_six_task_api_supports_generic_status_updates_and_metadata(
    task_api_client_with_mutations,
):
    create_response = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks",
        json={
            "title": "Prepare KPI summary",
            "description": "Produce a concise KPI summary for leadership.",
            "assigned_to": "Bob",
            "actor": "Alice",
            "deliverable_type": "analytics_summary",
            "acceptance_criteria": [
                "Include the top three KPIs.",
                "Note any material risk or upside.",
            ],
            "tool_plan": "Use lookup_business_data first, then save a markdown brief if needed.",
        },
    )

    assert create_response.status_code == 201
    created_task = create_response.get_json()["data"]["task"]
    assert (
        created_task["deliverable_metadata"]["deliverable_type"] == "analytics_summary"
    )
    assert (
        created_task["deliverable_metadata"]["acceptance_criteria"][0]
        == "Include the top three KPIs."
    )

    update_response = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks/TEST-1/status",
        json={
            "actor": "Bob",
            "status": "open",
            "reason": "Collected the KPI inputs and drafted the summary outline.",
        },
    )
    assert update_response.status_code == 200
    updated_task = update_response.get_json()["data"]["task"]
    assert updated_task["status"] == "open"
    assert updated_task["latest_event"]["event_type"] == "progress_updated"
    assert updated_task["latest_status_note"] == (
        "Collected the KPI inputs and drafted the summary outline."
    )


def test_task_api_rejects_meeting_only_requests(task_api_client_with_mutations):
    create_response = task_api_client_with_mutations.post(
        "/api/simulation/sim_test/tasks",
        json={
            "title": "Set up a meeting with Marketing",
            "description": "Schedule a sync to talk through the campaign.",
            "assigned_to": "Bob",
            "actor": "Alice",
        },
    )

    assert create_response.status_code == 400
    assert (
        "Meeting-style tasks are not executable" in create_response.get_json()["error"]
    )


def test_phase_six_task_list_and_run_status_detail_include_task_events(
    task_api_client,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services.simulation_runner import SimulationRunner

    lifecycle = TaskLifecycleService("sim_test")
    task = lifecycle.offer_task(
        title="Round-aware task",
        description="Ensure the richer API payload exposes deadlines.",
        assigned_to="Bob",
        actor="Alice",
        created_round=3,
        due_round=6,
        round_budget=3,
    )
    lifecycle.accept_task(
        task.issue_key, actor="Bob", reason="Taking it", round_index=4
    )

    fake_run_state = SimpleNamespace(
        current_round=5,
        rounds=[],
        to_dict=lambda: {
            "simulation_id": "sim_test",
            "runner_status": "running",
            "current_round": 5,
            "total_rounds": 8,
            "progress_percent": 62.5,
            "twitter_actions_count": 1,
            "reddit_actions_count": 0,
            "total_actions_count": 1,
        },
    )

    class FakeAction:
        def __init__(self, round_num: int, timestamp: str, platform: str):
            self.round_num = round_num
            self.timestamp = timestamp
            self.platform = platform

        def to_dict(self):
            return {
                "round_num": self.round_num,
                "timestamp": self.timestamp,
                "platform": self.platform,
                "agent_id": 1,
                "agent_name": "Alice",
                "action_type": "CREATE_POST",
                "action_args": {"content": "Progress update"},
                "result": None,
                "success": True,
            }

    fake_actions = [FakeAction(5, "2026-04-23T10:00:00", "twitter")]
    monkeypatch.setattr(
        SimulationRunner, "get_run_state", lambda simulation_id: fake_run_state
    )
    monkeypatch.setattr(
        SimulationRunner,
        "get_all_actions",
        lambda simulation_id, platform=None, round_num=None: [
            action
            for action in fake_actions
            if (platform is None or action.platform == platform)
            and (round_num is None or action.round_num == round_num)
        ],
    )

    list_response = task_api_client.get("/api/simulation/sim_test/tasks")
    assert list_response.status_code == 200
    listed_task = list_response.get_json()["data"]["tasks"][0]
    assert listed_task["deadline"]["remaining_rounds"] == 1
    assert listed_task["offer_pending"] is False

    detail_response = task_api_client.get(
        "/api/simulation/sim_test/run-status/detail",
        query_string={
            "include_tasks": "true",
            "include_task_events": "true",
            "include_merged_feed": "true",
        },
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.get_json()["data"]
    assert detail_payload["tasks"][0]["issue_key"] == task.issue_key
    assert any(
        event["entry_type"] == "task_event" for event in detail_payload["task_events"]
    )
    assert any(item["entry_type"] == "action" for item in detail_payload["merged_feed"])
    assert any(
        item["entry_type"] == "task_event" for item in detail_payload["merged_feed"]
    )


def test_phase_six_report_api_supports_deliverables_and_task_scoped_chat(
    task_api_client,
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))

    lifecycle = TaskLifecycleService("sim_test")
    task = lifecycle.create_task(
        title="Report-context task",
        description="Provide deliverable context to report chat.",
        assigned_to="Bob",
        actor="Alice",
    )
    lifecycle.save_artifact(
        task.issue_key,
        actor="Bob",
        filename="notes.md",
        content="# Notes\n\nContext for report chat.",
        media_type="text/markdown",
    )
    lifecycle.complete_task(task.issue_key, actor="Bob", output="Attached notes")

    report = Report(
        report_id="report_test",
        simulation_id="sim_test",
        graph_id="graph_demo",
        simulation_requirement="Assess cross-functional alignment.",
        status=ReportStatus.COMPLETED,
        markdown_content="# Report\n\nGenerated content.",
        created_at="2026-04-23T09:00:00",
        completed_at="2026-04-23T09:05:00",
    )
    ReportManager.save_report(report)
    ReportStore().package_simulation_deliverables(
        report_id="report_test",
        simulation_id="sim_test",
        report_section_titles=["Actionable Recommendations"],
    )

    packaged_report = ReportManager.get_report("report_test")
    assert packaged_report is not None
    assert "## Packaged Deliverables" in packaged_report.markdown_content
    assert task.issue_key in packaged_report.markdown_content
    assert "deliverables/" in packaged_report.markdown_content

    deliverables_response = task_api_client.get("/api/report/report_test/deliverables")
    assert deliverables_response.status_code == 200
    deliverables_payload = deliverables_response.get_json()["data"]
    assert deliverables_payload["report_id"] == "report_test"
    assert deliverables_payload["deliverables"][0]["issue_key"] == task.issue_key

    captured: dict = {}

    class FakeReportAgent:
        def __init__(self, graph_id, simulation_id, simulation_requirement):
            captured["init"] = {
                "graph_id": graph_id,
                "simulation_id": simulation_id,
                "simulation_requirement": simulation_requirement,
            }

        def chat(self, message, chat_history=None, task_ref=None):
            captured["chat"] = {
                "message": message,
                "chat_history": chat_history,
                "task_ref": task_ref,
            }
            return {
                "response": "Focused answer",
                "tool_calls": [],
                "sources": [task_ref] if task_ref else [],
            }

    monkeypatch.setattr(report_api, "ReportAgent", FakeReportAgent)
    monkeypatch.setattr(
        report_api.SimulationManager,
        "get_simulation",
        lambda self, simulation_id: SimpleNamespace(
            simulation_id=simulation_id,
            project_id="proj_test",
            graph_id="graph_demo",
        ),
    )
    monkeypatch.setattr(
        report_api.ProjectManager,
        "get_project",
        lambda project_id: SimpleNamespace(
            graph_id="graph_demo",
            simulation_requirement="Assess cross-functional alignment.",
        ),
    )

    chat_response = task_api_client.post(
        "/api/report/chat",
        json={
            "simulation_id": "sim_test",
            "message": "Summarize the work product for this task.",
            "task_ref": task.issue_key,
            "chat_history": [{"role": "user", "content": "Earlier question"}],
        },
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.get_json()["data"]
    assert chat_payload["task_ref"] == task.issue_key
    assert captured["chat"]["task_ref"] == task.issue_key


def test_phase_eight_migrates_legacy_artifacts_and_default_metadata(
    simulation_root: Path,
):
    legacy_payload = [
        {
            "task_id": "legacy-task-artifacts",
            "issue_key": "TEST-7",
            "sequence_number": 7,
            "simulation_id": "sim_test",
            "title": "Legacy task with artifacts",
            "description": "Migrated from the pre-artifact_refs schema.",
            "assigned_by": "Alice",
            "assigned_to": "Bob",
            "status": "done",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T01:00:00+00:00",
            "output": "Legacy output",
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "filename": "legacy.txt",
                    "relative_path": "task_artifacts/TEST-7/artifact-1-legacy.txt",
                    "media_type": "text/plain",
                    "size_bytes": 12,
                    "checksum_sha256": "abc123",
                    "created_at": "2024-01-01T00:30:00+00:00",
                    "created_by": "Bob",
                    "kind": "deliverable",
                }
            ],
        }
    ]
    (simulation_root / "sim_test" / "sim_tasks.json").write_text(
        json.dumps(legacy_payload),
        encoding="utf-8",
    )

    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    task = store.list_tasks()[0]

    assert task.origin == "legacy"
    assert task.origin_metadata == {}
    assert task.mention_context == {}
    assert task.created_round is None
    assert task.due_round is None
    assert task.round_budget is None
    assert task.deadline_at is None
    assert len(task.artifact_refs) == 1
    assert task.artifact_refs[0].filename == "legacy.txt"
    assert task.events[0].event_type == "created"

    migrated_payload = json.loads(
        (simulation_root / "sim_test" / "sim_tasks.json").read_text(encoding="utf-8")
    )
    assert "artifacts" not in migrated_payload[0]
    assert migrated_payload[0]["origin"] == "legacy"
    assert migrated_payload[0]["artifact_refs"][0]["filename"] == "legacy.txt"
    assert migrated_payload[0]["origin_metadata"] == {}
    assert migrated_payload[0]["mention_context"] == {}


def test_phase_eight_smoke_flow_from_mention_offer_to_report_package(
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))
    report_root = simulation_root.parent / "reports"
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(report_root))

    store = get_simulation_task_store("sim_test", base_dir=simulation_root)
    lifecycle = TaskLifecycleService("sim_test", store=store)

    structured_pairs = process_task_actions_for_round(
        actual_actions=[
            {
                "trace_rowid": 101,
                "agent_id": 1,
                "agent_name": "Alice",
                "action_type": "CREATE_POST",
                "action_args": {
                    "content": "@Bob can you prepare the final rollout brief and share it back?",
                    "post_id": 88,
                },
            }
        ],
        simulation_id="sim_test",
        store=store,
        platform="twitter",
        round_index=2,
        total_rounds=6,
        mention_aliases={"bob": "Bob"},
        structured_offer_pairs=set(),
    )

    assert ("Alice", "Bob") in structured_pairs

    offered_task = store.list_tasks()[0]
    assert offered_task.status == "offered"
    assert offered_task.origin == "mention_compat"

    lifecycle.accept_task(
        offered_task.issue_key,
        actor="Bob",
        reason="I will take this on",
        round_index=3,
    )
    lifecycle.start_task(
        offered_task.issue_key,
        actor="Bob",
        reason="Drafting the brief",
        round_index=3,
    )
    lifecycle.block_task(
        offered_task.issue_key,
        actor="Bob",
        reason="Waiting on one final input",
        round_index=4,
    )
    lifecycle.start_task(
        offered_task.issue_key,
        actor="Bob",
        reason="Input arrived, resuming",
        round_index=5,
    )
    lifecycle.save_artifact(
        offered_task.issue_key,
        actor="Bob",
        filename="rollout-brief.md",
        content="# Rollout Brief\n\nFinal deliverable.",
        media_type="text/markdown",
    )
    lifecycle.complete_task(
        offered_task.issue_key,
        actor="Bob",
        output="Final rollout brief delivered.",
        round_index=6,
    )

    completed = store.get_task(offered_task.issue_key)
    assert completed is not None
    assert completed.status == "done"
    assert [event.event_type for event in completed.events] == [
        "offered",
        "accepted",
        "started",
        "blocked",
        "started",
        "artifact_saved",
        "completed",
    ]

    manifest = ReportStore().package_simulation_deliverables(
        report_id="report_smoke",
        simulation_id="sim_test",
    )

    assert manifest["summary"] == {
        "packaged_task_count": 1,
        "copied_artifact_count": 1,
        "missing_source_count": 0,
        "failed_copy_count": 0,
    }
    entry = manifest["deliverables"][0]
    assert entry["issue_key"] == offered_task.issue_key
    assert entry["copied_artifact_count"] == 1
    assert entry["failed_artifact_count"] == 0
    assert entry["artifacts"][0]["copied"] is True
    assert entry["artifacts"][0]["report_relative_path"] == (
        f"deliverables/{offered_task.issue_key}/rollout-brief.md"
    )

    copied_path = (
        report_root
        / "report_smoke"
        / "deliverables"
        / offered_task.issue_key
        / "rollout-brief.md"
    )
    assert copied_path.exists()
    assert (
        copied_path.read_text(encoding="utf-8")
        == "# Rollout Brief\n\nFinal deliverable."
    )


def test_phase_eight_emits_metrics_for_migration_compat_expiry_and_packaging(
    simulation_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    simulation_id = "sim_metrics"
    sim_dir = simulation_root / simulation_id
    sim_dir.mkdir(parents=True)
    (sim_dir / "state.json").write_text(
        json.dumps({"project_id": "proj_metrics", "graph_id": "graph_demo"}),
        encoding="utf-8",
    )
    (sim_dir / "sim_tasks.json").write_text(
        json.dumps(
            [
                {
                    "task_id": "legacy-open-task",
                    "simulation_id": simulation_id,
                    "title": "Legacy open task",
                    "description": "Needs migration and later expiry.",
                    "assigned_by": "Alice",
                    "assigned_to": "Bob",
                    "status": "open",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "artifacts": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    metric_logger = logging.getLogger("test.task_pipeline")
    metric_logger.handlers.clear()
    metric_logger.propagate = True
    metric_logger.setLevel(logging.INFO)
    monkeypatch.setattr(task_observability, "logger", metric_logger)
    caplog.set_level(logging.INFO)

    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root))
    report_root = simulation_root.parent / "reports"
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(report_root))

    store = get_simulation_task_store(simulation_id, base_dir=simulation_root)
    store.list_tasks()

    apply_task_action(
        ParsedTaskAction(
            action_type="create",
            title="Legacy XML offer",
            assign_to="Bob",
            description="Created through the compatibility path.",
        ),
        agent_name="Alice",
        simulation_id=simulation_id,
        store=store,
        round_index=2,
        total_rounds=5,
    )

    expire_unfinished_tasks(
        simulation_id=simulation_id,
        store=store,
        final_round=5,
    )

    lifecycle = TaskLifecycleService(simulation_id, store=store)
    deliverable_task = lifecycle.create_task(
        title="Artifact packaging failure",
        description="Creates a copy failure metric during packaging.",
        assigned_to="Bob",
        actor="Alice",
    )
    lifecycle.save_artifact(
        deliverable_task.issue_key,
        actor="Bob",
        filename="evidence.txt",
        content="evidence",
        media_type="text/plain",
    )
    lifecycle.complete_task(
        deliverable_task.issue_key,
        actor="Bob",
        output="Ready for report packaging.",
    )

    def failing_copy(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(report_agent_service.shutil, "copy2", failing_copy)

    manifest = ReportStore().package_simulation_deliverables(
        report_id="report_metrics",
        simulation_id=simulation_id,
    )

    assert manifest["summary"]["failed_copy_count"] == 1
    assert manifest["deliverables"][0]["artifacts"][0]["copy_error"] == "disk full"

    metric_messages = [
        record.getMessage()
        for record in caplog.records
        if "TASK_PIPELINE_METRIC" in record.getMessage()
    ]

    assert any("name=migration_applied" in message for message in metric_messages)
    assert any("name=compat_path_used" in message for message in metric_messages)
    assert any("name=expired_tasks" in message for message in metric_messages)
    assert any("name=packaging_failure" in message for message in metric_messages)
    assert any("name=packaging_summary" in message for message in metric_messages)
