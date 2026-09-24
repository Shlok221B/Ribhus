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
from ribhus.channels.gmail_web.policy import (
    CHANNEL_LABEL as EMAIL_CHANNEL_LABEL,
    TOS_WARNING as EMAIL_TOS_WARNING,
    EmailPolicy,
)
from ribhus.channels.gmail_web.session import GmailSession
from ribhus.channels.whatsapp_web.policy import (
    CHANNEL_LABEL,
    TOS_WARNING,
    WhatsAppPolicy,
)
from ribhus.channels.whatsapp_web.session import WhatsAppSession
from ribhus.cli.dispatch import parse_cli_invocations
from ribhus.cli.goodbye import random_goodbye
from ribhus.cli.status import random_status
from ribhus.config import Settings, get_settings
from ribhus.mcp.config import (
    default_mcp_config_path,
    example_mcp_config,
    load_mcp_config,
)
from ribhus.mcp.manager import McpManager, start_mcp_manager
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
from ribhus.tools.todo import TodoStore

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
mcp_app = typer.Typer(help="MCP client — connect external tool servers.")
email_app = typer.Typer(
    help="Gmail Web channel (browser automation — not the Gmail API).",
)
app.add_typer(skill_app, name="skill")
app.add_typer(memory_app, name="memory")
app.add_typer(whatsapp_app, name="whatsapp")
app.add_typer(mcp_app, name="mcp")
app.add_typer(email_app, name="email")
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


def _cli_clarify(question: str, choices: list[str] | None) -> str:
    """Ask the user a clarifying question; return their answer or 'cancel'."""
    console.print()
    body = f"[bold]{question}[/bold]"
    if choices:
        opts = "\n".join(f"  [cyan]{i}[/cyan]. {c}" for i, c in enumerate(choices, 1))
        body += f"\n\n{opts}\n\n[dim]Type a number, or your own answer. /cancel to skip.[/dim]"
    else:
        body += "\n\n[dim]Type your answer. /cancel to skip.[/dim]"
    console.print(Panel(body, title="Clarify", border_style="cyan"))
    try:
        raw = console.input("[bold cyan]Your answer:[/bold cyan] ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Skipped[/yellow]")
        return "cancel"
    if not raw:
        return ""
    if raw.lower() in {"/cancel", "cancel", "skip", "/skip"}:
        return "cancel"
    if choices and raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
    return raw


def _email_send_approver(arguments: dict[str, Any]) -> bool:
    """Approve / edit / cancel a Gmail send. Mutates arguments['body'] on edit."""
    mode = str(arguments.get("mode") or "reply").strip().lower() or "reply"
    to = str(arguments.get("to") or "").strip() or (
        "(open thread)" if mode == "reply" else "(unknown)"
    )
    subject = str(arguments.get("subject") or "").strip() or (
        "(reply)" if mode == "reply" else "(no subject)"
    )
    body = str(arguments.get("body") or "")
    console.print()
    console.print(
        Panel(
            f"[bold]{EMAIL_CHANNEL_LABEL}[/bold]\n"
            f"Mode: [cyan]{mode}[/cyan]\n"
            f"To: [cyan]{to}[/cyan]\n"
            f"Subject: [cyan]{subject}[/cyan]\n\n"
            f"[bold]Body[/bold]\n{body}\n\n"
            f"[dim]{EMAIL_TOS_WARNING}[/dim]",
            title="Gmail send — approval required",
            border_style="yellow",
        )
    )
    try:
        answer = console.input(
            "[bold yellow]Type [A]pprove, [E]dit body, or [C]ancel:[/bold yellow] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[red]Cancelled[/red]")
        return False
    if answer in {"a", "approve", "y", "yes"}:
        return True
    if answer in {"e", "edit"}:
        try:
            edited = console.input("[bold yellow]Edited body:[/bold yellow] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[red]Cancelled[/red]")
            return False
        if not edited.strip():
            console.print("[red]Empty edit — cancelled[/red]")
            return False
        arguments["body"] = edited
        return True
    console.print("[red]Cancelled[/red]")
    return False


def _cli_approver(name: str, risk: RiskLevel, arguments: dict[str, Any]) -> bool:
    if name == "whatsapp_send":
        return _whatsapp_send_approver(arguments)
    if name == "email_send":
        return _email_send_approver(arguments)
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


def _email_runtime(settings: Settings) -> tuple[GmailSession, EmailPolicy]:
    session = GmailSession(
        user_data_dir=settings.ribhus_dir / "gmail_profile",
        headed=settings.email_headed,
        login_timeout=settings.email_login_timeout,
    )
    policy = EmailPolicy(
        enabled=settings.email_enabled,
        kill_path=settings.ribhus_dir / "email.killed",
        sends_per_minute=settings.email_rate_limit,
        sends_per_hour=settings.email_max_per_hour,
        cooldown_seconds=settings.email_cooldown,
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
    gmail: GmailSession | None = None,
    email_policy: EmailPolicy | None = None,
    memory: MemoryService | None = None,
    todo_store: TodoStore | None = None,
    mcp_manager: McpManager | None = None,
    sticky_skills: list[str] | None = None,
    approver=None,
):
    settings = settings or get_settings()
    model = OpenAICompatibleModel(settings)
    # Always attach an approver so WhatsApp/Gmail sends cannot skip the prompt
    # even when RIBHUS_AUTO_APPROVE=true.
    policy = PolicyEngine(
        auto_approve=settings.auto_approve,
        approve_at_or_above=settings.approve_at_level,
        approver=approver or _cli_approver,
    )
    audit = AuditLog(settings.ribhus_dir / "audit.jsonl")
    if browser is None:
        browser = BrowserSession(
            user_data_dir=settings.ribhus_dir / "browser_profile",
            headed=settings.browser_headed,
            allowlist=settings.browser_allowlist_hosts,
            rate_limit_per_minute=settings.browser_rate_limit,
            cdp_url=settings.browser_cdp_url or None,
        )
    if whatsapp is None or wa_policy is None:
        whatsapp, wa_policy = _whatsapp_runtime(settings)
    if gmail is None or email_policy is None:
        gmail, email_policy = _email_runtime(settings)
    if memory is None:
        memory = _memory_service(settings)
    if todo_store is None:
        todo_store = TodoStore()
    tools = default_registry(
        settings.workspace,
        policy=policy,
        audit=audit,
        browser_session=browser,
        screenshot_dir=settings.ribhus_dir / "screenshots",
        whatsapp_session=whatsapp,
        whatsapp_policy=wa_policy,
        memory=memory,
        clarify_asker=_cli_clarify if sys.stdin.isatty() else None,
        todo_store=todo_store,
        mcp_manager=mcp_manager,
        vision_api_key=settings.api_key or None,
        vision_base_url=settings.base_url,
        vision_model=settings.effective_vision_model,
        gmail_session=gmail,
        email_policy=email_policy,
    )
    skills = SkillRegistry.load_default(settings.workspace)
    matched = (
        skills.match_with_sticky(prompt, sticky_skills) if prompt else []
    )
    skill_names = [s.name for s in matched]
    # Booking handoff needs a visible window so the user can pay.
    if "travel" in skill_names and not browser.headed and browser.page is None:
        browser.headed = True
    if memory.enabled and prompt:
        memory.prepare_for_prompt(prompt, skill_names=skill_names)
        memory.prompt_addon(prompt)
    agent = Agent(
        model=model,
        tools=tools,
        max_iterations=settings.max_iterations,
        on_event=_on_event,
        skill_prompt_addon=(
            skills.prompt_addon(prompt, sticky_names=sticky_skills) if prompt else ""
        ),
        skill_names=skill_names,
        memory=memory,
        todo_store=todo_store,
    )
    return (
        agent,
        browser,
        whatsapp,
        wa_policy,
        gmail,
        email_policy,
        matched,
        memory,
        todo_store,
        mcp_manager,
    )


async def _ensure_mcp(
    settings: Settings,
    mcp_manager: McpManager | None,
) -> McpManager | None:
    if mcp_manager is not None:
        return mcp_manager
    config_path = None
    if settings.mcp_config.strip():
        config_path = Path(settings.mcp_config.strip())
    manager = await start_mcp_manager(
        settings.workspace,
        enabled=settings.mcp_enabled,
        config_path=config_path,
    )
    if manager is None:
        return None
    for err in manager.errors:
        console.print(f"[yellow]MCP:[/yellow] {err}")
    if manager.connected_servers:
        names = ", ".join(manager.connected_servers)
        n_tools = len(manager.tools)
        console.print(f"[dim]MCP connected: {names} ({n_tools} tools)[/dim]")
    return manager


async def _cleanup_mcp(mcp_manager: McpManager | None) -> None:
    if mcp_manager is not None:
        await mcp_manager.close()


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


async def _close_gmail(gmail: GmailSession, *, pause: bool = False) -> None:
    """Close the Gmail Chromium session.

    By default closes immediately after send/agent exit. Pass pause=True for
    interactive checks (e.g. email status --check-login).
    """
    if pause and gmail.page is not None and sys.stdin.isatty():
        console.print()
        console.print(
            "[dim]Gmail window is still open so you can check the inbox.[/dim]"
        )
        try:
            console.input("[bold]Press Enter to close it:[/bold] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
    await gmail.close()


async def _on_event(event: str, data: dict) -> None:
    if event == "thinking":
        console.print(f"[dim]{random_status()}…[/dim]")
    elif event == "skill":
        console.print("[magenta]✦ skill active[/magenta]")
    elif event == "plan":
        display = data.get("display")
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        if display:
            console.print(f"[dim]plan:\n{display}[/dim]")
        elif summary:
            total = summary.get("total", 0)
            done = summary.get("completed", 0)
            console.print(f"[dim]plan: {done}/{total} done[/dim]")
    elif event == "tool_start":
        console.print(f"[cyan]→ {data.get('name')}[/cyan]")
    elif event == "tool_end":
        name = data.get("name")
        ok = bool(data.get("ok", True))
        if ok:
            console.print(f"[green]✓ {name}[/green]")
        else:
            console.print(f"[yellow]✗ {name} (cancelled or failed)[/yellow]")
        if name == "todo":
            preview_todo = _todo_event_preview(data.get("result_preview"))
            if preview_todo:
                console.print(f"[dim]{preview_todo}[/dim]")


def _todo_event_preview(result: Any) -> str | None:
    if not isinstance(result, str) or not result.strip():
        return None
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return None
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return None
    total = summary.get("total", 0)
    done = summary.get("completed", 0)
    active = summary.get("in_progress", 0)
    pending = summary.get("pending", 0)
    return f"todo: {done}/{total} done · {active} active · {pending} pending"


async def _cleanup_processes(tools) -> None:
    """Terminate any background shells started via the process tool."""
    tool = tools.get("process") if tools is not None else None
    registry = getattr(tool, "registry", None) if tool is not None else None
    if registry is not None:
        await registry.kill_all()


async def _run_once(prompt: str) -> str:
    settings = get_settings()
    mcp_manager = await _ensure_mcp(settings, None)
    (
        agent,
        browser,
        whatsapp,
        _wa_policy,
        gmail,
        _email_policy,
        matched,
        _memory,
        _todos,
        mcp_manager,
    ) = _build_runtime(prompt=prompt, mcp_manager=mcp_manager)
    if matched:
        names = ", ".join(s.name for s in matched)
        console.print(f"[magenta]✦ using skill: {names}[/magenta]")
    try:
        state = await agent.run(prompt)
        return state.final_text or ""
    finally:
        await _cleanup_processes(agent.tools)
        await _cleanup_mcp(mcp_manager)
        await browser.close()
        await _pause_and_close_whatsapp(whatsapp)
        await _close_gmail(gmail)


def _print_answer(text: str) -> None:
    console.print()
    console.print(Panel(Markdown(text), title="Ribhus", border_style="blue"))


def _say_bye(*, leading_newline: bool = False) -> None:
    line = random_goodbye()
    console.print(f"\n{line}" if leading_newline else line)


def _interactive() -> None:
    try:
        asyncio.run(_interactive_async())
    except KeyboardInterrupt:
        _say_bye(leading_newline=True)


async def _interactive_async() -> None:
    console.print(
        Panel(
            f"[bold]Ribhus[/bold] {__version__}\n"
            "Type a task, or a command like [cyan]skill list[/cyan] / "
            "[cyan]memory list[/cyan]. [cyan]/exit[/cyan] to leave. "
            "[cyan]/clear[/cyan] starts a fresh chat.\n"
            "Shell: [cyan]uv run ribhus skill validate travel[/cyan]",
            border_style="blue",
        )
    )
    settings = get_settings()
    browser = None
    whatsapp = None
    wa_policy = None
    gmail = None
    email_policy = None
    memory = None
    todo_store = None
    chat_history: list[dict[str, Any]] = []
    sticky_skills: list[str] = []
    mcp_manager = await _ensure_mcp(settings, None)
    try:
        while True:
            try:
                line = console.input("[bold blue]>[/bold blue] ").strip()
            except (EOFError, KeyboardInterrupt):
                _say_bye(leading_newline=True)
                break
            if not line:
                continue
            if line in {"/exit", "/quit", "exit", "quit"}:
                _say_bye()
                break
            if line in {"/clear", "/new"}:
                chat_history = []
                sticky_skills = []
                console.print("[dim]Conversation cleared.[/dim]")
                continue
            cli_groups = parse_cli_invocations([line])
            if cli_groups:
                code = _run_cli_groups(cli_groups)
                if code:
                    console.print(f"[red]Command exited {code}[/red]")
                continue
            agent = None
            try:
                from ribhus.skills.travel_handoff import looks_travel_handoff

                # Re-open headed if travel handoff needs a visible payment window.
                if (
                    looks_travel_handoff(line)
                    and "travel" in sticky_skills
                    and browser is not None
                    and not browser.headed
                    and browser.page is not None
                ):
                    await browser.close()
                    browser = None

                (
                    agent,
                    browser,
                    whatsapp,
                    wa_policy,
                    gmail,
                    email_policy,
                    matched,
                    memory,
                    todo_store,
                    mcp_manager,
                ) = _build_runtime(
                    prompt=line,
                    browser=browser,
                    whatsapp=whatsapp,
                    wa_policy=wa_policy,
                    gmail=gmail,
                    email_policy=email_policy,
                    memory=memory,
                    todo_store=todo_store,
                    mcp_manager=mcp_manager,
                    sticky_skills=sticky_skills,
                )
                if matched:
                    sticky_skills = [s.name for s in matched]
                    names = ", ".join(sticky_skills)
                    console.print(f"[magenta]✦ using skill: {names}[/magenta]")
                state = await agent.run(line, history=chat_history or None)
                chat_history = state.history_messages()
            except (KeyboardInterrupt, asyncio.CancelledError):
                if agent is not None:
                    await _cleanup_processes(agent.tools)
                _say_bye(leading_newline=True)
                break
            except ValueError as extra:
                if agent is not None:
                    await _cleanup_processes(agent.tools)
                console.print(f"[red]{extra}[/red]")
                continue
            except Exception as extra:  # noqa: BLE001
                if agent is not None:
                    await _cleanup_processes(agent.tools)
                console.print(f"[red]Error: {extra}[/red]")
                continue
            await _cleanup_processes(agent.tools)
            _print_answer(state.final_text or "")
    finally:
        try:
            await _cleanup_mcp(mcp_manager)
            if browser is not None:
                await browser.close()
            if whatsapp is not None:
                await _pause_and_close_whatsapp(whatsapp)
            if gmail is not None:
                await _close_gmail(gmail)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass


def _run_prompt(prompt: str) -> None:
    try:
        answer = asyncio.run(_run_once(prompt))
    except KeyboardInterrupt:
        _say_bye(leading_newline=True)
        return
    except ValueError as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    except Exception as extra:  # noqa: BLE001
        console.print(f"[red]Error: {extra}[/red]")
        raise typer.Exit(code=1) from extra
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
        cdp_url=settings.browser_cdp_url or None,
    )
    whatsapp, wa_policy = _whatsapp_runtime(settings)
    memory = _memory_service(settings)
    gmail, email_policy = _email_runtime(settings)
    registry = default_registry(
        settings.workspace,
        policy=policy,
        browser_session=browser,
        whatsapp_session=whatsapp,
        whatsapp_policy=wa_policy,
        memory=memory,
        vision_api_key=settings.api_key or None,
        vision_base_url=settings.base_url,
        vision_model=settings.effective_vision_model,
        gmail_session=gmail,
        email_policy=email_policy,
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


@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers and (if reachable) their tools."""
    asyncio.run(_mcp_list_async())


async def _mcp_list_async() -> None:
    settings = get_settings()
    path = (
        Path(settings.mcp_config.strip())
        if settings.mcp_config.strip()
        else default_mcp_config_path(settings.workspace)
    )
    if not path.exists():
        console.print(f"[yellow]No MCP config at {path}[/yellow]")
        console.print("Run [cyan]ribhus mcp init[/cyan] to create an example.")
        return
    try:
        servers = load_mcp_config(path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not servers:
        console.print(f"[dim]Empty mcpServers in {path}[/dim]")
        return

    if not settings.mcp_enabled:
        console.print("[yellow]MCP disabled (RIBHUS_MCP_ENABLED=false)[/yellow]")

    manager = McpManager()
    try:
        await manager.connect(servers, workspace=settings.workspace)
        for row in manager.status():
            state = "connected" if row["connected"] else "offline"
            if not row["enabled"]:
                state = "disabled"
            console.print(
                f"[cyan]{row['name']}[/cyan] ({state}, risk={row['risk']}) "
                f"— {row['command']}"
            )
            for tool_name in row["tools"]:
                console.print(f"  · {row['name']}__{tool_name}")
            if row["enabled"] and not row["connected"]:
                console.print("  [yellow](failed to connect)[/yellow]")
        for err in manager.errors:
            console.print(f"[yellow]{err}[/yellow]")
    finally:
        await manager.close()


@mcp_app.command("test")
def mcp_test(
    server: str = typer.Argument("demo", help="Server name from mcp.json"),
) -> None:
    """Call a simple tool on an MCP server (demo.add by default)."""
    asyncio.run(_mcp_test_async(server))


async def _mcp_test_async(server: str) -> None:
    settings = get_settings()
    path = (
        Path(settings.mcp_config.strip())
        if settings.mcp_config.strip()
        else default_mcp_config_path(settings.workspace)
    )
    if not path.exists():
        console.print(f"[yellow]No MCP config at {path}[/yellow]")
        raise typer.Exit(1)
    servers = load_mcp_config(path)
    match = next((s for s in servers if s.name == server), None)
    if match is None:
        console.print(f"[red]Unknown server '{server}'[/red]")
        raise typer.Exit(1)
    manager = McpManager()
    try:
        await manager.connect([match], workspace=settings.workspace)
        if manager.errors:
            for err in manager.errors:
                console.print(f"[red]{err}[/red]")
            raise typer.Exit(1)
        tools = [t for t in manager.tools if t.server_name == server]
        if not tools:
            console.print("[yellow]Server connected but exposed no tools[/yellow]")
            return
        probe = next((t for t in tools if t.remote_name == "add"), tools[0])
        args: dict[str, Any] = {}
        if probe.remote_name == "add":
            args = {"a": 2, "b": 40}
        elif probe.remote_name == "echo":
            args = {"message": "namaste"}
        result = await probe.execute(args)
        console.print(f"[green]{probe.name}[/green] → {result}")
    finally:
        await manager.close()


@mcp_app.command("init")
def mcp_init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing mcp.json"),
) -> None:
    """Write an example `.ribhus/mcp.json` pointing at the demo server."""
    settings = get_settings()
    path = default_mcp_config_path(settings.workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        console.print(f"[yellow]Already exists:[/yellow] {path}")
        console.print("Pass [cyan]--force[/cyan] to overwrite.")
        raise typer.Exit(1)
    payload = example_mcp_config(settings.workspace)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    console.print(f"[green]Wrote[/green] {path}")
    console.print("Try: [cyan]uv run ribhus mcp list[/cyan]")


@email_app.command("status")
def email_status_cmd(
    check_login: bool = typer.Option(
        False,
        "--check-login",
        help="Open Gmail, wait for Google sign-in if needed, confirm the inbox.",
    ),
) -> None:
    """Show kill-switch, rate limits, and session path."""
    settings = get_settings()
    session, policy = _email_runtime(settings)
    status = policy.status()
    killed = status["killed"]
    console.print(
        Panel(
            f"[bold]{EMAIL_CHANNEL_LABEL}[/bold]\n\n"
            f"{EMAIL_TOS_WARNING}\n\n"
            f"killed: [{'red' if killed else 'green'}]{killed}[/]\n"
            f"enabled (env): {status['enabled']}\n"
            f"rate: {status['sends_per_minute']}/min, "
            f"{status['sends_per_hour']}/hour, "
            f"cooldown {status['cooldown_seconds']}s\n"
            f"profile (credentials): {settings.ribhus_dir / 'gmail_profile'}\n"
            f"kill file: {status['kill_path']}",
            title="Gmail Web channel",
            border_style="red" if killed else "blue",
        )
    )
    if not check_login:
        return
    if policy.is_killed():
        console.print("[red]Channel is stopped. Resume before checking login.[/red]")
        raise typer.Exit(code=1)
    asyncio.run(_check_gmail_login(session))


async def _check_gmail_login(session: GmailSession) -> None:
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
        f"logged_in={logged} login_prompt={state.get('login_prompt')}[/]"
    )
    await _close_gmail(session, pause=True)


@email_app.command("kill")
def email_kill() -> None:
    """Immediately stop all Gmail actions until you resume."""
    settings = get_settings()
    _session, policy = _email_runtime(settings)
    policy.kill()
    console.print(
        "[red]Email/Gmail channel killed.[/red] "
        "All email_* tools will refuse to run. "
        "Resume with [cyan]ribhus email resume[/cyan]."
    )


@email_app.command("send")
def email_send_cmd(
    to: str = typer.Option(..., "--to", help="Recipient email"),
    subject: str = typer.Option(..., "--subject", "-s", help="Subject line"),
    body: str = typer.Option(..., "--body", "-b", help="Message body"),
) -> None:
    """Send one email via Gmail Web (skips the agent; still asks A/E/C)."""
    settings = get_settings()
    session, policy = _email_runtime(settings)
    if not policy.is_active():
        console.print("[red]Email channel is killed or disabled.[/red]")
        raise typer.Exit(code=1)
    args = {"mode": "new", "to": to, "subject": subject, "body": body}
    if not _email_send_approver(args):
        raise typer.Exit(code=1)
    from ribhus.channels.gmail_web.sender import GmailSender

    async def _run() -> None:
        sender = GmailSender(session)
        try:
            policy.assert_can_send(args["to"], args["subject"], args["body"])
            await sender.send_new(
                to=str(args["to"]),
                subject=str(args["subject"]),
                body=str(args["body"]),
            )
            policy.record_send(str(args["to"]), str(args["subject"]))
            console.print(f"[green]Sent[/green] to {args['to']}")
        finally:
            await _close_gmail(session)

    try:
        asyncio.run(_run())
    except Exception as extra:  # noqa: BLE001
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra


@email_app.command("resume")
def email_resume() -> None:
    """Clear the kill switch. Sends still require approval."""
    settings = get_settings()
    _session, policy = _email_runtime(settings)
    policy.resume()
    if not settings.email_enabled:
        console.print(
            "[yellow]Kill file cleared, but RIBHUS_EMAIL_ENABLED=false "
            "still disables the channel.[/yellow]"
        )
        return
    console.print(
        "[green]Email/Gmail channel resumed.[/green] "
        "Sends still require explicit approve / edit / cancel."
    )


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


@memory_app.command("forget")
def memory_forget(
    target: str = typer.Argument(..., help="Memory id or semantic key (e.g. football_club)"),
) -> None:
    """Forget a memory by id or semantic key."""
    memory = _memory_service()
    try:
        msg = memory.forget(target)
    except (FileNotFoundError, ValueError) as extra:
        console.print(f"[red]{extra}[/red]")
        raise typer.Exit(code=1) from extra
    console.print(f"[green]{msg}[/green]")


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Full-text search query"),
    kind: str | None = typer.Option(
        None, "--kind", "-k", help="short_term, episodic, or semantic"
    ),
) -> None:
    """Search memories with FTS5 (falls back to substring match)."""
    memory = _memory_service()
    if kind is not None and kind not in KINDS:
        console.print(f"[red]Unknown kind: {kind}. Use {', '.join(KINDS)}[/red]")
        raise typer.Exit(code=1)
    if not memory.enabled:
        console.print("[yellow]Memory is disabled — search returns nothing until enabled.[/yellow]")
    hits = memory.search(query, kind=kind)  # type: ignore[arg-type]
    if not hits:
        console.print(f"No memories matched {query!r}.")
        return
    for record in hits:
        _print_memory(record)


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


@whatsapp_app.command("listen")
def whatsapp_listen() -> None:
    """Poll Note to Self / Message yourself; run each new message as a Ribhus query.

    Full answer prints in this terminal; a short [Ribhus] reply goes back on WhatsApp.
    Ctrl+C to stop. Kill switch: `ribhus whatsapp kill`.
    """
    settings = get_settings()
    try:
        asyncio.run(_whatsapp_listen_async())
    except KeyboardInterrupt:
        console.print("\n[dim]WhatsApp inbox listen stopped.[/dim]")
    finally:
        # Sync fallback: asyncio cancel can skip async closes mid-flight.
        try:
            from ribhus.channels.browser_cleanup import force_release_ribhus_browsers

            force_release_ribhus_browsers(settings.ribhus_dir)
        except Exception:  # noqa: BLE001
            pass


async def _whatsapp_listen_async() -> None:
    from ribhus.channels.browser_cleanup import force_release_ribhus_browsers
    from ribhus.channels.whatsapp_web.inbox import (
        INBOX_QUERY_PREFIX,
        InboxCursorStore,
        open_note_to_self,
        run_listen_loop,
        wait_for_inbox_approval,
    )
    from ribhus.channels.whatsapp_web.navigator import WhatsAppNavigator
    from ribhus.channels.whatsapp_web.reader import WhatsAppReader
    from ribhus.channels.whatsapp_web.sender import WhatsAppSender

    settings = get_settings()
    # Drop Chromium left by a previous Ctrl+C / crashed listen before launching.
    stale = force_release_ribhus_browsers(settings.ribhus_dir)
    if stale:
        console.print(
            f"[dim]Cleared {stale} stale browser process(es) from prior session.[/dim]"
        )

    whatsapp, wa_policy = _whatsapp_runtime(settings)
    if wa_policy.is_killed():
        console.print(
            "[red]WhatsApp channel is stopped. "
            "Resume with `ribhus whatsapp resume` first.[/red]"
        )
        raise typer.Exit(code=1)

    navigator = WhatsAppNavigator(whatsapp)
    reader = WhatsAppReader(whatsapp)
    sender = WhatsAppSender(whatsapp)
    cursor = InboxCursorStore(settings.ribhus_dir / "whatsapp_inbox_cursor.json")

    browser = None
    gmail = None
    email_policy = None
    memory = None
    todo_store = None
    sticky_skills: list[str] = []
    chat_history: list[dict[str, Any]] = []
    last_tools = None
    mcp_manager = await _ensure_mcp(settings, None)

    def status(msg: str) -> None:
        console.print(f"[cyan]inbox[/cyan] {msg}")

    async def listen_approver(
        name: str, risk: RiskLevel, arguments: dict[str, Any]
    ) -> bool:
        # Always mirror the draft in the terminal; decide on WhatsApp Note to Self.
        if name == "whatsapp_send":
            contact = str(arguments.get("contact") or "").strip() or "(unknown)"
            draft = str(arguments.get("message") or "")
            console.print()
            console.print(
                Panel(
                    f"[bold]{CHANNEL_LABEL}[/bold]\n"
                    f"To: [cyan]{contact}[/cyan]\n\n"
                    f"[bold]Draft[/bold]\n{draft}\n\n"
                    "[yellow]Approve on WhatsApp Note to Self:[/yellow]\n"
                    "reply [bold]approve[/bold] / [bold]cancel[/bold] / "
                    "[bold]edit: …[/bold]",
                    title="WhatsApp send — approval required",
                    border_style="yellow",
                )
            )
        elif name == "email_send":
            to = str(arguments.get("to") or "(unknown)").strip()
            subject = str(arguments.get("subject") or "").strip()
            body = str(arguments.get("body") or "")
            console.print()
            console.print(
                Panel(
                    f"[bold]{EMAIL_CHANNEL_LABEL}[/bold]\n"
                    f"To: [cyan]{to}[/cyan]\n"
                    f"Subject: [cyan]{subject}[/cyan]\n\n"
                    f"[bold]Body[/bold]\n{body}\n\n"
                    "[yellow]Approve on WhatsApp Note to Self:[/yellow]\n"
                    "reply [bold]approve[/bold] / [bold]cancel[/bold] / "
                    "[bold]edit: …[/bold]",
                    title="Gmail send — approval required",
                    border_style="yellow",
                )
            )
        else:
            console.print()
            console.print(
                Panel(
                    f"[bold]{name}[/bold]  risk=[yellow]{risk.value}[/yellow]\n"
                    f"{json.dumps(arguments, indent=2, default=str)}\n\n"
                    "[yellow]Approve on WhatsApp Note to Self "
                    "(approve / cancel).[/yellow]",
                    title="Approval required",
                    border_style="yellow",
                )
            )

        try:
            return await wait_for_inbox_approval(
                navigator=navigator,
                reader=reader,
                sender=sender,
                policy=wa_policy,
                cursor=cursor,
                tool_name=name,
                arguments=arguments,
                inbox_chat=settings.whatsapp_inbox_chat or None,
                timeout=300.0,
                on_status=status,
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]WhatsApp approval failed: {exc}[/red]")
            console.print("[yellow]Falling back to CLI approval…[/yellow]")
            return _cli_approver(name, risk, arguments)

    async def on_query(text: str) -> str:
        nonlocal browser, gmail, email_policy, memory, todo_store, mcp_manager
        nonlocal sticky_skills, chat_history, last_tools
        from ribhus.skills.travel_handoff import looks_travel_handoff

        prompt = text if text.startswith("[Via WhatsApp") else INBOX_QUERY_PREFIX + text

        if (
            looks_travel_handoff(text)
            and "travel" in sticky_skills
            and browser is not None
            and not browser.headed
            and browser.page is not None
        ):
            await browser.close()
            browser = None

        agent = None
        try:
            (
                agent,
                browser,
                whatsapp_sess,
                _wa_pol,
                gmail,
                email_policy,
                matched,
                memory,
                todo_store,
                mcp_manager,
            ) = _build_runtime(
                settings,
                prompt=prompt,
                browser=browser,
                whatsapp=whatsapp,
                wa_policy=wa_policy,
                gmail=gmail,
                email_policy=email_policy,
                memory=memory,
                todo_store=todo_store,
                mcp_manager=mcp_manager,
                sticky_skills=sticky_skills,
                approver=listen_approver,
            )
            _ = whatsapp_sess
            last_tools = agent.tools
            if matched:
                sticky_skills = [s.name for s in matched]
                names = ", ".join(sticky_skills)
                console.print(f"[magenta]✦ using skill: {names}[/magenta]")
            state = await agent.run(prompt, history=chat_history or None)
            chat_history = state.history_messages()
            answer = state.final_text or ""
            _print_answer(answer)
            return answer
        finally:
            if agent is not None:
                await _cleanup_processes(agent.tools)

    console.print(
        Panel(
            f"[bold]WhatsApp inbox listen[/bold]\n\n"
            f"Chat: Note to Self / Message yourself"
            + (
                f" (override: {settings.whatsapp_inbox_chat})"
                if settings.whatsapp_inbox_chat
                else ""
            )
            + "\n"
            f"Poll every {settings.whatsapp_listen_interval:g}s. "
            "New messages become Ribhus queries.\n"
            "Full answer here; short [Ribhus] reply on WhatsApp.\n"
            "Send approvals: reply [bold]approve[/bold] / [bold]cancel[/bold] / "
            "[bold]edit:…[/bold] on Note to Self.\n"
            "Ctrl+C to stop · `ribhus whatsapp kill` to halt the channel.",
            border_style="green",
        )
    )

    def on_wa_status(message: str) -> None:
        console.print(f"[yellow]{message}[/yellow]")

    async def _safe_close(label: str, coro) -> None:
        try:
            await coro
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception as exc:  # noqa: BLE001
            console.print(f"[dim]cleanup {label}: {exc}[/dim]")

    try:
        await whatsapp.ensure_logged_in(on_status=on_wa_status)
        await run_listen_loop(
            navigator=navigator,
            reader=reader,
            sender=sender,
            policy=wa_policy,
            cursor=cursor,
            on_query=on_query,
            inbox_chat=settings.whatsapp_inbox_chat or None,
            interval=settings.whatsapp_listen_interval,
            reply_max=settings.whatsapp_inbox_reply_max,
            on_status=status,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        # Close each resource independently — one CancelledError must not skip the rest.
        await _safe_close("processes", _cleanup_processes(last_tools))
        await _safe_close("mcp", _cleanup_mcp(mcp_manager))
        if browser is not None:
            await _safe_close("browser", browser.close())
            browser = None
        await _safe_close("whatsapp", whatsapp.close())
        if gmail is not None:
            await _safe_close("gmail", _close_gmail(gmail))
            gmail = None
        try:
            force_release_ribhus_browsers(settings.ribhus_dir)
        except Exception:  # noqa: BLE001
            pass


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

    try:
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
    except KeyboardInterrupt:
        _say_bye(leading_newline=True)


if __name__ == "__main__":
    run()
