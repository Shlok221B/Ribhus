"""Run agent tasks for the dashboard with web-based approvals."""

from __future__ import annotations

import asyncio
from typing import Any

from ribhus.agent.loop import Agent
from ribhus.channels.gmail_web.policy import EmailPolicy
from ribhus.channels.gmail_web.session import GmailSession
from ribhus.channels.whatsapp_web.policy import WhatsAppPolicy
from ribhus.channels.whatsapp_web.session import WhatsAppSession
from ribhus.config import get_settings
from ribhus.mcp.manager import McpManager, start_mcp_manager
from ribhus.memory.service import MemoryService
from ribhus.models.openai_compatible import OpenAICompatibleModel
from ribhus.policy.audit import AuditLog
from ribhus.policy.engine import PolicyEngine
from ribhus.policy.levels import RiskLevel
from ribhus.skills.registry import SkillRegistry
from ribhus.tools.browser import BrowserSession
from ribhus.tools.location import enrich_answer_with_place_links
from ribhus.tools.registry import default_registry
from ribhus.tools.todo import TodoStore
from ribhus.web.task_store import TaskStore


def _make_web_approver(store: TaskStore, task_id: str):
    def approver(name: str, risk: RiskLevel, arguments: dict[str, Any]) -> bool:
        approval_id, _event = store.begin_approval(
            task_id,
            tool=name,
            risk=risk.value,
            arguments=arguments,
        )
        store.add_event(
            task_id,
            "approval_requested",
            {"tool": name, "risk": risk.value, "approval_id": approval_id},
        )
        decision, edited = store.wait_approval_result(approval_id)
        if decision == "edit" and edited is not None:
            if name == "whatsapp_send":
                arguments["message"] = edited
            elif name == "email_send":
                arguments["body"] = edited
            store.add_event(task_id, "approval_edited", {"tool": name})
            return True
        allowed = decision == "approve"
        store.add_event(
            task_id,
            "approval_resolved",
            {"tool": name, "allowed": allowed, "decision": decision},
        )
        return allowed

    return approver


async def run_task(store: TaskStore, task_id: str) -> None:
    task = store.get(task_id)
    if task is None:
        return
    prompt = task.prompt
    settings = get_settings()
    store.update(task_id, status="running")
    store.add_event(task_id, "started", {})

    browser: BrowserSession | None = None
    whatsapp: WhatsAppSession | None = None
    gmail: GmailSession | None = None
    memory: MemoryService | None = None
    mcp_manager: McpManager | None = None

    async def on_event(event: str, data: dict[str, Any]) -> None:
        preview = dict(data)
        # Keep payloads small for the UI.
        for key in ("text", "addon_preview", "result"):
            if key in preview and isinstance(preview[key], str):
                preview[key] = preview[key][:500]
        store.add_event(task_id, event, preview)

    try:
        model = OpenAICompatibleModel(settings)
        policy = PolicyEngine(
            auto_approve=settings.auto_approve,
            approve_at_or_above=settings.approve_at_level,
            approver=_make_web_approver(store, task_id),
        )
        audit = AuditLog(settings.ribhus_dir / "audit.jsonl")
        browser = BrowserSession(
            user_data_dir=settings.ribhus_dir / "browser_profile",
            headed=settings.browser_headed,
            allowlist=settings.browser_allowlist_hosts,
            rate_limit_per_minute=settings.browser_rate_limit,
            cdp_url=settings.browser_cdp_url or None,
        )
        whatsapp = WhatsAppSession(
            user_data_dir=settings.ribhus_dir / "whatsapp_profile",
            headed=settings.whatsapp_headed,
            login_timeout=settings.whatsapp_login_timeout,
        )
        wa_policy = WhatsAppPolicy(
            enabled=settings.whatsapp_enabled,
            kill_path=settings.ribhus_dir / "whatsapp.killed",
            sends_per_minute=settings.whatsapp_rate_limit,
            sends_per_hour=settings.whatsapp_max_per_hour,
            cooldown_seconds=settings.whatsapp_cooldown,
        )
        gmail = GmailSession(
            user_data_dir=settings.ribhus_dir / "gmail_profile",
            headed=settings.email_headed,
            login_timeout=settings.email_login_timeout,
        )
        email_policy = EmailPolicy(
            enabled=settings.email_enabled,
            kill_path=settings.ribhus_dir / "email.killed",
            sends_per_minute=settings.email_rate_limit,
            sends_per_hour=settings.email_max_per_hour,
            cooldown_seconds=settings.email_cooldown,
        )
        memory = MemoryService.from_path(
            settings.ribhus_dir / "memory.sqlite",
            env_enabled=settings.memory_enabled,
        )
        todo_store = TodoStore()
        config_path = None
        if settings.mcp_config.strip():
            from pathlib import Path

            config_path = Path(settings.mcp_config.strip())
        mcp_manager = await start_mcp_manager(
            settings.workspace,
            enabled=settings.mcp_enabled,
            config_path=config_path,
        )
        tools = default_registry(
            settings.workspace,
            policy=policy,
            audit=audit,
            browser_session=browser,
            screenshot_dir=settings.ribhus_dir / "screenshots",
            whatsapp_session=whatsapp,
            whatsapp_policy=wa_policy,
            memory=memory,
            clarify_asker=None,
            todo_store=todo_store,
            mcp_manager=mcp_manager,
            vision_api_key=settings.api_key or None,
            vision_base_url=settings.base_url,
            vision_model=settings.effective_vision_model,
            gmail_session=gmail,
            email_policy=email_policy,
        )
        skills = SkillRegistry.load_default(settings.workspace)
        matched = skills.match(prompt)
        skill_names = [s.name for s in matched]
        if "travel" in skill_names and not browser.headed and browser.page is None:
            browser.headed = True
        agent = Agent(
            model=model,
            tools=tools,
            max_iterations=settings.max_iterations,
            on_event=on_event,
            skill_prompt_addon=skills.prompt_addon(prompt),
            skill_names=skill_names,
            memory=memory,
            todo_store=todo_store,
        )
        store.update(task_id, skills=skill_names)
        # Approver blocks on a thread Event — run agent in a worker thread
        # so the FastAPI event loop stays responsive for approval POSTs.
        state = await asyncio.to_thread(_run_agent_sync, agent, prompt)
        final = enrich_answer_with_place_links(
            (state.final_text or "").strip(),
            messages=list(getattr(state, "messages", []) or []),
        )
        store.update(
            task_id,
            status="completed",
            result=final,
            pending_approval=None,
        )
        store.add_event(task_id, "done", {"text": final[:500]})
    except Exception as exc:  # noqa: BLE001 — surface to UI
        store.update(
            task_id,
            status="failed",
            error=str(exc),
            pending_approval=None,
        )
        store.add_event(task_id, "error", {"message": str(exc)})
    finally:
        if memory is not None:
            memory.close()
        if mcp_manager is not None:
            await mcp_manager.close()
        if browser is not None:
            await browser.close()
        if whatsapp is not None:
            await whatsapp.close()
        if gmail is not None:
            await gmail.close()


def _run_agent_sync(agent: Agent, prompt: str):
    """Run the async agent from a worker thread."""
    return asyncio.run(agent.run(prompt))
