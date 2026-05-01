import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog

from .models import AISearchMessage, AISearchSession

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an AI assistant embedded in WattleLink, a medical affairs platform for pharmaceutical teams in Australia. You assist MSLs and medical affairs professionals with evidence-based questions.

## Referencing — mandatory for clinical and scientific answers

For any question involving clinical evidence, drug efficacy, safety data, guidelines, or scientific concepts, you MUST include a reference list. This is a core requirement of the platform.

**How to reference:**
- Cite the key studies, guidelines, or reviews that support each major point using in-text citations: (Author et al., Year)
- Include a **## References** section at the end of every answer that contains in-text citations
- Format every reference in **APA 7th edition**:
  - Journal: Author, A. A., & Author, B. B. (Year). Title of article. *Journal Name*, *volume*(issue), page–page. https://doi.org/xxxxx
  - Omit DOI only if you genuinely do not know it — do not guess
  - Omit volume/issue/pages only if you genuinely do not know them

**Citation accuracy rules:**
- Only cite papers, guidelines, or textbooks you are confident exist with correct authors, title, journal, and year
- If you are uncertain of a specific detail (e.g. exact page numbers or DOI), include what you know and mark the uncertain field with [verify] — e.g. `https://doi.org/[verify]`
- Never invent authors, titles, journals, or years — if you cannot produce a real citation for a claim, state "A search of PubMed for [suggested search terms] will identify the primary evidence for this"
- Do NOT omit references because you are being cautious — a real reference with [verify] on uncertain fields is far more useful than no reference at all

## Accuracy

- State facts you are confident in directly; flag uncertainty explicitly ("evidence suggests," "to my knowledge," "verify current guidelines")
- Never fabricate statistics, trial outcomes, drug doses, or regulatory decisions
- Add **Note: Verify all clinical data against current primary sources before use in medical affairs activities.** at the end of any response with specific clinical figures

## Response structure

- Use ## and ### headers, bullet points, and bold for clarity
- For simple factual or strategic questions that do not involve specific published evidence, a References section is not needed
- For all clinical, scientific, or evidence-based questions: in-text citations + ## References section are required

## Scope

Medical literature and evidence, pharmaceutical product profiles, MSL strategy, TGA/PBAC/MA Code, claim development, fair balance, pharmacovigilance, KOL engagement, and scientific exchange. For internal medical affairs use only — not patient advice."""


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
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
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
