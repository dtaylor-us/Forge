# Forge End-to-End Product Dogfood Report

**Date:** 2026-06-29
**Tester role:** Independent QA engineer / senior developer, exercising Forge as a product (not running its own unit test suite)
**Test subject:** `forge-workbench` CLI + web workbench, against a disposable example application
**Scope:** Phases 0–15 of a fixed end-to-end test plan — init, repo intelligence, worksets, engineering memory, planning, implementation, patch tooling, verification, policy, guarded apply, the workflow engine, artifact layout, the web UI, and error handling.

This report does not implement any fixes. No Forge source file was modified during this exercise; the only write performed inside the Forge repository was the creation of this report.

---

## Executive Summary

Forge's deterministic backbone is real and mostly works. Project initialization, repository detection, workset scoring, context-bundle generation, the engineering-memory knowledgebase (decisions/investigations), patch validation, policy evaluation, guarded apply, the workflow engine's orchestration, the artifact layout under `.forge/`, the web workbench's page rendering, and CLI error handling all behaved correctly and consistently across this session. These are not trivial — workset scoring with transparent, human-readable reasons, a policy engine with a clean pass/fail gate report, and a guarded apply flow with a real confirmation prompt are the kind of details that separate a usable internal tool from a demo.

The part of Forge that the product is actually named for — turning a task description into a model-generated patch via `forge implement` / `forge plan` / `forge workflow feature` — could not be exercised at all in this environment, because Forge's only model backend is Ollama at `http://localhost:11434` with no offline or alternative-provider fallback, and no Ollama instance (or any other LLM) was reachable from this sandbox. Every LLM-dependent command failed identically and immediately with a clean connection-refused error. This is recorded here as an environment limitation, not a Forge defect — but it means the single most important workflow in the product was never genuinely validated in this session.

Critically, this is not merely a gap in this report. A separate, independently dated dogfood report already existed in this repository at `docs/reports/forge-e2e-dogfood-report-20260629.md` before this session began (untracked, same calendar date, evidently produced in an environment where Ollama was actually reachable on macOS with `qwen2.5-coder:32b`). That report's own finding, preserved and cited in this document (see "Prior Session Evidence" below), is that `forge implement` failed 4 out of 4 times even with a working model: the model hallucinated stale file content and produced patches that failed `git apply --check` every time, with the repair loop unable to recover. Taken together with this session's findings, the picture is consistent: the AI-generation pipeline is the part of Forge most likely to fail a new user, whether because no provider is configured (this session) or because the provider produces invalid patches against real files (the prior session).

To genuinely exercise the deterministic back half of the pipeline (patch validation, verification, policy, apply, post-apply regression) in the absence of any usable model, a hand-authored patch implementing the same requested feature was substituted in place of a model-generated one, seeded into `.forge/patches/` using Forge's own naming convention. This is disclosed in full below and in every phase where it applies; the patch's content is synthetic, but every Forge code path that processed it (`forge patch validate`, `forge policy check`, `forge apply`, `forge verify`) is genuine.

**Biggest strengths:** workset scoring with transparent, legible reasons; the engineering memory (decision/investigation) model; the policy engine's check-by-check pass/fail report; guarded apply with a real `[y/N]` confirmation; consistent, scriptable error handling (exit 1, single-line messages, no stack traces, valid `--json` even on failure); a web workbench that renders every page without crashing.

**Biggest blockers:** a hard, unconfigurable dependency on a local Ollama server with no fallback, which makes the core AI workflow untestable in any environment without one (and, per the prior session's evidence, fragile even when one is present); a `forge init` that does not gitignore its own `.forge/` directory or `__pycache__/`, which produces an immediate, confusing policy failure on a brand-new project; and a workflow engine whose `list` command shows a truncated run ID that does not resolve when passed to `show`.

**Readiness rating: Developer Preview.** See "Readiness Rating" below for full justification.

---

## Environment

| Item | Value |
|---|---|
| Test execution platform | Linux sandbox (Ubuntu 22), not the user's native macOS environment |
| Python (sandbox) | 3.10.12, with three targeted compatibility shims (`enum.StrEnum`, `tomllib`, `datetime.UTC`) to satisfy Forge's `>=3.12` stdlib usage — applied entirely outside the Forge repo, in the sandbox virtualenv's site-packages |
| Forge's own `requires-python` | `>=3.12` (`pyproject.toml`) |
| Forge version | 0.1.0 |
| Forge repo branch | main, with 31 pre-existing modified files and several untracked files (`.DS_Store`, `.claude/`, `docs/reports/`) already present before this session started — not introduced by this test, not reverted by this test |
| Git | 2.34.1 |
| ripgrep | 13.0.0 |
| Docker | not found (`forge doctor`: failed) |
| Java | OpenJDK 11.0.31 (optional check) |
| Ollama | not responding at `http://localhost:11434` — confirmed unreachable from this sandbox; network egress allowlist also blocked `ollama.com`, GitHub release-asset downloads, `huggingface.co`, and `python.org`, so no alternative model or interpreter could be obtained |
| `forge doctor` overall | 1 hard failure relevant to this report (Ollama unreachable), plus the expected Python-version failure (3.10.12 vs required ≥3.12, a sandbox artifact, not a real regression — the shims do not and should not fool Forge's own version check) |
| `ruff check .` (Forge repo, before and after testing) | All checks passed |
| `pytest` (Forge repo, before and after testing) | 506 passed (6.24s baseline, 5.37s final) — identical pass count before and after, confirming this dogfood session left the Forge repo's test suite unaffected |

---

## Prior Session Evidence (found in-repo, not produced by this session)

Before writing this report, `docs/reports/` was inspected as instructed. It already contained a complete, dated dogfood report (untracked in git, same filename this report now replaces) describing a session run on macOS Darwin with a working Ollama backend (`qwen2.5-coder:32b`) and full Python 3.12.10. That report is not part of this session's output and its raw command transcript was not re-verified here, but its central finding is directly relevant and is preserved as corroborating evidence:

- `forge implement` was run 3 times standalone and once via `forge workflow feature`; all 4 attempts produced a patch whose context lines did not match the real file content (e.g., the model generated diffs against a list-based note store while the actual repository used a dict-based one). `git apply --check` rejected every patch as corrupt. The built-in single repair attempt did not recover in any run.
- That report rated the product "Developer Preview" for the same underlying reason this report does — independently arrived at — and flagged the same `forge init` gitignore gap (its phrasing: "Updated .gitignore" message vs. actual untracked `.forge/` blocking the policy check) as this session's Phase 2 separately discovered.

This session's environment could not reproduce the prior session's exact failure mode (no model was reachable at all here, vs. a reachable-but-wrong-output model there), but the two sessions' conclusions reinforce each other: across two materially different environments, `forge implement` has never successfully produced an applicable patch against a real, hand-written codebase.

---

## Test Application

A disposable Python library, `forge-dogfood-notes-api`, created fresh for this test at `/tmp/forge-dogfood-notes-api` and git-initialized:

- `notes_api/models.py` — `Note` dataclass
- `notes_api/repository.py` — `NoteRepository`, dict-backed in-memory store, with `create` and `list_active`
- `notes_api/service.py` — `NoteService`, constructor-injected with a repository, exposing `create_note` and `list_notes`
- `tests/test_notes.py` — 3 pytest tests
- `README.md`, `docs/API.md` — minimal docs, the latter explicitly stating "There is no search capability yet."

Baseline: 3 tests passing, `ruff check .` clean. The requested feature throughout this session was: add case-insensitive note search by title and body, including tests and documentation updates — small, realistic, and scoped to exactly the kind of task Forge's planning/implementation pipeline is meant to handle.

---

## Workflow Results

### Phase 0 — Forge Baseline

**Commands:** `git status`, `forge version`, `forge doctor`, `ruff check .`, `pytest` (Forge repo root)

**Observed:** Branch main, working tree already dirty with 31 modified files pre-existing from before this session (not introduced here). `forge version` → 0.1.0. `forge doctor` correctly reported "Python >= 3.12: failed 3.10.12" (it does not get fooled by the sandbox compatibility shims, which is the correct behavior — the shims patch stdlib gaps, not Forge's own version gate) and "Ollama: failed — not responding at http://localhost:11434." `ruff check .` passed cleanly. `pytest` reported 506 passed in 6.24s.

**Pass.** `forge doctor`'s output is exactly the kind of clear, actionable health check a CLI should have: every row states the check, status, and a concrete remediation detail (e.g., the model-timeout row recommends a specific config key to change).

---

### Phase 1 — Disposable Example Application

**Commands:** file creation via heredoc, `git init`, `git commit`, `pytest`, `ruff check .` (example app)

**Observed:** App created cleanly, 3 tests passed, ruff clean. `git init` defaulted to branch `master` (the sandbox's git 2.34.1 default, not "main" — an environment detail, not a Forge issue).

**Pass.**

---

### Phase 2 — Forge Init

**Commands:** `forge init`, `forge project info` (example app)

**Observed:**

```
Initialized Forge project at /tmp/forge-dogfood-notes-api/.forge
  Repository root: /tmp/forge-dogfood-notes-api
  Git detected:    True
  Updated .gitignore: added .forge/, __pycache__/, *.py
```

`.forge/` created with the expected subdirectories (`architecture`, `cache`, `context`, `memory`, `patches`, `plans`, `sessions`, `summaries`, `verifications`, `worksets`) plus `project.json`. `forge project info` correctly reported the repo root, git detection, Forge version, creation timestamp, and detected languages/build system/package manager (Python, pyproject, pip). A grep for key-like strings across `.forge/` found no secrets.

**Issue found:** the console message says `*.py` was added to `.gitignore`, but the actual file content written is `*.py[cod]` (compiled artifacts only, not source). A user skimming this output could reasonably believe `forge init` just gitignored all their Python source files — it did not, the file content is correct, but the confirmation message is truncated/misleading.

**Issue found (more consequential, surfaces later in Phase 9):** `forge init` writes `.gitignore` but does not commit it. The new `.gitignore` itself, plus `.forge/`, remain untracked. This sets up every fresh project for an immediate, confusing `git_clean` policy failure (see Phase 9).

**Pass with two issues.**

---

### Phase 3 — Repository Intelligence

**Commands:** `forge repo detect`, `forge repo tree`, `forge repo grep "NoteService"`, `forge repo grep "search"`

**Observed:** Detection correctly identified Python, pyproject, pip, source root `notes_api`, test root `tests`, important files README.md/pyproject.toml. Tree rendering was clean and complete, including `docs/`. Grep for "NoteService" found all 5 real occurrences across `tests/test_notes.py` and `notes_api/service.py` with correct line numbers. Grep for "search" found the one matching line in `docs/API.md` ("There is no search capability yet.") — confirming prose/doc content is indexed, not just code.

**Pass.** No issues.

---

### Phase 4 — Workset Discovery and Context

**Commands:** `forge workset suggest` (×3 distinct queries), `forge workset create note-search --query "..."`, `forge workset list`, `forge workset show note-search`, `forge workset context note-search`

**Observed:** All three `suggest` queries returned well-ranked, well-reasoned candidate lists. Scoring is transparent and legible: each file's score is broken into named, additive components (e.g., "filename matched 'service' (+10); path matched 'notes', 'api' (+10); content matched ... (+32); source file (+3)"), with an inline content excerpt. For the query `"search notes service repository tests"`, the four files most relevant to the actual feature (service, repository, tests, API doc) ranked at the top, ahead of generic files like `pyproject.toml` and `README.md`.

`forge workset create note-search --query "search notes service repository tests API documentation"` selected all 8 candidate files and reported `Created workset note-search with 8 file(s)`. `forge workset show note-search` rendered per-file score/category/manual-flag/reasons in a table. `forge workset context note-search` generated and saved a context bundle: `/tmp/forge-dogfood-notes-api/.forge/context/note-search-20260629T222500Z.md`, 8 files, 2,748 chars, 684 tokens. The bundle file itself (read in full) was well-structured: metadata header, a file table, and per-file reason/summary/symbols/dependency-hints/excerpt sections.

**Minor issue:** `workset show`'s reasons column is prefixed differently than `workset suggest`'s — a cosmetic inconsistency, not a functional one.

**Pass.** This is one of the most polished parts of the product. A developer reviewing `workset show` output would trust the file selection because the reasoning is visible and sensible, not a black box.

---

### Phase 5 — Engineering Knowledgebase

**Commands:** `forge decision create`, `forge investigation create`, `forge memory timeline`, `forge memory search "search"`

**Observed:** `forge decision create` captured a decision ("Keep notes service dependency-injected", tags: architecture, testing, workset note-search, file notes_api/service.py) and returned ID `2ac88821` plus a `forge memory show 2ac88821` hint. `forge investigation create` captured an investigation ("Search feature implementation options", tags: search, design, files repository.py + service.py) with ID `1601eb1b`. `forge memory timeline` listed both in reverse-chronological order with workset and tags visible in a table. `forge memory search "search"` correctly ranked the investigation highest (score 41, matched on title) and surfaced the decision at a much lower score (5) purely via a substring match on the workset name "note-search" — a minor relevance smell (workset-name substring matches arguably shouldn't score the same tier as title/content matches) but not a functional bug.

**Pass with one minor relevance-tuning observation.** The knowledgebase model (decision/investigation, tagged, linked to a workset and files) is a genuinely useful, well-thought-out feature, and the CLI commands for creating and querying it are clean.

---

### Phase 6 — Planning

**Command:** `forge plan "Add case-insensitive note search by title and body, including tests and API documentation updates" --workset note-search --save`

**Observed:**

```
Planning error: Model provider error: Unable to reach Ollama at http://localhost:11434: [Errno 111] Connection refused
EXIT CODE: 1
```

**Could not be genuinely exercised in this environment.** No LLM provider was reachable; Forge has no offline or deterministic fallback for planning. The failure mode itself was clean: a clear one-line error, correct exit code 1, no stack trace, no hang. This is the correct way to fail when a hard dependency is missing — but it means planning, as a feature, was never actually validated here. (Per the prior in-repo report, even with a reachable model, planning itself succeeded — it correctly identified the right files to change and surfaced the existing decision; the failures begin downstream of planning, at `forge implement`.)

---

### Phase 7 — Implementation Patch Generation

**Command:** `forge implement "Add case-insensitive note search..." --workset note-search`

**Observed:**

```
Provider error: Unable to reach Ollama at http://localhost:11434: [Errno 111] Connection refused
EXIT CODE: 1
```

`forge patch list` correctly reported "No saved patches found in .forge/patches/." afterward — no partial/corrupt state was left behind by the failed attempt.

**Could not be genuinely exercised; root cause is environmental (no provider), not this command's logic.** Per the prior in-repo report (different environment, working Ollama), this is also the single most severe defect found across both sessions: 4/4 real `forge implement` invocations there produced patches with hallucinated, stale file content that failed `git apply --check`, and the repair loop did not recover. Two independent sessions, two different failure mechanisms (no provider vs. wrong provider output), same practical outcome: a user cannot currently rely on `forge implement` to produce an applicable patch.

**To still exercise the deterministic back half of the pipeline** (patch validation, verification, policy, apply, regression — all of which are real Forge product surface independent of any model), a patch implementing the same requested feature was hand-authored against the working tree, captured via `git diff`, the working tree was reverted, and the resulting unified diff was placed into `.forge/patches/` using Forge's own naming convention (`<timestamp>-<slug>.patch`, matching `_unique_artifact_path` in `forge/patches/service.py`). This patch touches exactly the 4 files the task implies (`notes_api/repository.py`, `notes_api/service.py`, `tests/test_notes.py`, `docs/API.md`), uses real diff syntax, and is explicitly **not** a Forge-generated artifact — every downstream phase below states this plainly. Only the patch's authorship is synthetic; every command that subsequently processed it ran the genuine Forge code path.

`forge patch list` and `forge patch show` against the seeded patch rendered correctly — file table with validity/affected-files/size/path, and a clean unified diff on `show`. `forge patch validate` (both plain and `--json`) reported valid: true, 4 affected files, 64 added / 2 removed lines, `structural_valid: true`, `apply_check_valid: true`, no suggestions.

**Implementation generation: untestable here / CRITICAL per corroborating prior evidence. Patch tooling itself (list/show/validate): Pass.**

---

### Phase 8 — Verification

**Commands:** `forge verify --detect`, `--detect --json`, `forge verify`, `forge verify --json`

**Observed:** Strategy detection correctly identified Python/pytest/ruff/black with confidence "high," correctly marking the formatter step as not required while tests and linter are required. `forge verify` ran all three steps and reported `Overall: PASS` with a clean gate table (Formatter PASS, Linter PASS, Build SKIPPED, Tests PASS), duration 0.2s, and saved a JSON artifact under `.forge/verifications/`. The `--json` form included full stdout/stderr/exit codes per step, a summary block, and an `artifact` reference with both absolute and relative paths plus an `artifact_id`. One sandbox-specific wrinkle: black emitted a non-fatal warning about parsing Python 3.15-target code under the sandbox's Python 3.10 — this is a sandbox/Python-version artifact, not a Forge logic bug, and the step still correctly reported `status: pass`.

**Pass.** The `--json` schema here is detailed and well-organized; it would be straightforward to wire into CI.

---

### Phase 9 — Policy

**Commands:** `forge policy show`, `--json`, `forge policy check <patch>`, `--json`, then a second check after fixing worktree state

**Observed:** `forge policy show` rendered the active policy clearly (patch limits, verification requirements, git requirements, apply confirmation rules) in both text and JSON. The first `forge policy check` against the seeded patch correctly **failed** with:

```
✗ git_clean: Working tree has untracked files only (modified=0, staged=0, untracked=1). Add them to .gitignore if they should be excluded, or run 'git add' to track them, then re-run this check.
```

This was a legitimate failure, not a Forge bug: the `.gitignore` written by `forge init` in Phase 2 had never been committed. The error message is exactly right — it correctly distinguishes "untracked" from "modified/staged" and gives two concrete remediation paths. After `git add .gitignore && git commit`, the same check passed cleanly with all 7 gates green, and the JSON output included a `verification_report_used` field pointing at the exact verification artifact that had been consulted — solid traceability between policy and verification.

**Pass, and worth highlighting as the best-designed command in the product:** every gate is named, given a pass/fail status, a human-readable message, and a severity, in a structure that's identical between text and JSON output. Other commands should aspire to this.

**Issue (root cause traced to Phase 2):** the underlying trigger for this failure — `forge init` not committing its own `.gitignore` — means every fresh Forge project will hit this exact policy failure on its first `forge apply`. The policy engine behaved correctly; the project bootstrapping did not finish the job it started.

---

### Phase 10 — Guarded Apply

**Commands:** `forge apply <patch>` (answered `n`), `forge apply <patch> --yes`, post-apply pytest/ruff/verify/git status/diff

**Cancellation test:** Prompt `Apply patch '...' to the working tree? [y/N]:`, answered `n` → `Apply cancelled.`, exit code 0, confirmed zero file changes via `git status`.

**Apply test:** `forge apply <patch> --yes` → `Patch applied: ...`, policy status shown as pass, affected files listed, exit code 0. No automatic commit was created (correct — apply should leave commit decisions to the user). An apply record was saved at `.forge/applications/20260629T222923Z-432c7349.json`.

**Post-apply regression:** `pytest` → 7 passed (3 original + 4 new search tests). `ruff check .` → clean. `forge verify` → PASS across all gates. `git status` → exactly the 4 expected files modified, nothing staged or committed automatically. `git diff --stat` → 64 insertions, 2 deletions across the 4 files, matching the patch exactly.

**Pass, no issues.** This is a textbook guarded-apply flow: real confirmation gate, accurate dry-run-equivalent cancellation, correct non-destructive apply, and a verifiable audit record.

---

### Phase 11 — Workflow Engine

**Commands:** `git reset --hard && git clean -fd` (reset to pre-patch state), `forge workflow templates`, `forge workflow feature "..."`, `forge workflow list`, `forge workflow show <id>`

**Observed:** `forge workflow templates` listed feature/bugfix/refactor, each with the same 8-stage pipeline: repository → workset → context → plan → patch → validate → verify → policy. `forge workflow feature "Add case-insensitive note search..."` ran and correctly executed and reported success for the first three stages (repository, workset, context — these create a fresh, auto-named workset `workflow-feature-fd9d1241` independent of the existing `note-search` workset from Phase 4), then failed cleanly at the `plan` stage with the same Ollama-connection-refused error seen in Phase 6, and exited 1. The failure output included a run ID and two well-formed next-step hints:

```
forge workflow show fd9d12411a354b2a   — inspect stage details
forge workflow clean fd9d12411a354b2a  — remove leftover artifacts
```

`forge workflow list` displayed the run with a **truncated** 12-character ID (`fd9d12411a35`), template, status, truncated task text, and duration. `forge workflow show fd9d1241` (an 8-character prefix) worked via prefix matching and reproduced full stage-by-stage detail.

**Issue:** the ID shown in `forge workflow list` (12 characters) is not the same length as the full ID printed by the run itself or required for unambiguous reference (16 characters); this session's specific 8-character prefix happened to resolve via prefix matching, but the discrepancy between what `list` displays and what a user might copy-paste is a real rough edge — a user copying the 12-character ID shown in `list` should not have to wonder whether it's enough.

**Partial pass.** The orchestration, staging, error surfacing, and artifact linkage of the workflow engine itself are sound — it correctly composed repository → workset → context, correctly halted at the first failing stage, and gave actionable next steps. It inherits the same blocker as `forge implement`/`forge plan` at the `plan` stage, for the same environmental reason.

---

### Phase 12 — Artifact Review

**Command:** `find .forge -maxdepth 3 -type f`

**Observed:** Every artifact category was present, consistently named, and exactly where expected:

```
.forge/applications/20260629T222923Z-432c7349.json
.forge/context/note-search-20260629T222500Z.md
.forge/memory/decisions/2ac88821.json
.forge/memory/index.json
.forge/memory/investigations/1601eb1b.json
.forge/patches/20260629T222813Z-add-case-insensitive-note-search.patch
.forge/project.json
.forge/verifications/verification-20260629T222832Z.json (×3 total)
.forge/workflows/fd9d12411a354b2a.json
.forge/worksets/note-search.json
```

No top-level `forge artifact list/show` CLI command exists (confirmed via `forge --help` and a grep of `forge/cli/app.py`); artifacts must be browsed per-domain (`workset show`, `patch show`, `memory show`, `workflow show`) or by raw filesystem listing. For a tool whose stated value is durable engineering artifacts, a unified artifact browser would reduce friction, especially in the CLI (the web UI does have a dedicated `/artifacts` page — see Phase 13).

`forge workflow feature` has no flag to reuse an existing curated workset; every workflow run mints its own throwaway workset from the raw task string rather than connecting to work already done (e.g., the `note-search` workset and its attached decision/investigation from Phase 4–5 were not used by the Phase 11 workflow run at all). The workflow run's JSON correctly records `artifact_refs` pointing at the workset/context it did create, so artifact linkage is internally consistent — it's just disconnected from prior manual work.

**Pass with two structural observations** (no unified CLI artifact browser; workflows don't reuse existing worksets).

---

### Phase 13 — Web Workbench

**Command:** `forge web --root /tmp/forge-dogfood-notes-api --port 8765`

All ten documented page routes plus the workflow detail page were crawled via HTTP after server startup:

| Page | HTTP | Notes |
|---|---|---|
| `/` (Dashboard) | 200 | shows branch "main", recent workflow run, workset note-search, repo name |
| `/workflows` | 200 | lists the run, status "Failed" — correctly reflects the real failure |
| `/repository` | 200 | loads |
| `/worksets` | 200 | shows "note-search" |
| `/planning` | 200 | loads |
| `/execution` | 200 | loads |
| `/artifacts` | 200 | shows the context bundle, workset JSON, and patch references |
| `/patches` | 200 | shows the seeded patch marked "Valid" |
| `/memory` | 200 | shows both the decision and the investigation by title |
| `/project` | 200 | loads |
| `/workflows/<run-id>` (detail) | 200 | shows all 4 executed stages and surfaces the verbatim backend error text ("Unable to reach Ollama... Connection refused") without crashing |

No page returned a stack trace or an "Internal Server Error" string. Cross-checking the workflow detail page's rendered content against the run's actual JSON on disk confirmed the UI faithfully reproduces backend state rather than masking or stubbing it.

Negative-path checks: `/workflows/does-not-exist` and `/worksets/does-not-exist` both returned styled 404 pages (not stack traces). `/nonexistent-route` (a route that doesn't exist at all, vs. a missing resource under a real route) returned a bare, unstyled default-FastAPI 404 — a minor inconsistency, not a defect.

**Pass.** Every page loads, reflects real backend state accurately (including failure states), and no broken/erroring page was found in this crawl. The one caveat: this was an HTTP-level content crawl (status codes + text search), not an interactive browser session, so JavaScript-driven interactivity, in-page navigation links, and visual rendering were not directly verified.

**Note on test methodology:** the web server initially appeared to die between tool invocations; this was a sandbox artifact (background processes do not persist across separate shell-tool calls here) and was resolved by starting the server, running all checks, and stopping the server within a single shell invocation — not a Forge issue.

---

### Phase 14 — Error Handling

Seven commands targeting nonexistent resources were run against a project with a valid `.forge/` already present:

| Command | Result | Exit code |
|---|---|---|
| `forge workset show does-not-exist` | `Error: Workset 'does-not-exist' not found.` | 1 |
| `forge plan "test task" --workset does-not-exist` | `Planning error: Workset 'does-not-exist' not found.` | 1 |
| `forge patch show does-not-exist.patch` | `Error: Patch 'does-not-exist.patch' not found.` | 1 |
| `forge patch validate does-not-exist.patch` | `Error: Patch 'does-not-exist.patch' not found.` | 1 |
| `forge policy check does-not-exist.patch` | `Error: Patch 'does-not-exist.patch' not found.` | 1 |
| `forge apply does-not-exist.patch --json` | `{"error": "Patch 'does-not-exist.patch' not found."}` | 1 |
| `forge workflow show does-not-exist` | `Workflow run 'does-not-exist' not found.` | 1 |

**Pass, no significant issues.** Every case: exit code 1, a single clear line, no Python traceback, no hang waiting on stdin, and `--json` mode degraded gracefully to a JSON object with an `error` key instead of breaking the machine-readable contract. The only nit is cosmetic: error prefixes vary slightly ("Error: ..." vs. "Planning error: ..." vs. no prefix at all) across commands — not a functional problem, just a small consistency gap.

---

### Phase 15 — Final Forge Regression

**Commands:** `git status`, `ruff check .`, `pytest` (Forge repo root, after all testing)

**Observed:** `ruff check .` → all checks passed. `pytest` → 506 passed in 5.37s, identical pass count to the Phase 0 baseline. `git status` showed the same 31 pre-existing modified files and untracked entries (`.DS_Store`, `.claude/`, `docs/reports/`) as at Phase 0 — this session did not introduce, fix, or otherwise touch any of them.

**Pass.** The Forge repository's own test suite and lint configuration are unaffected by this dogfood exercise, confirming the testing was conducted entirely against the disposable example application and did not leak into Forge's own source tree.

---

## Feature Coverage Matrix

| Feature | Tested | Result | Notes |
|---|---:|---|---|
| init | Yes | Pass with issues | Misleading `.gitignore` confirmation message; new `.gitignore` not auto-committed, causing a downstream policy failure |
| repo intelligence (detect/tree/grep) | Yes | Pass | Accurate detection and search, including doc content |
| worksets (suggest/create/list/show) | Yes | Pass | Best-in-class transparent scoring; minor reason-format inconsistency between `suggest` and `show` |
| context bundles | Yes | Pass | Well-structured, accurate file/token counts |
| memory (decision/investigation) | Yes | Pass | Minor relevance-scoring smell on workset-name substring matches |
| planning | Attempted, blocked | Untestable here | No LLM provider reachable; clean failure mode; prior in-repo report shows it works correctly when a model is available |
| implement (AI patch generation) | Attempted, blocked | Untestable here / Critical per corroborating evidence | No LLM provider reachable in this session; prior in-repo report (different environment, working Ollama) found 4/4 failures from hallucinated patch context |
| patch validation (list/show/validate) | Yes (against seeded patch) | Pass | Clean text and JSON output, structurally and semantically correct |
| verification | Yes | Pass | Detailed `--json` schema; one sandbox-only black/Python-version warning, non-fatal |
| policy | Yes | Pass | Best-designed command in the product; correctly caught a real pre-existing dirty-worktree issue |
| apply (guarded) | Yes | Pass | Cancellation, confirmation, non-destructive apply, and audit record all correct |
| workflow engine | Yes | Partial pass | Orchestration/staging/error-surfacing correct; blocked at `plan` stage (same root cause as implement/plan); `list`/`show` ID-length mismatch |
| artifacts | Yes | Pass with observations | All categories present and consistent; no unified CLI artifact browser; workflows don't reuse existing worksets |
| web workbench | Yes | Pass | All 10+ pages return 200 with accurate content; minor 404-styling inconsistency |
| error handling | Yes | Pass | Consistent exit codes and clean messages; minor prefix-wording inconsistency |

---

## Issue Register

| ID | Severity | Area | Issue | Evidence | Suggested Fix |
|---|---|---|---|---|---|
| I-01 | Critical | implement | The core AI-generation workflow (`forge implement`, and transitively `forge plan`/`forge workflow feature`) cannot be relied upon to produce an applicable patch. In this session it was entirely untestable (no LLM provider reachable, by hard design with no fallback). In a separately-dated in-repo report from a different environment with a working Ollama backend, it failed 4/4 times because the model hallucinated stale file content, producing patches that failed `git apply --check`. | This session: `Provider error: Unable to reach Ollama at http://localhost:11434: [Errno 111] Connection refused` on every LLM-dependent command. Prior report: invalid patches in `.forge/patches/invalid/` showing context mismatched against real file content (e.g., list-based vs. dict-based store). | Add at least one non-Ollama provider option (even a "paste this prompt into any model" manual mode) so the tool is usable without a local Ollama install; separately, make the implementation prompt enforce verbatim file context (e.g., re-derive diff context from the real file post-generation, or validate context line-by-line before sending to the model) so hallucinated content is caught before being surfaced as a "patch." |
| I-02 | High | init / policy | `forge init` does not commit (or gitignore in a way that avoids the issue entirely) its own generated state. The result: a brand-new Forge project fails its very first `forge policy check` with a `git_clean` error caused entirely by Forge's own untracked `.gitignore`/`.forge/` files. | Phase 2/9 transcript: policy check failed with `untracked=1` immediately traceable to the just-created `.gitignore`; resolved only by manually committing it. | Have `forge init` either commit the `.gitignore` change itself (with a clear message) or prompt/offer to do so, so the very next command a new user runs doesn't fail. |
| I-03 | Medium | init | `forge init`'s console confirmation says `.gitignore` was updated with "*.py" when the actual file content correctly writes "*.py[cod]" — the message text doesn't match the file content and could be misread as "all Python source files were gitignored." | Phase 2 transcript, direct comparison of stdout vs. `.gitignore` file contents. | Fix the confirmation string to print the literal pattern written, not a hand-shortened paraphrase. |
| I-04 | Medium | workflow | `forge workflow list` displays a 12-character truncated run ID; the canonical ID is 16 characters. The two don't visually match, and a user who copies exactly what `list` shows has no guarantee it will resolve unambiguously with `show` (this session's 8-char manual prefix happened to work via prefix matching, but the displayed 12-char form in `list` was never directly tested against `show` for an exact-length match). | Phase 11 transcript: `list` shows `fd9d12411a35`; the run's own self-reported full ID is `fd9d12411a354b2a`. | Make `workflow list`'s displayed ID the same value (or same guaranteed-unique prefix length) that `workflow show` accepts, and document/test that exact relationship. |
| I-05 | Low | memory | `forge memory search` ranks unrelated decisions if their content happens to substring-match inside a workset *name* (e.g., a query for "search" surfaced an unrelated decision purely because it belongs to the workset literally named "note-search"). | Phase 5 transcript: decision "Keep notes service dependency-injected" scored 5 on query "search" via `workset:workset: note-search`. | Down-weight or exclude workset-name substring matches from semantic relevance scoring, or label that match reason more specifically so it's clear it's a name collision, not a content match. |
| I-06 | Low | CLI consistency | Error message prefixes vary across commands ("Error: ...", "Planning error: ...", or no prefix), and workset/worksets `show` vs `suggest` format their per-file "reasons" column slightly differently. | Phase 4 and Phase 14 transcripts. | Normalize on one error-prefix convention and one reason-rendering format across all commands. |
| I-07 | Low | web | Unknown top-level routes (`/nonexistent-route`) return a bare, unstyled default 404, while unknown resources under known routes (`/workflows/does-not-exist`) return a styled, on-brand 404 page. | Phase 13 transcript: byte-size and content comparison (22 bytes plain JSON vs. 12,000+ byte styled page). | Add a catch-all 404 handler styled consistently with the rest of the web UI. |
| I-08 | Low | artifacts/CLI | There is no unified `forge artifact list/show` command; durable artifacts must be browsed per-domain or via raw filesystem listing, and `forge workflow feature` does not let a user reuse an already-curated workset (it always mints a new throwaway one from the task string). | Phase 12 transcript: confirmed via `forge --help` and grep of `forge/cli/app.py`; workflow run's workset was `workflow-feature-fd9d1241`, distinct from the manually curated `note-search` workset. | Add a top-level `forge artifact` command for cross-domain browsing; add a `--workset` flag to `forge workflow feature/bugfix/refactor` to reuse existing worksets. |

---

## UX Findings

The policy command is the strongest piece of UX in the product: every gate gets a name, a pass/fail glyph, a human-readable message, and a severity, in a format that's identical between the terminal table and the `--json` output. This consistency should be the template other commands converge toward — `forge verify`'s gate table is close but the JSON schema, while detailed, organizes information slightly differently than policy's.

Workset scoring's transparency is a genuine differentiator. Most tools that auto-select "relevant files" for an AI task are black boxes; Forge shows exactly why each file scored what it did, broken into named additive components with content excerpts. This is the kind of detail that will earn a skeptical developer's trust faster than almost anything else in the product.

The workflow engine's failure messaging is good practice worth replicating: on failure it didn't just say "failed" — it printed the failed stage, the underlying error, the run ID, and two copy-pasteable next commands (`workflow show`, `workflow clean`). Commands like `forge verify` or `forge patch validate` could adopt the same "here's exactly what to run next" pattern when they fail.

The guarded-apply confirmation flow is correctly cautious without being annoying: a single `[y/N]` prompt, a clean cancellation path that leaves zero side effects, and a `--yes` flag for scripted/CI use. This is the right shape for a "this command mutates your working tree" gate.

The biggest first-five-minutes UX risk is the `forge init` → `forge policy check` interaction: a brand-new user who runs `forge init`, makes a change, and tries to apply a patch will hit a `git_clean` failure caused entirely by Forge's own untracked files, with no signal at `init` time that this is coming. The error message itself, once you hit it, is clear and actionable — but the experience of hitting it at all, on a fresh project, before you've done anything wrong, is avoidable.

---

## Architecture/Product Findings

Forge's deterministic services (repository detection, workset scoring, context excerpting, memory indexing, patch validation, policy evaluation, verification strategy detection) are independently solid and don't depend on the model layer at all — they could ship and be useful as a standalone "engineering context and governance" tool even if the AI-generation half were removed entirely. This is a meaningful architectural strength: the product's value isn't actually concentrated in the LLM call, even though its name and primary pitch are.

The single point of failure is the hard, unconfigurable binding to Ollama in `ModelManager`/`ImplementationService` — there is no abstraction seam for "no provider available" beyond a clean error, and no alternative provider path (cloud API, manual paste-and-resume, or a deterministic stub mode for testing/CI). Given that `forge plan`, `forge implement`, and the `plan`/`patch` stages of every workflow template all route through this same dependency, a single missing or misbehaving Ollama instance disables the majority of the product's advertised functionality at once. This is the architectural root of both this session's "untestable" finding and the prior in-repo report's "4/4 hallucinated patches" finding — the latter is a symptom of the implementation service trusting model output as ground truth for diff context rather than re-deriving or strictly validating it against the real file before treating it as authoritative.

The workflow engine's stage model (repository → workset → context → plan → patch → validate → verify → policy) is a sound, legible pipeline design, and its artifact-linkage (`artifact_refs` pointing at the exact workset/context/patch paths a run touched) is implemented correctly. Its disconnection from manually-curated worksets and memory entries (an engineer who already did the legwork in Phase 4/5 gets no benefit from it when running Phase 11's workflow) suggests the workflow engine and the manual CLI commands were built as two separate paths to the same destination rather than one path with multiple entry points — worth unifying.

The `.forge/` directory structure itself (`architecture`, `cache`, `context`, `memory`, `patches`, `plans`, `sessions`, `summaries`, `verifications`, `worksets`) is sensible and was fully and consistently populated for every kind of artifact this session actually produced. `sessions`, `summaries`, and `architecture` were never populated, which is expected given this session never exercised whatever features write to them, not evidence of a defect.

---

## Readiness Rating

**Developer Preview.**

The deterministic workflows — init, repository intelligence, worksets, context bundling, engineering memory, patch validation, verification, policy, guarded apply, workflow orchestration short of the model call, artifact layout, the web workbench, and error handling — are consistently well-built, internally consistent, and ready for an internal developer other than the author to pick up and use today, with two caveats that should be fixed first (I-01's environment-dependency framing and I-02's gitignore gap).

The product cannot be rated above Developer Preview because its headline capability — AI-assisted planning and patch generation — was either completely unusable (this session, no provider reachable, no fallback) or unreliable (the prior in-repo session, working provider, 4/4 hallucinated-context failures). A tool cannot be "Internal Dogfood Ready" if the workflow it's named for doesn't work in the only two environments it's been tested in to date. This is not a verdict on whether the idea is sound — the surrounding scaffolding strongly suggests it is — but on whether a developer who isn't the author, dropping in cold, would have a working experience with the core feature on day one. Based on the combined evidence from both sessions, they would not.

---

## Recommended Next Actions

### Must Fix

1. **[I-01] Make the AI-generation pipeline either reliable or honestly optional.** At minimum, harden the implementation prompt/validation loop so hallucinated patch context is caught and repaired (or rejected with a clear "could not generate a valid patch against your actual files" message) rather than silently failing the same way every time. Strongly consider supporting at least one alternative to a local Ollama instance so the tool is usable in CI, sandboxes, and on machines without a local model server.

2. **[I-02] Fix the `forge init` → policy-check footgun.** Commit the `.gitignore` Forge writes (or otherwise ensure a freshly initialized project starts with a clean worktree from Forge's own perspective) so the very first thing a new user does isn't a confusing policy failure.

### Should Fix

3. **[I-04] Reconcile workflow run ID display between `list` and `show`.** Either show the full ID in `list` or guarantee the truncated form is always sufficient for `show`, and add a regression test for this specific relationship.

4. **[I-03] Correct the `forge init` `.gitignore` confirmation message** to print the literal pattern written.

5. **[I-08] Add a `--workset` flag to `forge workflow <template>`** so workflow runs can build on manually curated worksets and memory entries instead of always starting fresh.

### Nice to Have

6. **[I-05] Tighten memory search relevance scoring** so workset-name substring matches don't compete with title/content matches at a similar tier.

7. **[I-06] Normalize error-message prefixes and reason-column formatting** across CLI commands for a more consistent feel.

8. **[I-07] Add a styled catch-all 404 handler** to the web workbench for unknown top-level routes.

9. **Add a unified `forge artifact list/show` command** for cross-domain artifact browsing, complementing the existing web `/artifacts` page.
