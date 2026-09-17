from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ribhus import __version__
from ribhus.agent.loop import Agent
from ribhus.config import Settings, get_settings
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.policy.audit import AuditLog
from ribhus.policy.engine import PolicyEngine
from ribhus.policy.levels import RiskLevel
from ribhus.skills.installer import create_skill, install_skill, remove_skill
from ribhus.skills.registry import SkillRegistry
from ribhus.tools.browser import BrowserSession
from ribhus.tools.registry import default_registry

app = typer.Typer(
    name="ribhus",
    help="Ribhus — open-source AI agent for India.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)
skill_app = typer.Typer(help="Manage Ribhus skills.")
app.add_typer(skill_app, name="skill")
console = Console()


def _cli_approver(name: str, risk: RiskLevel, arguments: dict[str, Any]) -> bool:
    console.print()
    console.print(
        Panel(
            f"[bold]{name}[/bold]  risk=[yellow]{risk.value}[/yellow]\n"
            f"{json.dumps(arguments, indent=2, default=str)}",
            title="Approval required",
            border_style="yellow",
        )
    )
    try:
        answer = console.input("[bold yellow]Approve? [y/N]:[/bold yellow] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[red]Denied[/red]")
        return False
    return answer in {"y", "yes"}


def _build_runtime(settings: Settings | None = None, *, prompt: str = ""):
    settings = settings or get_settings()
    model = OpenAICompatibleModel(settings)
    policy = PolicyEngine(
        auto_approve=settings.auto_approve,
        approve_at_or_above=settings.approve_at_level,
        approver=None if settings.auto_approve else _cli_approver,
    )
    audit = AuditLog(settings.ribhus_dir / "audit.jsonl")
    browser = BrowserSession(
        user_data_dir=settings.ribhus_dir / "browser_profile",
        headed=settings.browser_headed,
        allowlist=settings.browser_allowlist_hosts,
        rate_limit_per_minute=settings.browser_rate_limit,
    )
    tools = default_registry(
        settings.workspace,
        policy=policy,
        audit=audit,
        browser_session=browser,
        screenshot_dir=settings.ribhus_dir / "screenshots",
    )
    skills = SkillRegistry.load_default(settings.workspace)
    matched = skills.match(prompt) if prompt else []
    agent = Agent(
        model=model,
        tools=tools,
        max_iterations=settings.max_iterations,
        on_event=_on_event,
        skill_prompt_addon=skills.prompt_addon(prompt) if prompt else "",
    )
    return agent, browser, matched


async def _on_event(event: str, data: dict) -> None:
    if event == "thinking":
        console.print(f"[dim]thinking (step {data.get('iteration')})…[/dim]")
    elif event == "skill":
        console.print("[magenta]✦ skill active[/magenta]")
    elif event == "tool_start":
        console.print(f"[cyan]→ {data.get('name')}[/cyan]")
    elif event == "tool_end":
        console.print(f"[green]✓ {data.get('name')}[/green]")


async def _run_once(prompt: str) -> str:
    agent, browser, matched = _build_runtime(prompt=prompt)
    if matched:
        names = ", ".join(s.name for s in matched)
        console.print(f"[magenta]✦ using skill: {names}[/magenta]")
    try:
        state = await agent.run(prompt)
        return state.final_text or ""
    finally:
        await browser.close()


def _print_answer(text: str) -> None:
    console.print()
    console.print(Panel(Markdown(text), title="Ribhus", border_style="blue"))


def _run_prompt(prompt: str) -> None:
    try:
        answer = asyncio.run(_run_once(prompt))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_answer(answer)


def _interactive() -> None:
    console.print(
        Panel(
            f"[bold]Ribhus[/bold] {__version__}\n"
            "Type a task, or [cyan]/exit[/cyan] / [cyan]/quit[/cyan] to leave.\n"
            "Skills: [cyan]ribhus skill list[/cyan]",
            border_style="blue",
        )
    )
    while True:
        try:
            line = console.input("[bold blue]>[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye.")
            break
        if not line:
            continue
        if line in {"/exit", "/quit", "exit", "quit"}:
            console.print("Bye.")
            break
        try:
            answer = asyncio.run(_run_once(line))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            continue
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error: {exc}[/red]")
            continue
        _print_answer(answer)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Run with no args for interactive mode. Pass a prompt for one-shot."""
    if ctx.invoked_subcommand is not None:
        return


@app.command("tools")
def list_tools() -> None:
    """List registered tools."""
    settings = get_settings()
    policy = PolicyEngine(auto_approve=True)
    browser = BrowserSession(
        user_data_dir=settings.ribhus_dir / "browser_profile",
        headed=False,
        allowlist=settings.browser_allowlist_hosts,
    )
    registry = default_registry(
        settings.workspace,
        policy=policy,
        browser_session=browser,
    )
    for name in registry.names():
        tool = registry.get(name)
        risk = getattr(tool, "risk_level", "?") if tool else "?"
        desc = (tool.description if tool else "")[:80]
        console.print(f"[cyan]{name}[/cyan] ({risk}) — {desc}")


@app.command("version")
def show_version() -> None:
    """Show version."""
    console.print(f"ribhus {__version__}")


@skill_app.command("list")
def skill_list() -> None:
    """List available skills."""
    settings = get_settings()
    registry = SkillRegistry.load_default(settings.workspace)
    if not registry.names():
        console.print("No skills found.")
        return
    for skill in registry.list():
        triggers = ", ".join(skill.config.triggers[:4])
        console.print(
            f"[cyan]{skill.name}[/cyan] v{skill.config.version} — "
            f"{skill.config.description}"
        )
        if triggers:
            console.print(f"  triggers: {triggers}")


@skill_app.command("install")
def skill_install(
    source: str = typer.Argument(..., help="Skill name or path to skill directory"),
) -> None:
    """Install a skill into .ribhus/skills."""
    settings = get_settings()
    try:
        skill = install_skill(source, workspace=settings.workspace)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Installed[/green] {skill.name} v{skill.config.version}")


@skill_app.command("remove")
def skill_remove(
    name: str = typer.Argument(..., help="Installed skill name"),
) -> None:
    """Remove an installed skill from .ribhus/skills."""
    settings = get_settings()
    try:
        remove_skill(name, workspace=settings.workspace)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Removed[/green] {name}")


@skill_app.command("create")
def skill_create(
    name: str = typer.Argument(..., help="New skill name"),
    description: str = typer.Option("Custom Ribhus skill", "--description", "-d"),
) -> None:
    """Scaffold a new skill under ./skills."""
    settings = get_settings()
    try:
        path = create_skill(name, workspace=settings.workspace, description=description)
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Created[/green] {path}")


def run() -> None:
    """Entry point: ribhus | ribhus "prompt" | ribhus tools | ribhus skill …"""
    args = sys.argv[1:]

    if not args:
        _interactive()
        return

    if args[0] in {"-h", "--help"}:
        app()
        return

    if args[0] in {"-V", "--version", "version"}:
        console.print(f"ribhus {__version__}")
        return

    if args[0] in {"tools", "skill"}:
        app(args)
        return

    prompt = " ".join(args)
    _run_prompt(prompt)


if __name__ == "__main__":
    run()
