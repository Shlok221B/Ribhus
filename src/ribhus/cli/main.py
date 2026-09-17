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
from ribhus.channels.whatsapp_web.policy import (
    CHANNEL_LABEL,
    TOS_WARNING,
    WhatsAppPolicy,
)
from ribhus.channels.whatsapp_web.session import WhatsAppSession
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
whatsapp_app = typer.Typer(
    help="WhatsApp Web channel (browser automation — not the official API).",
)
app.add_typer(skill_app, name="skill")
app.add_typer(whatsapp_app, name="whatsapp")
console = Console()


def _whatsapp_send_approver(arguments: dict[str, Any]) -> bool:
    """Approve / edit / cancel a WhatsApp send. Mutates arguments['message'] on edit."""
    contact = str(arguments.get("contact") or "").strip() or "(unknown)"
    draft = str(arguments.get("message") or "")
    console.print()
    console.print(
        Panel(
            f"[bold]{CHANNEL_LABEL}[/bold]\n"
            f"To: [cyan]{contact}[/cyan]\n\n"
            f"[bold]Draft[/bold]\n{draft}\n\n"
            f"[dim]{TOS_WARNING}[/dim]",
            title="WhatsApp send — approval required",
            border_style="yellow",
        )
    )
    try:
        answer = console.input(
            "[bold yellow][A]pprove  [E]dit  [C]ancel:[/bold yellow] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[red]Cancelled[/red]")
        return False
    if answer in {"a", "approve", "y", "yes"}:
        return True
    if answer in {"e", "edit"}:
        try:
            edited = console.input("[bold yellow]Edited message:[/bold yellow] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[red]Cancelled[/red]")
            return False
        if not edited.strip():
            console.print("[red]Empty edit — cancelled[/red]")
            return False
        arguments["message"] = edited
        return True
    console.print("[red]Cancelled[/red]")
    return False


def _cli_approver(name: str, risk: RiskLevel, arguments: dict[str, Any]) -> bool:
    if name == "whatsapp_send":
        return _whatsapp_send_approver(arguments)
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


def _whatsapp_runtime(settings: Settings) -> tuple[WhatsAppSession, WhatsAppPolicy]:
    session = WhatsAppSession(
        user_data_dir=settings.ribhus_dir / "whatsapp_profile",
        headed=settings.whatsapp_headed,
        login_timeout=settings.whatsapp_login_timeout,
    )
    policy = WhatsAppPolicy(
        enabled=settings.whatsapp_enabled,
        kill_path=settings.ribhus_dir / "whatsapp.killed",
        sends_per_minute=settings.whatsapp_rate_limit,
        sends_per_hour=settings.whatsapp_max_per_hour,
        cooldown_seconds=settings.whatsapp_cooldown,
    )
    return session, policy


def _build_runtime(settings: Settings | None = None, *, prompt: str = ""):
    settings = settings or get_settings()
    model = OpenAICompatibleModel(settings)
    # Always attach the CLI approver so WhatsApp sends cannot skip the prompt
    # even when RIBHUS_AUTO_APPROVE=true.
    policy = PolicyEngine(
        auto_approve=settings.auto_approve,
        approve_at_or_above=settings.approve_at_level,
        approver=_cli_approver,
    )
    audit = AuditLog(settings.ribhus_dir / "audit.jsonl")
    browser = BrowserSession(
        user_data_dir=settings.ribhus_dir / "browser_profile",
        headed=settings.browser_headed,
        allowlist=settings.browser_allowlist_hosts,
        rate_limit_per_minute=settings.browser_rate_limit,
    )
    whatsapp, wa_policy = _whatsapp_runtime(settings)
    tools = default_registry(
        settings.workspace,
        policy=policy,
        audit=audit,
        browser_session=browser,
        screenshot_dir=settings.ribhus_dir / "screenshots",
        whatsapp_session=whatsapp,
        whatsapp_policy=wa_policy,
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
    return agent, browser, whatsapp, matched


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
    agent, browser, whatsapp, matched = _build_runtime(prompt=prompt)
    if matched:
        names = ", ".join(s.name for s in matched)
        console.print(f"[magenta]✦ using skill: {names}[/magenta]")
    try:
        state = await agent.run(prompt)
        return state.final_text or ""
    finally:
        await browser.close()
        await whatsapp.close()


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
            "Skills: [cyan]ribhus skill list[/cyan]  ·  "
            "WhatsApp: [cyan]ribhus whatsapp status[/cyan]",
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
    whatsapp, wa_policy = _whatsapp_runtime(settings)
    registry = default_registry(
        settings.workspace,
        policy=policy,
        browser_session=browser,
        whatsapp_session=whatsapp,
        whatsapp_policy=wa_policy,
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


@whatsapp_app.command("status")
def whatsapp_status() -> None:
    """Show kill-switch, rate limits, and session path. Does not open a browser."""
    settings = get_settings()
    _session, policy = _whatsapp_runtime(settings)
    status = policy.status()
    killed = status["killed"]
    console.print(
        Panel(
            f"[bold]{CHANNEL_LABEL}[/bold]\n\n"
            f"{TOS_WARNING}\n\n"
            f"killed: [{'red' if killed else 'green'}]{killed}[/]\n"
            f"enabled (env): {status['enabled']}\n"
            f"rate: {status['sends_per_minute']}/min, "
            f"{status['sends_per_hour']}/hour, "
            f"cooldown {status['cooldown_seconds']}s\n"
            f"profile (credentials): {settings.ribhus_dir / 'whatsapp_profile'}\n"
            f"kill file: {status['kill_path']}",
            title="WhatsApp Web channel",
            border_style="red" if killed else "blue",
        )
    )


@whatsapp_app.command("kill")
def whatsapp_kill() -> None:
    """Immediately stop all WhatsApp actions until you resume."""
    settings = get_settings()
    _session, policy = _whatsapp_runtime(settings)
    policy.kill()
    console.print(
        "[red]WhatsApp channel killed.[/red] "
        "All whatsapp_* tools will refuse to run. "
        "Resume with [cyan]ribhus whatsapp resume[/cyan]."
    )


@whatsapp_app.command("resume")
def whatsapp_resume() -> None:
    """Clear the kill switch. Sends still require approval."""
    settings = get_settings()
    _session, policy = _whatsapp_runtime(settings)
    policy.resume()
    if not settings.whatsapp_enabled:
        console.print(
            "[yellow]Kill file cleared, but RIBHUS_WHATSAPP_ENABLED=false "
            "still disables the channel.[/yellow]"
        )
        return
    console.print(
        "[green]WhatsApp channel resumed.[/green] "
        "Sends still require explicit approve / edit / cancel."
    )


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

    if args[0] in {"tools", "skill", "whatsapp"}:
        app(args)
        return

    prompt = " ".join(args)
    _run_prompt(prompt)


if __name__ == "__main__":
    run()
