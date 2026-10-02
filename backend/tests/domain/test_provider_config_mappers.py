"""Regression: provider models must configure without the API's import order.

The worker loads only the provider config module. While the string foreign keys
to `users.id` were unresolvable there, every candidate operation query failed
with NoReferencedTableError. This runs in a fresh interpreter so an unrelated
test's imports cannot mask the missing registration.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_provider_models_configure_standalone():
    program = (
        "import app.domain.provider_configs.models;"
        "from sqlalchemy.orm import configure_mappers;"
        "configure_mappers();"
        "print('configured')"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "configured" in result.stdout
