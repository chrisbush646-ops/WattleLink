import re


def validate_summary(summary_data: dict, paper_text: str) -> list[str]:
    """
    Check a parsed summary JSON against the source paper text.
    Returns a list of warning strings; empty list means no issues detected.

    These checks are heuristic — a clean result does not guarantee accuracy.
    All AI output must still be reviewed by a human before confirmation.
    """
    warnings = []
    findings = summary_data.get("findings", [])
    paper_lower = paper_text.lower()

    # a. Every finding's quantitative_result must contain at least one digit.
    for i, finding in enumerate(findings, 1):
        qr = finding.get("quantitative_result", "")
        if qr and qr.strip().lower() != "not reported" and not re.search(r"\d", qr):
            warnings.append(
                f"Finding {i} has no numbers in quantitative_result — verify or mark 'not reported'"
            )

    # b. Each number in quantitative_result must appear verbatim in the paper text.
    for i, finding in enumerate(findings, 1):
        qr = finding.get("quantitative_result", "")
        if not qr or qr.strip().lower() == "not reported":
            continue
        numbers = re.findall(r"\d+\.?\d*", qr)
        unverified = [n for n in numbers if n not in paper_text]
        if unverified:
            warnings.append(
                f"Statistic(s) {unverified} in finding {i} not found verbatim in source text — verify manually"
            )

    # c. Executive summary word count must be 100–250.
    exec_text = summary_data.get("executive_summary", "")
    word_count = len(exec_text.split()) if exec_text.strip() else 0
    if word_count < 100:
        warnings.append(
            f"Executive summary is {word_count} words — expected 100–250; may be too brief for MSL use"
        )
    elif word_count > 250:
        warnings.append(
            f"Executive summary is {word_count} words — expected 100–250; consider condensing"
        )

    # d. Non-empty confidence_flags means the AI had uncertainties.
    flags = summary_data.get("confidence_flags", [])
    if flags:
        n = len(flags)
        warnings.append(
            f"AI flagged {n} uncertainty item{'s' if n != 1 else ''} — review carefully before confirming"
        )

    # e. Every finding must have a non-empty source_reference.
    for i, finding in enumerate(findings, 1):
        ref = finding.get("source_reference", "").strip()
        if not ref or ref == "[LOCATION NOT FOUND]":
            label = "[LOCATION NOT FOUND]" if ref == "[LOCATION NOT FOUND]" else "missing"
            warnings.append(
                f"Finding {i} source reference is {label} — locate in paper before confirming"
            )

    # f. Safety profile summary must contain at least one number.
    safety = summary_data.get("safety_profile", {})
    if isinstance(safety, dict):
        safety_text = safety.get("summary", "")
    else:
        safety_text = str(safety)
    if safety_text.strip() and not re.search(r"\d", safety_text):
        warnings.append(
            "Safety profile summary contains no statistics — verify adverse event rates are included"
        )

    # h. Methodology structure checks.
    methodology = summary_data.get("methodology", {})
    if isinstance(methodology, dict) and methodology:
        # sample_size in executive_summary must match methodology.population.sample_size
        pop = methodology.get("population", {})
        sample_size = (pop.get("sample_size", "") if isinstance(pop, dict) else "").strip()
        if sample_size and sample_size.lower() not in ("not reported", ""):
            ns = re.findall(r"\d[\d,]*", sample_size)
            if ns:
                for n in ns:
                    bare = n.replace(",", "")
                    if bare not in exec_text and n not in exec_text:
                        warnings.append(
                            f"Executive summary sample size may not match methodology "
                            f"(methodology.population.sample_size={sample_size!r}) — verify consistency"
                        )
                        break

        required_fields = ["study_design", "intervention", "primary_endpoint", "follow_up"]
        missing_fields = [
            f for f in required_fields
            if not (methodology.get(f, "") or "").strip()
            or (methodology.get(f, "") or "").strip().lower() == "not reported"
        ]
        if missing_fields:
            warnings.append(
                f"Methodology missing key fields: {', '.join(missing_fields)} — review source paper"
            )

    # g. Certainty upgrade: paper says "may be associated" but summary says "is associated".
    if "may be associated" in paper_lower:
        exec_lower = exec_text.lower()
        findings_text = " ".join(f.get("finding", "") for f in findings).lower()
        combined = exec_lower + " " + findings_text
        if re.search(r"\bis associated\b", combined) and "may be associated" not in combined:
            warnings.append(
                "Possible certainty upgrade detected — paper uses 'may be associated' but summary "
                "uses 'is associated'; verify hedging language is preserved"
            )

    return warnings
