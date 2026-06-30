"""Application service architecture tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from forge.models.types import ModelResponse
from forge.services import repository_service, workset_service
from forge.services.planning_service import PlanningService, generate
from forge.worksets.store import save


def _make_repo(tmp_path: Path) -> None:
    (tmp_path / "forge").mkdir()
    (tmp_path / "forge" / "models.py").write_text(
        "class ModelManager:\n    pass\n",
        encoding="utf-8",
    )


def _make_workset(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    save(
        tmp_path,
        {
            "schema_version": 1,
            "name": "model",
            "query": "model manager",
            "root": str(tmp_path),
            "created_at": "2026-06-28T00:00:00+00:00",
            "updated_at": "2026-06-28T00:00:00+00:00",
            "include_tests": False,
            "max_results": 10,
            "files": [
                {
                    "path": "forge/models.py",
                    "score": 10,
                    "category": "source",
                    "reasons": [{"signal": "filename", "detail": "model", "points": 10}],
                    "manual": False,
                }
            ],
        },
    )


def _model_manager() -> MagicMock:
    manager = MagicMock()
    manager.config.return_value = MagicMock(default_model="qwen2.5")
    manager.ask.return_value = ModelResponse(
        content="# Forge Implementation Plan\n\nDo the thing.",
        model="qwen2.5",
        provider="ollama",
    )
    return manager


def test_planning_service_coordinates_model_and_save(tmp_path: Path) -> None:
    _make_workset(tmp_path)

    plan = PlanningService(_model_manager()).generate_plan(
        tmp_path,
        "Add model validation",
        "model",
        save=True,
    )

    assert plan.saved_path is not None
    assert plan.saved_path.exists()
    assert plan.memory_item_id is not None


def test_planning_service_payload_is_adapter_ready(tmp_path: Path) -> None:
    _make_workset(tmp_path)

    payload = generate(
        tmp_path,
        "Add model validation",
        "model",
        model_manager=_model_manager(),
        use_memory=False,
    )

    assert payload["workset"] == "model"
    assert payload["workset_name"] == "model"
    assert payload["memory_used"] is False


def test_workset_context_service_can_render_json_without_saving(tmp_path: Path) -> None:
    _make_workset(tmp_path)

    result = workset_service.generate_context(
        tmp_path,
        "model",
        output_json=True,
        save=False,
    )

    assert result["path"] is None
    assert json.loads(result["content"])["workset"] == "model"
    assert not list((tmp_path / ".forge" / "context").glob("*.json"))


def test_workset_context_filename_timestamp_is_not_malformed(tmp_path: Path) -> None:
    """Regression for I-09.

    Saved context bundle filenames previously encoded the UTC "+00:00" offset
    as a confusing "...-0000-00" suffix because "+" was stripped right before
    the offset digits. The timestamp segment should now be a clean
    "<date>T<time>Z" with no stray "+"/extra digit groups.
    """
    _make_workset(tmp_path)

    result = workset_service.generate_context(tmp_path, "model", save=True)

    saved_path = Path(result["path"])
    assert saved_path.exists()
    stem = saved_path.stem  # "model-20260629T142024Z"
    assert "+" not in stem
    ts_part = stem.split("model-", 1)[1]
    assert ts_part.endswith("Z")
    assert "-0000-00" not in stem
    # "model" + "-" + "YYYYMMDDT HHMMSS" (15 chars) + "Z"
    assert len(ts_part) == len("20260629T142024Z")


def test_repository_service_preserves_glob_filtered_search(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / "README.md").write_text("ModelManager docs\n", encoding="utf-8")

    result = repository_service.search(
        tmp_path,
        "ModelManager",
        globs=["*.md"],
    )

    assert [match["path"] for match in result["matches"]] == ["README.md"]
