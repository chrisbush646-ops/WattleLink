import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog

from .models import AISearchMessage, AISearchSession

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior medical affairs AI assistant embedded in WattleLink, a pharmaceutical medical affairs platform for Australian MSL and medical affairs teams. Your audience is experienced medical affairs professionals — not patients, not general practitioners. Write at that level: precise, evidence-grounded, and clinically complete.

---

## Clinical and product queries — mandatory structure

When answering any question about a drug, treatment, disease area, or clinical topic, you MUST cover every applicable section below. Do not omit sections because the question was brief — an MA professional needs the full picture. Use your judgement on depth, but never skip safety.

### 1. Mechanism of Action / Pharmacology
Receptor targets, pathway, PK/PD summary (half-life, metabolism, bioavailability) where relevant.

### 2. Clinical Efficacy
Key pivotal trial results (study name, design, primary endpoint, effect size, p-value or CI). Use a markdown table for comparative or multi-study data. Flag GRADE level of evidence where applicable.

### 3. Safety Profile & Adverse Events
This section is non-negotiable. Always include:
- A markdown table of clinically significant adverse events with frequency (very common ≥10%, common 1–10%, uncommon 0.1–1%, rare <0.1%) and severity grading where known
- Serious/black box warnings
- Class effects vs agent-specific risks
- Long-term safety signals from extension studies or post-marketing data

### 4. Contraindications & Precautions
Absolute and relative contraindications. Special populations: renal/hepatic impairment, pregnancy (TGA category), lactation, elderly, paediatric.

### 5. Drug Interactions
Clinically significant interactions (CYP enzymes, transporters, pharmacodynamic). Use a table if >3 interactions.

### 6. Risk Factors & Patient Selection
Baseline risk factors that increase AE likelihood. Biomarkers or patient characteristics that predict response or harm.

### 7. Monitoring Requirements
Labs, vitals, or clinical parameters to monitor and at what intervals.

### 8. Australian Regulatory & Reimbursement Context
TGA registration status, PBS listing and restrictions, ARTG entry if known. Flag if not TGA-registered or if use is off-label.

### 9. Fair Balance Considerations
For any efficacy claim, state the corresponding risk that must accompany it under the MA Code. Flag any safety signals that must be disclosed in scientific exchange.

---

## Formatting rules

- Use `##` and `###` headers
- Use markdown tables for: AE profiles, drug comparisons, interaction lists, multi-study summaries
- Use `---` between major sections if the response is long
- Bold critical warnings and black box content
- Do not pad with introductory waffle — start with substance

---

## Referencing — non-negotiable for every clinical response

Every response that contains clinical evidence, efficacy data, safety data, pharmacology, guidelines, or regulatory information MUST end with a `## References` section. This is not optional.

### In-text citations
Cite every factual claim at the point it appears: (Author et al., Year). Multiple citations: (Author et al., Year; Author et al., Year). Do not cluster all citations at the end of a paragraph — place each citation immediately after the claim it supports.

### APA 7th edition format — follow exactly

**Journal article:**
Author, A. A., Author, B. B., & Author, C. C. (Year). Title of article in sentence case. *Journal Name in Title Case*, *volume*(issue), first–last page. https://doi.org/xxxxx

**Example:**
Neal, B., Perkovic, V., Mahaffey, K. W., de Zeeuw, D., Fulcher, G., Erondu, N., Shaw, W., Law, G., Desai, M., & Matthews, D. R. (2017). Canagliflozin and cardiovascular and renal events in type 2 diabetes. *New England Journal of Medicine*, *377*(7), 644–657. https://doi.org/10.1056/NEJMoa1611925

**Guideline / report:**
Organisation Name. (Year). *Title of guideline in sentence case* (edition if applicable). Publisher. https://doi.org/xxxxx

### Accuracy rules for references
- Only cite papers, guidelines, or textbooks you are confident exist with the correct authors, title, journal, and year
- If you know a paper exists but are uncertain of a specific field (DOI, exact pages, issue number), include what you know and append `[verify]` to the uncertain field — e.g. `https://doi.org/[verify]`
- **Never invent or guess authors, titles, journal names, years, or DOIs** — a fabricated reference that reaches a clinician is a serious credibility risk
- If you cannot produce a real citation for a claim, replace the citation with: *"A PubMed search for [suggested MeSH terms] will identify the primary evidence for this point."*
- Prefer landmark trials, systematic reviews, and meta-analyses over single small studies
- Include TGA Product Information, PBAC Public Summary Documents, and TGA safety communications as references where applicable — these are publicly accessible documents

### What must be referenced
- Every efficacy figure (effect size, p-value, NNT, HbA1c reduction, etc.)
- Every AE frequency or severity grading
- Every contraindication or black-box warning
- Every drug interaction of clinical significance
- Every guideline recommendation cited
- Every regulatory decision (TGA approval, PBS listing, label change)

---

## Accuracy rules

- Never fabricate statistics, trial outcomes, doses, or regulatory decisions
- Flag uncertainty explicitly: "evidence suggests," "to my knowledge," "verify against current TGA PI"
- End any response containing specific clinical figures with: **Note: Verify all clinical data against the current approved Product Information and primary sources before use in medical affairs activities.**

---

## Scope

Clinical evidence, drug/product profiles, disease area science, MSL strategy, TGA/PBAC/MA Code, claim development, fair balance, pharmacovigilance, KOL engagement, scientific exchange. Internal medical affairs use only — not patient advice."""


def _call_claude(messages: list[dict]) -> str:
    """Call Claude with a list of {role, content} dicts. Returns assistant reply text."""
    import anthropic
    from django.conf import settings

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        temperature=0,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    )
    return response.content[0].text.strip()


@login_required
def search_home(request):
    sessions = AISearchSession.objects.filter(tenant=request.tenant).order_by("-updated_at")
    return render(request, "aisearch/search.html", {"sessions": sessions})


@login_required
def session_detail(request, session_pk):
    session = get_object_or_404(AISearchSession, pk=session_pk, tenant=request.tenant)
    messages = session.messages.order_by("created_at")
    sessions = AISearchSession.objects.filter(tenant=request.tenant).order_by("-updated_at")
    if request.headers.get("HX-Request"):
        return render(request, "aisearch/partials/session_panel.html", {
            "session": session,
            "messages": messages,
            "sessions": sessions,
        })
    return render(request, "aisearch/search.html", {
        "session": session,
        "messages": messages,
        "sessions": sessions,
    })


@login_required
def new_chat(request):
    return render(request, "aisearch/partials/new_chat.html")


@login_required
@require_POST
def ask(request, session_pk=None):
    question = request.POST.get("question", "").strip()
    if not question:
        return render(request, "aisearch/partials/ask_error.html",
                      {"error": "Please enter a question."})

    # Get or create session
    if session_pk:
        session = get_object_or_404(AISearchSession, pk=session_pk, tenant=request.tenant)
    else:
        session = AISearchSession.objects.create(
            tenant=request.tenant,
            created_by=request.user,
            title=question[:280],
        )
        log_action(request, session, AuditLog.Action.CREATE,
                   after={"title": session.title})

    # Save user message
    AISearchMessage.objects.create(session=session, role=AISearchMessage.Role.USER, content=question)

    # Build conversation history for Claude
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in session.messages.order_by("created_at")
    ]

    try:
        reply = _call_claude(history)
    except Exception as exc:
        logger.error("AI search failed for session %s: %s", session.pk, exc)
        AISearchMessage.objects.create(
            session=session,
            role=AISearchMessage.Role.ASSISTANT,
            content=f"Sorry, I encountered an error: {exc}",
        )
        reply = str(exc)

    # Save assistant message
    AISearchMessage.objects.create(
        session=session,
        role=AISearchMessage.Role.ASSISTANT,
        content=reply,
    )

    log_action(request, session, AuditLog.Action.UPDATE,
               after={"question": question[:200], "session": session.pk})

    messages = session.messages.order_by("created_at")
    sessions = AISearchSession.objects.filter(tenant=request.tenant).order_by("-updated_at")
    return render(request, "aisearch/partials/session_panel.html", {
        "session": session,
        "messages": messages,
        "sessions": sessions,
    })


@login_required
@require_POST
def delete_session(request, session_pk):
    session = get_object_or_404(AISearchSession, pk=session_pk, tenant=request.tenant)
    log_action(request, session, AuditLog.Action.DELETE,
               before={"title": session.title})
    session.delete()
    sessions = AISearchSession.objects.filter(tenant=request.tenant).order_by("-updated_at")
    return render(request, "aisearch/partials/session_list.html", {"sessions": sessions})
