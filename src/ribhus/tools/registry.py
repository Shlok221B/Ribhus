from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.policy.audit import AuditLog
from ribhus.policy.engine import PolicyEngine
from ribhus.policy.levels import RiskLevel
from ribhus.tools.base import Tool


class ToolRegistry:
    def __init__(
        self,
        *,
        policy: PolicyEngine | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.policy = policy or PolicyEngine(auto_approve=True)
        self.audit = audit

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'. Available: {', '.join(self.names())}"

        # Temporarily elevate tool.risk_level for action-dependent tools.
        effective_risk = tool.risk_for_arguments(arguments)
        original_risk = tool.risk_level
        tool.risk_level = effective_risk.value

        approved: bool | None = None
        try:
            blocked = tool.preflight(arguments)
            if blocked:
                if self.audit:
                    self.audit.write(
                        tool=name,
                        risk=effective_risk.value,
                        arguments=arguments,
                        approved=False,
                        result_preview=blocked,
                        ok=False,
                    )
                return blocked

            allowed, denial = await self.policy.authorize(tool, arguments)
            approved = allowed
            if not allowed:
                msg = denial or f"Denied tool '{name}'"
                if self.audit:
                    self.audit.write(
                        tool=name,
                        risk=effective_risk.value,
                        arguments=arguments,
                        approved=False,
                        result_preview=msg,
                        ok=False,
                    )
                return msg

            result = await tool.execute(arguments)
            ok = not result.startswith("Error")
            if self.audit:
                self.audit.write(
                    tool=name,
                    risk=effective_risk.value,
                    arguments=arguments,
                    approved=approved if self.policy.requires_approval(tool) else None,
                    result_preview=result,
                    ok=ok,
                )
            return result
        except Exception as exc:  # noqa: BLE001 — surface tool failures to the model
            msg = f"Error executing {name}: {exc}"
            if self.audit:
                self.audit.write(
                    tool=name,
                    risk=effective_risk.value,
                    arguments=arguments,
                    approved=approved,
                    result_preview=msg,
                    ok=False,
                )
            return msg
        finally:
            tool.risk_level = original_risk


def default_registry(
    workspace: Path,
    *,
    policy: PolicyEngine | None = None,
    audit: AuditLog | None = None,
    browser_session=None,
    screenshot_dir: Path | None = None,
    whatsapp_session=None,
    whatsapp_policy=None,
    memory=None,
    clarify_asker=None,
    todo_store=None,
    mcp_manager=None,
    vision_api_key: str | None = None,
    vision_base_url: str | None = None,
    vision_model: str | None = None,
    gmail_session=None,
    email_policy=None,
) -> ToolRegistry:
    from ribhus.tools.browser import BrowserTool
    from ribhus.tools.clarify import ClarifyTool
    from ribhus.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
    from ribhus.tools.http import HttpRequestTool
    from ribhus.tools.process import make_process_tool
    from ribhus.tools.python_exec import PythonTool
    from ribhus.tools.terminal import TerminalTool
    from ribhus.tools.todo import TodoStore, TodoTool
    from ribhus.tools.vision import VisionTool, analyze_image
    from ribhus.tools.web_extract import WebExtractTool
    from ribhus.tools.web_search import WebSearchTool

    registry = ToolRegistry(policy=policy, audit=audit)
    shots = screenshot_dir or (workspace / ".ribhus" / "screenshots")

    read = ReadFileTool(workspace=workspace)
    read.risk_level = RiskLevel.LOW.value

    write = WriteFileTool(workspace=workspace)
    write.risk_level = RiskLevel.HIGH.value

    edit = EditFileTool(workspace=workspace)
    edit.risk_level = RiskLevel.HIGH.value

    http = HttpRequestTool()
    http.risk_level = RiskLevel.MEDIUM.value

    search = WebSearchTool()
    search.risk_level = RiskLevel.LOW.value

    extract = WebExtractTool()
    extract.risk_level = RiskLevel.LOW.value

    clarify = ClarifyTool(asker=clarify_asker)
    clarify.risk_level = RiskLevel.LOW.value

    todo = TodoTool(store=todo_store or TodoStore())
    todo.risk_level = RiskLevel.LOW.value

    python = PythonTool(workspace=workspace)
    python.risk_level = RiskLevel.HIGH.value

    terminal = TerminalTool(workspace=workspace)
    terminal.risk_level = RiskLevel.HIGH.value

    process = make_process_tool(workspace)
    process.risk_level = RiskLevel.HIGH.value

    tools: list = [
        search,
        extract,
        http,
        read,
        write,
        edit,
        python,
        terminal,
        process,
        clarify,
        todo,
    ]

    vision = None
    if vision_api_key and vision_base_url and vision_model:
        vision = VisionTool(
            workspace=workspace,
            screenshot_dir=shots,
            api_key=vision_api_key,
            base_url=vision_base_url,
            model=vision_model,
        )
        vision.risk_level = RiskLevel.MEDIUM.value
        tools.append(vision)

        async def _vision_analyze(path: Path, question: str) -> str:
            return await analyze_image(
                image_path=path,
                question=question,
                api_key=vision_api_key,
                base_url=vision_base_url,
                model=vision_model,
            )

        vision_cb = _vision_analyze
    else:
        vision_cb = None

    if browser_session is not None:
        tools.append(
            BrowserTool(
                session=browser_session,
                screenshot_dir=shots,
                vision_analyze=vision_cb,
            )
        )

    for tool in tools:
        registry.register(tool)

    if whatsapp_session is not None and whatsapp_policy is not None:
        from ribhus.channels.whatsapp_web.tools import register_whatsapp_tools

        register_whatsapp_tools(
            registry, whatsapp_session, whatsapp_policy, memory=memory
        )

    if memory is not None:
        from ribhus.memory.tools import register_memory_tools

        register_memory_tools(registry, memory)

    if mcp_manager is not None:
        from ribhus.mcp.manager import register_mcp_tools

        register_mcp_tools(registry, mcp_manager)

    if gmail_session is not None and email_policy is not None:
        from ribhus.channels.gmail_web.tools import register_email_tools

        register_email_tools(registry, gmail_session, email_policy)

    return registry
