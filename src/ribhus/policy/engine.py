from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ribhus.policy.levels import RiskLevel

Approver = Callable[[str, RiskLevel, dict[str, Any]], Awaitable[bool] | bool]


class RiskAware(Protocol):
    name: str
    risk_level: str


class PolicyEngine:
    """Decides whether a tool call needs human approval before running."""

    def __init__(
        self,
        *,
        auto_approve: bool = False,
        approve_at_or_above: RiskLevel = RiskLevel.HIGH,
        approver: Approver | None = None,
    ) -> None:
        self.auto_approve = auto_approve
        self.approve_at_or_above = approve_at_or_above
        self.approver = approver

    def requires_approval(self, tool: RiskAware) -> bool:
        if getattr(tool, "force_approval", False):
            return True
        if self.auto_approve:
            return False
        risk = RiskLevel.parse(getattr(tool, "risk_level", RiskLevel.LOW))
        return risk.rank >= self.approve_at_or_above.rank

    async def authorize(
        self,
        tool: RiskAware,
        arguments: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Return (allowed, denial_message)."""
        if not self.requires_approval(tool):
            return True, None

        risk = RiskLevel.parse(tool.risk_level)
        if self.approver is None:
            if getattr(tool, "force_approval", False):
                return (
                    False,
                    f"Blocked: {tool.name} always requires explicit approval "
                    "and cannot be auto-approved.",
                )
            return (
                False,
                f"Blocked: {tool.name} is {risk.value} risk and requires approval, "
                "but no approver is configured. Re-run in the CLI or set "
                "RIBHUS_AUTO_APPROVE=true (unsafe).",
            )

        decision = self.approver(tool.name, risk, arguments)
        if isinstance(decision, Awaitable):
            allowed = await decision
        else:
            allowed = decision

        if allowed:
            return True, None
        return False, f"User denied {risk.value}-risk tool '{tool.name}'."
