"""CareFlow AI agents – shared groundwork (multi-agent phase 1).

    llm.py           provider layer (Gemini, structured output, model fallback, fail fast)
    privacy.py       de-identification + identifier leak detection
    base.py          Agent definition + registry
    limits.py        kill switch, per-user hourly cap, 429 cooldown
    orchestrator.py  run(): switch → limits → privacy → one provider request → verify → run log
    verifier.py      safety & grounding checks (phase 2): clinical advice, priority changes, invented actions, ungrounded
                     dates / values / tests, responsible role, urgency vs priority, length
    testing.py       FakeLLM for tests

Rules for every agent: on demand only (a person's click), at most one provider request sequence per click, de-identified input,
output verified before use, rule/template fallback on any failure, and no action without human approval.

    context.py       Context agent (phase 3, code only): scoped, numbered, de-identified patient facts

Agents in use (LLM, on demand):
    recommendation   care-gap "Recommended next action" wording (services/recommendation_agent.py)
    summary          patient AI summary – overview + narrative sections citing sources (services/summary_agent.py)
    answer           AI Care Assistant "Ask AI" – answers + drafted tasks / reminders (services/answer_agent.py)
    import_extract   Data Import: report fields from a PDF's text, identity removed (services/import_agents.py)
    import_map       Data Import: CareFlow field for unrecognised CSV/JSON columns – names and value shapes only
    insights         Doctor Performance / Executive Overview "Explain with AI" – aggregates only (services/insight_agents.py)
    reviewer         "AI safety check" – advisory second opinion on an AI output already shown
"""


def load_all() -> None:
    """Import the modules that register agents (they live next to the service that uses them)."""
    import app.services.recommendation_agent  # noqa: F401
    import app.services.summary_agent  # noqa: F401
    import app.services.answer_agent  # noqa: F401
    import app.services.import_agents  # noqa: F401
    import app.services.insight_agents  # noqa: F401
