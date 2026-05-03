def build_methodology_section(summary) -> str:
    """
    Build a structured methodology paragraph for a literature review from a
    PaperSummary's structured methodology dict. Returns plain text suitable
    for inclusion in AI-drafted lit review documents.
    """
    m = summary.methodology or {}
    if not isinstance(m, dict) or not m:
        return ""

    parts = []

    design = (m.get("study_design") or "").strip()
    pop = m.get("population") or {}
    n = ((pop.get("sample_size") or "").strip() if isinstance(pop, dict) else "")
    setting = (m.get("setting") or "").strip()
    follow_up = (m.get("follow_up") or "").strip()

    if design and n:
        sentence = f"This was a {design} (N={n})"
        if setting:
            sentence += f" conducted {setting}"
        if follow_up:
            sentence += f" with {follow_up} follow-up"
        parts.append(sentence + ".")
    elif design:
        sentence = f"This was a {design}"
        if setting:
            sentence += f" conducted {setting}"
        parts.append(sentence + ".")

    intervention = (m.get("intervention") or "").strip()
    comparator = (m.get("comparator") or "").strip()
    if intervention:
        if comparator and comparator.lower() not in ("none (single arm)", "not reported"):
            parts.append(f"Patients received {intervention} versus {comparator}.")
        else:
            parts.append(f"Patients received {intervention}.")

    primary_ep = (m.get("primary_endpoint") or "").strip()
    if primary_ep:
        parts.append(f"The primary endpoint was {primary_ep}.")

    secondary_eps = m.get("secondary_endpoints") or []
    if secondary_eps:
        joined = "; ".join(secondary_eps)
        parts.append(f"Secondary endpoints included {joined}.")

    stats = (m.get("statistical_methods") or "").strip()
    if stats and stats.lower() != "not reported":
        parts.append(f"Statistical analysis: {stats}.")

    return " ".join(parts)
