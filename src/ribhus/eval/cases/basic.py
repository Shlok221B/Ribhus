from __future__ import annotations

from unittest.mock import patch

from ribhus.eval.harness import temp_workspace
from ribhus.eval.models import EvalCase
from ribhus.tools.filesystem import ReadFileTool, WriteFileTool
from ribhus.tools.http import HttpRequestTool
from ribhus.tools.location import LocationTool, save_location
from ribhus.tools.maps import MapsTool, google_maps_place_url
from ribhus.tools.python_exec import PythonTool
from ribhus.tools.registry import default_registry
from ribhus.tools.terminal import TerminalTool
from ribhus.tools.web_extract import WebExtractTool, html_to_text
from ribhus.tools.web_search import WebSearchTool

_EXPECTED_CORE = {
    "clarify",
    "edit_file",
    "http_request",
    "location",
    "maps",
    "process",
    "python",
    "read_file",
    "terminal",
    "todo",
    "web_extract",
    "web_search",
    "write_file",
}

_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Zoho Corp Brief</title></head>
<body>
  <nav>Home</nav>
  <script>window.track=1</script>
  <main>
    <h1>Zoho Corporation</h1>
    <p>Zoho is an Indian software company based in Chennai.</p>
  </main>
</body>
</html>
"""


def registry_core_tools() -> None:
    with temp_workspace() as workspace:
        names = set(default_registry(workspace).names())
        missing = _EXPECTED_CORE - names
        assert not missing, f"missing tools: {sorted(missing)}"
        assert "vision" not in names
        assert "browser" not in names


async def files_roundtrip() -> None:
    with temp_workspace() as workspace:
        write = WriteFileTool(workspace=workspace)
        read = ReadFileTool(workspace=workspace)
        await write.execute({"path": "hello.txt", "content": "namaste"})
        assert await read.execute({"path": "hello.txt"}) == "namaste"


async def path_escape_blocked() -> None:
    with temp_workspace() as workspace:
        read = ReadFileTool(workspace=workspace)
        result = await read.execute({"path": "../outside.txt"})
        assert "outside the workspace" in result


async def python_prints() -> None:
    with temp_workspace() as workspace:
        result = await PythonTool(workspace=workspace).execute({"code": "print(2 + 2)"})
        assert "exit_code=0" in result
        assert "4" in result


async def terminal_echo() -> None:
    with temp_workspace() as workspace:
        result = await TerminalTool(workspace=workspace).execute({"command": "echo ribhus"})
        assert "exit_code=0" in result
        assert "ribhus" in result


async def terminal_blocks_rm() -> None:
    with temp_workspace() as workspace:
        result = await TerminalTool(workspace=workspace).execute({"command": "rm -rf /"})
        assert "blocked" in result.lower()


async def http_request_mocked() -> None:
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok": true}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, headers=None, content=None):
            assert method == "GET"
            assert url.startswith("https://example.com")
            return FakeResponse()

    with patch("ribhus.tools.http.httpx.AsyncClient", FakeClient):
        result = await HttpRequestTool().execute({"url": "https://example.com/api"})
    assert "Status: 200" in result
    assert '"ok": true' in result


async def web_search_stubbed() -> None:
    class FakeDDGS:
        def text(self, query, max_results=5):
            assert "Zoho" in query
            return [
                {
                    "title": "Zoho Corporation",
                    "href": "https://www.zoho.com",
                    "body": "Indian software company",
                }
            ]

    with patch("ribhus.tools.web_search.DDGS", FakeDDGS):
        result = await WebSearchTool().execute({"query": "Zoho"})
    assert "Zoho Corporation" in result
    assert "https://www.zoho.com" in result


async def web_extract_stubbed() -> None:
    title, text = html_to_text(_SAMPLE_HTML)
    assert title == "Zoho Corp Brief"
    assert "Chennai" in text
    assert "window.track" not in text

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = _SAMPLE_HTML
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

    with patch("ribhus.tools.web_extract.httpx.AsyncClient", FakeClient):
        result = await WebExtractTool().execute({"url": "https://example.com/zoho"})
    assert "Zoho Corp Brief" in result
    assert "Chennai" in result


async def location_saved_coords() -> None:
    with temp_workspace() as workspace:
        ribhus_dir = workspace / ".ribhus"
        save_location(
            ribhus_dir,
            {
                "lat": 12.9784,
                "lng": 77.6408,
                "label": "Indiranagar, Bangalore",
                "source": "manual",
            },
        )
        tool = LocationTool(
            ribhus_dir=ribhus_dir,
            ip_lookup=False,
            device_lookup=False,
        )
        result = await tool.execute({"action": "get", "fresh": False})
        assert "Indiranagar" in result
        assert "12.9784" in result or "12.978" in result


async def maps_place_url() -> None:
    url = google_maps_place_url(name="Cubbon Park", lat=12.9763, lng=77.5929)
    assert "google.com/maps" in url
    with temp_workspace() as workspace:
        location = LocationTool(
            ribhus_dir=workspace / ".ribhus",
            ip_lookup=False,
            device_lookup=False,
        )
        maps = MapsTool(location_tool=location)
        result = await maps.execute(
            {"action": "place", "to": "12.9763,77.5929"}
        )
        assert "maps place" in result
        assert "google.com/maps" in result


CASES = [
    EvalCase("basic-registry", "basic", "registry", "Core tools are registered", registry_core_tools),
    EvalCase("basic-files", "basic", "read_file/write_file", "File round-trip", files_roundtrip),
    EvalCase("basic-path-escape", "basic", "read_file", "Path escape blocked", path_escape_blocked),
    EvalCase("basic-python", "basic", "python", "Python prints 4", python_prints),
    EvalCase("basic-terminal", "basic", "terminal", "Terminal echo", terminal_echo),
    EvalCase("basic-terminal-block", "basic", "terminal", "Dangerous rm blocked", terminal_blocks_rm),
    EvalCase("basic-http", "basic", "http_request", "HTTP with mocked httpx", http_request_mocked),
    EvalCase("basic-search", "basic", "web_search", "Search with stubbed DDGS", web_search_stubbed),
    EvalCase("basic-extract", "basic", "web_extract", "Extract with mocked fetch", web_extract_stubbed),
    EvalCase("basic-location", "basic", "location", "Saved coords without GPS/IP", location_saved_coords),
    EvalCase("basic-maps", "basic", "maps", "Place URL from lat,lng", maps_place_url),
]
