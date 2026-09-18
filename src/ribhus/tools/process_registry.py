from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_MAX_OUTPUT_CHARS = 200_000
_MAX_CONCURRENT = 8
_MAX_RETAINED = 32
_DEFAULT_WAIT_TIMEOUT = 120.0
_MAX_WAIT_TIMEOUT = 600.0


@dataclass
class ProcessSession:
    id: str
    command: str
    cwd: str
    started_at: float
    proc: asyncio.subprocess.Process | None = None
    output: str = ""
    poll_offset: int = 0
    exit_code: int | None = None
    ended_at: float | None = None
    killed: bool = False
    error: str | None = None
    _watch_task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.killed and self.exit_code is not None:
            return "killed"
        if self.exit_code is not None:
            return "exited"
        return "running"

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    def append_output(self, text: str) -> None:
        if not text:
            return
        self.output += text
        if len(self.output) > _MAX_OUTPUT_CHARS:
            overflow = len(self.output) - _MAX_OUTPUT_CHARS
            self.output = self.output[overflow:]
            self.poll_offset = max(0, self.poll_offset - overflow)

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "status": self.status,
            "pid": self.pid,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "output_chars": len(self.output),
            "error": self.error,
        }


class ProcessRegistry:
    """In-memory registry of background shell processes for the process tool."""

    def __init__(
        self,
        workspace: Path,
        *,
        max_concurrent: int = _MAX_CONCURRENT,
        max_retained: int = _MAX_RETAINED,
    ) -> None:
        self.workspace = workspace
        self.max_concurrent = max_concurrent
        self.max_retained = max_retained
        self._sessions: dict[str, ProcessSession] = {}
        self._lock = asyncio.Lock()

    def get(self, session_id: str) -> ProcessSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        items = sorted(
            self._sessions.values(),
            key=lambda s: s.started_at,
            reverse=True,
        )
        return [s.summary() for s in items]

    async def start(self, command: str, *, cwd: Path | None = None) -> ProcessSession:
        command = command.strip()
        if not command:
            raise ValueError("command is required")

        async with self._lock:
            running = sum(1 for s in self._sessions.values() if s.status == "running")
            if running >= self.max_concurrent:
                raise RuntimeError(
                    f"Too many running processes ({running}/{self.max_concurrent}). "
                    "Kill or wait for one before starting another."
                )
            self._prune_locked()

            workdir = cwd or self.workspace
            session = ProcessSession(
                id=f"proc_{uuid.uuid4().hex[:10]}",
                command=command,
                cwd=str(workdir),
                started_at=time.time(),
            )
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=str(workdir),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as exc:
                session.error = str(exc)
                session.exit_code = -1
                session.ended_at = time.time()
                self._sessions[session.id] = session
                return session

            session.proc = proc
            self._sessions[session.id] = session
            session._watch_task = asyncio.create_task(
                self._watch(session),
                name=f"ribhus-proc-{session.id}",
            )
            return session

    async def _watch(self, session: ProcessSession) -> None:
        proc = session.proc
        if proc is None or proc.stdout is None:
            session.exit_code = -1
            session.ended_at = time.time()
            session.error = "process missing stdout"
            return
        try:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                session.append_output(chunk.decode("utf-8", errors="replace"))
        finally:
            code = await proc.wait()
            session.exit_code = code
            session.ended_at = time.time()

    def poll(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process '{session_id}'"}
        new_output = session.output[session.poll_offset :]
        session.poll_offset = len(session.output)
        payload = session.summary()
        payload["new_output"] = new_output
        return payload

    def log(
        self,
        session_id: str,
        *,
        offset: int = 0,
        limit: int = 8_000,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process '{session_id}'"}
        offset = max(0, offset)
        limit = max(1, min(limit, 50_000))
        chunk = session.output[offset : offset + limit]
        payload = session.summary()
        payload["offset"] = offset
        payload["limit"] = limit
        payload["output"] = chunk
        payload["next_offset"] = offset + len(chunk)
        payload["total_chars"] = len(session.output)
        return payload

    async def wait(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process '{session_id}'"}
        if session.exit_code is not None:
            payload = session.summary()
            payload["output_tail"] = session.output[-8_000:]
            return payload

        timeout = _DEFAULT_WAIT_TIMEOUT if timeout is None else float(timeout)
        timeout = max(0.1, min(timeout, _MAX_WAIT_TIMEOUT))
        task = session._watch_task
        if task is None:
            return {"status": "error", "error": "No watcher for process"}

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            payload = session.summary()
            payload["timed_out"] = True
            payload["new_output"] = session.output[session.poll_offset :]
            session.poll_offset = len(session.output)
            return payload

        payload = session.summary()
        payload["output_tail"] = session.output[-8_000:]
        return payload

    async def kill(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process '{session_id}'"}
        if session.exit_code is not None:
            payload = session.summary()
            payload["already_finished"] = True
            return payload
        proc = session.proc
        if proc is None:
            session.exit_code = -1
            session.ended_at = time.time()
            session.error = "missing process handle"
            return session.summary()

        session.killed = True
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        if session._watch_task is not None:
            try:
                await asyncio.wait_for(session._watch_task, timeout=5.0)
            except TimeoutError:
                session.exit_code = session.exit_code if session.exit_code is not None else -9
                session.ended_at = session.ended_at or time.time()
        payload = session.summary()
        payload["output_tail"] = session.output[-4_000:]
        return payload

    async def write(
        self,
        session_id: str,
        data: str,
        *,
        submit: bool = False,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process '{session_id}'"}
        if session.exit_code is not None:
            return {
                "status": "exited",
                "error": "Process already finished; cannot write stdin",
                "session_id": session.id,
                "exit_code": session.exit_code,
            }
        proc = session.proc
        if proc is None or proc.stdin is None:
            return {"status": "error", "error": "stdin is not available"}

        payload = data if not submit else (data + ("" if data.endswith("\n") else "\n"))
        try:
            proc.stdin.write(payload.encode("utf-8", errors="replace"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            return {"status": "error", "error": f"stdin write failed: {exc}"}
        return {
            "status": "ok",
            "session_id": session.id,
            "bytes_written": len(payload.encode("utf-8", errors="replace")),
            "submit": submit,
        }

    async def kill_all(self) -> int:
        ids = [
            sid
            for sid, session in list(self._sessions.items())
            if session.status == "running"
        ]
        for sid in ids:
            await self.kill(sid)
        return len(ids)

    def _prune_locked(self) -> None:
        finished = [
            s
            for s in self._sessions.values()
            if s.exit_code is not None
        ]
        if len(finished) <= self.max_retained:
            return
        finished.sort(key=lambda s: s.ended_at or s.started_at)
        for session in finished[: len(finished) - self.max_retained]:
            self._sessions.pop(session.id, None)
