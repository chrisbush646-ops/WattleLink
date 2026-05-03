import re
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s: str) -> str:
    """Handle **bold**, *italic*, and `code` inline."""
    s = re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', s)
    s = re.sub(r"\*(.+?)\*", r'<em>\1</em>', s)
    s = re.sub(r"`(.+?)`", r'<code style="font-family:var(--mono);font-size:11.5px;background:var(--line-soft);padding:1px 5px;border-radius:4px">\1</code>', s)
    return s


def _is_sep_row(line: str) -> bool:
    t = line.strip()
    return bool("|" in t and "-" in t and re.match(r"^\|?[\s:|-]+\|?$", t))


def _parse_table_row(line: str) -> list[str]:
    parts = line.strip().split("|")
    start = 1 if parts[0].strip() == "" else 0
    end = len(parts) - 1 if parts[-1].strip() == "" else len(parts)
    return [c.strip() for c in parts[start:end]]


def _render_table(table_lines: list[str]) -> str:
    data_lines = [l for l in table_lines if not _is_sep_row(l) and l.strip()]
    if not data_lines:
        return ""
    header = _parse_table_row(data_lines[0])
    body = [_parse_table_row(l) for l in data_lines[1:]]
    ths = "".join(f"<th>{_inline(_esc(h))}</th>" for h in header)
    trs = "".join(
        f'<tr>{"".join(f"<td>{_inline(_esc(c))}</td>" for c in row)}</tr>'
        for row in body
    )
    return (
        '<div class="ai-table-wrap">'
        '<table class="ai-table">'
        f"<thead><tr>{ths}</tr></thead>"
        f"<tbody>{trs}</tbody>"
        "</table></div>"
    )


@register.filter
def ai_markdown(text: str) -> str:
    """Convert markdown (headers, bold, lists, tables, code, HR) to safe HTML."""
    if not text:
        return ""

    lines = text.split("\n")
    out = []
    in_list = False
    in_ol = False
    in_code = False
    in_references = False
    table_lines: list[str] = []

    def flush_list():
        nonlocal in_list, in_ol
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def flush_table():
        if table_lines:
            out.append(_render_table(table_lines))
            table_lines.clear()

    for idx, line in enumerate(lines):
        # --- Fenced code blocks ---
        if line.strip().startswith("```"):
            flush_list()
            flush_table()
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append('<pre style="background:var(--line-soft);border-radius:6px;padding:10px 12px;font-size:11.5px;overflow-x:auto;margin:8px 0"><code>')
                in_code = True
            continue

        if in_code:
            out.append(_esc(line))
            continue

        stripped = line.strip()

        # --- Table detection ---
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        is_table_row = stripped.startswith("|")
        is_implicit_header = (
            not is_table_row
            and not table_lines
            and bool(next_line)
            and _is_sep_row(next_line)
        )

        if is_table_row or _is_sep_row(line) or is_implicit_header:
            flush_list()
            table_lines.append(line)
            continue

        # Flush any accumulated table when we hit a non-table line
        flush_table()

        # --- Blank line ---
        if not stripped:
            flush_list()
            out.append("")
            continue

        # --- HR ---
        if stripped in ("---", "***", "___"):
            flush_list()
            out.append('<hr style="border:none;border-top:1px solid var(--line);margin:14px 0">')
            continue

        # --- Headers ---
        if stripped.startswith("### "):
            flush_list()
            out.append(f'<h3 style="font-family:var(--serif);font-size:13px;font-weight:600;color:var(--ink);margin:12px 0 3px">{_inline(_esc(stripped[4:]))}</h3>')
            continue
        if stripped.startswith("## "):
            flush_list()
            heading_text = stripped[3:]
            if heading_text.strip().lower() == "references":
                if in_references:
                    out.append("</div>")
                out.append('<div class="ai-references"><p style="font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:0 0 8px">References</p>')
                in_references = True
            else:
                if in_references:
                    out.append("</div>")
                    in_references = False
                out.append(f'<h2 style="font-family:var(--serif);font-size:14px;font-weight:600;color:var(--ink);margin:14px 0 4px">{_inline(_esc(heading_text))}</h2>')
            continue
        if stripped.startswith("# "):
            flush_list()
            out.append(f'<h1 style="font-family:var(--serif);font-size:15px;font-weight:600;color:var(--ink);margin:14px 0 4px">{_inline(_esc(stripped[2:]))}</h1>')
            continue

        # --- Unordered list ---
        if stripped.startswith("- ") or stripped.startswith("* "):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_list:
                out.append('<ul style="margin:4px 0 8px;padding-left:18px">')
                in_list = True
            out.append(f'<li style="margin-bottom:3px">{_inline(_esc(stripped[2:]))}</li>')
            continue

        # --- Ordered list ---
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            if not in_ol:
                out.append('<ol style="margin:4px 0 8px;padding-left:18px">')
                in_ol = True
            out.append(f'<li style="margin-bottom:3px">{_inline(_esc(m.group(2)))}</li>')
            continue

        # --- Blockquote ---
        if stripped.startswith("> "):
            flush_list()
            out.append(f'<blockquote style="border-left:3px solid var(--euc-l);margin:6px 0;padding:3px 12px;color:var(--muted);font-style:italic">{_inline(_esc(stripped[2:]))}</blockquote>')
            continue

        # --- Paragraph ---
        flush_list()
        out.append(f'<p style="margin:0 0 7px;line-height:1.6">{_inline(_esc(stripped))}</p>')

    flush_list()
    flush_table()
    if in_code:
        out.append("</code></pre>")
    if in_references:
        out.append("</div>")

    return mark_safe("\n".join(out))
