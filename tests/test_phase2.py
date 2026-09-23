from __future__ import annotations

import pytest

from ribhus.policy.audit import AuditLog
from ribhus.policy.engine import PolicyEngine
from ribhus.policy.levels import RiskLevel
from ribhus.tools.browser import BrowserSession, BrowserTool, DomainNotAllowed
from ribhus.tools.filesystem import WriteFileTool
from ribhus.tools.registry import ToolRegistry, default_registry


def test_risk_levels_order():
    assert RiskLevel.LOW.rank < RiskLevel.MEDIUM.rank
    assert RiskLevel.HIGH.rank < RiskLevel.CRITICAL.rank


@pytest.mark.asyncio
async def test_policy_blocks_without_approver():
    policy = PolicyEngine(auto_approve=False, approve_at_or_above=RiskLevel.HIGH)
    tool = WriteFileTool(workspace=__import__("pathlib").Path("."))
    tool.risk_level = RiskLevel.HIGH.value
    allowed, msg = await policy.authorize(tool, {"path": "x", "content": "y"})
    assert not allowed
    assert msg and "approval" in msg.lower()


@pytest.mark.asyncio
async def test_policy_approver_yes():
    policy = PolicyEngine(
        auto_approve=False,
        approve_at_or_above=RiskLevel.HIGH,
        approver=lambda n, r, a: True,
    )
    tool = WriteFileTool(workspace=__import__("pathlib").Path("."))
    tool.risk_level = RiskLevel.HIGH.value
    allowed, msg = await policy.authorize(tool, {"path": "x", "content": "y"})
    assert allowed
    assert msg is None


@pytest.mark.asyncio
async def test_registry_denies_and_audits(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    policy = PolicyEngine(auto_approve=False, approve_at_or_above=RiskLevel.HIGH)
    registry = ToolRegistry(policy=policy, audit=audit)
    tool = WriteFileTool(workspace=tmp_path)
    tool.risk_level = RiskLevel.HIGH.value
    registry.register(tool)

    result = await registry.execute("write_file", {"path": "a.txt", "content": "hi"})
    assert "Denied" in result or "approval" in result.lower()
    assert (tmp_path / "audit.jsonl").exists()
    line = (tmp_path / "audit.jsonl").read_text().strip()
    assert "write_file" in line
    assert "false" in line


def test_domain_allowlist():
    session = BrowserSession(
        user_data_dir=__import__("pathlib").Path("/tmp/ribhus-test-browser"),
        allowlist=["example.com"],
    )
    session.check_url("https://www.example.com/pricing")
    with pytest.raises(DomainNotAllowed):
        session.check_url("https://evil.test/x")


def test_browser_risk_by_action(tmp_path):
    session = BrowserSession(user_data_dir=tmp_path / "profile")
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")
    assert tool.risk_for_arguments({"action": "read"}) == RiskLevel.MEDIUM
    assert tool.risk_for_arguments({"action": "click"}) == RiskLevel.HIGH
    assert tool.risk_for_arguments({"action": "type"}) == RiskLevel.HIGH
    assert tool.risk_for_arguments({"action": "press"}) == RiskLevel.HIGH
    assert tool.risk_for_arguments({"action": "status"}) == RiskLevel.LOW


def test_default_registry_includes_browser(tmp_path):
    session = BrowserSession(user_data_dir=tmp_path / "profile")
    registry = default_registry(tmp_path, browser_session=session)
    assert "browser" in registry.names()


@pytest.mark.asyncio
async def test_browser_open_read_example(tmp_path):
    pytest.importorskip("playwright")
    session = BrowserSession(user_data_dir=tmp_path / "profile", headed=False)
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")
    try:
        opened = await tool.execute({"action": "open", "url": "https://example.com"})
        if "Executable doesn't exist" in opened or "Chromium is not installed" in opened:
            pytest.skip("Playwright Chromium not installed")
        assert "Opened" in opened or "example" in opened.lower()
        read = await tool.execute({"action": "read"})
        assert "Example Domain" in read or "example" in read.lower()
    finally:
        await session.close()
