"""Workflow template definitions."""

from __future__ import annotations

from forge.workflows.models import WorkflowDefinition, WorkflowTemplate

_STANDARD_STAGES = (
    "repository",
    "workset",
    "context",
    "plan",
    "patch",
    "validate",
    "verify",
    "policy",
)

_STANDARD_ARTIFACTS = (
    "workset",
    "context_bundle",
    "implementation_plan",
    "patch",
    "verification",
    "policy_evaluation",
)

FEATURE = WorkflowDefinition(
    template=WorkflowTemplate.feature,
    name="Feature",
    description="End-to-end workflow for implementing a new feature.",
    stage_names=_STANDARD_STAGES,
    output_artifact_types=_STANDARD_ARTIFACTS,
)

BUGFIX = WorkflowDefinition(
    template=WorkflowTemplate.bugfix,
    name="Bug Fix",
    description="End-to-end workflow for diagnosing and patching a bug.",
    stage_names=_STANDARD_STAGES,
    output_artifact_types=_STANDARD_ARTIFACTS,
)

REFACTOR = WorkflowDefinition(
    template=WorkflowTemplate.refactor,
    name="Refactor",
    description="End-to-end workflow for a targeted refactoring change.",
    stage_names=_STANDARD_STAGES,
    output_artifact_types=_STANDARD_ARTIFACTS,
)

ALL_DEFINITIONS: dict[WorkflowTemplate, WorkflowDefinition] = {
    WorkflowTemplate.feature: FEATURE,
    WorkflowTemplate.bugfix: BUGFIX,
    WorkflowTemplate.refactor: REFACTOR,
}
