"""CareFlow AI agents – shared groundwork (multi-agent phase 1).

    llm.py           provider layer (Gemini, structured output, model fallback, fail fast)
    privacy.py       de-identification + identifier leak detection
    base.py          Agent definition + registry
    limits.py        kill switch, per-user hourly cap, 429 cooldown
    orchestrator.py  run(): switch → limits → privacy → one provider request → verify → run log
    testing.py       FakeLLM for tests

Rules for every agent: on demand only (a person's click), at most one provider request sequence per click, de-identified input,
output verified before use, rule/template fallback on any failure, and no action without human approval.

Agents in use:
    recommendation   care-gap "Recommended next action" wording (services/recommendation_agent.py)
"""


def load_all() -> None:
    """Import the modules that register agents (they live next to the service that uses them)."""
    import app.services.recommendation_agent  # noqa: F401
