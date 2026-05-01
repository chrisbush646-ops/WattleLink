from django import template
from django.utils.html import format_html, escape

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, "")


@register.filter
def apa7(paper):
    """Render APA7 citation string for a Paper instance."""
    if paper is None:
        return ""
    if hasattr(paper, "apa7_citation"):
        return paper.apa7_citation()
    return str(paper)


@register.inclusion_tag("components/apa7_citation.html")
def apa7_block(paper):
    """Render a copyable APA7 citation block."""
    return {"paper": paper, "citation": paper.apa7_citation() if paper else ""}
