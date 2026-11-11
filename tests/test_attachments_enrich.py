from __future__ import annotations

import zipfile
from pathlib import Path

from ribhus.bots.attachments import enrich_prompt_with_uploads


def _docx(path: Path, text: str) -> None:
    body = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document)


def test_enrich_inlines_docx(tmp_path: Path) -> None:
    upload = tmp_path / ".ribhus" / "uploads" / "chat1"
    upload.mkdir(parents=True)
    doc = upload / "resume.docx"
    _docx(doc, "SHLOK SAWANT AI Engineer")
    prompt = (
        "here is my resume\n\nAttached file:\n"
        "- resume.docx (workspace path: `.ribhus/uploads/chat1/resume.docx`)"
    )
    out = enrich_prompt_with_uploads(prompt, tmp_path)
    assert "Begin attached file: resume.docx" in out
    assert "SHLOK SAWANT" in out
