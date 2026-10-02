from types import SimpleNamespace

from app.domain.identity.scope_policy import can_create_global, can_create_group, can_create_personal, get_allowed_scopes, resolve_config_scope


def test_scope_policy_uses_the_role_of_the_specific_group_membership():
    user = SimpleNamespace(role="runner", memberships={"a": "group_manager", "b": "member"})
    assert can_create_group(user, "a")
    assert not can_create_group(user, "b")
    assert resolve_config_scope(user, "a") == "group"
    assert resolve_config_scope(user, "b") is None


def test_admin_and_personal_scope_policy():
    admin = SimpleNamespace(role="admin", memberships={})
    ordinary_user = SimpleNamespace(role="viewer", memberships={})
    assert can_create_personal(ordinary_user)
    assert can_create_global(admin)
    assert not can_create_global(ordinary_user)
    assert get_allowed_scopes(admin, []) == {"personal": True, "groups": [], "global": True}
