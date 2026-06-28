# Forge

Forge is a local-first AI software engineering workbench.

This repository currently implements Phase 2F: workset context bundles on top
of the Phase 2E centralized root resolution foundation.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Commands

Forge behaves like Git: call it from any subdirectory inside a repository and it
discovers the repository root automatically by walking upward until it finds `.git`.
Global configuration lives in `~/.forge/`. Project-specific artifacts (worksets,
summaries, sessions) live in `<repo-root>/.forge/`. Do not store secrets in `.forge/`.

Pass `--root <path>` to any command to override automatic root detection.
If no `.git` directory is found, Forge falls back to the current working directory.

```bash
cd src/main/java
forge repo detect           # resolves to the repository root automatically

cd docs
forge workset suggest "model config"   # searches from the repository root

forge repo tree --root ~/projects/forge --max-depth 2
```

```bash
forge init

forge project root

forge project info

forge project paths

cd src/main/java
forge project root   # still resolves to the repository root

forge version
forge doctor
forge config show
forge config edit
forge config set-default-model qwen2.5-coder:14b
forge models
forge models use qwen2.5-coder:14b
forge ask "Explain this project in one sentence."
forge ask --model qwen2.5-coder:32b "Explain this project in one sentence."
forge ask --timeout 180 "Explain dependency injection in Python."
forge explain-project
forge repo detect
forge repo tree --max-depth 3
forge repo grep "@RestController"
forge repo files --ext java
```

`forge ask` sends exactly the prompt you provide. It does not automatically read the
repository. Use `forge explain-project` when you want Forge to inspect the current
working directory and send project context to the configured model.

`forge ask` uses the configured default model unless `--model` is provided. Ollama
requests default to a 120 second timeout; use `--timeout` for a one-off override.

Forge stores local model configuration in `~/.forge/config.yaml`:

```yaml
provider: ollama
default_model: qwen2.5-coder:14b
providers:
  ollama:
    endpoint: http://localhost:11434
    timeout_seconds: 120
```

`forge explain-project` reads common project files when present, including
`README.md`, `pyproject.toml`, JavaScript package files, and
`docs/development/DEVELOPMENT_LOG.md`. It also includes a compact tree that excludes
`.git`, `.venv`, `target`, `build`, `node_modules`, and `dist`.

Repository inspection and workset commands are deterministic and do not call AI models:

```bash
forge repo detect
forge repo tree --max-depth 3
forge repo grep "@RestController"
forge repo files --ext java
forge workset suggest "model manager config"
forge workset suggest "Spring controller service repository" --max-results 15
forge workset suggest "timeout regression tests" --include-tests
forge workset suggest "model config" --json

forge workset create model-config --query "model manager config"
forge workset list
forge workset show model-config
forge workset show model-config --json
forge workset add model-config README.md
forge workset remove model-config README.md
forge workset refresh model-config
forge workset clear model-config --yes

forge workset context model-config
forge workset context model-config --max-lines-per-file 80
forge workset context model-config --json
forge workset context model-config --include-full
forge workset context model-config --output /tmp/context.md
```

`forge workset context <name>` produces a deterministic, model-free context bundle
for the named workset. The bundle includes per-file statistics, file summaries
(classes, functions, imports, headings, top-level keys), detected symbols, dependency
hints, and relevant excerpts around query matches. No AI models are called. Bundles
are saved to `.forge/context/<name>-<timestamp>.md` and are designed to be pasted
into AI tools or used by future Forge planning commands.

`forge workset suggest "<query>"` scores and ranks repository files using filename
terms, path segments, and content matches. Each result includes its score and the
specific reasons it was selected. Use `--include-tests` to include test files, or
omit it to let Forge detect a test-focused query automatically. Use `--json` for
structured output.

`forge repo detect` reports languages, build systems, package managers, frameworks,
likely source/test roots, and important files. `forge repo tree`, `forge repo grep`,
and `forge repo files` all skip common generated/vendor directories such as `.git`,
`.venv`, `node_modules`, `target`, `build`, `dist`, editor folders, and Python caches.
Use `--root <path>` with any repo command to inspect a directory other than the
current working directory.

OpenAI and Anthropic still use the same provider interface and read API keys from the
environment:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

The CLI routes model operations through `ModelManager`, which loads configuration,
selects the active model, validates installed models, and delegates provider-specific
work to the configured provider.

## Development

```bash
pytest
pytest -m "not integration"
pytest -m integration
pytest tests/test_config_manager.py
ruff check .
black --check .
```

Use `pytest` for the full deterministic suite, `pytest -m "not integration"` for unit
tests only, `pytest -m integration` for tests that require external services such as
Ollama, and a file path such as `pytest tests/test_config_manager.py` for focused
iteration.

Future recommendation: add `forge verify` as a single local validation command once
verification orchestration is part of the active phase.

## Phase 2F Scope

Implemented:

- centralized root resolution via `forge.project.resolver.resolve_root()` used by all repo and workset commands
- `forge init` — initialize `.forge/` project structure and `project.json`
- `forge project root` — print the resolved repository root
- `forge project info` — show project identity and detected metadata
- `forge project paths` — show all important Forge paths
- `forge version`
- `forge doctor`
- `forge models`
- `forge ask`
- `forge explain-project`
- structured JSON logging
- model manager abstraction
- Ollama provider
- OpenAI and Anthropic providers with configuration validation
- local `~/.forge/config.yaml` model configuration
- `forge repo tree`
- `forge repo detect`
- `forge repo grep`
- `forge repo files`
- deterministic repository inspection services under `forge.repository`
- `forge workset suggest` with explainable scoring under `forge.worksets`
- `forge workset create`, `list`, `show`, `add`, `remove`, `refresh`, `clear`
- persistent workset storage under `.forge/worksets/<name>.json`
- `forge workset context` — deterministic context bundle generation under `forge.context`
- context bundles saved to `.forge/context/<name>-<timestamp>.md` (or JSON with `--json`)

Deferred until later phases:
- planning
- patch generation and application
- test orchestration
- Git and PR automation
