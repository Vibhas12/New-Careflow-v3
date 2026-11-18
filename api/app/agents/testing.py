"""Fake LLM for tests – no network. Replaces agents.llm.generate and switches the agents on with a dummy key.

    fake = install_fake_llm(monkeypatch)
    fake.respond(Recommendation, Recommendation(...))      # or a callable(prompt) -> BaseModel
    fake.fail(LLMUnavailable('quota', 429))                 # every later call raises
    assert len(fake.calls) == 1 and 'Facts (JSON)' in fake.calls[0]['prompt']
"""
from collections.abc import Callable

from pydantic import BaseModel

from app.agents import llm
from app.core.config import get_settings


class FakeLLM:
    model = 'fake-llm'

    def __init__(self):
        self.calls: list[dict] = []
        self.responses: dict[type, BaseModel | Callable[[str], BaseModel]] = {}
        self.error: Exception | None = None

    def respond(self, schema: type[BaseModel], value: BaseModel | Callable[[str], BaseModel]) -> 'FakeLLM':
        self.responses[schema] = value
        return self

    def fail(self, error: Exception | None) -> 'FakeLLM':
        self.error = error
        return self

    def __call__(self, *, system: str, prompt: str, schema: type[BaseModel], **kw) -> llm.LLMResult:
        self.calls.append({'system': system, 'prompt': prompt, 'schema': schema.__name__})
        if self.error:
            raise self.error
        if schema not in self.responses:
            raise AssertionError(f'FakeLLM has no response configured for {schema.__name__}')
        v = self.responses[schema]
        out = v(prompt) if callable(v) and not isinstance(v, BaseModel) else v
        return llm.LLMResult(out.model_copy(deep=True), self.model, [{'model': self.model, 'outcome': 'ok'}])


def install_fake_llm(monkeypatch) -> FakeLLM:
    s = get_settings()
    monkeypatch.setattr(s, 'llm_enabled', True)
    monkeypatch.setattr(s, 'gemini_api_key', 'test-key')
    fake = FakeLLM()
    monkeypatch.setattr(llm, 'generate', fake)
    return fake
