def build_study_context(summary) -> str:
    """
    Build a plain-text study context block from a PaperSummary for use in
    talking points and other AI-drafted documents. Pulls from the structured
    methodology dict and confirmed findings rows.
    """
    lines = []
    m = summary.methodology or {}

    if isinstance(m, dict) and m:
        design = (m.get("study_design") or "").strip()
        if design:
            lines.append(f"Study design: {design}")

        pop = m.get("population") or {}
        if isinstance(pop, dict):
            n = (pop.get("sample_size") or "").strip()
            desc = (pop.get("description") or "").strip()
            demo = (pop.get("demographics") or "").strip()
            if n:
                lines.append(f"Sample size: {n}")
            if desc:
                lines.append(f"Population: {desc}")
            if demo:
                lines.append(f"Demographics: {demo}")

        intervention = (m.get("intervention") or "").strip()
        comparator = (m.get("comparator") or "").strip()
        if intervention:
            lines.append(f"Intervention: {intervention}")
        if comparator:
            lines.append(f"Comparator: {comparator}")

        follow_up = (m.get("follow_up") or "").strip()
        if follow_up:
            lines.append(f"Follow-up: {follow_up}")

        primary_ep = (m.get("primary_endpoint") or "").strip()
        if primary_ep:
            lines.append(f"Primary endpoint: {primary_ep}")

        secondary_eps = m.get("secondary_endpoints") or []
        if secondary_eps:
            lines.append("Secondary endpoints: " + "; ".join(secondary_eps))

        stats = (m.get("statistical_methods") or "").strip()
        if stats:
            lines.append(f"Statistical methods: {stats}")

        setting = (m.get("setting") or "").strip()
        if setting:
            lines.append(f"Setting: {setting}")

    lines.append("")
    lines.append("Key findings:")
    for row in summary.findings.filter(category__in=["Primary", "Secondary"]).order_by("order"):
        result_part = f" ({row.quantitative_result})" if row.quantitative_result else ""
        ref_part = f" [{row.page_ref}]" if row.page_ref else ""
        lines.append(f"  [{row.category}] {row.finding}{result_part}{ref_part}")

    if summary.safety_summary:
        lines.append("")
        lines.append(f"Safety: {summary.safety_summary}")

    return "\n".join(lines)
