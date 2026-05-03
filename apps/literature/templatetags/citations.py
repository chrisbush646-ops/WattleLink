import json

from django import template
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def tojson(value):
    """Render a Python value as a JSON literal safe for inline HTML data attributes."""
    return mark_safe(json.dumps(value))


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


@register.simple_tag
def apa7_doi_html(paper):
    """
    Render the DOI portion of an APA7 citation as safe HTML.
    - Verified: clickable link
    - Unverified (doi present but not verified): text with warning icon
    - Empty or failed: nothing
    """
    if paper is None:
        return mark_safe("")
    doi = getattr(paper, "doi", "") or ""
    if not doi:
        return mark_safe("")
    verified = getattr(paper, "doi_verified", False)
    if verified:
        return format_html(
            ' <a href="https://doi.org/{}" target="_blank" rel="noopener"'
            ' style="font-family:var(--mono);font-size:inherit;color:var(--euc)">'
            "https://doi.org/{}</a>",
            doi, doi,
        )
    # Unverified — show with warning icon but no link
    return format_html(
        ' <span style="font-family:var(--mono);font-size:inherit;color:var(--muted)">'
        '{}'
        ' <span title="DOI not yet verified against CrossRef" style="color:#8A6918;cursor:help">'
        '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle">'
        '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'
        '</svg>'
        "</span></span>",
        doi,
    )


@register.inclusion_tag("components/apa7_citation.html")
def apa7_block(paper):
    """Render a copyable APA7 citation block."""
    return {"paper": paper, "citation": paper.apa7_citation() if paper else ""}
