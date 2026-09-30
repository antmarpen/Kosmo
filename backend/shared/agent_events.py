"""Small, bounded event contracts shared by agent adapters and activities."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentStarted:
    session_id: str = ""


@dataclass(frozen=True)
class AgentText:
    delta: str


@dataclass(frozen=True)
class AgentToolUse:
    name: str


@dataclass(frozen=True)
class InputRequested:
    message_key: str
    params: dict[str, Any] = field(default_factory=dict)
    request_id: str | int | None = None
    method: str | None = None


@dataclass(frozen=True)
class CompletionProposed:
    artifacts: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class AgentError:
    message_key: str
    params: dict[str, Any] = field(default_factory=dict)


AgentEvent = AgentStarted | AgentText | AgentToolUse | InputRequested | CompletionProposed | AgentError
