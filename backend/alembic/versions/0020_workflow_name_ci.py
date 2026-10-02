"""Make workflow names case-insensitively unique at the database level.

The API already prechecks names case-insensitively, but the exact-name unique
constraint left a race: concurrent creations or publications renaming onto
case-variant names ("Billing" / "billing") could both win. The exact-name
constraint is replaced by a functional unique index on lower(name), matching
the precheck, so the database itself decides the race and the repository
translates the violation into the existing `errors.workflow.name_conflict`
conflict.

Existing rows that would collide under the new rule are suffixed
deterministically ("Name (2)", "Name (3)", ...) keeping the first row (by id)
unsuffixed; the suffix search skips unrelated pre-existing names so the
backfill can never itself collide, and candidates are truncated to the column
limit so the update cannot overflow String(200). Rows are only renamed, never
deleted or merged. The downgrade restores the exact-name constraint — always
representable, because the backfill left every name distinct even
case-insensitively.
"""
from collections import Counter
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0020_workflow_name_ci"
down_revision: str | None = "0019_provider_config_instances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTIONAL_INDEX = "uq_workflows_name_ci"
_EXACT_CONSTRAINT = "workflows_name_key"
_NAME_LIMIT = 200


def _suffixed(base: str, suffix: int) -> str:
    """First free "Name (N)" candidate, truncated to fit String(200)."""
    tail = f" ({suffix})"
    return base[:_NAME_LIMIT - len(tail)] + tail


def _backfill_names(conn) -> None:
    """Make existing names collision-safe under lower(name) uniqueness.

    Deterministic: rows are walked in id order, the first row of each
    case-variant group keeps its name, and every later sibling takes the
    first free "Name (N)" suffix — skipping both the untouched originals and
    the suffixes already assigned, so the result never collides.
    """
    rows = conn.execute(sa.text("SELECT id, name FROM workflows ORDER BY id")).fetchall()
    counts = Counter(row.name.lower() for row in rows)
    taken = {row.name.lower() for row in rows}
    seen: set[str] = set()
    renames: list[tuple[str, str]] = []
    for row in rows:
        key = row.name.lower()
        if counts[key] == 1:
            continue
        if key not in seen:
            seen.add(key)  # the first duplicate row (lowest id) keeps the name
            continue
        suffix = 2
        while True:
            candidate = _suffixed(row.name, suffix)
            if candidate.lower() not in taken:
                break
            suffix += 1
        taken.add(candidate.lower())
        renames.append((candidate, row.id))
    for name, row_id in renames:
        conn.execute(sa.text("UPDATE workflows SET name = :name WHERE id = :id"),
                     {"name": name, "id": row_id})


def upgrade() -> None:
    conn = op.get_bind()
    _backfill_names(conn)
    op.drop_constraint(_EXACT_CONSTRAINT, "workflows", type_="unique")
    op.create_index(_FUNCTIONAL_INDEX, "workflows", [sa.text("lower(name)")], unique=True)


def downgrade() -> None:
    op.drop_index(_FUNCTIONAL_INDEX, table_name="workflows")
    op.create_unique_constraint(_EXACT_CONSTRAINT, "workflows", ["name"])
