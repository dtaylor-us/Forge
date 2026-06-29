"""Forge command-line interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from forge.commands.doctor import CheckResult, run_doctor
from forge.commands.project_context import build_project_explanation_prompt
from forge.config.manager import ConfigManager
from forge.execution import ExecutionServiceError
from forge.memory.store import MemoryStoreError
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelManager, ModelNotFoundError
from forge.patches import PatchError
from forge.planning import PlannerError
from forge.planning.render import render_plan_json, render_plan_text
from forge.services import (
    apply_service,
    git_service,
    implementation_service,
    memory_service,
    patch_service,
    planning_service,
    policy_service,
    project_service,
    repository_service,
    verification_service,
    workflow_service,
    workset_service,
)
from forge.services.apply_service import ApplyError, PolicyBlockedError
from forge.utils.logging import configure_logging
from forge.version import __version__
from forge.web.app import create_app
from forge.worksets.store import WorksetStoreError

app = typer.Typer(
    name="forge",
    help="Local-first AI software engineering workbench.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Manage Forge configuration.")
models_app = typer.Typer(help="Manage configured provider models.")
repo_app = typer.Typer(help="Inspect the current repository deterministically.")
workset_app = typer.Typer(help="Build and inspect worksets of relevant files.")
project_app = typer.Typer(help="Show project identity and Forge path information.")
memory_app = typer.Typer(help="Manage the engineering memory knowledge base.")
patch_app = typer.Typer(help="Inspect and validate saved patches.")
git_app = typer.Typer(help="Inspect Git repository state.")
policy_app = typer.Typer(help="Inspect and evaluate engineering policy.")
workflow_app = typer.Typer(help="Run guided engineering workflows.")
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")
app.add_typer(repo_app, name="repo")
app.add_typer(workset_app, name="workset")
app.add_typer(project_app, name="project")
app.add_typer(memory_app, name="memory")
app.add_typer(patch_app, name="patch")
app.add_typer(git_app, name="git")
app.add_typer(policy_app, name="policy")
app.add_typer(workflow_app, name="workflow")
console = Console()


def _config_manager() -> ConfigManager:
    return ConfigManager()


def _model_manager() -> ModelManager:
    return ModelManager(_config_manager())


def _handle_provider_error(exc: ModelProviderError) -> None:
    console.print(f"[red]Provider error:[/red] {exc}")
    raise typer.Exit(code=1) from exc


def _handle_model_not_found(exc: ModelNotFoundError) -> None:
    console.print(f"[red]Model not found:[/red] {exc.requested_model}")
    console.print("Run [bold]forge models[/bold] to see installed models.")
    if exc.suggestions:
        console.print("Closest installed models:")
        for model in exc.suggestions:
            console.print(f"  {model.name}")
    raise typer.Exit(code=1) from exc


@app.callback()
def configure(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging.")] = False,
) -> None:
    """Configure shared CLI behavior."""
    configure_logging(verbose)


@app.command()
def version() -> None:
    """Print the Forge version."""
    console.print(__version__)


@app.command()
def doctor() -> None:
    """Verify local tools needed by Forge."""
    checks = run_doctor(_config_manager().load())
    table = Table(title="Forge Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    for check in checks:
        table.add_row(check.name, _status(check), check.detail)

    console.print(table)
    failed_required = [check for check in checks if check.required and not check.ok]
    raise typer.Exit(code=1 if failed_required else 0)


@app.command("verify")
def verify(
    detect: Annotated[
        bool,
        typer.Option("--detect", help="Detect verification strategy without executing commands."),
    ] = False,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output verification data as JSON."),
    ] = False,
    patch: Annotated[
        str | None,
        typer.Option("--patch", help="Patch metadata to associate with this verification."),
    ] = None,
    plan: Annotated[
        str | None,
        typer.Option("--plan", help="Plan metadata to associate with this verification."),
    ] = None,
    workset: Annotated[
        str | None,
        typer.Option("--workset", help="Workset metadata to associate with this verification."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Path to write the verification report JSON."),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", min=1.0, help="Timeout in seconds for each verification step."),
    ] = 300.0,
) -> None:
    """Execute repository verification or inspect the detected strategy."""
    resolved = project_service.resolve_project_root(root)
    if detect:
        result = verification_service.detect(resolved.root)
        if output_json:
            console.print_json(json.dumps(result))
            return
        _render_detection(result)
        return

    try:
        report = verification_service.run(
            resolved.root,
            timeout=timeout,
            output_path=output,
            patch=patch,
            plan=plan,
            workset=workset,
        )
    except verification_service.VerificationServiceError as exc:
        if output_json:
            console.print_json(json.dumps({"error": str(exc), "overall_status": "error"}))
        else:
            console.print(f"[red]Verification infrastructure error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if output_json:
        console.print_json(json.dumps(report))
    else:
        _render_verification_report(report)
    raise typer.Exit(code=verification_service.exit_code(report))


@config_app.command("show")
def config_show() -> None:
    """Print the active Forge configuration."""
    console.print(_config_manager().show())


@config_app.command("edit")
def config_edit() -> None:
    """Open the Forge configuration file in $EDITOR."""
    path = _config_manager().edit()
    console.print(f"Config file: {path}")


@config_app.command("set-default-model")
def config_set_default_model(
    model: Annotated[str, typer.Argument(help="Model to persist as the default.")],
) -> None:
    """Validate and persist the default model."""
    try:
        config = _model_manager().use_model(model)
    except ModelNotFoundError as exc:
        _handle_model_not_found(exc)
    except ModelProviderError as exc:
        _handle_provider_error(exc)
    console.print(f"Default model set to {config.default_model}")


@models_app.callback(invoke_without_command=True)
def models_command(ctx: typer.Context) -> None:
    """Enumerate installed models for the configured provider."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        manager = _model_manager()
        config = manager.config()
        models = manager.list_models()
    except ModelProviderError as exc:
        _handle_provider_error(exc)

    table = Table(title=f"Forge Models ({config.provider.value})")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Active")
    table.add_column("Details")
    for model in models:
        active = "*" if model.name == config.default_model else ""
        table.add_row(model.provider, model.name, active, model.details or "")
    console.print(table)


@models_app.command("use")
def models_use(
    model: Annotated[str, typer.Argument(help="Installed model to use by default.")],
) -> None:
    """Validate and persist the default model."""
    try:
        config = _model_manager().use_model(model)
    except ModelNotFoundError as exc:
        _handle_model_not_found(exc)
    except ModelProviderError as exc:
        _handle_provider_error(exc)
    console.print(f"Default model set to {config.default_model}")


@app.command()
def ask(
    prompt: Annotated[str, typer.Argument(help="Prompt to send to the configured model.")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override for this request."),
    ] = None,
    timeout_seconds: Annotated[
        int | None,
        typer.Option(
            "--timeout",
            help="Request timeout in seconds for this ask.",
        ),
    ] = None,
) -> None:
    """Ask the configured model a question."""
    try:
        response = _model_manager().ask(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except ModelNotFoundError as exc:
        _handle_model_not_found(exc)
    except ModelProviderError as exc:
        _handle_provider_error(exc)
    console.print(response.content)


@app.command("explain-project")
def explain_project(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override for this request."),
    ] = None,
    timeout_seconds: Annotated[
        int | None,
        typer.Option(
            "--timeout",
            help="Request timeout in seconds for this explanation.",
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to explain (default: auto-detected)."),
    ] = None,
) -> None:
    """Explain the current project using explicit local project context."""
    resolved = project_service.resolve_project_root(root)
    prompt = build_project_explanation_prompt(resolved.root)
    try:
        response = _model_manager().ask(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except ModelNotFoundError as exc:
        _handle_model_not_found(exc)
    except ModelProviderError as exc:
        _handle_provider_error(exc)
    console.print(response.content)


@repo_app.command("tree")
def repo_tree(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    max_depth: Annotated[
        int,
        typer.Option("--max-depth", min=0, help="Maximum directory depth to print."),
    ] = 3,
) -> None:
    """Print a compact repository tree."""
    resolved = project_service.resolve_project_root(root)
    for line in repository_service.tree(resolved.root, max_depth=max_depth)["lines"]:
        console.print(line)


@repo_app.command("detect")
def repo_detect(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
) -> None:
    """Detect repository characteristics."""
    resolved = project_service.resolve_project_root(root)
    detection = repository_service.detect(resolved.root)
    table = Table(title="Repository Detection")
    table.add_column("Property")
    table.add_column("Value")
    table.add_row("Root path", detection["root_path"])
    table.add_row("Languages", _join_values(detection["languages"]))
    table.add_row("Build systems", _join_values(detection["build_systems"]))
    table.add_row("Package managers", _join_values(detection["package_managers"]))
    table.add_row("Frameworks", _join_values(detection["frameworks"]))
    table.add_row("Likely source roots", _join_values(detection["source_roots"]))
    table.add_row("Likely test roots", _join_values(detection["test_roots"]))
    table.add_row("Important files", _join_values(detection["important_files"]))
    console.print(table)


@repo_app.command("grep")
def repo_grep(
    pattern: Annotated[str, typer.Argument(help="Literal pattern to search for.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    glob_patterns: Annotated[
        list[str] | None,
        typer.Option("--glob", help="File glob to include. Can be repeated."),
    ] = None,
    max_results: Annotated[
        int,
        typer.Option("--max-results", min=1, help="Maximum matches to print."),
    ] = 100,
) -> None:
    """Search repository files."""
    resolved = project_service.resolve_project_root(root)
    result = repository_service.search(
        resolved.root,
        pattern,
        globs=glob_patterns or [],
        max_results=max_results,
    )
    table = Table(title="Repository Search")
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Match")
    for match in result["matches"]:
        table.add_row(match["path"], str(match["line_number"]), match["line"])
    console.print(table)


@repo_app.command("files")
def repo_files(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    ext: Annotated[
        str | None,
        typer.Option("--ext", help="Only include files with this extension."),
    ] = None,
    max_results: Annotated[
        int,
        typer.Option("--max-results", min=1, help="Maximum files to print."),
    ] = 200,
) -> None:
    """List relevant repository files."""
    resolved = project_service.resolve_project_root(root)
    result = repository_service.files(resolved.root, ext=ext, max_results=max_results)
    table = Table(title="Repository Files")
    table.add_column("File")
    for path in result["files"]:
        table.add_row(path)
    console.print(table)


@workset_app.command("suggest")
def workset_suggest(
    query: Annotated[str, typer.Argument(help="Natural-language query describing the task.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    max_results: Annotated[
        int,
        typer.Option("--max-results", min=1, help="Maximum candidates to return."),
    ] = 20,
    include_tests: Annotated[
        bool,
        typer.Option("--include-tests", help="Include test files in candidates."),
    ] = False,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output results as JSON."),
    ] = False,
) -> None:
    """Suggest relevant files for a task using deterministic scoring."""
    resolved = project_service.resolve_project_root(root)
    suggestion = workset_service.suggest(
        resolved.root,
        query,
        max_results=max_results,
        include_tests=include_tests,
    )

    if output_json:
        console.print_json(json.dumps(suggestion))
        return

    if not suggestion["candidates"]:
        console.print("[yellow]No candidates found for query.[/yellow]")
        return

    console.print(f"[bold]Workset Suggestion:[/bold] {suggestion['query']}")
    console.print(f"[dim]Tokens: {', '.join(suggestion['tokens'])}[/dim]")
    console.print()

    table = Table(title=f"Candidates ({len(suggestion['candidates'])})")
    table.add_column("File", no_wrap=False)
    table.add_column("Score", justify="right")
    table.add_column("Category")
    table.add_column("Reasons")

    for candidate in suggestion["candidates"]:
        reason_text = "\n".join(
            f"{reason['label']} (+{reason['score']})" for reason in candidate["reasons"]
        )
        if candidate["content_matches"]:
            snippets = "\n".join(f"  > {s[:80]}" for s in candidate["content_matches"])
            reason_text = reason_text + "\n" + snippets
        table.add_row(
            candidate["path"],
            str(candidate["score"]),
            candidate["file_category"],
            reason_text,
        )

    console.print(table)


@workset_app.command("create")
def workset_create(
    name: Annotated[str, typer.Argument(help="Name for the workset.")],
    query: Annotated[str, typer.Option("--query", "-q", help="Query to populate the workset.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    max_results: Annotated[
        int,
        typer.Option("--max-results", min=1, help="Maximum candidates to store."),
    ] = 20,
    include_tests: Annotated[
        bool,
        typer.Option("--include-tests", help="Include test files in candidates."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite if workset already exists."),
    ] = False,
) -> None:
    """Create a named workset from a deterministic query."""
    resolved = project_service.resolve_project_root(root)
    try:
        data = workset_service.create(
            resolved.root,
            name,
            query,
            max_results=max_results,
            include_tests=include_tests,
            force=force,
        )
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    count = len(data["files"])
    console.print(f"[green]Created workset[/green] [bold]{name}[/bold] with {count} file(s).")


@workset_app.command("list")
def workset_list(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
) -> None:
    """List existing worksets."""
    resolved = project_service.resolve_project_root(root)
    worksets = workset_service.list_all(resolved.root)
    if not worksets:
        console.print("[yellow]No worksets found.[/yellow]")
        return
    table = Table(title="Worksets")
    table.add_column("Name")
    table.add_column("Query")
    table.add_column("Files", justify="right")
    table.add_column("Created")
    table.add_column("Updated")
    for data in worksets:
        if data.get("unreadable"):
            table.add_row(str(data["name"]), "[red]unreadable[/red]", "-", "-", "-")
            continue
        table.add_row(
            str(data["name"]),
            str(data.get("query", "")),
            str(data.get("file_count", 0)),
            str(data.get("created_at", "")),
            str(data.get("updated_at", "")),
        )
    console.print(table)


@workset_app.command("show")
def workset_show(
    name: Annotated[str, typer.Argument(help="Workset name to show.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Show workset metadata and files."""
    resolved = project_service.resolve_project_root(root)
    try:
        data = workset_service.detail(resolved.root, name)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if output_json:
        console.print_json(json.dumps(data))
        return

    console.print(f"[bold]Workset:[/bold] {data['name']}")
    console.print(f"  Query:   {data.get('query', '')}")
    console.print(f"  Root:    {data.get('root', '')}")
    console.print(f"  Created: {data.get('created_at', '')}")
    console.print(f"  Updated: {data.get('updated_at', '')}")
    console.print()

    table = Table(title=f"Files ({len(data.get('files', []))})")
    table.add_column("File")
    table.add_column("Score", justify="right")
    table.add_column("Category")
    table.add_column("Manual")
    table.add_column("Reasons")
    for f in data.get("files", []):
        reasons = "; ".join(
            f"{r['signal']}:{r['detail']} (+{r['points']})" for r in f.get("reasons", [])
        )
        table.add_row(
            f["path"],
            str(f.get("score", 0)),
            f.get("category", ""),
            "yes" if f.get("manual") else "no",
            reasons,
        )
    console.print(table)


@workset_app.command("add")
def workset_add(
    name: Annotated[str, typer.Argument(help="Workset name.")],
    file: Annotated[str, typer.Argument(help="File path to add (relative to root).")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
) -> None:
    """Add a file to an existing workset."""
    resolved = project_service.resolve_project_root(root)
    try:
        workset_service.add(resolved.root, name, file)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Added[/green] {file} to workset [bold]{name}[/bold].")


@workset_app.command("remove")
def workset_remove(
    name: Annotated[str, typer.Argument(help="Workset name.")],
    file: Annotated[str, typer.Argument(help="File path to remove.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
) -> None:
    """Remove a file from an existing workset."""
    resolved = project_service.resolve_project_root(root)
    try:
        workset_service.remove(resolved.root, name, file)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Removed[/green] {file} from workset [bold]{name}[/bold].")


@workset_app.command("refresh")
def workset_refresh(
    name: Annotated[str, typer.Argument(help="Workset name to refresh.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
) -> None:
    """Re-run the saved query and update the workset."""
    resolved = project_service.resolve_project_root(root)
    try:
        data = workset_service.refresh(resolved.root, name)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    count = len(data["files"])
    console.print(f"[green]Refreshed workset[/green] [bold]{name}[/bold] — {count} file(s).")


@workset_app.command("context")
def workset_context(
    name: Annotated[str, typer.Argument(help="Workset name.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    max_lines_per_file: Annotated[
        int,
        typer.Option("--max-lines-per-file", min=1, help="Max excerpt lines per file."),
    ] = 120,
    include_full: Annotated[
        bool,
        typer.Option("--include-full", help="Include full file contents in excerpts."),
    ] = False,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON instead of Markdown."),
    ] = False,
    output_path: Annotated[
        Path | None,
        typer.Option("--output", help="Write bundle to this path instead of default."),
    ] = None,
) -> None:
    """Generate a deterministic context bundle for a workset."""
    resolved = project_service.resolve_project_root(root)

    try:
        result = workset_service.generate_context(
            resolved.root,
            name,
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
            output_path=output_path,
            output_json=output_json,
            save=not output_json or output_path is not None,
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if output_json:
        if output_path:
            console.print(f"[green]Saved JSON context bundle:[/green] {output_path}")
        else:
            console.print_json(result["content"])
        return

    console.print(f"[green]Context bundle saved:[/green] {result['path']}")
    console.print(
        f"  Files: {result['file_count']}  "
        f"Chars: {result['total_chars']:,}  Tokens: {result['total_tokens']:,}"
    )


@workset_app.command("clear")
def workset_clear(
    name: Annotated[str, typer.Argument(help="Workset name to delete.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to inspect (default: auto-detected)."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a workset."""
    resolved = project_service.resolve_project_root(root)
    if not yes:
        confirmed = typer.confirm(f"Delete workset {name!r}?")
        if not confirmed:
            console.print("Aborted.")
            return
    try:
        workset_service.delete(resolved.root, name)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Deleted workset[/green] [bold]{name}[/bold].")


@app.command("init")
def init(
    force: Annotated[
        bool,
        typer.Option("--force", help="Reinitialize even if already initialized."),
    ] = False,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root to initialize (default: auto-detected)."),
    ] = None,
) -> None:
    """Initialize Forge metadata in the current repository."""
    resolved = project_service.resolve_project_root(root)
    try:
        result = project_service.initialize(resolved.root, force=force)
    except FileExistsError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1) from exc

    action = "Reinitialized" if result["already_existed"] and result["forced"] else "Initialized"
    console.print(
        f"[green]{action} Forge project[/green] at " f"{result['paths']['project_forge_dir']}"
    )
    console.print(f"  Repository root: {result['paths']['repo_root']}")
    console.print(f"  Git detected:    {resolved.git_detected}")


@app.command("web")
def web_command(
    host: Annotated[str, typer.Option("--host", help="Host to bind. Defaults to localhost.")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port to bind.")] = 8765,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    reload: Annotated[
        bool, typer.Option("--reload", help="Reload server on code changes.")
    ] = False,
) -> None:
    """Start the local Forge web UI."""
    resolved = project_service.resolve_project_root(root)
    url = f"http://{host}:{port}"
    if host == "0.0.0.0":
        console.print(
            "[yellow]Warning:[/yellow] binding to 0.0.0.0 may expose Forge on your network."
        )
    console.print(f"Forge Web UI running at {url}")
    console.print(f"Repository root: {resolved.root}")

    import uvicorn

    os.environ["FORGE_WEB_ROOT"] = str(resolved.root)
    if reload:
        uvicorn.run("forge.web.app:create_app", host=host, port=port, reload=True, factory=True)
        return
    uvicorn.run(create_app(resolved.root), host=host, port=port)


@project_app.command("root")
def project_root(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override the repository root."),
    ] = None,
) -> None:
    """Print the resolved repository root."""
    resolved = project_service.resolve_project_root(root)
    console.print(str(resolved.root))


@project_app.command("info")
def project_info(
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override the repository root."),
    ] = None,
) -> None:
    """Show project identity and Forge metadata."""
    resolved = project_service.resolve_project_root(root)
    info = project_service.project_info(resolved.root)
    paths = info["paths"]
    meta = info["metadata"]
    initialized = info["initialized"]

    if output_json:
        data: dict[str, object] = {
            "initialized": initialized,
            "git_detected": info["git_detected"],
            "repo_root": info["repo_root"],
            "project_forge_dir": paths["project_forge_dir"],
            "project_metadata_path": str(Path(paths["project_forge_dir"]) / "project.json"),
        }
        if meta:
            data.update(meta)
        console.print_json(json.dumps(data))
        return

    detected = info["detected"]
    project_name = info["project_name"]
    console.print(f"[bold]Project:[/bold] {project_name}")
    console.print(f"  Repository root:       {info['repo_root']}")
    console.print(f"  Git detected:          {info['git_detected']}")
    console.print(f"  Forge project dir:     {paths['project_forge_dir']}")
    console.print(f"  Project metadata path: {Path(paths['project_forge_dir']) / 'project.json'}")
    console.print(f"  Initialized:           {initialized}")
    if meta:
        console.print(f"  Forge version:         {meta.get('forge_version', '-')}")
        console.print(f"  Created:               {meta.get('created_at', '-')}")
        console.print(f"  Updated:               {meta.get('updated_at', '-')}")
    console.print()
    console.print(f"  Languages:        {_join_values(detected.get('languages', []))}")
    console.print(f"  Frameworks:       {_join_values(detected.get('frameworks', []))}")
    console.print(f"  Build systems:    {_join_values(detected.get('build_systems', []))}")
    console.print(f"  Package managers: {_join_values(detected.get('package_managers', []))}")


@project_app.command("paths")
def project_paths(
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override the repository root."),
    ] = None,
) -> None:
    """Show important Forge paths."""
    resolved = project_service.resolve_project_root(root)
    paths = project_service.project_paths(resolved.root)

    if output_json:
        console.print_json(json.dumps(paths))
        return

    table = Table(title="Forge Paths")
    table.add_column("Path")
    table.add_column("Location")
    table.add_row("Global config", paths["global_config_path"])
    table.add_row("Global Forge dir", paths["global_forge_dir"])
    table.add_row("Repository root", paths["repo_root"])
    table.add_row("Project Forge dir", paths["project_forge_dir"])
    table.add_row("Worksets dir", paths["worksets_dir"])
    table.add_row("Summaries dir", paths["summaries_dir"])
    table.add_row("Context dir", paths["context_dir"])
    table.add_row("Architecture dir", paths["architecture_dir"])
    table.add_row("Sessions dir", paths["sessions_dir"])
    table.add_row("Cache dir", paths["cache_dir"])
    table.add_row("Plans dir", paths["plans_dir"])
    table.add_row("Memory dir", paths["memory_dir"])
    table.add_row("Patches dir", paths["patches_dir"])
    table.add_row("Verifications dir", paths["verifications_dir"])
    console.print(table)


def _status(check: CheckResult) -> str:
    if check.ok and check.required:
        return "[green]ok[/green]"
    if check.ok:
        return "[cyan]optional[/cyan]"
    return "[red]failed[/red]"


def _join_values(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def _first_command(steps: object, kind: str) -> str:
    if not isinstance(steps, list):
        return "none"
    for step in steps:
        if isinstance(step, dict) and step.get("kind") == kind:
            return str(step.get("command") or "none")
    return "none"


def _render_detection(result: dict[str, object]) -> None:
    strategy = result["strategy"]
    if not isinstance(strategy, dict):
        console.print("[red]Error:[/red] malformed verification strategy.")
        return
    console.print("[bold]Verification Strategy[/bold]")
    console.print(f"Ecosystem: {_human_ecosystem(str(strategy['ecosystem']))}")
    if strategy["ecosystem"] == "unknown":
        console.print("No deterministic verification strategy detected.")
        return

    console.print(f"Build: {_first_command(strategy['steps'], 'build')}")
    console.print(f"Tests: {_first_command(strategy['steps'], 'tests')}")
    console.print(f"Formatter: {_first_command(strategy['steps'], 'formatter')}")
    console.print(f"Linter: {_first_command(strategy['steps'], 'linter')}")
    console.print(f"Package Manager: {strategy['package_manager'] or 'none'}")
    console.print(f"Confidence: {strategy['confidence']}")


def _render_verification_report(report: dict[str, object]) -> None:
    repository = report.get("repository", {})
    summary = report.get("summary", {})
    artifact = report.get("artifact", {})
    steps = report.get("steps", [])
    by_kind = summary.get("by_kind", {}) if isinstance(summary, dict) else {}
    repo_name = repository.get("name", "unknown") if isinstance(repository, dict) else "unknown"
    overall = str(report.get("overall_status", "fail")).upper()

    console.print("[bold]Verification[/bold]")
    console.print(f"Repository: {repo_name}")
    console.print(f"Overall: {_status_label(overall)}")
    console.print()

    table = Table(show_header=False, box=None)
    table.add_column("Gate")
    table.add_column("Status")
    for label, kind in (
        ("Formatter", "formatter"),
        ("Linter", "linter"),
        ("Build", "build"),
        ("Tests", "tests"),
    ):
        table.add_row(label, _status_label(str(by_kind.get(kind, "skipped")).upper()))
    console.print(table)
    console.print(f"Duration: {_format_duration(float(report.get('duration') or 0))}")
    if isinstance(artifact, dict) and artifact.get("path"):
        console.print(f"Artifact: {artifact['path']}")
    if isinstance(steps, list):
        failed = [
            step
            for step in steps
            if isinstance(step, dict) and step.get("status") in {"fail", "error"}
        ]
        for step in failed:
            detail = step.get("exception") or step.get("stderr") or step.get("stdout") or ""
            console.print(
                f"[red]{step.get('name', 'step')} failed:[/red] {str(detail).strip()[:300]}"
            )


def _status_label(status: str) -> str:
    if status == "PASS":
        return "[green]PASS[/green]"
    if status == "SKIPPED":
        return "[yellow]SKIPPED[/yellow]"
    if status == "ERROR":
        return "[red]ERROR[/red]"
    return "[red]FAIL[/red]"


def _format_duration(seconds: float) -> str:
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes:02d}:{remainder:02d}"


def _human_ecosystem(ecosystem: str) -> str:
    labels = {
        "python": "Python",
        "node": "Node",
        "maven": "Java Maven",
        "gradle": "Java Gradle",
        "go": "Go",
        "rust": "Rust",
        "dotnet": ".NET",
        "unknown": "unknown",
    }
    return labels.get(ecosystem, ecosystem)


@app.command("plan")
def plan_command(
    task: Annotated[str, typer.Argument(help="Implementation task to plan.")],
    workset: Annotated[str, typer.Option("--workset", "-w", help="Persisted workset name.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override for this request."),
    ] = None,
    timeout_seconds: Annotated[
        int | None,
        typer.Option("--timeout", help="Request timeout in seconds."),
    ] = None,
    max_lines_per_file: Annotated[
        int,
        typer.Option("--max-lines-per-file", min=1, help="Max excerpt lines per file."),
    ] = 120,
    include_full: Annotated[
        bool,
        typer.Option("--include-full", help="Include full file contents in context."),
    ] = False,
    save: Annotated[
        bool,
        typer.Option("--save", help="Save the plan to .forge/plans/."),
    ] = False,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Generate an implementation plan using a persisted workset."""
    resolved = project_service.resolve_project_root(root)

    try:
        result = planning_service.PlanningService(_model_manager()).generate_plan(
            resolved.root,
            task,
            workset,
            model=model,
            save=save,
            timeout_seconds=timeout_seconds,
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
        )
    except PlannerError as exc:
        console.print(f"[red]Planning error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if save:
        console.print(f"[green]Plan saved:[/green] {result.saved_path}")

    if output_json:
        console.print_json(render_plan_json(result))
        return

    console.print(render_plan_text(result))


@app.command("implement")
def implement_command(
    task: Annotated[str, typer.Argument(help="Implementation task to generate a patch for.")],
    workset: Annotated[str, typer.Option("--workset", "-w", help="Persisted workset name.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override for this request."),
    ] = None,
    timeout_seconds: Annotated[
        int | None,
        typer.Option("--timeout", help="Request timeout in seconds."),
    ] = None,
    max_lines_per_file: Annotated[
        int,
        typer.Option("--max-lines-per-file", min=1, help="Max excerpt lines per file."),
    ] = 120,
    include_full: Annotated[
        bool,
        typer.Option("--include-full", help="Include full file contents in context."),
    ] = False,
    output_path: Annotated[
        Path | None,
        typer.Option("--output", help="Write a valid patch to this explicit path."),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Generate a human-reviewable patch without applying it."""
    resolved = project_service.resolve_project_root(root)

    try:
        result = implementation_service.ImplementationService(_model_manager()).implement(
            resolved.root,
            task,
            workset,
            model=model,
            timeout_seconds=timeout_seconds,
            max_lines_per_file=max_lines_per_file,
            include_full=include_full,
            output_path=output_path,
        )
    except ExecutionServiceError as exc:
        console.print(f"[red]Execution error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except implementation_service.ImplementationServiceError as exc:
        console.print(f"[red]Implementation error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except ModelNotFoundError as exc:
        _handle_model_not_found(exc)
    except ModelProviderError as exc:
        _handle_provider_error(exc)

    data = result.to_dict()
    if output_json:
        console.print_json(json.dumps(data))
        if not data["valid"]:
            raise typer.Exit(code=1)
        return

    console.print(f"Model: {data['model']}")
    console.print(f"Status: {data['status']}")
    if data["patch_path"]:
        console.print(f"Patch path: {data['patch_path']}")
    if data["raw_response_path"]:
        console.print(f"Invalid artifact path: {data['raw_response_path']}")
    console.print(f"Valid: {'yes' if data['valid'] else 'no'}")
    console.print(f"Affected files: {_join_values(data['affected_files'])}")
    if data["validation_errors"]:
        console.print("Validation errors:")
        for error in data["validation_errors"]:
            console.print(f"  - {error}")
    if data["next_command"]:
        console.print(f"Next command: {data['next_command']}")

    if not data["valid"]:
        console.print("No patch was accepted.")
        raise typer.Exit(code=1)


@memory_app.command("list")
def memory_list(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """List all engineering memory items."""
    resolved = project_service.resolve_project_root(root)
    items = memory_service.list_timeline(resolved.root)
    if output_json:
        console.print_json(json.dumps(items))
        return
    if not items:
        console.print("[yellow]No memory items found.[/yellow]")
        return
    table = Table(title="Engineering Memory")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Workset")
    table.add_column("Created")
    for item in items:
        table.add_row(
            item["id"],
            item["type"],
            item["title"],
            item["workset"],
            item["created_at"],
        )
    console.print(table)


@memory_app.command("show")
def memory_show(
    item_id: Annotated[str, typer.Argument(help="Memory item ID.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show a single memory item by ID."""
    resolved = project_service.resolve_project_root(root)
    try:
        item = memory_service.get(resolved.root, item_id)
    except MemoryStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if output_json:
        console.print_json(json.dumps(item))
        return
    console.print(f"[bold]{item['title']}[/bold]")
    console.print(f"  ID:       {item['id']}")
    console.print(f"  Type:     {item['type']}")
    console.print(f"  Workset:  {item['workset'] or '—'}")
    console.print(f"  Created:  {item['created_at']}")
    if item["tags"]:
        console.print(f"  Tags:     {', '.join(item['tags'])}")
    if item["summary"]:
        console.print(f"  Summary:  {item['summary']}")
    if item["related_files"]:
        console.print(f"  Files:    {', '.join(item['related_files'][:5])}")
    if item["related_plans"]:
        console.print(f"  Related plans: {', '.join(item['related_plans'])}")


@memory_app.command("search")
def memory_search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    max_results: Annotated[int, typer.Option("--max-results", help="Maximum results.")] = 10,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Search engineering memory with a query string."""
    resolved = project_service.resolve_project_root(root)
    data = memory_service.search(resolved.root, query, max_results=max_results)
    results = data["results"]
    if output_json:
        console.print_json(json.dumps(results))
        return
    if not results:
        console.print("[yellow]No matching memory items.[/yellow]")
        return
    table = Table(title=f"Memory Search: {query!r}")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Score", justify="right")
    table.add_column("Why")
    for result in results:
        item = result["item"]
        why = "; ".join(
            f"{reason['signal']}:{reason['detail']}" for reason in result["reasons"][:2]
        )
        table.add_row(item["id"], item["type"], item["title"], str(result["score"]), why)
    console.print(table)


@memory_app.command("related")
def memory_related(
    query: Annotated[str, typer.Argument(help="Query describing the current context.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    workset: Annotated[str, typer.Option("--workset", help="Workset name for similarity.")] = "",
    max_results: Annotated[int, typer.Option("--max-results", help="Maximum results.")] = 5,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Find memory items similar to the given query and context."""
    resolved = project_service.resolve_project_root(root)
    data = memory_service.related(
        resolved.root,
        query,
        workset=workset,
        max_results=max_results,
    )
    results = data["results"]
    if output_json:
        console.print_json(json.dumps(results))
        return
    if not results:
        console.print("[yellow]No similar memory items found.[/yellow]")
        return
    table = Table(title=f"Related Memory: {query!r}")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Score", justify="right")
    table.add_column("Why")
    for result in results:
        item = result["item"]
        why = "; ".join(
            f"{reason['signal']}:{reason['detail']}" for reason in result["reasons"][:2]
        )
        table.add_row(item["id"], item["type"], item["title"], str(result["score"]), why)
    console.print(table)


@memory_app.command("rebuild")
def memory_rebuild(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
) -> None:
    """Rebuild the memory index from stored item files."""
    resolved = project_service.resolve_project_root(root)
    count = memory_service.rebuild(resolved.root)["count"]
    console.print(f"[green]Memory index rebuilt.[/green] {count} item(s) indexed.")


@patch_app.command("list")
def patch_list(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """List saved patches under .forge/patches."""
    resolved = project_service.resolve_project_root(root)
    patches = patch_service.list_all(resolved.root)

    if output_json:
        console.print_json(json.dumps(patches))
        return

    if not patches:
        console.print("[yellow]No saved patches found in .forge/patches/.[/yellow]")
        return

    table = Table(title="Saved Patches")
    table.add_column("Name")
    table.add_column("Valid")
    table.add_column("Affected files")
    table.add_column("Size", justify="right")
    table.add_column("Path")
    for patch in patches:
        table.add_row(
            patch["name"],
            "[green]yes[/green]" if patch["valid"] else "[red]no[/red]",
            _join_values(patch["affected_files"]),
            str(patch["size_bytes"]),
            str(patch["path"]),
        )
    console.print(table)


@patch_app.command("show")
def patch_show(
    patch_name: Annotated[str, typer.Argument(help="Saved patch name or direct patch path.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Print saved patch content."""
    resolved = project_service.resolve_project_root(root)
    try:
        patch = patch_service.show(resolved.root, patch_name)
    except PatchError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if output_json:
        console.print_json(json.dumps(patch))
        return

    console.print(patch["content"], markup=False, end="")


@patch_app.command("validate")
def patch_validate(
    patch_path_or_name: Annotated[
        str,
        typer.Argument(help="Saved patch name or direct patch path to validate."),
    ],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Validate whether a file looks like a unified diff."""
    resolved = project_service.resolve_project_root(root)
    try:
        patch = patch_service.validate(resolved.root, patch_path_or_name)
    except PatchError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if output_json:
        console.print_json(json.dumps(patch))
    else:
        status = "[green]valid[/green]" if patch["valid"] else "[red]invalid[/red]"
        console.print(f"Patch {patch['name']}: {status}")
        if patch["affected_files"]:
            console.print(f"Affected files: {', '.join(patch['affected_files'])}")
        if patch["validation_errors"]:
            console.print("Validation errors:")
            for error in patch["validation_errors"]:
                console.print(f"  - {error}")

    raise typer.Exit(code=0 if patch["valid"] else 1)


@git_app.command("status")
def git_status(
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show Git repository status."""
    result = git_service.status()

    if output_json:
        console.print_json(json.dumps(result))
        raise typer.Exit(code=0 if result["is_git_repository"] else 1)

    if not result["is_git_repository"]:
        console.print("[red]Not a git repository.[/red]")
        raise typer.Exit(code=1)

    console.print("Repository: git")
    console.print(f"Branch: {result['branch']}")
    console.print(f"Commit: {result['commit']}")
    console.print(f"Clean: {'true' if result['clean'] else 'false'}")

    if result["modified_files"]:
        console.print("\nModified:")
        for f in result["modified_files"]:
            console.print(f"  - {f}")

    if result["staged_files"]:
        console.print("\nStaged:")
        for f in result["staged_files"]:
            console.print(f"  - {f}")

    if result["deleted_files"]:
        console.print("\nDeleted:")
        for f in result["deleted_files"]:
            console.print(f"  - {f}")

    if result["untracked_files"]:
        console.print("\nUntracked:")
        for f in result["untracked_files"]:
            console.print(f"  - {f}")


@git_app.command("branch")
def git_branch(
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show current Git branch."""
    result = git_service.branch()

    if output_json:
        console.print_json(json.dumps(result))
        raise typer.Exit(code=0 if result["is_git_repository"] else 1)

    if not result["is_git_repository"]:
        console.print("[red]Not a git repository.[/red]")
        raise typer.Exit(code=1)

    console.print(f"Current branch: {result['branch']}")


@policy_app.command("show")
def policy_show(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show the active engineering policy."""
    resolved = project_service.resolve_project_root(root)
    policy = policy_service.show(resolved.root)

    if output_json:
        console.print_json(json.dumps(policy))
        raise typer.Exit(code=0)

    for section, fields in policy.items():
        console.print(f"\n[bold]{section}:[/bold]")
        for key, value in fields.items():
            console.print(f"  {key}: {value}")

    raise typer.Exit(code=0)


@policy_app.command("check")
def policy_check(
    patch_path_or_name: Annotated[
        str,
        typer.Argument(help="Saved patch name or path to evaluate."),
    ],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    verification: Annotated[
        str | None,
        typer.Option("--verification", help="Path or name of verification report."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Evaluate a patch against the active engineering policy."""
    resolved = project_service.resolve_project_root(root)
    try:
        result = policy_service.check(resolved.root, patch_path_or_name, verification)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Policy check error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if output_json:
        console.print_json(json.dumps(result))
        evaluation = result["evaluation"]
        raise typer.Exit(code=0 if evaluation["status"] == "pass" else 1)

    evaluation = result["evaluation"]
    status = evaluation["status"]
    color = "green" if status == "pass" else ("yellow" if status == "warn" else "red")
    console.print(f"\nPolicy evaluation: [{color}]{status.upper()}[/{color}]")
    console.print(f"Patch: {result['patch']}")

    for check in evaluation["checks"]:
        st = check["status"]
        icon = "✓" if st == "pass" else ("⚠" if st == "warn" else ("–" if st == "skip" else "✗"))
        sev_color = "green" if st == "pass" else ("yellow" if st in ("warn", "skip") else "red")
        console.print(f"  [{sev_color}]{icon}[/{sev_color}] {check['name']}: {check['message']}")

    raise typer.Exit(code=0 if status == "pass" else 1)


@app.command("apply")
def apply_command(
    patch_path_or_name: Annotated[
        str,
        typer.Argument(help="Saved patch name or path to apply."),
    ],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    verification: Annotated[
        str | None,
        typer.Option("--verification", help="Path or name of verification report."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Override policy failures if policy allows force."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt (does not bypass policy)."),
    ] = False,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Apply a patch after policy evaluation and confirmation."""
    resolved = project_service.resolve_project_root(root)

    # Validate patch existence and structure before prompting
    try:
        pre_check = patch_service.validate(resolved.root, patch_path_or_name)
    except PatchError as exc:
        if output_json:
            console.print_json(json.dumps({"error": str(exc)}))
        else:
            console.print(f"[red]Patch not found:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not pre_check.get("valid"):
        errors = "; ".join(pre_check.get("validation_errors", []))
        suggestions = pre_check.get("suggestions", [])
        if output_json:
            payload = {"error": f"Patch is invalid: {errors}", "patch": pre_check}
            console.print_json(json.dumps(payload))
        else:
            console.print("[red]Patch validation failed.[/red]\n")
            structural = pre_check.get("structural_valid", True)
            apply_ok = pre_check.get("apply_check_valid")
            console.print(f"  Structural diff:  {'pass' if structural else 'fail'}")
            if apply_ok is not None:
                console.print(f"  Git apply check:  {'pass' if apply_ok else 'fail'}")
            if errors:
                console.print(f"\nReason:\n  {errors}")
            if suggestions:
                console.print("\nSuggested next steps:")
                for s in suggestions:
                    console.print(f"  - {s}")
        raise typer.Exit(code=1)

    if not yes:
        confirm = typer.confirm(f"Apply patch '{patch_path_or_name}' to the working tree?")
        if not confirm:
            console.print("Apply cancelled.")
            raise typer.Exit(code=0)

    try:
        record = apply_service.apply(
            resolved.root,
            patch_path_or_name,
            verification_path=verification,
            force=force,
        )
    except PolicyBlockedError as exc:
        if output_json:
            console.print_json(json.dumps({"error": str(exc), "evaluation": exc.evaluation}))
        else:
            console.print(f"[red]Policy blocked apply:[/red] {exc}")
            for check in exc.evaluation.get("checks", []):
                if check["status"] == "fail":
                    console.print(f"  ✗ {check['name']}: {check['message']}")
            console.print("Use [bold]--force[/bold] to override if policy permits.")
        raise typer.Exit(code=1) from exc
    except ApplyError as exc:
        if output_json:
            console.print_json(json.dumps({"error": str(exc)}))
        else:
            console.print(f"[red]Apply failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        if output_json:
            console.print_json(json.dumps({"error": str(exc)}))
        else:
            console.print(f"[red]Infrastructure error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if output_json:
        console.print_json(json.dumps(record))
    else:
        console.print(f"[green]Patch applied:[/green] {record['patch']}")
        console.print(f"Policy status: {record['policy_status']}")
        if record.get("affected_files"):
            console.print(f"Affected files: {', '.join(record['affected_files'])}")
        if record.get("forced"):
            console.print("[yellow]Note: policy overridden with --force[/yellow]")

    raise typer.Exit(code=0)


def _run_workflow(
    template: str,
    task: str,
    root: Path | None,
    model: str | None,
    output_json: bool,
) -> None:
    """Shared workflow execution logic used by feature / bugfix / refactor commands."""
    from forge.services.workflow_service import WorkflowServiceError

    resolved = project_service.resolve_project_root(root)
    if not output_json:
        console.print(f"[bold]forge workflow {template}[/bold] — {task}")
        console.print("")

    try:
        run = workflow_service.run_workflow(resolved.root, template, task, model=model)
    except WorkflowServiceError as exc:
        if output_json:
            console.print_json(json.dumps({"error": str(exc), "status": "failed"}))
        else:
            console.print(f"[red]Workflow error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if output_json:
        console.print_json(json.dumps(run))
        raise typer.Exit(code=0 if run.get("status") == "completed" else 1)

    _render_workflow_run(run)
    raise typer.Exit(code=0 if run.get("status") == "completed" else 1)


def _render_workflow_run(run: dict) -> None:
    for stage in run.get("stages", []):
        name = stage["name"]
        status = stage["status"]
        if status == "completed":
            console.print(f"  [green]✓[/green] {name}")
        elif status == "failed":
            console.print(f"  [red]✗[/red] {name}: {stage.get('error', '')}")
        elif status == "skipped":
            console.print(f"  [dim]–[/dim] {name}")
        else:
            console.print(f"  [yellow]?[/yellow] {name}")

    console.print("")
    overall = run.get("status", "unknown")
    if overall == "completed":
        console.print("[green]Workflow complete.[/green]")
        patch_path = run.get("patch_path")
        if patch_path:
            import os

            patch_name = os.path.basename(patch_path)
            console.print(f"\nPatch ready:\n\n  forge apply {patch_name}")
    else:
        console.print(f"[red]Workflow failed.[/red] Status: {overall}")
        for stage in run.get("stages", []):
            if stage["status"] == "failed":
                console.print(f"  Failed stage: {stage['name']}")
                if stage.get("error"):
                    console.print(f"  Error: {stage['error']}")


@workflow_app.command("feature")
def workflow_feature(
    task: Annotated[str, typer.Argument(help="Feature description.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Run a Feature engineering workflow."""
    _run_workflow("feature", task, root, model, output_json)


@workflow_app.command("bugfix")
def workflow_bugfix(
    task: Annotated[str, typer.Argument(help="Bug description.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Run a Bug Fix engineering workflow."""
    _run_workflow("bugfix", task, root, model, output_json)


@workflow_app.command("refactor")
def workflow_refactor(
    task: Annotated[str, typer.Argument(help="Refactor description.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Run a Refactor engineering workflow."""
    _run_workflow("refactor", task, root, model, output_json)


@workflow_app.command("run")
def workflow_run(
    template: Annotated[str, typer.Argument(help="Workflow template name.")],
    task: Annotated[str, typer.Argument(help="Engineering task description.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model to use.")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Run an engineering workflow by template name."""
    _run_workflow(template, task, root, model, output_json)


@workflow_app.command("templates")
def workflow_templates(
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """List available workflow templates."""
    templates = workflow_service.list_templates()
    if output_json:
        console.print_json(json.dumps(templates))
        return
    table = Table(title="Workflow Templates")
    table.add_column("Template")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Stages")
    for tmpl in templates:
        table.add_row(
            tmpl["template"],
            tmpl["name"],
            tmpl["description"],
            ", ".join(tmpl["stages"]),
        )
    console.print(table)


@workflow_app.command("list")
def workflow_list(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    template: Annotated[
        str | None,
        typer.Option("--template", help="Filter by template name."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """List workflow runs for this repository."""
    resolved = project_service.resolve_project_root(root)
    runs = workflow_service.list_runs(resolved.root, template=template)
    if output_json:
        console.print_json(json.dumps(runs))
        return
    if not runs:
        console.print("[yellow]No workflow runs found.[/yellow]")
        return
    table = Table(title="Workflow Runs")
    table.add_column("ID")
    table.add_column("Template")
    table.add_column("Status")
    table.add_column("Task")
    table.add_column("Duration", justify="right")
    for run in runs:
        dur = run.get("duration_seconds")
        dur_str = f"{dur:.1f}s" if dur is not None else "—"
        table.add_row(
            run.get("id", "")[:12],
            run.get("template", ""),
            run.get("status", ""),
            (run.get("task") or "")[:60],
            dur_str,
        )
    console.print(table)


@workflow_app.command("show")
def workflow_show(
    run_id: Annotated[str, typer.Argument(help="Workflow run ID.")],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root (default: auto-detected)."),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show details of a workflow run."""
    resolved = project_service.resolve_project_root(root)
    run = workflow_service.show_run(resolved.root, run_id)
    if run is None:
        console.print(f"[red]Workflow run {run_id!r} not found.[/red]")
        raise typer.Exit(code=1)
    if output_json:
        console.print_json(json.dumps(run))
        return
    console.print(f"[bold]Run:[/bold] {run['id']}")
    console.print(f"[bold]Template:[/bold] {run['template']}")
    console.print(f"[bold]Status:[/bold] {run['status']}")
    console.print(f"[bold]Task:[/bold] {run['task']}")
    console.print(f"[bold]Repository:[/bold] {run['repository']}")
    console.print(f"[bold]Started:[/bold] {run.get('started_at', '—')}")
    console.print(f"[bold]Completed:[/bold] {run.get('completed_at', '—')}")
    if run.get("patch_path"):
        console.print(f"[bold]Patch:[/bold] {run['patch_path']}")
    console.print("")
    _render_workflow_run(run)


def main() -> None:
    """Run the Forge CLI."""
    app()
