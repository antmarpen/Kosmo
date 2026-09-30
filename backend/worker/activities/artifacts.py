import hashlib
import json
from pathlib import Path


def artifact_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_output(path: Path, media_type: str) -> None:
    if not path.is_file():
        raise ValueError(f"Declared output missing: {path.name}")
    if media_type == "application/json" or path.suffix.lower() == ".json":
        json.loads(path.read_text(encoding="utf-8"))
    elif media_type in {"text/markdown", "text/plain"} or path.suffix.lower() in {".md", ".txt"}:
        path.read_text(encoding="utf-8")


def output_media_type(name: str) -> str:
    return {".json": "application/json", ".md": "text/markdown", ".txt": "text/plain"}.get(Path(name).suffix.lower(), "application/octet-stream")
