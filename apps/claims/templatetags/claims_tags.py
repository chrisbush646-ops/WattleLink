import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def tojson(value):
    """Render a Python value as a JSON literal safe for inline JS."""
    return mark_safe(json.dumps(value))
