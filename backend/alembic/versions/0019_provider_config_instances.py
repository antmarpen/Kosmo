"""Allow multiple named provider configurations per owner and provider.

Replaces the one-row-per-scope rule with case-insensitive display-name
uniqueness per owner and provider (functional unique index on
lower(display_name)), so a user can keep several configurations for the
same provider in the same scope and edit each one in place by id.

Existing rows keep their identifiers and ciphertext. Names that would
collide under the new rule are suffixed deterministically ("Name (2)",
"Name (3)", ...) keeping the first row (by id) unsuffixed. The suffix is
carved out of the 80-character display_name limit, so an overlong name is
truncated to make room and every collision check runs against the final
truncated value. The suffix search also skips unrelated pre-existing names
so the backfill can never itself collide. The downgrade refuses
transactionally — without deleting or merging stored credentials — when
rows cannot be represented under the restored one-row-per-scope
constraints.
"""
from collections import Counter
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0019_provider_config_instances"
down_revision: str | None = "0018_candidate_operation_purpose"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTIONAL_INDEX = "uq_provider_config_owner_provider_name_ci"
_DISPLAY_NAME_LIMIT = 80


def _suffixed_name(base: str, suffix: int) -> str:
    """Return `base` with a " (N)" tag appended, fitting the column limit.

    The tag is reserved inside the 80-character limit, so an overlong base
    is truncated to make room; the caller collision-checks the returned
    value, which is the one actually written. A tag that alone would exceed
    the limit is unreachable for the 80-character column and realistic
    suffix counts, but is refused instead of looping forever.
    """
    tag = f" ({suffix})"
    room = _DISPLAY_NAME_LIMIT - len(tag)
    if room < 0:
        raise RuntimeError(
            f"display_name limit {_DISPLAY_NAME_LIMIT} cannot hold the '{tag}' suffix")
    return f"{base[:room]}{tag}"


def _backfill_display_names(conn) -> None:
    """Make existing names collision-safe under (owner, provider, lower(name)).

    Deterministic: rows are walked in id order, the first row of each
    duplicate group keeps its name, and every later sibling takes the first
    free "Name (N)" suffix — skipping both the untouched originals and the
    suffixes already assigned, so the result never collides. The suffix is
    reserved inside the display_name column limit (overlong bases are
    truncated by `_suffixed_name`), and collisions are checked against the
    final value that will actually be stored.
    """
    rows = conn.execute(sa.text(
        "SELECT id, user_id, provider, display_name FROM provider_configs ORDER BY id"
    )).fetchall()
    counts = Counter((row.user_id, row.provider, row.display_name.lower()) for row in rows)
    taken = {(row.user_id, row.provider, row.display_name.lower()) for row in rows}
    seen: set[tuple[str, str, str]] = set()
    renames: list[tuple[str, str]] = []
    for row in rows:
        key = (row.user_id, row.provider, row.display_name.lower())
        if counts[key] == 1:
            continue
        if key not in seen:
            seen.add(key)  # the first duplicate row (lowest id) keeps the name
            continue
        suffix = 2
        while True:
            candidate = _suffixed_name(row.display_name, suffix)
            candidate_key = (row.user_id, row.provider, candidate.lower())
            if candidate_key not in taken:
                break
            suffix += 1
        taken.add(candidate_key)
        renames.append((candidate, row.id))
    for name, row_id in renames:
        conn.execute(sa.text("UPDATE provider_configs SET display_name = :name WHERE id = :id"),
                     {"name": name, "id": row_id})


def _unrepresentable_scope_groups(conn) -> int:
    """Count scope groups the restored one-row-per-scope rules cannot hold.

    Three restored invariants are checked: one row per (owner, provider,
    visibility, group), one global row per provider, and one group row per
    (group, provider). Coalescing keeps NULL and empty group ids comparable.
    """
    checks = (
        """SELECT count(*) FROM (
             SELECT user_id, provider, visibility, coalesce(group_id, '') AS group_key
             FROM provider_configs
             GROUP BY user_id, provider, visibility, coalesce(group_id, '')
             HAVING count(*) > 1) AS duplicates""",
        """SELECT count(*) FROM (
             SELECT provider FROM provider_configs WHERE visibility = 'global'
             GROUP BY provider HAVING count(*) > 1) AS duplicates""",
        """SELECT count(*) FROM (
             SELECT coalesce(group_id, '') AS group_key, provider FROM provider_configs
             WHERE visibility = 'group'
             GROUP BY coalesce(group_id, ''), provider HAVING count(*) > 1) AS duplicates""",
    )
    return sum(conn.execute(sa.text(query)).scalar_one() for query in checks)


def upgrade() -> None:
    conn = op.get_bind()
    _backfill_display_names(conn)
    op.drop_constraint("uq_provider_config_owner_provider_visibility_group",
                       "provider_configs", type_="unique")
    op.drop_index("uq_provider_configs_global_provider", table_name="provider_configs")
    op.drop_index("uq_provider_configs_group_provider", table_name="provider_configs")
    op.create_index(_FUNCTIONAL_INDEX, "provider_configs",
                    ["user_id", "provider", sa.text("lower(display_name)")], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    conflicts = _unrepresentable_scope_groups(conn)
    if conflicts:
        raise RuntimeError(
            "Downgrade refused: "
            f"{conflicts} provider configuration scope group(s) cannot be represented under "
            "the one-configuration-per-scope rule of revision 0018. Multiple instances exist "
            "for the same owner, provider, and scope (or several global/group instances for "
            "one provider). Delete or merge the extra configurations first; the downgrade "
            "never deletes or merges stored credentials itself."
        )
    op.drop_index(_FUNCTIONAL_INDEX, table_name="provider_configs")
    op.create_unique_constraint("uq_provider_config_owner_provider_visibility_group",
                                "provider_configs",
                                ["user_id", "provider", "visibility", "group_id"])
    op.create_index("uq_provider_configs_global_provider", "provider_configs", ["provider"],
                    unique=True, postgresql_where=sa.text("visibility = 'global'"))
    op.create_index("uq_provider_configs_group_provider", "provider_configs",
                    ["group_id", "provider"], unique=True,
                    postgresql_where=sa.text("visibility = 'group'"))
