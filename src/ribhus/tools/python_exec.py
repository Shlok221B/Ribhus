from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from ribhus.tools.base import Tool


class PythonTool(Tool):
    name = "python"
    description = (
        "Execute a Python 3 code snippet in a subprocess. "
        "Use print() to return output. Timeout: 30s."
    )
    risk_level = "high"

    def __init__(self, workspace: Path, timeout: float = 30.0) -> None:
        self.workspace = workspace
        self.timeout = timeout

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute",
                },
            },
            "required": ["code"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            return "Error: code is required"

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                tmp_path,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: python execution timed out after {self.timeout}s"

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            parts = [f"exit_code={proc.returncode}"]
            if out:
                parts.append(f"stdout:\n{out}")
            if err:
                parts.append(f"stderr:\n{err}")
            return "\n".join(parts)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
