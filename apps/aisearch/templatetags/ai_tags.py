import re
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def ai_markdown(text: str) -> str:
    """Convert a subset of markdown (headers, bold, lists, code) to safe HTML."""
    if not text:
        return ""

    lines = text.split("\n")
    out = []
    in_list = False
    in_code = False

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append('<pre style="background:var(--line-soft);border-radius:6px;padding:10px 12px;font-size:11.5px;overflow-x:auto;margin:8px 0"><code>')
                in_code = True
            continue

        if in_code:
            out.append(_esc(line))
            continue

        stripped = line.strip()

        # Blank line
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("")
            continue

        # Headers
        if stripped.startswith("### "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f'<h3 style="font-family:var(--serif);font-size:13px;font-weight:600;color:var(--ink);margin:12px 0 3px">{_inline(_esc(stripped[4:]))}</h3>')
            continue
        if stripped.startswith("## "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f'<h2 style="font-family:var(--serif);font-size:14px;font-weight:600;color:var(--ink);margin:14px 0 4px">{_inline(_esc(stripped[3:]))}</h2>')
            continue
        if stripped.startswith("# "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f'<h1 style="font-family:var(--serif);font-size:15px;font-weight:600;color:var(--ink);margin:14px 0 4px">{_inline(_esc(stripped[2:]))}</h1>')
            continue

        # List items
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append('<ul style="margin:4px 0 8px;padding-left:18px">')
                in_list = True
            out.append(f'<li style="margin-bottom:3px">{_inline(_esc(stripped[2:]))}</li>')
            continue

        # Numbered list
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            if not in_list:
                out.append('<ol style="margin:4px 0 8px;padding-left:18px">')
                in_list = True
            out.append(f'<li style="margin-bottom:3px">{_inline(_esc(m.group(2)))}</li>')
            continue

        # Blockquote
        if stripped.startswith("> "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f'<blockquote style="border-left:3px solid var(--euc-l);margin:6px 0;padding:3px 12px;color:var(--muted);font-style:italic">{_inline(_esc(stripped[2:]))}</blockquote>')
            continue

        # Paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f'<p style="margin:0 0 7px;line-height:1.6">{_inline(_esc(stripped))}</p>')

    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")

    return mark_safe("\n".join(out))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s: str) -> str:
    """Handle **bold**, *italic*, and `code` inline."""
    s = re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', s)
    s = re.sub(r"\*(.+?)\*", r'<em>\1</em>', s)
    s = re.sub(r"`(.+?)`", r'<code style="font-family:var(--mono);font-size:11.5px;background:var(--line-soft);padding:1px 5px;border-radius:4px">\1</code>', s)
    return s
