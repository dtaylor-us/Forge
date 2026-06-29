"""Tests for the local Forge web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from forge.cli.app import app as cli_app
from forge.memory.manager import MemoryManager
from forge.memory.models import MemoryType
from forge.web.app import create_app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Sample\n\nForge memory and worksets.\n", encoding="utf-8"
    )
    (tmp_path / "forge").mkdir()
    (tmp_path / "forge" / "app.py").write_text(
        "class ModelManager:\n    pass\n",
        encoding="utf-8",
    )
    return tmp_path


def test_app_creation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    app = create_app(root)

    assert app.state.repo_root == root


def test_dashboard_route_returns_200(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/")

    assert response.status_code == 200
    assert "Forge" in response.text


def test_dashboard_shows_branch_for_git_repo(tmp_path: Path, monkeypatch) -> None:
    from forge.services import git_service as gs

    monkeypatch.setattr(gs, "branch", lambda root=None: {"branch": "main"})
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/")

    assert response.status_code == 200
    assert "main" in response.text


def test_dashboard_shows_dash_for_non_git_repo(tmp_path: Path, monkeypatch) -> None:
    from forge.services import git_service as gs

    monkeypatch.setattr(gs, "branch", lambda root=None: {"branch": None})
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/")

    assert response.status_code == 200
    assert "—" in response.text


def test_project_api_returns_metadata(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/project")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["project_name"] == tmp_path.name
    assert "paths" in payload["data"]


def test_repository_detect_api_shape(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/repository/detect")

    assert response.status_code == 200
    assert response.json()["data"]["languages"] == ["Python"]


def test_repository_tree_api_shape(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/repository/tree")

    assert response.status_code == 200
    assert "lines" in response.json()["data"]


def test_repository_search_api_handles_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("forge.repository.grep.shutil.which", lambda _: None)
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/repository/search", params={"q": "ModelManager"})

    assert response.status_code == 200
    matches = response.json()["data"]["matches"]
    assert matches[0]["path"] == "forge/app.py"


def test_workset_list_route_and_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    page = client.get("/worksets")
    api = client.get("/api/worksets")

    assert page.status_code == 200
    assert api.status_code == 200
    assert api.json()["data"]["worksets"] == []


def test_workbench_evolution_pages_return_200(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    for path in ("/execution", "/artifacts", "/patches"):
        response = client.get(path)
        assert response.status_code == 200


def test_artifacts_and_patches_api_shape(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    artifacts = client.get("/api/artifacts")
    patches = client.get("/api/patches")

    assert artifacts.status_code == 200
    assert "artifacts" in artifacts.json()["data"]
    assert "relationships" in artifacts.json()["data"]
    assert patches.status_code == 200
    assert "patches" in patches.json()["data"]


def test_workset_suggest_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))
    (tmp_path / ".forge" / "worksets").mkdir(parents=True)
    (tmp_path / ".forge" / "worksets" / "generated.json").write_text(
        '{"name": "generated", "query": "model manager"}',
        encoding="utf-8",
    )

    response = client.post("/api/worksets/suggest", json={"query": "model manager"})

    assert response.status_code == 200
    candidates = response.json()["data"]["candidates"]
    assert candidates
    assert all(not item["path"].startswith(".forge/") for item in candidates)


def test_workset_create_and_detail_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    create = client.post(
        "/api/worksets/create",
        json={"name": "model", "query": "model manager"},
    )
    detail = client.get("/api/worksets/model")
    page = client.get("/worksets/model")

    assert create.status_code == 200
    assert detail.status_code == 200
    assert page.status_code == 200
    assert detail.json()["data"]["name"] == "model"


def test_context_generation_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))
    client.post("/api/worksets/create", json={"name": "model", "query": "model manager"})

    response = client.post("/api/worksets/model/context", json={})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["path"].endswith(".md")
    assert "preview" in data


def test_planning_api_with_mocked_service(tmp_path: Path, monkeypatch) -> None:
    def fake_generate(root, task, workset, **kwargs):
        return {
            "task": task,
            "workset": workset,
            "model": kwargs.get("model") or "fake",
            "generated_at": "2026-06-28T00:00:00+00:00",
            "content": "Plan body",
            "saved_path": None,
            "memory_used": kwargs.get("use_memory", True),
            "memory_item_id": None,
        }

    monkeypatch.setattr("forge.web.routes.planning.planning_service.generate", fake_generate)
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.post(
        "/api/plans/generate",
        json={"task": "Add UI", "workset": "model", "use_memory": False},
    )

    assert response.status_code == 200
    assert response.json()["data"]["content"] == "Plan body"
    assert response.json()["data"]["memory_used"] is False


def test_memory_search_and_timeline_api(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    MemoryManager.from_root(root).add(
        type=MemoryType.decision,
        title="Use FastAPI",
        repository=str(root),
        summary="Local web API",
        tags=["web"],
    )
    client = TestClient(create_app(root))

    search = client.get("/api/memory/search", params={"q": "FastAPI"})
    timeline = client.get("/api/memory/timeline")

    assert search.status_code == 200
    assert search.json()["data"]["results"][0]["item"]["title"] == "Use FastAPI"
    assert timeline.json()["data"]["items"][0]["title"] == "Use FastAPI"


def test_decision_and_investigation_create_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    decision = client.post(
        "/api/decisions/create",
        json={"title": "Use service layer", "summary": "Keep routes thin."},
    )
    investigation = client.post(
        "/api/investigations/create",
        json={"title": "Search issue", "summary": "Investigated search behavior."},
    )

    assert decision.status_code == 200
    assert decision.json()["data"]["type"] == "decision"
    assert investigation.status_code == 200
    assert investigation.json()["data"]["type"] == "investigation"


def test_error_response_shape(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/worksets/missing")

    assert response.status_code == 404
    payload = response.json()
    assert payload["ok"] is False
    assert "message" in payload["error"]
    assert "type" in payload["error"]


def test_root_path_is_fixed_to_resolved_repo(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    app = create_app(root)
    client = TestClient(app)

    response = client.get("/api/project")

    assert app.state.repo_root == root.resolve()
    assert response.json()["data"]["repo_root"] == str(root.resolve())


def test_workflows_page_returns_200(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/workflows")

    assert response.status_code == 200
    assert "Workflow" in response.text


def test_workflows_api_empty(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/workflows")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["runs"] == []
    assert data["data"]["count"] == 0


def test_workflows_templates_api(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/workflows/templates")

    assert response.status_code == 200
    templates = response.json()["data"]["templates"]
    names = {t["template"] for t in templates}
    assert {"feature", "bugfix", "refactor"}.issubset(names)


def test_workflow_detail_missing_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/workflows/nonexistent-id")

    assert response.status_code == 404


def test_workflow_detail_api_missing_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.get("/api/workflows/nonexistent-id")

    assert response.status_code == 404
    assert response.json()["ok"] is False


def test_workflow_detail_page_and_api_with_run(tmp_path: Path) -> None:
    from forge.workflows.models import WorkflowRun, WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    root = _repo(tmp_path)
    reg = WorkflowRegistry.from_root(root)
    run = WorkflowRun(
        id="test-run-1",
        template=WorkflowTemplate.feature,
        task="Add feature",
        repository=str(root),
    )
    reg.save(run)
    client = TestClient(create_app(root))

    page = client.get("/workflows/test-run-1")
    api = client.get("/api/workflows/test-run-1")

    assert page.status_code == 200
    assert "Add feature" in page.text
    assert api.status_code == 200
    assert api.json()["data"]["run"]["task"] == "Add feature"


def test_workflows_api_lists_persisted_runs(tmp_path: Path) -> None:
    from forge.workflows.models import WorkflowRun, WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    root = _repo(tmp_path)
    reg = WorkflowRegistry.from_root(root)
    reg.save(
        WorkflowRun(
            id="r1",
            template=WorkflowTemplate.feature,
            task="feat",
            repository=str(root),
        )
    )
    reg.save(
        WorkflowRun(
            id="r2",
            template=WorkflowTemplate.bugfix,
            task="fix",
            repository=str(root),
        )
    )
    client = TestClient(create_app(root))

    response = client.get("/api/workflows")

    assert response.status_code == 200
    runs = response.json()["data"]["runs"]
    ids = {r["id"] for r in runs}
    assert {"r1", "r2"}.issubset(ids)


def test_workflow_start_api_invalid_template(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.post("/api/workflows", json={"template": "invalid", "task": "do something"})

    assert response.status_code == 422
    assert response.json()["ok"] is False


def test_workflow_start_api_missing_task(tmp_path: Path) -> None:
    client = TestClient(create_app(_repo(tmp_path)))

    response = client.post("/api/workflows", json={"template": "feature", "task": ""})

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_dashboard_includes_workflow_metrics(tmp_path: Path) -> None:
    from forge.workflows.models import WorkflowRun, WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    root = _repo(tmp_path)
    reg = WorkflowRegistry.from_root(root)
    reg.save(
        WorkflowRun(
            id="dash1",
            template=WorkflowTemplate.feature,
            task="Dashboard test",
            repository=str(root),
        )
    )
    client = TestClient(create_app(root))

    response = client.get("/")

    assert response.status_code == 200
    assert "Workflow" in response.text


def test_workflows_page_shows_run_in_table(tmp_path: Path) -> None:
    from forge.workflows.models import WorkflowRun, WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    root = _repo(tmp_path)
    reg = WorkflowRegistry.from_root(root)
    reg.save(
        WorkflowRun(
            id="show1",
            template=WorkflowTemplate.refactor,
            task="Refactor auth module",
            repository=str(root),
        )
    )
    client = TestClient(create_app(root))

    response = client.get("/workflows")

    assert response.status_code == 200
    assert "Refactor auth module" in response.text


def test_workflow_detail_shows_empty_stage_state(tmp_path: Path) -> None:
    from forge.workflows.models import WorkflowRun, WorkflowTemplate
    from forge.workflows.registry import WorkflowRegistry

    root = _repo(tmp_path)
    reg = WorkflowRegistry.from_root(root)
    reg.save(
        WorkflowRun(
            id="empty1",
            template=WorkflowTemplate.bugfix,
            task="Fix login",
            repository=str(root),
        )
    )
    client = TestClient(create_app(root))

    response = client.get("/workflows/empty1")

    assert response.status_code == 200
    assert "Fix login" in response.text
    assert "Engineering Pipeline" in response.text


def test_cli_web_help() -> None:
    result = runner.invoke(cli_app, ["web", "--help"])

    assert result.exit_code == 0
    assert "--host" in result.stdout
    assert "--port" in result.stdout
    assert "--reload" in result.stdout


def test_cli_web_public_host_warning(tmp_path: Path, monkeypatch) -> None:
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = runner.invoke(
        cli_app,
        ["web", "--host", "0.0.0.0", "--root", str(_repo(tmp_path))],
    )

    assert result.exit_code == 0
    assert "Warning" in result.stdout
    assert "Forge Web UI running at http://0.0.0.0:8765" in result.stdout
    assert calls
