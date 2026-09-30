from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from shared.agent_events import AgentEvent
from shared.execution import ArtifactRef


@dataclass(frozen=True)
class SessionHandle:
    id: str


@dataclass(frozen=True)
class ArtifactContract:
    logical_name: str
    media_type: str = "application/octet-stream"


@dataclass(frozen=True)
class CompletionResult:
    artifacts: list[Any] = field(default_factory=list)


class AgentRuntimeAdapter(Protocol):
    async def start_session(self, cfg: Any) -> SessionHandle: ...
    async def send_prompt(self, text: str) -> None: ...
    def events(self) -> AsyncIterator[AgentEvent]: ...
    async def request_completion(self, expected_artifacts: list[ArtifactContract]) -> CompletionResult: ...
    async def deliver_feedback(self, errors: list[Any]) -> None: ...
    async def deliver_answer(self, text: str, request_id: str | int | None = None) -> None: ...
    async def collect_artifacts(self) -> dict[str, ArtifactRef]: ...
