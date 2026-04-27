# WattleLink v3

Literature-to-claims pipeline for pharmaceutical medical affairs teams.

## Local setup

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (for Postgres + Redis)
- Node.js 20+ (for Tailwind CSS compilation)

### 1. Clone and create virtualenv

```bash
cd wattlelink/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/development.txt
```

### 2. Environment variables

```bash
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD
```

### 3. Start backing services

```bash
docker compose up -d
```

Postgres will be available on `localhost:5432`, Redis on `localhost:6379`.

### 4. Run migrations

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Build Tailwind CSS

Install Tailwind CLI (one-time):

```bash
npm install -g tailwindcss
```

Build once:

```bash
tailwindcss -i static/css/input.css -o static/css/output.css
```

Watch mode (run alongside Django):

```bash
tailwindcss -i static/css/input.css -o static/css/output.css --watch
```

### 6. Start the development server

```bash
python manage.py runserver
```

App is at http://localhost:8000

### 7. Start Celery worker (optional)

```bash
celery -A config worker -l info
```

### 8. Run tests

```bash
pytest
```

## Project structure

See `CLAUDE.md` in the repository root for the full architecture reference.

## Key conventions

- Every model has a `tenant` FK — never query without tenant scoping.
- All models inherit from `SoftDeleteModel` — use `.soft_delete()` not `.delete()`.
- Audit trail is append-only — use `log_action()` from `apps.audit.helpers`.
- AI output is always labelled "AI draft" and requires human approval.
