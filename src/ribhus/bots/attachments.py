"""Expand chat upload references into extracted text for the agent prompt."""

from __future__ import annotations

import re
from pathlib import Path

from ribhus.tools.filesystem import extract_document_text

# Paths the UI embeds, e.g. `.ribhus/uploads/<chat>/<file.pdf>`
_UPLOAD_PATH_RE = re.compile(
    r"(?:^|[`\"'\s])("
    r"\.ribhus/uploads/[A-Za-z0-9_./-]+\.(?:pdf|docx|txt|md|csv|json|tex)"
    r")(?:[`\"'\s]|$)",
    re.IGNORECASE,
)

_EXTRACT_SUFFIXES = {".pdf", ".docx"}
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".tex", ".py"}


def enrich_prompt_with_uploads(prompt: str, workspace: Path) -> str:
    """If the prompt references uploaded files, append their text inline.

    So the model can use resume contents even when it skips read_file, and
    so PDF/DOCX work without relying on a tool call.
    """
    text = (prompt or "").strip()
    if not text:
        return text

    paths: list[str] = []
    seen: set[str] = set()
    for match in _UPLOAD_PATH_RE.finditer(text):
        rel = match.group(1).strip()
        if rel in seen:
            continue
        seen.add(rel)
        paths.append(rel)
    if not paths:
        return text

    blocks: list[str] = []
    for rel in paths:
        # Avoid duplicating if we already inlined this file.
        marker = f"--- Begin attached file: {Path(rel).name} ---"
        if marker in text:
            continue
        path = (workspace / rel).resolve()
        try:
            path.relative_to(workspace.resolve())
        except ValueError:
            blocks.append(f"{marker}\nError: path outside workspace\n--- End attached file ---")
            continue
        if not path.is_file():
            blocks.append(f"{marker}\nError: file not found: {rel}\n--- End attached file ---")
            continue
        suffix = path.suffix.lower()
        try:
            if suffix in _EXTRACT_SUFFIXES:
                body = extract_document_text(path)
            elif suffix in _TEXT_SUFFIXES:
                body = path.read_text(encoding="utf-8", errors="replace")
            else:
                continue
        except Exception as exc:  # noqa: BLE001
            blocks.append(
                f"{marker}\nError extracting text: {exc}\n--- End attached file ---"
            )
            continue
        if len(body) > 80_000:
            body = body[:80_000] + "\n...[truncated]"
        blocks.append(f"{marker}\n{body}\n--- End attached file ---")

    if not blocks:
        return text
    return text + "\n\n" + "\n\n".join(blocks)
