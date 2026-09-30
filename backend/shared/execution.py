from dataclasses import dataclass, field


@dataclass(frozen=True)
class KosmoErrorData:
    code: str
    message_key: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRef:
    id: str
    logical_name: str


@dataclass(frozen=True)
class NodeResult:
    state: str
    outputs: dict[str, ArtifactRef] = field(default_factory=dict)
    error: KosmoErrorData | None = None


@dataclass(frozen=True)
class TaskExecutionInput:
    task_id: str
    definition: dict
    input_values: dict


def result_payload(result):
    if isinstance(result, dict):
        return result
    return {"state": result.state, "outputs": result.outputs, "error": result.error}
