# Forge

Forge is a local-first AI software engineering workbench.

This repository currently implements Phase 1: the CLI foundation.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Commands

```bash
forge version
forge doctor
forge config show
forge config edit
forge config set-default-model qwen2.5-coder:14b
forge models
forge models use qwen2.5-coder:14b
forge ask "Explain this project in one sentence."
forge ask --model qwen2.5-coder:32b "Explain this project in one sentence."
```

`forge ask` uses the configured default model unless `--model` is provided.

Forge stores local model configuration in `~/.forge/config.yaml`:

```yaml
provider: ollama
default_model: qwen2.5-coder:14b
providers:
  ollama:
    endpoint: http://localhost:11434
```

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
ruff check .
black --check .
```

## Phase 1 Scope

Implemented:

- `forge version`
- `forge doctor`
- `forge models`
- `forge ask`
- structured JSON logging
- model manager abstraction
- Ollama provider
- OpenAI and Anthropic providers with configuration validation
- local `~/.forge/config.yaml` model configuration

Deferred until later phases:

- repository scanning
- worksets
- planning
- patch generation and application
- test orchestration
- Git and PR automation
