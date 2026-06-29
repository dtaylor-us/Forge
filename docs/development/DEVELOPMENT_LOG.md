# Dev Log

## Phase 6.3 — Engineering Knowledgebase CLI Completion

### Summary

Exposed the `forge decision create` and `forge investigation create` command groups, and added `forge memory timeline`, so the README-documented workflows now work exactly as written.

### Changes

- **`forge/memory/models.py`**: Added `MemoryType.investigation` to the enum so investigations have their own first-class type rather than piggybacking on `bug`.
- **`forge/memory/store.py`**: Mapped `MemoryType.investigation` → `investigations/` subdirectory.
- **`forge/services/memory_service.py`**: Updated `create_decision` and `create_investigation` to accept `tags` and `related_files`; `create_investigation` now uses `MemoryType.investigation`.
- **`forge/cli/app.py`**: Added `decision_app` and `investigation_app` typer groups; added `forge decision create`, `forge investigation create`, and `forge memory timeline` commands with `--summary`, `--workset`, `--tag`, `--file`, and `--json` options.
- **`tests/test_web.py`**: Updated web test assertion to reflect `investigation` type (was `bug`).
- **`tests/test_memory.py`**: Added 13 new tests covering all Phase 6.3 requirements.

### CLI Surface

```bash
forge decision create "Use JWT for gateway authentication"
forge decision create "Use JWT" --summary "Stateless, scales well" --tag auth --workset gateway
forge investigation create "Planning timeout with Ollama"
forge investigation create "Planning timeout" --tag performance --file forge/planning/planner.py
forge memory timeline
forge memory timeline --json
```

### Verification

- `python3 -m pytest` passed with 494 tests (13 new).
- `python3 -m ruff check .` passed.

---

## 2026-06-28 — Phase 6.1: Dogfood Readiness Hardening

### Completed

- **Patch validation hardened**: `patch_service.validate()` now runs `git apply --check` via `GitService.apply_check()` after structural validation. JSON output includes `structural_valid`, `apply_check_valid`, `errors`, and `suggestions` fields. A patch that fails `git apply --check` is reported as invalid with actionable next steps.
- **Apply command reordered**: `forge apply` now validates patch existence and structure before showing the confirmation prompt. A missing or invalid patch exits immediately without prompting.
- **`--yes` semantics documented and tested**: `--yes` skips the interactive confirmation only; policy is always evaluated. `--force` is required to bypass allowed policy failures. Tests verify both behaviors.
- **Workflow validate uses GitService**: Replaced direct `subprocess.run(["git", "apply", "--check"])` in `WorkflowEngine._stage_validate` with `GitService.apply_check()`. No direct git subprocess calls outside `GitService`.
- **Workflow failure guidance**: Validate stage failure messages include actionable next steps: inspect the patch, regenerate, revalidate.
- **Implementation prompt strengthened**: `_IMPLEMENTATION_SYSTEM_INSTRUCTIONS` now explicitly forbids `/dev/null` diffs for existing files. The workset file table header clearly states all listed files already exist in the repository.
- **Verification recommendations**: `VerificationExecutor.execute()` now populates `recommendations` with deterministic guidance for failed steps (black, ruff, pytest, npm, build, missing tool).
- **Telemetry suppressed in non-verbose mode**: `configure_logging(verbose=False)` now sets logging level to `WARNING`, preventing model telemetry (INFO-level) from appearing in stderr during normal CLI use.
- **Dashboard branch**: `repository_service.detect()` now includes `current_branch` via `GitService.branch()`. Dashboard `BRANCH: —` is resolved.
- **29 new tests** covering all of the above. All 465 tests pass.

### Architecture Notes

Patch validation is now a two-phase check: structural diff format check (fast, offline) followed by `git apply --check` (requires a git repository). The `apply_check_valid` field is `None` (not attempted) when the repo is not a git repository. The CLI renders both phases clearly on failure.

The workflow engine's validate stage now calls `patch_service.validate()` for the structural check and then independently calls `GitService.apply_check()` directly — keeping the stages decoupled but ensuring both checks run in sequence.

---

## 2026-06-28 — Phase 6.1: Engineering Workflow Workbench

### Completed

- Added `forge/web/routes/workflows.py` with GET `/workflows`, GET `/workflows/{run_id}`, GET `/api/workflows`, GET `/api/workflows/templates`, GET `/api/workflows/{run_id}`, POST `/api/workflows`.
- Created `forge/web/templates/workflows.html` — workflow list page with table, status/template filters, empty state, template cards with metadata, and a Start Workflow modal.
- Created `forge/web/templates/workflow_detail.html` — rich detail view showing summary hero, visual pipeline with per-node status/duration, artifact relationships, per-stage cards with error display, and engineering timeline.
- Updated `forge/web/templates/base.html` — added Workflows as second nav item (after Dashboard), added to command palette, removed stale "Workflow History (planned)" item.
- Updated `forge/web/templates/dashboard.html` — evolved to Engineering Command Center: added Current Workflow card, updated hero copy, added `workflow_runs` metric at top of metrics grid, updated activity timeline to link workflow runs, replaced "What To Do Next" with smart `next_action` recommendation.
- Updated `forge/web/routes/dashboard.py` — loads `workflow_service.list_runs()`, computes `latest_run`, adds `next_action()` and `_next_action()` helper, adds `workflow_runs` metric, extends `_activity()` with workflow run events.
- Updated `forge/web/app.py` — registered `workflows.router`.
- Extended `forge/web/static/styles.css` — added `status-error`, `status-neutral`, `pipeline-failed`, `pipeline-running`, `timeline-dot.danger`, `data-table`, `filter-btn.active`, `action-btn-primary`.
- Added 11 new web tests in `tests/test_web.py` covering: workflow list page, empty API, templates API, 404 detail, 404 detail API, detail page with run, list with persisted runs, invalid template start, missing task start, dashboard workflow metrics, detail stage state.
- All 31 web tests pass. All 23 workflow engine tests pass.

### Architecture Notes

The UI is a thin presentation layer. Workflow data flows exclusively through `WorkflowService` → `WorkflowRegistry`. The dashboard calls `workflow_service.list_runs()` to derive latest run and next action without reading `.forge/workflows/` directly. No orchestration logic lives in routes or templates. The Start Workflow modal POSTs to `/api/workflows` which delegates entirely to `workflow_service.run_workflow()`.

### Design Decisions

- Navigation order: Dashboard → Workflows → Repository → … puts the workflow as the primary engineering object immediately after the command center.
- Dashboard `next_action` is derived from the latest run's status/patch/verification/policy fields — it always recommends a concrete next step rather than static links.
- Workflow detail renders all eight pipeline stages even when a run has fewer (pending stages shown as grey "Pending"), giving the engineer a stable mental model of the full lifecycle regardless of where a run stopped.

---

## 2026-06-28 — Phase 6.0: Engineering Workflow Engine

### Completed

- Added `forge/workflows/` orchestration package: `models.py`, `templates.py`, `registry.py`, `engine.py`, `workflow.py`, `__init__.py`.
- `WorkflowTemplate` StrEnum: `feature`, `bugfix`, `refactor`, `custom`.
- `WorkflowRun` dataclass tracks id, template, task, repository, status, stages, artifacts, workset/patch/verification/policy references, and timing.
- `WorkflowStage` dataclass captures name, description, service, status, timing, artifact references, and error message.
- `WorkflowDefinition` describes static template metadata (stage names, output artifact types).
- Three initial templates: `Feature`, `BugFix`, `Refactor` — each runs identical eight-stage pipeline.
- `WorkflowEngine` orchestrates eight stages in fixed order: repository → workset → context → plan → patch → validate → verify → policy. Each stage calls exactly one existing application service. Stage failure stops the run, preserves prior artifacts, and marks status `failed`.
- `WorkflowRegistry` reads/writes workflow run records to `.forge/workflows/*.json`.
- `forge/services/workflow_service.py` is the public entry point: `run_workflow`, `list_templates`, `list_runs`, `show_run`.
- `forge/artifacts/discovery.py` extended with `_workflow_artifacts()` — workflow runs surface as `ArtifactType.workflow` with relationships to workset and patch artifacts.
- `forge/project/paths.py` extended with `workflows_dir = .forge/workflows`.
- CLI commands: `forge workflow feature|bugfix|refactor "<task>"`, `forge workflow run <template> "<task>"`, `forge workflow templates`, `forge workflow list`, `forge workflow show <id>`. All support `--json`.
- 23 new tests in `tests/test_workflow.py` covering templates, models, registry, stage ordering, all three workflow types, stage failure, partial artifact preservation, no-apply guarantee, artifact registration, JSON output, artifact discovery, service delegation, and service reuse invariants.
- No existing tests broken. Total test count: 424.

### Architecture Notes

The Workflow Engine is a pure orchestration layer. It contains no business logic, no domain models beyond run state, and no model calls. All substantive work remains in existing application services. The engine imports services inside stage methods (lazy local imports) to keep the module boundary clean and make service-level mocking straightforward in tests.

The `WorkflowRegistry` is the sole writer to `.forge/workflows/`. The `ArtifactRegistry` discovers workflow runs read-only via `forge/artifacts/discovery.py`.

No patch is ever automatically applied. The workflow stops at policy evaluation and emits `forge apply patches/<name>` as the next step.

### Design Decisions

- Three templates share identical stage pipelines by intent. Template identity is preserved in run metadata and artifact descriptions. Future templates (Documentation, Review, Repair) can introduce different stage sets without redesign.
- Stage failure preserves all artifacts produced before the failing stage. This supports future repair loop workflows that resume from the last successful stage.
- `WorkflowEngine` uses local imports inside stage methods rather than module-level imports so tests can patch at the service module level without import-order sensitivity.

---

## 2026-06-28 — Phase 5.8: Engineering Policies and Guarded Patch Apply

### Completed

- Added `forge/policies/` domain package: `models.py`, `defaults.py`, `evaluator.py`, `service.py`, `__init__.py`.
- `ForgePolicy` dataclass captures four policy sections: `patch`, `verification`, `git`, `apply`.
- Default policy enforces: valid patch, max 25 changed files, max 1000 added/removed lines, verification required and must pass, git repo required, clean worktree required, human confirmation required.
- Optional `.forge/policy.yaml` override; defaults used when file is absent.
- `PolicyEvaluator` produces a `PolicyEvaluation` with per-check `status` / `message` / `severity`.
- `PolicyEvaluation` status: `pass | warn | fail`. Failures with `severity=error` block apply.
- Added `forge/services/policy_service.py` and `forge/services/apply_service.py`.
- `apply_service.apply()` enforces the full guarded workflow:
  1. Resolve and validate patch.
  2. `git apply --check` (dry run) — apply is aborted if this fails.
  3. Load verification report from `.forge/verifications/` (latest by default).
  4. Evaluate policy.
  5. Block on policy failure unless `--force` and `policy.apply.allow_force`.
  6. Apply patch via `GitService.apply()`.
  7. Persist apply record under `.forge/applications/`.
- `GitService` extended with `apply_check(patch_path)` and `apply(patch_path)`. Never commits. Never creates branches.
- Added `added_lines` and `removed_lines` to `Patch` model and `inspect_patch()`.
- Added `applications_dir` to `ForgePaths` and `_SUBDIRS`.
- Added `ArtifactType.policy_evaluation` and `ArtifactType.patch_application`.
- CLI commands:
  - `forge policy show [--json]` — display active policy.
  - `forge policy check <patch> [--json] [--verification <report>]` — evaluate policy.
  - `forge apply <patch> [--yes] [--force] [--json] [--verification <report>]` — guarded apply.
- `--yes` skips interactive confirmation but does not bypass policy.
- `--force` may bypass policy failures only when `policy.apply.allow_force` is true.
- Apply records include: id, patch name, affected files, verification report, policy status, branch, commit before apply, forced flag.
- No model calls. No commits. No repair loop.
- 26 new tests in `tests/test_policy.py`. All 401 tests pass.

## 2026-06-28 — GitService Foundation

### Completed

- Added `forge/git/` domain package: `models.py`, `service.py`, `__init__.py`.
- `GitService` is read-only. It never applies patches, creates commits, or
  modifies any file. All `git` subprocess calls are centralized here.
- `GitStatus` datamodel captures: `is_git_repository`, `root`, `branch`,
  `commit`, `clean`, `staged_files`, `modified_files`, `deleted_files`,
  `untracked_files`.
- Added `forge/services/git_service.py` application service facade.
- Added `forge git status` and `forge git status --json` CLI commands.
- Added `forge git branch` and `forge git branch --json` CLI commands.
- CLI exits non-zero when outside a git repository.
- Added 14 tests covering: non-git directory, clean repo, dirty repo, staged
  files, modified files, untracked files, branch detection, JSON output, and
  CLI error paths.

### Design Note

`GitService` is the intended gateway for future `forge apply`. Before any patch
is applied to the working tree, the gate must check repository cleanliness
through `GitService.status()`. No source modification occurs in this phase.

## 2026-06-28 — Engineering Verification Execution

### Completed

- Added `forge verify` execution while preserving `forge verify --detect` for
  strategy inspection.
- Added `forge/verification/runner.py`, `executor.py`, `report.py`, and
  `artifact.py`.
- Verification now executes detected formatter, linter, build, and test steps
  through a reusable command runner instead of the CLI.
- Each step records command, working directory, timestamps, duration, exit code,
  stdout, stderr, timeout state, exception, and status.
- Verification continues after recoverable failures and returns deterministic
  exit codes: `0` for pass, `1` for verification failure, and `2` for
  infrastructure errors.
- Added JSON output and optional `--patch`, `--plan`, `--workset`, `--output`,
  and `--timeout` metadata/configuration flags.
- Persisted structured reports under `.forge/verifications/` and registered
  them as Engineering Artifacts with optional workset, plan, and patch
  relationships.
- Updated the artifact registry, README, and architecture docs for verification
  reports.

### Future Workflow

Patch Apply, Repair Loop, Continuous Verification, and Policy Gate workflows
should consume `VerificationReport` artifacts rather than parsing shell output.
Verification remains local-first and does not mutate repository source files.

### Verification

- `.venv/bin/ruff check forge tests` passed.
- `pytest tests/test_verification.py tests/test_artifacts.py tests/test_cli.py`
  passed with 51 tests.

## 2026-06-28 — Phase 5.6: Forge Workbench UX Evolution

### Completed

- Reorganized the Workbench navigation around engineering workflows: Dashboard,
  Repository, Worksets, Planning, Execution, Artifacts, Patches, Engineering
  Memory, Project, and disabled planned surfaces for Verification,
  Architecture, and Workflow History.
- Rebuilt the Dashboard as the engineering command center with repository
  summary, workflow visualization, registry-backed metrics, recent engineering
  activity, and next-step links.
- Added a read-only Execution page that visualizes the canonical execution
  pipeline and the latest prepared `ExecutionRequest` when a saved plan/workset
  is available.
- Added a unified Artifact Explorer backed by `ArtifactRegistry`, including
  artifact type, name, created time, metadata, origin, and relationship detail.
- Added a Patch Explorer for saved patch artifacts with searchable rows,
  affected-file counts, validation status, unified diff preview, validate, show,
  and browser download actions. Verify, Apply, and Repair are visible as coming
  soon.
- Expanded Repository, Worksets, Planning, and Engineering Memory pages with
  workflow-oriented sections and relationship links without duplicating backend
  logic.

### Architecture Notes

- This phase is presentation-layer only. Web routes remain thin adapters over
  application services, the Artifact Registry, and domain packages.
- No CLI behavior changed.
- No patch application, verification execution, repair loop, or backend workflow
  history feature was introduced.

### Verification

- `python3 -m pytest tests/test_web.py` passed with 19 tests.
- `python3 -m pytest` passed with 349 tests.
- `.venv/bin/ruff check .` passed.

## 2026-06-28 — Phase 5.3: Unified Engineering Artifact Registry

### Problem Solved

Forge now has a shared Engineering Artifact Registry that can represent
repository metadata, worksets, context bundles, implementation plans,
Engineering Memory entries, and saved patches through one read-only model.

### Architecture Decisions

- Added `forge/artifacts/` as a new internal package with models, metadata
  helpers, discovery, and a registry facade.
- Introduced `ArtifactType`, `Artifact`, and `ArtifactRelationship` as the
  common vocabulary for current and future engineering artifacts.
- Discovery preserves existing storage locations and file formats:
  `.forge/project.json`, `.forge/worksets/`, `.forge/context/`,
  `.forge/plans/`, `.forge/memory/`, and `.forge/patches/`.
- Artifact identifiers are deterministic. Intrinsic IDs are used where existing
  artifacts provide them; path-based artifacts use stable hashed IDs.
- Metadata loading is tolerant of partial or malformed files so the registry can
  enumerate old artifacts without forcing migration.
- Relationships are sparse and explicit. The registry records workset and memory
  lineage only where it can be determined reliably.
- No CLI commands were added. Existing end-user workflows, services, storage,
  and file formats remain unchanged.

### Files Added

- `forge/artifacts/__init__.py`
- `forge/artifacts/models.py`
- `forge/artifacts/metadata.py`
- `forge/artifacts/discovery.py`
- `forge/artifacts/registry.py`
- `tests/test_artifacts.py`

### Files Modified

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/development/DEVELOPMENT_LOG.md`

### Future Extension Points

- Execution records
- Verification reports
- Repair reports
- Architecture analysis
- Review reports
- Documentation updates
- Knowledge capture
- Workflow history

---

## 2026-06-28 — `forge implement` Patch Generation MVP

### Problem Solved

Forge now has its first end-to-end Engineering Execution capability:
`forge implement "<task>" --workset <name>` generates a human-reviewable raw
unified diff from a task and persisted workset.

### Architecture Decisions

- Added `ImplementationService` under `forge/services/` so the CLI remains a
  thin adapter.
- Reused `ExecutionService` to prepare workset context, selected model,
  Engineering Memory, and execution request metadata.
- Added a dedicated implementation prompt builder in `forge/execution/` that
  requires raw unified diff output only, with no Markdown fences or
  explanations.
- Provider calls go through `ModelManager`.
- Patch validation and affected-file extraction reuse `forge/patches`.
- Valid model diffs are saved under `.forge/patches/` unless `--output` is
  provided. Invalid model responses are preserved under
  `.forge/patches/invalid/`.
- This MVP does not apply patches, edit source files directly, call `git apply`,
  run verification, implement repair loops, or change the web UI.

### CLI

```bash
forge workset create copy-mermaid --query "mermaid copy button"
forge implement "Add a Copy Mermaid button next to rendered Mermaid diagrams" \
  --workset copy-mermaid
forge patch show <generated-patch>
forge patch validate <generated-patch>
```

### Files Added

- `forge/services/implementation_service.py`
- `tests/test_implement.py`

### Files Modified

- `forge/cli/app.py`
- `forge/execution/execution_prompt.py`
- `forge/patches/__init__.py`
- `forge/patches/service.py`
- `README.md`
- `docs/development/DEVELOPMENT_LOG.md`

---

## 2026-06-28 — Application Service Architecture Refactor

### Problem Solved

Forge had service modules, but orchestration responsibilities were still split
between CLI commands, planning code, workset/context modules, memory commands,
and web routes. This refactor establishes a consistent Application Service
architecture before future Engineering Execution, Patch Generation,
Verification, Repair, and Architecture Intelligence add more workflow
complexity.

### Architecture Decisions

- `PlanningService` is now the canonical application-service pattern. It
  coordinates context bundle generation, Engineering Memory lookup/write,
  provider calls through `ModelManager`, and optional plan persistence.
- `forge.planning.generate_plan` remains as a compatibility facade, but new
  orchestration should be added under `forge/services/`.
- CLI commands now delegate repository, workset/context, project, planning,
  memory, and patch inspection workflows to application services, while keeping
  Typer parsing and Rich output in the adapter layer.
- Web routes continue to use services; the dashboard now uses project service
  helpers for recent plan artifacts instead of reading `.forge/plans` directly.
- Domain packages remain focused on deterministic business logic: repository
  inspection, workset scoring, context rendering, memory search/similarity,
  planning prompts/rendering/storage, and patch validation.
- Patch support remains inspection and validation only. This refactor does not
  add patch generation, patch application, source editing, or verification
  loops.

### Files Added

- `docs/ARCHITECTURE.md`
- `forge/services/patch_service.py`
- `tests/test_application_services.py`

### Files Modified

- `forge/services/planning_service.py` — canonical planning orchestrator.
- `forge/planning/planner.py` — compatibility facade into `PlanningService`.
- `forge/services/repository_service.py` — repository file/search workflows.
- `forge/services/workset_service.py` — workset add/remove and context artifact
  workflow.
- `forge/services/memory_service.py` — related-memory and rebuild workflows.
- `forge/services/project_service.py` — root/path/recent-plan helpers.
- `forge/cli/app.py` — thin CLI adapter over application services.
- `forge/web/routes/dashboard.py` — service-backed recent plans.
- `README.md` — documented the Application Service architecture.
- `docs/development/DEVELOPMENT_LOG.md`

### Guidance For Future Work

- New workflows belong in `forge/services/`.
- Business rules belong in the relevant domain package.
- Provider calls go through `forge/models/`.
- Infrastructure concerns stay local and explicit.
- Future `ExecutionService`, `VerificationService`, `PatchService`, and
  `ArchitectureService` should follow the `PlanningService` shape.

---

## 2026-06-28 — Engineering Execution Architecture Foundation

### Problem Solved

Planning previously ended at a generated implementation plan. Forge now has an
Engineering Execution pipeline that prepares all execution inputs as typed,
stage-by-stage orchestration without editing repositories, generating patches,
invoking git, implementing verification/repair, or calling model providers.

### Architecture Decisions

- Added `forge/execution/` as the reusable execution orchestration package.
- Execution is intentionally separate from Planning: planning creates advisory
  implementation plans, while execution coordinates how approved work will move
  through future implementation stages.
- Added a provider-independent `ExecutionPipeline` and `ExecutionOrchestrator`
  that run insertable stages and collect `ExecutionStageResult` timing, status,
  metadata, and errors.
- The initial canonical stages are Load Workset, Load Context, Load Engineering
  Memory, Load Implementation Plan, Assemble Execution Context, and Execution
  Complete.
- The existing `ExecutionService` still prepares an `ExecutionRequest` for
  callers that need the prompt-oriented contract, while the pipeline is now the
  canonical orchestration mechanism for future implementation workflows.
- The pipeline returns structured data only. It does not mutate source
  repositories, generate diffs, apply patches, call git, run tests, implement
  repair, update documentation, update memory, or ask model providers.
- The execution prompt builder reuses planning context and memory rendering helpers, but remains isolated so execution-specific instructions can evolve independently from planning.
- Added typed execution vocabulary: `ExecutionStage`, `ExecutionContext`,
  `ExecutionRequest`, `ExecutionResult`, `ExecutionStatus`,
  `ExecutionStageResult`, and `ExecutionTarget`.

### Future Extension Points

Future phases can plug into the prepared request contract without redesigning the orchestration layer:

- Patch Generation
- Patch Validation
- Patch Storage
- Patch Review
- Patch Application
- Verification
- Repair
- Documentation Updates
- Knowledge Capture

### Files Added

- `forge/execution/__init__.py`
- `forge/execution/models.py`
- `forge/execution/pipeline.py`
- `forge/execution/stages.py`
- `forge/execution/orchestrator.py`
- `forge/execution/execution_models.py`
- `forge/execution/execution_prompt.py`
- `forge/execution/execution_result.py`
- `forge/execution/execution_service.py`
- `tests/test_execution.py`

### Files Modified

- `forge/planning/prompts.py` — exposed reusable context and memory rendering helpers for planning-adjacent prompts.
- `docs/development/DEVELOPMENT_LOG.md`

---

## 2026-06-28 — Patch Management Foundation

### Problem Solved

Forge now has first-class storage, inspection, and validation for patch artifacts under `.forge/patches/`. This gives future implementation workflows a deterministic place to save and review raw diffs before any source-editing behavior exists.

### Commands Added

```bash
forge patch list
forge patch list --json
forge patch show <patch-name-or-path>
forge patch show <patch-name-or-path> --json
forge patch validate <patch-name-or-path>
forge patch validate <patch-name-or-path> --json
```

### Architecture Decisions

- Added `forge/patches/` with a `Patch` dataclass and a small service layer for directory management, lookup, content reading, validation, and affected-file extraction.
- Patch files live in `.forge/patches/`; the directory is created by `forge init` and on demand when patch listing/storage helpers need it.
- Validation is intentionally conservative: raw git or unified diffs with hunk markers pass, while empty files, prose, Markdown fenced responses, and files without hunks fail.
- Affected file extraction is best effort for `diff --git a/path b/path`, `--- a/path`, and `+++ b/path`.
- This phase does not generate patches, apply patches, edit source files, call AI providers, run verification/repair loops, or change the web UI.
- This prepares the storage and validation foundation for a future `forge implement` command.

### Files Added

- `forge/patches/__init__.py`
- `forge/patches/models.py`
- `forge/patches/service.py`
- `tests/test_patches.py`

### Files Modified

- `forge/cli/app.py` — registered the `forge patch` command group.
- `forge/project/paths.py` — added `patches_dir`.
- `forge/project/initializer.py` — creates `.forge/patches/`.
- `README.md` — documented patch management commands while keeping patch generation planned.
- `docs/development/DEVELOPMENT_LOG.md`

---

## 2026-06-28 — Phase 4.2: Web UI Redesign — Premium Engineering Workbench

### Problem Solved

The Phase 4.1 web UI was a functional CRUD application with a light theme, plain HTML tables, and no design hierarchy. Phase 4.2 transforms the UI into a dark-first engineering workbench that feels closer to Cursor, Linear, or Vercel than a typical internal tool.

### Design System

Complete rewrite of `forge/web/static/styles.css`:

- Dark-first color palette: near-black `#0c0d0f` background, charcoal `#131416` panels, Forge Orange `#f97316` brand accent.
- Inter typeface loaded via Google Fonts with system-font fallback. Monospace stack for code/paths.
- Full component library as CSS utility classes: hero cards, metric cards, workset cards, memory timeline, score bars, reason tags, status pills, tech chips, split pane, empty states, toasts, command palette, collapsible sidebar, action buttons.
- Lucide icon library loaded via CDN for consistent iconography throughout.

### Shell Redesign (`base.html`)

- Persistent collapsible sidebar with `localStorage` state, Forge orange logo mark, Lucide nav icons, "soon" badges for upcoming sections (Architecture, Settings).
- Topbar with breadcrumb navigation, centered global search bar, Active status pill.
- Command palette triggered by `⌘K` with keyboard navigation (`↑↓` to move, `↵` to open, `Esc` to dismiss).
- Global `showToast()` helper available to all pages for success/error feedback.
- Global `copyText()` helper for clipboard copy actions.

### Pages Redesigned

**Dashboard** — Hero card with project name, initialized status pill, git/language/framework tags, and radial orange glow. 4-column quick action grid. 3-column activity section (Recent Worksets, Recent Plans, Memory Timeline) with proper empty states including illustration icon, description, and CTA button.

**Worksets** — Auto-fill card grid replacing the plain table. Each card shows name, query excerpt, file count, and size. Side panel with Suggest Files form and Create Workset form. Create navigates to the new workset detail after success.

**Workset Detail** — Metric row (file count, top score, category count, status). File table with score bars (visual fill proportional to score), category tags (primary/test/config), and signal reason pills showing signal name and point contribution. Refresh and Generate Context buttons with loading spinners and toast feedback.

**Planning** — Split-pane layout: configuration panel left (task textarea, workset selector, model override, timeout, toggles), plan output panel right. Output renders as formatted markdown via `marked.js` CDN. Toggle between rendered and raw. Copy button. Loading spinner during generation.

**Memory** — Inline search bar at the top of the timeline. Timeline view with colored dots (blue for decisions, amber for investigations) and connecting lines. Side panel with typed New Decision and New Investigation forms, each with distinct icon/color treatment. Search results rendered inline without page reload.

**Memory Detail** — Two-column layout: summary and related files left, metadata sidebar right (ID with copy button, type tag, workset link, tags, created date).

**Repository** — 4 detection cards (Languages, Frameworks, Source Roots, Test Roots), each with a colored icon. Monospace file tree panel. Inline full-text search with result display.

**Project** — Status pills for initialized/git state, tech chip grids for detected stack, copy-to-clipboard on forge directory path.

**Error** — Centered error state with large status code, icon, and back to dashboard button.

### Architecture Notes

- All JavaScript remains page-local vanilla JS. No build pipeline added.
- `marked.js` CDN added to planning page only for markdown rendering.
- Lucide icon CDN added to base template for consistent iconography.
- Sidebar collapse state persisted in `localStorage` across page loads.
- Toast and copy helpers defined once in `base.html` and available globally.
- `.claude/launch.json` added to support `preview_start` from Claude Code.

### Files Modified

- `forge/web/static/styles.css` — complete rewrite
- `forge/web/templates/base.html` — new AppShell with sidebar, topbar, command palette, toasts
- `forge/web/templates/dashboard.html` — hero card, quick actions, activity grid
- `forge/web/templates/worksets.html` — card grid, suggest/create side panel
- `forge/web/templates/workset_detail.html` — metrics, score bars, reason tags
- `forge/web/templates/planning.html` — split pane, markdown output, copy/raw toggle
- `forge/web/templates/memory.html` — timeline, inline search, typed create forms
- `forge/web/templates/memory_detail.html` — two-column detail view
- `forge/web/templates/repository.html` — detection cards, file tree, inline search
- `forge/web/templates/project.html` — status pills, tech chips, path copy
- `forge/web/templates/error.html` — centered error state

---

## 2026-06-28 17:18 CDT - Phase 4.1: Local Web UI MVP

### Problem Solved

Forge was primarily accessible through the CLI. Phase 4.1 adds a local-only browser UI so engineers can inspect project state, repository detection, worksets, context bundles, plans, and engineering memory without duplicating core Forge business logic in web routes.

### Commands Added

```bash
forge web
forge web --host 127.0.0.1 --port 8765 --root <path> --reload
```

`forge web` defaults to `127.0.0.1:8765`, prints the URL and resolved repository root, and warns when binding to `0.0.0.0`.

### Routes And Screens Added

- `GET /` dashboard with project metadata, recent worksets, plans, memory, and quick actions.
- `GET /project`, `GET /api/project`, `POST /api/project/init`.
- `GET /repository`, `GET /api/repository/detect`, `GET /api/repository/tree`, `GET /api/repository/search?q=...`.
- `GET /worksets`, `GET /worksets/{name}`, `GET /api/worksets`, `GET /api/worksets/{name}`.
- `POST /api/worksets/suggest`, `POST /api/worksets/create`, `POST /api/worksets/{name}/refresh`, `DELETE /api/worksets/{name}`.
- `POST /api/worksets/{name}/context`.
- `GET /planning`, `POST /api/plans/generate`.
- `GET /memory`, `GET /memory/{id}`, `GET /api/memory/search?q=...`, `GET /api/memory/timeline`.
- `POST /api/memory/add`, `POST /api/decisions/create`, `POST /api/investigations/create`.

### Architecture Decisions

- Added `forge/web/` using FastAPI, Jinja2 templates, static CSS, and minimal page-local JavaScript. No React or frontend build pipeline.
- Added `forge/services/` application services for project, repository, workset/context, planning, and memory orchestration. Web routes delegate to services, and services call existing Forge core modules.
- JSON APIs return a consistent envelope: `{"ok": true, "data": ...}` or `{"ok": false, "error": {"message": "...", "type": "..."}}`.
- The FastAPI app is created through `create_app(root)` and stores the resolved repo root in app state. Reload mode preserves `--root` through `FORGE_WEB_ROOT`.
- The web UI does not add authentication, remote sharing, patch generation, patch application, or a database.
- `forge init` now creates `plans/` and `memory/` directories in addition to the earlier project artifact directories.
- Shared repository ignore rules now skip `.forge/` and `.claude/` so generated project artifacts and local agent worktrees are not suggested as source workset candidates.

### Files Added

- `forge/services/__init__.py`
- `forge/services/project_service.py`
- `forge/services/repository_service.py`
- `forge/services/workset_service.py`
- `forge/services/planning_service.py`
- `forge/services/memory_service.py`
- `forge/web/__init__.py`
- `forge/web/app.py`
- `forge/web/deps.py`
- `forge/web/schemas.py`
- `forge/web/routes/__init__.py`
- `forge/web/routes/dashboard.py`
- `forge/web/routes/project.py`
- `forge/web/routes/repository.py`
- `forge/web/routes/worksets.py`
- `forge/web/routes/planning.py`
- `forge/web/routes/memory.py`
- `forge/web/templates/*.html`
- `forge/web/static/styles.css`
- `tests/test_web.py`

### Files Modified

- `forge/cli/app.py` — added `forge web` command.
- `forge/project/initializer.py` — creates `plans/` and `memory/` artifact directories.
- `forge/repository/ignore.py` — excludes `.forge/` and `.claude/` from repository scans.
- `pyproject.toml` — added FastAPI, Jinja2, Uvicorn, and TestClient dependencies.
- `README.md` — documented the local web UI, command usage, security note, and workflows.
- `docs/development/DEVELOPMENT_LOG.md`

### Tests Added

- App factory creation.
- Dashboard route returns 200.
- Project API metadata shape.
- Repository detect, tree, and search APIs.
- Workset list route/API, suggest, create, detail route/API.
- Workset suggestions exclude `.forge/` generated artifacts.
- Context generation API.
- Planning API with mocked planning service/model path.
- Memory search and timeline APIs.
- Decision and investigation creation APIs.
- Error response shape.
- Fixed root behavior.
- `forge web --help`.
- Public-host warning behavior with Uvicorn mocked.

### Verification

```bash
.venv/bin/python -m pytest          — 284 passed
.venv/bin/python -m ruff check .    — All checks passed
.venv/bin/python -m black --check . — 174 files unchanged
```

Manual smoke:

- `forge init --force` completed for `/Users/derektaylor/projects/forge`.
- `forge web` started at `http://127.0.0.1:8765` after sandbox escalation for localhost binding.
- Dashboard, project API, repository detection API, memory page/timeline/search, workset suggest/create/detail, and context generation returned successful responses.
- Live planning API returned a normal error envelope because the configured Ollama model timed out with a 1-second smoke timeout; automated planning API coverage uses a mocked planning service and does not require Ollama.

### Known Limitations

- The UI is an MVP with simple server-rendered pages and JSON previews rather than polished interactive components.
- Planning still depends on the configured model provider at runtime; tests mock planning and do not require Ollama.
- Context bundle preview is truncated to the first 4,000 rendered characters.
- Decision and investigation creation capture basic memory items only; richer ADR/bug investigation schemas are not implemented yet.
- No authentication or remote sharing is implemented. The tool remains local-only.

### Recommended Phase 4.2

Improve the web workflow ergonomics: richer forms with inline validation, better context bundle viewing/download, structured decision and investigation capture, plan history/detail pages, and shared CLI/web service usage for existing CLI commands where it reduces duplication.

## 2026-06-28 CDT - Phase 3.1: Engineering Memory

### Problem Solved

Every plan generated by Forge was treated as an isolated event. Prior engineering work — plans, decisions, ADRs, bug investigations — was forgotten between sessions. Phase 3.1 introduces a persistent Engineering Memory subsystem so that future planning is progressively enriched by prior work.

### Commands Added

```bash
forge memory list                                    # List all memory items
forge memory show <id>                               # Show a single item by ID
forge memory search "<query>"                        # Deterministic search with ranked results
forge memory related "<query>" --workset <name>      # Similarity-based related item lookup
forge memory rebuild                                 # Rebuild the index from stored item files
```

### Architecture Decisions

- New package `forge/memory/` with five single-responsibility modules:
  - `models.py` — `MemoryType` (StrEnum), `MemoryItem` dataclass; `to_dict` / `from_dict` for JSON round-trips.
  - `store.py` — persistence layer: `save_item`, `load_item`, `list_items`, `load_index`, `rebuild_index`, `delete_item`. Index kept in `.forge/memory/index.json`; individual items stored under type-specific subdirectories.
  - `manager.py` — `MemoryManager`: CRUD and `rebuild`. CLI commands and planning delegate through this class.
  - `search.py` — deterministic search with six ranked signals: title exact match, title token overlap, tag overlap, workset overlap, related file token overlap, summary token overlap, artifact type. Every result includes match reasons.
  - `similarity.py` — deterministic similarity using overlapping files, directories, top-level directories, worksets, tags, and query term intersection. No embeddings, no vector database.
- Storage layout: `.forge/memory/{plans,decisions,bugs,architecture}/` + `index.json`.
- `ForgePaths` extended with `memory_dir` field.
- `forge/planning/planner.py` updated to search memory before generating a plan. Matching prior items are injected into the planning prompt under an `## Engineering Memory Context` section. Each generated plan is automatically saved to memory (`save_to_memory=True` by default).
- `forge/planning/prompts.py` updated with `build_planning_prompt(..., memory_context)` parameter and `_build_memory_section` helper.
- Memory search is deterministic — no embeddings, no external services.
- `MemoryStoreError` wraps all store-level failures for clean CLI exit.

### Files Added

- `forge/memory/__init__.py`
- `forge/memory/models.py`
- `forge/memory/store.py`
- `forge/memory/manager.py`
- `forge/memory/search.py`
- `forge/memory/similarity.py`
- `tests/test_memory.py` (48 tests)

### Files Modified

- `forge/cli/app.py` — added `memory_app` Typer group and five `forge memory` commands
- `forge/project/paths.py` — added `memory_dir` to `ForgePaths`; updated `_SUBDIRS`
- `forge/planning/planner.py` — memory search before planning; auto-save plan to memory; `save_to_memory` flag; `ImplementationPlan.memory_item_id`
- `forge/planning/prompts.py` — `build_planning_prompt` accepts `memory_context`; `_build_memory_section`

### Tests Added (48 new, 267 total)

- Model: `MemoryItem` round-trip, `to_dict` shape, `MemoryType` values
- Store: save/load, creates subdirs, updates index, missing raises, list empty, list multiple, delete, delete removes from index, rebuild index, duplicate overwrites, missing dir returns empty
- Manager: add/get, list sorted descending, delete, rebuild, get missing raises
- Search: empty memory, title match, tag match, reasons populated, ranking order, max results, no match, summary match
- Similarity: empty memory, shared files, shared workset, shared tags, max results, reasons populated
- Repository isolation: separate roots do not bleed items
- Planning integration: memory searched before generating (prior items in prompt), auto-save to memory
- CLI: `memory list`, `list` empty, `list --json`, `show`, `show` missing, `show --json`, `search`, `search` no match, `search --json`, `related`, `rebuild`, `rebuild` empty

### Verification

```
python3 -m pytest          — 267 passed
python3 -m ruff check .    — All checks passed
python3 -m black --check . — 75 files unchanged
```

### Known Limitations

- Memory items are stored per repository root; there is no cross-repository memory.
- `forge memory list` returns items sorted by `created_at` descending; no other sort options yet.
- Tags are auto-extracted from the task text and workset name; user-supplied tags are not yet supported via CLI.
- `forge memory show` output is plain text only (except `--json`); Rich table formatting could improve readability.
- `forge memory search ""` (empty query) returns all items unsorted — a more useful default could be added.
- Plans saved to memory use an 8-character UUID prefix for IDs; collision probability is negligible but non-zero.
- Memory is not deduplicated across repeated `forge plan` calls for the same task — each run adds a new item.

### Recommended Phase 3.2

**Structured decision capture**: allow engineers to explicitly record architectural decisions (`forge memory add decision "Use JWT for session tokens" --tags auth,security`), bugs (`forge memory add bug "Token refresh race condition" --workset auth`), and follow-up tasks. This would make the memory knowledge base useful beyond just plan auto-save, and would form the foundation for `forge adr` integration.

## 2026-06-28 CDT - Phase 2F Workset Context Bundles

# 
## 2026-06-28 CDT - Phase 2E Root Resolver Migration

### Problem Solved

- Repo and workset commands used `normalize_root()` from `forge.repository.ignore`,
  which resolved `Path(".")` to the shell's current working directory. Running any
  command from a nested subdirectory (e.g. `src/main/java`) operated against that
  subdirectory rather than the repository root, causing worksets to miss root-level
  files and `.forge/` artifacts to be created in the wrong location.
- Phase 2E migrates all affected commands to `resolve_root()` from
  `forge.project.resolver`, which walks upward until it finds `.git` before
  settling on a root. `--root` overrides still work and take priority.

### Commands Updated

- `forge explain-project` — added `--root` option; resolves root via `resolve_root()`
- `forge repo tree` — now walks up to `.git` when no `--root` given
- `forge repo detect` — same
- `forge repo grep` — same
- `forge repo files` — same
- `forge workset suggest` — same
- `forge workset create` — now writes `.forge/worksets/` under repo root
- `forge workset list` — reads from resolved repo root
- `forge workset show` — reads from resolved repo root
- `forge workset add` — resolves repo root before adding
- `forge workset remove` — resolves repo root before removing
- `forge workset refresh` — resolves repo root before refreshing
- `forge workset clear` — resolves repo root before deleting

### Architecture Decisions

- All CLI command `--root` options changed from `Path` (default `Path(".")`) to
  `Path | None` (default `None`). This lets `resolve_root(override=root)` distinguish
  "not provided — walk up" from "explicitly provided — use as-is".
- CLI commands resolve root first, then pass the concrete `resolved.root` path to
  service functions. Service functions (`tree.py`, `detect.py`, etc.) continue to
  use `normalize_root()` internally, which is a no-op on already-absolute paths.
- `forge.worksets.suggest.suggest_candidates` and `forge.worksets.manager` now import
  `resolve_root` directly, removing their `normalize_root` imports.
- `normalize_root()` in `forge.repository.ignore` is preserved for backward
  compatibility with the repository service modules; its docstring now notes that
  `resolve_root()` should be preferred for new code.

### Files Modified

- `forge/cli/app.py` — all affected CLI commands
- `forge/worksets/suggest.py` — replaced `normalize_root` with `resolve_root`
- `forge/worksets/manager.py` — replaced `normalize_root` with `resolve_root`
- `forge/repository/ignore.py` — deprecation note on `normalize_root`
- `README.md` — updated phase scope, root resolution behavior, added examples
- `docs/development/DEVELOPMENT_LOG.md`

### Files Added

- `tests/test_phase2e_root_migration.py` — 17 new tests

### Tests Added

- `forge repo detect` from nested dir resolves to repo root (README.md in important files)
- `forge repo detect` with `--root` override
- `forge repo detect` with no `.git` falls back to cwd without crashing
- `forge repo tree` from nested dir shows root-level README.md
- `forge repo tree --root` override wins over cwd
- `forge repo grep` from nested dir finds root-level pattern
- `forge repo grep --root` override
- `forge repo files` from nested dir lists root-level source files
- `forge repo files --root` override
- `forge workset suggest` from nested dir finds root-level files
- `forge workset suggest --root` override
- `forge explain-project --help` shows `--root` option
- `forge workset create` from nested dir writes `.forge/worksets/` at repo root
- `forge workset list` from nested dir reads worksets from repo root
- `forge workset show` from nested dir reads workset from repo root
- `--root` override wins over unrelated cwd
- no `.git` fallback uses cwd, does not crash

### Known Limitations

- `normalize_root()` in the repository service modules still exists and is not
  removed; it is used internally with pre-resolved absolute paths and is harmless.
- The repo service modules (`tree.py`, `detect.py`, `grep.py`, `files.py`) do not
  themselves call `resolve_root()`. Root resolution happens at the CLI layer only.
  Callers of these services directly (e.g. in tests) must pass an already-resolved
  path if they want `.git`-aware behavior.

### Next Recommended Phase

- Phase 2F: workset context compression — given a persisted workset, produce a
  compact context bundle (per-file summaries, relevant line ranges, symbol index)
  stored under `<repo-root>/.forge/context/` and suitable for inclusion in a
  focused AI prompt without exceeding context limits.

## 2026-06-28 CDT - Phase 2D Repository Identity & Project Metadata

### Problem Solved

- Forge had no concept of which repository it was operating in. Commands used
  `Path(".")` directly, making root resolution implicit and non-composable.
  Phase 2D introduces a centralized repository root resolver, a typed path
  object covering all significant Forge directories, and project metadata
  persisted in `<repo-root>/.forge/project.json`. This cleanly separates global
  config (`~/.forge/`) from project artifacts (`<repo-root>/.forge/`).

### Commands Added

- `forge init` — discover repository root, create `.forge/` subdirectory
  structure (`worksets/`, `summaries/`, `context/`, `architecture/`,
  `sessions/`, `cache/`), and write `project.json`. `--force` reinitializes
  without losing `created_at`. `--root` overrides auto-detection.
- `forge project root` — print the resolved repository root; supports `--root`.
- `forge project info` — show project name, root, paths, initialized state,
  detected languages/frameworks/build systems/package managers. Supports
  `--json` and `--root`.
- `forge project paths` — show all significant Forge paths (global config,
  global dir, repo root, project dir, worksets, summaries, context,
  architecture, sessions, cache). Supports `--json` and `--root`.

### Architecture Decisions

- Added `forge/project/` package with four single-responsibility modules:
  - `resolver.py` — `ResolvedRoot` dataclass + `resolve_root()`: walks upward
    looking for `.git`, returns `git_detected` flag, supports `--root` override.
  - `paths.py` — `ForgePaths` dataclass computed from a resolved root; exposes
    `to_dict()` for JSON output. `global_forge_dir()` is a top-level helper.
  - `metadata.py` — `build_metadata()`, `load_metadata()`, `save_metadata()`;
    schema_version=1; preserves `created_at` on force-reinit via the caller.
  - `initializer.py` — `initialize_project()`: creates subdirs, calls
    `detect_repository()` to populate `detected` section, delegates to
    metadata helpers. Returns `InitResult` (paths, already_existed, forced).
- CLI commands remain thin wrappers; all logic lives in the `forge.project`
  package.
- `resolve_root()` is available for future use by workset, repo, and explain
  commands to replace ad-hoc `normalize_root()` calls.

### Files Added

- `forge/project/__init__.py`
- `forge/project/resolver.py`
- `forge/project/paths.py`
- `forge/project/metadata.py`
- `forge/project/initializer.py`
- `tests/test_project_phase2d.py`

### Files Modified

- `forge/cli/app.py` — added `project_app` Typer group; `forge init`,
  `forge project root/info/paths` commands
- `README.md` — updated phase scope, added new commands and separation docs
- `docs/development/DEVELOPMENT_LOG.md`

### Tests Added

- 28 new tests in `tests/test_project_phase2d.py` covering: resolve_root from
  repo root, from nested subdirectory, no-git fallback, `--root` override with
  and without `.git`; `ForgePaths` field values and `to_dict()` shape;
  `build_metadata` schema; save/load round-trip; load returns None when missing;
  initialize creates all six subdirs; creates project.json; raises on
  already-exists without --force; force overwrites; force preserves `created_at`;
  `already_existed` flag; CLI coverage for `forge init`, `forge init --force`,
  `forge init` already-exists error, `forge project root`, `forge project root`
  nested, `forge project info` uninitialized and initialized, `forge project
  info --json` initialized and uninitialized, `forge project paths`,
  `forge project paths --json`.

### Known Limitations

- Existing repo/workset commands still use `normalize_root()` from
  `forge.repository.ignore` rather than `resolve_root()`; they do not walk
  upward to find `.git`. Migrating them is deferred to avoid scope creep.
- `forge init` does not automatically add `.forge/` to `.gitignore`.
- No `forge project update` to refresh `detected` metadata without full reinit.

### Next Recommended Phase

- Phase 2E: workset context compression — given a persisted workset, produce a
  compact context bundle (per-file summaries, relevant line ranges, symbol
  index) suitable for inclusion in a focused AI prompt without exceeding context
  limits. Now that `<repo-root>/.forge/` is reliable, context bundles can be
  stored under `.forge/context/`.

## 2026-06-28 CDT - Phase 2C Persistent Worksets

### Problem Solved

- Engineers need to save, revisit, and evolve focused file sets across sessions.
  Phase 2C adds durable named worksets stored as versioned JSON files under
  `.forge/worksets/` in the repository root. Worksets are project-specific,
  inspectable, and fully model-independent.

### Commands Added

- `forge workset create <name> --query "<query>"` — run the suggestion engine and
  persist the result as a named workset; `--force` overwrites an existing workset.
- `forge workset list` — list all worksets with name, query, file count, and timestamps.
- `forge workset show <name>` — display workset metadata and file table; `--json`
  returns the raw JSON document.
- `forge workset add <name> <file>` — add a file manually; validates existence and
  root membership; marks the entry `manual: true`.
- `forge workset remove <name> <file>` — remove a file from the workset.
- `forge workset refresh <name>` — re-run the saved query and update scores;
  preserves manually added files that still exist on disk; manually-flagged files
  that were also re-suggested retain their `manual: true` flag.
- `forge workset clear <name>` — delete a workset after confirmation; `--yes` skips
  the prompt.

### Architecture Decisions

- Added `forge/worksets/store.py`: name validation, path resolution
  (`.forge/worksets/<name>.json`), JSON read/write, list, and delete. No logic above
  persistence here.
- Added `forge/worksets/manager.py`: higher-level operations (create, add, remove,
  refresh, clear, get, list) that call `suggest_candidates` and delegate persistence
  to `store`. CLI commands remain thin wrappers.
- Workset JSON uses `schema_version: 1`. Each file entry carries `path` (relative
  POSIX), `score`, `category`, `reasons` (with `signal`, `detail`, `points`), and a
  `manual` boolean.
- `CandidateReason.label` (format `"signal:detail"`) is split on the first `:` when
  serializing to the JSON reasons shape, matching the spec without modifying the
  existing candidate data models.
- Files outside the workset root are rejected at add time via `Path.is_relative_to`.
- Manually added files that happen to be re-suggested during refresh retain
  `manual: true` so they survive future refreshes regardless of query drift.

### Files Added

- `forge/worksets/store.py`
- `forge/worksets/manager.py`
- `tests/test_workset_persist.py`

### Files Modified

- `forge/cli/app.py` — added `workset create/list/show/add/remove/refresh/clear`
- `README.md` — updated commands and phase scope
- `docs/development/DEVELOPMENT_LOG.md`

### Tests Added

- 40 new tests in `tests/test_workset_persist.py` covering: name validation (valid,
  empty, slash, backslash, dotdot, space), store path resolution, create/load,
  JSON shape/schema version, duplicate create rejection, force overwrite, exists,
  list_names, add_file (new file, already-present file, duplicate prevention, outside
  root, missing file), remove_file (present, not-present noop), clear (success,
  missing), refresh (basic, preserves manual, drops missing manual), relative POSIX
  normalization, list_worksets, and all eight CLI commands.

### Known Limitations

- Workset files are not tracked by `.gitignore` automatically; teams should decide
  whether to commit `.forge/worksets/` to version control.
- `forge workset add` marks already-suggested files as `manual: true`, which means
  they survive refresh even if the query no longer matches them.
- No merge strategy when `--force` recreates a workset that had manual additions.
- Content scanning during refresh reads entire files (inherited from Phase 2B).

### Next Recommended Phase

- Phase 2D: workset context compression — given a persisted workset, produce a
  compact context bundle (per-file summaries, relevant line ranges, symbol index)
  suitable for inclusion in a focused AI prompt without exceeding context limits.

## 2026-06-28 CDT - Phase 2B Workset Candidate Selection

### Problem Solved

- Engineers need to know which files are relevant to a task before sending context
  to an AI model. Sending an entire repository is wasteful and often exceeds context
  limits. Phase 2B adds deterministic, explainable file ranking so Forge can propose
  a focused workset from a natural-language query without calling any AI model.

### Command Added

- `forge workset suggest "<query>"`
- Options: `--max-results`, `--root`, `--include-tests`, `--json`

### Architecture Decisions

- Created `forge/worksets/` as a new package with three modules:
  - `candidate.py` — `WorksetCandidate`, `CandidateReason`, `WorksetSuggestion` data models.
  - `scoring.py` — query tokenization, file categorization, and per-signal scoring logic.
  - `suggest.py` — orchestration: list files, filter tests, score, rank, return suggestion.
- Scoring uses six deterministic signals: exact filename match, per-token filename match,
  per-token path segment match, content grep match, important-file bonus, and file-type
  bonus (source/config/doc). Each reason is recorded with its point value so the output
  is fully explainable.
- Test files are excluded by default; inclusion is triggered by `--include-tests` or
  when the query itself contains test-related terms (test, spec, fixture, regression).
- Content scanning reads only files with source or config extensions; binary and unknown
  files are skipped without error.
- Reused `forge.repository.files.list_relevant_files` for file discovery and
  `forge.repository.ignore` for ignore rules. No duplication of ignore logic.
- CLI command is thin: it delegates entirely to `suggest_candidates()` and formats
  output with Rich tables or JSON via `console.print_json`.

### Files Added

- `forge/worksets/__init__.py`
- `forge/worksets/candidate.py`
- `forge/worksets/scoring.py`
- `forge/worksets/suggest.py`
- `tests/test_workset_suggest.py`

### Files Modified

- `forge/cli/app.py` — added `workset_app` Typer group and `workset suggest` command
- `README.md` — updated phase scope, added workset command examples
- `docs/development/DEVELOPMENT_LOG.md`

### Tests Added

- 30 new tests covering: query tokenization, stop-word filtering, short-token removal,
  test-query detection, file categorization, per-signal scoring, test inclusion/exclusion,
  ranking order, max-results clamping, empty-query handling, and CLI behavior for
  table output, `--include-tests`, `--json`, and `--max-results`.

### Known Limitations

- Content scanning reads entire files line by line; very large files are fully read
  without truncation.
- Scoring weights are fixed constants; there is no user-configurable scoring profile yet.
- Symbol-level matching (class names, function names) is not yet implemented — the
  content scan is substring-based.
- Test/source pairing (finding `test_manager.py` when `manager.py` is highly scored)
  is not yet implemented.
- Ignore handling uses Forge's built-in list; `.gitignore` parsing is not yet supported.

### Next Recommended Phase

- Phase 2C: workset context compression — given a ranked workset, produce a compact
  context bundle (file summaries, relevant line ranges, dependency edges) suitable for
  inclusion in a focused AI prompt without exceeding context limits.

## 2026-06-28 14:50 CDT - Phase 2A Repository Intelligence Foundation

### Problem Solved

- Added deterministic repository inspection so Forge can understand the current
  working directory before invoking any AI model.
- Kept repository scanning model-independent and reusable for future worksets,
  planning, impact analysis, and context compression.

### Commands Added

- `forge repo tree`
- `forge repo detect`
- `forge repo grep`
- `forge repo files`

### Architecture Decisions

- Added a new `forge.repository` package for repository services.
- Kept CLI commands thin: Typer/Rich formats output while scanning logic lives in
  `ignore.py`, `tree.py`, `detect.py`, `grep.py`, and `files.py`.
- Centralized ignored directory handling for generated, vendor, editor, and cache
  folders.
- Used ripgrep for repository search when installed and a deterministic Python text
  scan fallback when it is unavailable.
- Detection is heuristic and local-only: it looks at important files, source
  extensions, package manifests, Java annotations, and common Docker/Kubernetes
  markers.

### Files Changed

- `README.md`
- `docs/development/DEVELOPMENT_LOG.md`
- `forge/cli/app.py`
- `forge/repository/__init__.py`
- `forge/repository/ignore.py`
- `forge/repository/tree.py`
- `forge/repository/detect.py`
- `forge/repository/grep.py`
- `forge/repository/files.py`
- `tests/test_cli.py`
- `tests/test_repository_inspection.py`

### Tests Added

- Ignored directory handling.
- Tree generation max-depth behavior.
- Python repository detection.
- Java/Spring Boot repository detection.
- Node/React/Angular repository detection.
- Grep Python fallback behavior without requiring ripgrep.
- Relevant file listing.
- CLI coverage for `forge repo tree`, `forge repo detect`, `forge repo grep`, and
  `forge repo files`.

### Known Limitations

- Detection is intentionally heuristic; it does not parse full dependency graphs or
  ASTs yet.
- `forge repo grep` fallback performs literal substring matching, while ripgrep
  supports regex patterns.
- Ignore handling uses Forge's built-in default generated/vendor directory list; it
  does not parse `.gitignore` yet.
- Repository tree output is compact but does not yet support max-entry truncation.

### Next Recommended Phase

- Phase 2B: build deterministic workset construction on top of `forge.repository`,
  including explainable file selection, scoring, and context-size controls, while
  continuing to avoid patching and destructive changes.

## 2026-06-28 14:40 CDT - Test Coverage Hardening

### Completed

- Added practical pytest coverage for CLI smoke behavior using `typer.testing.CliRunner`.
- Added deterministic config tests for default `~/.forge/config.yaml` creation, custom Ollama endpoint loading, custom timeout parsing, default model resolution, and invalid provider handling.
- Added Ollama provider tests with mocked HTTP connections for reachability checks, `/api/tags` parsing, `/api/generate` payload construction, configured timeout forwarding, timeout override behavior, and HTTP error formatting.
- Added model-manager regression tests for exact tagged model validation and nonexistent default model prevention.
- Added CLI regression tests confirming model-not-found errors suggest `forge models`, provider errors are formatted, and `forge ask` sends only the literal prompt.
- Added project explanation tests for `README.md`, `pyproject.toml`, `docs/development/DEVELOPMENT_LOG.md`, and excluded folder handling.
- Registered the `integration` pytest marker and documented test commands in the README.

### Files Changed

- `pyproject.toml`
- `README.md`
- `docs/development/DEVELOPMENT_LOG.md`
- `tests/test_cli.py`
- `tests/test_config_manager.py`
- `tests/test_model_manager.py`
- `tests/test_ollama_provider.py`
- `tests/test_project_context.py`

### Bugs Captured as Regression Tests

- Untagged model names such as `llama3.1` are not silently accepted when only `llama3.1:8b` is installed.
- `forge ask` validates the configured default model before generating, so it does not use a nonexistent default.
- `forge ask` and the Ollama provider use configured or explicit timeouts instead of a 5-second hardcoded timeout.
- Model-not-found CLI output suggests running `forge models`.
- `forge ask` remains literal and does not pretend to explain a project unless `forge explain-project` is used.

### Known Gaps

- No real-Ollama integration tests are included yet.
- OpenAI and Anthropic provider HTTP payloads and error paths still need equivalent mocked coverage.
- Config parsing remains a small Forge-owned YAML subset, so malformed YAML diagnostics are basic.

### Next Recommended Testing Improvements

- Add `@pytest.mark.integration` tests against a local Ollama instance for `forge models` and a tiny `forge ask` flow.
- Add mocked OpenAI and Anthropic provider request/response tests.
- Add command-level tests around `forge explain-project --model` and timeout error surfacing.
- Add a future `forge verify` command once verification orchestration enters scope.

## 2026-06-28 - Phase 1 Foundation

### Started

- Read the product request and confirmed the instruction to implement Phase 1 only.
- Found an empty workspace, so started a fresh modular Python package.
- Added project metadata, initial README, package skeleton, settings, structured logging, model provider interface, provider factory, and initial Ollama/OpenAI/Anthropic provider modules.

### In Progress

- Implementing the Phase 1 CLI commands: `doctor`, `version`, `models`, and `ask`.
- Adding tests for command behavior and provider selection.

### Completed

- Implemented the Typer/Rich CLI entry point with `forge version`, `forge doctor`, `forge models`, and `forge ask`.
- Added environment-driven settings for provider, model, and Ollama host selection.
- Added a `ModelProvider` protocol and typed request/response models.
- Added an Ollama provider using Python's standard HTTP client for `/api/tags` and `/api/generate`.
- Added OpenAI and Anthropic provider modules behind the same interface using SDK-free HTTP clients.
- Added doctor checks for Python, Git, ripgrep, Docker, Java, and Ollama.
- Added JSON structured logging through `structlog`.
- Added unit tests for settings, provider factory behavior, and CLI basics.
- Added `.gitignore` for Python build, cache, and local environment artifacts.

### Verification

- `python3 -m pytest` passed with 10 tests.
- `python3 -m ruff check .` passed.
- `python3 -m black --check .` passed.
- `forge version` returned `0.1.0`.
- `forge --help` showed the expected Phase 1 commands.
- `git status --short` could not run because this workspace is not currently a Git repository.

## 2026-06-28 - Phase 1 Model Management Refactor

### Completed

- Refactored model operations around a first-class `ModelManager`.
- Added `ConfigManager` for local `~/.forge/config.yaml` loading, creation, display, editing, and default model persistence.
- Added config-backed model selection so `forge ask "Hello"` uses the configured default model.
- Added per-request override support with `forge ask --model <model> "Hello"`.
- Added `forge config show`, `forge config edit`, and `forge config set-default-model <model>`.
- Converted `forge models` into a model management command group while preserving list behavior.
- Added `forge models use <model>` for validated default model selection.
- Added installed-model validation and closest-match suggestions when a requested model is missing.
- Kept CLI/provider separation intact: CLI commands now route model operations through `ModelManager`.
- Added log-safe model interaction telemetry for provider, endpoint, model, elapsed time, prompt size, and response size.
- Updated the README to document config-backed model management.
- Added tests for config management, model management, CLI model overrides, missing-model output, and telemetry safety.

### Verification

- `/usr/local/Caskroom/miniforge/base/bin/python3.12 -m pytest` passed with 20 tests.
- `ruff check .` passed.
- `black --check .` passed.
- The plain `pytest` entrypoint is currently tied to a broken Python 3.10 environment with an incompatible `charset_normalizer` wheel, so Python 3.12 was used for verification.

## 2026-06-28 - Ask Timeout and Explicit Project Explanation

### Completed

- Increased the default Ollama request timeout from 5 seconds to 120 seconds.
- Added `providers.ollama.timeout_seconds` support in `~/.forge/config.yaml`.
- Added `forge ask --timeout <seconds>` for per-request timeout overrides.
- Improved Ollama timeout errors to show the model, endpoint, configured timeout, and a smaller-model suggestion.
- Kept `forge ask` literal so it does not automatically read repository files.
- Added `forge explain-project` for explicit current-directory inspection, selected project file context, compact tree context, and project explanation prompts.
- Updated README documentation for timeout configuration, `ask --timeout`, and `explain-project`.
- Added regression tests for timeout config parsing, CLI timeout forwarding, timeout error details, and explicit project-context prompting.

### Verification

- `python3 -m pytest` passed with 25 tests.
- `python3 -m ruff check .` passed.
- `python3 -m black --check .` passed.

### Next

- Do not start Phase 2 yet.
- Continue hardening Phase 1 foundation before repository scanning: provider-agnostic config, model validation, local model workflows, and command architecture.

## 2026-06-28 — Engineering Verification Foundation

### Completed

- Added `forge verify --detect` and `forge verify --detect --json`.
- Added deterministic verification strategy detection for Python, Node npm,
  Node pnpm, Node yarn, Maven, Gradle, Go, Rust, .NET, and unknown repositories.
- Added structured verification models and an application service so CLI
  adapters do not call the detector directly.
- Kept this phase read-only: no commands are executed, no patches are applied,
  and no source files are modified by verification detection.
- Prepared the model shape for future verification reports as engineering
  artifacts of type `verification`.

### Future Workflow

```bash
forge implement "..." --workset <name>
forge patch validate <patch>
forge verify --detect
```

Actual verification command execution and repair loops remain future phases.

## 2026-06-28 - Ask Timeout and Explicit Project Explanation

### Completed

- Increased the default Ollama request timeout to 120 seconds.
- Added `providers.ollama.timeout_seconds` support in `~/.forge/config.yaml`.
- Added `forge ask --timeout <seconds>` for per-request timeout overrides.
- Improved Ollama timeout errors to include the model, endpoint, configured timeout, and a smaller-model suggestion.
- Kept `forge ask` literal so it does not automatically read repository files.
- Added `forge explain-project` to explicitly inspect the current working directory, include selected project files, include a compact excluded-directory tree, and ask the configured model for a project explanation.
- Updated the README with the new config, timeout option, and explicit project explanation command.

### Verification

- Added regression tests for timeout config parsing, CLI timeout forwarding, Ollama timeout error details, and explicit project-context prompting.

## 2026-06-28 — Phase 2G: Workset-Based Planning

### Problem Solved

Forge could build context bundles from worksets but had no way to turn that context
into an actionable implementation plan. Engineers had to manually paste context into an
AI tool and prompt it themselves. Phase 2G closes that gap.

### Command Added

```bash
forge plan "<task>" --workset <name>
forge plan "<task>" --workset <name> --save
forge plan "<task>" --workset <name> --model qwen2.5-coder:14b
forge plan "<task>" --workset <name> --json
```

### How Planning Works

1. `resolve_root` determines the repository root.
2. The persisted workset is loaded from `.forge/worksets/<name>.json`.
3. `generate_bundle` builds a deterministic context bundle (file summaries, symbols,
   excerpts, dependency hints) — no AI model is called at this stage.
4. `build_planning_prompt` assembles a structured prompt from the task, workset
   metadata, and per-file context. The prompt explicitly instructs the model not to
   generate patches or claim files were modified.
5. `ModelManager.ask` sends the prompt to the configured provider.
6. The plan Markdown is printed (or saved to `.forge/plans/` with `--save`).

### Architecture Decisions

- New package `forge/planning/` with single-responsibility modules:
  - `planner.py` — orchestration; owns `ImplementationPlan` dataclass and `generate_plan`
  - `prompts.py` — builds the planning prompt from a `ContextBundle`
  - `render.py` — renders plans as text or JSON
  - `store.py` — saves plans to `.forge/plans/<workset>-<timestamp>.md`
- CLI remains thin; all prompt assembly and orchestration lives in `forge.planning`.
- `ForgePaths` extended with `plans_dir` field (`.forge/plans/`).
- Model is never called directly from CLI — always routed through `ModelManager`.
- `PlannerError` wraps workset and model failures for clean CLI exit.

### Files Added

- `forge/planning/__init__.py`
- `forge/planning/planner.py`
- `forge/planning/prompts.py`
- `forge/planning/render.py`
- `forge/planning/store.py`
- `tests/test_planning.py` (19 tests)

### Files Modified

- `forge/cli/app.py` — added `plan` command
- `forge/project/paths.py` — added `plans_dir` to `ForgePaths`
- `README.md` — updated phase description and planning workflow

### Tests Added

- Prompt includes task, workset name, file summaries, excerpts, model name
- Prompt instructs model not to modify files or generate patches
- Planner calls `ModelManager` with selected model
- Planner uses model override when provided
- Missing workset raises `PlannerError`
- Model provider error raises `PlannerError`
- `--save` writes plan under `.forge/plans/`
- Plan saved in correct subdirectory
- `render_plan_text` and `render_plan_json` output shape
- CLI: success, `--save`, `--json`, `--model` override, missing workset

### Verification

- `python3 -m pytest` passed with 219 tests (19 new).
- `python3 -m ruff check .` passed.
- `python3 -m black --check .` passed.

### Known Limitations

- Plan quality depends on the configured model and workset size; large worksets may
  exceed context windows for smaller models.
- `--save` does not deduplicate — running the same plan twice creates two files.
- The footer instructs the model to include plan/workset/model attribution, but model
  compliance is not validated.

### Recommended Phase 2H

**Workset-aware patch scaffolding**: given a completed plan, generate a structured
edit scaffold (file → proposed changes) that can be reviewed and applied. This should
be a read-only scaffold (not applied automatically) and should build on the `forge.planning`
package already in place. Key additions: `forge scaffold "<task>" --plan <path>`,
a `forge/scaffold/` package, and a unified diff or file-edit representation that can
later feed `forge apply`.

