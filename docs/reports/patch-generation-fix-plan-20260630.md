# Patch Stage Failure: Root Cause and Fix Plan

**Run:** `forge workflow bugfix "fix SessionControllerIntegrationTest"` (run ID `d76798b502274874`)
**Failed stage:** `patch`
**Error:** `Patch generation produced an invalid patch: No SEARCH/REPLACE blocks found in model output.`
**Date:** 2026-06-30

## Summary

The patch stage doesn't fail because the SEARCH/REPLACE design is wrong — it's a sound,
well-documented alternative to unified diffs (`forge/srp/__init__.py` explains the
rationale clearly: the model copies content verbatim instead of computing line numbers).
It fails because of two plumbing bugs upstream of the parser, the larger of which is a
hardcoded 1024-token output cap that the live config system has no way to override. For
a task like fixing `SessionControllerIntegrationTest` — which needs the model to
reproduce verbatim, multi-line SEARCH context across what's likely a sizeable Java test
file — 1024 tokens is exhausted before the model emits a single complete block, so the
parser correctly finds zero blocks and the applier reports the generic error seen above.
The same cap applies to every one of the workflow's 3 repair attempts, so retrying
doesn't help; the run was always going to fail.

## Root cause #1 (primary): output token budget is hardcoded to 1024 and unconfigurable in the live config path

`forge/models/anthropic.py` and `forge/models/openai.py` default `max_tokens=1024`.
`ModelManager._provider()` (`forge/models/manager.py`), which is what every real CLI
and workflow call goes through, constructs these providers directly and **never passes
`max_tokens`**:

```python
return AnthropicProvider(
    os.getenv("ANTHROPIC_API_KEY"),
    base_url=endpoint or "https://api.anthropic.com/v1",
)
```

There is a separate `Settings` / `create_provider()` path (`forge/config/settings.py`,
`forge/models/factory.py`) that *does* thread `max_tokens` through and even honors a
`FORGE_MAX_TOKENS` env var — but `ModelManager` doesn't call it. It loads config via
`ConfigManager` / `ForgeConfig` / `ProviderConfig` instead, and `ProviderConfig`
(`forge/config/manager.py`) only has `endpoint` and `timeout_seconds` fields. There is
no `max_tokens` anywhere in that struct, in `~/.forge/config.yaml` parsing, or in its
rendering. The two config systems are disconnected: one is fully wired but dead, the
other is live but missing the field entirely.

Net effect: every Anthropic/OpenAI call Forge makes — plan generation, patch
generation, every repair attempt — is silently capped at 1024 output tokens, with no
config flag, env var, or CLI option that changes it.

A second, related gap: `ModelResponse` (`forge/models/types.py`) carries only
`content`, `model`, `provider`. It drops the provider's stop/finish reason and token
usage entirely, so even if the cap were raised, Forge has no way to *detect* a
truncated response and tell the difference between "the model truncated" and "the
model genuinely produced no blocks."

## Root cause #2 (compounding): the SEARCH/REPLACE path doesn't strip markdown fences

`_implement_unified_diff()` in `forge/services/implementation_service.py` calls
`_strip_markdown_fence(response.content)` before validating, because models often wrap
output in ` ``` ` fences despite "no Markdown fences" instructions. `_implement_search_replace()`
has no equivalent call — `raw_response` goes straight into `parse_search_replace_blocks()`
unstripped, on both the initial call and every repair call.

This matters because of how the parser locates a block's file path
(`forge/srp/parser.py`): it walks backward from `<<<<<<< SEARCH` to the nearest
non-blank line and requires it to look like a path (`_FILEPATH_RE`, which requires a
`/` or `.`). If the model fences its output (` ```java `), that fence line sits directly
above the marker, fails the path regex, and the whole block is silently dropped —
parser returns `[]`, applier reports the same generic "no blocks found" error. This is
a real, fixable gap even though it isn't the run's primary cause.

## Root cause #3 (diagnosability): the failure is reported without the data needed to diagnose it

`ImplementationResult.raw_response_path` is populated on every rejection
(`save_invalid_response(...)` is called in all three failure branches of
`_implement_search_replace`), and `forge implement` *does* print it
(`cli/app.py:1426`). But `_stage_patch` in `forge/workflows/engine.py` raises a
`WorkflowEngineError` built only from `'; '.join(impl.validation_errors)` — it discards
`raw_response_path` entirely. `_render_workflow_run()` then prints only `stage.error`.
So the artifact that would have shown this was a truncation (an empty or
mid-block-cutoff response) is written to disk but never surfaced to the terminal,
which is why the only way to find this was reading source.

## Why this is the right fix vs. alternatives

- **Don't redesign the diff format.** SEARCH/REPLACE is already the documented "model-friendly
  alternative to unified diffs" and the design is correct — the bug is in the I/O
  plumbing around it (token budget, fence handling, error surfacing), not the format
  itself. Switching formats again wouldn't change anything because the same 1024-token
  cap would still truncate whatever format was chosen.
- **Don't just raise `repair_attempts`.** The workflow already uses 3 repair attempts,
  and every attempt hits the identical cap, so more attempts only burn API calls for
  the same guaranteed failure. The cap must be fixed before retries can help.
- **Fix the cap at the source (provider config), not the symptom (parser leniency).**
  Making the parser tolerant of fences is good hygiene and worth doing for parity with
  the unified-diff path, but it would not have saved this run if the response was
  truncated before any marker was even emitted.

## Fix Plan

### P0 — unblock patch generation

1. **Wire `max_tokens` into the live config path.** Add a `max_tokens` field to
   `ProviderConfig` (`forge/config/manager.py`), parse/render it in
   `_provider_configs` / `_render_config`, and pass it through in
   `ModelManager._provider()` when constructing `AnthropicProvider` / `OpenAIProvider`.
   Support a `FORGE_MAX_TOKENS` env var override for parity with the (currently dead)
   `Settings.from_env()` path.
2. **Raise the default.** 1024 is too low for any code-generation workload. Move the
   default to something realistic for patch/diff output (commonly 4096–8192 depending
   on provider) and consider a higher default specifically for the patch and repair
   prompts, since repair prompts re-include the original response plus authoritative
   excerpts and may need to reproduce more content, not less.
3. **Decide the fate of `forge/config/settings.py` + `forge/models/factory.py`.**
   They're currently dead code that looks live (fully wired, tested-looking, never
   called). Either delete them or make `ModelManager` use `create_provider()` as the
   single source of truth — keeping both creates exactly this kind of silent drift.

### P1 — make truncation visible instead of silent

4. **Extend `ModelResponse`** with a `stop_reason` (or `truncated: bool`) field and
   plumb it from each provider's `_extract_*` helper (Anthropic: `stop_reason ==
   "max_tokens"`; OpenAI Responses API: `incomplete_details.reason ==
   "max_output_tokens"`; Ollama: `done_reason`).
5. **Have `_parse_and_apply_srp` / the unified-diff path check that flag** when zero
   blocks (or an invalid patch) come back, and emit a distinct, actionable error —
   e.g. `"Model response was truncated at the token limit before any complete
   SEARCH/REPLACE block was produced. Increase max_tokens."` — instead of the generic
   "no blocks found," which currently looks identical whether the model refused,
   misformatted, or was cut off mid-token.
6. **Surface `raw_response_path` (and the truncation flag) in workflow failures.**
   `_stage_patch` should attach `impl.raw_response_path` to the raised
   `WorkflowEngineError` (or store it on the stage/run artifact) and
   `_render_workflow_run` should print it next to "Failed stage," matching what
   `forge implement` already does standalone.

### P2 — close the fence-stripping gap and harden the parser

7. **Call the same fence-stripping helper in `_implement_search_replace`** (generalize
   `_strip_markdown_fence` to handle blocks with a leading file-path line preceding the
   fence, or strip fences before the parser runs) on both the initial response and
   every repair response.
8. **Make `parse_search_replace_blocks` itself fence-tolerant** as defense in depth:
   when scanning backward for the file path, skip lines that are pure fence delimiters
   (``` or ```lang) the same way blank lines are already skipped, rather than relying
   solely on prompt compliance.

### P3 — regression coverage

9. Add `tests/test_srp.py` cases for: (a) model output wrapped in a ` ```diff `/` ``` `
   fence with a file path immediately above the fence, (b) a response that is cut off
   mid-block (no `>>>>>>> REPLACE` reached) — should produce the new truncation-specific
   error, not the generic one, (c) `ModelManager._provider()` actually passing a
   configured `max_tokens` through to the constructed provider (a unit test would have
   caught root cause #1 directly).
10. Add an integration-style test for `_stage_patch` asserting that
    `raw_response_path` ends up in the raised error / stage output when generation
    fails, covering root cause #3.

## Suggested sequencing

P0 items (1–3) are the actual unblock for this run and should land first — without
them, nothing else in this plan will change the outcome of `forge workflow bugfix`. P1
(4–6) is what turns the next failure (because there will be edge cases even at a higher
token budget) into a two-second diagnosis instead of a source-reading exercise. P2–P3
are correctness/regression hardening that should ride along with the same change since
they touch the same files.
