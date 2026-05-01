def user_permissions(request):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return {
            "can_edit": user.can_edit,
            "is_platform_admin": user.is_admin_role,
        }
    return {"can_edit": False, "is_platform_admin": False}
