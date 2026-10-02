"""Shared authorization policy for personal, group, and global configuration scopes."""


def _role(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "value", role))


def _memberships(user) -> dict[str, str]:
    memberships = getattr(user, "memberships", {}) or {}
    return {group_id: str(getattr(role, "value", role)) for group_id, role in memberships.items()}


def can_create_personal(user) -> bool:
    return user is not None


def can_create_group(user, group_id: str) -> bool:
    return _role(user) == "admin" or _memberships(user).get(group_id) == "group_manager"


def can_create_global(user) -> bool:
    return _role(user) == "admin"


def get_allowed_scopes(user, groups) -> dict:
    memberships = _memberships(user)
    group_ids = {group.get("id") if isinstance(group, dict) else group.id for group in groups}
    return {
        "personal": can_create_personal(user),
        "groups": sorted(group_id for group_id, role in memberships.items()
                         if role == "group_manager" and group_id in group_ids),
        "global": can_create_global(user),
    }


def resolve_config_scope(user, group_id: str | None) -> str | None:
    if group_id is not None:
        return "group" if can_create_group(user, group_id) else None
    return "global" if can_create_global(user) else "personal" if can_create_personal(user) else None
