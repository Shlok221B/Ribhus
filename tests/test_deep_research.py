from ribhus.agent.deep_research import (
    looks_deep_research,
    research_pass_is_shallow,
)


def test_looks_deep_for_job_and_general_research():
    assert looks_deep_research("find me ai engineer jobs")
    assert looks_deep_research("compare the best vector databases in 2026")
    assert looks_deep_research("research what's happening with OpenAI API pricing")
    assert looks_deep_research("shortlist vendors for SOC2 compliance")


def test_looks_shallow_for_simple_asks():
    assert not looks_deep_research("calculate 17*19")
    assert not looks_deep_research("rewrite this paragraph more clearly")
    assert not looks_deep_research("hi")


def test_research_pass_is_shallow_until_multi_query_and_open():
    assert research_pass_is_shallow([])
    assert research_pass_is_shallow(["web_search"])
    assert research_pass_is_shallow(["web_search", "web_search"])
    assert research_pass_is_shallow(
        ["web_search", "web_search", "web_search"]
    )  # no page open yet
    assert not research_pass_is_shallow(
        ["web_search", "web_search", "web_search", "web_extract"]
    )
    assert not research_pass_is_shallow(
        ["web_search", "todo", "web_search", "web_search", "browser"]
    )
