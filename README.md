# Forge

> **AI-Native Software Engineering Workbench**
>
> **Understand Software Before You Change It**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)]()
[![CLI](https://img.shields.io/badge/Interface-CLI%20%7C%20Web%20UI-orange)]()
[![Local First](https://img.shields.io/badge/Local-First-success)]()
[![AI Providers](https://img.shields.io/badge/Providers-Ollama%20%7C%20OpenAI%20%7C%20Anthropic-blue)]()
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()

Forge is an **AI-native software engineering workbench** that helps engineers understand, plan, and evolve software using **deterministic repository intelligence**, **engineering knowledge**, and **architecture-aware workflows**.

Rather than immediately asking an AI to write code, Forge first builds engineering context that both humans and AI can trust.

---

# Why Forge?

Modern AI coding tools excel at implementation.

Forge focuses on everything that should happen **before implementation**.

Instead of asking an AI:

> "Write code."

Forge asks:

- What kind of repository is this?
- Which files actually matter?
- What architecture already exists?
- What decisions have already been made?
- What engineering knowledge should influence this task?
- What context should be given to the model?

Only then does Forge involve AI.

```text
Repository
        │
        ▼
Repository Intelligence
        │
        ▼
Relevant Workset
        │
        ▼
Context Bundle
        │
        ▼
Engineering Knowledge
        │
        ▼
Implementation Plan
        │
        ▼
AI Model
        │
        ▼
Engineer
```

Forge is intentionally:

- Deterministic first
- Human controlled
- Provider independent
- Architecture aware
- Local first

---

# What Makes Forge Different?

| Traditional AI Coding Tools | Forge |
|-----------------------------|-------|
| Start with prompts | Start with repository understanding |
| Editor context | Repository intelligence |
| Temporary chat history | Persistent engineering knowledge |
| AI-first | Deterministic-first |
| Focus on code generation | Focus on engineering understanding |
| One-off conversations | Repeatable engineering workflows |

Forge complements tools like Cursor, Claude Code, Continue, and Codex by supplying the engineering context they typically lack.

---

# Who Is Forge For?

### 👨‍💻 Software Engineers

Understand unfamiliar repositories, identify relevant files, generate plans, and preserve engineering knowledge.

---

### 🏗 Software Architects

Explore architecture, capture decisions, build reusable knowledge, and guide implementation from repository facts.

---

### 👥 Technical Leads

Maintain engineering history, understand previous work, and guide teams through repeatable workflows.

---

### 🤖 AI Agents

Consume deterministic repository intelligence instead of large, noisy prompts.

---

### 🏢 Engineering Teams

Create engineering knowledge that survives beyond AI conversations and individual contributors.

---

# Core Capabilities

| Capability | Status | Description |
|------------|:------:|-------------|
| Repository Intelligence | ✅ | Detect languages, frameworks, source roots, build systems, important files, and repository structure. |
| Worksets | ✅ | Deterministic task-scoped file collections with explainable scoring. |
| Context Engineering | ✅ | Structured Markdown/JSON context bundles with summaries, symbols, excerpts, and dependency hints. |
| Engineering Knowledge | ✅ | Decisions, investigations, lessons, plans, architecture notes, and searchable engineering history. |
| Architecture-Aware Planning | ✅ | Generate implementation plans grounded in repository facts. |
| Engineering Execution Pipeline | ✅ | Provider-independent orchestration stages that load worksets, context, memory, and plans without mutating repositories. |
| Patch Management | ✅ | Store, list, inspect, and validate saved raw diff patches without applying them. |
| Patch Generation | ✅ | Generate human-reviewable unified diff patches from a task and workset without applying them. |
| Engineering Artifact Registry | ✅ | Internal read-only registry that unifies repository metadata, worksets, context bundles, plans, memory entries, and patches without moving or rewriting files. |
| Local Web Workbench | ✅ | Engineering Command Center — workflows as primary object, visual pipeline, artifact registry, repository intelligence, planning, patches, and memory. |
| Multi-Provider AI | ✅ | Ollama, OpenAI, and Anthropic through a common provider abstraction. |
| Architecture Intelligence | 🚧 Planned | Living architecture, dependency analysis, and architectural health. |
| Agent Orchestration | 🚧 Planned | Multi-agent engineering workflows. |

---

# Typical Engineering Workflows

## 📖 Understand a New Repository

```bash
forge init

forge repo detect

forge repo tree

forge explain-project
```

Forge will:

- Detect languages
- Detect frameworks
- Discover important files
- Understand repository structure
- Explain the project using explicit repository context

---

## 🚀 Plan a Feature

```bash
forge workset suggest "authentication"

forge workset create auth --query "authentication"

forge workset context auth

forge plan "Add GitHub OAuth" --workset auth
```

Workflow

```text
Task

↓

Relevant Files

↓

Context Bundle

↓

Implementation Plan

↓

Execution Pipeline
```

---

## 🐛 Investigate a Bug

```bash
forge memory search "timeout"

forge workset suggest "timeout"

forge workset context timeout

forge investigation create "Planning timeout"

forge plan "Resolve planning timeout" --workset timeout
```

---

## 🧠 Capture Engineering Knowledge

```bash
forge decision create "Use JWT"

forge investigation create "Planning timeout"

forge memory timeline
```

## Inspect Git Repository State

```bash
forge git status

forge git status --json

forge git branch

forge git branch --json
```

`forge git status` inspects the current Git repository without modifying any
file. It reports branch, commit SHA, clean/dirty state, staged files, modified
files, deleted files, and untracked files. `GitService` centralizes all git
subprocess calls and is the foundation for future guarded patch application.

## 🧩 Inspect Saved Patches

```bash
forge patch list

forge patch show example.patch

forge patch validate example.patch
```

## 🛠️ Generate Reviewable Patches

```bash
forge workset create copy-mermaid --query "mermaid copy button"

forge implement "Add a Copy Mermaid button next to rendered Mermaid diagrams" \
  --workset copy-mermaid

forge patch show <generated-patch>

forge patch validate <generated-patch>
```

`forge implement` defaults to SEARCH/REPLACE blocks: the model copies exact
file content to edit, Forge applies those blocks in memory, then Forge
deterministically generates and validates the unified diff. The legacy
model-generated diff path remains available with `--output-format unified_diff`,
but SEARCH/REPLACE is the recommended path because it avoids hunk line-number
failures. The command does not apply patches or edit source files directly.
Invalid model output is preserved under `.forge/patches/invalid/` for review.

Forge separates workset context from editable targets. A workset may include
files that help the model understand the task, but `forge implement` approves a
stricter editable target set before asking for SEARCH/REPLACE blocks. For a task
such as `fix SessionControllerIntegrationTest`, the exact test file is required
and related implementation files are limited to the same module when possible.
Blocks for unrelated context files, for example UI files in another package, are
rejected before Forge attempts to apply them.

That enforcement is a safety net for what the model *submits*; Forge also
isolates what the model *sees*. The implementation prompt is built with three
tiers, computed once per request: approved editable targets get full,
line-numbered, SEARCH/REPLACE-ready content; other files in the same module
(DTOs, repositories, adjacent classes the model may need to read but not edit)
get a short summary — category, symbols, a one-line reason — with no verbatim
source and no line numbers; and files outside the approved target's module
(e.g. a UI package when the fix is scoped to an API module) are left out of
the prompt entirely, noted only in an "Omitted Workset Files" diagnostic
section. Repair and regeneration follow-ups reuse the same split, so a failed
attempt never causes the full workset to be resent. `forge implement --json`
and workflow run artifacts report the split as `editable_context_files`,
`context_only_files`, and `omitted_files` for debugging.

`forge patch validate` performs a two-phase check: structural format validation
followed by `git apply --check` against the current working tree. Output
includes `structural_valid`, `apply_check_valid`, validation errors, and
actionable suggestions on failure.

## ✅ Run Engineering Verification

```bash
forge verify

forge verify --json

forge verify --patch <patch> --plan <plan> --workset <workset>

forge verify --detect

forge verify --detect --json
```

`forge verify` executes the deterministic verification strategy Forge detects
for the current working tree. It captures each formatter, linter, build, and
test step as structured engineering evidence with command, working directory,
start and completion time, duration, exit code, stdout, stderr, timeout state,
and status.

Every run writes a JSON report under `.forge/verifications/` unless `--output`
is provided. Reports are Engineering Artifacts and can be associated with
metadata for a workset, plan, or patch. Verification continues after recoverable
step failures so engineers can see all quality gate evidence in one report.

`forge verify --detect` remains available for strategy inspection. It reads
deterministic repository signals such as
`pyproject.toml`, `package.json`, lockfiles, `pom.xml`, `build.gradle`,
`go.mod`, `Cargo.toml`, `.sln`, and `.csproj` files. It returns a structured
strategy with likely build, test, formatter, linter, package manager, ecosystem,
and confidence fields.

Verification does not apply patches, edit source files, or start repair loops.

---

# Engineering Workflow Engine

Forge includes a Workflow Engine that orchestrates existing capabilities into guided end-to-end engineering workflows. The engine is a pure orchestration layer — it delegates to existing application services and produces all artifacts without applying changes.

## Run a Guided Workflow

```bash
# Feature workflow
forge workflow feature "Add Copy Mermaid button"

# Bug fix workflow
forge workflow bugfix "Fix null pointer in auth handler"

# Refactor workflow
forge workflow refactor "Extract retry logic into shared utility"

# Explicit template + task form
forge workflow run feature "Add GitHub OAuth"

# JSON output
forge workflow feature "Add Copy Mermaid button" --json
```

Each workflow executes eight stages in order:

```
Repository → Workset → Context → Plan → Patch → Validate → Verify → Policy
```

After completion, the patch is ready for review and guarded apply:

```bash
forge apply patches/<patch-name>.patch
```

## Inspect Workflow History

```bash
forge workflow list

forge workflow show <run-id>

forge workflow templates
```

## Workflow Artifacts

Each workflow run is registered as a `workflow` artifact under `.forge/workflows/`.  The run record includes all produced artifacts:

- Workset
- Context bundle
- Implementation plan
- Patch
- Verification report
- Policy evaluation

Workflow runs surface in `forge artifacts` alongside all other engineering artifacts.

---

# Engineering Policy and Guarded Apply

Forge enforces a policy gate before any patch is applied to the working tree.

```bash
forge policy show                          # display the active policy
forge policy check <patch>                 # evaluate patch, verification, and git
forge apply <patch>                        # guarded apply with confirmation
forge apply <patch> --yes                  # skip prompt, policy still enforced
forge apply <patch> --force                # override policy failures if allowed
forge apply <patch> --verification <path>  # use a specific verification report
```

`forge apply` runs the following guards in order before touching any file:

1. Validate patch existence — missing patch exits immediately, before any prompt.
2. Validate patch structure (must be a valid unified diff).
3. `git apply --check` — dry-run to confirm patch can be applied cleanly.
4. Load the latest verification report from `.forge/verifications/`.
5. Evaluate the active policy against patch metadata, verification, and git state.
6. Block if policy fails unless `--force` is used and `policy.apply.allow_force` is true.
7. Prompt for confirmation unless `--yes` is supplied (`--yes` skips prompt only, not policy).
8. Apply patch via `git apply`. No commit is created.
9. Persist apply record under `.forge/applications/`.

Policy fields (`patch`, `verification`, `git`, `apply`) may be overridden via
`.forge/policy.yaml`. Defaults are applied when the file is absent.

`--yes` skips the interactive confirmation prompt but never bypasses policy.
`--force` may bypass policy failures only when `policy.apply.allow_force` is `true`.
No model calls occur. No commits are created. No repair loop runs.

Current workflow:

```bash
forge implement "..." --workset <name>
forge patch validate <patch>
forge verify --patch <patch> --workset <name>
forge policy check <patch>
forge apply <patch>
```

Engineering knowledge becomes searchable and influences future planning.

---

# Engineering Artifact Registry

Forge has an internal read-only Engineering Artifact Registry in
`forge/artifacts/`. It provides a common `Artifact` model over the project-local
artifacts Forge already writes:

- `.forge/project.json` repository metadata
- `.forge/worksets/*.json`
- `.forge/context/*`
- `.forge/plans/*.md`
- `.forge/memory/**/*.json`
- `.forge/patches/*.patch`
- `.forge/verifications/*.json`
- `.forge/applications/*.json`

The registry does not expose new CLI commands yet. It preserves existing
storage locations, file formats, and workflows while giving future capabilities
a shared vocabulary for artifact type, path, producer, timestamps, workset
association, sparse relationships, and free-form metadata.

Artifact lifecycle is intentionally simple in this phase:

```text
Existing Forge service writes artifact
        |
Artifact remains in its current storage location
        |
Registry discovers artifact read-only
        |
Future services consume unified metadata and relationships
```

Relationships are explicit and sparse. Forge records only lineage it can infer
reliably, such as a memory entry or saved plan associated with a workset. Future
execution, verification, repair, review, documentation, ADR, and workflow
artifacts can join the same model without storage migration.

---

# Five-Minute Quick Start

## Install Forge

```bash
git clone <forge-repository>

cd forge

python3.12 -m venv .venv

source .venv/bin/activate

pip install -e ".[dev]"
```

---

## Install Ollama

```bash
brew install ollama

brew services start ollama

ollama pull llama3.1:8b
```

---

## Verify Installation

```bash
forge doctor
```

Forge validates:

- Python
- Git
- Docker
- Java
- ripgrep
- Ollama
- installed models

---

## Initialize Your Project

```bash
forge init
```

Creates

```text
.forge/

    project.json

    worksets/

    context/

    plans/

    memory/

    patches/

    architecture/

    sessions/

    cache/
```

---

## Inspect the Repository

```bash
forge repo detect
```

Discover

- Languages
- Frameworks
- Package managers
- Source roots
- Test roots
- Important files

---

## Build a Workset

```bash
forge workset suggest "authentication"
```

Forge builds task-scoped worksets through an offline deterministic pipeline:

```text
Task → Intent → Identifiers → Relationships → Scoring → Assembly → Context
```

The selector ignores action verbs such as `fix`, `add`, and `refactor` as
search terms while still using them to infer intent. CamelCase identifiers are
expanded into searchable parts, test-like identifiers pull in their related
implementation files, and bugfix workflows include tests by default.

Infrastructure files such as `README.md`, `Dockerfile`, and build manifests are
eligible when relevant, but they use a small quota once high-confidence source
matches exist so they cannot crowd out implementation files. Every selected file
keeps explainable reasons such as primary match, relationship, identifier match,
content match, test match, documentation, or infrastructure.

---

## Generate Context

```bash
forge workset context authentication
```

Produces

- Symbols
- Summaries
- Dependency hints
- Excerpts

without calling AI.

---

## Generate a Plan

```bash
forge plan "Add GitHub OAuth" --workset authentication
```

The model receives structured engineering context rather than a blind prompt.

---

## Open the Forge Workbench

```bash
forge web
```

Open

```
http://127.0.0.1:8765
```

---

# Forge Workbench

The browser interface is the visual command center for Forge's engineering
workflow. It is presentation-only: routes consume application services and the
Engineering Artifact Registry, while CLI behavior and backend orchestration stay
unchanged.

Workflows are the primary engineering object. The Dashboard evolves into an Engineering Command Center; every other page surfaces its workflow context.

| Workspace | Purpose |
|-----------|---------|
| Dashboard | Engineering Command Center — current workflow, repository summary, pipeline visualization, workflow metrics, smart next-action, and activity timeline |
| Workflows | Engineering orchestration — start workflows, browse run history, filter by status/template, view full pipeline detail with stage cards and artifact relationships |
| Repository | Engineering overview with detected languages, frameworks, package managers, roots, important files, and build systems |
| Worksets | Build, inspect, refresh, and relate task-scoped file sets to plans, patches, context bundles, and artifacts |
| Planning | Generate implementation plans and browse saved plan artifacts connected to execution, memory, patches, and verification |
| Execution | Read-only visualization of the prepared `ExecutionRequest`, selected model, pipeline stages, prompt summary, memory summary, and context summary |
| Artifacts | Unified Artifact Explorer backed by the read-only registry for repositories, worksets, context bundles, plans, memory entries, patches, and workflows |
| Patches | Patch Explorer for saved unified diffs with affected files, validation state, source metadata, show, validate, and download actions |
| Engineering Memory | Search decisions, investigations, plans, lessons, and navigate naturally to plans, execution, patches, and worksets |
| Project | Project metadata and Forge configuration |
| Verification | Planned |
| Architecture | Planned |

The Workbench uses a common relationship vocabulary:

```text
Workset
        |
        v
Context Bundle
        |
        v
Plan
        |
        v
Execution Request
        |
        v
Patch
        |
        v
Future Verification
        |
        v
Future Apply
```

Generated artifacts remain in their existing `.forge/` locations. The UI
discovers and links them through the Artifact Registry rather than moving files
or duplicating service logic.

*(Screenshot placeholders)*

```
docs/images/dashboard.png

docs/images/worksets.png

docs/images/planning.png

docs/images/execution.png

docs/images/artifacts.png

docs/images/patches.png

docs/images/knowledge.png
```

---

# Supported AI Providers

| Provider | Status |
|----------|:------:|
| Ollama | ✅ Default |
| OpenAI | ✅ Supported |
| Anthropic | ✅ Supported |

Switch providers simply by changing your configuration.

---

# Architecture

Forge now follows an Application Service architecture. CLI commands and web
routes are adapters; they parse input and format output. Workflow coordination
lives in `forge/services/`, deterministic business logic stays in domain
packages, provider calls go through `forge/models/`, and local artifact storage
stays explicit under `.forge/`.

```text
                Forge

          CLI      Web UI
             \      /
              \    /
       Application Services
                     │
     ┌───────────────┼─────────────────┐
     │               │                 │
Repository      Worksets       Engineering
Intelligence                   Knowledge
     │               │                 │
     └───────────────┼─────────────────┘
                     │
           Context Engineering
                     │
               Planning Engine
                  /     \
                 /       \
             Execution    Provider
              Pipeline   Abstraction
                          │
                 Ollama • OpenAI • Anthropic
```

`PlanningService` is the canonical pattern for future services. It coordinates
workset context, Engineering Memory, provider calls, and optional plan
persistence without modifying source files. The Engineering Execution Pipeline
is the next layer: it consumes a plan and coordinates read-only stages that load
the workset, context bundle, Engineering Memory, and implementation plan into a
durable `ExecutionResult`. Future patch generation, validation, application,
verification, repair, documentation, and knowledge capture stages plug into that
pipeline without coupling orchestration to the CLI or model providers.

Detailed guidance: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

# Engineering Philosophy

Forge follows six core principles.

| Principle | Meaning |
|-----------|---------|
| Deterministic First | Repository facts before model output. |
| Human in Control | Forge advises but never silently edits source code. |
| Architecture Before Implementation | Understand software before changing it. |
| Explainability | Worksets, context, and recommendations explain themselves. |
| Engineering Knowledge | Valuable engineering knowledge survives AI sessions. |
| Provider Independence | AI providers are interchangeable. |

---

# Development Workflow

```bash
pytest

pytest -m "not integration"

pytest -m integration

ruff check .

black --check .
```

Contributors should:

- Update the Development Log
- Create ADRs for architectural decisions
- Add tests for every meaningful feature
- Keep repository intelligence deterministic
- Preserve clean architecture
- Update documentation alongside user-facing changes

---

# Repository Artifacts

Forge stores project-local artifacts under:

```text
.forge/
```

| Artifact | Purpose |
|----------|---------|
| `project.json` | Project identity and metadata |
| `worksets/` | Persisted worksets |
| `context/` | Context bundles |
| `plans/` | Saved implementation plans |
| `memory/` | Engineering knowledge |
| `patches/` | Saved raw diff patches for inspection and validation |
| `verifications/` | Structured verification report artifacts |
| `architecture/` | Future architecture artifacts |
| `sessions/` | Future session history |
| `cache/` | Local cache |

Never store secrets under `.forge/`.

---

# Roadmap

| Area | Status |
|------|:------:|
| Repository Intelligence | ✅ Complete |
| Context Engineering | ✅ Complete |
| Engineering Knowledge | ✅ Complete |
| Planning | ✅ Complete |
| Web Workbench | ✅ Complete |
| Engineering Workflow Engine | ✅ Complete |
| Guided Engineering Experience | 🚧 In Progress |
| Architecture Intelligence | ⏳ Planned |
| Patch Generation | ✅ Complete |
| Verification Engine | ✅ Complete |
| Patch Application | ⏳ Planned |
| Agent Orchestration | ⏳ Planned |
| Enterprise Knowledge | ⏳ Planned |

---

# Contributing

Forge is built around **deterministic engineering workflows**.

Before contributing:

1. Read the Constitution.
2. Read the Development Log.
3. Review existing tests.
4. Preserve architectural boundaries.
5. Update documentation with any user-facing changes.

Every meaningful change should include:

- Tests
- Documentation
- Development Log update
- ADR when architecture changes

---

# License

MIT License.
