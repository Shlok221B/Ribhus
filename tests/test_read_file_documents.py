from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ribhus.tools.filesystem import ReadFileTool, extract_document_text


def _make_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )


def test_extract_docx(tmp_path: Path) -> None:
    path = tmp_path / "resume.docx"
    _make_docx(path, ["SHLOK SAWANT", "AI Engineer"])
    text = extract_document_text(path)
    assert "SHLOK SAWANT" in text
    assert "AI Engineer" in text


@pytest.mark.asyncio
async def test_read_file_docx(tmp_path: Path) -> None:
    path = tmp_path / "cv.docx"
    _make_docx(path, ["Experience at Acme"])
    tool = ReadFileTool(workspace=tmp_path)
    result = await tool.execute({"path": "cv.docx"})
    assert "Acme" in result
    assert not result.startswith("Error:")


@pytest.mark.asyncio
async def test_read_file_pdf_smoke() -> None:
    pytest.importorskip("pypdf")
    repo = Path(__file__).resolve().parents[1]
    pdf = (
        repo
        / ".ribhus"
        / "uploads"
        / "4c96dadeef06"
        / "b2acd9bf_Shlok_Sawant_AI_Engineer_Resume.pdf"
    )
    if not pdf.is_file():
        pytest.skip("sample resume PDF not present")
    tool = ReadFileTool(workspace=repo)
    result = await tool.execute(
        {
            "path": ".ribhus/uploads/4c96dadeef06/b2acd9bf_Shlok_Sawant_AI_Engineer_Resume.pdf"
        }
    )
    assert "SHLOK" in result.upper()
    assert not result.startswith("Error:")


@pytest.mark.asyncio
async def test_read_file_rejects_legacy_doc(tmp_path: Path) -> None:
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0 binary junk")
    tool = ReadFileTool(workspace=tmp_path)
    result = await tool.execute({"path": "old.doc"})
    assert result.startswith("Error:")
    assert ".docx" in result or "not supported" in result.lower()
