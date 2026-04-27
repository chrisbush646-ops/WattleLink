import json
from django.core import serializers
from .models import AuditLog


def _serialize_entity(entity):
    if entity is None:
        return None
    data = serializers.serialize("python", [entity])
    return data[0]["fields"] if data else None


def log_action(request, entity, action, before=None, after=None):
    tenant = getattr(request, "tenant", None)
    user = request.user if request.user.is_authenticated else None

    if tenant is None and user is not None:
        tenant = getattr(user, "tenant", None)

    AuditLog.objects.create(
        tenant=tenant,
        user=user,
        entity_type=entity.__class__.__name__,
        entity_id=entity.pk,
        action=action,
        before_state=_serialize_entity(before) if not isinstance(before, dict) else before,
        after_state=_serialize_entity(after) if not isinstance(after, dict) else after,
    )
