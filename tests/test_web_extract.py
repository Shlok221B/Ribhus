from __future__ import annotations

import pytest

from ribhus.tools.web_extract import WebExtractTool, html_to_text


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Zoho Corp Brief</title></head>
<body>
  <nav>Home | About | Login</nav>
  <script>window.track=1</script>
  <main>
    <h1>Zoho Corporation</h1>
    <p>Zoho is an Indian software company based in Chennai.</p>
    <p>It offers a suite of business applications.</p>
  </main>
  <footer>Copyright</footer>
</body>
</html>
"""


def test_html_to_text_strips_chrome():
    title, text = html_to_text(SAMPLE_HTML)
    assert title == "Zoho Corp Brief"
    assert "Zoho is an Indian software company" in text
    assert "window.track" not in text
    assert "Home | About" not in text


@pytest.mark.asyncio
async def test_web_extract_blocks_whatsapp():
    tool = WebExtractTool()
    result = await tool.execute({"url": "https://web.whatsapp.com/"})
    assert result.startswith("Error:")
    assert "whatsapp" in result.lower()


@pytest.mark.asyncio
async def test_web_extract_requires_url():
    tool = WebExtractTool()
    result = await tool.execute({})
    assert "url is required" in result


@pytest.mark.asyncio
async def test_web_extract_fetches_html(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = SAMPLE_HTML
        url = "https://example.com/zoho"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("ribhus.tools.web_extract.httpx.AsyncClient", FakeClient)
    tool = WebExtractTool()
    result = await tool.execute({"url": "https://example.com/zoho"})
    assert "Zoho Corp Brief" in result
    assert "Chennai" in result
    assert "window.track" not in result


def test_default_registry_includes_web_extract(tmp_path):
    from ribhus.tools.registry import default_registry

    assert "web_extract" in default_registry(tmp_path).names()
