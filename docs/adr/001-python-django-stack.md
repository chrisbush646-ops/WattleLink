# ADR 001 — Python/Django Stack

**Date:** 2026-04-27  
**Status:** Accepted

## Context

WattleLink v3 is a multi-tenant, workflow-heavy application for pharmaceutical medical affairs. It needs:

- Complex relational data (papers → assessments → summaries → claims → versions)
- Role-based access control with strict tenant isolation
- An immutable audit trail
- Background task processing (PubMed sync, PDF extraction, AI calls)
- Server-rendered UI with targeted interactivity (no full SPA needed)
- A path to Veeva PromoMats integration via API

## Decision: Django over Flask / FastAPI

**Chosen:** Django 5.x with Django REST Framework

**Why not Flask:**  
Flask is a micro-framework. We would need to bolt on: ORM, migrations, admin, auth, sessions, CSRF, permissions, form validation. Every piece is a separate dependency to evaluate, integrate, and maintain. Django ships all of this with coherent defaults and a 20-year battle-hardened track record. The admin panel alone is worth the choice — it gives us an internal data tool for free.

**Why not FastAPI:**  
FastAPI is excellent for pure API services. Our primary interface is server-rendered templates (Django + HTMX), not a JSON API consumed by a React SPA. FastAPI's async-first model adds complexity without benefit for our I/O pattern: most latency is in Anthropic API calls, which run in Celery tasks anyway, not in the request cycle. Django's ORM, migration system, and template engine are more productive for this shape of application.

**Django's specific advantages here:**
- `AbstractUser` lets us extend the user model cleanly on day one (tenant FK, role enum)
- Django's ORM with `Manager` subclassing is the right tool for tenant scoping
- Built-in `ContentTypes` framework makes the audit log's `entity_type` / `entity_id` pattern natural
- `django-allauth` gives email/password + social + eventual SAML SSO from one package
- Migrations are battle-tested for the kind of iterative schema evolution this project will have

## Decision: HTMX over React / Vue / SvelteKit

**Chosen:** Django templates + HTMX + Alpine.js

**Why not React (or Vue, Svelte):**  
A JavaScript SPA doubles the surface area: Django API layer, JavaScript build tooling, client state management, hydration, and a separate deployment artefact. For a workflow tool where every interaction round-trips to the database anyway (approve a claim → write to DB → refresh state), the SPA model provides no advantage and significant complexity cost.

HTMX lets us write interactivity as HTML attributes. The server sends HTML fragments; the browser swaps them in. This means:
- No JSON serialisation layer between views and templates
- The same Django view handles both full-page and partial (HTMX) requests via `request.htmx`
- Template rendering stays on the server where the data is
- The audit trail, tenant scoping, and permission checks happen in one place

Alpine.js handles purely client-side UI state (toggle open/closed, dropdown active, form validation feedback) without a build step or bundler.

**Trade-off accepted:** If WattleLink later needs a native mobile app or a third-party integration that consumes a JSON API, DRF is already installed and can serve it. HTMX and a JSON API are not mutually exclusive.

## Decision: Celery over alternatives

**Chosen:** Celery 5.x with Redis as broker and result backend

**Why not Django Q / Huey / django-rq:**  
All are good options. Celery was chosen because:
- It is the default answer in the Django ecosystem — hiring, documentation, Stack Overflow answers all assume it
- It handles the concurrency model we need: multiple worker types (I/O-bound AI calls, CPU-bound PDF extraction) via separate queues and worker pools
- `celery beat` gives us scheduled tasks (PubMed nightly sync) without a second scheduler service
- Redis doubles as the cache backend, so we avoid running a separate message broker

**Why not AWS SQS / RDS broker:**  
Adds operational complexity and AWS coupling at a stage where we're still validating the product. Redis on a single node (or ElastiCache for production) is sufficient. Can migrate broker later without changing task code.

**Why not async Django (asyncio tasks):**  
Django's async support is maturing but the ORM is still primarily synchronous. Mixing sync ORM calls in async views creates footguns. Celery with sync tasks is safer, more observable, and easier to debug.
