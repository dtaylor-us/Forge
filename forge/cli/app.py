"""Forge command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from forge.commands.doctor import CheckResult, run_doctor
from forge.commands.project_context import build_project_explanation_prompt
from forge.config.manager import ConfigManager
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelManager, ModelNotFoundError
from forge.repository import (
    detect_repository,
    generate_tree,
    list_relevant_files,
    search_repository,
)
from forge.utils.logging import configure_logging
from forge.version import __version__
from forge.worksets import suggest_candidates
from forge.worksets.manager import (
    add_file,
    clear_workset,
    create_workset,
    get_workset,
    list_worksets,
    refresh_workset,
    remove_file,
)
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
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")
app.add_typer(repo_app, name="repo")
app.add_typer(workset_app, name="workset")
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
) -> None:
    """Explain the current project using explicit local project context."""
    prompt = build_project_explanation_prompt(Path.cwd())
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
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
    max_depth: Annotated[
        int,
        typer.Option("--max-depth", min=0, help="Maximum directory depth to print."),
    ] = 3,
) -> None:
    """Print a compact repository tree."""
    for line in generate_tree(root, max_depth=max_depth):
        console.print(line)


@repo_app.command("detect")
def repo_detect(
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Detect repository characteristics."""
    detection = detect_repository(root)
    table = Table(title="Repository Detection")
    table.add_column("Property")
    table.add_column("Value")
    table.add_row("Root path", str(detection.root_path))
    table.add_row("Languages", _join_values(detection.languages))
    table.add_row("Build systems", _join_values(detection.build_systems))
    table.add_row("Package managers", _join_values(detection.package_managers))
    table.add_row("Frameworks", _join_values(detection.frameworks))
    source_roots = [str(path) for path in detection.source_roots]
    test_roots = [str(path) for path in detection.test_roots]
    important_files = [str(path) for path in detection.important_files]
    table.add_row("Likely source roots", _join_values(source_roots))
    table.add_row("Likely test roots", _join_values(test_roots))
    table.add_row("Important files", _join_values(important_files))
    console.print(table)


@repo_app.command("grep")
def repo_grep(
    pattern: Annotated[str, typer.Argument(help="Literal pattern to search for.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
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
    matches = search_repository(
        pattern,
        root,
        globs=glob_patterns or [],
        max_results=max_results,
    )
    table = Table(title="Repository Search")
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Match")
    for match in matches:
        table.add_row(str(match.path), str(match.line_number), match.line)
    console.print(table)


@repo_app.command("files")
def repo_files(
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
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
    table = Table(title="Repository Files")
    table.add_column("File")
    for path in list_relevant_files(root, ext=ext, max_results=max_results):
        table.add_row(str(path))
    console.print(table)


@workset_app.command("suggest")
def workset_suggest(
    query: Annotated[str, typer.Argument(help="Natural-language query describing the task.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
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
    suggestion = suggest_candidates(
        query,
        root,
        max_results=max_results,
        include_tests=include_tests,
    )

    if output_json:
        data = {
            "query": suggestion.query,
            "tokens": suggestion.tokens,
            "root": str(suggestion.root),
            "candidates": [
                {
                    "path": str(c.path),
                    "score": c.score,
                    "file_category": c.file_category,
                    "reasons": [{"label": r.label, "score": r.score} for r in c.reasons],
                    "content_matches": c.content_matches,
                }
                for c in suggestion.candidates
            ],
        }
        console.print_json(json.dumps(data))
        return

    if not suggestion.candidates:
        console.print("[yellow]No candidates found for query.[/yellow]")
        return

    console.print(f"[bold]Workset Suggestion:[/bold] {suggestion.query}")
    console.print(f"[dim]Tokens: {', '.join(suggestion.tokens)}[/dim]")
    console.print()

    table = Table(title=f"Candidates ({len(suggestion.candidates)})")
    table.add_column("File", no_wrap=False)
    table.add_column("Score", justify="right")
    table.add_column("Category")
    table.add_column("Reasons")

    for candidate in suggestion.candidates:
        reason_text = "\n".join(f"{r.label} (+{r.score})" for r in candidate.reasons)
        if candidate.content_matches:
            snippets = "\n".join(f"  > {s[:80]}" for s in candidate.content_matches)
            reason_text = reason_text + "\n" + snippets
        table.add_row(
            str(candidate.path),
            str(candidate.score),
            candidate.file_category,
            reason_text,
        )

    console.print(table)


@workset_app.command("create")
def workset_create(
    name: Annotated[str, typer.Argument(help="Name for the workset.")],
    query: Annotated[str, typer.Option("--query", "-q", help="Query to populate the workset.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
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
    try:
        data = create_workset(
            root,
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
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """List existing worksets."""
    names = list_worksets(root)
    if not names:
        console.print("[yellow]No worksets found.[/yellow]")
        return
    table = Table(title="Worksets")
    table.add_column("Name")
    table.add_column("Query")
    table.add_column("Files", justify="right")
    table.add_column("Created")
    table.add_column("Updated")
    for wname in names:
        try:
            data = get_workset(root, wname)
            table.add_row(
                data["name"],
                data.get("query", ""),
                str(len(data.get("files", []))),
                data.get("created_at", ""),
                data.get("updated_at", ""),
            )
        except WorksetStoreError:
            table.add_row(wname, "[red]unreadable[/red]", "-", "-", "-")
    console.print(table)


@workset_app.command("show")
def workset_show(
    name: Annotated[str, typer.Argument(help="Workset name to show.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Show workset metadata and files."""
    try:
        data = get_workset(root, name)
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
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Add a file to an existing workset."""
    try:
        add_file(root, name, file)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Added[/green] {file} to workset [bold]{name}[/bold].")


@workset_app.command("remove")
def workset_remove(
    name: Annotated[str, typer.Argument(help="Workset name.")],
    file: Annotated[str, typer.Argument(help="File path to remove.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Remove a file from an existing workset."""
    try:
        remove_file(root, name, file)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Removed[/green] {file} from workset [bold]{name}[/bold].")


@workset_app.command("refresh")
def workset_refresh(
    name: Annotated[str, typer.Argument(help="Workset name to refresh.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Re-run the saved query and update the workset."""
    try:
        data = refresh_workset(root, name)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    count = len(data["files"])
    console.print(f"[green]Refreshed workset[/green] [bold]{name}[/bold] — {count} file(s).")


@workset_app.command("clear")
def workset_clear(
    name: Annotated[str, typer.Argument(help="Workset name to delete.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Repository root to inspect."),
    ] = Path("."),
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a workset."""
    if not yes:
        confirmed = typer.confirm(f"Delete workset {name!r}?")
        if not confirmed:
            console.print("Aborted.")
            return
    try:
        clear_workset(root, name)
    except WorksetStoreError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Deleted workset[/green] [bold]{name}[/bold].")


def _status(check: CheckResult) -> str:
    if check.ok and check.required:
        return "[green]ok[/green]"
    if check.ok:
        return "[cyan]optional[/cyan]"
    return "[red]failed[/red]"


def _join_values(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def main() -> None:
    """Run the Forge CLI."""
    app()
