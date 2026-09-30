import jwt

from app.domain.tasks.validator_auth import create_validator_token


def test_validator_token_is_short_lived_and_scoped_to_one_node_execution():
    secret = "test-signing-secret-that-is-at-least-32-bytes"
    token = create_validator_token(secret, "task-1", "ai-1", "execution-1", 60)
    claims = jwt.decode(token, secret, algorithms=["HS256"], audience="kosmo-validator")
    assert claims["iss"] == "kosmo-agent-validator"
    assert claims["scope"] == "validator:candidate"
    assert claims["task_id"] == "task-1"
    assert claims["node_id"] == "ai-1"
    assert claims["node_execution_id"] == "execution-1"
    assert claims["exp"] - claims["iat"] == 60
