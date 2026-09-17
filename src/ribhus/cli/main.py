from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
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
from ribhus.cli.dispatch import parse_cli_invocations
from ribhus.config import Settings, get_settings
from ribhus.memory.models import KINDS
from ribhus.memory.service import MemoryService
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.policy.audit import AuditLog
from ribhus.policy.engine import PolicyEngine
from ribhus.policy.levels import RiskLevel
from ribhus.skills.installer import (
    create_skill,
    install_skill_with_warnings,
    remove_skill,
)
from ribhus.skills.package import SkillPackageError, validate_skill
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
memory_app = typer.Typer(
    help="View, edit, delete, export, or disable persistent memory.",
)
whatsapp_app = typer.Typer(
    help="WhatsApp Web channel (browser automation — not the official API).",
)
app.add_typer(skill_app, name="skill")
app.add_typer(memory_app, name="memory")
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


def _memory_service(settings: Settings | None = None) -> MemoryService:
    settings = settings or get_settings()
    return MemoryService.from_path(
        settings.ribhus_dir / "memory.sqlite",
        env_enabled=settings.memory_enabled,
    )


def _build_runtime(
    settings: Settings | None = None,
    *,
    prompt: str = "",
    browser: BrowserSession | None = None,
    whatsapp: WhatsAppSession | None = None,
    wa_policy: WhatsAppPolicy | None = None,
    memory: MemoryService | None = None,
):
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
    if browser is None:
        browser = BrowserSession(
            user_data_dir=settings.ribhus_dir / "browser_profile",
            headed=settings.browser_headed,
            allowlist=settings.browser_allowlist_hosts,
            rate_limit_per_minute=settings.browser_rate_limit,
        )
    if whatsapp is None or wa_policy is None:
        whatsapp, wa_policy = _whatsapp_runtime(settings)
    if memory is None:
        memory = _memory_service(settings)
    tools = default_registry(
        settings.workspace,
        policy=policy,
        audit=audit,
        browser_session=browser,
        screenshot_dir=settings.ribhus_dir / "screenshots",
        whatsapp_session=whatsapp,
        whatsapp_policy=wa_policy,
        memory=memory,
    )
    skills = SkillRegistry.load_default(settings.workspace)
    matched = skills.match(prompt) if prompt else []
    agent = Agent(
        model=model,
        tools=tools,
        max_iterations=settings.max_iterations,
        on_event=_on_event,
        skill_prompt_addon=skills.prompt_addon(prompt) if prompt else "",
        skill_names=[s.name for s in matched],
        memory=memory,
    )
    return agent, browser, whatsapp, wa_policy, matched, memory


async def _pause_and_close_whatsapp(whatsapp: WhatsAppSession) -> None:
    """Keep the headed window visible until the user is done looking at it."""
    if whatsapp.page is not None and sys.stdin.isatty():
        console.print()
        console.print(
            "[dim]WhatsApp window is still open so you can check the chat.[/dim]"
        )
        try:
            console.input("[bold]Press Enter to close it:[/bold] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
    await whatsapp.close()


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
    agent, browser, whatsapp, _wa_policy, matched, _memory = _build_runtime(prompt=prompt)
    if matched:
        names = ", ".join(s.name for s in matched)
        console.print(f"[magenta]✦ using skill: {names}[/magenta]")
    try:
        state = await agent.run(prompt)
        return state.final_text or ""
    finally:
        await browser.close()
        await _pause_and_close_whatsapp(whatsapp)


def _print_answer(text: str) -> None:
    console.print()
    console.print(Panel(Markdown(text), title="Ribhus", border_style="blue"))


def _run_prompt(prompt: str) -> None:
    try:
        answer = asyncio.run(_run_once(prompt))
    except ValueError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    except Exception as extra:  # noqa: BLE001
        console.print(f"[red]Error: {extra}[/red]")
        raise typer.Exit(code=1) from extra
    _print_answer(answer)


def _interactive() -> None:
    asyncio.run(_interactive_async())


async def _interactive_async() -> None:
    console.print(
        Panel(
            f"[bold]Ribhus[/bold] {__version__}\n"
            "Type a task, or a command like [cyan]skill list[/cyan] / "
            "[cyan]memory list[/cyan]. [cyan]/exit[/cyan] to leave.\n"
            "Shell: [cyan]uv run ribhus skill validate travel[/cyan]",
            border_style="blue",
        )
    )
    browser = None
    whatsapp = None
    wa_policy = None
    memory = None
    try:
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
            cli_groups = parse_cli_invocations([line])
            if cli_groups:
                code = _run_cli_groups(cli_groups)
                if code:
                    console.print(f"[red]Command exited {code}[/red]")
                continue
            try:
                agent, browser, whatsapp, wa_policy, matched, memory = _build_runtime(
                    prompt=line,
                    browser=browser,
                    whatsapp=whatsapp,
                    wa_policy=wa_policy,
                    memory=memory,
                )
                if matched:
                    names = ", ".join(s.name for s in matched)
                    console.print(f"[magenta]✦ using skill: {names}[/magenta]")
                state = await agent.run(line)
            except ValueError as extra:
                console.print(f"[red]{extra}[/red]")
                continue
            except Exception as extra:  # noqa: BLE001
                console.print(f"[red]Error: {extra}[/red]")
                continue
            _print_answer(state.final_text or "")
    finally:
        if browser is not None:
            await browser.close()
        if whatsapp is not None:
            await _pause_and_close_whatsapp(whatsapp)


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
    memory = _memory_service(settings)
    registry = default_registry(
        settings.workspace,
        policy=policy,
        browser_session=browser,
        whatsapp_session=whatsapp,
        whatsapp_policy=wa_policy,
        memory=memory,
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
        skill, warnings = install_skill_with_warnings(
            source, workspace=settings.workspace
        )
    except (FileNotFoundError, FileExistsError, ValueError, SkillPackageError) as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Installed[/green] {skill.name} v{skill.config.version}")
    for warning in warnings:
        console.print(f"[yellow]{warning}[/yellow]")


@skill_app.command("remove")
def skill_remove(
    name: str = typer.Argument(..., help="Installed skill name"),
) -> None:
    """Remove an installed skill from .ribhus/skills."""
    settings = get_settings()
    try:
        remove_skill(name, workspace=settings.workspace)
    except FileNotFoundError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
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
    except (FileExistsError, ValueError) as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Created[/green] {path}")
    console.print("[dim]Package: config.yaml, skill.md, README.md, tools.py, tests/[/dim]")


@skill_app.command("validate")
def skill_validate(
    source: str = typer.Argument(..., help="Skill name or path to skill directory"),
) -> None:
    """Check that a skill directory is a valid installable package."""
    settings = get_settings()
    path = Path(source)
    if not path.exists():
        from ribhus.skills.installer import skill_search_dirs

        found = None
        for root in skill_search_dirs(settings.workspace):
            candidate = root / source
            if candidate.is_dir():
                found = candidate
                break
        if found is None:
            console.print(f"[red]Skill not found: {source}[/red]")
            raise typer.Exit(code=1)
        path = found
    try:
        warnings = validate_skill(path)
    except SkillPackageError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Valid skill package[/green] {path}")
    for warning in warnings:
        console.print(f"[yellow]{warning}[/yellow]")


def _print_memory(record) -> None:
    flag = " [dim]disabled[/dim]" if record.disabled else ""
    console.print(
        f"[cyan]{record.id}[/cyan] ({record.kind}){flag}  {record.preview(90)}"
    )


@memory_app.command("list")
def memory_list(
    kind: str | None = typer.Option(
        None, "--kind", "-k", help="short_term, episodic, or semantic"
    ),
    all_records: bool = typer.Option(
        False, "--all", help="Include disabled memories"
    ),
) -> None:
    """List saved memories."""
    memory = _memory_service()
    if not memory.env_enabled:
        console.print("[yellow]RIBHUS_MEMORY_ENABLED=false — recall is off.[/yellow]")
    elif not memory.enabled:
        console.print("[yellow]Memory is disabled. `ribhus memory enable` to resume.[/yellow]")
    if kind is not None and kind not in KINDS:
        console.print(f"[red]Unknown kind: {kind}. Use {', '.join(KINDS)}[/red]")
        raise typer.Exit(code=1)
    try:
        records = memory.list(kind=kind, include_disabled=all_records)  # type: ignore[arg-type]
    except ValueError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    if not records:
        console.print("No memories stored.")
        return
    for record in records:
        _print_memory(record)


@memory_app.command("show")
def memory_show(
    memory_id: str = typer.Argument(..., help="Memory id (e.g. sem_ab12cd34ef)"),
) -> None:
    """View one memory."""
    memory = _memory_service()
    try:
        record = memory.get(memory_id)
    except FileNotFoundError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(
        Panel(
            f"[bold]{record.id}[/bold]  {record.kind}"
            f"{'  disabled' if record.disabled else ''}\n"
            f"key: {record.key or '—'}\n"
            f"updated: {record.updated_at}\n\n{record.content}",
            title="Memory",
            border_style="blue",
        )
    )


@memory_app.command("add")
def memory_add(
    content: str = typer.Argument(..., help="Fact or preference to remember"),
    key: str | None = typer.Option(None, "--key", help="Optional stable key to upsert"),
) -> None:
    """Add a semantic memory (user preference or fact)."""
    memory = _memory_service()
    try:
        record = memory.remember_fact(content, key=key)
    except ValueError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Saved[/green] {record.id}")


@memory_app.command("edit")
def memory_edit(
    memory_id: str = typer.Argument(..., help="Memory id"),
    content: str = typer.Option(..., "--content", "-c", help="Replacement text"),
) -> None:
    """Edit a memory's content."""
    memory = _memory_service()
    try:
        record = memory.edit(memory_id, content)
    except (FileNotFoundError, ValueError) as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Updated[/green] {record.id}")


@memory_app.command("delete")
def memory_delete(
    memory_id: str = typer.Argument(..., help="Memory id"),
) -> None:
    """Delete a memory permanently."""
    memory = _memory_service()
    try:
        memory.delete(memory_id)
    except FileNotFoundError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Deleted[/green] {memory_id}")


@memory_app.command("export")
def memory_export(
    out: Path | None = typer.Option(None, "--out", "-o", help="Write JSON to this file"),
) -> None:
    """Export all memories as JSON (including disabled)."""
    memory = _memory_service()
    payload = json.dumps(memory.export(), indent=2, default=str)
    if out is None:
        console.print(payload)
        return
    out.write_text(payload, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out}")


@memory_app.command("disable")
def memory_disable(
    memory_id: str | None = typer.Argument(
        None, help="Memory id, or omit to turn memory off globally"
    ),
) -> None:
    """Disable one memory, or all memory injection."""
    memory = _memory_service()
    if memory_id is None:
        memory.set_enabled(False)
        console.print("[yellow]Memory disabled.[/yellow] Agent will not recall or save.")
        return
    try:
        record = memory.disable(memory_id)
    except FileNotFoundError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[yellow]Disabled[/yellow] {record.id}")


@memory_app.command("enable")
def memory_enable(
    memory_id: str | None = typer.Argument(
        None, help="Memory id, or omit to turn memory on globally"
    ),
) -> None:
    """Re-enable one memory, or all memory injection."""
    memory = _memory_service()
    if memory_id is None:
        memory.set_enabled(True)
        if not memory.env_enabled:
            console.print(
                "[yellow]Local flag on, but RIBHUS_MEMORY_ENABLED=false still blocks recall.[/yellow]"
            )
            return
        console.print("[green]Memory enabled.[/green]")
        return
    try:
        record = memory.enable(memory_id)
    except FileNotFoundError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]Enabled[/green] {record.id}")


@whatsapp_app.command("status")
def whatsapp_status(
    check_login: bool = typer.Option(
        False,
        "--check-login",
        help="Open WhatsApp Web, wait for a QR scan if needed, confirm the chat list.",
    ),
) -> None:
    """Show kill-switch, rate limits, and session path."""
    settings = get_settings()
    session, policy = _whatsapp_runtime(settings)
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
    if not check_login:
        return
    if policy.is_killed():
        console.print("[red]Channel is stopped. Resume before checking login.[/red]")
        raise typer.Exit(code=1)
    asyncio.run(_check_login(session))


async def _check_login(session: WhatsAppSession) -> None:
    def on_status(message: str) -> None:
        console.print(f"[yellow]{message}[/yellow]")

    try:
        await session.ensure_logged_in(on_status=on_status)
        state = await session.login_state()
    except Exception as extra:  # noqa: BLE001
        console.print(f"[red]{extra}[/red]")
        await session.close()
        raise typer.Exit(code=1) from extra
    logged = bool(state.get("logged_in"))
    console.print(
        f"[{'green' if logged else 'red'}]"
        f"logged_in={logged} chat_list_ready={logged} "
        f"qr_visible={state.get('qr_visible')}[/]"
    )
    await _pause_and_close_whatsapp(session)


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


def _invoke_cli(argv: list[str]) -> int:
    """Run a Typer subcommand without killing the process on success."""
    try:
        app(argv, standalone_mode=False)
        return 0
    except typer.Exit as extra:
        return int(extra.exit_code or 0)
    except SystemExit as extra:
        code = extra.code
        if code in {None, 0}:
            return 0
        if isinstance(code, int):
            return code
        return 1


def _run_cli_groups(groups: list[list[str]]) -> int:
    for argv in groups:
        code = _invoke_cli(argv)
        if code:
            return code
    return 0


def run() -> None:
    """Entry point: ribhus | ribhus "prompt" | ribhus tools | ribhus skill …"""
    args = sys.argv[1:]

    if not args:
        _interactive()
        return

    if args[0] in {"-h", "--help"}:
        app()
        return

    if args[0] in {"-V", "--version"}:
        console.print(f"ribhus {__version__}")
        return

    cli_groups = parse_cli_invocations(args)
    if cli_groups is not None:
        raise SystemExit(_run_cli_groups(cli_groups))

    prompt = " ".join(args)
    _run_prompt(prompt)


if __name__ == "__main__":
    run()
