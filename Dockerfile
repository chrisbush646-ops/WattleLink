FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system --gid 1001 django \
    && adduser --system --uid 1001 --gid 1001 django

# ---- dependencies ----
FROM base AS deps
COPY requirements/base.txt requirements/production.txt ./requirements/
RUN pip install -r requirements/production.txt

# ---- final ----
FROM base AS final
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .
RUN python manage.py collectstatic --noinput --settings=config.settings.production

USER django

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4"]
