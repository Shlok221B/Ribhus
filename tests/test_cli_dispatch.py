from ribhus.cli.dispatch import parse_cli_invocations


def test_invoke_validate_travel():
    from ribhus.cli.main import _run_cli_groups

    assert _run_cli_groups([["skill", "validate", "travel"]]) == 0


def test_skill_subcommand_tokens():
    assert parse_cli_invocations(["skill", "validate", "travel"]) == [
        ["skill", "validate", "travel"]
    ]
    assert parse_cli_invocations(["skill", "install", "travel"]) == [
        ["skill", "install", "travel"]
    ]


def test_mcp_subcommand_tokens():
    assert parse_cli_invocations(["mcp", "list"]) == [["mcp", "list"]]
    assert parse_cli_invocations(["mcp", "init", "--force"]) == [
        ["mcp", "init", "--force"]
    ]


def test_double_uv_run_prefix():
    assert parse_cli_invocations(
        ["uv", "run", "ribhus", "skill", "validate", "travel"]
    ) == [["skill", "validate", "travel"]]


def test_pasted_full_command_as_one_string():
    assert parse_cli_invocations(["uv run ribhus skill validate travel"]) == [
        ["skill", "validate", "travel"]
    ]
    assert parse_cli_invocations(["skill validate travel"]) == [
        ["skill", "validate", "travel"]
    ]


def test_two_commands_on_separate_lines():
    text = (
        "uv run ribhus skill validate travel\n"
        "uv run ribhus skill install travel"
    )
    assert parse_cli_invocations([text]) == [
        ["skill", "validate", "travel"],
        ["skill", "install", "travel"],
    ]


def test_slash_command():
    assert parse_cli_invocations(["/skill list"]) == [["skill", "list"]]


def test_agent_prompts_are_not_cli():
    assert parse_cli_invocations(["Find", "me", "a", "hotel", "in", "Goa"]) is None
    assert parse_cli_invocations(["Research this Indian company: Zoho"]) is None
    assert parse_cli_invocations(["remember that I prefer Hinglish"]) is None
