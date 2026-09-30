"""Pure output validation shared by API and worker execution paths."""

from app.domain.workflows.validation_logic import validate_outputs

__all__ = ["validate_outputs"]
