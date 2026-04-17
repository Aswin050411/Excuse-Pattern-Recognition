"""
Permission Utility Functions
=============================
Central permission checking and role-hierarchy validation.

Design note — two complementary systems:
  has_permission(role, action)        — fine-grained action-level checks
  role_hierarchy_check(required, actual) — coarse "at least X" checks

Both respect the same hierarchy: employee < manager < admin.
Managers implicitly inherit all employee permissions (see _ROLE_PERMISSIONS).
"""
import logging
from enum import IntEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role hierarchy — single definition used by both permission systems.
# ---------------------------------------------------------------------------

class RoleLevel(IntEnum):
    """Numeric hierarchy for role comparison. Higher value = more privilege."""
    employee = 1
    manager  = 2
    admin    = 3


def _role_level(role: str) -> int:
    """Return the numeric level for a role string, or 0 for unknown roles."""
    try:
        return RoleLevel[role].value
    except KeyError:
        return 0


# Legacy mapping for backward compatibility with flask_auth.py
ROLE_LEVELS = {r.name: r.value for r in RoleLevel}


def can_manage(actor_role: str, target_role: str) -> bool:
    """Return True if actor_role is strictly higher than target_role."""
    return _role_level(actor_role) > _role_level(target_role)


# ---------------------------------------------------------------------------
# Permission table — defined once at module level so it can be audited and
# tested without calling any function.
#
# Convention: each role lists *only* the permissions it adds beyond the role
# below it. has_permission() resolves the full set via the hierarchy.
# ---------------------------------------------------------------------------

_EMPLOYEE_PERMISSIONS: frozenset[str] = frozenset([
    'view_own_tasks',
    'complete_task',
    'submit_delay',
    'use_chatbot',
    'view_own_analytics',
    'edit_own_profile',
])

_MANAGER_EXTRA_PERMISSIONS: frozenset[str] = frozenset([
    'view_team_tasks',
    'create_task',
    'assign_task',
    'view_team_analytics',
    'export_reports',
    'view_employee_profiles',
])

# Derived sets — managers inherit employee permissions automatically.
_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    'employee': _EMPLOYEE_PERMISSIONS,
    'manager':  _EMPLOYEE_PERMISSIONS | _MANAGER_EXTRA_PERMISSIONS,
    # 'admin' uses wildcard logic; explicit set kept for documentation.
    'admin':    frozenset(['*']),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def has_permission(user_role: str, action: str) -> bool:
    """
    Return True if user_role may perform action.

    Admin has universal access. Unknown roles are denied and logged as a
    warning so misconfigured roles surface during development.

    Args:
        user_role: Role string ('employee', 'manager', 'admin').
        action:    Permission key to check (e.g. 'create_task').
    """
    if user_role == 'admin':
        return True

    allowed = _ROLE_PERMISSIONS.get(user_role)
    if allowed is None:
        logger.warning("has_permission: unknown role %r — denying action %r", user_role, action)
        return False

    return action in allowed


def role_hierarchy_check(required_role: str, user_role: str) -> bool:
    """
    Return True if user_role meets or exceeds required_role in the hierarchy.

    Use this for coarse "at least manager" guards. For action-level checks,
    prefer has_permission() so the permission table stays the source of truth.

    Args:
        required_role: Minimum acceptable role ('employee', 'manager', 'admin').
        user_role:     The user's actual role.
    """
    user_level     = _role_level(user_role)
    required_level = _role_level(required_role)

    if user_level == 0:
        logger.warning("role_hierarchy_check: unknown user_role %r", user_role)
    if required_level == 0:
        logger.warning("role_hierarchy_check: unknown required_role %r", required_role)

    return user_level >= required_level and user_level > 0


def check_task_ownership(task, user_id: int, user_role: str) -> bool:
    """
    Return True if the user may access task.

    Accepts a pre-fetched task dict rather than a task_id so this function
    has no repository dependency and can be unit tested without a database.
    The caller is responsible for fetching the task and handling the
    not-found case (which is a different concern from authorisation).

    Args:
        task:      Task dict with at least an 'assigned_to' key.
        user_id:   The requesting user's ID.
        user_role: The requesting user's role.

    Raises:
        TypeError: If task is None (caller should check existence first).
    """
    if task is None:
        raise TypeError(
            "check_task_ownership received None for task. "
            "Fetch the task and handle the not-found case before calling this function."
        )

    # Admins and managers have full access.
    if role_hierarchy_check('manager', user_role):
        return True

    # Employees may only access tasks assigned to them.
    return task.get('assigned_to') == user_id
