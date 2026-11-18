"""Agent definition shared by every CareFlow agent.

An agent is a small declarative object: a name, a system prompt, an output schema, how to build the prompt from
(already de-identified) facts, how to tidy the output, and a code-level `verify()` hook that returns problems.
Agents never touch the database, never call the provider themselves and never act: the orchestrator runs them and
the calling service decides what to store; anything that would change records goes through human approval.
"""
import json
from typing import ClassVar

from pydantic import BaseModel

REGISTRY: dict[str, 'Agent'] = {}


class Agent:
    name: ClassVar[str]                    # stable id – used by the on/off switches, limits and the run log
    label: ClassVar[str]                   # human-readable, shown in the UI / run log
    system: ClassVar[str]                  # system instruction
    instruction: ClassVar[str]             # first line of the user prompt
    output: ClassVar[type[BaseModel]]      # structured output schema
    temperature: ClassVar[float] = 0.2
    max_output_tokens: ClassVar[int] = 2048

    def prompt(self, context: dict) -> str:
        return f'{self.instruction} Facts (JSON):\n' + json.dumps(context, ensure_ascii=False)

    def clean(self, out: BaseModel, context: dict | None = None) -> BaseModel:
        """Normalise the model's output (trim, cap lengths) before verify(). Override per agent; `context` is what was sent."""
        return out

    def verify(self, out: BaseModel, context: dict) -> list[str]:
        """Code-level checks on the output; return a list of problems (empty = passes). The safety & grounding verifier
        (multi-agent phase 2) extends this. A non-empty list means the output is withheld and the template is shown."""
        return []


def register(cls: type[Agent]) -> type[Agent]:
    REGISTRY[cls.name] = cls()
    return cls


def get(name: str) -> Agent:
    if name not in REGISTRY:
        from app.agents import load_all
        load_all()
    return REGISTRY[name]


def all_agents() -> list[Agent]:
    from app.agents import load_all
    load_all()
    return list(REGISTRY.values())
