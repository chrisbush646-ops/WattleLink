import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# ── Section heading patterns ──────────────────────────────────────────────────

_REFS_HEADING_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:\d+\.?\s+)?'
    r'(?:references?(?:\s+and\s+notes)?|bibliography|reference\s+list)\s*(?:\n|$)',
    re.IGNORECASE,
)

_ACK_HEADING_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:\d+\.?\s+)?'
    r'(?:acknowledgements?|acknowledgments?|funding(?:\s+source)?(?:\s+information)?|'
    r'financial\s+(?:support|disclosure)|grant\s+support)\s*(?:\n|$)',
    re.IGNORECASE,
)

# Sections that follow Acknowledgements/Funding — stop removing at these
_ACK_STOP_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:\d+\.?\s+)?'
    r'(?:references?|bibliography|conflict\s+of\s+interest|'
    r'author\s+contributions?|supplementary|appendix|'
    r'data\s+availability|ethics|declarations)\s*(?:\n|$)',
    re.IGNORECASE,
)

# Copyright / publisher boilerplate (full-line match)
_COPYRIGHT_LINE_RE = re.compile(
    r'^[ \t]*(?:'
    r'©\s*\d{4}|'
    r'copyright\s+(?:\(c\)\s*)?\d{4}|'
    r'published\s+by\s+\w[\w\s]*?(?:ltd|inc|bv|llc|gmbh)?|'
    r'elsevier(?:\s+ltd)?|'
    r'creative\s+commons|'
    r'(?:this\s+is\s+an?\s+)?open[\s-]access\s+article|'
    r'under\s+the\s+(?:terms|cc\s+by|creative)|'
    r'licen[cs]e\s*:|'
    r'all\s+rights\s+reserved'
    r').*$',
    re.IGNORECASE | re.MULTILINE,
)

# Email addresses
_EMAIL_RE = re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b')

# ORCID identifiers
_ORCID_RE = re.compile(
    r'(?:https?://orcid\.org/|orcid:?\s*)\d{4}-\d{4}-\d{4}-\d{3}[\dXx]'
    r'|\b\d{4}-\d{4}-\d{4}-\d{3}[\dXx]\b',
    re.IGNORECASE,
)

# Numbered institutional affiliation lines at start of document
_AFFIL_LINE_RE = re.compile(
    r'^[\d\s\*\†\‡]+\s*(?:department|faculty|school|institute|division|'
    r'centre|center|hospital|university|college|clinic|laboratory|lab)\b',
    re.IGNORECASE,
)

# Inline supplementary cross-references (kept as empty string, not a section removal)
_SUPP_REF_RE = re.compile(
    r'(?:(?:see|refer\s+to)\s+)?'
    r'(?:supplementary|online\s+supplement(?:ary)?|electronic\s+supplement(?:ary)?)\s+'
    r'(?:table|figure|fig\.|data|methods?|materials?|appendix|information)\s*[a-z0-9]*\.?',
    re.IGNORECASE,
)


# ── Section removal helpers ───────────────────────────────────────────────────

def _remove_from_heading(text: str, heading_re: re.Pattern,
                          stop_re: re.Pattern | None = None) -> tuple[str, bool]:
    """
    Remove text from the first match of heading_re to stop_re (or end of document).
    Returns (modified_text, was_found).
    """
    match = heading_re.search(text)
    if not match:
        return text, False
    start = match.start()
    if stop_re:
        stop = stop_re.search(text, match.end())
        end = stop.start() if stop else len(text)
    else:
        end = len(text)
    return text[:start] + text[end:], True


def _remove_author_affiliations(text: str) -> tuple[str, bool]:
    """
    Remove author affiliation blocks from the first 3 000 characters.
    Targets: email addresses, ORCID IDs, numbered institutional address lines.
    """
    zone = text[:3000]
    lines = zone.splitlines()
    out = []
    removed = False
    blank_after_affil = False

    for line in lines:
        s = line.strip()
        is_affil = (
            bool(_EMAIL_RE.search(s))
            or bool(_ORCID_RE.search(s))
            or bool(_AFFIL_LINE_RE.match(s))
        )
        if is_affil:
            removed = True
            blank_after_affil = True
            continue
        if blank_after_affil and not s:
            blank_after_affil = False
            continue
        blank_after_affil = False
        out.append(line)

    return "\n".join(out) + text[3000:], removed


def _remove_repeated_headers_footers(text: str) -> tuple[str, bool]:
    """
    Remove short lines (< 120 chars) that appear 3+ times — page headers/footers.
    """
    lines = text.splitlines()
    counts = Counter(ln.strip() for ln in lines if ln.strip() and len(ln.strip()) < 120)
    repeated = {ln for ln, n in counts.items() if n >= 3}
    if not repeated:
        return text, False
    return "\n".join(ln for ln in lines if ln.strip() not in repeated), True


def _remove_copyright_lines(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    out = []
    removed = False
    for line in lines:
        if _COPYRIGHT_LINE_RE.match(line.strip()):
            removed = True
        else:
            out.append(line)
    return "\n".join(out), removed


def _collapse_blank_lines(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    out = []
    blank_run = 0
    for ln in lines:
        if not ln.strip():
            blank_run += 1
            if blank_run == 1:
                out.append("")
        else:
            blank_run = 0
            out.append(ln)
    return "\n".join(out).strip()


# ── Public API ────────────────────────────────────────────────────────────────

def prepare_text_for_ai(full_text: str) -> tuple[str, dict]:
    """
    Strip content that adds tokens without adding clinical value.
    Returns (cleaned_text, stats_dict).

    Always store the original full_text unchanged on the Paper model.
    Only use the cleaned text for AI calls.

    Sections preserved: Title, Abstract, Introduction, Methods, Results,
    Discussion, Tables, Figure captions, Limitations, Conclusions,
    Conflict of Interest.
    """
    if not full_text:
        return "", {"original_tokens": 0, "cleaned_tokens": 0,
                    "reduction_pct": 0.0, "sections_removed": []}

    original_len = len(full_text)
    text = full_text
    removed = []

    # a. Remove References / Bibliography to end of document
    text, found = _remove_from_heading(text, _REFS_HEADING_RE)
    if found:
        removed.append("References")

    # b. Remove author affiliation blocks at the start
    text, found = _remove_author_affiliations(text)
    if found:
        removed.append("Author affiliations")

    # c. Remove copyright notices and publisher boilerplate
    text, found = _remove_copyright_lines(text)
    if found:
        removed.append("Copyright/boilerplate")

    # d. Remove repeated page headers and footers (3+ occurrences)
    text, found = _remove_repeated_headers_footers(text)
    if found:
        removed.append("Page headers/footers")

    # e. Remove Acknowledgements / Funding — stop at References / COI / etc.
    text, found = _remove_from_heading(text, _ACK_HEADING_RE, stop_re=_ACK_STOP_RE)
    if found:
        removed.append("Acknowledgements/Funding")

    # f. Remove inline supplementary cross-references
    cleaned = _SUPP_REF_RE.sub("", text)
    if cleaned != text:
        removed.append("Supplementary references")
    text = cleaned

    # g. Collapse multiple blank lines; strip trailing whitespace per line
    text = _collapse_blank_lines(text)

    original_tokens = original_len // 4
    cleaned_tokens = len(text) // 4
    reduction_pct = round((1 - len(text) / original_len) * 100, 1) if original_len else 0.0

    logger.info(
        "Text preprocessing: %d → %d tokens (%.1f%% reduction); removed: %s",
        original_tokens, cleaned_tokens, reduction_pct,
        ", ".join(removed) if removed else "none",
    )

    return text, {
        "original_tokens": original_tokens,
        "cleaned_tokens": cleaned_tokens,
        "reduction_pct": reduction_pct,
        "sections_removed": removed,
    }
