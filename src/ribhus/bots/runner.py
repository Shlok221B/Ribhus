"""Run agent turns for bots: direct chats, groups, and handoffs."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ribhus.agent.loop import Agent
from ribhus.bots.attachments import enrich_prompt_with_uploads
from ribhus.bots.chat_store import ChatStore, parse_mentions
from ribhus.bots.message_tool import MAX_HANDOFF_HOPS, MessageBotTool
from ribhus.bots.queue import BotJob, BotQueueManager
from ribhus.bots.store import BotStore
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

_PASS_RE = re.compile(
    r"^\s*(pass|no\s+comment|nothing\s+to\s+add|skip)\s*\.?\s*$",
    re.IGNORECASE,
)

GROUP_MAX_ROUNDS = 3
GROUP_MAX_POSTS_PER_BOT = 2


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
            "approval.requested",
            {"tool": name, "risk": risk.value, "approval_id": approval_id},
        )
        decision, edited = store.wait_approval_result(approval_id)
        if decision == "edit" and edited is not None:
            if name == "whatsapp_send":
                arguments["message"] = edited
            elif name == "email_send":
                arguments["body"] = edited
            store.add_event(
                task_id,
                "approval.resolved",
                {"tool": name, "allowed": True, "decision": "edit"},
            )
            return True
        allowed = decision == "approve"
        store.add_event(
            task_id,
            "approval.resolved",
            {"tool": name, "allowed": allowed, "decision": decision},
        )
        return allowed

    return approver


class BotOrchestrator:
    """Coordinates bot queues, chats, tasks, and the existing Agent loop."""

    def __init__(
        self,
        *,
        bots: BotStore,
        chats: ChatStore,
        tasks: TaskStore,
        queues: BotQueueManager | None = None,
    ) -> None:
        self.bots = bots
        self.chats = chats
        self.tasks = tasks
        self.queues = queues or BotQueueManager()
        self.queues.set_handler(self._handle_job)

    def ensure_direct_chats(self) -> None:
        for bot in self.bots.list():
            self.chats.direct_for_bot(bot.id, bot_name=bot.name)

    def enqueue_user_message(
        self,
        chat_id: str,
        text: str,
    ) -> dict[str, Any]:
        chat = self.chats.get(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        prompt = text.strip()
        if not prompt:
            raise ValueError("message is empty")
        # Inline PDF/DOCX/text uploads into the agent prompt (chat bubble stays short).
        agent_prompt = enrich_prompt_with_uploads(
            prompt, get_settings().workspace
        )

        if chat.kind == "direct":
            bot_id = chat.bot_ids[0]
            bot = self.bots.get(bot_id)
            msg = self.chats.append_message(
                chat_id, role="user", content=prompt
            )
            task = self.tasks.create(
                agent_prompt,
                chat_id=chat_id,
                bot_id=bot_id,
            )
            if msg is not None:
                self.chats.set_message_task(chat_id, msg.id, task.id)
            self.bots.set_status(bot_id, "working")
            self.queues.enqueue(
                BotJob(
                    kind="user",
                    chat_id=chat_id,
                    bot_id=bot_id,
                    prompt=agent_prompt,
                    task_id=task.id,
                    message_id=msg.id if msg else None,
                )
            )
            return {
                "chat": self.chats.get(chat_id).to_dict() if self.chats.get(chat_id) else None,
                "task": task.to_dict(),
                "bot": bot.to_dict() if bot else None,
            }

        # Group: host schedules speakers.
        name_map = {
            b.name.lower(): b.id for b in self.bots.list() if b.id in chat.bot_ids
        }
        mentions = parse_mentions(prompt, name_map)
        # Restrict mentions to group members.
        mentions = [m for m in mentions if m in chat.bot_ids]
        msg = self.chats.append_message(
            chat_id,
            role="user",
            content=prompt,
            mention_bot_ids=mentions,
        )
        speakers = mentions if mentions else list(chat.bot_ids)
        first_task = None
        for bot_id in speakers:
            task = self.tasks.create(
                agent_prompt,
                chat_id=chat_id,
                bot_id=bot_id,
            )
            if first_task is None:
                first_task = task
                if msg is not None:
                    self.chats.set_message_task(chat_id, msg.id, task.id)
            self.bots.set_status(bot_id, "working")
            self.queues.enqueue(
                BotJob(
                    kind="group",
                    chat_id=chat_id,
                    bot_id=bot_id,
                    prompt=agent_prompt,
                    task_id=task.id,
                    speak_or_pass=not bool(mentions),
                    group_round=1,
                    meta={
                        "posts_this_user_msg": 0,
                        "speakers": speakers,
                        "max_rounds": GROUP_MAX_ROUNDS,
                    },
                )
            )
        return {
            "chat": self.chats.get(chat_id).to_dict() if self.chats.get(chat_id) else None,
            "task": first_task.to_dict() if first_task else None,
            "speakers": speakers,
        }

    def enqueue_handoff(self, payload: dict[str, Any]) -> str:
        to_bot_id = str(payload["to_bot_id"])
        to_name = str(payload.get("to_name") or to_bot_id)
        body = str(payload["body"])
        priority = str(payload.get("priority") or "action")
        from_bot_id = str(payload["from_bot_id"])
        from_chat_id = str(payload["from_chat_id"])
        hop = int(payload.get("hop") or 1)
        if hop > MAX_HANDOFF_HOPS:
            return f"Error: handoff hop limit ({MAX_HANDOFF_HOPS}) reached"

        from_bot = self.bots.get(from_bot_id)
        from_name = from_bot.name if from_bot else from_bot_id

        handoff_meta = {
            "from_bot_id": from_bot_id,
            "from_bot_name": from_name,
            "to_bot_id": to_bot_id,
            "to_bot_name": to_name,
            "priority": priority,
            "body": body,
            "hop": hop,
        }
        # Visible card in the sender's chat.
        self.chats.append_message(
            from_chat_id,
            role="handoff",
            content=f"{from_name} → {to_name}: {body}",
            bot_id=from_bot_id,
            bot_name=from_name,
            handoff=handoff_meta,
        )
        # Also note in recipient's direct chat.
        dest_chat = self.chats.direct_for_bot(
            to_bot_id,
            bot_name=to_name,
        )
        self.chats.append_message(
            dest_chat.id,
            role="handoff",
            content=f"{from_name} → {to_name}: {body}",
            bot_id=from_bot_id,
            bot_name=from_name,
            handoff=handoff_meta,
        )

        if priority == "fyi":
            # Soft wake: store note, optional short ack without forcing reply chain.
            self.queues.enqueue(
                BotJob(
                    kind="handoff",
                    chat_id=dest_chat.id,
                    bot_id=to_bot_id,
                    prompt=(
                        f"FYI from {from_name} (no reply expected unless you need a "
                        f"decision):\n{body}\n\n"
                        "Acknowledge silently by remembering anything durable with "
                        "memory_remember if useful. Reply with a single short line "
                        "only if a decision from the user or sender is required; "
                        "otherwise reply exactly: pass."
                    ),
                    from_bot_id=from_bot_id,
                    from_chat_id=from_chat_id,
                    priority="fyi",
                    hop=hop,
                )
            )
            return f"Queued FYI for {to_name}."

        self.bots.set_status(to_bot_id, "working")
        self.queues.enqueue(
            BotJob(
                kind="handoff",
                chat_id=dest_chat.id,
                bot_id=to_bot_id,
                prompt=(
                    f"Handoff from {from_name} (action — do the work, then reply):\n"
                    f"{body}\n\n"
                    f"When finished, put your result in the final answer. "
                    f"Do not message {from_name} back about this same handoff "
                    f"with message_bot unless you must escalate a blocker."
                ),
                from_bot_id=from_bot_id,
                from_chat_id=from_chat_id,
                priority="action",
                hop=hop,
            )
        )
        return f"Queued for {to_name}."

    async def _handle_job(self, job: BotJob) -> None:
        bot = self.bots.get(job.bot_id)
        if bot is None:
            return
        self.bots.set_status(job.bot_id, "working")
        chat = self.chats.get(job.chat_id)
        if chat is None:
            self.bots.set_status(job.bot_id, "idle")
            return

        task_id = job.task_id
        if not task_id:
            task = self.tasks.create(
                job.prompt,
                chat_id=job.chat_id,
                bot_id=job.bot_id,
            )
            task_id = task.id
            self.chats.update(job.chat_id, active_task_id=task_id)

        try:
            final = await self._run_agent_job(job, bot=bot, task_id=task_id)
        except Exception as exc:  # noqa: BLE001
            self.tasks.update(
                task_id,
                status="failed",
                error=str(exc),
                pending_approval=None,
            )
            self.tasks.add_event(task_id, "turn.failed", {"message": str(exc)})
            self.bots.set_status(job.bot_id, "idle")
            return

        text = (final or "").strip()
        is_pass = bool(_PASS_RE.match(text)) if job.speak_or_pass or job.priority == "fyi" else False

        if text and not is_pass:
            self.chats.append_message(
                job.chat_id,
                role="bot" if chat.kind == "group" else "assistant",
                content=text,
                bot_id=bot.id,
                bot_name=bot.name,
                task_id=task_id,
            )
            # Action handoff: also post reply into the sender's chat.
            if (
                job.kind == "handoff"
                and job.priority == "action"
                and job.from_chat_id
                and job.from_chat_id != job.chat_id
            ):
                self.chats.append_message(
                    job.from_chat_id,
                    role="bot",
                    content=text,
                    bot_id=bot.id,
                    bot_name=bot.name,
                    task_id=task_id,
                    handoff={
                        "reply_to": job.from_bot_id,
                        "from_bot_id": bot.id,
                        "from_bot_name": bot.name,
                    },
                )

        if job.kind == "group" and text and not is_pass:
            posts = int(job.meta.get("posts_this_user_msg") or 0) + 1
            job.meta["posts_this_user_msg"] = posts
            # Optional follow-up rounds when everyone was @mentioned / open floor
            # are limited; for v1 we run one pass per speaker per user message.

        self.bots.set_status(job.bot_id, "idle")

    async def _run_agent_job(
        self,
        job: BotJob,
        *,
        bot: Any,
        task_id: str,
    ) -> str:
        chat = self.chats.get(job.chat_id)
        history: list[dict[str, str]] = []
        if chat is not None:
            # Exclude the trailing user message that matches this prompt when present.
            full = chat.history_for_bot(bot.id)
            if full and full[-1].get("role") == "user" and full[-1].get("content") == job.prompt:
                history = full[:-1]
            else:
                history = full

        settings = get_settings()
        self.tasks.update(task_id, status="running")
        self.tasks.add_event(
            task_id,
            "turn.started",
            {"bot_id": bot.id, "bot_name": bot.name, "kind": job.kind},
        )

        browser: BrowserSession | None = None
        whatsapp: WhatsAppSession | None = None
        gmail: GmailSession | None = None
        memory: MemoryService | None = None
        mcp_manager: McpManager | None = None

        async def on_event(event: str, data: dict[str, Any]) -> None:
            preview = dict(data)
            for key in ("text", "addon_preview", "result"):
                if key in preview and isinstance(preview[key], str):
                    preview[key] = preview[key][:500]
            if event == "done":
                return
            self.tasks.add_event(task_id, event, preview)
            if event in {"approval_requested", "approval.requested"}:
                self.bots.set_status(bot.id, "waiting")

        try:
            model = OpenAICompatibleModel(settings)
            policy = PolicyEngine(
                auto_approve=settings.auto_approve,
                approve_at_or_above=settings.approve_at_level,
                approver=_make_web_approver(self.tasks, task_id),
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
                bot_id=bot.id,
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

            def _list_bots() -> list[dict[str, str]]:
                return [
                    {"id": b.id, "name": b.name}
                    for b in self.bots.list()
                    if b.id != bot.id
                ]

            def _enqueue(payload: dict[str, Any]) -> str:
                result = self.enqueue_handoff(payload)
                if not str(result).startswith("Error"):
                    self.tasks.add_event(
                        task_id,
                        "handoff.sent",
                        {
                            "to_bot_id": payload.get("to_bot_id"),
                            "to_name": payload.get("to_name"),
                            "priority": payload.get("priority"),
                            "body_preview": str(payload.get("body") or "")[:500],
                            "hop": payload.get("hop"),
                        },
                    )
                return result

            tools.register(
                MessageBotTool(
                    sender_bot_id=bot.id,
                    sender_chat_id=job.chat_id,
                    hop=job.hop,
                    enqueue=_enqueue,
                    list_bots=_list_bots,
                )
            )

            skills = SkillRegistry.load_default(settings.workspace)
            matched = skills.match(job.prompt)
            skill_names = [s.name for s in matched]
            if "travel" in skill_names and not browser.headed and browser.page is None:
                browser.headed = True

            speak_addon = ""
            if job.speak_or_pass:
                speak_addon = (
                    "\n\n## Group chat\n"
                    "You are in a group with other bots. If you have nothing useful "
                    "to add, reply with exactly: pass\n"
                )

            self.tasks.update(task_id, skills=skill_names, bot_id=bot.id, chat_id=job.chat_id)

            from ribhus.research.entry import maybe_run_deep_research

            research_text = await maybe_run_deep_research(
                job.prompt,
                settings,
                skill_names=skill_names,
                skill_hint=skills.prompt_addon(job.prompt),
                browser=browser,
                task_id=task_id,
                on_event=on_event,
                model=model,
            )
            if research_text is not None:
                final = research_text
            else:
                agent = Agent(
                    model=model,
                    tools=tools,
                    max_iterations=settings.max_iterations,
                    on_event=on_event,
                    skill_prompt_addon=(
                        (bot.job_prompt_addon() or "")
                        + skills.prompt_addon(job.prompt)
                        + speak_addon
                    ),
                    skill_names=skill_names,
                    memory=memory,
                    todo_store=todo_store,
                )
                state = await asyncio.to_thread(
                    _run_agent_sync, agent, job.prompt, history
                )
                final = enrich_answer_with_place_links(
                    (state.final_text or "").strip(),
                    messages=list(getattr(state, "messages", []) or []),
                )
            self.tasks.add_assistant_turn(task_id, final)
            self.tasks.update(
                task_id,
                status="completed",
                result=final,
                error=None,
                pending_approval=None,
            )
            self.tasks.add_event(task_id, "turn.completed", {"text": final[:500]})
            return final
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


def _run_agent_sync(
    agent: Agent,
    prompt: str,
    history: list[dict[str, Any]] | None = None,
):
    return asyncio.run(agent.run(prompt, history=history or None))
