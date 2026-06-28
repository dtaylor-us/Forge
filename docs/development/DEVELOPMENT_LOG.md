# Dev Log

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

# Development Log

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
