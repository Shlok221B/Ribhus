"""Structured types for the autonomous research orchestrator."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ResearchObjective(BaseModel):
    id: str
    description: str
    success_criteria: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    objective: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    information_needed: list[str] = Field(default_factory=list)
    research_objectives: list[ResearchObjective] = Field(default_factory=list)
    search_strategies: list[str] = Field(default_factory=list)
    success_definition: str = ""
    domain: Literal["jobs", "general"] = "general"


class SearchLead(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""
    provider: str = ""
    query: str = ""
    canonical_url: str = ""
    score: float = 0.0


class JobVerification(BaseModel):
    job_page_accessible: bool = False
    application_link_found: bool = False
    application_page_accessible: bool = False
    active_status_confirmed: bool = False
    closed_evidence: str | None = None
    redirect_final_url: str | None = None
    http_status: int | None = None
    evidence_excerpt: str | None = None


class JobRecord(BaseModel):
    company: str | None = None
    role: str | None = None
    location: str | None = None
    experience: str | None = None
    salary: str | None = None
    skills: list[str] = Field(default_factory=list)
    job_url: str | None = None
    application_url: str | None = None
    source_url: str | None = None
    date_posted: str | None = None
    valid_through: str | None = None
    employment_type: str | None = None
    status: Literal[
        "unknown",
        "discovered",
        "accessible",
        "application_url_found",
        "application_accessible",
        "active_confirmed",
        "closed",
    ] = "unknown"
    verification: JobVerification = Field(default_factory=JobVerification)
    inferred_fields: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0
    notes: str | None = None


class EvaluationResult(BaseModel):
    research_complete: bool = False
    completion_score: int = 0
    missing_information: list[str] = Field(default_factory=list)
    next_search_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    rationale: str = ""


class ResearchMetrics(BaseModel):
    search_relevance: float | None = None
    listing_precision: float | None = None
    application_url_coverage: float | None = None
    application_page_accessibility: float | None = None
    active_verification_rate: float | None = None
    duplicate_rate: float | None = None
    constraint_satisfaction: float | None = None
    research_completion_rate: float | None = None
    average_research_cost_usd: float | None = None
    execution_time_seconds: float | None = None
    leads_discovered: int = 0
    records_kept: int = 0
    urls_investigated: int = 0
    iterations: int = 0
    queries_run: int = 0
    total_tokens: int = 0


class ResearchResult(BaseModel):
    objective: str
    plan: ResearchPlan | None = None
    records: list[JobRecord] = Field(default_factory=list)
    evaluation: EvaluationResult | None = None
    metrics: ResearchMetrics = Field(default_factory=ResearchMetrics)
    summary_markdown: str = ""
    limitations: list[str] = Field(default_factory=list)
    incomplete: bool = False
