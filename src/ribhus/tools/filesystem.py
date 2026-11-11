from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ribhus.tools.base import Tool

_TEXT_LIMIT = 100_000
_DOCX_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def _ensure_pypdf() -> None:
    """Import pypdf, falling back to a repo-local vendor/ install if needed."""
    try:
        import pypdf  # noqa: F401

        return
    except ImportError:
        pass
    candidates = [
        Path.cwd() / "vendor",
        Path(__file__).resolve().parents[3] / "vendor",
    ]
    for vendor in candidates:
        if not (vendor / "pypdf").is_dir():
            continue
        path = str(vendor)
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import pypdf  # noqa: F401

            return
        except ImportError:
            continue
    raise ImportError("pypdf is not installed")


def _resolve_path(workspace: Path, path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    workspace_resolved = workspace.resolve()
    if not str(resolved).startswith(str(workspace_resolved)):
        raise PermissionError(
            f"Path '{path_str}' is outside the workspace ({workspace_resolved})"
        )
    return resolved


def extract_document_text(path: Path) -> str:
    """Extract plain text from PDF or DOCX. Raises ValueError on failure."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".doc":
        raise ValueError(
            "Legacy .doc is not supported. Re-save as .docx, .pdf, or .txt."
        )
    raise ValueError(f"No document extractor for {suffix or 'this file type'}")


def _extract_pdf(path: Path) -> str:
    try:
        _ensure_pypdf()
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError(
            "PDF support requires the pypdf package. Run: uv sync"
        ) from exc
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 — surface to the agent
        raise ValueError(f"Could not open PDF: {exc}") from exc
    parts: list[str] = []
    for page in reader.pages:
        try:
            chunk = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            chunk = ""
        if chunk.strip():
            parts.append(chunk)
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError(
            "PDF has no extractable text (it may be a scanned image). "
            "Paste the text or upload a .txt / .docx version."
        )
    return text


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("Invalid DOCX: missing word/document.xml") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid DOCX: {exc}") from exc
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for para in root.iter(f"{{{_DOCX_NS['w']}}}p"):
        runs = [
            (node.text or "")
            for node in para.iter(f"{{{_DOCX_NS['w']}}}t")
        ]
        line = "".join(runs).strip()
        if line:
            paragraphs.append(line)
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ValueError("DOCX has no extractable text")
    return text


def _clip_text(text: str, limit: int = _TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read a file relative to the workspace. Supports UTF-8 text plus "
        "PDF and DOCX (extracts plain text). Truncated at 100KB of text."
    )
    risk_level = "low"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace (or absolute within workspace)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        path_str = str(arguments.get("path", "")).strip()
        if not path_str:
            return "Error: path is required"
        try:
            path = _resolve_path(self.workspace, path_str)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not path.exists():
            return f"Error: file not found: {path_str}"
        if not path.is_file():
            return f"Error: not a file: {path_str}"

        suffix = path.suffix.lower()
        if suffix in {".pdf", ".docx", ".doc"}:
            try:
                return _clip_text(extract_document_text(path))
            except ValueError as exc:
                return f"Error: {exc}"

        data = path.read_bytes()
        truncated = False
        if len(data) > _TEXT_LIMIT:
            data = data[:_TEXT_LIMIT]
            truncated = True
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # Some uploads are binary with a misleading extension — try PDF magic.
            if data[:5] == b"%PDF-":
                try:
                    return _clip_text(extract_document_text(path))
                except ValueError as exc:
                    return f"Error: {exc}"
            return (
                f"Error: file is not valid UTF-8 text ({path_str}). "
                "For resumes, upload PDF, DOCX, or plain text."
            )
        if truncated:
            text += "\n...[truncated]"
        return text


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write the full contents of a file inside the workspace (creates parent dirs). "
        "Prefer edit_file for changing part of an existing file."
    )
    risk_level = "high"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace",
                },
                "content": {
                    "type": "string",
                    "description": "Full file contents to write",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        path_str = str(arguments.get("path", "")).strip()
        content = arguments.get("content")
        if not path_str:
            return "Error: path is required"
        if content is None:
            return "Error: content is required"
        try:
            path = _resolve_path(self.workspace, path_str)
        except PermissionError as exc:
            return f"Error: {exc}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        return f"Wrote {len(str(content))} characters to {path_str}"


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "Surgically patch an existing text file by replacing an exact string. "
        "Prefer this over write_file for small edits. "
        "old_string must match exactly (including whitespace/indentation) and "
        "uniquely identify the spot unless replace_all=true. "
        "To delete text, set new_string to empty. To insert, include enough "
        "surrounding context in old_string and the inserted text in new_string."
    )
    risk_level = "high"

    def __init__(self, workspace: Path, *, max_bytes: int = 2_000_000) -> None:
        self.workspace = workspace
        self.max_bytes = max_bytes

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find in the file",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text (may be empty to delete)",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": (
                        "If true, replace every occurrence of old_string. "
                        "Default false — requires a unique match."
                    ),
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        path_str = str(arguments.get("path") or "").strip()
        if not path_str:
            return "Error: path is required"
        if "old_string" not in arguments:
            return "Error: old_string is required"
        if "new_string" not in arguments:
            return "Error: new_string is required"
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not isinstance(old, str):
            return "Error: old_string must be a string"
        if not isinstance(new, str):
            return "Error: new_string must be a string"
        if old == "":
            return "Error: old_string must not be empty"
        if old == new:
            return "Error: old_string and new_string are identical — nothing to change"
        return None

    async def execute(self, arguments: dict[str, Any]) -> str:
        path_str = str(arguments.get("path") or "").strip()
        old = str(arguments.get("old_string"))
        new = str(arguments.get("new_string"))
        replace_all = bool(arguments.get("replace_all") or False)

        try:
            path = _resolve_path(self.workspace, path_str)
        except PermissionError as exc:
            return f"Error: {exc}"

        if not path.exists():
            return f"Error: file not found: {path_str}"
        if not path.is_file():
            return f"Error: not a file: {path_str}"

        size = path.stat().st_size
        if size > self.max_bytes:
            return (
                f"Error: file too large to edit in-place "
                f"({size} bytes > {self.max_bytes})"
            )

        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: file is not valid UTF-8 text ({path_str})"

        count = original.count(old)
        if count == 0:
            hint = _nearest_hint(original, old)
            msg = f"Error: old_string not found in {path_str}."
            if hint:
                msg += f" Near match hint: {hint}"
            return msg
        if count > 1 and not replace_all:
            return (
                f"Error: old_string found {count} times in {path_str}. "
                "Provide more surrounding context for a unique match, "
                "or set replace_all=true."
            )

        if replace_all:
            updated = original.replace(old, new)
            replacements = count
        else:
            updated = original.replace(old, new, 1)
            replacements = 1

        path.write_text(updated, encoding="utf-8")
        delta = len(updated) - len(original)
        sign = "+" if delta >= 0 else ""
        return (
            f"Edited {path_str}: {replacements} replacement(s), "
            f"{sign}{delta} chars (now {len(updated)} chars)."
        )


def _nearest_hint(text: str, needle: str, *, max_len: int = 80) -> str | None:
    """Best-effort hint when an exact match fails (first line of old_string)."""
    first_line = needle.splitlines()[0].strip() if needle else ""
    if len(first_line) < 4:
        return None
    for i, line in enumerate(text.splitlines(), start=1):
        if first_line in line or (
            len(first_line) >= 8 and first_line[:8] in line
        ):
            snippet = line.strip()
            if len(snippet) > max_len:
                snippet = snippet[: max_len - 1] + "…"
            return f"line {i}: {snippet!r}"
    return None
