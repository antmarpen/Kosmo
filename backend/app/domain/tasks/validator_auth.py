"""Short-lived task/node/execution-scoped validator MCP credentials."""

from datetime import datetime, timedelta, timezone

import jwt


VALIDATOR_ISSUER = "kosmo-agent-validator"
VALIDATOR_AUDIENCE = "kosmo-validator"
VALIDATOR_SCOPE = "validator:candidate"


def create_validator_token(secret: str, task_id: str, node_id: str,
                           node_execution_id: str, lifetime_seconds: int = 3600) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": VALIDATOR_ISSUER, "aud": VALIDATOR_AUDIENCE,
        "purpose": "agent-validator", "scope": VALIDATOR_SCOPE,
        "task_id": task_id, "node_id": node_id, "node_execution_id": node_execution_id,
        "iat": now, "exp": now + timedelta(seconds=lifetime_seconds),
    }
    return jwt.encode(claims, secret, algorithm="HS256")
