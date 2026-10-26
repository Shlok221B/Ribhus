from __future__ import annotations

import shlex

SUBCOMMANDS = frozenset(
    {
        "tools",
        "skill",
        "whatsapp",
        "memory",
        "mcp",
        "email",
        "version",
        "dashboard",
        "eval",
    }
)
LAUNCHER_PREFIXES = (
    ("uv", "run", "ribhus"),
    ("uv", "run", "python", "-m", "ribhus"),
    ("python", "-m", "ribhus"),
)


def strip_launcher(parts: list[str]) -> list[str]:
    """Drop repeated `uv run ribhus` / `ribhus` prefixes."""
    i = 0
    n = len(parts)
    while i < n:
        matched = False
        for prefix in LAUNCHER_PREFIXES:
            plen = len(prefix)
            if parts[i : i + plen] == list(prefix):
                i += plen
                matched = True
                break
        if matched:
            continue
        if parts[i] == "ribhus":
            i += 1
            continue
        break
    return parts[i:]


def argv_if_cli(parts: list[str]) -> list[str] | None:
    """Return Typer argv if this is a Ribhus CLI command, else None."""
    parts = [p for p in parts if p]
    if not parts:
        return None
    if parts[0].startswith("/") and parts[0][1:] in SUBCOMMANDS:
        parts = [parts[0][1:], *parts[1:]]
    parts = strip_launcher(parts)
    if not parts:
        return None
    if parts[0] in SUBCOMMANDS:
        return parts
    if parts[0] in {"-h", "--help", "-V", "--version"}:
        return parts
    return None


def _split_on_launchers(parts: list[str]) -> list[list[str]]:
    """Split a flattened paste of several `uv run ribhus …` commands."""
    starts = [0]
    i = 1
    while i < len(parts):
        hit = False
        for prefix in LAUNCHER_PREFIXES:
            plen = len(prefix)
            if parts[i : i + plen] == list(prefix):
                starts.append(i)
                i += plen
                hit = True
                break
        if not hit:
            i += 1
    chunks: list[list[str]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(parts)
        chunk = parts[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks or [parts]


def _groups_from_parts(parts: list[str]) -> list[list[str]] | None:
    chunks = _split_on_launchers(parts)
    groups: list[list[str]] = []
    for chunk in chunks:
        cli = argv_if_cli(chunk)
        if cli is None:
            return None
        groups.append(cli)
    return groups or None


def parse_cli_invocations(args: list[str]) -> list[list[str]] | None:
    """If `args` is one or more CLI commands, return Typer argv groups.

    Handles:
    - skill validate travel
    - uv run ribhus skill validate travel  (typed inside Ribhus)
    - a quoted 'skill validate travel'
    - newline-separated shell commands pasted as one prompt
    """
    if not args:
        return None

    if len(args) == 1:
        text = args[0].strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) > 1:
            groups: list[list[str]] = []
            for line in lines:
                try:
                    parts = shlex.split(line)
                except ValueError:
                    return None
                parsed = _groups_from_parts(parts)
                if parsed is None:
                    return None
                groups.extend(parsed)
            return groups or None
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = [text]
        return _groups_from_parts(parts) if argv_if_cli(strip_launcher(parts)) else None

    return _groups_from_parts(args) if argv_if_cli(strip_launcher(args)) else None
