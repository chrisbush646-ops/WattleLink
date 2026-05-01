from .managers import set_current_tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = None
        if request.user.is_authenticated and hasattr(request.user, "tenant"):
            tenant = request.user.tenant
        request.tenant = tenant
        set_current_tenant(tenant)

        # Flag inactive tenants so views can respond appropriately
        request.tenant_inactive = bool(tenant and not tenant.is_active)

        response = self.get_response(request)

        set_current_tenant(None)
        return response
