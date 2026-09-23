from __future__ import annotations

from pathlib import Path

import pytest

from ribhus.tools.browser import BrowserSession, BrowserTool
from ribhus.tools.browser_snapshot import format_snapshot, normalize_ref


def test_normalize_ref():
    assert normalize_ref("@e3") == "e3"
    assert normalize_ref("e3") == "e3"
    assert normalize_ref("3") == "e3"
    assert normalize_ref("") is None
    assert normalize_ref("btn") is None


def test_format_snapshot_lists_refs():
    text = format_snapshot(
        {
            "url": "https://example.com",
            "title": "Example",
            "items": [
                {"ref": "e1", "role": "link", "name": "More information"},
                {"ref": "e2", "role": "button", "name": "OK"},
            ],
        }
    )
    assert "@e1" in text
    assert "[link]" in text
    assert "More information" in text


def test_browser_risk_includes_new_actions(tmp_path: Path):
    from ribhus.policy.levels import RiskLevel

    session = BrowserSession(user_data_dir=tmp_path / "profile")
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")
    assert tool.risk_for_arguments({"action": "press"}) == RiskLevel.HIGH
    assert tool.risk_for_arguments({"action": "select"}) == RiskLevel.HIGH
    assert tool.risk_for_arguments({"action": "console"}) == RiskLevel.HIGH
    assert tool.risk_for_arguments({"action": "wait"}) == RiskLevel.LOW
    assert tool.risk_for_arguments({"action": "hover"}) == RiskLevel.MEDIUM
    assert tool.risk_for_arguments({"action": "reload"}) == RiskLevel.MEDIUM
    assert tool.risk_for_arguments({"action": "snapshot"}) == RiskLevel.MEDIUM
    assert tool.risk_for_arguments({"action": "status"}) == RiskLevel.LOW
    assert tool.risk_for_arguments({"action": "connect"}) == RiskLevel.MEDIUM


def test_browser_schema_includes_tier1(tmp_path: Path):
    session = BrowserSession(user_data_dir=tmp_path / "profile")
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")
    enum = tool.input_schema()["properties"]["action"]["enum"]
    for action in ("wait", "select", "hover", "reload"):
        assert action in enum


@pytest.mark.asyncio
async def test_browser_status_before_start(tmp_path: Path):
    session = BrowserSession(user_data_dir=tmp_path / "profile")
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")
    result = await tool.execute({"action": "status"})
    assert "started=False" in result
    assert "cdp_mode=False" in result


@pytest.mark.asyncio
async def test_snapshot_click_press_on_fixture(tmp_path: Path):
    pytest.importorskip("playwright")
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
      <h1>Demo</h1>
      <a href="#more">More information</a>
      <input id="q" placeholder="Search" />
      <button id="go" type="button">Go</button>
      <div id="out"></div>
      <script>
        document.getElementById('go').onclick = () => {
          document.getElementById('out').textContent =
            'ok:' + document.getElementById('q').value;
        };
      </script>
    </body></html>
    """
    session = BrowserSession(user_data_dir=tmp_path / "profile", headed=False)
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Playwright Chromium not installed")
            raise
        # Use tool session's own page via injecting through ensure after we
        # hijack by launching through the tool's local path — set_content on
        # the session page instead.
        await browser.close()

    try:
        page = await session.ensure()
        await page.set_content(html)
        snap = await tool.execute({"action": "snapshot"})
        assert "@e" in snap
        assert "More information" in snap or "Search" in snap or "Go" in snap

        # Find a textbox / button ref from the stamp payload
        from ribhus.tools.browser_snapshot import stamp_interactive

        stamped = await stamp_interactive(page)
        refs = {i["ref"]: i for i in stamped["items"]}
        textbox = next(
            (r for r, i in refs.items() if i.get("role") in {"textbox", "searchbox"}),
            None,
        )
        button = next(
            (r for r, i in refs.items() if i.get("role") == "button"),
            None,
        )
        assert textbox and button

        typed = await tool.execute(
            {"action": "type", "ref": f"@{textbox}", "text": "ribhus"}
        )
        assert "Typed" in typed
        clicked = await tool.execute({"action": "click", "ref": f"@{button}"})
        assert "Clicked" in clicked
        assert "Interactive elements" in clicked  # auto re-snapshot
        out = await page.inner_text("#out")
        assert "ok:ribhus" in out

        pressed = await tool.execute({"action": "press", "key": "Tab"})
        assert "Pressed Tab" in pressed

        evaluated = await tool.execute(
            {"action": "console", "expression": "document.title"}
        )
        assert "console eval" in evaluated

        dialog = await tool.execute({"action": "dialog", "dialog_action": "accept"})
        assert "ACCEPT" in dialog
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_tier1_wait_select_hover_reload_iframe(tmp_path: Path):
    pytest.importorskip("playwright")
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
      <h1>Tier1</h1>
      <select id="city">
        <option value="">Pick</option>
        <option value="bom">Mumbai</option>
        <option value="del">Delhi</option>
      </select>
      <div id="menu" style="display:none">Hover menu</div>
      <button id="hov">Hover me</button>
      <div id="late"></div>
      <iframe id="pay" srcdoc='
        <button id="paybtn">Pay now</button>
        <span id="paid"></span>
        <script>
          document.getElementById("paybtn").onclick = () => {
            document.getElementById("paid").textContent = "paid";
          };
        </script>
      '></iframe>
      <script>
        document.getElementById('hov').onmouseenter = () => {
          document.getElementById('menu').style.display = 'block';
        };
        setTimeout(() => {
          document.getElementById('late').textContent = 'Ready now';
        }, 400);
      </script>
    </body></html>
    """
    session = BrowserSession(user_data_dir=tmp_path / "profile", headed=False)
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Playwright Chromium not installed")
            raise
        await browser.close()

    try:
        page = await session.ensure()
        await page.set_content(html)
        await page.frame_locator("iframe#pay").locator("#paybtn").wait_for(
            state="attached", timeout=5_000
        )

        waited = await tool.execute(
            {"action": "wait", "until": "text", "text": "Ready now", "timeout": 5000}
        )
        assert "Waited for text" in waited
        assert "Interactive elements" in waited

        snap = await tool.execute({"action": "snapshot"})
        assert "(iframe)" in snap or "Pay now" in snap

        from ribhus.tools.browser_snapshot import stamp_interactive

        stamped = await stamp_interactive(page)
        refs = {i["ref"]: i for i in stamped["items"]}
        select_ref = next(
            (
                r
                for r, i in refs.items()
                if i.get("tag") == "select" or i.get("role") == "combobox"
            ),
            None,
        )
        hover_ref = next(
            (r for r, i in refs.items() if "Hover me" in (i.get("name") or "")),
            None,
        )
        iframe_btn = next(
            (
                r
                for r, i in refs.items()
                if i.get("iframe") and "Pay" in (i.get("name") or "")
            ),
            None,
        )
        assert select_ref
        assert hover_ref
        assert iframe_btn, f"iframe button missing from stamp: {stamped['items']}"

        selected = await tool.execute(
            {
                "action": "select",
                "ref": f"@{select_ref}",
                "text": "Mumbai",
                "resnapshot": False,
            }
        )
        assert "Selected" in selected
        value = await page.locator("#city").input_value()
        assert value == "bom"

        hovered = await tool.execute(
            {"action": "hover", "ref": f"@{hover_ref}", "resnapshot": False}
        )
        assert "Hovered" in hovered
        assert await page.is_visible("#menu")

        clicked = await tool.execute(
            {"action": "click", "ref": f"@{iframe_btn}", "resnapshot": False}
        )
        assert "Clicked" in clicked
        paid = await page.frame_locator("iframe#pay").locator("#paid").inner_text()
        assert "paid" in paid

        reloaded = await tool.execute({"action": "reload", "resnapshot": False})
        assert "Reloaded" in reloaded
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_connect_missing_url(tmp_path: Path):
    session = BrowserSession(user_data_dir=tmp_path / "profile")
    tool = BrowserTool(session=session, screenshot_dir=tmp_path / "shots")
    result = await tool.execute({"action": "connect"})
    assert result.startswith("Error:")
    assert "9222" in result or "CDP" in result or "url" in result.lower()
