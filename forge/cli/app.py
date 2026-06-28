"""Forge command-line interface."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from forge.commands.doctor import CheckResult, run_doctor
from forge.config.manager import ConfigManager
from forge.models.errors import ModelProviderError
from forge.models.manager import ModelManager, ModelNotFoundError
from forge.utils.logging import configure_logging
from forge.version import __version__

app = typer.Typer(
    name="forge",
    help="Local-first AI software engineering workbench.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Manage Forge configuration.")
models_app = typer.Typer(help="Manage configured provider models.")
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")
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
) -> None:
    """Ask the configured model a question."""
    try:
        response = _model_manager().ask(prompt=prompt, model=model)
    except ModelNotFoundError as exc:
        _handle_model_not_found(exc)
    except ModelProviderError as exc:
        _handle_provider_error(exc)
    console.print(response.content)


def _status(check: CheckResult) -> str:
    if check.ok and check.required:
        return "[green]ok[/green]"
    if check.ok:
        return "[cyan]optional[/cyan]"
    return "[red]failed[/red]"


def main() -> None:
    """Run the Forge CLI."""
    app()
