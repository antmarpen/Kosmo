"""Compatibility import for shared output validation."""

from app.domain.workflows.validation_logic import validate_outputs

__all__ = ["validate_outputs"]

import json
import os
import re
from pathlib import Path
from shared.paths import safe_path
