from __future__ import annotations

from ribhus.cli.dispatch import SUBCOMMANDS, parse_cli_invocations
from ribhus.eval.models import EvalCase


def skill_list_is_cli() -> None:
    assert parse_cli_invocations(["skill", "list"]) == [["skill", "list"]]
    assert parse_cli_invocations(["skill", "validate", "travel"]) == [
        ["skill", "validate", "travel"]
    ]


def natural_prompt_is_not_cli() -> None:
    assert parse_cli_invocations(["Find", "me", "a", "hotel", "in", "Goa"]) is None
    assert parse_cli_invocations(["Research this Indian company: Zoho"]) is None


def version_and_eval_are_commands() -> None:
    assert parse_cli_invocations(["version"]) == [["version"]]
    assert "eval" in SUBCOMMANDS
    assert parse_cli_invocations(["eval"]) == [["eval"]]
    assert parse_cli_invocations(["eval", "--json"]) == [["eval", "--json"]]


CASES = [
    EvalCase("cli-skill-list", "cli", "dispatch", "skill list is a CLI command", skill_list_is_cli),
    EvalCase("cli-natural-prompt", "cli", "dispatch", "Hero prompts are not CLI", natural_prompt_is_not_cli),
    EvalCase("cli-version-eval", "cli", "dispatch", "version and eval are commands", version_and_eval_are_commands),
]
