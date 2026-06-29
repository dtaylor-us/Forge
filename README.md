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
| Local Web Workbench | ✅ | Modern browser interface for planning, worksets, repository analysis, and engineering knowledge. |
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

`forge implement` asks the configured model for a raw unified diff, validates
the response, and saves valid patches under `.forge/patches/`. It does not
apply patches, edit source files directly, run verification, or start repair
loops. Invalid model output is preserved under `.forge/patches/invalid/` for
review.

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

Forge ranks relevant files using deterministic scoring.

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

The browser interface provides a modern engineering experience.

| Workspace | Purpose |
|-----------|---------|
| Dashboard | Project overview, recent activity, workflows |
| Repository | Detection, search, repository structure |
| Worksets | Build, inspect, refresh, manage worksets |
| Planning | Generate implementation plans |
| Engineering Knowledge | Search decisions, investigations, plans, lessons |
| Project | Project metadata and Forge configuration |

*(Screenshot placeholders)*

```
docs/images/dashboard.png

docs/images/worksets.png

docs/images/planning.png

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
| Guided Engineering Experience | 🚧 In Progress |
| Architecture Intelligence | ⏳ Planned |
| Verification Engine | ⏳ Planned |
| Patch Generation | ✅ Complete |
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
