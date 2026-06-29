# Forge Architecture

Forge follows an Application Service architecture:

```text
CLI and Web Adapters
        |
        v
Application Services
        |
        v
Domain Services
        |
        v
Provider Abstractions
        |
        v
Infrastructure
```

This keeps Forge deterministic first, provider independent, local first, and easy
to test as orchestration grows.

## Responsibilities

### CLI and Web Adapters

Adapters translate user input into service calls and format responses. They may:

- Parse command-line options or HTTP payloads.
- Resolve presentation concerns such as Rich tables, Typer exits, templates, and
  JSON envelopes.
- Handle adapter-specific error rendering.

Adapters should not coordinate repository scans, context generation, memory
lookup, model calls, artifact persistence, or provider selection directly.

### Application Services

Application services live in `forge/services/`. They coordinate workflows across
domain packages, provider abstractions, and project-local storage.

`PlanningService` is the canonical pattern:

- Accept explicit dependencies such as `ModelManager` when provider calls need
  test doubles.
- Gather deterministic context through domain services.
- Search and update Engineering Memory.
- Call the model provider through the provider abstraction.
- Save application artifacts such as plans when requested.
- Return domain objects for Python callers or serializable payloads for
  adapters.

Other service modules use module-level functions when no stateful dependency is
needed. This is intentional: Forge adds classes only where dependency injection
or workflow state makes them useful.

### Domain Packages

Domain packages hold deterministic business logic:

- `forge/repository/`: repository detection, tree generation, ignore rules, and
  deterministic text search.
- `forge/worksets/`: candidate scoring, persisted workset semantics, and manual
  file membership rules.
- `forge/context/`: context bundle construction, summaries, symbols, excerpts,
  and rendering.
- `forge/memory/`: memory models, storage, search, and similarity scoring.
- `forge/planning/`: planning prompts, plan datatypes, rendering, and storage
  helpers.
- `forge/execution/`: provider-independent execution pipeline models, stages,
  and orchestration.
- `forge/patches/`: saved patch inspection and validation.
- `forge/artifacts/`: unified read-only metadata model, discovery helpers, and
  registry facade over existing engineering artifacts.
- `forge/git/`: read-only Git repository inspection. `GitService` centralizes all
  `git` subprocess calls. It never modifies files, applies patches, or creates
  commits. This is the foundation for future guarded patch application — any
  operation that touches the working tree must go through `GitService` first.

Domain code should stay provider independent and should not know whether a
workflow was invoked by CLI, web, or a future agent.

### Provider Abstractions

Provider abstractions live under `forge/models/`. They normalize Ollama, OpenAI,
and Anthropic behind `ModelManager` and model provider interfaces. Application
services call these abstractions instead of provider SDKs directly.

### Infrastructure

Infrastructure is local and explicit: `.forge/` project directories, JSON files,
Markdown artifacts, configuration files, and provider clients. Infrastructure
code performs storage or external calls; it should not decide whole workflows.

## Engineering Artifact Registry

The Engineering Artifact Registry in `forge/artifacts/` is the canonical
read-oriented representation of Forge engineering artifacts. It does not own
storage and does not migrate files. Existing subsystems continue to write their
native formats in their existing locations:

- Repository metadata: `.forge/project.json`
- Worksets: `.forge/worksets/*.json`
- Context bundles: `.forge/context/*`
- Implementation plans: `.forge/plans/*.md`
- Engineering Memory: `.forge/memory/**/*.json`
- Patches: `.forge/patches/*.patch`
- Verification reports: `.forge/verifications/*.json`

The registry discovers those files and exposes them as `Artifact` objects with
partial metadata: identifier, type, name, description, timestamps, project root,
relative path, producing service, producing command, workset association,
related artifacts, and an open metadata dictionary. Missing fields are valid.
This lets old artifacts and future artifacts share a model without requiring a
new storage format.

The registry is intentionally read-only. It may load metadata, enumerate
artifacts, filter by type, locate by identifier, and expose sparse
relationships, but it must not edit artifact files or create sidecars.

### Artifact Lifecycle

```text
Service or domain package creates artifact in existing storage
        |
Artifact keeps its original format and path
        |
ArtifactRegistry discovers and normalizes metadata
        |
Future services use the common model for lineage and traceability
```

### Relationships

Relationships are represented as sparse `ArtifactRelationship` records. Forge
only records relationships it can determine reliably, for example:

```text
Workset
        |
Context Bundle
        |
Implementation Plan
        |
Patch
        |
Verification
        |
Commit
```

Early relationships are limited to explicit workset associations and memory
links. Future execution records, verification reports, repair reports, review
reports, documentation updates, ADRs, knowledge capture, and workflow history
can extend the same artifact vocabulary without redesigning worksets, plans,
memory, context bundles, or patches.

## Planning And Execution

Planning and Execution are intentionally separate.

Planning decides what should be built. `PlanningService` gathers deterministic
context, searches Engineering Memory, calls the configured provider through
`ModelManager`, and returns an `ImplementationPlan`.

Execution coordinates how approved work will be carried out. The initial
`forge/execution/` pipeline does not call providers, generate patches, apply
patches, run tests, repair failures, or update source repositories. It runs
read-only stages and returns an `ExecutionResult` containing per-stage timing,
status, metadata, and the assembled `ExecutionContext`.

The canonical execution stages are:

```text
Load Workset
        |
Load Context
        |
Load Engineering Memory
        |
Load Implementation Plan
        |
Assemble Execution Context
        |
Execution Complete
```

Each stage implements the same shape: receive an `ExecutionContext`, perform
small deterministic work, return the updated context, and let the orchestrator
capture an `ExecutionStageResult`. Future stages such as
`PatchGenerationStage`, `PatchValidationStage`, `PatchStorageStage`,
`PatchApplicationStage`, `VerificationStage`, `RepairStage`,
`DocumentationStage`, and `KnowledgeCaptureStage` can be inserted without
rewriting `ExecutionOrchestrator`.

## Verification

Verification is a first-class engineering workflow rather than a terminal log
wrapper. `forge/verification/` owns deterministic strategy detection,
command execution, step result models, report models, and artifact persistence.
`forge/services/verification_service.py` is the application boundary used by
adapters.

The verification pipeline is:

```text
Resolve Repository
        |
Detect Verification Strategy
        |
Execute Formatter
        |
Execute Linter
        |
Execute Build
        |
Execute Tests
        |
Collect Step Results
        |
Persist Verification Report
        |
Register Artifact Metadata
```

Commands are executed through `CommandRunner`, which captures stdout, stderr,
exit code, duration, timeout state, command line, working directory, and any
exception. The CLI never invokes subprocesses directly. Execution continues
after recoverable step failures so the final `VerificationReport` can show all
available quality gate evidence.

Verification reports are serialized JSON artifacts under `.forge/verifications/`
by default, or at an explicit `--output` path. Report metadata can relate the
run to a workset, plan, or patch without changing the working tree. Future
Patch Apply, Repair Loop, Continuous Verification, and Policy Gate workflows
should consume these reports instead of scraping command output.

## Engineering Policy and Guarded Apply

`forge/policies/` owns the policy domain: `ForgePolicy` dataclass, per-section
models (`PatchPolicy`, `VerificationPolicy`, `GitPolicy`, `ApplyPolicy`),
`PolicyEvaluator`, and `load_policy` which reads `.forge/policy.yaml` or returns
defaults. Policy evaluation produces a `PolicyEvaluation` with a `status` of
`pass | warn | fail` and per-check evidence.

`forge/services/apply_service.py` implements the guarded apply workflow:

1. Validate patch (must be a valid unified diff).
2. `git apply --check` via `GitService` (dry-run).
3. Load latest verification report from `.forge/verifications/`.
4. Evaluate active policy.
5. Block on policy failure unless `--force` is used and policy allows it.
6. `git apply` via `GitService`.
7. Persist apply record to `.forge/applications/`.

`GitService` has been extended with `apply_check(patch_path)` and
`apply(patch_path)`. It never commits, never creates branches, and never
modifies files except via `git apply`.

`--yes` on `forge apply` skips the confirmation prompt only. Policy is always
evaluated. `--force` bypasses policy failures only when
`policy.apply.allow_force` is `true`.

No model calls occur during apply. No repair loop exists.

## Future Services

Future orchestration should follow the `PlanningService` pattern:

- `ExecutionService`: prepare execution requests for pipeline consumption while
  preserving the Planning/Execution boundary.
- `PatchService`: coordinate patch artifact creation, validation, and review
  state. Patch parsing and validation remain in `forge/patches/`.
- `VerificationService`: detect and execute repository verification strategies
  from deterministic file signals. `forge/verification/` owns the domain
  models, detector, runner, report model, and artifact persistence;
  `forge/services/verification_service.py` exposes structured results to
  adapters. Verification never applies patches or mutates source files.
- `ArchitectureService`: coordinate repository intelligence, worksets, memory,
  and architecture records. Detection and dependency analysis remain
  deterministic domain logic.

New workflows belong in `forge/services/` first. New business rules belong in
the relevant domain package. New adapters should call services rather than
duplicating orchestration.
