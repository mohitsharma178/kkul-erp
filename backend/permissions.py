from functools import wraps

from flask import abort
from flask_login import current_user


ROLE_PERMISSIONS = {
    "admin": {
        "dashboard",
        "inventory",
        "inward",
        "plants",
        "supervisors",
        "issues",
        "daily_limits",
        "reports",
        "users",
    },
    "godown_incharge": {
        "dashboard",
        "inventory",
        "inward",
        "plants",
        "supervisors",
        "issues",
        "daily_limits",
        "reports",
    },
    "godown_supervisor": {
        "dashboard",
        "inventory",
        "issues",
        "reports",
    },
    "godown": {
        "dashboard",
        "inventory",
        "inward",
        "plants",
        "supervisors",
        "issues",
        "daily_limits",
        "reports",
    },
    "shift": {
        "reports",
    },
    "viewer": {
        "reports",
    },
}


def has_permission(module):
    """Check whether the logged-in user can access a module."""
    if not current_user.is_authenticated:
        return False

    allowed_modules = ROLE_PERMISSIONS.get(current_user.role, set())
    return module in allowed_modules


def permission_required(module):
    """Protect a backend route using the user's role permissions."""

    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not has_permission(module):
                abort(403)

            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator


def roles_required(*roles):
    """Allow access only to users with one of the specified roles."""

    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if current_user.role not in roles:
                abort(403)

            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator