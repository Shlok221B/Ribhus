"""Compile a LaTeX resume to PDF with Tectonic."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ribhus.jobs.errors import JobHuntError


def tectonic_available() -> bool:
    return shutil.which("tectonic") is not None


def compile_resume(tex_path: Path, pdf_path: Path) -> None:
    binary = shutil.which("tectonic")
    if binary is None:
        raise JobHuntError(
            "Tectonic is not installed, so the PDF could not be built. "
            "Install it with `brew install tectonic` and prepare the job again."
        )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [binary, "--outdir", str(pdf_path.parent), str(tex_path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    produced = pdf_path.parent / f"{tex_path.stem}.pdf"
    if result.returncode != 0 or not produced.is_file():
        detail = (result.stderr or result.stdout or "unknown tectonic error").strip()
        raise JobHuntError(f"LaTeX compile failed: {detail[-900:]}")
    if produced.resolve() != pdf_path.resolve():
        produced.replace(pdf_path)
