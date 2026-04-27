import threading
from django.db import models

_thread_locals = threading.local()


def set_current_tenant(tenant):
    _thread_locals.tenant = tenant


def get_current_tenant():
    return getattr(_thread_locals, "tenant", None)


class TenantQuerySet(models.QuerySet):
    pass


class TenantManager(models.Manager):
    """
    Auto-scopes querysets to the current request's tenant.
    Falls back to unscoped if no tenant is set (e.g. management commands).
    """

    def get_queryset(self):
        qs = TenantQuerySet(self.model, using=self._db)
        tenant = get_current_tenant()
        if tenant is not None:
            return qs.filter(tenant=tenant)
        return qs


class UnfilteredManager(models.Manager):
    """Cross-tenant access for admin and internal tooling."""

    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)
